"""Pruebas del Dashboard RRHH.

Cubre `DashboardView.get_plazas()`, en particular el caso de sobrecupo
(`cant_cubierta > cant_aprobada`): antes de la corrección, `totales` se
calculaba como `cubiertas + vacantes`, que con sobrecupo queda igual a
`cubiertas` y hace que `porc_cubiertas` dé un 100% falso que esconde el
sobrecupo real. Ahora `totales` es siempre la plantilla aprobada, así que el
porcentaje de ocupación puede superar el 100% cuando corresponde.
"""

from datetime import date

from django.test import RequestFactory, TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from contratos.models import CAlta, CBaja
from dashboard.filtros import resolver_filtros, unidades_visibles
from dashboard.views import (CORTES_EDAD_DEFECTO, DashboardView,
                              _bucket_edad, _categorias_edad,
                              _cortes_edad_desde_request)
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio,
                                   NProvincia, NTipoContrato,
                                   NTipoUnidadOrganizativa)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser


class GetPlazasTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo_unidad, grupo_nomina=1,
            orden_informe=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad, orden_informe=1)
        cls.grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000)

    def test_sin_sobrecupo_totales_coincide_con_aprobadas(self):
        """Caso normal: cubiertas <= aprobadas. `totales` debe seguir dando el
        mismo resultado que antes de la corrección (aprobadas == cubiertas+vacantes)."""
        CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=self.departamento,
            cant_aprobada=10, cant_cubierta=6, orden_informe=1)

        plazas = DashboardView().get_plazas()

        self.assertEqual(plazas['totales'], 10)
        self.assertEqual(plazas['cubiertas'], 6)
        self.assertEqual(plazas['vacantes'], 4)
        self.assertEqual(plazas['porc_cubiertas'], 60.0)
        self.assertEqual(plazas['porc_vacantes'], 40.0)

    def test_sobrecupo_totales_es_la_plantilla_aprobada_no_cubiertas(self):
        """Con sobrecupo (cubiertas > aprobadas), `totales` debe seguir siendo
        la plantilla aprobada, `vacantes` debe quedar en 0 (nunca negativa) y
        `porc_cubiertas` debe reflejar el sobrecupo real (>100%), no un 100%
        artificial que lo esconda."""
        CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=self.departamento,
            cant_aprobada=5, cant_cubierta=8, orden_informe=1)

        plazas = DashboardView().get_plazas()

        self.assertEqual(plazas['totales'], 5)
        self.assertEqual(plazas['cubiertas'], 8)
        self.assertEqual(plazas['vacantes'], 0)
        self.assertEqual(plazas['porc_cubiertas'], 160.0)
        self.assertEqual(plazas['porc_vacantes'], 0.0)

    def test_sin_cargos_activos_no_divide_por_cero(self):
        plazas = DashboardView().get_plazas()

        self.assertEqual(plazas['totales'], 0)
        self.assertEqual(plazas['cubiertas'], 0)
        self.assertEqual(plazas['vacantes'], 0)
        self.assertEqual(plazas['porc_cubiertas'], 0)
        self.assertEqual(plazas['porc_vacantes'], 0)


class PiramideEdadHelpersTests(TestCase):
    """`_cortes_edad_desde_request` es todo-o-nada: si la entrada no cumple
    las tres condiciones (enteros, rango razonable, estrictamente creciente),
    se descarta COMPLETA y se usan los cortes por defecto — nunca se corrige
    parcialmente quitando solo el valor inválido."""

    factory = RequestFactory()

    def _cortes(self, cortes_qs=None):
        url = '/dashboard/' if cortes_qs is None else f'/dashboard/?cortes={cortes_qs}'
        request = self.factory.get(url)
        return _cortes_edad_desde_request(request)

    def test_sin_parametro_usa_defecto(self):
        self.assertEqual(self._cortes(None), CORTES_EDAD_DEFECTO)

    def test_cortes_validos_se_usan_tal_cual(self):
        self.assertEqual(self._cortes('20,30,45,60'), [20, 30, 45, 60])

    def test_letras_caen_a_defecto_completo(self):
        self.assertEqual(self._cortes('20,treinta,45'), CORTES_EDAD_DEFECTO)

    def test_no_creciente_cae_a_defecto_completo(self):
        self.assertEqual(self._cortes('30,20,45'), CORTES_EDAD_DEFECTO)

    def test_repetidos_caen_a_defecto_completo(self):
        self.assertEqual(self._cortes('20,20,45'), CORTES_EDAD_DEFECTO)

    def test_fuera_de_rango_cae_a_defecto_completo(self):
        self.assertEqual(self._cortes('-5,20,45'), CORTES_EDAD_DEFECTO)
        self.assertEqual(self._cortes('20,45,500'), CORTES_EDAD_DEFECTO)

    def test_categorias_se_generan_desde_los_cortes(self):
        self.assertEqual(
            _categorias_edad([25, 35, 45, 55, 65]),
            ['≤25', '26-35', '36-45', '46-55', '56-65', '66+']
        )
        self.assertEqual(
            _categorias_edad([30, 60]),
            ['≤30', '31-60', '61+']
        )

    def test_bucket_edad_cae_en_el_rango_correcto(self):
        cortes = [25, 35, 45]
        self.assertEqual(_bucket_edad(20, cortes), 0)
        self.assertEqual(_bucket_edad(25, cortes), 0)
        self.assertEqual(_bucket_edad(26, cortes), 1)
        self.assertEqual(_bucket_edad(45, cortes), 2)
        self.assertEqual(_bucket_edad(46, cortes), 3)


def _crear_provincia_municipio():
    provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
    municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')
    return provincia, municipio


def _ci_para_edad(edad, seq):
    """Carnet de identidad válido (11 dígitos) cuyo dueño cumple hoy `edad`
    años exactos, siguiendo la misma codificación que `Aspirante._calcular_fecha_nacimiento`."""
    hoy = date.today()
    nacimiento = hoy.replace(year=hoy.year - edad)
    century_digit = 0 if nacimiento.year < 2000 else 6
    return f"{nacimiento.year % 100:02d}{nacimiento.month:02d}{nacimiento.day:02d}{century_digit}{seq:04d}"


class HistoricoAltasBajasTests(TestCase):
    """El histórico de Altas/Bajas del dashboard (gráfico `altasBajasAreaChart`)
    se calcula agrupando `todos_altas`/`todas_bajas` en un único recorrido
    (dashboard/views.py, sección '--- 4. GRÁFICO HISTÓRICO ---'), en vez del
    O(6·N) anterior que recorría las mismas tablas una vez por mes. Aquí se
    verifica que el resultado agregado es el mismo, incluyendo el caso ya
    documentado en el código: alguien dado de alta y de baja cuenta una vez en
    altas gracias a `CBaja.fecha_alta` (CAlta se borra al causar baja)."""

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo_unidad, grupo_nomina=1, orden_informe=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad, orden_informe=1)
        cls.grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000)
        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento, cant_aprobada=10, orden_informe=1)
        cls.provincia, cls.municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)

        hoy = date.today()

        def _meses_atras(n):
            """Misma aritmética año/mes que usa el bucle histórico de
            `DashboardView` (mes_target = hoy.month - i, con acarreo de año) —
            el día se fija a 15 porque el gráfico solo agrupa por (año, mes)."""
            mes = hoy.month - n
            anno = hoy.year
            while mes <= 0:
                mes += 12
                anno -= 1
            return date(anno, mes, 15)

        cls.hace_2_meses = _meses_atras(2)

        def _crear_aspirante(seq, estado):
            return Aspirante.objects.create(
                nombre=f'Trab{seq}', papellido='Prueba', sapellido='Test',
                doc_identidad=_ci_para_edad(30, seq), estado=estado, sexo='F', raza='BL',
                provincia=cls.provincia, municipio=cls.municipio)

        # 1) Alta activa este mes: cuenta como alta en el mes actual.
        cls.asp_activo = _crear_aspirante(1, 'ACTIVO')
        cls.alta_activa = CAlta.objects.create(
            aspirante=cls.asp_activo, no_expediente='00001', tipo=cls.tipo_contrato,
            cargo=cls.cargo, fecha_alta=hoy)

        # 2) Alguien dado de alta hace 2 meses y de baja este mes: debe contar
        # una vez como alta (hace 2 meses, vía CBaja.fecha_alta) y una vez
        # como baja (este mes), sin doble conteo.
        cls.asp_baja = _crear_aspirante(2, 'BAJA')
        cls.baja = CBaja.objects.create(
            aspirante=cls.asp_baja, no_expediente='00002', tipo=cls.tipo_contrato,
            cargo=cls.cargo, fecha_alta=cls.hace_2_meses, fecha_baja=hoy)

        cls.admin = CustomUser.objects.create_user(
            username='admin_dashboard', password='x', es_admin=True)

    def test_historico_cuenta_altas_y_bajas_por_mes_sin_duplicar(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))
        graficos = respuesta.context['graficos']

        # Mes actual: 1 alta (asp_activo) + 1 baja (asp_baja).
        self.assertEqual(graficos['altas'][-1], 1)
        self.assertEqual(graficos['bajas'][-1], 1)
        self.assertEqual(graficos['altas_total'], 1)
        self.assertEqual(graficos['bajas_total'], 1)

        # Hace 2 meses: 1 alta (asp_baja, vía CBaja.fecha_alta), 0 bajas.
        # La ventana histórica cubre 6 meses (índice 5 = mes actual, índice 3 =
        # hace 2 meses), mismo orden que genera el bucle de `views.py`.
        idx_hace_2_meses = 3
        self.assertEqual(graficos['altas'][idx_hace_2_meses], 1)
        self.assertEqual(graficos['bajas'][idx_hace_2_meses], 0)


class FiltrosUOTests(TestCase):
    """`dashboard/filtros.py::resolver_filtros` es el único punto de alcance
    para el Dashboard: un Moderador nunca debe poder ver datos fuera de sus
    UO asignadas, ni siquiera manipulando la querystring a mano."""

    factory = RequestFactory()

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad_propia = UnidadOrganizativa.objects.create(
            descripcion='UEB Propia', tipo=cls.tipo_unidad, grupo_nomina=1, orden_informe=1)
        cls.unidad_ajena = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=cls.tipo_unidad, grupo_nomina=2, orden_informe=2)
        cls.depto_propio = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad_propia, orden_informe=1)
        cls.depto_ajeno = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=cls.unidad_ajena, orden_informe=1)

        cls.admin = CustomUser.objects.create_user(
            username='admin_filtros', password='x', es_admin=True)
        cls.observador = CustomUser.objects.create_user(
            username='obs_filtros', password='x', es_observador=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_filtros', password='x', es_moderador=True)
        cls.moderador.unidades.add(cls.unidad_propia)

    def _request(self, usuario, **params):
        query = '&'.join(f'{k}={v}' for k, v in params.items())
        request = self.factory.get(f'/dashboard/?{query}' if query else '/dashboard/')
        request.user = usuario
        return request

    def test_moderador_solo_ve_su_propia_uo_por_defecto(self):
        uo_ids, depto_ids, _ = resolver_filtros(self._request(self.moderador))
        self.assertEqual(uo_ids, {self.unidad_propia.pk})

    def test_moderador_no_puede_filtrar_uo_ajena_por_querystring(self):
        uo_ids, depto_ids, _ = resolver_filtros(
            self._request(self.moderador, uo=self.unidad_ajena.pk))
        # El id ajeno se descarta; el resultado es el mismo que sin selección:
        # el alcance propio del moderador, nunca la UO ajena ni el universo vacío.
        self.assertEqual(uo_ids, {self.unidad_propia.pk})
        self.assertNotIn(self.unidad_ajena.pk, uo_ids)

    def test_moderador_no_puede_filtrar_departamento_ajeno(self):
        uo_ids, depto_ids, _ = resolver_filtros(
            self._request(self.moderador, depto=self.depto_ajeno.pk))
        self.assertNotIn(self.depto_ajeno.pk, depto_ids)

    def test_administrador_puede_filtrar_cualquier_uo(self):
        uo_ids, depto_ids, _ = resolver_filtros(
            self._request(self.admin, uo=self.unidad_ajena.pk))
        self.assertEqual(uo_ids, {self.unidad_ajena.pk})

    def test_observador_puede_filtrar_cualquier_uo(self):
        uo_ids, depto_ids, _ = resolver_filtros(
            self._request(self.observador, uo=self.unidad_propia.pk))
        self.assertEqual(uo_ids, {self.unidad_propia.pk})

    def test_unidades_visibles_admin_ve_todas(self):
        visibles = set(unidades_visibles(self.admin).values_list('pk', flat=True))
        self.assertEqual(visibles, {self.unidad_propia.pk, self.unidad_ajena.pk})

    def test_unidades_visibles_moderador_solo_las_asignadas(self):
        visibles = set(unidades_visibles(self.moderador).values_list('pk', flat=True))
        self.assertEqual(visibles, {self.unidad_propia.pk})
