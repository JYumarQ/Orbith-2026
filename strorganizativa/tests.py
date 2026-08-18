from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from nomencladores.models import NTipoUnidadOrganizativa
from usuarios.models import CustomUser

from .models import UnidadOrganizativa


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar una UnidadOrganizativa desde el Admin de Django ahora
    deja rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
        cls.admin = CustomUser.objects.create_user(
            username='admin_strorganizativa', password='x', es_admin=True)

    def test_eliminar_una_unidad_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        unidad = UnidadOrganizativa.objects.create(
            codigo_interno=1, descripcion="UEB de prueba", tipo=self.tipo, grupo_nomina=1)
        self.client.force_login(self.admin)

        url = reverse('admin:strorganizativa_unidadorganizativa_delete', args=[unidad.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(UnidadOrganizativa.objects.filter(pk=unidad.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(unidad.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'strorganizativa')

    def test_editar_una_unidad_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from strorganizativa.admin import UnidadOrganizativaAdmin

        unidad = UnidadOrganizativa.objects.create(
            codigo_interno=2, descripcion="UEB de prueba", tipo=self.tipo, grupo_nomina=2)

        admin_instance = UnidadOrganizativaAdmin(UnidadOrganizativa, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        unidad.descripcion = 'UEB renombrada'
        admin_instance.save_model(request, unidad, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(unidad.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
