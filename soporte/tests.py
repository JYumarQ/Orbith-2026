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


class CopiaBaseDatosTests(TestCase):
    """Copia completa de la base desde el admin (18-11-2026): solo el Administrador,
    en un proceso aparte, con Auditoría y borrada a las 24 horas."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from django.test import override_settings
        self.carpeta = Path(tempfile.mkdtemp())
        ajuste = override_settings(CARPETA_COPIAS_BD=str(self.carpeta))
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        programa = mock.patch('core.copia_base.programa', return_value='/usr/bin/pg_dump')
        programa.start()
        self.addCleanup(programa.stop)
        self.url = reverse('admin:soporte_copiabasedatos_changelist')
        self.admin = CustomUser.objects.create_user(username='adm_copia', password='x',
                                                    es_admin=True, is_staff=True)

    def _copia(self, nombre='orbith-copia-2026-11-18_080000.dump'):
        fichero = self.carpeta / nombre
        fichero.write_bytes(b'PGDMP')
        return fichero

    def test_solo_el_administrador(self):
        moderador = CustomUser.objects.create_user(username='mod_copia', password='x',
                                                   es_moderador=True, is_staff=True)
        self.client.force_login(moderador)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)
        from unittest import mock
        with mock.patch('core.copia_base.subprocess.Popen') as popen:
            self.client.post(reverse('admin:soporte_copiabasedatos_preparar'))
        popen.assert_not_called()

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), 'Preparar una copia nueva')

    def test_preparar_lanza_pg_dump_aparte_y_queda_en_auditoria(self):
        from unittest import mock
        from auditoria.models import AccionAuditoria, EventoAuditoria
        self.client.force_login(self.admin)
        with mock.patch('core.copia_base.subprocess.Popen') as popen:
            self.client.post(reverse('admin:soporte_copiabasedatos_preparar'))
            orden = popen.call_args.args[0]
            self.assertIn('-Fc', orden)
            self.assertIn('PGPASSWORD', popen.call_args.kwargs['env'])
            from django.conf import settings
            clave = settings.DATABASES['default']['PASSWORD']
            if clave:
                self.assertNotIn(clave, orden)  # la contraseña nunca en la orden

            self.assertContains(self.client.get(self.url), 'Preparando la copia')
            # Mientras se prepara, no se lanza otra.
            respuesta = self.client.post(reverse('admin:soporte_copiabasedatos_preparar'), follow=True)
            self.assertContains(respuesta, 'Ya se está preparando una copia')
            self.assertEqual(popen.call_count, 1)
        self.assertEqual(EventoAuditoria.objects.filter(accion=AccionAuditoria.COPIA_BASE).count(), 1)

    def test_descargar_queda_en_auditoria_y_solo_nombres_de_la_lista(self):
        from auditoria.models import AccionAuditoria, EventoAuditoria
        copia = self._copia()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), copia.name)
        descarga = self.client.get(reverse('admin:soporte_copiabasedatos_descargar', args=[copia.name]))
        self.assertEqual(descarga.status_code, 200)
        self.assertEqual(b''.join(descarga.streaming_content), b'PGDMP')
        self.assertTrue(EventoAuditoria.objects.filter(
            accion=AccionAuditoria.COPIA_BASE, descriptor__contains='Descargó').exists())
        self.assertEqual(self.client.get(reverse('admin:soporte_copiabasedatos_descargar',
                                                 args=['..%2Fsettings.py'])).status_code, 404)

    def test_el_proceso_aparte_deja_la_copia_o_el_error(self):
        import sys
        from core import copia_base
        final = self.carpeta / 'orbith-copia-2026-11-18_090000.dump'
        parcial = self.carpeta / (final.name + copia_base.PARCIAL)
        parcial.touch()
        bien = [sys.executable, '-c', 'import sys; open(sys.argv[1], "w").write("x")', str(parcial)]
        self.assertTrue(copia_base.ejecutar(parcial, final, bien))
        self.assertTrue(final.exists())
        self.assertFalse(parcial.exists())

        final = self.carpeta / 'orbith-copia-2026-11-18_100000.dump'
        parcial = self.carpeta / (final.name + copia_base.PARCIAL)
        parcial.touch()
        mal = [sys.executable, '-c', 'import sys; sys.stderr.write("fallo de prueba"); sys.exit(1)']
        self.assertFalse(copia_base.ejecutar(parcial, final, mal))
        self.assertFalse(parcial.exists())
        self.assertIn('fallo de prueba', copia_base.errores()[0].read_text(encoding='utf-8'))

    def test_las_copias_se_borran_solas_a_las_24_horas(self):
        import os
        import time
        from core import copia_base
        vieja = self._copia('orbith-copia-2026-11-16_080000.dump')
        hace_dos_dias = time.time() - 48 * 3600
        os.utime(vieja, (hace_dos_dias, hace_dos_dias))
        nueva = self._copia()
        copia_base.borrar_antiguas()
        self.assertFalse(vieja.exists())
        self.assertTrue(nueva.exists())


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


class ActualizacionOrbithTests(TestCase):
    """Diagnóstico y ensayo de actualización desde el admin (18-11-2026): solo el
    Administrador, subida por trozos, lista de huellas y un ensayo que no toca nada."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        self.carpeta = Path(tempfile.mkdtemp())
        ajuste = override_settings(CARPETA_ACTUALIZACIONES=str(self.carpeta / 'act'))
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        self.url = reverse('admin:soporte_actualizacionorbith_changelist')
        self.admin = CustomUser.objects.create_user(username='adm_act', password='x', es_admin=True, is_staff=True)

    def _paquete(self, nombre='orbith-9.9.9.tar.gz', estropear=False, carpeta_raiz='orbith-9.9.9'):
        """Un paquete mínimo con su lista de huellas."""
        import tarfile
        from core import actualizacion
        raiz = self.carpeta / 'fuente' / carpeta_raiz
        (raiz / 'core').mkdir(parents=True, exist_ok=True)
        (raiz / 'core' / 'changelog.py').write_text('CHANGELOG = [\n    {"version": "9.9.9"},\n]\n', encoding='utf-8')
        (raiz / 'requirements.txt').write_text('', encoding='utf-8')
        actualizacion.escribir_manifiesto(raiz)
        if estropear:
            (raiz / 'requirements.txt').write_text('cambiado', encoding='utf-8')
        destino = actualizacion.subidas() / nombre
        with tarfile.open(destino, 'w:gz') as tar:
            tar.add(raiz, arcname=carpeta_raiz)
        return destino

    def test_solo_el_administrador(self):
        moderador = CustomUser.objects.create_user(username='mod_act', password='x', es_moderador=True, is_staff=True)
        self.client.force_login(moderador)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url + '?diagnostico=1')
        self.assertContains(respuesta, 'DIAGNÓSTICO DEL SERVIDOR')
        from django.conf import settings
        clave = settings.DATABASES['default']['PASSWORD']
        if clave:
            self.assertNotContains(respuesta, clave)

    def test_subida_por_trozos_y_auditoria(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from auditoria.models import AccionAuditoria, EventoAuditoria
        from core import actualizacion
        self.client.force_login(self.admin)
        url = reverse('admin:soporte_actualizacion_subir')
        with mock.patch.object(actualizacion, 'TAMANO_TROZO', 4):
            for i, trozo in enumerate([b'abcd', b'efgh', b'ij']):
                r = self.client.post(url, {'nombre': 'orbith-9.9.9.tar.gz', 'indice': i, 'total': 3,
                                           'trozo': SimpleUploadedFile('t', trozo)})
                self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()['terminado'])
            # Un trozo fuera de orden se rechaza.
            r = self.client.post(url, {'nombre': 'orbith-9.9.9.tar.gz', 'indice': 2, 'total': 3,
                                       'trozo': SimpleUploadedFile('t', b'xx')})
            self.assertEqual(r.status_code, 400)
        self.assertEqual((actualizacion.subidas() / 'orbith-9.9.9.tar.gz').read_bytes(), b'abcdefghij')
        self.assertTrue(EventoAuditoria.objects.filter(accion=AccionAuditoria.ACTUALIZACION).exists())
        r = self.client.post(url, {'nombre': '../settings.py', 'indice': 0, 'total': 1,
                                   'trozo': SimpleUploadedFile('t', b'x')})
        self.assertEqual(r.status_code, 400)

    def test_lista_de_huellas(self):
        from core import actualizacion
        raiz = self.carpeta / 'arbol'
        (raiz / 'a').mkdir(parents=True)
        (raiz / 'a' / 'b.txt').write_text('hola', encoding='utf-8')
        actualizacion.escribir_manifiesto(raiz)
        self.assertNotIn(b'\r', (raiz / actualizacion.MANIFIESTO).read_bytes())   # LF también en Windows
        self.assertEqual(actualizacion.comprobar_manifiesto(raiz), [])
        (raiz / 'a' / 'b.txt').write_text('otra cosa', encoding='utf-8')
        (raiz / 'intruso.py').write_text('x', encoding='utf-8')
        problemas = actualizacion.comprobar_manifiesto(raiz)
        self.assertTrue(any('dañado' in p for p in problemas))
        self.assertTrue(any('intruso.py' in p for p in problemas))

    def test_no_se_extrae_fuera_de_su_carpeta(self):
        import io
        import tarfile
        from core import actualizacion
        malo = self.carpeta / 'malo.tar.gz'
        with tarfile.open(malo, 'w:gz') as tar:
            info = tarfile.TarInfo('orbith-1/../../fuera.txt')
            info.size = 1
            tar.addfile(info, io.BytesIO(b'x'))
        with self.assertRaises(actualizacion.ErrorDeActualizacion):
            actualizacion._extraer(malo, self.carpeta / 'destino')
        self.assertFalse((self.carpeta / 'fuera.txt').exists())

    def _ensayar(self, paquete):
        from unittest import mock
        from core import actualizacion
        with mock.patch.object(actualizacion, 'ejecutar', return_value=(0, 'todo bien')), \
                mock.patch.object(actualizacion, 'diagnostico', return_value='(diagnóstico)'), \
                mock.patch.object(actualizacion, 'puede_crear_bases', return_value=False), \
                mock.patch.object(actualizacion.shutil, 'copy2'):
            actualizacion.ensayar(paquete, 'ensayo-prueba.log')
        return (actualizacion.registros() / 'ensayo-prueba.log').read_text(encoding='utf-8')

    def test_ensayo_correcto_y_limpia(self):
        from core import actualizacion
        texto = self._ensayar(self._paquete())
        self.assertIn('Versión del paquete: 9.9.9', texto)
        self.assertIn('Todos los archivos coinciden con su huella', texto)
        self.assertIn('RESULTADO: ENSAYO CORRECTO', texto)
        self.assertEqual(list(actualizacion.trabajo().iterdir()), [])     # sin restos
        self.assertIsNone(actualizacion.ensayo_en_curso())

    def test_paquete_con_el_nombre_de_la_3_10(self):
        """Desde la 3.10.0 el paquete es orbith.tar.gz con la carpeta orbith (sin versión)."""
        from core.actualizacion import PATRON_PAQUETE
        self.assertTrue(PATRON_PAQUETE.match('orbith.tar.gz'))
        self.assertTrue(PATRON_PAQUETE.match('orbith-3.9.2.tar.gz'))
        self.assertFalse(PATRON_PAQUETE.match('orbith (1).tar.gz'))
        texto = self._ensayar(self._paquete('orbith.tar.gz', carpeta_raiz='orbith'))
        self.assertIn('Versión del paquete: 9.9.9', texto)
        self.assertIn('RESULTADO: ENSAYO CORRECTO', texto)

    def test_ensayo_con_un_paquete_cambiado_se_detiene(self):
        texto = self._ensayar(self._paquete(estropear=True))
        self.assertIn('El paquete no está entero', texto)
        self.assertIn('ENSAYO CON ERRORES', texto)
        self.assertNotIn('Entorno de Python', texto)

    def test_lanzar_el_ensayo_desde_el_admin(self):
        from unittest import mock
        from auditoria.models import AccionAuditoria, EventoAuditoria
        from core import actualizacion
        paquete = self._paquete()
        self.client.force_login(self.admin)
        with mock.patch('core.actualizacion.subprocess.Popen') as popen:
            self.client.post(reverse('admin:soporte_actualizacion_ensayar'), {'paquete': paquete.name})
            self.assertEqual(popen.call_args.args[0][2], 'ensayar_actualizacion')
            # Con uno en marcha no se lanza otro.
            respuesta = self.client.post(reverse('admin:soporte_actualizacion_ensayar'),
                                         {'paquete': paquete.name}, follow=True)
            self.assertContains(respuesta, 'Ya hay un ensayo en marcha')
            self.assertEqual(popen.call_count, 1)
        self.assertTrue(actualizacion.ensayo_en_curso())
        self.assertTrue(EventoAuditoria.objects.filter(accion=AccionAuditoria.ACTUALIZACION,
                                                       descriptor__contains='Lanzó').exists())
