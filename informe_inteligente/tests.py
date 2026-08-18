from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from usuarios.models import CustomUser

from .models import InformePersonalizado


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar un InformePersonalizado desde el Admin de Django ahora
    deja rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_informe_inteligente', password='x', es_admin=True)

    def test_eliminar_un_informe_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        informe = InformePersonalizado.objects.create(
            nombre='Informe de prueba', modelo_raiz='CAlta', configuracion={})
        self.client.force_login(self.admin)

        url = reverse('admin:informe_inteligente_informepersonalizado_delete', args=[informe.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(InformePersonalizado.objects.filter(pk=informe.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(informe.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'informe_inteligente')

    def test_editar_un_informe_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from informe_inteligente.admin import InformePersonalizadoAdmin

        informe = InformePersonalizado.objects.create(
            nombre='Informe de prueba', modelo_raiz='CAlta', configuracion={})

        admin_instance = InformePersonalizadoAdmin(InformePersonalizado, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        informe.nombre = 'Informe renombrado'
        admin_instance.save_model(request, informe, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(informe.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
