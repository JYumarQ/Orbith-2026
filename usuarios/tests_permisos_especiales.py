"""Permisos especiales de Moderadores (25-10-2026): perfiles, caducidad, límites,
marca en Auditoría, aviso por la campana y cada uno de los siete permisos."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CustomUser, PerfilPermisos
from .permisos_especiales import (CODIGOS, con_permiso, foto_de_asignacion, perfil_vigente,
                                  puede_resolver, registrar_cambio_de_perfil, tiene_permiso,
                                  usuarios_con_permiso)


class PermisosEspecialesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username='adm_pe', password='x', es_admin=True)
        cls.todo = PerfilPermisos.objects.create(nombre='Todo', **{c: True for c in CODIGOS})
        cls.solo_nomenclador = PerfilPermisos.objects.create(nombre='Nomencladores', nomencladores=True)
        cls.moderador = CustomUser.objects.create_user(username='mod_pe', password='x', es_moderador=True)
        cls.otro = CustomUser.objects.create_user(username='mod_pe2', password='x', es_moderador=True)
        cls.observador = CustomUser.objects.create_user(username='obs_pe', password='x', es_observador=True)

    def asignar(self, perfil, vence=None, usuario=None):
        usuario = usuario or self.moderador
        CustomUser.objects.filter(pk=usuario.pk).update(perfil_permisos=perfil, perfil_vence=vence)
        usuario.refresh_from_db()
        return usuario

    # --- Quién tiene qué ------------------------------------------------------

    def test_admin_siempre_moderador_segun_su_perfil(self):
        self.assertTrue(all(tiene_permiso(self.admin, c) for c in CODIGOS))
        self.assertFalse(any(tiene_permiso(self.moderador, c) for c in CODIGOS))
        self.asignar(self.solo_nomenclador)
        self.assertTrue(tiene_permiso(self.moderador, 'nomencladores'))
        self.assertFalse(tiene_permiso(self.moderador, 'auditoria'))

    def test_caduca_el_dia_siguiente_a_su_fecha(self):
        hoy = timezone.localdate()
        self.asignar(self.todo, vence=hoy)
        self.assertIsNotNone(perfil_vigente(self.moderador))
        self.asignar(self.todo, vence=hoy - timedelta(days=1))
        self.assertIsNone(perfil_vigente(self.moderador))
        self.assertFalse(tiene_permiso(self.moderador, 'auditoria'))
        self.assertNotIn(self.moderador, usuarios_con_permiso('resolver_solicitudes'))

    def test_solo_moderadores_y_se_pierde_al_cambiar_de_rol(self):
        self.asignar(self.todo)
        self.moderador.es_moderador = False
        self.moderador.es_observador = True
        self.moderador.save()
        self.moderador.refresh_from_db()
        self.assertIsNone(self.moderador.perfil_permisos)
        self.assertFalse(tiene_permiso(self.moderador, 'nomencladores'))

    # --- Pantallas ------------------------------------------------------------

    def test_nomencladores_auditoria_y_editor_abren_con_el_permiso(self):
        self.client.force_login(self.moderador)
        urls = [reverse('parametros'), reverse('auditoria:index')]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.asignar(self.todo)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_usuarios_y_perfiles_nunca(self):
        self.asignar(self.todo)
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.get(reverse('list_usuarios')).status_code, 403)
        self.assertEqual(self.client.get(reverse('perfiles_permisos')).status_code, 403)
        self.assertFalse(self.moderador.is_staff or self.moderador.is_superuser)

    def test_subsanacion_y_gestor_ven_toda_la_empresa(self):
        from strorganizativa.permisos import unidades_visibles
        from subsanacion.permisos import es_administrador
        self.assertFalse(es_administrador(self.moderador))
        self.asignar(self.todo)
        self.assertTrue(es_administrador(self.moderador))
        from strorganizativa.models import UnidadOrganizativa
        self.assertEqual(unidades_visibles(self.moderador).count(), UnidadOrganizativa.objects.count())

    # --- Solicitudes ----------------------------------------------------------

    def test_editar_sin_solicitud(self):
        from solicitudes.integracion import requiere_solicitud
        self.assertTrue(requiere_solicitud(self.moderador))
        self.asignar(self.todo)
        self.assertFalse(requiere_solicitud(self.moderador))
        # «Resolver solicitudes» incluye guardar sin solicitud (decisión del usuario).
        self.asignar(PerfilPermisos.objects.create(nombre='Resuelve', resolver_solicitudes=True))
        self.assertFalse(requiere_solicitud(self.moderador))

    def test_resolver_solicitudes_pero_nunca_las_suyas(self):
        from solicitudes.permisos import es_moderador
        self.asignar(self.todo)
        propia = type('S', (), {'solicitante_id': self.moderador.pk})()
        ajena = type('S', (), {'solicitante_id': self.otro.pk})()
        self.assertTrue(puede_resolver(self.moderador, ajena))
        self.assertFalse(puede_resolver(self.moderador, propia))
        self.assertIn(self.moderador, usuarios_con_permiso('resolver_solicitudes'))
        # Sigue siendo Moderador para enviar las suyas.
        self.assertTrue(es_moderador(self.moderador))

    # --- Auditoría y aviso ----------------------------------------------------

    def test_lo_que_hace_con_el_permiso_queda_marcado(self):
        from auditoria.models import AccionAuditoria, EventoAuditoria
        from auditoria.servicios import registrar
        self.asignar(self.todo)
        with con_permiso(self.moderador, 'nomencladores'):
            evento = registrar(usuario=self.moderador, accion=AccionAuditoria.MODIFICAR, descriptor='x')
        self.assertEqual(evento.permiso_especial, 'Nomencladores y parámetros')
        with con_permiso(self.admin, 'nomencladores'):
            evento = registrar(usuario=self.admin, accion=AccionAuditoria.MODIFICAR, descriptor='y')
        self.assertEqual(evento.permiso_especial, '')
        self.assertEqual(EventoAuditoria.objects.filter(permiso_especial='').count() >= 1, True)

    def test_asignar_avisa_al_moderador_y_queda_en_auditoria(self):
        from auditoria.models import EventoAuditoria
        from notificaciones.models import Notificacion
        antes = foto_de_asignacion(self.moderador.pk)
        usuario = self.asignar(self.solo_nomenclador, vence=timezone.localdate() + timedelta(days=5))
        registrar_cambio_de_perfil(usuario, antes)
        aviso = Notificacion.objects.get(destinatario=usuario, codigo_regla='PERMISOS-ESPECIALES')
        self.assertIn('Nomencladores', aviso.titulo)
        self.assertIn('Hasta el', aviso.mensaje)
        self.assertTrue(EventoAuditoria.objects.filter(descriptor__contains='Permisos especiales').exists())

    def test_pantalla_de_perfiles_crea_y_borra(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('perfiles_permisos'), {'nombre': 'Jefe municipal', 'auditoria': 'on'})
        self.assertEqual(respuesta.status_code, 302)
        perfil = PerfilPermisos.objects.get(nombre='Jefe municipal')
        self.assertEqual(perfil.permisos_marcados(), ['Auditoría y estadísticas'])
        self.asignar(perfil)
        self.client.post(reverse('borrar_perfil_permisos', args=[perfil.pk]))
        self.moderador.refresh_from_db()
        self.assertIsNone(self.moderador.perfil_permisos)
