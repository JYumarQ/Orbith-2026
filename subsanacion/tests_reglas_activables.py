"""Reglas activables por el Administrador (25-10-2026): una regla desactivada no se
ejecuta, sus avisos abiertos siguen normales, «Probar ahora» no crea avisos, y lo
pueden hacer el Administrador y el Moderador con el permiso especial de Subsanación."""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import CustomUser, PerfilPermisos

from .constantes import CLAVES_MODULOS, CRITICIDAD_ALTA, MODULO_ESTRUCTURA
from .models import EjecucionAnalisis, EstadoRegla, Hallazgo
from .reglas import codigos_desactivados, obtener_reglas

REGLA = 'EST-011'


class ReglasActivablesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username='adm_reglas', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(username='mod_reglas', password='x', es_moderador=True)

    def desactivar(self):
        EstadoRegla.objects.update_or_create(codigo=REGLA, defaults={'activa': False})

    def test_una_desactivada_no_se_ejecuta_pero_se_puede_listar(self):
        self.assertIn(REGLA, [r.codigo for r in obtener_reglas()])
        self.desactivar()
        self.assertIn(REGLA, codigos_desactivados())   # junto a las de Pre-Nómina (3.9.0)
        self.assertNotIn(REGLA, [r.codigo for r in obtener_reglas()])
        self.assertIn(REGLA, [r.codigo for r in obtener_reglas(solo_activas=False)])

    def test_sus_avisos_abiertos_no_se_archivan(self):
        from .servicios import archivar_hallazgos_de_reglas_retiradas
        aviso = Hallazgo.objects.create(
            codigo_regla=REGLA, content_type=ContentType.objects.get_for_model(CustomUser),
            object_id='1', modulo=MODULO_ESTRUCTURA, criticidad=CRITICIDAD_ALTA, titulo='x',
            ultima_deteccion=timezone.now(), estado=Hallazgo.PENDIENTE)
        self.desactivar()
        ejecucion = EjecucionAnalisis.objects.create(
            modulos_solicitados=list(CLAVES_MODULOS), modulos_completados=list(CLAVES_MODULOS))
        self.assertEqual(archivar_hallazgos_de_reglas_retiradas(ejecucion), 0)
        aviso.refresh_from_db()
        self.assertTrue(aviso.vigente)

    def test_el_admin_la_desactiva_y_queda_en_auditoria(self):
        from auditoria.models import EventoAuditoria
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('subsanacion:estado_regla', args=[REGLA]),
                                     {'activa': '0', 'motivo': 'Ya está limpia'})
        self.assertEqual(respuesta.status_code, 200)
        estado = EstadoRegla.objects.get(codigo=REGLA)
        self.assertEqual((estado.activa, estado.motivo, estado.cambiado_por), (False, 'Ya está limpia', self.admin))
        self.assertTrue(EventoAuditoria.objects.filter(descriptor__contains=REGLA).exists())
        self.client.post(reverse('subsanacion:estado_regla', args=[REGLA]), {'activa': '1'})
        self.assertTrue(EstadoRegla.objects.get(codigo=REGLA).activa)

    def test_moderador_solo_con_el_permiso_especial(self):
        url = reverse('subsanacion:estado_regla', args=[REGLA])
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.post(url, {'activa': '0'}).status_code, 403)
        perfil = PerfilPermisos.objects.create(nombre='Subsanación', subsanacion=True)
        CustomUser.objects.filter(pk=self.moderador.pk).update(perfil_permisos=perfil)
        self.assertEqual(self.client.post(url, {'activa': '0'}).status_code, 200)
        from auditoria.models import EventoAuditoria
        evento = EventoAuditoria.objects.filter(descriptor__contains=REGLA).latest('pk')
        self.assertEqual(evento.permiso_especial, 'Subsanación como administrador')

    def test_probar_ahora_no_crea_avisos(self):
        self.client.force_login(self.admin)
        antes = Hallazgo.objects.count()
        respuesta = self.client.post(reverse('subsanacion:probar_regla', args=[REGLA]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No se creó ningún aviso')
        self.assertEqual(Hallazgo.objects.count(), antes)

    def test_el_analisis_anota_tiempo_y_ultimo_fallo(self):
        from .servicios import anotar_ejecucion_de_regla
        anotar_ejecucion_de_regla(REGLA, 120, 0)
        estado = EstadoRegla.objects.get(codigo=REGLA)
        self.assertEqual((estado.ultima_duracion_ms, estado.ultimo_fallo, estado.activa), (120, None, True))
        anotar_ejecucion_de_regla(REGLA, 90, 3)
        self.assertIsNotNone(EstadoRegla.objects.get(codigo=REGLA).ultimo_fallo)


class DesactivarOcultaLosAvisosTests(TestCase):
    """3.9.0 (09-11-2026, RRHH): al desactivar una regla sus avisos dejan de verse en
    todas partes, sin borrarse; al reactivarla vuelven con su estado."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username='adm_ocultar', password='x', es_admin=True)

    def aviso(self, estado=Hallazgo.EN_REVISION):
        return Hallazgo.objects.create(
            codigo_regla=REGLA, content_type=ContentType.objects.get_for_model(CustomUser),
            object_id='1', modulo=MODULO_ESTRUCTURA, criticidad=CRITICIDAD_ALTA, titulo='x',
            ultima_deteccion=timezone.now(), estado=estado)

    def test_desactivar_oculta_sin_perder_el_estado_y_reactivar_lo_devuelve(self):
        from notificaciones.models import Notificacion
        aviso = self.aviso()
        Notificacion.objects.create(
            titulo='x', mensaje='x', tipo=Notificacion.Tipo.ALERTA, codigo_regla=REGLA,
            content_type=aviso.content_type, object_id='1', destinatario=self.admin)
        self.client.force_login(self.admin)
        url = reverse('subsanacion:estado_regla', args=[REGLA])

        self.client.post(url, {'activa': '0'})
        aviso.refresh_from_db()
        self.assertEqual((aviso.vigente, aviso.estado), (False, Hallazgo.EN_REVISION))
        self.assertFalse(Notificacion.objects.filter(codigo_regla=REGLA).exists())
        lista = self.client.get(reverse('subsanacion:panel_hallazgos') + '?archivados=on',
                                HTTP_HX_REQUEST='true')
        self.assertNotContains(lista, REGLA)

        # Al reactivarla se ejecuta: como en esta base EST-011 no detecta nada, el
        # aviso vuelve a la vista y se cierra como Corregido con su nota.
        self.client.post(url, {'activa': '1'})
        aviso.refresh_from_db()
        self.assertEqual((aviso.vigente, aviso.estado), (False, Hallazgo.CORREGIDO))
        self.assertIsNotNone(aviso.fecha_resolucion)


class InformativasSinAvisosTests(TestCase):
    """3.9.0: una regla Informativa solo se ve en Subsanación, nunca en la campana."""

    def test_no_crea_advertencia(self):
        from notificaciones.avisos import _registrar_notificacion_de_hallazgo
        from notificaciones.models import Notificacion
        from .constantes import CRITICIDAD_INFORMATIVA
        from .reglas import obtener_regla
        from .reglas.base import HallazgoDetectado

        regla = obtener_regla('ASP-005')
        self.assertEqual(regla.criticidad, CRITICIDAD_INFORMATIVA)
        usuario = CustomUser.objects.create_user(username='mod_info', password='x', es_moderador=True)
        resultado = _registrar_notificacion_de_hallazgo(
            tipo_ct=ContentType.objects.get_for_model(CustomUser), object_id='1',
            destinatario=usuario, regla=regla, hallazgo=HallazgoDetectado(object_id='1', titulo='x'))
        self.assertIsNone(resultado)
        self.assertFalse(Notificacion.objects.exists())

    def test_gravedades_decididas(self):
        from .constantes import CRITICIDAD_ALTA, CRITICIDAD_CRITICA, CRITICIDAD_INFORMATIVA, CRITICIDAD_MEDIA
        from .reglas import obtener_regla
        esperadas = {'CTR-002': CRITICIDAD_CRITICA, 'CTR-005': CRITICIDAD_ALTA, 'CTR-009': CRITICIDAD_MEDIA,
                     'SAL-001': CRITICIDAD_CRITICA, 'CTR-008': CRITICIDAD_CRITICA, 'CIE-001': CRITICIDAD_MEDIA,
                     'ASP-008': CRITICIDAD_INFORMATIVA, 'EXT-002': CRITICIDAD_INFORMATIVA,
                     'EST-005': CRITICIDAD_INFORMATIVA, 'USR-002': CRITICIDAD_INFORMATIVA}
        self.assertEqual({c: obtener_regla(c).criticidad for c in esperadas}, esperadas)

    def test_prenomina_desactivada(self):
        self.assertTrue({'CAL-101', 'CAL-102', 'PNM-002'} <= codigos_desactivados())


class OrdenDelIndiceTests(TestCase):
    """3.9.0: el Índice de Reglas se ordena por código (por categoría), por gravedad o
    por hallazgos abiertos."""

    def test_por_gravedad_y_por_hallazgos(self):
        admin = CustomUser.objects.create_user(username='adm_orden', password='x', es_admin=True)
        Hallazgo.objects.create(
            codigo_regla='CTR-016', content_type=ContentType.objects.get_for_model(CustomUser),
            object_id='1', modulo=MODULO_ESTRUCTURA, criticidad=CRITICIDAD_ALTA, titulo='x',
            ultima_deteccion=timezone.now(), estado=Hallazgo.PENDIENTE)
        self.client.force_login(admin)
        url = reverse('subsanacion:panel_reglas')

        reglas = self.client.get(url, {'orden': 'gravedad'}).context['categorias'][0]['reglas']
        valores = [r['criticidad_valor'] for r in reglas]
        self.assertEqual(valores, sorted(valores))

        reglas = self.client.get(url, {'orden': 'hallazgos'}).context['categorias'][0]['reglas']
        self.assertEqual(reglas[0]['codigo'], 'CTR-016')

        categorias = self.client.get(url).context['categorias']
        self.assertGreater(len(categorias), 1)   # por código: agrupadas como siempre
