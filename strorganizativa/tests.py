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
        self.assertEqual(evento.modulo, 'estructura')  # mismo módulo que en los formularios

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
    """La marca «puesto clave» de la lista de Cargos tiene que distinguir.

    Antes la plantilla leía `c.puesto_clave` sobre un `CargoPlantilla`, y ese
    campo vive en `NCargo`. Django no falla cuando una variable de plantilla no
    existe —la resuelve como cadena vacía—, así que el `{% if %}` era siempre
    falso y NINGÚN cargo salía marcado, contradiciendo al informe de Puestos
    Clave, que sí lee el campo correcto.

    Un fallo así no deja traza en ningún log: la página carga perfecta y solo
    informa mal. De ahí esta prueba, que compara los dos casos en la misma
    respuesta: si alguien vuelve a apuntar al modelo equivocado, la marca
    desaparece de los dos cargos y esto salta.

    La prueba interroga a `htmx_load_cargos`, que es la tercera columna del
    Gestor de Plantilla. Antes interrogaba a `search_cargos_view`, del sistema
    anterior; esa vista se eliminó junto con su plantilla (ver
    `strorganizativa/urls.py`), pero la regresión que vigila sigue siendo
    posible en la pantalla que la sustituyó, así que la prueba se mudó en vez
    de borrarse.
    """

    MARCA_CLAVE = '<i class="fas fa-star"></i> CLAVE'

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import NCargo, NGrupoEscala

        from .models import CargoPlantilla, Departamento

        cls.admin = CustomUser.objects.create_user(
            username='admin_puesto_clave', password='x', es_admin=True)

        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB de prueba')
        unidad = UnidadOrganizativa.objects.create(
            codigo_interno=99, descripcion='UEB Puesto Clave', tipo=tipo, grupo_nomina=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Departamento de prueba', unidad_organizativa=unidad)

        grupo = NGrupoEscala.objects.create(nivel='I')

        ncargo_clave = NCargo.objects.create(
            descripcion='Director de prueba', cat_ocupacional='CDI',
            grupo_escala=grupo, salario_basico=0, puesto_clave=True)
        ncargo_normal = NCargo.objects.create(
            descripcion='Obrero de prueba', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=0, puesto_clave=False)

        cls.cargo_clave = CargoPlantilla.objects.create(
            ncargo=ncargo_clave, departamento=cls.departamento, cant_aprobada=1, orden_informe=1)
        cls.cargo_normal = CargoPlantilla.objects.create(
            ncargo=ncargo_normal, departamento=cls.departamento, cant_aprobada=1, orden_informe=2)

    def _listado(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('htmx_load_cargos', args=[self.departamento.pk]))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.content.decode()

    def test_el_cargo_clave_sale_marcado_y_el_normal_no(self):
        html = self._listado()
        # Los dos cargos están en la respuesta...
        self.assertIn('Director de prueba', html)
        self.assertIn('Obrero de prueba', html)
        # ...pero solo uno lleva la marca. Si la plantilla vuelve a mirar el
        # campo equivocado, este contador valdría 0.
        self.assertEqual(html.count(self.MARCA_CLAVE), 1)

    def test_el_listado_coincide_con_lo_que_dice_la_base_de_datos(self):
        """Blindaje contra la contradicción original entre pantallas."""
        from .models import CargoPlantilla

        html = self._listado()
        esperados = CargoPlantilla.objects.filter(
            departamento=self.departamento, ncargo__puesto_clave=True).count()
        self.assertEqual(html.count(self.MARCA_CLAVE), esperados)


class AlcanceGestorPlantillaTests(TestCase):
    """Las tres columnas del Gestor de Plantilla no pueden servir datos ajenos.

    `htmx_load_departamentos`, `htmx_load_cargos` y `htmx_load_contratos` reciben
    un id por la URL. Antes lo buscaban en toda la tabla, así que un Moderador
    podía leer la plantilla —y los NOMBRES de los trabajadores— de cualquier
    Unidad Organizativa que no tuviera asignada, sin más que cambiar el número a
    mano. El menú no ofrece esos enlaces, pero ocultarlos nunca fue la protección.

    Lo que estas pruebas fijan es la frontera exacta:

    * la unidad asignada, SÍ;
    * la subunidad que cuelga de una unidad asignada, SÍ — el desplegable del
      Gestor ya la pinta, y negarla dejaría filas muertas en pantalla;
    * cualquier otra, NO, y con 404 en vez de 403: así la respuesta no revela
      siquiera si esa unidad existe.

    El Observador queda deliberadamente fuera de esta restricción: su alcance es
    toda la empresa, igual que en el Dashboard y en el listado de Contratos.
    """

    @classmethod
    def setUpTestData(cls):
        from contratos.models import CAlta
        from nomencladores.models import NCargo, NGrupoEscala

        from .models import CargoPlantilla, Departamento

        principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Direccion General', es_principal=True)
        subunidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True)

        # Parcela del moderador: una unidad principal y una subunidad suya.
        cls.propia = UnidadOrganizativa.objects.create(
            codigo_interno=1, descripcion='UEB Propia', tipo=principal, grupo_nomina=1)
        cls.hija = UnidadOrganizativa.objects.create(
            codigo_interno=2, descripcion='Subunidad Propia', tipo=subunidad,
            grupo_nomina=1, padre=cls.propia)

        # Unidad de otro moderador: nada de aqui debe alcanzarse.
        cls.ajena = UnidadOrganizativa.objects.create(
            codigo_interno=3, descripcion='UEB Ajena', tipo=principal, grupo_nomina=2)

        # Desde el 25-10-2026 una unidad principal no puede tener departamentos propios;
        # estos se crean como datos antiguos (sin la validación) porque lo que se prueba
        # aquí es el alcance del Moderador, también sobre esos datos.
        cls.dpto_propio, cls.dpto_ajeno = Departamento.objects.bulk_create([
            Departamento(descripcion='Dpto Propio', unidad_organizativa=cls.propia, orden_informe=1),
            Departamento(descripcion='Dpto Ajeno', unidad_organizativa=cls.ajena, orden_informe=1)])
        cls.dpto_hija = Departamento.objects.create(
            descripcion='Dpto de la Subunidad', unidad_organizativa=cls.hija)

        grupo = NGrupoEscala.objects.create(nivel='I')
        ncargo = NCargo.objects.create(
            descripcion='Especialista', cat_ocupacional='TEC',
            grupo_escala=grupo, salario_basico=0)

        cls.cargo_propio = CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=cls.dpto_propio, cant_aprobada=1, orden_informe=1)
        cls.cargo_ajeno = CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=cls.dpto_ajeno, cant_aprobada=1, orden_informe=1)

        cls.moderador = CustomUser.objects.create_user(
            username='moderador_alcance', password='x', es_moderador=True)
        cls.moderador.unidades.add(cls.propia)

        cls.observador = CustomUser.objects.create_user(
            username='observador_alcance', password='x', es_observador=True)

        cls.admin = CustomUser.objects.create_user(
            username='admin_alcance', password='x', es_admin=True)

    # ------------------------------------------------------------------ ayudas
    def _get(self, usuario, nombre_ruta, pk):
        self.client.force_login(usuario)
        return self.client.get(reverse(nombre_ruta, args=[pk]))

    # ------------------------------------------------- lo que el moderador SI ve
    def test_el_moderador_entra_en_su_propia_unidad(self):
        respuesta = self._get(self.moderador, 'htmx_load_departamentos', self.propia.pk)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Dpto Propio', respuesta.content.decode())

    def test_el_moderador_entra_en_la_subunidad_de_su_unidad(self):
        """El desplegable del Gestor pinta las hijas de una unidad asignada.

        Si esto devolviera 404, esas filas quedarian visibles pero muertas: se
        pulsan y la columna no responde.
        """
        respuesta = self._get(self.moderador, 'htmx_load_departamentos', self.hija.pk)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Dpto de la Subunidad', respuesta.content.decode())

    # ------------------------------------------------- lo que el moderador NO ve
    def test_el_moderador_no_alcanza_los_departamentos_de_otra_unidad(self):
        respuesta = self._get(self.moderador, 'htmx_load_departamentos', self.ajena.pk)
        self.assertEqual(respuesta.status_code, 404)

    def test_el_moderador_no_alcanza_los_cargos_de_otra_unidad(self):
        respuesta = self._get(self.moderador, 'htmx_load_cargos', self.dpto_ajeno.pk)
        self.assertEqual(respuesta.status_code, 404)

    def test_el_moderador_no_alcanza_los_trabajadores_de_otra_unidad(self):
        """La columna 4 lista personas con nombre y apellidos: es la peor fuga."""
        respuesta = self._get(self.moderador, 'htmx_load_contratos', self.cargo_ajeno.pk)
        self.assertEqual(respuesta.status_code, 404)

    def test_sus_propios_cargos_y_trabajadores_si_los_alcanza(self):
        """La restriccion no puede haberse llevado por delante el caso normal."""
        self.assertEqual(
            self._get(self.moderador, 'htmx_load_cargos', self.dpto_propio.pk).status_code, 200)
        self.assertEqual(
            self._get(self.moderador, 'htmx_load_contratos', self.cargo_propio.pk).status_code, 200)

    # --------------------------------------------- observador y administrador
    def test_el_observador_ve_toda_la_empresa(self):
        """Su alcance es global a proposito, igual que en el Dashboard."""
        for ruta, pk in (('htmx_load_departamentos', self.ajena.pk),
                         ('htmx_load_cargos', self.dpto_ajeno.pk),
                         ('htmx_load_contratos', self.cargo_ajeno.pk)):
            with self.subTest(ruta=ruta):
                self.assertEqual(self._get(self.observador, ruta, pk).status_code, 200)

    def test_el_administrador_ve_toda_la_empresa(self):
        for ruta, pk in (('htmx_load_departamentos', self.ajena.pk),
                         ('htmx_load_cargos', self.dpto_ajeno.pk),
                         ('htmx_load_contratos', self.cargo_ajeno.pk)):
            with self.subTest(ruta=ruta):
                self.assertEqual(self._get(self.admin, ruta, pk).status_code, 200)


class ListadoDelGestorNoOcultaNadaTests(TestCase):
    """Una unidad que el usuario puede ver nunca desaparece del listado.

    El Gestor lista arriba solo las unidades raíz y cuelga las subunidades del
    desplegable de su padre. Esa regla da por hecho algo que casi siempre es
    cierto: que quien ve una subunidad ve también a su padre. Cuando no lo era,
    la subunidad no salía por ningún lado y la pantalla aparecía VACÍA, sin un
    mensaje ni una traza en el log que explicara nada.

    Hoy ese dato ya no se puede crear desde la aplicación: una subunidad solo se
    asigna a través de su Unidad Principal (ver `usuarios/forms.py` y
    `strorganizativa/signals.py`). Pero sí puede entrar por un `loaddata` al
    restaurar un backup anterior a esa regla, así que la pantalla tiene que
    aguantarlo en vez de quedarse muda.
    """

    @classmethod
    def setUpTestData(cls):
        principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Oficina', es_principal=True)
        subunidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True)

        cls.padre = UnidadOrganizativa.objects.create(
            codigo_interno=41, descripcion='Oficina Central',
            tipo=principal, grupo_nomina=1)
        cls.hija = UnidadOrganizativa.objects.create(
            codigo_interno=42, descripcion='Camaguey',
            tipo=subunidad, grupo_nomina=1, padre=cls.padre)

        cls.moderador = CustomUser.objects.create_user(
            username='moderador_listado', password='x', es_moderador=True)
        cls.admin = CustomUser.objects.create_user(
            username='admin_listado', password='x', es_admin=True)

    def _listado(self, usuario):
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse('gestor_plantilla'))
        self.assertEqual(respuesta.status_code, 200)
        return [u.descripcion for u in respuesta.context['unidades']]

    def test_con_el_padre_asignado_solo_sale_el_padre(self):
        """El caso normal no cambia: la hija vive en el desplegable del padre."""
        self.moderador.unidades.set([self.padre, self.hija])
        self.assertEqual(self._listado(self.moderador), ['Oficina Central'])

    def test_una_subunidad_sin_su_padre_visible_no_desaparece(self):
        """El dato incoherente que podría llegar restaurando un backup."""
        self.moderador.unidades.set([self.hija])
        self.assertEqual(self._listado(self.moderador), ['Camaguey'])

    def test_el_administrador_sigue_viendo_solo_las_raices(self):
        """Lo ve todo, así que el padre siempre es visible: nada cambia."""
        self.assertEqual(self._listado(self.admin), ['Oficina Central'])


class ExcelEstructuraTests(TestCase):
    """Importar/Exportar la estructura en Excel desde el admin (24-10-2026): todo o
    nada, simular, nunca borra y lo exportado se vuelve a importar sin cambios."""

    @classmethod
    def setUpTestData(cls):
        from .models import Departamento
        cls.ueb = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
        cls.unidad = UnidadOrganizativa.objects.create(descripcion='UEB Florida', tipo=cls.ueb,
                                                       grupo_nomina=1, orden_informe=1)
        Departamento.objects.create(descripcion='Dirección', unidad_organizativa=cls.unidad, orden_informe=1)
        cls.admin = CustomUser.objects.create_user(username='admin_excel', password='x', es_admin=True)

    def libro(self, unidades=(), departamentos=()):
        import io
        from .importacion import exportar_estructura
        libro = exportar_estructura()
        for fila in unidades:
            libro['Unidades'].append(list(fila))
        for fila in departamentos:
            libro['Departamentos'].append(list(fila))
        salida = io.BytesIO()
        libro.save(salida)
        salida.seek(0)
        return salida

    def test_lo_exportado_se_vuelve_a_importar_sin_cambios(self):
        from .importacion import importar_estructura
        resultado = importar_estructura(self.libro(), 'ACTUALIZAR')
        self.assertEqual((resultado['errores'], resultado['creados'], resultado['actualizados']), ([], [], []))
        self.assertEqual(resultado['sin_cambios'], 2)

    def test_crea_unidades_y_departamentos_y_simular_no_guarda(self):
        from .importacion import importar_estructura
        from .models import Departamento
        nuevo = self.libro([(None, 'UEB Najasa', 'ueb', '', '', 2, None)],
                           [('UEB Najasa', 'Grupo Comercial', None)])
        simulado = importar_estructura(nuevo, simular=True)
        self.assertEqual(len(simulado['creados']), 2)
        self.assertFalse(UnidadOrganizativa.objects.filter(descripcion='UEB Najasa').exists())
        nuevo.seek(0)
        importar_estructura(nuevo)
        unidad = UnidadOrganizativa.objects.get(descripcion='UEB Najasa')
        self.assertEqual(unidad.orden_informe, 2)   # sin posición: al final
        self.assertTrue(Departamento.objects.filter(unidad_organizativa=unidad,
                                                    descripcion='Grupo Comercial').exists())

    def test_un_error_no_deja_guardar_nada(self):
        from .importacion import importar_estructura
        resultado = importar_estructura(self.libro([(None, 'UEB Najasa', 'UEB', '', '', 2, None),
                                                    (None, 'UEB Rara', 'No existe', '', '', 1, None)]))
        self.assertIn('el tipo «No existe» no existe', resultado['errores'][0])
        self.assertFalse(UnidadOrganizativa.objects.filter(descripcion='UEB Najasa').exists())

    def test_con_el_codigo_se_renombra_y_saltar_no_toca_lo_existente(self):
        from .importacion import importar_estructura
        fila = [(self.unidad.pk, 'UEB Florida Norte', 'UEB', '', '', 1, 1)]
        importar_estructura(self.libro(fila), 'SALTAR')
        self.unidad.refresh_from_db()
        self.assertEqual(self.unidad.descripcion, 'UEB Florida')
        importar_estructura(self.libro(fila), 'ACTUALIZAR')
        self.unidad.refresh_from_db()
        self.assertEqual(self.unidad.descripcion, 'UEB Florida Norte')

    def test_botones_del_admin(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('admin:strorganizativa_unidadorganizativa_changelist')),
                            'Importar Excel')
        respuesta = self.client.get(reverse('admin:exportar-estructura'))
        self.assertEqual(respuesta['Content-Type'],
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(self.client.get(reverse('admin:importar-estructura')).status_code, 200)


class GrupoDeNominaUnicoTests(TestCase):
    """El grupo de nómina no se repite entre unidades principales o normales; solo lo
    comparten una principal y sus subunidades (24-10-2026)."""

    @classmethod
    def setUpTestData(cls):
        cls.ueb = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
        cls.sub = NTipoUnidadOrganizativa.objects.create(descripcion='Subunidad', es_subunidad=True)
        cls.florida = UnidadOrganizativa.objects.create(descripcion='UEB Florida', tipo=cls.ueb,
                                                        grupo_nomina=7, orden_informe=1)

    def test_otra_unidad_normal_no_puede_usar_el_mismo_grupo(self):
        from .models import unidad_con_el_grupo_de_nomina
        self.assertEqual(unidad_con_el_grupo_de_nomina(7, self.ueb), self.florida)
        self.assertIsNone(unidad_con_el_grupo_de_nomina(7, self.ueb, excluir_pk=self.florida.pk))
        self.assertIsNone(unidad_con_el_grupo_de_nomina(8, self.ueb))

    def test_una_subunidad_si_lo_comparte(self):
        from .models import unidad_con_el_grupo_de_nomina
        self.assertIsNone(unidad_con_el_grupo_de_nomina(7, self.sub))

    def test_el_importador_rechaza_el_grupo_repetido(self):
        import io
        from .importacion import exportar_estructura, importar_estructura
        libro = exportar_estructura()
        libro['Unidades'].append([None, 'UEB Najasa', 'UEB', '', '', 7, None])
        salida = io.BytesIO()
        libro.save(salida)
        salida.seek(0)
        resultado = importar_estructura(salida)
        self.assertTrue(any('el grupo de nómina 7 ya lo tiene' in e for e in resultado['errores']))
        self.assertFalse(UnidadOrganizativa.objects.filter(descripcion='UEB Najasa').exists())


class UnidadPrincipalSinDepartamentosTests(TestCase):
    """Una unidad principal no tiene departamentos propios: los tienen sus subunidades
    (25-10-2026). Lo comprueba el servidor, venga de donde venga."""

    @classmethod
    def setUpTestData(cls):
        from .models import Departamento
        cls.Departamento = Departamento
        cls.principal_tipo = NTipoUnidadOrganizativa.objects.create(descripcion='Dirección General', es_principal=True)
        cls.ueb = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
        cls.principal = UnidadOrganizativa.objects.create(descripcion='Oficina Central', tipo=cls.principal_tipo,
                                                          grupo_nomina=11, orden_informe=1)
        cls.normal = UnidadOrganizativa.objects.create(descripcion='UEB Florida', tipo=cls.ueb,
                                                       grupo_nomina=12, orden_informe=2)

    def test_no_se_crea_un_departamento_en_una_unidad_principal(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as error:
            self.Departamento.objects.create(descripcion='Grupo Jurídico', unidad_organizativa=self.principal)
        self.assertIn('es una unidad principal', str(error.exception))

    def test_una_unidad_con_departamentos_no_pasa_a_principal(self):
        from django.core.exceptions import ValidationError
        self.Departamento.objects.create(descripcion='Dirección', unidad_organizativa=self.normal)
        self.normal.tipo = self.principal_tipo
        with self.assertRaises(ValidationError):
            self.normal.save()

    def test_el_importador_lo_rechaza_en_su_fila(self):
        import io
        from .importacion import exportar_estructura, importar_estructura
        libro = exportar_estructura()
        libro['Departamentos'].append(['Oficina Central', 'Grupo Jurídico', None])
        salida = io.BytesIO()
        libro.save(salida)
        salida.seek(0)
        resultado = importar_estructura(salida)
        self.assertTrue(any('es una unidad principal' in e for e in resultado['errores']), resultado['errores'])
        self.assertFalse(self.Departamento.objects.filter(descripcion='Grupo Jurídico').exists())

    def test_est010_avisa_de_los_que_ya_existian(self):
        from subsanacion.contexto import ContextoAnalisis
        from subsanacion.reglas import obtener_regla
        # Como los datos antiguos: entró sin pasar por la validación.
        self.Departamento.objects.bulk_create([self.Departamento(
            descripcion='Grupo Jurídico', unidad_organizativa=self.principal, orden_informe=1)])
        hallazgos = list(obtener_regla('EST-010').ejecutar(ContextoAnalisis()))
        self.assertEqual([h.object_id for h in hallazgos], [str(self.principal.pk)])
