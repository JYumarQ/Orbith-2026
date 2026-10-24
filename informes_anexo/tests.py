"""Pruebas del Anexo 17.

Se centran en el contrato de la vista (permisos y respuesta HTMX parcial), no en el
contenido del árbol de unidades: ese depende de datos de estructura organizativa que
aquí no se montan, y la vista ya lo tolera devolviendo listas vacías.
"""
from django.test import TestCase
from django.urls import reverse

from nomencladores.models import NTipoUnidadOrganizativa
from strorganizativa.models import UnidadOrganizativa
from usuarios.models import CustomUser

from .views import _unidades_del_alcance


class PermisosAnexo17Tests(TestCase):
    """El Anexo 17 lo consultan los tres roles; cada uno ve su alcance.

    Antes el Moderador recibía un 403. Se le abrió al acotar el informe por
    unidad: lo que se le negaba era ver la plantilla de la empresa entera, y eso
    es justo lo que `_unidades_del_alcance()` impide ahora. El informe sigue
    siendo de solo lectura para todos: no hay ninguna vista de escritura aquí.
    """

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
        self.assertEqual(self.client.get(reverse('informes_anexo:anexo17')).status_code, 200)

    def test_observador_accede(self):
        self.client.force_login(self.observador)
        self.assertEqual(self.client.get(reverse('informes_anexo:anexo17')).status_code, 200)

    def test_moderador_accede(self):
        """Antes era un 403. Ahora entra, pero acotado a sus unidades: eso lo
        verifica `AlcanceAnexo17Tests`."""
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.get(reverse('informes_anexo:anexo17')).status_code, 200)

    def test_un_anonimo_sigue_fuera(self):
        """Abrir el Anexo 17 a los tres roles no lo abre a quien no ha entrado.

        Al anónimo lo ataja el middleware de sesión ANTES que el mixin, así que
        la respuesta es una redirección al login (302) y no un 403: es lo
        correcto —a quien no ha iniciado sesión se le pide que lo haga, no se le
        dice que no tiene permiso—.

        El caso del usuario AUTENTICADO y sin ningún rol no se puede montar en
        una prueba: la restricción `exactamente_un_rol` de la base de datos lo
        rechaza incluso con un `update()` directo. Que exista esa restricción es
        precisamente lo que hace que ese caso no pueda darse en producción.
        """
        respuesta = self.client.get(reverse('informes_anexo:anexo17'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login', respuesta['Location'])


class AlcanceAnexo17Tests(TestCase):
    """El árbol del Anexo 17 se acota a las unidades asignadas.

    `_unidades_del_alcance()` es el único punto que lo decide, así que se prueba
    él directamente y además una vez por la URL, para que no quede solo en la
    teoría: los KPIs se calculan sobre el árbol ya acotado, de modo que un
    usuario con alcance parcial nunca ve los totales de la empresa.
    """

    @classmethod
    def setUpTestData(cls):
        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Direccion Anexo', es_principal=True)

        cls.propia = UnidadOrganizativa.objects.create(
            codigo_interno=911, descripcion='Direccion Propia Anexo',
            tipo=tipo_principal, grupo_nomina=911)
        cls.ajena = UnidadOrganizativa.objects.create(
            codigo_interno=912, descripcion='Direccion Ajena Anexo',
            tipo=tipo_principal, grupo_nomina=912)

        cls.admin = CustomUser(username='anexo_alcance_admin', es_admin=True, is_active=True)
        cls.admin.set_password('Clave12345!')
        cls.admin.save()

        cls.acotado = CustomUser(username='anexo_alcance_obs', es_observador=True, is_active=True)
        cls.acotado.set_password('Clave12345!')
        cls.acotado.save()
        cls.acotado.unidades.add(cls.propia)

        cls.global_ = CustomUser(username='anexo_alcance_obs_global', es_observador=True, is_active=True)
        cls.global_.set_password('Clave12345!')
        cls.global_.save()

    def test_sin_unidades_el_observador_no_tiene_restriccion(self):
        self.assertIsNone(_unidades_del_alcance(self.global_))
        self.assertIsNone(_unidades_del_alcance(self.admin))

    def test_con_unidades_solo_ve_las_suyas(self):
        self.assertEqual(_unidades_del_alcance(self.acotado), {self.propia.pk})

    def test_el_selector_de_unidades_no_ofrece_la_ajena(self):
        self.client.force_login(self.acotado)
        html = self.client.get(reverse('informes_anexo:anexo17')).content.decode()
        self.assertIn('Direccion Propia Anexo', html)
        self.assertNotIn('Direccion Ajena Anexo', html)

    def test_el_administrador_las_sigue_viendo_todas(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('informes_anexo:anexo17')).content.decode()
        self.assertIn('Direccion Propia Anexo', html)
        self.assertIn('Direccion Ajena Anexo', html)

    def test_pedir_una_unidad_ajena_por_la_url_no_la_devuelve(self):
        """El acotado se hace en el servidor, no limitando el desplegable."""
        self.client.force_login(self.acotado)
        respuesta = self.client.get(
            reverse('informes_anexo:anexo17'), {'padre': self.ajena.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['padre_actual'], self.propia)


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
        respuesta = self.client.get(reverse('informes_anexo:anexo17'))
        plantillas = [t.name for t in respuesta.templates if t.name]
        self.assertIn('pages/informes_anexo/anexo17.html', plantillas)
        # El bloque de firmas se incluye, pero NO como respuesta suelta.
        self.assertIn('pages/informes_anexo/partials/bloque_firmas.html', plantillas)

    def test_peticion_htmx_devuelve_solo_el_bloque_de_firmas(self):
        respuesta = self.client.get(reverse('informes_anexo:anexo17'), HTTP_HX_REQUEST='true')
        plantillas = [t.name for t in respuesta.templates if t.name]
        self.assertIn('pages/informes_anexo/partials/bloque_firmas.html', plantillas)
        self.assertNotIn('pages/informes_anexo/anexo17.html', plantillas)

    def test_htmx_reenvia_la_botonera_fuera_de_banda(self):
        """Sin esto los enlaces de Excel/PDF conservarían el firmante anterior."""
        respuesta = self.client.get(reverse('informes_anexo:anexo17'), HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'hx-swap-oob="true"')
        self.assertContains(respuesta, 'id="accionesExportAnexo17"')

    def test_pagina_completa_no_duplica_la_botonera(self):
        """El `hx-swap-oob` solo debe aparecer en las respuestas HTMX."""
        respuesta = self.client.get(reverse('informes_anexo:anexo17'))
        self.assertNotContains(respuesta, 'hx-swap-oob')
        self.assertEqual(respuesta.content.decode().count('id="accionesExportAnexo17"'), 1)

    def test_el_firmante_ya_elegido_se_conserva_en_el_bloque_intercambiado(self):
        """Regresión: al elegir el 2º firmante se perdía el 1º.

        Los `hidden` que conservan la elección deben regenerarse dentro del bloque que
        HTMX reemplaza. Si viven en el formulario de filtros (que no se intercambia)
        conservan el valor del render inicial — vacío — y la selección anterior se cae.
        """
        respuesta = self.client.get(
            reverse('informes_anexo:anexo17'), {'director_ch': '999'}, HTTP_HX_REQUEST='true')
        cuerpo = respuesta.content.decode()
        self.assertIn('name="director_ch" value="999"', cuerpo)
        self.assertIn('form="formFiltrosAnexo17"', cuerpo)

    def test_htmx_incluye_el_bloque_de_firmas_al_enviar(self):
        """Sin este `hx-include` los `hidden` del bloque no viajarían en la petición."""
        respuesta = self.client.get(reverse('informes_anexo:anexo17'))
        self.assertContains(respuesta, 'hx-include="#formFiltrosAnexo17, #bloqueFirmasAnexo17"')

    def test_los_selects_de_firmante_ya_no_recargan_la_pagina(self):
        """Regresión: antes usaban `form.submit()`, que repintaba todo el informe."""
        respuesta = self.client.get(reverse('informes_anexo:anexo17'))
        cuerpo = respuesta.content.decode()
        self.assertNotIn("getElementById('formFiltrosAnexo17').submit()", cuerpo)
        self.assertIn('hx-target="#bloqueFirmasAnexo17"', cuerpo)
