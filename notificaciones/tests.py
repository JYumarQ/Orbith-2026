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
from .escaneo import escanear_globalmente_y_notificar_por_unidad, escanear_para_usuario
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


class _ReglaFalsaDeEscaneo:
    """Doble de prueba para `evaluar_reglas_en_caliente()`: expone `obtener_modelo()`
    (necesario para resolver el `ContentType`) además de `codigo`/`criticidad`."""

    def __init__(self, codigo, criticidad, modelo=NProvincia):
        self.codigo = codigo
        self.criticidad = criticidad
        self.evaluable_en_caliente = True
        self._modelo = modelo

    def obtener_modelo(self):
        return self._modelo


class EscaneoTests(TestCase):
    """`notificaciones/escaneo.py`: la contabilidad del escaneo manual y automático.

    Se aísla de la detección real con `patch` sobre `evaluar_reglas_en_caliente` —
    igual que `AvisarHallazgosEnCalienteTests` se aísla de `evaluar_reglas_de_instancia`
    — porque lo que se prueba aquí es el reparto por alcance/destinatario, no si una
    regla concreta detecta bien un campo vacío (eso ya está en `subsanacion/tests.py`).
    """

    def setUp(self):
        from strorganizativa.models import UnidadOrganizativa
        from usuarios.models import CustomUser
        from nomencladores.models import NTipoUnidadOrganizativa

        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='Tipo de prueba')
        self.unidad_a = UnidadOrganizativa.objects.create(
            codigo_interno=1, descripcion='Unidad A', tipo=tipo, grupo_nomina=1)
        self.unidad_b = UnidadOrganizativa.objects.create(
            codigo_interno=2, descripcion='Unidad B', tipo=tipo, grupo_nomina=1)

        self.moderador_a = CustomUser(
            username='moderador_a', is_active=True, es_moderador=True)
        self.moderador_a.set_password('contraseña-de-prueba')
        self.moderador_a.save()
        self.moderador_a.unidades.add(self.unidad_a)

        self.moderador_sin_unidades = CustomUser(
            username='moderador_sin_unidades', is_active=True, es_moderador=True)
        self.moderador_sin_unidades.set_password('contraseña-de-prueba')
        self.moderador_sin_unidades.save()

        self.admin = CustomUser(username='admin_prueba', is_active=True, es_admin=True)
        self.admin.set_password('contraseña-de-prueba')
        self.admin.save()

        self.provincia = NProvincia.objects.create(nombre='Provincia de prueba')
        self.regla = _ReglaFalsaDeEscaneo('ESCANEO-001', CRITICIDAD_BAJA)

    def _resultados(self, unidad_organizativa_id, clave_extra=''):
        hallazgo = HallazgoDetectado(
            object_id=str(self.provincia.pk), titulo='Falta un dato',
            clave_extra=clave_extra, unidad_organizativa_id=unidad_organizativa_id)
        return [(self.regla, [hallazgo])]

    def test_moderador_sin_unidades_no_notifica_nada(self):
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(self.unidad_a.pk)):
            total = escanear_para_usuario(self.moderador_sin_unidades)

        self.assertEqual(total, 0)
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_moderador_solo_ve_su_propia_unidad(self):
        resultados = self.regla, [
            HallazgoDetectado(object_id=str(self.provincia.pk), titulo='En A',
                               clave_extra='a', unidad_organizativa_id=self.unidad_a.pk),
            HallazgoDetectado(object_id=str(self.provincia.pk), titulo='En B',
                               clave_extra='b', unidad_organizativa_id=self.unidad_b.pk),
        ]
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=[resultados]):
            total = escanear_para_usuario(self.moderador_a)

        self.assertEqual(total, 1)
        notificacion = Notificacion.objects.get()
        self.assertEqual(notificacion.clave_extra, 'a')
        self.assertEqual(notificacion.destinatario, self.moderador_a)

    def test_admin_recibe_hallazgos_sin_unidad(self):
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(None)):
            total = escanear_para_usuario(self.admin)

        self.assertEqual(total, 1)
        self.assertEqual(Notificacion.objects.get().destinatario, self.admin)

    def test_escanear_dos_veces_no_duplica(self):
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(self.unidad_a.pk)):
            escanear_para_usuario(self.moderador_a)
            escanear_para_usuario(self.moderador_a)

        self.assertEqual(Notificacion.objects.count(), 1)

    def test_hallazgo_corregido_se_resuelve_sin_tocar_leido(self):
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(self.unidad_a.pk)):
            escanear_para_usuario(self.moderador_a)

        notificacion = Notificacion.objects.get()
        notificacion.leido = True
        notificacion.save(update_fields=['leido'])

        # Aunque la regla ya no detecte NADA en ninguna parte (resultados_globales
        # queda vacío), sus notificaciones activas deben poder resolverse: por eso
        # `obtener_reglas()` también se parchea aquí, para que la regla siga
        # contando como «evaluada» aunque no haya encontrado ningún hallazgo.
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente', return_value=[]), \
             patch('notificaciones.escaneo.obtener_reglas', return_value=[self.regla]):
            escanear_para_usuario(self.moderador_a)

        notificacion.refresh_from_db()
        self.assertEqual(notificacion.estado, Notificacion.Estado.RESUELTA)
        self.assertTrue(notificacion.leido)

    def test_escaneo_automatico_reparte_por_unidad(self):
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(self.unidad_a.pk)):
            resumen = escanear_globalmente_y_notificar_por_unidad()

        self.assertEqual(resumen['sin_unidad'], 0)
        # Destinatarios de unidad_a: el moderador de esa unidad + todos los admins.
        destinatarios = set(
            Notificacion.objects.values_list('destinatario__username', flat=True))
        self.assertEqual(destinatarios, {'moderador_a', 'admin_prueba'})

    def test_escaneo_automatico_sin_unidad_va_a_todos_los_admins(self):
        otro_admin = self.admin.__class__(
            username='otro_admin', is_active=True, es_admin=True)
        otro_admin.set_password('contraseña-de-prueba')
        otro_admin.save()

        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(None)):
            resumen = escanear_globalmente_y_notificar_por_unidad()

        self.assertEqual(resumen['sin_unidad'], 1)
        destinatarios = set(
            Notificacion.objects.values_list('destinatario__username', flat=True))
        self.assertEqual(destinatarios, {'admin_prueba', 'otro_admin'})

    def test_escaneo_automatico_dos_veces_no_duplica(self):
        with patch('notificaciones.escaneo.evaluar_reglas_en_caliente',
                   return_value=self._resultados(self.unidad_a.pk)):
            escanear_globalmente_y_notificar_por_unidad()
            total_tras_primera = Notificacion.objects.count()
            escanear_globalmente_y_notificar_por_unidad()

        self.assertEqual(Notificacion.objects.count(), total_tras_primera)


class CoreMixinsTests(TestCase):
    """`core.mixins` no vive en una app con tests propios: `core/` es la configuración
    del proyecto (settings, urls), no está en `INSTALLED_APPS` y no tiene modelos —
    `manage.py test core` ni siquiera lo descubriría. Se prueba aquí porque esta ronda
    de Notificaciones (el problema de "el formulario se abre sin estilos" / "no vuelve
    al origen") fue la que motivó su creación.
    """

    def _vista(self, request, **atributos):
        from django.views.generic import View

        from core.mixins import ModalOPaginaCompletaMixin, VolverAlOrigenMixin

        class VistaDePrueba(ModalOPaginaCompletaMixin, VolverAlOrigenMixin, View):
            template_name = 'fragmento.html'
            template_name_pagina = 'pagina.html'
            url_por_defecto = '/listado/'

        vista = VistaDePrueba()
        vista.request = request
        for clave, valor in atributos.items():
            setattr(vista, clave, valor)
        return vista

    def test_peticion_normal_usa_la_pagina_completa(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/editar/1/')
        self.assertEqual(self._vista(request).get_template_names(), ['pagina.html'])

    def test_peticion_ajax_usa_el_fragmento(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/editar/1/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(self._vista(request).get_template_names(), ['fragmento.html'])

    def test_peticion_htmx_usa_el_fragmento(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/editar/1/', HTTP_HX_REQUEST='true')
        self.assertEqual(self._vista(request).get_template_names(), ['fragmento.html'])

    def test_next_por_get_tiene_prioridad_sobre_url_por_defecto(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/editar/1/', {'next': '/notificaciones/lista/?tab=advertencias'})
        self.assertEqual(
            self._vista(request).get_success_url(), '/notificaciones/lista/?tab=advertencias')

    def test_next_por_post_tiene_prioridad_sobre_next_por_get(self):
        from django.test import RequestFactory

        request = RequestFactory().post('/editar/1/?next=/uno/', {'next': '/dos/'})
        self.assertEqual(self._vista(request).get_success_url(), '/dos/')

    def test_sin_next_devuelve_la_url_por_defecto(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/editar/1/')
        self.assertEqual(self._vista(request).get_success_url(), '/listado/')


class FiltrosAdvertenciasTests(TestCase):
    """`notificaciones/filtros.py::filtrar_advertencias`, sobre datos reales del
    catálogo de reglas (no un doble): así se prueba también que la resolución
    Módulo -> códigos de regla usa el registro de verdad, no uno inventado."""

    def setUp(self):
        from strorganizativa.models import UnidadOrganizativa
        from usuarios.models import CustomUser
        from nomencladores.models import NTipoUnidadOrganizativa

        self.usuario = CustomUser(username='usuario_filtros', is_active=True, es_admin=True)
        self.usuario.set_password('contraseña-de-prueba')
        self.usuario.save()

        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='Tipo filtros')
        self.unidad = UnidadOrganizativa.objects.create(
            codigo_interno=99, descripcion='Unidad de prueba', tipo=tipo, grupo_nomina=1)

        provincia = NProvincia.objects.create(nombre='Provincia filtros')
        self.tipo_ct = ContentType.objects.get_for_model(provincia)

        # CTR-012 es una regla real y registrada (módulo Contratos, criticidad Baja);
        # se reutiliza para que el filtro de Módulo tenga algo real que resolver.
        self.alerta = Notificacion.objects.create(
            titulo='Funcionario sin código', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            codigo_regla='CTR-012', severidad=CRITICIDAD_BAJA,
            estado=Notificacion.Estado.ACTIVA, unidad=self.unidad,
            content_type=self.tipo_ct, object_id=str(provincia.pk),
            destinatario=self.usuario)

        # Una segunda alerta de otra regla/severidad, para confirmar que los filtros
        # SÍ excluyen lo que no corresponde, no solo que no rompen nada. Misma
        # subpestaña (ACTIVA) que `self.alerta`: la partición por subpestaña
        # (activas/resueltas/descartadas) es un eje aparte, cubierto por los tests de
        # subpestañas más abajo, no por estos.
        self.otra = Notificacion.objects.create(
            titulo='Chófer sin fechas', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            codigo_regla='CTR-013', severidad=CRITICIDAD_MEDIA,
            estado=Notificacion.Estado.ACTIVA,
            content_type=self.tipo_ct, object_id=str(provincia.pk),
            destinatario=self.usuario)

        # Una RESUELTA y una DESCARTADA, para los tests de subpestañas: deben quedar
        # FUERA de la subpestaña por defecto (activas) y aparecer solo en la suya.
        self.resuelta = Notificacion.objects.create(
            titulo='Nivel educativo vacío', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            codigo_regla='ASP-007', severidad=CRITICIDAD_BAJA,
            estado=Notificacion.Estado.RESUELTA,
            content_type=self.tipo_ct, object_id=str(provincia.pk),
            destinatario=self.usuario)
        self.descartada = Notificacion.objects.create(
            titulo='Móvil personal vacío', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            codigo_regla='ASP-005', severidad=CRITICIDAD_BAJA,
            estado=Notificacion.Estado.DESCARTADA,
            content_type=self.tipo_ct, object_id=str(provincia.pk),
            destinatario=self.usuario)

    def _filtrar(self, **parametros):
        from django.test import RequestFactory

        from .filtros import filtrar_advertencias

        request = RequestFactory().get('/', parametros)
        request.user = self.usuario
        return filtrar_advertencias(request, self.usuario)

    def test_sin_filtros_devuelve_las_activas_del_usuario(self):
        """Sin `sub`, la subpestaña por defecto es «activas»: no mezcla con
        resueltas/descartadas (decisión explícita, ver `SUBTABS_ADVERTENCIAS`)."""
        consulta, filtros = self._filtrar()
        self.assertEqual(set(consulta), {self.alerta, self.otra})
        self.assertFalse(filtros['hay_filtros'])

    def test_filtro_por_regla(self):
        consulta, filtros = self._filtrar(regla='CTR-012')
        self.assertEqual(list(consulta), [self.alerta])
        self.assertTrue(filtros['hay_filtros'])

    def test_filtro_por_severidad(self):
        consulta, _ = self._filtrar(severidad=str(CRITICIDAD_MEDIA))
        self.assertEqual(list(consulta), [self.otra])

    def test_subpestana_resueltas_devuelve_solo_las_resueltas(self):
        consulta, filtros = self._filtrar(sub='resueltas')
        self.assertEqual(list(consulta), [self.resuelta])
        self.assertEqual(filtros['sub_activa'], 'resueltas')

    def test_subpestana_descartadas_devuelve_solo_las_descartadas(self):
        consulta, filtros = self._filtrar(sub='descartadas')
        self.assertEqual(list(consulta), [self.descartada])
        self.assertEqual(filtros['sub_activa'], 'descartadas')

    def test_subpestana_invalida_cae_a_activas(self):
        consulta, filtros = self._filtrar(sub='no-existe')
        self.assertEqual(set(consulta), {self.alerta, self.otra})
        self.assertEqual(filtros['sub_activa'], 'activas')

    def test_filtro_por_unidad(self):
        consulta, _ = self._filtrar(unidad=str(self.unidad.pk))
        self.assertEqual(list(consulta), [self.alerta])

    def test_filtro_por_modelo_afectado(self):
        consulta, _ = self._filtrar(modelo=str(self.tipo_ct.pk))
        self.assertEqual(set(consulta), {self.alerta, self.otra})

    def test_filtro_por_modulo_resuelve_via_catalogo_de_reglas(self):
        from subsanacion.constantes import MODULO_CONTRATOS

        consulta, _ = self._filtrar(modulo=MODULO_CONTRATOS)
        # CTR-012 Y CTR-013 son ambas del módulo Contratos: el filtro por módulo no
        # discrimina entre ellas, solo entre módulos distintos.
        self.assertEqual(set(consulta), {self.alerta, self.otra})

    def test_filtro_por_destinatario_solo_para_admin(self):
        otro_admin = self.usuario.__class__(
            username='otro_admin_filtros', is_active=True, es_admin=True)
        otro_admin.set_password('contraseña-de-prueba')
        otro_admin.save()

        # Pide filtrar por un destinatario que no es self.usuario: como quien filtra
        # SÍ es admin, el filtro se aplica de verdad y no debe devolver nada (ninguna
        # notificación es de otro_admin).
        consulta, _ = self._filtrar(destinatario=str(otro_admin.pk))
        self.assertEqual(list(consulta), [])

    def test_filtro_invalido_se_descarta_en_silencio(self):
        consulta, filtros = self._filtrar(severidad='no-es-un-numero')
        self.assertEqual(set(consulta), {self.alerta, self.otra})
        self.assertFalse(filtros['hay_filtros'])


class VisibilidadAdminTests(TestCase):
    """`_notificaciones_visibles()`: un admin ve TODO, sin importar unidad ni
    destinatario — un moderador (o un admin de mentira que no lo sea) sigue acotado."""

    def setUp(self):
        from strorganizativa.models import UnidadOrganizativa
        from usuarios.models import CustomUser
        from nomencladores.models import NTipoUnidadOrganizativa

        self.admin = CustomUser(username='admin_visibilidad', is_active=True, es_admin=True)
        self.admin.set_password('contraseña-de-prueba')
        self.admin.save()

        self.moderador = CustomUser(
            username='moderador_visibilidad', is_active=True, es_moderador=True)
        self.moderador.set_password('contraseña-de-prueba')
        self.moderador.save()

        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='Tipo visibilidad')
        unidad_ajena = UnidadOrganizativa.objects.create(
            codigo_interno=199, descripcion='Unidad ajena', tipo=tipo, grupo_nomina=1)

        provincia = NProvincia.objects.create(nombre='Provincia visibilidad')
        tipo_ct = ContentType.objects.get_for_model(provincia)

        # Ni de la unidad del moderador, ni dirigida a nadie en particular de este test.
        self.notificacion_ajena = Notificacion.objects.create(
            titulo='Ajena', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            estado=Notificacion.Estado.ACTIVA, unidad=unidad_ajena,
            content_type=tipo_ct, object_id=str(provincia.pk))

    def test_admin_ve_notificaciones_fuera_de_su_unidad(self):
        from .views import _notificaciones_visibles

        self.assertIn(self.notificacion_ajena, _notificaciones_visibles(self.admin))

    def test_moderador_no_ve_notificaciones_fuera_de_su_unidad(self):
        from .views import _notificaciones_visibles

        self.assertNotIn(self.notificacion_ajena, _notificaciones_visibles(self.moderador))


class DescartarYReactivarAdvertenciaTests(TestCase):
    """Vistas `descartar_advertencia`/`reactivar_advertencia`: actúan sobre TODAS las
    notificaciones del mismo hallazgo (misma clave natural, todos los destinatarios),
    no solo la fila `pk` recibida — porque el listado las deduplica por destinatario."""

    def setUp(self):
        from usuarios.models import CustomUser

        self.admin = CustomUser(username='admin_descartes', is_active=True, es_admin=True)
        self.admin.set_password('contraseña-de-prueba')
        self.admin.save()

        self.moderador = CustomUser(
            username='moderador_descartes', is_active=True, es_moderador=True)
        self.moderador.set_password('contraseña-de-prueba')
        self.moderador.save()

        provincia = NProvincia.objects.create(nombre='Provincia descartes')
        tipo_ct = ContentType.objects.get_for_model(provincia)

        # Mismo hallazgo (misma clave natural), dos destinatarios distintos.
        self.propia = Notificacion.objects.create(
            titulo='Hallazgo', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            codigo_regla='ASP-005', estado=Notificacion.Estado.ACTIVA,
            content_type=tipo_ct, object_id=str(provincia.pk), destinatario=self.admin)
        self.otro_destinatario = Notificacion.objects.create(
            titulo='Hallazgo', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            codigo_regla='ASP-005', estado=Notificacion.Estado.ACTIVA,
            content_type=tipo_ct, object_id=str(provincia.pk), destinatario=self.moderador)

    def test_moderador_no_puede_descartar(self):
        cliente = Client()
        cliente.force_login(self.moderador)
        respuesta = cliente.post(reverse('descartar_advertencia', args=[self.propia.pk]))
        self.assertEqual(respuesta.status_code, 403)
        self.propia.refresh_from_db()
        self.assertEqual(self.propia.estado, Notificacion.Estado.ACTIVA)

    def test_admin_descarta_todo_el_grupo(self):
        cliente = Client()
        cliente.force_login(self.admin)
        respuesta = cliente.post(reverse('descartar_advertencia', args=[self.propia.pk]))
        self.assertEqual(respuesta.status_code, 302)

        self.propia.refresh_from_db()
        self.otro_destinatario.refresh_from_db()
        self.assertEqual(self.propia.estado, Notificacion.Estado.DESCARTADA)
        self.assertEqual(self.otro_destinatario.estado, Notificacion.Estado.DESCARTADA)
        self.assertIsNotNone(self.propia.fecha_resolucion)

    def test_admin_reactiva_todo_el_grupo(self):
        Notificacion.objects.filter(pk__in=[self.propia.pk, self.otro_destinatario.pk]).update(
            estado=Notificacion.Estado.DESCARTADA)

        cliente = Client()
        cliente.force_login(self.admin)
        respuesta = cliente.post(reverse('reactivar_advertencia', args=[self.propia.pk]))
        self.assertEqual(respuesta.status_code, 302)

        self.propia.refresh_from_db()
        self.otro_destinatario.refresh_from_db()
        self.assertEqual(self.propia.estado, Notificacion.Estado.ACTIVA)
        self.assertEqual(self.otro_destinatario.estado, Notificacion.Estado.ACTIVA)
        self.assertIsNone(self.propia.fecha_resolucion)

    def test_no_se_puede_reactivar_una_resuelta(self):
        self.propia.estado = Notificacion.Estado.RESUELTA
        self.propia.save(update_fields=['estado'])

        cliente = Client()
        cliente.force_login(self.admin)
        respuesta = cliente.post(reverse('reactivar_advertencia', args=[self.propia.pk]))
        self.assertEqual(respuesta.status_code, 404)


class FiltrosRecordatoriosTests(TestCase):
    """`notificaciones/filtros.py::filtrar_recordatorios`: búsqueda libre y filtro de
    prioridad, sobre datos reales de un solo `origen` (nunca mezcla Sistema/Administración,
    eso ya lo decide `_contexto_tab_recordatorios`/`panel_recordatorios` antes de llamar)."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone
        from usuarios.models import CustomUser

        self.usuario = CustomUser(username='usuario_recordatorios', is_active=True, es_admin=True)
        self.usuario.set_password('contraseña-de-prueba')
        self.usuario.save()

        provincia = NProvincia.objects.create(nombre='Provincia recordatorios')
        tipo_ct = ContentType.objects.get_for_model(provincia)
        hoy = timezone.localdate()

        self.lejano = Notificacion.objects.create(
            titulo='Cumpleaños de Ana', mensaje='...', tipo=Notificacion.Tipo.RECORDATORIO,
            origen=Notificacion.Origen.SISTEMA, codigo_regla='REC-CUMPLE',
            estado=Notificacion.Estado.ACTIVA, fecha_objetivo=hoy + timedelta(days=90),
            content_type=tipo_ct, object_id=str(provincia.pk), destinatario=self.usuario)
        self.vencido = Notificacion.objects.create(
            titulo='Contrato de Luis por vencer', mensaje='...', tipo=Notificacion.Tipo.RECORDATORIO,
            origen=Notificacion.Origen.SISTEMA, codigo_regla='REC-CONTRATO',
            estado=Notificacion.Estado.ACTIVA, fecha_objetivo=hoy - timedelta(days=1),
            content_type=tipo_ct, object_id=str(provincia.pk), destinatario=self.usuario)
        # Mismo origen SISTEMA pero RESUELTA: nunca debe aparecer (la bandeja de
        # Recordatorios, igual que Advertencias, solo muestra lo vigente).
        Notificacion.objects.create(
            titulo='Ya resuelto', mensaje='...', tipo=Notificacion.Tipo.RECORDATORIO,
            origen=Notificacion.Origen.SISTEMA, codigo_regla='REC-CUMPLE',
            estado=Notificacion.Estado.RESUELTA, fecha_objetivo=hoy,
            content_type=tipo_ct, object_id=str(provincia.pk), destinatario=self.usuario)
        # Mismo origen y estado, pero ADMINISTRACION: no debe mezclarse con SISTEMA.
        Notificacion.objects.create(
            titulo='Revisar expediente', mensaje='...', tipo=Notificacion.Tipo.RECORDATORIO,
            origen=Notificacion.Origen.ADMINISTRACION,
            estado=Notificacion.Estado.ACTIVA, fecha_objetivo=hoy,
            content_type=tipo_ct, object_id=str(provincia.pk), destinatario=self.usuario)

    def _filtrar(self, **parametros):
        from django.test import RequestFactory

        from .filtros import filtrar_recordatorios

        request = RequestFactory().get('/', parametros)
        request.user = self.usuario
        return filtrar_recordatorios(request, self.usuario, Notificacion.Origen.SISTEMA)

    def test_sin_filtros_devuelve_solo_activas_del_origen_pedido(self):
        consulta, filtros = self._filtrar()
        self.assertEqual(set(consulta), {self.lejano, self.vencido})
        self.assertFalse(filtros['hay_filtros'])

    def test_busqueda_libre_filtra_por_titulo(self):
        consulta, filtros = self._filtrar(q='Luis')
        self.assertEqual(list(consulta), [self.vencido])
        self.assertTrue(filtros['hay_filtros'])

    def test_filtro_de_prioridad_rojo_solo_vencidos(self):
        consulta, filtros = self._filtrar(prioridad='rojo')
        self.assertEqual(list(consulta), [self.vencido])
        self.assertEqual(filtros['prioridad_actual'], 'rojo')

    def test_filtro_de_prioridad_verde_solo_lejanos(self):
        consulta, _ = self._filtrar(prioridad='verde')
        self.assertEqual(list(consulta), [self.lejano])

    def test_prioridad_invalida_se_ignora(self):
        consulta, filtros = self._filtrar(prioridad='no-existe')
        self.assertEqual(set(consulta), {self.lejano, self.vencido})
        self.assertFalse(filtros['hay_filtros'])


class ReclasificarCriticasMigrationTests(TestCase):
    """Migración de datos `0006_reclasificar_criticas`: las notificaciones históricas
    de `avisar_criticas_nuevas` (apuntan a `EjecucionAnalisis`, sin `tipo` fijado
    explícitamente antes de esta ronda) deben pasar de EVENTO a ALERTA.

    Se invoca la función de la migración directamente (con el registro de apps real,
    vía `django.apps.apps`) en vez de usar el framework de pruebas de migraciones de
    Django: esta migración no cambia esquema, solo datos, así que no hace falta
    reconstruir un estado histórico — el modelo de hoy es idéntico al que la migración
    manipula.
    """

    def _reclasificar(self):
        import importlib

        from django.apps import apps

        modulo = importlib.import_module('notificaciones.migrations.0006_reclasificar_criticas')
        modulo.reclasificar_a_alerta(apps, None)

    def test_reclasifica_solo_las_que_apuntan_a_ejecucionanalisis(self):
        from subsanacion.models import EjecucionAnalisis

        provincia = NProvincia.objects.create(nombre='Provincia migración')
        ejecucion = EjecucionAnalisis.objects.create(estado=EjecucionAnalisis.COMPLETA)

        de_critica = Notificacion.objects.create(
            titulo='3 críticas nuevas', mensaje='...', tipo=Notificacion.Tipo.EVENTO,
            content_type=ContentType.objects.get_for_model(ejecucion), object_id=str(ejecucion.pk))
        de_otro_evento = Notificacion.objects.create(
            titulo='Nuevo Cargo creado', mensaje='...', tipo=Notificacion.Tipo.EVENTO,
            content_type=ContentType.objects.get_for_model(provincia), object_id=str(provincia.pk))

        self._reclasificar()

        de_critica.refresh_from_db()
        de_otro_evento.refresh_from_db()
        self.assertEqual(de_critica.tipo, Notificacion.Tipo.ALERTA)
        self.assertEqual(de_otro_evento.tipo, Notificacion.Tipo.EVENTO)  # sin tocar

    def test_no_falla_si_nunca_hubo_ninguna_ejecucion(self):
        self._reclasificar()  # no debe lanzar, aunque no exista ningún EjecucionAnalisis
