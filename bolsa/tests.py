from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from nomencladores.models import NMunicipio, NProvincia
from usuarios.models import CustomUser

from .models import Aspirante


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar un Aspirante desde el Admin de Django ahora deja
    rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.provincia = NProvincia.objects.create(nombre='La Habana')
        cls.municipio = NMunicipio.objects.create(nombre='Playa', provincia=cls.provincia)
        cls.admin = CustomUser.objects.create_user(
            username='admin_bolsa', password='x', es_admin=True)

    def test_eliminar_un_aspirante_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        aspirante = Aspirante.objects.create(
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad='85010112345', estado='ACTIVO', sexo='F', raza='BL',
            provincia=self.provincia, municipio=self.municipio)
        self.client.force_login(self.admin)

        url = reverse('admin:bolsa_aspirante_delete', args=[aspirante.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(Aspirante.objects.filter(pk=aspirante.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(aspirante.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'bolsa')

    def test_editar_un_aspirante_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from bolsa.admin import AspiranteAdmin

        aspirante = Aspirante.objects.create(
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad='85010112346', estado='ACTIVO', sexo='F', raza='BL',
            provincia=self.provincia, municipio=self.municipio)

        admin_instance = AspiranteAdmin(Aspirante, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        aspirante.nombre = 'Ana María'
        admin_instance.save_model(request, aspirante, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(aspirante.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
