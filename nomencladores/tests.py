from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from usuarios.models import CustomUser

from .models import NCargo, NGrupoEscala, NMunicipio, NProvincia


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar un nomenclador (NCargo) desde el Admin de Django ahora
    deja rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests` para
    el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.grupo_escala = NGrupoEscala.objects.create(nivel='G1')
        cls.admin = CustomUser.objects.create_user(
            username='admin_nomencladores', password='x', es_admin=True)

    def test_eliminar_un_cargo_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        cargo = NCargo.objects.create(
            descripcion='Cargo de prueba', cat_ocupacional='TEC',
            grupo_escala=self.grupo_escala, salario_basico=1000)
        self.client.force_login(self.admin)

        url = reverse('admin:nomencladores_ncargo_delete', args=[cargo.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(NCargo.objects.filter(pk=cargo.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(cargo.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'nomencladores')

    def test_editar_un_cargo_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from nomencladores.admin import NCargoAdmin

        cargo = NCargo.objects.create(
            descripcion='Cargo de prueba', cat_ocupacional='TEC',
            grupo_escala=self.grupo_escala, salario_basico=1000)

        admin_instance = NCargoAdmin(NCargo, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        cargo.descripcion = 'Cargo corregido'
        admin_instance.save_model(request, cargo, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(cargo.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)


class AuditoriaInlineTests(TestCase):
    """El inline NMunicipioInline (dentro de NProvinciaAdmin) permite crear/editar/
    eliminar municipios sin pasar por save_model/delete_model — Django solo llama a
    `formset.save()`. `AuditoriaAdminMixin.save_formset` cierra ese hueco."""

    @classmethod
    def setUpTestData(cls):
        cls.provincia = NProvincia.objects.create(nombre='Provincia Auditoría')
        cls.municipio = NMunicipio.objects.create(
            nombre='Municipio Viejo', provincia=cls.provincia)
        cls.admin = CustomUser.objects.create_user(
            username='admin_inline_nomencladores', password='x', es_admin=True)

    def _datos_formset(self, total_forms, initial_forms):
        return {
            'nmunicipio_set-TOTAL_FORMS': str(total_forms),
            'nmunicipio_set-INITIAL_FORMS': str(initial_forms),
            'nmunicipio_set-MIN_NUM_FORMS': '0',
            'nmunicipio_set-MAX_NUM_FORMS': '1000',
        }

    def test_crear_y_editar_municipio_desde_el_inline_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        self.client.force_login(self.admin)
        url = reverse('admin:nomencladores_nprovincia_change', args=[self.provincia.pk])

        data = {'nombre': self.provincia.nombre, 'siglas': ''}
        data.update(self._datos_formset(total_forms=2, initial_forms=1))
        data['nmunicipio_set-0-id'] = str(self.municipio.pk)
        data['nmunicipio_set-0-nombre'] = 'Municipio Editado'
        data['nmunicipio_set-1-id'] = ''
        data['nmunicipio_set-1-nombre'] = 'Municipio Nuevo'

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        self.municipio.refresh_from_db()
        self.assertEqual(self.municipio.nombre, 'Municipio Editado')
        nuevo = NMunicipio.objects.get(nombre='Municipio Nuevo')

        evento_editado = EventoAuditoria.objects.filter(
            object_id=str(self.municipio.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento_editado.usuario_id, self.admin.pk)
        evento_creado = EventoAuditoria.objects.filter(
            object_id=str(nuevo.pk), accion='ADD').latest('fecha')
        self.assertEqual(evento_creado.usuario_id, self.admin.pk)

    def test_eliminar_municipio_desde_el_inline_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        self.client.force_login(self.admin)
        url = reverse('admin:nomencladores_nprovincia_change', args=[self.provincia.pk])

        data = {'nombre': self.provincia.nombre, 'siglas': ''}
        data.update(self._datos_formset(total_forms=1, initial_forms=1))
        data['nmunicipio_set-0-id'] = str(self.municipio.pk)
        data['nmunicipio_set-0-nombre'] = self.municipio.nombre
        data['nmunicipio_set-0-DELETE'] = 'on'

        municipio_pk = self.municipio.pk
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(NMunicipio.objects.filter(pk=municipio_pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(municipio_pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
