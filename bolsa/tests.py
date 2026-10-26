import json
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
        self.assertEqual(evento.modulo, 'aspirantes')  # mismo módulo que en los formularios

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


class SelectorDeAspirantesParaContratar(TestCase):
    """El modal de «Nuevo contrato» de la Lista de Contratos y del Gestor.

    Lo que se fija aquí es QUIÉN sale en la lista: solo los contratables. Los de
    la Lista de Bajas no, porque contratarlos desde ahí no tiene sentido y el
    formulario los rechazaría después.
    """

    @classmethod
    def setUpTestData(cls):
        provincia = NProvincia.objects.create(nombre='Camagüey', siglas='CMG')
        municipio = NMunicipio.objects.create(
            nombre='Nuevitas', provincia=provincia, siglas='NUE')

        def persona(nombre, apellido, ci, estado):
            return Aspirante.objects.create(
                doc_identidad=ci, nombre=nombre, papellido=apellido,
                sapellido='Solis', sexo='F', raza='BL', estado=estado,
                nivel_educ='MS', provincia=provincia, municipio=municipio)

        cls.contratable = persona('Ana', 'Pérez', '85010112345', 'ASPIRANTE')
        cls.activo = persona('Luis', 'Gómez', '85010112346', 'ACTIVO')
        cls.de_baja = persona('Rosa', 'Lima', '85010112347', 'BAJA')

        cls.usuario = CustomUser.objects.create_user(
            username='usuario_modal', password='x', es_admin=True)

    def setUp(self):
        self.client.force_login(self.usuario)

    def listar(self, **parametros):
        return self.client.get(reverse('seleccionar_aspirante'), parametros)

    def test_solo_lista_a_los_contratables(self):
        nombres = [a.nombre for a in self.listar().context['aspirantes']]
        self.assertEqual(nombres, ['Ana'])

    def test_busca_por_nombre_apellido_o_carnet(self):
        for termino in ('Ana', 'Pérez', 'Ana Pérez', '8501011234'):
            with self.subTest(busqueda=termino):
                encontrados = self.listar(q=termino).context['aspirantes']
                self.assertEqual(len(encontrados), 1, termino)

    def test_una_busqueda_sin_resultados_no_revienta(self):
        respuesta = self.listar(q='nadie con este nombre')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context['aspirantes']), 0)

    def test_la_primera_pagina_se_dibuja_sin_error(self):
        """La paginación pedía `previous_page_number` en la página 1.

        Django no silencia el `EmptyPage` que eso lanza, así que la petición
        entera se caía con un error 500 en vez de dibujar el botón apagado.
        """
        self.assertEqual(self.listar().status_code, 200)
        self.assertEqual(self.listar(page=1).status_code, 200)

    def test_el_cargo_de_origen_viaja_hasta_el_enlace(self):
        """Abierto desde el Gestor de Cargos, el contrato hereda la plaza."""
        html = self.listar(cargo='77').content.decode()
        self.assertIn('?cargo=77', html)


class FiltrosDeBajasTests(TestCase):
    """La lista de Bajas filtra por fecha y unidad de la baja (lo usa la Dashboard)
    y, ahora también, por los datos personales del panel, que antes no hacían nada."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from contratos.models import CBaja
        from nomencladores.models import (NCargo, NGrupoEscala, NTipoContrato,
                                          NTipoUnidadOrganizativa)
        from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa

        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        ncargo = NCargo.objects.create(descripcion='Técnico', cat_ocupacional='TEC',
                                       grupo_escala=NGrupoEscala.objects.create(nivel='IV'),
                                       salario_basico=4000)
        cargos = []
        for orden, nombre in enumerate(('UEB Central', 'UEB Norte'), start=1):
            unidad = UnidadOrganizativa.objects.create(
                descripcion=nombre, tipo=tipo_unidad, grupo_nomina=1, orden_informe=orden)
            cargos.append(CargoPlantilla.objects.create(
                ncargo=ncargo, cant_aprobada=5, orden_informe=1,
                departamento=Departamento.objects.create(
                    descripcion='Dpto', unidad_organizativa=unidad, orden_informe=1)))
        cls.central = cargos[0].departamento.unidad_organizativa
        provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')
        tipo = NTipoContrato.objects.create(
            descripcion='Determinado', ocupa_plaza=True, requiere_motivo=False)
        for seq, (fecha, cargo, sexo) in enumerate((
                (date(2026, 9, 20), cargos[0], 'F'),
                (date(2026, 9, 25), cargos[1], 'M'),
                (date(2026, 5, 1), cargos[0], 'F')), start=1):
            aspirante = Aspirante.objects.create(
                nivel_educ='SA', nombre=f'Baja{seq}', papellido='P', sapellido='T',
                doc_identidad=f'8501011230{seq}', estado='BAJA', sexo=sexo, raza='BL',
                provincia=provincia, municipio=municipio)
            CBaja.objects.create(aspirante=aspirante, no_expediente=f'0080{seq}', tipo=tipo,
                                 cargo=cargo, fecha_alta=date(2024, 1, 1), fecha_baja=fecha)
        cls.admin = CustomUser.objects.create_user(
            username='admin_bajas_f', password='x', es_admin=True)

    def nombres(self, url, **params):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse(url), params)
        return sorted(a.nombre for a in respuesta.context['aspirantes'])

    def test_por_fecha_y_unidad_de_la_baja(self):
        self.assertEqual(self.nombres('list_baja', baja_desde='2026-09-12', baja_hasta='2026-10-12'),
                         ['Baja1', 'Baja2'])
        self.assertEqual(self.nombres('search_bajas', baja_desde='2026-09-12', unidad=self.central.pk),
                         ['Baja1'])

    def test_los_datos_personales_ya_filtran_en_bajas(self):
        self.assertEqual(self.nombres('search_bajas', sexo='M'), ['Baja2'])

    def test_prefijo_u_busca_la_unidad_de_la_baja(self):
        """La persona no guarda unidad (campo eliminado el 26-10-2026): U: en Bajas
        busca la unidad donde causó baja."""
        self.assertEqual(self.nombres('search_bajas', filter_aspirante='U:norte'), ['Baja2'])
        self.assertEqual(self.nombres('search_bajas', filter_aspirante='U:central'), ['Baja1', 'Baja3'])


class EliminarPersonaTests(TestCase):
    """La papelera de Aspirantes y Bajas (26-10-2026). La persona no tiene unidad, así
    que el Moderador pide la eliminación de cualquiera por solicitud; con el permiso
    especial «Editar sin solicitud» borra directamente. Antes el Moderador recibía un
    403 «Fuera de su UO asignada» que no se veía en pantalla y no pasaba nada."""

    @classmethod
    def setUpTestData(cls):
        provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')
        cls.personas = {}
        for seq, estado in enumerate(('ASPIRANTE', 'BAJA'), start=1):
            cls.personas[estado] = Aspirante.objects.create(
                nivel_educ='SA', nombre=f'Persona{seq}', papellido='P', sapellido='T',
                doc_identidad=f'8601011230{seq}', estado=estado, sexo='F', raza='BL',
                provincia=provincia, municipio=municipio)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_borrar', password='x', es_moderador=True)

    def borrar(self, persona):
        self.client.force_login(self.moderador)
        return self.client.post(reverse('del_aspir', args=[persona.pk]), HTTP_HX_REQUEST='true')

    def test_moderador_pide_la_eliminacion_de_cualquiera(self):
        from solicitudes.models import Solicitud

        for estado, persona in self.personas.items():
            with self.subTest(estado=estado):
                respuesta = self.borrar(persona)
                self.assertEqual(respuesta.status_code, 204)
                aviso = json.loads(respuesta['HX-Trigger'])['showMessage']['text']
                self.assertIn('Solicitud de eliminación enviada', aviso)
                self.assertTrue(Aspirante.objects.filter(pk=persona.pk).exists())
                self.assertTrue(Solicitud.objects.filter(
                    operacion="aspirante_del", object_id=str(persona.pk)).exists())

    def test_moderador_con_permiso_especial_borra_directamente(self):
        from solicitudes.models import Solicitud
        from usuarios.models import PerfilPermisos

        perfil = PerfilPermisos.objects.create(nombre='Edita', editar_sin_solicitud=True)
        CustomUser.objects.filter(pk=self.moderador.pk).update(perfil_permisos=perfil)
        persona = self.personas['ASPIRANTE']
        respuesta = self.borrar(persona)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Aspirante.objects.filter(pk=persona.pk).exists())
        self.assertFalse(Solicitud.objects.exists())
