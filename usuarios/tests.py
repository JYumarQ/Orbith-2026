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


class GestionDeUsuariosSoloAdminTests(TestCase):
    """Las pantallas de gestión de usuarios son exclusivas del Administrador.

    Ocultar el enlace en la barra lateral no basta: hay que comprobar que un
    Moderador que escriba la URL a mano (o al que el sistema redirija ahí por
    error) recibe un 403 y no ve el listado de cuentas del sistema.
    """

    def setUp(self):
        crear_configuracion()
        self.admin = CustomUser.objects.create_user(
            username='admin_test', password='ClaveSegura123', es_admin=True,
        )
        self.moderador = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )
        self.observador = CustomUser.objects.create_user(
            username='obs_test', password='ClaveSegura123', es_observador=True,
        )

    def _urls_de_gestion(self):
        return [
            reverse('list_usuarios'),
            reverse('add_usuario'),
            reverse('updt_usuario', args=[self.moderador.pk]),
            reverse('del_usuario', args=[self.moderador.pk]),
            reverse('search_usuarios'),
            reverse('validar_username'),
        ]

    def test_moderador_no_accede_a_la_gestion_de_usuarios(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        for url in self._urls_de_gestion():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_observador_no_accede_a_la_gestion_de_usuarios(self):
        self.client.login(username='obs_test', password='ClaveSegura123')
        for url in self._urls_de_gestion():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_si_accede_al_listado(self):
        self.client.login(username='admin_test', password='ClaveSegura123')
        self.assertEqual(self.client.get(reverse('list_usuarios')).status_code, 200)

    def test_moderador_no_borra_usuarios_por_url(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        respuesta = self.client.get(reverse('del_usuario', args=[self.observador.pk]))
        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(CustomUser.objects.filter(pk=self.observador.pk).exists())


class CambiarPasswordTests(TestCase):
    """Cada usuario cambia su propia contraseña; solo el Administrador la de otros.

    Y, sobre todo: al terminar NO se puede acabar en `list_usuarios`, que es una
    pantalla exclusiva del Administrador.
    """

    def setUp(self):
        crear_configuracion()
        self.admin = CustomUser.objects.create_user(
            username='admin_test', password='ClaveSegura123', es_admin=True,
        )
        self.moderador = CustomUser.objects.create_user(
            username='mod_test', password='ClaveSegura123', es_moderador=True,
        )
        self.otro_moderador = CustomUser.objects.create_user(
            username='mod2_test', password='ClaveSegura123', es_moderador=True,
        )

    def _datos(self, clave='NuevaClave123', next=''):
        return {'new_password1': clave, 'new_password2': clave, 'next': next}

    def test_moderador_cambia_su_clave_y_no_acaba_en_el_listado(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        url = reverse('cambiar_password', args=[self.moderador.pk])

        respuesta = self.client.post(url, self._datos())

        self.assertRedirects(respuesta, reverse('dashboard'), fetch_redirect_response=False)
        self.assertNotIn(reverse('list_usuarios'), respuesta['Location'])
        self.moderador.refresh_from_db()
        self.assertTrue(self.moderador.check_password('NuevaClave123'))

    def test_moderador_vuelve_a_la_pagina_desde_la_que_abrio_el_modal(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        url = reverse('cambiar_password', args=[self.moderador.pk])

        respuesta = self.client.post(url, self._datos(next=reverse('dashboard')))

        self.assertRedirects(respuesta, reverse('dashboard'), fetch_redirect_response=False)

    def test_next_a_otro_dominio_se_ignora(self):
        """Nadie puede usar el cambio de contraseña como redirección abierta."""
        self.client.login(username='mod_test', password='ClaveSegura123')
        url = reverse('cambiar_password', args=[self.moderador.pk])

        respuesta = self.client.post(url, self._datos(next='https://sitio-malicioso.example/'))

        self.assertEqual(respuesta['Location'], reverse('dashboard'))

    def test_moderador_sigue_conectado_tras_cambiar_su_clave(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        self.client.post(reverse('cambiar_password', args=[self.moderador.pk]), self._datos())

        respuesta = self.client.get(reverse('dashboard'))
        self.assertTrue(respuesta.wsgi_request.user.is_authenticated)

    def test_moderador_no_puede_cambiar_la_clave_de_otro(self):
        self.client.login(username='mod_test', password='ClaveSegura123')
        url = reverse('cambiar_password', args=[self.otro_moderador.pk])

        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.post(url, self._datos())
        self.otro_moderador.refresh_from_db()
        self.assertTrue(self.otro_moderador.check_password('ClaveSegura123'))

    def test_admin_cambia_la_clave_de_otro_sin_perder_su_sesion(self):
        """`update_session_auth_hash` solo debe aplicarse a la propia cuenta."""
        self.client.login(username='admin_test', password='ClaveSegura123')

        self.client.post(reverse('cambiar_password', args=[self.moderador.pk]), self._datos())

        self.moderador.refresh_from_db()
        self.assertTrue(self.moderador.check_password('NuevaClave123'))

        respuesta = self.client.get(reverse('list_usuarios'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.wsgi_request.user.is_authenticated)


class BorradoDeUsuarioTests(TestCase):
    """Confirmación del borrado y bloqueo por datos a cargo del usuario.

    Antes de esto, `del_usuario` borraba con un GET y sin confirmación: bastaba
    visitar la URL. Estas pruebas fijan las tres cosas que se corrigieron —el
    método, la confirmación y el bloqueo por dependencias— para que no puedan
    volver atrás sin que salte algo.
    """

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='admin_borrado', password='ClaveSegura123', es_admin=True)
        self.sobrante = CustomUser.objects.create_user(
            username='sobrante', password='ClaveSegura123', es_observador=True)
        self.client.force_login(self.admin)

    def url(self, usuario):
        return reverse('del_usuario', args=[usuario.pk])

    # --- El método: ya no se borra con un GET --------------------------------

    def test_un_get_no_borra_nada(self):
        """Era el agujero real: Django no protege los GET con CSRF, así que un
        enlace externo bastaba para borrar una cuenta."""
        respuesta = self.client.get(self.url(self.sobrante))

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(CustomUser.objects.filter(pk=self.sobrante.pk).exists())

    def test_el_get_devuelve_la_confirmacion(self):
        respuesta = self.client.get(self.url(self.sobrante))
        self.assertContains(respuesta, 'no se puede deshacer')
        self.assertContains(respuesta, 'sobrante')

    def test_el_post_si_borra_cuando_no_hay_impedimentos(self):
        self.client.post(self.url(self.sobrante))
        self.assertFalse(CustomUser.objects.filter(pk=self.sobrante.pk).exists())

    # --- El bloqueo por dependencias -----------------------------------------

    def _con_unidad(self):
        from nomencladores.models import NTipoUnidadOrganizativa
        from strorganizativa.models import UnidadOrganizativa

        tipo = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Prueba', tipo=tipo, grupo_nomina=1, orden_informe=1)
        moderador = CustomUser.objects.create_user(
            username='mod_con_unidad', password='ClaveSegura123', es_moderador=True)
        moderador.unidades.add(unidad)
        return moderador

    def test_no_se_borra_un_moderador_con_unidades(self):
        moderador = self._con_unidad()
        self.client.post(self.url(moderador))
        self.assertTrue(CustomUser.objects.filter(pk=moderador.pk).exists())

    def test_la_confirmacion_explica_que_lo_impide(self):
        moderador = self._con_unidad()
        respuesta = self.client.get(self.url(moderador))

        self.assertContains(respuesta, 'No se puede eliminar')
        self.assertContains(respuesta, 'UEB Prueba')
        # Y no ofrece el botón de borrar.
        self.assertNotContains(respuesta, 'btn-danger')

    def test_la_confirmacion_recomienda_reutilizar_la_cuenta(self):
        """Casi siempre es la salida buena: cambiar usuario, contraseña y
        contrato conserva unidades, plantillas y calendarios."""
        moderador = self._con_unidad()
        respuesta = self.client.get(self.url(moderador))

        self.assertContains(respuesta, 'Reutilizarla')
        self.assertContains(respuesta, 'Editar usuario')
        self.assertContains(respuesta, 'Cambiar contraseña')
        # La segunda salida: inhabilitar en lugar de borrar.
        self.assertContains(respuesta, 'Inhabilitar cuenta')

    def test_no_se_borra_un_usuario_con_plantillas(self):
        from prenomina.models import NPagoHoras
        from prenomina import servicios_plantilla

        NPagoHoras.objects.create(codigo=7, descripcion='Concepto')
        servicios_plantilla.crear_plantilla(
            self.sobrante, descripcion='La suya', codigos_horas=[7])

        self.client.post(self.url(self.sobrante))
        self.assertTrue(CustomUser.objects.filter(pk=self.sobrante.pk).exists())

    def test_no_se_borra_un_usuario_con_calendarios(self):
        from prenomina import servicios_calendario

        servicios_calendario.crear_calendario(
            self.sobrante, codigo=1, descripcion='Jornada')

        self.client.post(self.url(self.sobrante))
        self.assertTrue(CustomUser.objects.filter(pk=self.sobrante.pk).exists())

    # --- Permisos ------------------------------------------------------------

    def test_un_moderador_no_puede_borrar_usuarios(self):
        """La ruta va envuelta en `admin_required` (ver usuarios/urls.py)."""
        moderador = CustomUser.objects.create_user(
            username='mod_curioso', password='ClaveSegura123', es_moderador=True)
        self.client.force_login(moderador)

        self.client.post(self.url(self.sobrante))
        self.assertTrue(CustomUser.objects.filter(pk=self.sobrante.pk).exists())


class BorradoDeAdministradoresTests(TestCase):
    """Las dos reglas de rol: entre iguales nadie decide, y nunca sin admins.

    Se prueban aparte de `BorradoDeUsuarioTests` porque el escenario es otro:
    aquí lo que manda es quién borra a quién, no qué datos cuelgan del usuario.
    """

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='admin_uno', password='ClaveSegura123', es_admin=True)
        self.otro_admin = CustomUser.objects.create_user(
            username='admin_dos', password='ClaveSegura123', es_admin=True)
        self.client.force_login(self.admin)

    def url(self, usuario):
        return reverse('del_usuario', args=[usuario.pk])

    # --- Un administrador solo se elimina a sí mismo -------------------------

    def test_un_admin_no_puede_eliminar_a_otro_admin(self):
        self.client.post(self.url(self.otro_admin))
        self.assertTrue(CustomUser.objects.filter(pk=self.otro_admin.pk).exists())

    def test_la_confirmacion_explica_la_regla_sin_dar_rodeos(self):
        """Se dice qué no se puede hacer; el camino alternativo no se detalla."""
        respuesta = self.client.get(self.url(self.otro_admin))

        self.assertContains(respuesta, 'solo puede eliminar su propia cuenta')
        self.assertNotContains(respuesta, 'btn-danger')
        # No se sugiere degradar el rol para saltarse la regla.
        self.assertNotContains(respuesta, 'Moderador u Observador')

    def test_un_admin_si_puede_eliminarse_a_si_mismo(self):
        self.client.post(self.url(self.admin))
        self.assertFalse(CustomUser.objects.filter(pk=self.admin.pk).exists())

    def test_al_borrarse_a_si_mismo_cierra_sesion_y_va_al_login(self):
        respuesta = self.client.post(self.url(self.admin))

        self.assertRedirects(respuesta, reverse('login'),
                             fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_la_confirmacion_avisa_de_que_perdera_la_sesion(self):
        respuesta = self.client.get(self.url(self.admin))
        self.assertContains(respuesta, 'Eliminar su propia cuenta')
        self.assertContains(respuesta, 'cerrará su sesión')

    # --- Nunca sin administradores ------------------------------------------

    def test_no_se_borra_al_ultimo_admin_activo(self):
        """Sin ninguno, la única salida sería crear un superusuario por consola."""
        self.otro_admin.is_active = False
        self.otro_admin.save(update_fields=['is_active'])

        self.client.post(self.url(self.admin))

        self.assertTrue(CustomUser.objects.filter(pk=self.admin.pk).exists())

    def test_la_confirmacion_explica_que_es_el_ultimo(self):
        self.otro_admin.is_active = False
        self.otro_admin.save(update_fields=['is_active'])

        respuesta = self.client.get(self.url(self.admin))
        self.assertContains(respuesta, 'único Administrador activo')

    # --- Inhabilitar como alternativa ---------------------------------------

    def test_a_un_admin_no_se_le_ofrece_inhabilitar(self):
        """Dejar fuera a un igual es justo lo que impide la regla de rol."""
        respuesta = self.client.get(self.url(self.otro_admin))
        self.assertNotContains(respuesta, 'Inhabilitar')

    def test_inhabilitar_a_un_admin_se_rechaza_aunque_se_fuerce_el_post(self):
        self.client.post(reverse('inhabilitar_usuario', args=[self.otro_admin.pk]))
        self.otro_admin.refresh_from_db()
        self.assertTrue(self.otro_admin.is_active)

    def test_inhabilitar_a_un_no_admin_funciona(self):
        moderador = CustomUser.objects.create_user(
            username='mod_a_inhabilitar', password='ClaveSegura123',
            es_moderador=True)

        self.client.post(reverse('inhabilitar_usuario', args=[moderador.pk]))

        moderador.refresh_from_db()
        self.assertFalse(moderador.is_active)
        # Inhabilitar NO borra: es lo que conserva su rastro y sus datos.
        self.assertTrue(CustomUser.objects.filter(pk=moderador.pk).exists())

    def test_se_ofrece_inhabilitar_a_un_usuario_normal(self):
        moderador = CustomUser.objects.create_user(
            username='mod_normal', password='ClaveSegura123', es_moderador=True)
        respuesta = self.client.get(self.url(moderador))
        self.assertContains(respuesta, 'Inhabilitar')

    def test_un_moderador_no_puede_inhabilitar_a_nadie(self):
        curioso = CustomUser.objects.create_user(
            username='mod_curioso2', password='ClaveSegura123', es_moderador=True)
        victima = CustomUser.objects.create_user(
            username='victima', password='ClaveSegura123', es_observador=True)
        self.client.force_login(curioso)

        self.client.post(reverse('inhabilitar_usuario', args=[victima.pk]))

        victima.refresh_from_db()
        self.assertTrue(victima.is_active)


class EjecutarTodosLosAnalisisTests(TestCase):
    """Botón «Ejecutar todos los análisis» de la lista de Usuarios.

    Se comprueba el contrato de la vista, no lo que detecta cada regla: que solo
    entre un Administrador, que use el escaneo GLOBAL (no el del usuario que pulsa),
    que arranque la cadena de Subsanación y que un análisis ya en curso no impida los
    dos pasos anteriores.
    """

    def setUp(self):
        self.url = reverse('ejecutar_todos_los_analisis')
        self.admin = CustomUser.objects.create_user(
            username='admin_analisis', password='ClaveSegura123', es_admin=True,
        )
        self.moderador = CustomUser.objects.create_user(
            username='mod_analisis', password='ClaveSegura123', es_moderador=True,
        )

    def test_un_moderador_no_puede_lanzarlo(self):
        self.client.login(username='mod_analisis', password='ClaveSegura123')

        respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 403)

    def test_get_no_esta_permitido(self):
        self.client.login(username='admin_analisis', password='ClaveSegura123')

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 405)

    def test_ejecuta_los_tres_pasos_y_abre_la_ejecucion(self):
        from unittest.mock import patch

        from subsanacion.models import EjecucionAnalisis

        self.client.login(username='admin_analisis', password='ClaveSegura123')

        with patch('notificaciones.escaneo.escanear_globalmente_y_notificar_por_unidad',
                   return_value={'notificados': 3, 'sin_unidad': 1}) as escaneo, \
             patch('notificaciones.recordatorios.generar_recordatorios',
                   return_value={'generados': 2, 'sin_unidad': 0}) as recordatorios:
            respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 200)
        escaneo.assert_called_once_with()
        recordatorios.assert_called_once_with()

        contenido = respuesta.content.decode()
        self.assertIn('3 incidencia(s) notificada(s)', contenido)
        self.assertIn('2 recordatorio(s) actualizado(s)', contenido)

        # El tercer paso solo se ABRE: la cadena continúa por HTMX.
        ejecucion = EjecucionAnalisis.objects.get()
        self.assertEqual(ejecucion.estado, EjecucionAnalisis.EN_CURSO)
        self.assertEqual(ejecucion.origen, EjecucionAnalisis.MANTENIMIENTO)
        self.assertEqual(ejecucion.lanzada_por, self.admin)

    def test_usa_el_escaneo_global_y_no_el_del_usuario_que_pulsa(self):
        """`escanear_para_usuario()` solo notifica a quien pulsa; aquí no sirve."""
        from unittest.mock import patch

        self.client.login(username='admin_analisis', password='ClaveSegura123')

        with patch('notificaciones.escaneo.escanear_para_usuario') as por_usuario, \
             patch('notificaciones.escaneo.escanear_globalmente_y_notificar_por_unidad',
                   return_value={'notificados': 0, 'sin_unidad': 0}), \
             patch('notificaciones.recordatorios.generar_recordatorios',
                   return_value={'generados': 0, 'sin_unidad': 0}):
            self.client.post(self.url)

        por_usuario.assert_not_called()

    def test_un_analisis_en_curso_no_impide_los_dos_primeros_pasos(self):
        from unittest.mock import patch

        from subsanacion.models import EjecucionAnalisis

        EjecucionAnalisis.objects.create(estado=EjecucionAnalisis.EN_CURSO)
        self.client.login(username='admin_analisis', password='ClaveSegura123')

        with patch('notificaciones.escaneo.escanear_globalmente_y_notificar_por_unidad',
                   return_value={'notificados': 5, 'sin_unidad': 0}) as escaneo, \
             patch('notificaciones.recordatorios.generar_recordatorios',
                   return_value={'generados': 1, 'sin_unidad': 0}) as recordatorios:
            respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 200)
        escaneo.assert_called_once_with()
        recordatorios.assert_called_once_with()
        self.assertIn('Ya hab\u00eda un an\u00e1lisis en curso', respuesta.content.decode())
        # No se abrió una segunda ejecución.
        self.assertEqual(EjecucionAnalisis.objects.count(), 1)

    def test_si_falla_un_paso_los_demas_siguen(self):
        from unittest.mock import patch

        from subsanacion.models import EjecucionAnalisis

        self.client.login(username='admin_analisis', password='ClaveSegura123')

        with patch('notificaciones.escaneo.escanear_globalmente_y_notificar_por_unidad',
                   side_effect=RuntimeError('fallo simulado')), \
             patch('notificaciones.recordatorios.generar_recordatorios',
                   return_value={'generados': 4, 'sin_unidad': 0}) as recordatorios:
            respuesta = self.client.post(self.url)

        self.assertEqual(respuesta.status_code, 200)
        recordatorios.assert_called_once_with()
        self.assertIn('fallo simulado', respuesta.content.decode())
        self.assertEqual(EjecucionAnalisis.objects.count(), 1)
