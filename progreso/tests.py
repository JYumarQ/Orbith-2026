from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .middleware import DeteccionExportacionMiddleware
from .models import TareaGuia, TareaGuiaUsuario
from .receptores import al_finalizar_analisis, al_revisar_hallazgo
from .servicios import completar_tarea

CustomUser = get_user_model()


def crear_usuario(username='usuario_test', **overrides):
    datos = {'password': 'ClaveSegura123', 'es_moderador': True}
    datos.update(overrides)
    return CustomUser.objects.create_user(username=username, **datos)


class TareaGuiaAisladaTestCase(TestCase):
    """Base común: el catálogo semilla de la migración de datos
    (progreso/migrations/0002_seed_tareas.py) ya existe en la BD de test, así
    que estos tests parten de una pizarra limpia para no chocar con esos
    códigos ni contaminar los conteos de `progreso_total`."""

    def setUp(self):
        TareaGuia.objects.all().delete()
        super().setUp()


class CompletarTareaTests(TareaGuiaAisladaTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        self.tarea = TareaGuia.objects.create(
            codigo='tarea_prueba', titulo='Tarea de prueba', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
        )

    def test_completa_la_tarea_la_primera_vez(self):
        resultado = completar_tarea(self.usuario, 'tarea_prueba')
        self.assertEqual(resultado, self.tarea)
        self.assertTrue(TareaGuiaUsuario.objects.filter(usuario=self.usuario, tarea=self.tarea).exists())

    def test_es_idempotente_no_duplica_ni_repite_el_aviso(self):
        completar_tarea(self.usuario, 'tarea_prueba')
        resultado_2 = completar_tarea(self.usuario, 'tarea_prueba')

        self.assertIsNone(resultado_2)
        self.assertEqual(TareaGuiaUsuario.objects.filter(usuario=self.usuario, tarea=self.tarea).count(), 1)

    def test_codigo_inexistente_no_lanza_excepcion(self):
        resultado = completar_tarea(self.usuario, 'codigo_que_no_existe')
        self.assertIsNone(resultado)

    def test_tarea_inactiva_no_se_puede_completar(self):
        self.tarea.activo = False
        self.tarea.save()

        resultado = completar_tarea(self.usuario, 'tarea_prueba')

        self.assertIsNone(resultado)
        self.assertFalse(TareaGuiaUsuario.objects.filter(usuario=self.usuario).exists())

    def test_usuario_anonimo_no_lanza_excepcion(self):
        from django.contrib.auth.models import AnonymousUser
        resultado = completar_tarea(AnonymousUser(), 'tarea_prueba')
        self.assertIsNone(resultado)

    def test_fallo_interno_se_registra_y_no_se_propaga(self):
        """Requisito de diseño: completar_tarea() nunca debe poder romper la
        operación de negocio real que la origina (ver progreso/servicios.py)."""
        with patch('progreso.servicios.TareaGuiaUsuario.objects.get_or_create', side_effect=RuntimeError('boom')):
            resultado = completar_tarea(self.usuario, 'tarea_prueba')
        self.assertIsNone(resultado)


class ReceptoresDefensivosTests(TareaGuiaAisladaTestCase):
    """Las señales de Subsanación se despachan con Signal.send() normal (no
    send_robust()): un receptor que deje escapar una excepción rompería el
    flujo real de revisión de hallazgos o de finalización de análisis. Estos
    tests confirman que eso no puede pasar, incluso si completar_tarea()
    fallara internamente."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        TareaGuia.objects.create(
            codigo='primera_revision_hallazgo', titulo='Revisión', categoria=TareaGuia.Categoria.DOMINAR,
        )
        TareaGuia.objects.create(
            codigo='primer_analisis_subsanacion', titulo='Análisis', categoria=TareaGuia.Categoria.EXPLORAR,
        )

    def test_al_revisar_hallazgo_no_propaga_excepciones(self):
        with patch('progreso.receptores.completar_tarea', side_effect=RuntimeError('boom')):
            try:
                al_revisar_hallazgo(
                    sender=None, hallazgo=None, estado_anterior='PEN', estado_nuevo='COR',
                    usuario=self.usuario, nota='', automatica=False,
                )
            except RuntimeError:
                self.fail("al_revisar_hallazgo no debe propagar excepciones")

    def test_al_revisar_hallazgo_ignora_revisiones_automaticas(self):
        with patch('progreso.receptores.completar_tarea') as mock_completar:
            al_revisar_hallazgo(
                sender=None, hallazgo=None, estado_anterior='PEN', estado_nuevo='COR',
                usuario=self.usuario, nota='', automatica=True,
            )
        mock_completar.assert_not_called()

    def test_al_finalizar_analisis_no_propaga_excepciones(self):
        usuario = self.usuario

        class EjecucionFalsa:
            lanzada_por = usuario

        with patch('progreso.receptores.completar_tarea', side_effect=RuntimeError('boom')):
            try:
                al_finalizar_analisis(sender=None, ejecucion=EjecucionFalsa())
            except RuntimeError:
                self.fail("al_finalizar_analisis no debe propagar excepciones")

    def test_al_finalizar_analisis_completa_la_tarea(self):
        usuario = self.usuario

        class EjecucionFalsa:
            lanzada_por = usuario

        al_finalizar_analisis(sender=None, ejecucion=EjecucionFalsa())
        self.assertTrue(TareaGuiaUsuario.objects.filter(
            usuario=self.usuario, tarea__codigo='primer_analisis_subsanacion').exists())

    def test_al_finalizar_analisis_sin_usuario_no_hace_nada(self):
        class EjecucionFalsa:
            lanzada_por = None

        al_finalizar_analisis(sender=None, ejecucion=EjecucionFalsa())
        self.assertFalse(TareaGuiaUsuario.objects.exists())


class MiddlewareExportacionTests(TareaGuiaAisladaTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        self.factory = RequestFactory()
        TareaGuia.objects.create(
            codigo='primera_exportacion_pdf', titulo='Exportar PDF', categoria=TareaGuia.Categoria.EXPLORAR,
        )

    def _procesar(self, response):
        from django.contrib.messages.storage.fallback import FallbackStorage

        middleware = DeteccionExportacionMiddleware(get_response=lambda request: response)
        request = self.factory.get('/cualquier-url/')
        request.user = self.usuario
        # En un request real, MessageMiddleware ya deja `_messages` listo antes
        # de llegar aquí (ver core/settings.py: este middleware va después).
        # RequestFactory no pasa por ese middleware, así que se simula a mano.
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return middleware(request)

    def test_detecta_pdf_por_content_type(self):
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="informe.pdf"'
        self._procesar(response)
        self.assertTrue(TareaGuiaUsuario.objects.filter(
            usuario=self.usuario, tarea__codigo='primera_exportacion_pdf').exists())

    def test_ignora_respuestas_html_normales(self):
        response = HttpResponse(content_type='text/html')
        self._procesar(response)
        self.assertFalse(TareaGuiaUsuario.objects.exists())

    def test_ignora_content_type_pdf_sin_attachment(self):
        # Una vista que sirva un PDF "inline" (no descarga) no debe contar.
        response = HttpResponse(content_type='application/pdf')
        self._procesar(response)
        self.assertFalse(TareaGuiaUsuario.objects.exists())


class ContextoGlobalTests(TareaGuiaAisladaTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        TareaGuia.objects.create(codigo='t1', titulo='Uno', categoria=TareaGuia.Categoria.PRIMEROS_PASOS)
        TareaGuia.objects.create(codigo='t2', titulo='Dos', categoria=TareaGuia.Categoria.PRIMEROS_PASOS)
        TareaGuia.objects.create(codigo='t3', titulo='Inactiva', categoria=TareaGuia.Categoria.PRIMEROS_PASOS, activo=False)

    def test_progreso_expuesto_en_el_contexto_de_cualquier_pagina(self):
        self.client.force_login(self.usuario)
        completar_tarea(self.usuario, 't1')

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['progreso_total'], 2)  # la inactiva no cuenta
        self.assertEqual(response.context['progreso_completadas'], 1)
        self.assertEqual(response.context['progreso_porcentaje'], 50)

    def test_no_escribe_en_bd_en_una_peticion_de_lectura(self):
        self.client.force_login(self.usuario)
        antes = TareaGuiaUsuario.objects.count()
        self.client.get(reverse('dashboard'))
        self.assertEqual(TareaGuiaUsuario.objects.count(), antes)


class InstrumentacionAspiranteTests(TareaGuiaAisladaTestCase):
    """Verifica de extremo a extremo (vía Client, sin depender de la validación
    JS del formulario en el navegador) que crear un Aspirante real completa
    `primer_aspirante` una sola vez."""

    def setUp(self):
        super().setUp()
        from nomencladores.models import NMunicipio, NProvincia

        TareaGuia.objects.create(
            codigo='primer_aspirante', titulo='Crea tu primer Aspirante', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
        )
        self.usuario = crear_usuario()
        self.provincia = NProvincia.objects.create(nombre='Provincia de prueba')
        self.municipio = NMunicipio.objects.create(nombre='Municipio de prueba', provincia=self.provincia)

    def _datos_aspirante(self, doc_identidad):
        return {
            'doc_identidad': doc_identidad,
            'sexo': 'M',
            'nombre': 'PruebaProgreso',
            'papellido': 'VerificacionGuia',
            'sapellido': 'Test',
            'provincia': self.provincia.id,
            'municipio': self.municipio.id,
            'raza': 'BL',
            'nivel_educ': 'SA',
        }

    def test_crear_aspirante_completa_primer_aspirante(self):
        self.client.force_login(self.usuario)
        response = self.client.post(reverse('add_aspir'), self._datos_aspirante('90050598761'))

        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.context else response.content)
        self.assertTrue(TareaGuiaUsuario.objects.filter(
            usuario=self.usuario, tarea__codigo='primer_aspirante').exists())

    def test_crear_segundo_aspirante_no_duplica_la_tarea(self):
        self.client.force_login(self.usuario)
        self.client.post(reverse('add_aspir'), self._datos_aspirante('90050598761'))
        self.client.post(reverse('add_aspir'), self._datos_aspirante('90050598762'))

        self.assertEqual(TareaGuiaUsuario.objects.filter(
            usuario=self.usuario, tarea__codigo='primer_aspirante').count(), 1)

    def test_formulario_invalido_no_completa_la_tarea(self):
        self.client.force_login(self.usuario)
        datos = self._datos_aspirante('90050598761')
        del datos['nombre']  # dato requerido ausente -> el form no debe validar

        response = self.client.post(reverse('add_aspir'), datos)

        self.assertEqual(response.status_code, 200)  # re-renderiza el form con errores, no redirige
        self.assertFalse(TareaGuiaUsuario.objects.exists())


class PanelGuiaViewTests(TareaGuiaAisladaTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        self.tarea = TareaGuia.objects.create(
            codigo='t1', titulo='Uno', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
            instrucciones='Paso uno.\nPaso dos.\n\nPaso tres.',
            url_relacionada='/algun-modulo/', modulo='Algún módulo',
        )

    def test_panel_requiere_login(self):
        response = self.client.get(reverse('progreso_panel'))
        self.assertNotEqual(response.status_code, 200)

    def test_marcar_vistas_pone_visto_true(self):
        self.client.force_login(self.usuario)
        completar_tarea(self.usuario, 't1')

        response = self.client.post(reverse('progreso_marcar_vistas'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TareaGuiaUsuario.objects.get(usuario=self.usuario, tarea=self.tarea).visto)

    def test_panel_muestra_instrucciones_y_enlace_para_tarea_pendiente(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('progreso_panel'))
        contenido = response.content.decode()

        self.assertIn('Paso uno.', contenido)
        self.assertIn('Paso dos.', contenido)
        self.assertIn('Paso tres.', contenido)
        self.assertIn('/algun-modulo/', contenido)

    def test_panel_muestra_instrucciones_tambien_para_tarea_ya_completada(self):
        """Requisito explícito: el usuario debe poder volver a consultar el
        tutorial de una tarea aunque ya la haya completado."""
        self.client.force_login(self.usuario)
        completar_tarea(self.usuario, 't1')

        response = self.client.get(reverse('progreso_panel'))
        contenido = response.content.decode()

        self.assertIn('Paso uno.', contenido)
        self.assertIn('/algun-modulo/', contenido)


class TareaGuiadaEndpointTests(TareaGuiaAisladaTestCase):
    """Endpoint que consulta el widget de modo guiado
    (static/js/progreso_guia.js) en cada carga de página cuando hay una guía
    activa en sessionStorage."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        self.tarea = TareaGuia.objects.create(
            codigo='t1', titulo='Uno', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
            instrucciones='Paso uno.\nPaso dos.',
        )

    def test_requiere_login(self):
        response = self.client.get(reverse('progreso_tarea_guiada', args=['t1']))
        self.assertNotEqual(response.status_code, 200)

    def test_devuelve_pasos_y_completada_false_si_no_se_ha_hecho(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('progreso_tarea_guiada', args=['t1']))
        datos = response.json()

        self.assertEqual(datos['titulo'], 'Uno')
        self.assertEqual(datos['pasos'], ['Paso uno.', 'Paso dos.'])
        self.assertFalse(datos['completada'])

    def test_completada_true_una_vez_realizada_la_accion_real(self):
        self.client.force_login(self.usuario)
        completar_tarea(self.usuario, 't1')

        response = self.client.get(reverse('progreso_tarea_guiada', args=['t1']))

        self.assertTrue(response.json()['completada'])

    def test_codigo_inexistente_devuelve_404(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('progreso_tarea_guiada', args=['no-existe']))
        self.assertEqual(response.status_code, 404)

    def test_tarea_inactiva_devuelve_404(self):
        self.tarea.activo = False
        self.tarea.save()
        self.client.force_login(self.usuario)

        response = self.client.get(reverse('progreso_tarea_guiada', args=['t1']))

        self.assertEqual(response.status_code, 404)


class TareaGuiaPasosTests(TareaGuiaAisladaTestCase):
    def test_pasos_ignora_lineas_vacias_y_recorta_espacios(self):
        tarea = TareaGuia.objects.create(
            codigo='t1', titulo='Uno', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
            instrucciones='  Primero  \n\n  Segundo\n',
        )
        self.assertEqual(tarea.pasos, ['Primero', 'Segundo'])

    def test_pasos_vacio_sin_instrucciones(self):
        tarea = TareaGuia.objects.create(
            codigo='t1', titulo='Uno', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
        )
        self.assertEqual(tarea.pasos, [])


class AuditoriaAdminTests(TareaGuiaAisladaTestCase):
    """Crear/editar/eliminar una TareaGuia desde el Admin de Django ahora deja
    rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto). A diferencia de `TareaGuiaUsuarioAdmin`
    (bloqueado, es evidencia de una acción real), `TareaGuiaAdmin` sí tiene CRUD
    completo."""

    def setUp(self):
        super().setUp()
        self.admin = crear_usuario(username='admin_progreso', es_moderador=False, es_admin=True)

    def test_eliminar_una_tarea_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        tarea = TareaGuia.objects.create(
            codigo='tarea_auditoria', titulo='Tarea de auditoría',
            categoria=TareaGuia.Categoria.PRIMEROS_PASOS)
        self.client.force_login(self.admin)

        url = reverse('admin:progreso_tareaguia_delete', args=[tarea.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(TareaGuia.objects.filter(pk=tarea.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(tarea.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'progreso')

    def test_editar_una_tarea_desde_el_admin_queda_auditado(self):
        from django.contrib.admin.sites import AdminSite

        from auditoria.models import EventoAuditoria
        from progreso.admin import TareaGuiaAdmin

        tarea = TareaGuia.objects.create(
            codigo='tarea_auditoria_2', titulo='Tarea de auditoría',
            categoria=TareaGuia.Categoria.PRIMEROS_PASOS)

        admin_instance = TareaGuiaAdmin(TareaGuia, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        tarea.titulo = 'Tarea renombrada'
        admin_instance.save_model(request, tarea, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(tarea.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
