"""Seguridad del inicio de sesión: bloqueo por fuerza bruta, caducidad de sesión
por inactividad, auditoría de accesos y ayuda desde el login.

Va en un módulo aparte de `usuarios/tests.py` por tamaño: ese fichero ya cubre
mantenimiento, expulsión de sesiones, permisos y borrado. El descubridor de
Django recoge cualquier fichero `test*.py`, así que `manage.py test usuarios`
sigue ejecutándolo todo.
"""

from datetime import timedelta

from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auditoria.models import AccionAuditoria, EventoAuditoria
from configuracion.models import Configuracion
from soporte.models import ReporteProblema
from soporte.views import MAXIMO_AYUDAS_POR_IP_HORA

from .middleware import CLAVE_ACTIVIDAD, INACTIVIDAD_MAXIMA
from .models import (
    MAX_INTENTOS_FALLIDOS, VENTANA_BLOQUEO, CustomUser, IntentoAcceso,
)


def crear_configuracion(**overrides):
    datos = {'nombre_empresa': 'Empresa de prueba'}
    datos.update(overrides)
    return Configuracion.objects.create(**datos)


class BloqueoPorIntentosFallidosTests(TestCase):
    """Fuerza bruta: la cuenta deja de admitir intentos tras MAX_INTENTOS_FALLIDOS."""

    def setUp(self):
        self.usuario = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )
        self.url = reverse('login')

    def _fallar(self, veces, username='mod_test'):
        for _ in range(veces):
            self.client.post(self.url, {'username': username, 'password': 'incorrecta'})

    def test_los_fallos_se_registran(self):
        self._fallar(3)
        self.assertEqual(IntentoAcceso.objects.filter(username='mod_test').count(), 3)

    def test_el_nombre_se_normaliza_a_minusculas(self):
        """Sin normalizar, alternar mayúsculas bastaría para no llegar al tope."""
        self._fallar(1, username='MOD_TEST')
        self.assertEqual(IntentoAcceso.objects.filter(username='mod_test').count(), 1)

    def test_por_debajo_del_tope_se_puede_entrar(self):
        self._fallar(MAX_INTENTOS_FALLIDOS - 1)
        respuesta = self.client.post(
            self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})
        self.assertEqual(respuesta.status_code, 302)

    def test_al_llegar_al_tope_se_bloquea_aunque_la_clave_sea_correcta(self):
        self._fallar(MAX_INTENTOS_FALLIDOS)
        respuesta = self.client.post(
            self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})
        self.assertEqual(respuesta.status_code, 200)  # no redirige: no entró
        self.assertContains(respuesta, 'Demasiados intentos fallidos')

    def test_el_bloqueo_no_se_alarga_al_reintentar(self):
        """Si cada intento durante el bloqueo sumara, el bloqueo no terminaría
        nunca mientras alguien siguiera probando, y un usuario legítimo que
        reintenta a los dos minutos se auto-castigaría cinco minutos más."""
        self._fallar(MAX_INTENTOS_FALLIDOS)
        limite = IntentoAcceso.bloqueado_hasta('mod_test')

        self._fallar(5)

        self.assertEqual(IntentoAcceso.objects.count(), MAX_INTENTOS_FALLIDOS)
        self.assertEqual(IntentoAcceso.bloqueado_hasta('mod_test'), limite)

    def test_el_bloqueo_caduca_al_salir_de_la_ventana(self):
        self._fallar(MAX_INTENTOS_FALLIDOS)
        self.assertIsNotNone(IntentoAcceso.bloqueado_hasta('mod_test'))

        antiguo = timezone.now() - VENTANA_BLOQUEO - timedelta(seconds=1)
        IntentoAcceso.objects.update(fecha=antiguo)

        self.assertIsNone(IntentoAcceso.bloqueado_hasta('mod_test'))
        respuesta = self.client.post(
            self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})
        self.assertEqual(respuesta.status_code, 302)

    def test_el_bloqueo_es_por_cuenta_y_no_afecta_a_las_demas(self):
        CustomUser.objects.create_user(
            username='otro_test', password='ClaveSegura123', es_observador=True)
        self._fallar(MAX_INTENTOS_FALLIDOS)

        respuesta = self.client.post(
            self.url, {'username': 'otro_test', 'password': 'ClaveSegura123'})
        self.assertEqual(respuesta.status_code, 302)

    def test_entrar_correctamente_limpia_los_fallos_previos(self):
        self._fallar(3)
        self.client.post(self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})
        self.assertEqual(IntentoAcceso.objects.filter(username='mod_test').count(), 0)

    def test_el_bloqueo_tambien_cubre_el_admin_de_django(self):
        """El panel de administración usa OTRO formulario. Si el bloqueo viviera
        solo en el formulario del login, bastaría atacar /admin/login/ para
        saltárselo; por eso vive en el backend de autenticación."""
        self._fallar(MAX_INTENTOS_FALLIDOS)
        self.assertIsNone(authenticate(username='mod_test', password='ClaveSegura123'))


class AuditoriaDeAccesosTests(TestCase):

    def setUp(self):
        self.usuario = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )
        self.url = reverse('login')

    def test_el_acceso_correcto_queda_auditado(self):
        self.client.post(self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})

        evento = EventoAuditoria.objects.filter(accion=AccionAuditoria.ACCESO).first()
        self.assertIsNotNone(evento)
        self.assertEqual(evento.usuario, self.usuario)
        self.assertEqual(evento.modulo, 'usuarios')

    def test_el_intento_fallido_queda_auditado_sin_usuario(self):
        self.client.post(self.url, {'username': 'mod_test', 'password': 'mala'})

        evento = EventoAuditoria.objects.filter(
            accion=AccionAuditoria.ACCESO_FALLIDO).first()
        self.assertIsNotNone(evento)
        self.assertIsNone(evento.usuario)
        self.assertIn('mod_test', evento.descriptor)

    def test_nunca_se_guarda_la_contrasena(self):
        self.client.post(self.url, {'username': 'mod_test', 'password': 'SuperSecreta9'})

        for evento in EventoAuditoria.objects.all():
            self.assertNotIn('SuperSecreta9', evento.descriptor)
            self.assertNotIn('SuperSecreta9', str(evento.datos_antes))
            self.assertNotIn('SuperSecreta9', str(evento.datos_despues))

    def test_el_cierre_de_sesion_queda_auditado(self):
        self.client.post(self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})
        self.client.post(reverse('logout'))

        self.assertTrue(
            EventoAuditoria.objects.filter(accion=AccionAuditoria.SALIDA).exists())

    def test_un_fallo_en_auditoria_no_impide_entrar(self):
        """Regla de `usuarios/signals.py`: el rastro nunca puede dejar a la
        empresa sin poder iniciar sesión."""
        from unittest.mock import patch

        with patch('usuarios.signals.registrar', side_effect=Exception('BD caída')):
            respuesta = self.client.post(
                self.url, {'username': 'mod_test', 'password': 'ClaveSegura123'})

        self.assertEqual(respuesta.status_code, 302)


class CaducidadPorInactividadTests(TestCase):

    def setUp(self):
        crear_configuracion()
        self.usuario = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )
        self.client.force_login(self.usuario)

    def _envejecer_sesion(self, delta):
        """Retrasa la marca de actividad para simular tiempo sin usar Orbith."""
        sesion = self.client.session
        sesion[CLAVE_ACTIVIDAD] = (timezone.now() - delta).timestamp()
        sesion.save()

    def test_una_sesion_activa_no_se_cierra(self):
        self._envejecer_sesion(INACTIVIDAD_MAXIMA - timedelta(minutes=1))
        respuesta = self.client.get(reverse('dashboard'))
        self.assertEqual(respuesta.status_code, 200)

    def test_la_sesion_inactiva_se_cierra(self):
        self._envejecer_sesion(INACTIVIDAD_MAXIMA + timedelta(minutes=1))
        respuesta = self.client.get(reverse('dashboard'))
        self.assertRedirects(respuesta, reverse('login'))

    def test_el_sondeo_de_notificaciones_no_mantiene_viva_la_sesion(self):
        """Es el caso que motiva todo esto: templates/base/navbar.html consulta
        el contador de notificaciones cada 5 minutos, así que una pestaña
        olvidada nunca dejaría caducar la sesión si ese sondeo contara como
        actividad del usuario."""
        self._envejecer_sesion(INACTIVIDAD_MAXIMA - timedelta(minutes=1))

        self.client.get(reverse('notificaciones_json'))

        # La marca NO se movió: sigue contando desde antes del sondeo.
        inactivo = timezone.now().timestamp() - self.client.session[CLAVE_ACTIVIDAD]
        self.assertGreater(inactivo, 60)

    def test_una_peticion_normal_si_renueva_la_sesion(self):
        self._envejecer_sesion(INACTIVIDAD_MAXIMA - timedelta(minutes=1))

        self.client.get(reverse('dashboard'))

        inactivo = timezone.now().timestamp() - self.client.session[CLAVE_ACTIVIDAD]
        self.assertLess(inactivo, 10)


class UrlsDeAutenticacionTests(TestCase):
    """Las rutas de Django que quedaban publicadas SIN plantilla ya no existen."""

    def test_el_reseteo_de_contrasena_de_django_ya_no_esta_publicado(self):
        self.assertEqual(self.client.get('/accounts/password_reset/').status_code, 404)

    def test_el_cambio_de_contrasena_de_django_ya_no_esta_publicado(self):
        self.assertEqual(self.client.get('/accounts/password_change/').status_code, 404)

    def test_login_y_logout_siguen_existiendo(self):
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)
        self.assertEqual(reverse('logout'), '/accounts/logout/')

    def test_quien_ya_tiene_sesion_no_ve_el_formulario(self):
        crear_configuracion()
        usuario = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True)
        self.client.force_login(usuario)

        self.assertEqual(self.client.get(reverse('login')).status_code, 302)


class FormularioDeLoginTests(TestCase):

    def test_el_usuario_se_repuebla_tras_un_fallo(self):
        """Antes los <input> estaban escritos a mano en la plantilla y el usuario
        tenía que reescribir su nombre en cada intento fallido."""
        CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True)

        respuesta = self.client.post(
            reverse('login'), {'username': 'mod_test', 'password': 'mala'})

        self.assertContains(respuesta, 'value="mod_test"')

    def test_los_campos_llevan_los_atributos_del_navegador(self):
        respuesta = self.client.get(reverse('login'))
        self.assertContains(respuesta, 'autocomplete="current-password"')
        self.assertContains(respuesta, 'autocomplete="username"')
        self.assertContains(respuesta, 'autocapitalize="none"')

    def test_el_boton_de_ver_contrasena_esta_presente(self):
        respuesta = self.client.get(reverse('login'))
        self.assertContains(respuesta, 'id="btnVerClave"')
        self.assertContains(respuesta, 'id="id_password"')


class AyudaDeAccesoSinLoginTests(TestCase):
    """El enlace «¿Problemas para acceder?» de la pantalla de login."""

    def setUp(self):
        self.url = reverse('soporte:crear_reporte_acceso')
        self.datos = {
            'usuario_declarado': 'jperez',
            'mensaje': 'No consigo entrar, me dice usuario o contraseña incorrectos.',
        }

    def test_se_puede_enviar_sin_iniciar_sesion(self):
        respuesta = self.client.post(self.url, self.datos)

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json()['exito'])

        reporte = ReporteProblema.objects.get()
        self.assertIsNone(reporte.usuario)
        self.assertEqual(reporte.usuario_declarado, 'jperez')
        self.assertIn('Login', reporte.url_origen)

    def test_el_nombre_declarado_no_se_confunde_con_un_usuario_real(self):
        self.client.post(self.url, self.datos)
        self.assertIn('sin autenticar', ReporteProblema.objects.get().autor_legible)

    def test_un_mensaje_demasiado_corto_se_rechaza(self):
        respuesta = self.client.post(
            self.url, {'usuario_declarado': 'jperez', 'mensaje': 'nada'})

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(ReporteProblema.objects.count(), 0)

    def test_no_se_admiten_peticiones_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_hay_tope_por_equipo_y_hora(self):
        """Es la única entrada de datos abierta a quien no ha iniciado sesión:
        sin tope, cualquiera inundaría la bandeja del Administrador."""
        for _ in range(MAXIMO_AYUDAS_POR_IP_HORA):
            self.client.post(self.url, self.datos)

        respuesta = self.client.post(self.url, self.datos)

        self.assertEqual(respuesta.status_code, 429)
        self.assertEqual(ReporteProblema.objects.count(), MAXIMO_AYUDAS_POR_IP_HORA)


class ReglasDeContrasenaTests(TestCase):
    """Un único criterio de contraseña en los tres sitios donde se fija una.

    Antes cada camino aplicaba reglas distintas: el alta usaba los validadores
    de Django (con los mensajes en inglés) y el cambio desde «Mi Perfil» tres
    comprobaciones escritas a mano que se saltaban la lista de contraseñas
    comunes. El agujero concreto que se cierra aquí: el cambio ACEPTABA claves
    que el alta rechazaba.
    """

    CLAVE_VALIDA = 'NuevaClave123'

    def setUp(self):
        crear_configuracion()
        self.moderador = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )
        self.client.login(username='mod_test', password='ClaveSegura123')
        self.url = reverse('cambiar_password', args=[self.moderador.pk])

    def _cambiar(self, clave):
        return self.client.post(
            self.url, {'new_password1': clave, 'new_password2': clave, 'next': ''})

    def _errores(self, respuesta):
        return respuesta.context['form'].errors.get('new_password1', [])

    # ---------- el agujero que motivó el cambio ----------
    def test_una_clave_comun_ya_no_pasa_el_cambio(self):
        """`Password1` cumple las tres reglas antiguas (8 caracteres, mayúscula
        y dígito) y es de las contraseñas más usadas del mundo."""
        respuesta = self._cambiar('Password1')

        self.assertEqual(respuesta.status_code, 200)  # no redirige: no se guardó
        self.moderador.refresh_from_db()
        self.assertFalse(self.moderador.check_password('Password1'))

    def test_una_clave_parecida_al_usuario_se_rechaza(self):
        respuesta = self._cambiar('Mod_test1')

        self.moderador.refresh_from_db()
        self.assertFalse(self.moderador.check_password('Mod_test1'))
        self.assertTrue(self._errores(respuesta))

    # ---------- las reglas que ya existían siguen ahí ----------
    def test_sigue_exigiendose_mayuscula(self):
        self.assertTrue(self._errores(self._cambiar('clavelarga123')))

    def test_sigue_exigiendose_un_digito(self):
        self.assertTrue(self._errores(self._cambiar('ClaveLargaSinNumero')))

    def test_sigue_exigiendose_la_longitud_minima(self):
        self.assertTrue(self._errores(self._cambiar('Cort1')))

    # ---------- una clave buena sigue funcionando ----------
    def test_una_clave_valida_se_guarda(self):
        self._cambiar(self.CLAVE_VALIDA)

        self.moderador.refresh_from_db()
        self.assertTrue(self.moderador.check_password(self.CLAVE_VALIDA))

    # ---------- idioma ----------
    def test_los_mensajes_estan_en_espanol(self):
        """El proyecto va con LANGUAGE_CODE='en-us', así que sin los validadores
        propios el usuario leería "This password is too common."."""
        errores = ' '.join(str(e) for e in self._errores(self._cambiar('password')))

        self.assertNotIn('This password', errores)
        self.assertIn('contraseña', errores)

    # ---------- el mismo criterio en el alta ----------
    def test_el_alta_de_usuario_aplica_las_mismas_reglas(self):
        from .forms import CustomUserCreationForm

        comun = CustomUserCreationForm(data={
            'username': 'nuevo', 'password1': 'Password1', 'password2': 'Password1',
            'es_observador': True,
        })
        self.assertFalse(comun.is_valid())
        self.assertIn('password2', comun.errors)

        valida = CustomUserCreationForm(data={
            'username': 'nuevo', 'password1': self.CLAVE_VALIDA,
            'password2': self.CLAVE_VALIDA, 'es_observador': True,
        })
        self.assertTrue(valida.is_valid(), valida.errors.as_data())
