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
