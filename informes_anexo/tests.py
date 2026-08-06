"""Pruebas del Anexo 14.

Se centran en el contrato de la vista (permisos y respuesta HTMX parcial), no en el
contenido del árbol de unidades: ese depende de datos de estructura organizativa que
aquí no se montan, y la vista ya lo tolera devolviendo listas vacías.
"""
from django.test import TestCase
from django.urls import reverse

from usuarios.models import CustomUser


class PermisosAnexo14Tests(TestCase):
    """El Anexo 14 es solo para Administradores y Observadores (no Moderadores)."""

    @classmethod
    def setUpTestData(cls):
        # `CustomUser.save()` valida que haya exactamente un rol, así que el rol se
        # pasa en el constructor y no después.
        cls.admin = CustomUser(username='anexo_admin', es_admin=True, is_active=True)
        cls.admin.set_password('Clave12345!')
        cls.admin.save()

        cls.observador = CustomUser(username='anexo_observador', es_observador=True, is_active=True)
        cls.observador.set_password('Clave12345!')
        cls.observador.save()

        cls.moderador = CustomUser(username='anexo_moderador', es_moderador=True, is_active=True)
        cls.moderador.set_password('Clave12345!')
        cls.moderador.save()

    def test_admin_accede(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('informes_anexo:anexo14')).status_code, 200)

    def test_observador_accede(self):
        self.client.force_login(self.observador)
        self.assertEqual(self.client.get(reverse('informes_anexo:anexo14')).status_code, 200)

    def test_moderador_no_accede(self):
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.get(reverse('informes_anexo:anexo14')).status_code, 403)


class FirmasHtmxTests(TestCase):
    """Elegir un firmante debe resolverse con un parcial, sin repintar la página."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser(username='anexo_htmx_admin', es_admin=True, is_active=True)
        cls.admin.set_password('Clave12345!')
        cls.admin.save()

    def setUp(self):
        self.client.force_login(self.admin)

    def test_peticion_normal_devuelve_pagina_completa(self):
        respuesta = self.client.get(reverse('informes_anexo:anexo14'))
        plantillas = [t.name for t in respuesta.templates if t.name]
        self.assertIn('pages/informes_anexo/anexo14.html', plantillas)
        # El bloque de firmas se incluye, pero NO como respuesta suelta.
        self.assertIn('pages/informes_anexo/partials/bloque_firmas.html', plantillas)

    def test_peticion_htmx_devuelve_solo_el_bloque_de_firmas(self):
        respuesta = self.client.get(reverse('informes_anexo:anexo14'), HTTP_HX_REQUEST='true')
        plantillas = [t.name for t in respuesta.templates if t.name]
        self.assertIn('pages/informes_anexo/partials/bloque_firmas.html', plantillas)
        self.assertNotIn('pages/informes_anexo/anexo14.html', plantillas)

    def test_htmx_reenvia_la_botonera_fuera_de_banda(self):
        """Sin esto los enlaces de Excel/PDF conservarían el firmante anterior."""
        respuesta = self.client.get(reverse('informes_anexo:anexo14'), HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'hx-swap-oob="true"')
        self.assertContains(respuesta, 'id="accionesExportAnexo14"')

    def test_pagina_completa_no_duplica_la_botonera(self):
        """El `hx-swap-oob` solo debe aparecer en las respuestas HTMX."""
        respuesta = self.client.get(reverse('informes_anexo:anexo14'))
        self.assertNotContains(respuesta, 'hx-swap-oob')
        self.assertEqual(respuesta.content.decode().count('id="accionesExportAnexo14"'), 1)

    def test_el_firmante_ya_elegido_se_conserva_en_el_bloque_intercambiado(self):
        """Regresión: al elegir el 2º firmante se perdía el 1º.

        Los `hidden` que conservan la elección deben regenerarse dentro del bloque que
        HTMX reemplaza. Si viven en el formulario de filtros (que no se intercambia)
        conservan el valor del render inicial — vacío — y la selección anterior se cae.
        """
        respuesta = self.client.get(
            reverse('informes_anexo:anexo14'), {'director_ch': '999'}, HTTP_HX_REQUEST='true')
        cuerpo = respuesta.content.decode()
        self.assertIn('name="director_ch" value="999"', cuerpo)
        self.assertIn('form="formFiltrosAnexo14"', cuerpo)

    def test_htmx_incluye_el_bloque_de_firmas_al_enviar(self):
        """Sin este `hx-include` los `hidden` del bloque no viajarían en la petición."""
        respuesta = self.client.get(reverse('informes_anexo:anexo14'))
        self.assertContains(respuesta, 'hx-include="#formFiltrosAnexo14, #bloqueFirmasAnexo14"')

    def test_los_selects_de_firmante_ya_no_recargan_la_pagina(self):
        """Regresión: antes usaban `form.submit()`, que repintaba todo el informe."""
        respuesta = self.client.get(reverse('informes_anexo:anexo14'))
        cuerpo = respuesta.content.decode()
        self.assertNotIn("getElementById('formFiltrosAnexo14').submit()", cuerpo)
        self.assertIn('hx-target="#bloqueFirmasAnexo14"', cuerpo)
