from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from usuarios.models import CustomUser

from .models import Configuracion


class AuditoriaAdminTests(TestCase):
    """Editar la Configuración desde el Admin de Django ahora deja rastro en
    `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin` (compartido con el
    resto de apps, ver `contratos.tests.AuditoriaAdminTests` para el caso original
    que motivó esto). No se prueba "eliminar": es un singleton sin permiso de
    borrado en la práctica (solo existe una fila y el negocio no la borra)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_configuracion', password='x', es_admin=True)

    def test_editar_la_configuracion_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from configuracion.admin import ConfiguracionAdmin

        config = Configuracion.objects.create(nombre_empresa='Empresa de prueba')

        admin_instance = ConfiguracionAdmin(Configuracion, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        config.nombre_empresa = 'Empresa Renombrada'
        admin_instance.save_model(request, config, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(config.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'configuracion')
