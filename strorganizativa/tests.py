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


class ColumnaPuestoClaveTests(TestCase):
    """La columna «puesto clave» del listado de Cargos tiene que distinguir.

    Antes la plantilla leía `c.puesto_clave` sobre un `CargoPlantilla`, y ese
    campo vive en `NCargo`. Django no falla cuando una variable de plantilla no
    existe —la resuelve como cadena vacía—, así que el `{% if %}` era siempre
    falso y TODOS los cargos salían con la X roja, contradiciendo al informe de
    Puestos Clave, que sí lee el campo correcto.

    Un fallo así no deja traza en ningún log: la página carga perfecta y solo
    informa mal. De ahí esta prueba, que compara los dos casos en la misma
    respuesta: si alguien vuelve a apuntar al modelo equivocado, los dos cargos
    pasarían a pintarse igual y esto salta.
    """

    ICONO_ES_CLAVE = 'title="Es puesto clave"'
    ICONO_NO_ES_CLAVE = 'title="No es puesto clave"'

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import NCargo, NGrupoEscala

        from .models import CargoPlantilla, Departamento

        cls.admin = CustomUser.objects.create_user(
            username='admin_puesto_clave', password='x', es_admin=True)

        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB de prueba')
        unidad = UnidadOrganizativa.objects.create(
            codigo_interno=99, descripcion='UEB Puesto Clave', tipo=tipo, grupo_nomina=1)
        departamento = Departamento.objects.create(
            descripcion='Departamento de prueba', unidad_organizativa=unidad)

        grupo = NGrupoEscala.objects.create(nivel='I')

        ncargo_clave = NCargo.objects.create(
            descripcion='Director de prueba', cat_ocupacional='CDI',
            grupo_escala=grupo, salario_basico=0, puesto_clave=True)
        ncargo_normal = NCargo.objects.create(
            descripcion='Obrero de prueba', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=0, puesto_clave=False)

        cls.cargo_clave = CargoPlantilla.objects.create(
            ncargo=ncargo_clave, departamento=departamento, cant_aprobada=1, orden_informe=1)
        cls.cargo_normal = CargoPlantilla.objects.create(
            ncargo=ncargo_normal, departamento=departamento, cant_aprobada=1, orden_informe=2)

    def _listado(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('search_cargos_view'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.content.decode()

    def test_el_cargo_clave_sale_marcado_y_el_normal_no(self):
        html = self._listado()
        self.assertIn(self.ICONO_ES_CLAVE, html)
        self.assertIn(self.ICONO_NO_ES_CLAVE, html)
        # Un icono de cada: si la plantilla vuelve a mirar el campo equivocado,
        # los dos cargos saldrían con el mismo icono y uno de estos contadores
        # valdría 0.
        self.assertEqual(html.count(self.ICONO_ES_CLAVE), 1)
        self.assertEqual(html.count(self.ICONO_NO_ES_CLAVE), 1)

    def test_el_listado_coincide_con_lo_que_dice_la_base_de_datos(self):
        """Blindaje contra la contradicción original entre pantallas."""
        from .models import CargoPlantilla

        html = self._listado()
        esperados = CargoPlantilla.objects.filter(ncargo__puesto_clave=True).count()
        self.assertEqual(html.count(self.ICONO_ES_CLAVE), esperados)
