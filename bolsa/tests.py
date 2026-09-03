import re

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

        aspirante = Aspirante.objects.create(nivel_educ='SA', 
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

        aspirante = Aspirante.objects.create(nivel_educ='SA', 
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


class BotonesSoloLecturaTests(TestCase):
    """El Observador ve la botonera de Aspirantes/Bajas, pero inactiva.

    El backend ya bloquea crear/editar/eliminar (`write_required` en
    bolsa/urls.py), así que esto comprueba lo otro: que el usuario lo VEA en
    pantalla en lugar de descubrirlo con un error al pulsar.
    """

    BOTONES = ('btn-editar', 'btn-contrato', 'btn-eliminar')

    @classmethod
    def setUpTestData(cls):
        cls.observador = CustomUser.objects.create_user(
            username='obs_bolsa', password='ClaveSegura123', es_observador=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_bolsa', password='ClaveSegura123', es_moderador=True)

    def _html(self, usuario, url):
        self.client.force_login(usuario)
        return self.client.get(reverse(url)).content.decode()

    def _botonera(self, html):
        """Devuelve la etiqueta <div id="aspirante-toolbar" ...> completa.

        Se mira la etiqueta y no la página entera: la clase
        `toolbar-solo-lectura` aparece SIEMPRE en el bloque <style>, así que
        buscarla en todo el HTML daría siempre positivo.
        """
        encontrado = re.search(r'<div[^>]*id="aspirante-toolbar".*?>', html, re.S)
        self.assertIsNotNone(encontrado, 'No se encontró la botonera')
        return encontrado.group(0)

    def _etiqueta(self, html, id_boton):
        """Devuelve la etiqueta <button ...> completa de ese id."""
        patron = re.compile(r'<button[^>]*id="%s".*?>' % re.escape(id_boton), re.S)
        encontrado = patron.search(html)
        self.assertIsNotNone(encontrado, f'No se encontró el botón {id_boton}')
        return encontrado.group(0)

    def test_observador_ve_los_botones_deshabilitados(self):
        html = self._html(self.observador, 'list_aspir')
        self.assertIn('toolbar-solo-lectura', self._botonera(html))
        for boton in self.BOTONES:
            with self.subTest(boton=boton):
                self.assertIn('disabled', self._etiqueta(html, boton))

    def test_moderador_ve_los_botones_habilitados(self):
        html = self._html(self.moderador, 'list_aspir')
        self.assertNotIn('toolbar-solo-lectura', self._botonera(html))
        for boton in self.BOTONES:
            with self.subTest(boton=boton):
                self.assertNotIn('disabled', self._etiqueta(html, boton))

    def test_observador_no_ve_el_boton_nuevo(self):
        html = self._html(self.observador, 'list_aspir')
        self.assertNotIn(reverse('add_aspir'), html)

    def test_moderador_si_ve_el_boton_nuevo(self):
        html = self._html(self.moderador, 'list_aspir')
        self.assertIn(reverse('add_aspir'), html)

    def test_nadie_ve_el_boton_nuevo_en_la_pantalla_de_bajas(self):
        """`{% if not es_baja_view and ... %}` se evaluaba con la precedencia
        equivocada (`(not es_baja_view and es_admin) or es_moderador`) y el
        Moderador veía «Nuevo» también en Bajas."""
        for usuario in (self.moderador, self.observador):
            with self.subTest(usuario=usuario.username):
                html = self._html(usuario, 'list_baja')
                self.assertNotIn(reverse('add_aspir'), html)


class SerieCarnetTests(TestCase):
    """La serie del carnet es OPCIONAL pero ÚNICA, y esa combinación tiene una
    trampa concreta: en PostgreSQL una columna UNIQUE admite tantos NULL como haga
    falta, pero solo UNA cadena vacía. Si el formulario guardase `''` en vez de
    `None`, el segundo trabajador sin serie reventaría con IntegrityError.
    Por eso `Aspirante._normalizar_serie_ci` convierte el vacío en `None`, y estas
    pruebas fijan ese comportamiento."""

    @classmethod
    def setUpTestData(cls):
        cls.provincia = NProvincia.objects.create(nombre='Matanzas')
        cls.municipio = NMunicipio.objects.create(nombre='Cárdenas', provincia=cls.provincia)

    def _crear(self, doc_identidad, serie_ci=None):
        return Aspirante.objects.create(nivel_educ='SA', 
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad=doc_identidad, estado='ACTIVO', sexo='F', raza='BL',
            serie_ci=serie_ci, provincia=self.provincia, municipio=self.municipio)

    def test_dos_trabajadores_sin_serie_conviven(self):
        """El caso que rompería si el vacío se guardara como cadena vacía."""
        self._crear('85010112301')
        self._crear('85010112302', serie_ci='')
        self._crear('85010112303', serie_ci='   ')

        self.assertEqual(Aspirante.objects.filter(serie_ci__isnull=True).count(), 3)

    def test_la_serie_se_guarda_siempre_en_mayusculas(self):
        """Normalizar en el modelo (y no solo en el formulario) hace que valga
        también desde el admin, un script o una importación."""
        aspirante = self._crear('85010112304', serie_ci=' ab12cd34e ')
        aspirante.refresh_from_db()
        self.assertEqual(aspirante.serie_ci, 'AB12CD34E')

    def test_no_se_puede_repetir_la_serie(self):
        from django.core.exceptions import ValidationError

        self._crear('85010112305', serie_ci='AB12CD34E')
        # `save()` llama a `full_clean()`, así que el duplicado sale como
        # ValidationError antes de llegar a la restricción de la base de datos.
        with self.assertRaises(ValidationError):
            self._crear('85010112306', serie_ci='ab12cd34e')

    def test_una_serie_de_menos_de_nueve_caracteres_se_rechaza(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self._crear('85010112307', serie_ci='AB12')


class ValidarDatosAspiranteTests(TestCase):
    """El endpoint que ya usaba el formulario para detectar CI y móviles repetidos
    devuelve ahora también la EDAD y comprueba la serie.

    La edad se calcula en el servidor a propósito: el criterio para deducir la fecha
    de nacimiento del carnet (el 7º dígito indica el siglo) vive en
    `Aspirante._calcular_fecha_nacimiento`, y reimplementarlo en JavaScript daría dos
    interpretaciones del mismo carnet que podrían divergir."""

    @classmethod
    def setUpTestData(cls):
        cls.provincia = NProvincia.objects.create(nombre='Villa Clara')
        cls.municipio = NMunicipio.objects.create(nombre='Santa Clara', provincia=cls.provincia)
        cls.usuario = CustomUser.objects.create_user(
            username='rrhh_serie', password='x', es_admin=True)
        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Luis', papellido='Díaz', sapellido='Mora',
            doc_identidad='85010112400', estado='ACTIVO', sexo='M', raza='BL',
            serie_ci='AB12CD34E',
            provincia=cls.provincia, municipio=cls.municipio)

    def setUp(self):
        self.client.force_login(self.usuario)

    def _consultar(self, **parametros):
        respuesta = self.client.get(reverse('validar_datos_aspirante'), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def test_devuelve_la_edad_que_codifica_el_carnet(self):
        from datetime import date

        datos = self._consultar(doc_identidad='85010112401')
        hoy = date.today()
        # Nacido el 01/01/1985 (7º dígito 2 -> siglo XX).
        esperada = hoy.year - 1985 - ((hoy.month, hoy.day) < (1, 1))

        self.assertEqual(datos['edad'], esperada)
        self.assertEqual(datos['fecha_nacimiento'], '01/01/1985')

    def test_un_carnet_con_fecha_imposible_no_devuelve_edad(self):
        """Mejor un guion en el formulario que una edad inventada."""
        datos = self._consultar(doc_identidad='85023112345')  # 31 de febrero

        self.assertIsNone(datos['edad'])
        self.assertEqual(datos['fecha_nacimiento'], '')

    def test_detecta_la_serie_repetida_sin_importar_las_mayusculas(self):
        datos = self._consultar(serie='ab12cd34e')

        self.assertTrue(datos['serie_existe'])
        self.assertIn('Luis', datos['serie_error_msg'])

    def test_un_trabajador_no_se_detecta_a_si_mismo(self):
        """Al editar, reenviar la propia serie no puede marcarse como duplicada."""
        datos = self._consultar(serie='AB12CD34E', aspirante_id=self.aspirante.pk)

        self.assertFalse(datos['serie_existe'])

    def test_una_serie_libre_no_da_error(self):
        datos = self._consultar(serie='ZZ99ZZ99Z')

        self.assertFalse(datos['serie_existe'])
