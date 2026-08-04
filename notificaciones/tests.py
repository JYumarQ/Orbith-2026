"""Pruebas de `avisos.py`: deduplicación, resolución automática y bandeja de lectura.

Se aíslan de `subsanacion` con `unittest.mock.patch` sobre
`evaluar_reglas_de_instancia`: lo que se prueba aquí es la contabilidad de
`Notificacion` (deduplicar, resolver sin tocar `leido`, no reabrir un descarte), no la
detección de las reglas en sí (eso ya está cubierto en `subsanacion/tests.py` y
verificado contra datos reales). Como instancia «afectada» se usa `NProvincia`, el
mismo estándar sencillo que ya usa `subsanacion/tests.py::ReglaDePrueba`: aquí no
importa qué modelo sea, solo que exista de verdad para tener un `ContentType` y un
`object_id` válidos.

Se ejecutan con:

    python manage.py test notificaciones
"""

from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, Client
from django.urls import reverse

from nomencladores.models import NProvincia
from subsanacion.constantes import CRITICIDAD_BAJA, CRITICIDAD_MEDIA
from subsanacion.reglas.base import HallazgoDetectado

from .avisos import avisar_hallazgos_en_caliente
from .models import Notificacion


class _ReglaFalsa:
    """Doble de prueba: sustituye a una `Regla` real en el resultado de
    `evaluar_reglas_de_instancia`, sin necesidad de registrarla en el catálogo."""

    def __init__(self, codigo, criticidad):
        self.codigo = codigo
        self.criticidad = criticidad


class AvisarHallazgosEnCalienteTests(TestCase):

    def setUp(self):
        from usuarios.models import CustomUser

        self.usuario = CustomUser(username='usuario_prueba', is_active=True, es_observador=True)
        self.usuario.set_password('contraseña-de-prueba')
        self.usuario.save()

        self.provincia = NProvincia.objects.create(nombre='Provincia de prueba')
        self.regla = _ReglaFalsa('PRUEBA-012', CRITICIDAD_BAJA)

    def _resultado(self, clave_extra='', titulo='Falta un dato', detalle='Detalle'):
        hallazgo = HallazgoDetectado(
            object_id=str(self.provincia.pk), titulo=titulo, detalle=detalle,
            clave_extra=clave_extra)
        return [(self.regla, [hallazgo])]

    _SIN_PASAR = object()

    def _avisar(self, resultado, usuario=_SIN_PASAR, reglas=()):
        destinatario = self.usuario if usuario is self._SIN_PASAR else usuario
        with patch('notificaciones.avisos.evaluar_reglas_de_instancia', return_value=resultado), \
             patch('notificaciones.avisos.get_current_user', return_value=destinatario), \
             patch('notificaciones.avisos.obtener_reglas', return_value=list(reglas)):
            avisar_hallazgos_en_caliente(self.provincia)

    def test_crea_una_alerta_activa(self):
        self._avisar(self._resultado())

        notificacion = Notificacion.objects.get()
        self.assertEqual(notificacion.tipo, Notificacion.Tipo.ALERTA)
        self.assertEqual(notificacion.estado, Notificacion.Estado.ACTIVA)
        self.assertEqual(notificacion.severidad, CRITICIDAD_BAJA)
        self.assertEqual(notificacion.destinatario, self.usuario)
        self.assertFalse(notificacion.leido)

    def test_guardar_dos_veces_sin_corregir_no_duplica(self):
        self._avisar(self._resultado())
        self._avisar(self._resultado())

        self.assertEqual(Notificacion.objects.count(), 1)

    def test_sin_usuario_en_contexto_no_notifica_a_nadie(self):
        self._avisar(self._resultado(), usuario=None)

        self.assertEqual(Notificacion.objects.count(), 0)

    def test_corregir_el_campo_resuelve_sin_tocar_leido(self):
        self.regla.evaluable_en_caliente = True
        self.regla.modelo = 'nomencladores.nprovincia'

        self._avisar(self._resultado(), reglas=[self.regla])
        notificacion = Notificacion.objects.get()
        notificacion.leido = True
        notificacion.save(update_fields=['leido'])

        self._avisar([], reglas=[self.regla])  # ya no se detecta nada: el campo se corrigió

        notificacion.refresh_from_db()
        self.assertEqual(notificacion.estado, Notificacion.Estado.RESUELTA)
        self.assertIsNotNone(notificacion.fecha_resolucion)
        self.assertTrue(notificacion.leido)  # intacto: resolver no toca leido

    def test_descartada_no_se_reabre_sola(self):
        self.regla.evaluable_en_caliente = True
        self.regla.modelo = 'nomencladores.nprovincia'

        self._avisar(self._resultado(), reglas=[self.regla])
        notificacion = Notificacion.objects.get()
        notificacion.estado = Notificacion.Estado.DESCARTADA
        notificacion.save(update_fields=['estado'])

        self._avisar(self._resultado(), reglas=[self.regla])  # se detecta el mismo problema de nuevo

        notificacion.refresh_from_db()
        self.assertEqual(notificacion.estado, Notificacion.Estado.DESCARTADA)

    def test_dos_variantes_por_clave_extra_no_se_confunden(self):
        hallazgo_a = HallazgoDetectado(
            object_id=str(self.provincia.pk), titulo='A', clave_extra='variante_a')
        hallazgo_b = HallazgoDetectado(
            object_id=str(self.provincia.pk), titulo='B', clave_extra='variante_b')
        self._avisar([(self.regla, [hallazgo_a, hallazgo_b])])

        self.assertEqual(Notificacion.objects.count(), 2)
        claves = set(Notificacion.objects.values_list('clave_extra', flat=True))
        self.assertEqual(claves, {'variante_a', 'variante_b'})


class OrdenPorSeveridadTests(TestCase):
    """`Meta.ordering` debe primar la severidad sobre la fecha."""

    def setUp(self):
        self.provincia = NProvincia.objects.create(nombre='Provincia de prueba')
        self.tipo_ct = ContentType.objects.get_for_model(self.provincia)

    def test_una_critica_antigua_va_antes_que_una_baja_reciente(self):
        antigua = Notificacion.objects.create(
            titulo='Baja antigua', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            severidad=CRITICIDAD_BAJA, content_type=self.tipo_ct,
            object_id=str(self.provincia.pk))
        reciente = Notificacion.objects.create(
            titulo='Media reciente', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            severidad=CRITICIDAD_MEDIA, content_type=self.tipo_ct,
            object_id=str(self.provincia.pk))

        # CRITICIDAD_MEDIA (más grave, número más bajo) primero aunque sea más nueva.
        self.assertLess(CRITICIDAD_MEDIA, CRITICIDAD_BAJA)
        primero, segundo = list(Notificacion.objects.all())
        self.assertEqual(primero, reciente)
        self.assertEqual(segundo, antigua)


class MarcarLeidaTests(TestCase):

    def setUp(self):
        from usuarios.models import CustomUser

        self.usuario = CustomUser(username='usuario_bandeja', is_active=True, es_observador=True)
        self.usuario.set_password('contraseña-de-prueba')
        self.usuario.save()
        self.otro = CustomUser(username='otro_usuario', is_active=True, es_observador=True)
        self.otro.set_password('contraseña-de-prueba')
        self.otro.save()

        provincia = NProvincia.objects.create(nombre='Provincia de prueba')
        self.notificacion = Notificacion.objects.create(
            titulo='Aviso', mensaje='...', tipo=Notificacion.Tipo.EVENTO,
            content_type=ContentType.objects.get_for_model(provincia),
            object_id=str(provincia.pk), destinatario=self.usuario)

        self.client = Client()
        self.client.force_login(self.usuario)

    def test_marcar_leida_no_toca_estado(self):
        url = reverse('notificacion_marcar_leida', args=[self.notificacion.pk])
        respuesta = self.client.post(url)

        self.assertEqual(respuesta.status_code, 200)
        self.notificacion.refresh_from_db()
        self.assertTrue(self.notificacion.leido)
        self.assertEqual(self.notificacion.estado, Notificacion.Estado.ACTIVA)

    def test_no_puede_marcar_la_de_otro_usuario(self):
        self.client.force_login(self.otro)
        url = reverse('notificacion_marcar_leida', args=[self.notificacion.pk])
        respuesta = self.client.post(url)

        self.assertEqual(respuesta.status_code, 404)
        self.notificacion.refresh_from_db()
        self.assertFalse(self.notificacion.leido)

    def test_marcar_todas_leidas(self):
        provincia = NProvincia.objects.create(nombre='Otra provincia')
        Notificacion.objects.create(
            titulo='Aviso 2', mensaje='...', tipo=Notificacion.Tipo.EVENTO,
            content_type=ContentType.objects.get_for_model(provincia),
            object_id=str(provincia.pk), destinatario=self.usuario)

        url = reverse('notificaciones_marcar_todas_leidas')
        respuesta = self.client.post(url)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            Notificacion.objects.filter(destinatario=self.usuario, leido=False).count(), 0)
