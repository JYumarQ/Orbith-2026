from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from usuarios.models import CustomUser

from .models import ReporteProblema


class AuditoriaAdminTests(TestCase):
    """Editar/eliminar un ReporteProblema desde el Admin de Django ahora deja
    rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_soporte', password='x', es_admin=True)

    def test_eliminar_un_reporte_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        reporte = ReporteProblema.objects.create(mensaje='Algo no funciona')
        self.client.force_login(self.admin)

        url = reverse('admin:soporte_reporteproblema_delete', args=[reporte.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(ReporteProblema.objects.filter(pk=reporte.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(reporte.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'soporte')

    def test_editar_un_reporte_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from soporte.admin import ReporteProblemaAdmin

        reporte = ReporteProblema.objects.create(mensaje='Algo no funciona')

        admin_instance = ReporteProblemaAdmin(ReporteProblema, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        reporte.estado = ReporteProblema.ESTADO_ATENDIDO
        admin_instance.save_model(request, reporte, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(reporte.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)


class RegistroErroresTests(TestCase):
    """Registro de errores en ficheros diarios, visible en el admin de Django solo
    para el Administrador (24-10-2026)."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self.carpeta = tempfile.mkdtemp()
        ajuste = override_settings(CARPETA_REGISTRO_ERRORES=self.carpeta)
        ajuste.enable()
        self.addCleanup(ajuste.disable)

    def _registrar(self, mensaje):
        import logging
        from core.registro_errores import ManejadorDiario
        manejador = ManejadorDiario()
        manejador.setFormatter(logging.Formatter('%(message)s'))
        manejador.emit(logging.makeLogRecord({'msg': mensaje, 'levelno': logging.ERROR}))

    def test_cada_error_va_al_fichero_del_dia_y_los_viejos_se_borran(self):
        from datetime import timedelta
        from pathlib import Path
        from django.utils import timezone
        from core import registro_errores
        viejo = registro_errores.fichero_del_dia(timezone.localdate() - timedelta(days=40))
        viejo.write_text('antiguo', encoding='utf-8')
        self._registrar('Fallo de prueba')
        hoy = registro_errores.fichero_del_dia(timezone.localdate())
        self.assertIn('Fallo de prueba', Path(hoy).read_text(encoding='utf-8'))
        self.assertFalse(viejo.exists())

    def test_sin_carpeta_utilizable_no_rompe(self):
        from core.registro_errores import configuracion_logging
        import os
        fichero = os.path.join(self.carpeta, 'no_es_carpeta')
        open(fichero, 'w').close()
        config = configuracion_logging(os.path.join(fichero, 'logs'))
        self.assertEqual(config['root']['handlers'], ['consola'])

    def test_solo_el_administrador_lo_ve_y_descarga(self):
        from django.urls import reverse
        from django.utils import timezone
        from usuarios.models import CustomUser
        self._registrar('Fallo visible')
        nombre = 'orbith-%s.log' % timezone.localdate().strftime('%Y-%m-%d')
        url = reverse('admin:soporte_registroerrores_changelist')

        moderador = CustomUser.objects.create_user(username='mod_reg', password='x',
                                                   es_moderador=True, is_staff=True)
        self.client.force_login(moderador)
        self.assertNotEqual(self.client.get(url).status_code, 200)

        admin = CustomUser.objects.create_user(username='adm_reg', password='x',
                                               es_admin=True, is_staff=True)
        self.client.force_login(admin)
        respuesta = self.client.get(url)
        self.assertContains(respuesta, 'Fallo visible')
        descarga = self.client.get(reverse('admin:soporte_registroerrores_descargar', args=[nombre]))
        self.assertEqual(descarga.status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:soporte_registroerrores_descargar',
                                                 args=['..%2Fsettings.py'])).status_code, 404)


class DiagnosticoServidorTests(TestCase):
    """Diagnóstico del servidor en el admin de Django (24-10-2026): solo el
    Administrador, y deja el fichero de prueba en la carpeta de ficheros subidos."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        ajuste = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        ajuste.enable()
        self.addCleanup(ajuste.disable)

    def test_solo_el_administrador_y_escribe_el_fichero_de_prueba(self):
        from pathlib import Path
        from django.conf import settings
        from django.urls import reverse
        from core.diagnostico import FICHERO_PRUEBA
        url = reverse('admin:soporte_diagnosticoservidor_changelist')

        moderador = CustomUser.objects.create_user(username='mod_diag', password='x',
                                                   es_moderador=True, is_staff=True)
        self.client.force_login(moderador)
        self.assertNotEqual(self.client.get(url).status_code, 200)

        admin = CustomUser.objects.create_user(username='adm_diag', password='x',
                                               es_admin=True, is_staff=True)
        self.client.force_login(admin)
        respuesta = self.client.get(url)
        self.assertContains(respuesta, 'Diagnóstico del servidor')
        self.assertTrue((Path(settings.MEDIA_ROOT) / FICHERO_PRUEBA).is_file())
