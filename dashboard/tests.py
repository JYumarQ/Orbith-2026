"""Pruebas del Dashboard RRHH.

Cubre `DashboardView.get_plazas()`, en particular el caso de sobrecupo
(`cant_cubierta > cant_aprobada`): antes de la corrección, `totales` se
calculaba como `cubiertas + vacantes`, que con sobrecupo queda igual a
`cubiertas` y hace que `porc_cubiertas` dé un 100% falso que esconde el
sobrecupo real. Ahora `totales` es siempre la plantilla aprobada, así que el
porcentaje de ocupación puede superar el 100% cuando corresponde.
"""

from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from contratos.models import CAlta, CBaja
from dashboard.filtros import resolver_filtros, unidades_visibles
from dashboard.views import (CORTES_EDAD_DEFECTO, DashboardView,
                              _bucket_edad, _categorias_edad,
                              _cortes_edad_desde_request, _rango_semana)
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio,
                                   NProvincia, NTipoContrato,
                                   NTipoUnidadOrganizativa)
from notificaciones.models import Notificacion
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
            return Aspirante.objects.create(nivel_educ='SA', 
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
        uo_ids, _ = resolver_filtros(self._request(self.moderador))
        self.assertEqual(uo_ids, {self.unidad_propia.pk})

    def test_moderador_no_puede_filtrar_uo_ajena_por_querystring(self):
        uo_ids, _ = resolver_filtros(
            self._request(self.moderador, uo=self.unidad_ajena.pk))
        # El id ajeno se descarta; el resultado es el mismo que sin selección:
        # el alcance propio del moderador, nunca la UO ajena ni el universo vacío.
        self.assertEqual(uo_ids, {self.unidad_propia.pk})
        self.assertNotIn(self.unidad_ajena.pk, uo_ids)

    def test_administrador_puede_filtrar_cualquier_uo(self):
        uo_ids, _ = resolver_filtros(
            self._request(self.admin, uo=self.unidad_ajena.pk))
        self.assertEqual(uo_ids, {self.unidad_ajena.pk})

    def test_observador_puede_filtrar_cualquier_uo(self):
        uo_ids, _ = resolver_filtros(
            self._request(self.observador, uo=self.unidad_propia.pk))
        self.assertEqual(uo_ids, {self.unidad_propia.pk})

    def test_unidades_visibles_admin_ve_todas(self):
        visibles = set(unidades_visibles(self.admin).values_list('pk', flat=True))
        self.assertEqual(visibles, {self.unidad_propia.pk, self.unidad_ajena.pk})

    def test_unidades_visibles_moderador_solo_las_asignadas(self):
        visibles = set(unidades_visibles(self.moderador).values_list('pk', flat=True))
        self.assertEqual(visibles, {self.unidad_propia.pk})

    def test_uo_count_depto_count_sin_seleccion_es_alcance_completo(self):
        # Admin sin seleccionar nada: ve las 2 UO y sus 2 departamentos.
        _, contexto = resolver_filtros(self._request(self.admin))
        self.assertEqual(contexto['uo_count'], 2)
        self.assertEqual(contexto['depto_count'], 2)

    def test_uo_count_depto_count_con_una_uo_seleccionada(self):
        _, contexto = resolver_filtros(
            self._request(self.admin, uo=self.unidad_propia.pk))
        self.assertEqual(contexto['uo_count'], 1)
        self.assertEqual(contexto['depto_count'], 1)

    def test_uo_count_depto_count_con_varias_uo_seleccionadas(self):
        query = f'uo={self.unidad_propia.pk}&uo={self.unidad_ajena.pk}'
        request = self.factory.get(f'/dashboard/?{query}')
        request.user = self.admin
        _, contexto = resolver_filtros(request)
        self.assertEqual(contexto['uo_count'], 2)
        self.assertEqual(contexto['depto_count'], 2)


class RecordatoriosContratoTests(TestCase):
    """La tarjeta Recordatorios del Dashboard reutiliza
    `notificaciones.recordatorios.detectar_contratos_por_vencer` — mismo
    horizonte de 60 días y misma exclusión de contratos "Indeterminado" que
    usa la pestaña Recordatorios de Notificaciones — para no tener dos
    criterios distintos de "cuándo un contrato está por vencer"."""

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
        cls.tipo_determinado = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        cls.tipo_indeterminado = NTipoContrato.objects.create(
            descripcion='Contrato Indeterminado', ocupa_plaza=True, requiere_motivo=False)

        hoy = date.today()

        def _crear_aspirante(seq):
            return Aspirante.objects.create(nivel_educ='SA', 
                nombre=f'Trab{seq}', papellido='Prueba', sapellido='Test',
                doc_identidad=_ci_para_edad(30, seq), estado='ACTIVO', sexo='F', raza='BL',
                provincia=cls.provincia, municipio=cls.municipio)

        # Vence en 30 días: dentro del horizonte de 60 días -> debe aparecer.
        cls.asp_por_vencer = _crear_aspirante(10)
        CAlta.objects.create(
            aspirante=cls.asp_por_vencer, no_expediente='10001', tipo=cls.tipo_determinado,
            cargo=cls.cargo, fecha_alta=hoy - timedelta(days=10), duracion=40)

        # Vence en 90 días: fuera del horizonte -> no debe aparecer.
        cls.asp_lejano = _crear_aspirante(11)
        CAlta.objects.create(
            aspirante=cls.asp_lejano, no_expediente='10002', tipo=cls.tipo_determinado,
            cargo=cls.cargo, fecha_alta=hoy, duracion=90)

        # Indeterminado, vence "pronto" en teoría -> excluido siempre.
        cls.asp_indeterminado = _crear_aspirante(12)
        CAlta.objects.create(
            aspirante=cls.asp_indeterminado, no_expediente='10003', tipo=cls.tipo_indeterminado,
            cargo=cls.cargo, fecha_alta=hoy - timedelta(days=10), duracion=40)

        cls.admin = CustomUser.objects.create_user(
            username='admin_recordatorios', password='x', es_admin=True)

    def _recordatorio(self, *, unidad, titulo='Contrato por vencer', dias=30,
                      clave=''):
        """Un recordatorio ya materializado, que es como existen hoy.

        Los recordatorios dejaron de calcularse al vuelo desde las fechas del
        contrato: los materializa `notificaciones/recordatorios.py` como filas de
        `Notificacion`, y tanto el Dashboard como la pestaña de Notificaciones
        leen de ahí. Por eso el fixture crea la notificación en vez de esperar
        que la vista la deduzca de los `CAlta`.
        """
        from datetime import timedelta

        from django.contrib.contenttypes.models import ContentType
        from django.utils import timezone

        from notificaciones.models import Notificacion

        return Notificacion.objects.create(
            titulo=titulo, mensaje='...',
            tipo=Notificacion.Tipo.RECORDATORIO,
            origen=Notificacion.Origen.SISTEMA,
            codigo_regla='REC-CONTRATO',
            estado=Notificacion.Estado.ACTIVA,
            fecha_objetivo=timezone.localdate() + timedelta(days=dias),
            content_type=ContentType.objects.get_for_model(unidad),
            object_id=str(unidad.pk),
            unidad=unidad,
            # `Notificacion` es unica por (objeto, destinatario, regla,
            # clave_extra): sin variar la clave no se pueden crear dos
            # recordatorios de la misma regla para el mismo usuario.
            clave_extra=clave,
            destinatario=self.admin)

    def test_la_tarjeta_expone_el_conteo_de_recordatorios_visibles(self):
        """El Dashboard ya no decide QUÉ es un recordatorio, solo los cuenta.

        El criterio (horizonte, exclusión de indeterminados) vive ahora en
        `notificaciones/recordatorios.py` y lo cubren sus propias pruebas; aquí
        solo se protege que el Dashboard siga exponiendo `recordatorios_total` y
        su lista, que es lo que la plantilla pinta.
        """
        self._recordatorio(unidad=self.unidad)

        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))

        self.assertEqual(respuesta.context['recordatorios_total'], 1)
        self.assertEqual(len(respuesta.context['recordatorios']), 1)

    def test_la_tarjeta_solo_muestra_diez_aunque_haya_mas(self):
        """`recordatorios_total` cuenta todos; la lista se corta en diez."""
        for indice in range(12):
            self._recordatorio(unidad=self.unidad, titulo=f'Recordatorio {indice}',
                               clave=str(indice))

        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))

        self.assertEqual(respuesta.context['recordatorios_total'], 12)
        self.assertEqual(len(respuesta.context['recordatorios']), 10)

    def test_los_recordatorios_se_acotan_por_la_unidad_del_dashboard(self):
        """Mismo alcance por UO que la tarjeta de Advertencias."""
        otra = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=self.tipo_unidad, grupo_nomina=2,
            orden_informe=2)
        self._recordatorio(unidad=self.unidad, titulo='De mi unidad', clave='a')
        self._recordatorio(unidad=otra, titulo='De la otra unidad', clave='b')

        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'), {'uo': self.unidad.pk})

        self.assertEqual(respuesta.context['recordatorios_total'], 1)
        self.assertEqual(respuesta.context['recordatorios'][0].titulo,
                         'De mi unidad')


class AdvertenciasTests(TestCase):
    """La tarjeta Advertencias reutiliza
    `notificaciones.filtros.filtrar_advertencias` (alcance por usuario/rol,
    filtro de severidad) y además se acota por la UO del Dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo_unidad, grupo_nomina=1, orden_informe=1)
        cls.otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=cls.tipo_unidad, grupo_nomina=2, orden_informe=2)

        cls.admin = CustomUser.objects.create_user(
            username='admin_advertencias', password='x', es_admin=True)

        ct = ContentType.objects.get_for_model(Aspirante)
        cls.advertencia_critica = Notificacion.objects.create(
            titulo='Advertencia crítica', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            estado=Notificacion.Estado.ACTIVA, severidad=10,
            content_type=ct, object_id='1', unidad=cls.unidad, destinatario=cls.admin)
        cls.advertencia_otra_uo = Notificacion.objects.create(
            titulo='Advertencia de otra UO', mensaje='...', tipo=Notificacion.Tipo.ALERTA,
            estado=Notificacion.Estado.ACTIVA, severidad=20,
            content_type=ct, object_id='2', unidad=cls.otra_unidad, destinatario=cls.admin)

    def test_advertencias_aparecen_sin_filtro(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))
        titulos = [a.titulo for a in respuesta.context['advertencias']]
        self.assertIn('Advertencia crítica', titulos)
        self.assertIn('Advertencia de otra UO', titulos)

    def test_advertencias_se_acotan_por_uo_seleccionada(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'), {'uo': self.unidad.pk})
        titulos = [a.titulo for a in respuesta.context['advertencias']]
        self.assertIn('Advertencia crítica', titulos)
        self.assertNotIn('Advertencia de otra UO', titulos)

    def test_advertencias_respeta_filtro_de_severidad(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'), {'severidad': 10})
        titulos = [a.titulo for a in respuesta.context['advertencias']]
        self.assertIn('Advertencia crítica', titulos)
        self.assertNotIn('Advertencia de otra UO', titulos)


class CumpleanosSemanaTests(TestCase):
    """Las pestañas 'Semana actual' y 'Próxima semana' de Cumpleaños usan
    `_rango_semana` (mismo criterio lunes-domingo que Informe Inteligente),
    sin tocar la lógica de 'Cercanos' (que sigue basada en `doc_identidad`,
    sin cambios)."""

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

        lunes_actual, _domingo_actual = _rango_semana(0)
        lunes_prox, _domingo_prox = _rango_semana(1)

        def _fecha_nacimiento_para(fecha_mes_dia, edad=30):
            """Fecha de nacimiento realista (edad ~30) que cae en el mismo
            (mes, día) que `fecha_mes_dia` — el año de esta última es
            irrelevante, solo importan mes/día para el cálculo de cumpleaños."""
            anno = date.today().year - edad
            try:
                return date(anno, fecha_mes_dia.month, fecha_mes_dia.day)
            except ValueError:
                return date(anno, fecha_mes_dia.month, fecha_mes_dia.day - 1)

        def _crear_con_cumple(seq, fecha_nacimiento):
            century_digit = 0 if fecha_nacimiento.year < 2000 else 6
            ci = (f"{fecha_nacimiento.year % 100:02d}{fecha_nacimiento.month:02d}"
                  f"{fecha_nacimiento.day:02d}{century_digit}{seq:04d}")
            asp = Aspirante.objects.create(nivel_educ='SA', 
                nombre=f'Cumple{seq}', papellido='Prueba', sapellido='Test',
                doc_identidad=ci, estado='ACTIVO', sexo='F', raza='BL',
                provincia=cls.provincia, municipio=cls.municipio)
            CAlta.objects.create(
                aspirante=asp, no_expediente=f'2000{seq}', tipo=cls.tipo_contrato,
                cargo=cls.cargo, fecha_alta=date.today() - timedelta(days=365))
            return asp

        cls.asp_esta_semana = _crear_con_cumple(1, _fecha_nacimiento_para(lunes_actual))
        cls.asp_prox_semana = _crear_con_cumple(
            2, _fecha_nacimiento_para(lunes_prox + timedelta(days=3)))
        cls.asp_fuera_de_rango = _crear_con_cumple(
            3, _fecha_nacimiento_para(lunes_actual - timedelta(days=15)))

        cls.admin = CustomUser.objects.create_user(
            username='admin_cumpleanos', password='x', es_admin=True)

    def test_cumpleanos_semana_actual(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))
        nombres = [c['nombre'] for c in respuesta.context['cumpleanos_semana_actual']]
        self.assertTrue(any('Cumple1' in n for n in nombres))
        self.assertFalse(any('Cumple2' in n for n in nombres))
        self.assertFalse(any('Cumple3' in n for n in nombres))

    def test_cumpleanos_proxima_semana(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard'))
        nombres = [c['nombre'] for c in respuesta.context['cumpleanos_semana_prox']]
        self.assertTrue(any('Cumple2' in n for n in nombres))
        self.assertFalse(any('Cumple1' in n for n in nombres))
        self.assertFalse(any('Cumple3' in n for n in nombres))
