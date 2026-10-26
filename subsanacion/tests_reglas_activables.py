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
        self.assertEqual(codigos_desactivados(), {REGLA})
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
