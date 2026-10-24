from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .middleware import DeteccionExportacionMiddleware
from .models import TareaGuia, TareaGuiaParte, TareaGuiaUsuario
from .receptores import al_finalizar_analisis, al_revisar_hallazgo
from .servicios import abrir_logros, cerrar_logros, completar_parte, completar_tarea

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


PDF = 'application/pdf'
WORD = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
EXCEL = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class MiddlewareExportacionTests(TareaGuiaAisladaTestCase):
    """Categoría "Exportar": cada descarga cuenta para la tarea de SU sección,
    reconocida por la ruta de la vista, y no por el formato a secas."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        self.factory = RequestFactory()
        crear = TareaGuia.objects.create
        crear(codigo='exportar_informe_inteligente', titulo='II', categoria=TareaGuia.Categoria.EXPORTAR,
              partes='pdf,word,excel')
        crear(codigo='exportar_informes_rrhh', titulo='RRHH', categoria=TareaGuia.Categoria.EXPORTAR,
              partes='pdf,word,excel')
        crear(codigo='exportar_contrato_modificacion', titulo='Contrato', categoria=TareaGuia.Categoria.EXPORTAR,
              partes='creacion,modificacion')
        crear(codigo='exportar_historico_trabajador', titulo='Histórico', categoria=TareaGuia.Categoria.EXPORTAR)
        crear(codigo='exportar_anexos', titulo='Anexos', categoria=TareaGuia.Categoria.EXPORTAR,
              partes='17,17_1,17_2')

    def _procesar(self, ruta, content_type, metodo='get', datos=None, estado=200):
        from django.urls import resolve

        response = HttpResponse(content_type=content_type, status=estado)
        response['Content-Disposition'] = 'attachment; filename="documento"'
        middleware = DeteccionExportacionMiddleware(get_response=lambda request: response)
        request = getattr(self.factory, metodo)(ruta, datos or {})
        request.user = self.usuario
        request.resolver_match = resolve(ruta)
        return middleware(request)

    def _partes(self, codigo):
        return set(TareaGuiaParte.objects.filter(usuario=self.usuario, tarea__codigo=codigo)
                   .values_list('parte', flat=True))

    def _completada(self, codigo):
        return TareaGuiaUsuario.objects.filter(usuario=self.usuario, tarea__codigo=codigo).exists()

    def test_informes_rrhh_cuenta_por_formato_y_completa_con_los_tres(self):
        self._procesar('/informes/economia/exportar-pdf/', PDF)
        self._procesar('/informes/misiones/exportar-word/', WORD)
        self.assertEqual(self._partes('exportar_informes_rrhh'), {'pdf', 'word'})
        self.assertFalse(self._completada('exportar_informes_rrhh'))
        self._procesar('/informes/altas-bajas/exportar-excel/', EXCEL)
        self.assertTrue(self._completada('exportar_informes_rrhh'))

    def test_un_pdf_de_rrhh_no_cuenta_para_el_informe_inteligente(self):
        self._procesar('/informes/economia/exportar-pdf/', PDF)
        self.assertEqual(self._partes('exportar_informe_inteligente'), set())

    def test_informe_inteligente(self):
        self._procesar('/informe-inteligente/exportar-excel/', EXCEL, metodo='post')
        self.assertEqual(self._partes('exportar_informe_inteligente'), {'excel'})

    def test_contrato_y_modificacion_segun_el_tipo_de_documento(self):
        self._procesar('/contrato/exportar_contrato/1/', WORD, metodo='post', datos={'tipo_documento': 'modificacion'})
        self.assertEqual(self._partes('exportar_contrato_modificacion'), {'modificacion'})
        self._procesar('/contrato/exportar_contrato/1/', WORD, metodo='post', datos={'tipo_documento': 'creacion'})
        self.assertTrue(self._completada('exportar_contrato_modificacion'))

    def test_el_libro_combinado_cuenta_para_el_17_y_el_17_1(self):
        self._procesar('/informes-anexo/anexo/excel/combinado/', EXCEL)
        self.assertEqual(self._partes('exportar_anexos'), {'17', '17_1'})

    def test_tarea_sin_partes_se_completa_con_una_descarga_inline(self):
        # "Exportar Todo" abre el PDF en otra pestaña (inline): cuenta igual.
        self._procesar('/contrato/exportar/historico/pdf/1/', PDF)
        self.assertTrue(self._completada('exportar_historico_trabajador'))

    def test_ignora_html_y_respuestas_con_error(self):
        self._procesar('/informes/economia/exportar-pdf/', 'text/html')
        self._procesar('/informes/economia/exportar-word/', WORD, estado=500)
        self.assertEqual(self._partes('exportar_informes_rrhh'), set())


class CompletarParteTests(TareaGuiaAisladaTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        TareaGuia.objects.create(codigo='con_partes', titulo='Con partes', categoria=TareaGuia.Categoria.EXPORTAR,
                                 partes='pdf,word,excel')

    def test_parte_repetida_o_desconocida_no_cuenta(self):
        self.assertTrue(completar_parte(self.usuario, 'con_partes', 'pdf'))
        self.assertFalse(completar_parte(self.usuario, 'con_partes', 'pdf'))
        self.assertFalse(completar_parte(self.usuario, 'con_partes', 'zip'))
        self.assertEqual(TareaGuiaParte.objects.count(), 1)

    def test_avisa_del_avance_y_del_logro_al_completar(self):
        token = abrir_logros(self.usuario)
        completar_parte(self.usuario, 'con_partes', 'pdf')
        completar_parte(self.usuario, 'con_partes', 'word')
        completar_parte(self.usuario, 'con_partes', 'excel')
        logros = cerrar_logros(token)
        tipos = [l['tipo'] for l in logros]
        self.assertEqual(tipos[:2], ['avance', 'avance'])
        self.assertIn('tarea', tipos)
        self.assertEqual(logros[1]['texto'], 'Con partes: 2 de 3')

    def test_panel_y_endpoint_muestran_el_avance(self):
        completar_parte(self.usuario, 'con_partes', 'word')
        self.client.force_login(self.usuario)
        panel = self.client.get(reverse('progreso_panel'))
        self.assertContains(panel, '1 de 3')
        datos = self.client.get(reverse('progreso_partes_tarea', args=['con_partes'])).json()
        self.assertEqual([p['hecha'] for p in datos['partes']], [False, True, False])
        self.assertFalse(datos['completada'])


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


class TareasPorRolTests(TareaGuiaAisladaTestCase):
    """Cada rol ve, cuenta y completa solo sus tareas. Antes un Observador veía
    «Crea tu primer Aspirante» y nunca podía llegar al 100 %."""

    def setUp(self):
        super().setUp()
        self.admin = crear_usuario(username='admin_rol', es_moderador=False, es_admin=True)
        self.moderador = crear_usuario(username='moderador_rol')
        self.observador = crear_usuario(username='observador_rol', es_moderador=False, es_observador=True)
        self.comun = TareaGuia.objects.create(
            codigo='tarea_comun', titulo='Para todos', categoria=TareaGuia.Categoria.EXPLORAR)
        self.solo_admin = TareaGuia.objects.create(
            codigo='tarea_admin', titulo='Solo admin', categoria=TareaGuia.Categoria.DOMINAR,
            para_moderador=False, para_observador=False)
        self.edicion = TareaGuia.objects.create(
            codigo='tarea_edicion', titulo='Admin y moderador', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
            para_observador=False)

    def test_tareas_visibles_segun_rol(self):
        from .servicios import tareas_visibles

        self.assertEqual(set(tareas_visibles(self.admin)), {self.comun, self.solo_admin, self.edicion})
        self.assertEqual(set(tareas_visibles(self.moderador)), {self.comun, self.edicion})
        self.assertEqual(set(tareas_visibles(self.observador)), {self.comun})

    def test_no_completa_una_tarea_de_otro_rol(self):
        self.assertIsNone(completar_tarea(self.observador, 'tarea_edicion'))
        self.assertFalse(TareaGuiaUsuario.objects.filter(usuario=self.observador).exists())

    def test_panel_del_observador_no_muestra_tareas_de_edicion(self):
        self.client.force_login(self.observador)
        respuesta = self.client.get(reverse('progreso_panel'))

        self.assertContains(respuesta, 'Para todos')
        self.assertNotContains(respuesta, 'Admin y moderador')
        self.assertNotContains(respuesta, 'Solo admin')
        self.assertContains(respuesta, '0 de 1 completadas')

    def test_modo_guiado_de_otro_rol_devuelve_404(self):
        self.client.force_login(self.observador)
        respuesta = self.client.get(reverse('progreso_tarea_guiada', args=['tarea_admin']))
        self.assertEqual(respuesta.status_code, 404)

    def test_contador_ignora_tareas_completadas_que_ya_no_cuentan(self):
        """Una tarea completada que luego se desactiva no debe seguir sumando:
        antes el contador podía decir «2/1»."""
        completar_tarea(self.moderador, 'tarea_comun')
        completar_tarea(self.moderador, 'tarea_edicion')
        self.edicion.activo = False
        self.edicion.save()

        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('dashboard'))

        self.assertEqual(respuesta.context['progreso_total'], 1)
        self.assertEqual(respuesta.context['progreso_completadas'], 1)
        self.assertEqual(respuesta.context['progreso_porcentaje'], 100)

    def test_anotar_progreso_usa_el_total_de_cada_rol(self):
        from .servicios import anotar_progreso

        completar_tarea(self.admin, 'tarea_admin')
        completar_tarea(self.observador, 'tarea_comun')

        usuarios = {u.username: u for u in anotar_progreso(
            CustomUser.objects.filter(pk__in=[self.admin.pk, self.moderador.pk, self.observador.pk]))}

        self.assertEqual((usuarios['admin_rol'].progreso_completadas_count, usuarios['admin_rol'].progreso_total), (1, 3))
        self.assertEqual((usuarios['moderador_rol'].progreso_completadas_count, usuarios['moderador_rol'].progreso_total), (0, 2))
        self.assertEqual((usuarios['observador_rol'].progreso_completadas_count, usuarios['observador_rol'].progreso_total), (1, 1))


class InstrumentacionTareasNuevasTests(TareaGuiaAisladaTestCase):
    """Las acciones reales de los módulos que se incorporaron a la Guía
    completan su tarea."""

    def setUp(self):
        super().setUp()
        self.observador = crear_usuario(username='observador_inst', es_moderador=False, es_observador=True)
        for codigo in ('primer_reporte_problema', 'primer_informe_rrhh'):
            TareaGuia.objects.create(codigo=codigo, titulo=codigo, categoria=TareaGuia.Categoria.EXPLORAR)

    def test_enviar_un_reporte_completa_primer_reporte_problema(self):
        self.client.force_login(self.observador)
        respuesta = self.client.post(reverse('soporte:crear_reporte'), {'mensaje': 'La tabla no carga.'})

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(TareaGuiaUsuario.objects.filter(
            usuario=self.observador, tarea__codigo='primer_reporte_problema').exists())

    def test_reporte_invalido_no_completa_la_tarea(self):
        self.client.force_login(self.observador)
        self.client.post(reverse('soporte:crear_reporte'), {'mensaje': ''})

        self.assertFalse(TareaGuiaUsuario.objects.filter(usuario=self.observador).exists())

    def test_abrir_un_informe_rrhh_completa_primer_informe_rrhh(self):
        self.client.force_login(self.observador)
        respuesta = self.client.get(reverse('informe_economia'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(TareaGuiaUsuario.objects.filter(
            usuario=self.observador, tarea__codigo='primer_informe_rrhh').exists())


class LogrosGuiaTests(TareaGuiaAisladaTestCase):
    """Cada tarea nueva es un logro que llega al navegador al momento, en la
    cookie `orbith_logros`, aunque la respuesta sea un JSON o una descarga."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario(username='usuario_logros')
        TareaGuia.objects.create(codigo='l1', titulo='Primera', categoria=TareaGuia.Categoria.PRIMEROS_PASOS)
        TareaGuia.objects.create(codigo='l2', titulo='Segunda', categoria=TareaGuia.Categoria.PRIMEROS_PASOS)
        TareaGuia.objects.create(codigo='l3', titulo='Tercera', categoria=TareaGuia.Categoria.EXPLORAR)

    def _completar(self, codigo):
        from .servicios import abrir_logros, cerrar_logros

        token = abrir_logros(self.usuario)
        completar_tarea(self.usuario, codigo)
        return cerrar_logros(token)

    def test_completar_una_tarea_genera_su_logro_con_el_progreso(self):
        logros = self._completar('l1')

        self.assertEqual([l['id'] for l in logros], ['tarea:l1'])
        self.assertEqual(logros[0]['texto'], 'Primera')
        self.assertEqual((logros[0]['completadas'], logros[0]['total']), (1, 3))

    def test_repetir_la_tarea_no_genera_otro_logro(self):
        self._completar('l1')
        self.assertEqual(self._completar('l1'), [])

    def test_cerrar_una_categoria_da_un_logro_especial(self):
        self._completar('l1')
        logros = self._completar('l2')

        self.assertEqual([l['id'] for l in logros], ['tarea:l2', 'categoria:PRI'])
        self.assertIn('Primeros pasos', logros[1]['titulo'])

    def test_completar_toda_la_guia_da_el_logro_final(self):
        self._completar('l1')
        self._completar('l2')
        logros = self._completar('l3')

        self.assertEqual([l['id'] for l in logros], ['tarea:l3', 'categoria:EXP', 'total'])

    def test_sin_peticion_en_curso_no_falla(self):
        """Un receptor de señal fuera de una petición (comando, tarea
        programada) completa la tarea igual, sin logro que entregar."""
        self.assertEqual(completar_tarea(self.usuario, 'l1').codigo, 'l1')

    def test_la_cookie_llega_con_una_respuesta_json(self):
        import json
        from urllib.parse import unquote

        TareaGuia.objects.create(codigo='primer_reporte_problema', titulo='Reporta',
                                 categoria=TareaGuia.Categoria.EXPLORAR)
        self.client.force_login(self.usuario)
        respuesta = self.client.post(reverse('soporte:crear_reporte'),
                                     {'mensaje': 'La tabla de contratos no carga.'})

        cookie = respuesta.cookies.get("orbith_logros")
        self.assertIsNotNone(cookie)
        self.assertFalse(cookie['httponly'])
        logros = json.loads(unquote(cookie.value))
        self.assertEqual(logros[0]['id'], 'tarea:primer_reporte_problema')

    def test_sin_logro_no_se_envia_cookie(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('dashboard'))
        self.assertNotIn('orbith_logros', respuesta.cookies)


class AccesosTareaTests(TareaGuiaAisladaTestCase):
    """Una tarea con varias formas de hacerse (la contratación) muestra en el
    panel un botón por cada acceso, cada uno con su recorrido."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario(username='usuario_accesos')
        self.tarea = TareaGuia.objects.create(
            codigo='tarea_accesos', titulo='Con accesos', categoria=TareaGuia.Categoria.PRIMEROS_PASOS,
            instrucciones='Un paso', url_relacionada='/unica/',
            accesos='Desde A | /a/ | tarea_accesos:a\nlínea mal escrita\nDesde B | /b/ | tarea_accesos:b',
        )

    def test_lista_accesos_ignora_lineas_mal_escritas(self):
        self.assertEqual(
            [a['recorrido'] for a in self.tarea.lista_accesos],
            ['tarea_accesos:a', 'tarea_accesos:b'],
        )

    def test_panel_muestra_un_boton_por_acceso_en_vez_del_ir_a(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('progreso_panel'))

        self.assertContains(respuesta, 'Desde A')
        self.assertContains(respuesta, "orbithIniciarGuia('tarea_accesos:b')")
        self.assertNotContains(respuesta, 'href="/unica/"')


class PanelMedallasYFiltrosTests(TareaGuiaAisladaTestCase):
    """La cabecera enciende la medalla de una categoría solo cuando el usuario
    completó todas SUS tareas de esa categoría, y los filtros cuentan bien."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario(username='usuario_medallas')
        TareaGuia.objects.create(codigo='m1', titulo='Uno', categoria=TareaGuia.Categoria.PRIMEROS_PASOS)
        TareaGuia.objects.create(codigo='m2', titulo='Dos', categoria=TareaGuia.Categoria.EXPLORAR)
        TareaGuia.objects.create(codigo='m3', titulo='Tres', categoria=TareaGuia.Categoria.EXPLORAR)

    def test_medalla_de_categoria_y_contadores(self):
        completar_tarea(self.usuario, 'm1')
        completar_tarea(self.usuario, 'm2')
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('progreso_panel'))
        grupos = {g['etiqueta']: g['completa'] for g in respuesta.context['grupos']}

        self.assertTrue(grupos['Primeros pasos'])
        self.assertFalse(grupos['Explorar Orbith'])
        self.assertEqual(respuesta.context['pendientes'], 1)
        self.assertContains(respuesta, 'Pendientes (1)')
        self.assertContains(respuesta, 'Completadas (2)')
        # El trofeo del 100 % sigue apagado.
        self.assertContains(respuesta, 'Completa toda la Guía')


class TareaEnDesarrolloTests(TareaGuiaAisladaTestCase):
    """Una tarea de un módulo en construcción se ve atenuada en el panel, pero
    no cuenta para el avance ni se puede completar."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        TareaGuia.objects.create(codigo='normal', titulo='Normal', categoria=TareaGuia.Categoria.EXPORTAR)
        TareaGuia.objects.create(codigo='en_obras', titulo='Tarea en obras', categoria=TareaGuia.Categoria.EXPORTAR,
                                 en_desarrollo=True)

    def test_no_cuenta_ni_se_completa(self):
        self.assertIsNone(completar_tarea(self.usuario, 'en_obras'))
        completar_tarea(self.usuario, 'normal')
        from .servicios import resumen_progreso
        resumen = resumen_progreso(self.usuario)
        self.assertEqual((resumen['completadas'], resumen['total']), (1, 1))

    def test_el_panel_la_muestra_atenuada(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('progreso_panel'))
        self.assertContains(respuesta, 'Tarea en obras')
        self.assertContains(respuesta, 'En desarrollo')
        self.assertContains(respuesta, 'data-guia-estado="desarrollo"')
        self.assertContains(respuesta, '0 de 1 completadas')


class BusquedaConPrefijosTests(TareaGuiaAisladaTestCase):
    """Tarea "Busca con prefijos": cuenta un prefijo que la pantalla entiende."""

    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario()
        self.factory = RequestFactory()
        TareaGuia.objects.create(codigo='primera_busqueda_prefijos', titulo='Busca con prefijos',
                                 categoria=TareaGuia.Categoria.EXPLORAR)

    def _buscar(self, ruta, parametros):
        from django.urls import resolve

        middleware = DeteccionExportacionMiddleware(get_response=lambda request: HttpResponse('ok'))
        request = self.factory.get(ruta, parametros)
        request.user = self.usuario
        request.resolver_match = resolve(ruta)
        middleware(request)
        return TareaGuiaUsuario.objects.filter(usuario=self.usuario,
                                               tarea__codigo='primera_busqueda_prefijos').exists()

    def test_cuenta_un_prefijo_valido(self):
        self.assertTrue(self._buscar('/contrato/search_contrato/', {'filter_contrato': 'N:Juan'}))

    def test_no_cuenta_sin_prefijo_ni_con_uno_que_la_pantalla_no_entiende(self):
        self.assertFalse(self._buscar('/contrato/search_contrato/', {'filter_contrato': 'Juan'}))
        # COD: es de Subsanación: en Contratos no filtra.
        self.assertFalse(self._buscar('/contrato/search_contrato/', {'filter_contrato': 'COD:CTR'}))
        # E: no vale en Aspirantes (un aspirante no tiene expediente).
        self.assertFalse(self._buscar('/bolsa/search_aspirante/', {'filter_aspirante': 'E:8855'}))
