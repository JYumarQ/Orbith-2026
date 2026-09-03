"""Qué alcanza —y qué no— el rol Observador.

El Observador es un rol de CONSULTA GLOBAL: ve toda la empresa, pero no escribe
nada en ninguna pantalla. Ocultar un botón o un enlace del menú lateral no es la
protección; la protección son los decoradores y mixins que se comprueban aquí,
porque el menú se puede saltar escribiendo la URL a mano.

Estas pruebas existen porque el reparto estaba incompleto y no se notaba desde la
interfaz: las vistas de Estructura Organizativa (crear/editar/borrar cargos y
departamentos) no comprobaban ningún rol, así que un usuario de solo consulta
podía modificar la plantilla de la empresa con una petición directa. La pantalla
no mostraba los botones, pero el servidor aceptaba la operación.

Cada prueba dice cuál de las tres cosas verifica:
  - PUERTA: qué URL puede abrir y cuál le devuelve 403.
  - ESCRITURA: que ninguna operación de guardado le pase.
  - ALCANCE: que lo que sí ve, lo vea COMPLETO (toda la empresa, no un trozo).
"""

from django.test import TestCase
from django.urls import reverse

from nomencladores.models import NCargo, NGrupoEscala, NTipoUnidadOrganizativa
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa

from .models import CustomUser


class BaseObservadorTests(TestCase):
    """Estructura mínima compartida: dos unidades, para poder distinguir el
    alcance global del alcance por unidad asignada."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_obs', password='x', es_admin=True)
        cls.observador = CustomUser.objects.create_user(
            username='observador_obs', password='x', es_observador=True)
        cls.moderador = CustomUser.objects.create_user(
            username='moderador_obs', password='x', es_moderador=True)

        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB de prueba')

        # `unidad_propia` se asigna al Moderador; `unidad_ajena` no se asigna a
        # nadie. La diferencia entre las dos es lo que revela si el alcance del
        # Observador es global o se quedó recortado al de un Moderador.
        cls.unidad_propia = UnidadOrganizativa.objects.create(
            codigo_interno=901, descripcion='UEB Propia Observador',
            tipo=tipo, grupo_nomina=901)
        cls.unidad_ajena = UnidadOrganizativa.objects.create(
            codigo_interno=902, descripcion='UEB Ajena Observador',
            tipo=tipo, grupo_nomina=902)
        cls.moderador.unidades.add(cls.unidad_propia)

        cls.departamento = Departamento.objects.create(
            descripcion='Departamento Observador',
            unidad_organizativa=cls.unidad_propia)

        grupo = NGrupoEscala.objects.create(nivel='I')
        cls.ncargo = NCargo.objects.create(
            descripcion='Cargo Observador', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=0)
        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento,
            cant_aprobada=1, orden_informe=1)


class PuertasDelObservadorTests(BaseObservadorTests):
    """PUERTA: qué URLs abre y cuáles le devuelven 403."""

    # Lo que el Observador SÍ debe poder consultar. Es la lista literal que pidió
    # el usuario; si mañana alguien cierra una de estas por error, salta aquí.
    PERMITIDAS = [
        'dashboard',
        'list_contrato',
        'list_aspir',
        'list_baja',
        'list_movimientos',
        'gestor_plantilla',
    ]

    # Lo que NO debe alcanzar ni escribiendo la URL. Cada una está cerrada por un
    # decorador distinto, por eso se prueban todas y no una de muestra.
    PROHIBIDAS = [
        ('lista_notificaciones', 'panel de Notificaciones'),
        ('familias_cargo', 'Familias de Cargos'),
        ('parametros', 'Parámetros Generales'),
        ('list_usuarios', 'listado de Usuarios'),
        ('list_solicitudes', 'módulo de Solicitudes'),
        ('list_cierres', 'módulo de Cierres'),
    ]

    def test_puede_abrir_las_pantallas_de_consulta(self):
        self.client.force_login(self.observador)
        for nombre in self.PERMITIDAS:
            with self.subTest(url=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertEqual(
                    respuesta.status_code, 200,
                    'El Observador debería poder consultar «%s».' % nombre)

    def test_no_alcanza_lo_que_no_es_suyo_ni_por_url(self):
        self.client.force_login(self.observador)
        for nombre, descripcion in self.PROHIBIDAS:
            with self.subTest(url=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertEqual(
                    respuesta.status_code, 403,
                    'El Observador no debería alcanzar el %s.' % descripcion)

    def test_prenomina_y_subsanacion_le_estan_cerradas(self):
        """Van aparte porque usan namespace y responden por su propio permisos.py."""
        self.client.force_login(self.observador)
        for nombre in ('prenomina:lista_reportes', 'subsanacion:index'):
            with self.subTest(url=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertEqual(respuesta.status_code, 403)


class EscrituraDelObservadorTests(BaseObservadorTests):
    """ESCRITURA: ninguna operación de guardado puede pasar.

    Este es el bloque que cubre el agujero real: `strorganizativa` no comprobaba
    ningún rol, así que estas mismas peticiones devolvían 200/302 y modificaban
    la base de datos.
    """

    def test_no_puede_crear_ni_editar_ni_borrar_estructura(self):
        self.client.force_login(self.observador)

        peticiones = [
            ('get', reverse('add_cargo'), {}),
            ('get', reverse('updt_cargo', args=[self.cargo.pk]), {}),
            ('post', reverse('del_cargoplantilla', args=[self.cargo.pk]), {}),
            ('get', reverse('add_dpto'), {}),
            ('get', reverse('updt_dpto', args=[self.departamento.pk]), {}),
            ('post', reverse('del_dpto', args=[self.departamento.pk]), {}),
            ('get', reverse('updt_uniorg', args=[self.unidad_propia.pk]), {}),
        ]

        for metodo, url, datos in peticiones:
            with self.subTest(url=url):
                respuesta = getattr(self.client, metodo)(url, datos)
                self.assertEqual(
                    respuesta.status_code, 403,
                    'El Observador no debería poder %s %s.' % (metodo.upper(), url))

    def test_la_estructura_sigue_intacta_tras_intentarlo(self):
        """El 403 tiene que llegar ANTES de tocar la base de datos."""
        self.client.force_login(self.observador)
        self.client.post(reverse('del_cargoplantilla', args=[self.cargo.pk]))
        self.client.post(reverse('del_dpto', args=[self.departamento.pk]))

        self.assertTrue(CargoPlantilla.objects.filter(pk=self.cargo.pk).exists())
        self.assertTrue(Departamento.objects.filter(pk=self.departamento.pk).exists())

    def test_no_puede_guardar_el_plan_mensual_de_informes(self):
        """La única vista de escritura de Informes. Responde JSON, así que el
        rechazo llega como 403 con cuerpo JSON, no como página de error."""
        self.client.force_login(self.observador)
        respuesta = self.client.post(
            reverse('guardar_plan_diario'),
            data='{"mes": 1, "anno": 2026, "valor": 5}',
            content_type='application/json')
        self.assertEqual(respuesta.status_code, 403)

    def test_una_peticion_htmx_recibe_json_y_no_una_pantalla_rota(self):
        """El Gestor de Plantilla habla por HTMX/JSON: un 403 en HTML se vería
        como un modal roto en vez de como un aviso."""
        self.client.force_login(self.observador)
        respuesta = self.client.post(
            reverse('del_cargoplantilla', args=[self.cargo.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(respuesta['Content-Type'], 'application/json')
        self.assertIn('error_popup', respuesta.json())


class AlcanceDelObservadorTests(BaseObservadorTests):
    """ALCANCE: lo que ve, lo ve completo.

    El Gestor de Plantilla decidía el alcance con `is_superuser`. El Observador no
    lo es, así que caía en la rama del Moderador y solo veía sus unidades
    asignadas —ninguna—: la pantalla le salía vacía pese a ser un rol de consulta
    global, igual que en el Dashboard y en el listado de Contratos.
    """

    def test_ve_todas_las_unidades_aunque_no_tenga_ninguna_asignada(self):
        self.assertEqual(self.observador.unidades.count(), 0)

        self.client.force_login(self.observador)
        html = self.client.get(reverse('gestor_plantilla')).content.decode()

        self.assertIn('UEB Propia Observador', html)
        self.assertIn('UEB Ajena Observador', html)

    def test_el_moderador_sigue_viendo_solo_las_suyas(self):
        """Contraprueba: el cambio de alcance no debe haber abierto el Gestor a
        todo el mundo, solo al Observador."""
        self.client.force_login(self.moderador)
        html = self.client.get(reverse('gestor_plantilla')).content.decode()

        self.assertIn('UEB Propia Observador', html)
        self.assertNotIn('UEB Ajena Observador', html)

    def test_el_gestor_no_le_ofrece_botones_de_escritura(self):
        """Coherencia entre lo que se pinta y lo que el servidor acepta: si el
        botón apareciera, el Observador solo descubriría el 403 al pulsarlo."""
        self.client.force_login(self.observador)
        html = self.client.get(reverse('gestor_plantilla')).content.decode()

        # Se busca el ATRIBUTO (`id="..."`), no el nombre suelto: los mismos
        # identificadores aparecen como cadenas dentro del JavaScript de la
        # página —`enableAddBtn('btn-create-dept', …)`— y ese código sigue ahí
        # para todos los roles.
        for boton in ('btn-create-dept', 'btn-create-cargo',
                      'btn-edit-dept', 'btn-del-dept',
                      'btn-edit-cargo', 'btn-del-cargo', 'btn-edit-unit'):
            with self.subTest(boton=boton):
                self.assertNotIn('id="%s"' % boton, html)

    def test_el_administrador_si_los_ve(self):
        """Contraprueba del anterior: los botones no se han perdido para todos."""
        self.client.force_login(self.admin)
        html = self.client.get(reverse('gestor_plantilla')).content.decode()

        self.assertIn('id="btn-create-dept"', html)
        self.assertIn('id="btn-edit-unit"', html)
