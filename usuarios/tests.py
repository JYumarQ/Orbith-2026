from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from configuracion.models import Configuracion
from .models import CustomUser


def crear_configuracion(**overrides):
    datos = {'nombre_empresa': 'Empresa de prueba'}
    datos.update(overrides)
    return Configuracion.objects.create(**datos)


class ModoMantenimientoTests(TestCase):
    def setUp(self):
        self.config = crear_configuracion()
        self.admin = CustomUser.objects.create_user(
            username='admin_test', password='ClaveSegura123', es_admin=True,
        )
        self.normal = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )

    def test_login_normal_bloqueado_durante_mantenimiento(self):
        self.config.modo_mantenimiento = True
        self.config.save()

        response = self.client.post(reverse('login'), {
            'username': 'mod_test', 'password': 'ClaveSegura123',
        })

        self.assertEqual(response.status_code, 200)  # re-renderiza el form, no redirige
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_login_admin_permitido_durante_mantenimiento(self):
        self.config.modo_mantenimiento = True
        self.config.save()

        logueado = self.client.login(username='admin_test', password='ClaveSegura123')
        self.assertTrue(logueado)

    def test_login_normal_permitido_sin_mantenimiento(self):
        logueado = self.client.login(username='mod_test', password='ClaveSegura123')
        self.assertTrue(logueado)

    def test_middleware_desconecta_usuario_normal_durante_mantenimiento(self):
        self.client.login(username='mod_test', password='ClaveSegura123')

        self.config.modo_mantenimiento = True
        self.config.save()

        response = self.client.get(reverse('list_usuarios'))
        # fetch_redirect_response=False: el fetch interno por defecto de
        # assertRedirects consumiría el mensaje flash antes de poder leerlo abajo.
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

        # El mensaje flash se guarda en la sesión nueva creada por logout(); se
        # confirma leyéndolo en la siguiente página que lo consume (login.html).
        pagina_login = self.client.get(reverse('login'))
        self.assertContains(pagina_login, 'mantenimiento')

    def test_middleware_no_afecta_a_administradores(self):
        self.client.login(username='admin_test', password='ClaveSegura123')

        self.config.modo_mantenimiento = True
        self.config.save()

        response = self.client.get(reverse('list_usuarios'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_mantenimiento_no_modifica_is_active(self):
        self.config.modo_mantenimiento = True
        self.config.save()
        self.normal.refresh_from_db()
        self.assertTrue(self.normal.is_active)

    def test_no_admin_no_puede_activar_mantenimiento(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        response = self.client.post(reverse('activar_mantenimiento'))
        self.assertEqual(response.status_code, 403)
        self.config.refresh_from_db()
        self.assertFalse(self.config.modo_mantenimiento)


class ExpulsarSesionTests(TestCase):
    def setUp(self):
        crear_configuracion()
        self.admin = CustomUser.objects.create_user(
            username='admin_test', password='ClaveSegura123', es_admin=True,
        )
        self.otro_admin = CustomUser.objects.create_user(
            username='admin_test2', password='ClaveSegura123', es_admin=True,
        )
        self.normal = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )

    def _marcar_conectado(self, usuario):
        CustomUser.objects.filter(pk=usuario.pk).update(ultima_actividad=timezone.now())

    def test_expulsar_usuario_normal_conectado(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        self.client.logout()  # solo para fijar last_login en el objeto real
        self.normal.refresh_from_db()
        self._marcar_conectado(self.normal)

        self.client.login(username='admin_test', password='ClaveSegura123')
        response = self.client.post(reverse('expulsar_sesion', args=[self.normal.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['exito'])

        self.normal.refresh_from_db()
        self.assertIsNotNone(self.normal.sesion_invalidada_en)
        self.assertTrue(self.normal.is_active)  # no se toca is_active
        self.assertFalse(self.normal.es_admin)  # ni el rol

    def test_usuario_expulsado_es_desconectado_en_su_siguiente_peticion(self):
        # Sesión real del usuario normal (login vía el cliente => last_login queda seteado).
        self.client.login(username='mod_test', password='ClaveSegura123')
        self.normal.refresh_from_db()
        self._marcar_conectado(self.normal)

        # Un segundo cliente para el Administrador, sin mezclar sesiones.
        admin_client = self.client_class()
        admin_client.login(username='admin_test', password='ClaveSegura123')
        expulsion = admin_client.post(reverse('expulsar_sesion', args=[self.normal.pk]))
        self.assertTrue(expulsion.json()['exito'])

        # El cliente del usuario normal sigue mandando la MISMA cookie de sesión.
        response = self.client.get(reverse('list_usuarios'))
        self.assertRedirects(response, reverse('login'))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_usuario_expulsado_puede_volver_a_entrar_de_inmediato(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        self._marcar_conectado(self.normal)
        self.client.logout()

        CustomUser.objects.filter(pk=self.normal.pk).update(sesion_invalidada_en=timezone.now())

        logueado = self.client.login(username='mod_test', password='ClaveSegura123')
        self.assertTrue(logueado)

    def test_admin_no_puede_expulsarse_a_si_mismo(self):
        self.client.login(username='admin_test', password='ClaveSegura123')
        self._marcar_conectado(self.admin)

        response = self.client.post(reverse('expulsar_sesion', args=[self.admin.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['exito'])

        self.admin.refresh_from_db()
        self.assertIsNone(self.admin.sesion_invalidada_en)

    def test_admin_no_puede_expulsar_a_otro_admin(self):
        self.client.login(username='admin_test', password='ClaveSegura123')
        self._marcar_conectado(self.otro_admin)

        response = self.client.post(reverse('expulsar_sesion', args=[self.otro_admin.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['exito'])

        self.otro_admin.refresh_from_db()
        self.assertIsNone(self.otro_admin.sesion_invalidada_en)

    def test_no_se_puede_expulsar_usuario_desconectado(self):
        self.client.login(username='admin_test', password='ClaveSegura123')
        # self.normal nunca registró actividad => esta_conectado es False.
        response = self.client.post(reverse('expulsar_sesion', args=[self.normal.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['exito'])

    def test_no_admin_no_puede_expulsar(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        response = self.client.post(reverse('expulsar_sesion', args=[self.otro_admin.pk]))
        self.assertEqual(response.status_code, 403)


class UsuarioInactivoTests(TestCase):
    def setUp(self):
        crear_configuracion()

    def test_usuario_inactivo_no_puede_iniciar_sesion_sin_mantenimiento(self):
        CustomUser.objects.create_user(
            username='inactivo_test', password='ClaveSegura123', es_moderador=True, is_active=False,
        )
        logueado = self.client.login(username='inactivo_test', password='ClaveSegura123')
        self.assertFalse(logueado)


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar un usuario desde el Admin de Django ahora deja rastro
    en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin` (compartido con
    el resto de apps, ver `contratos.tests.AuditoriaAdminTests` para el caso
    original que motivó esto). `CustomUserAdmin` ya tenía su propio `save_model`
    (valida que solo quede un rol marcado); esta prueba confirma que ambos
    cooperan por `super()` en vez de que uno pise al otro."""

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='admin_usuarios', password='ClaveSegura123', es_admin=True)

    def test_eliminar_un_usuario_en_el_admin_queda_auditado(self):
        from django.urls import reverse

        from auditoria.models import EventoAuditoria

        objetivo = CustomUser.objects.create_user(
            username='usuario_a_borrar', password='ClaveSegura123', es_moderador=True)
        self.client.force_login(self.admin)

        url = reverse('admin:usuarios_customuser_delete', args=[objetivo.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(CustomUser.objects.filter(pk=objetivo.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(objetivo.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'usuarios')

    def test_editar_un_usuario_desde_el_admin_queda_auditado(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from auditoria.models import EventoAuditoria
        from usuarios.admin import CustomUserAdmin

        objetivo = CustomUser.objects.create_user(
            username='usuario_a_editar', password='ClaveSegura123', es_moderador=True)

        admin_instance = CustomUserAdmin(CustomUser, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        objetivo.email = 'nuevo@correo.test'
        admin_instance.save_model(request, objetivo, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(objetivo.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
