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


class ColoresDeCategoriaOcupacional(TestCase):
    """La paleta de las categorías ocupacionales.

    Los colores viven en Python, al lado de los códigos que colorean, y se
    repiten en `static/css/informes-rrhh.css` para poder pintar insignias sin
    JavaScript. Estas pruebas son la guarda de que los dos sitios no se
    separen: sin ellas, cambiar un color en uno y olvidar el otro deja la
    aplicación pintando la misma categoría de dos maneras.
    """

    def test_todas_las_categorias_tienen_color(self):
        """Añadir una categoría obliga a decidir su color: sin esto, la nueva
        saldría gris en todos los gráficos sin que nadie se entere."""
        from nomencladores.models import COLORES_CAT_OCUPACIONAL, NCargo

        codigos = {codigo for codigo, _ in NCargo._meta.get_field('cat_ocupacional').choices}
        self.assertEqual(codigos, set(COLORES_CAT_OCUPACIONAL))

    def test_los_dos_cuadros_comparten_color(self):
        """La aplicación los agrupa como «Cuadros» en todas partes."""
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        self.assertEqual(COLORES_CAT_OCUPACIONAL['CDI'],
                         COLORES_CAT_OCUPACIONAL['CEJ'])

    def test_ninguna_categoria_usa_un_color_de_alerta(self):
        """En los informes el naranja significa «falta» y el rojo «crítico». Si
        una categoría fuera naranja, una barra naranja dejaría de querer decir
        algo. Se comprueba que ningún color cae en la franja cálida."""
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        for codigo, color in COLORES_CAT_OCUPACIONAL.items():
            rojo = int(color[1:3], 16)
            verde = int(color[3:5], 16)
            azul = int(color[5:7], 16)
            with self.subTest(categoria=codigo):
                # Cálido = el rojo domina claramente sobre el azul.
                self.assertLessEqual(rojo, azul + 40,
                                     '%s (%s) tira a cálido' % (codigo, color))

    def test_el_css_repite_exactamente_los_mismos_colores(self):
        import io
        import os

        from django.conf import settings
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        ruta = os.path.join(settings.BASE_DIR, 'static', 'css', 'informes-rrhh.css')
        css = io.open(ruta, encoding='utf-8').read().lower()

        for codigo, color in COLORES_CAT_OCUPACIONAL.items():
            with self.subTest(categoria=codigo):
                self.assertIn(color.lower(), css,
                              'El color de %s no está en informes-rrhh.css' % codigo)

    def test_un_codigo_desconocido_no_deja_el_grafico_sin_color(self):
        from nomencladores.models import COLOR_CAT_DESCONOCIDA, color_de_categoria

        self.assertEqual(color_de_categoria('XXX'), COLOR_CAT_DESCONOCIDA)
        self.assertEqual(color_de_categoria(None), COLOR_CAT_DESCONOCIDA)
        self.assertEqual(color_de_categoria(''), COLOR_CAT_DESCONOCIDA)
