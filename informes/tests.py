"""Pruebas de los informes con las dos fuentes de datos.

Lo que se comprueba aquí es la promesa central del módulo de Cierres: que un
informe histórico **no se mueve** cuando cambian los datos vivos. Si esto se
rompe, un consolidado firmado en agosto daría otras cifras al reimprimirlo, que
es exactamente el problema que la funcionalidad viene a resolver.

También se cubre la regla de negocio que se decidió al planificarlo: una unidad
que no cerró el mes **queda fuera del total y se avisa**, nunca se rellena con
datos actuales.
"""

from datetime import date

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from cierres import servicios as servicios_cierres
from contratos.models import CAlta
from informes import fuentes
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio, NProvincia,
                                  NTipoContrato, NTipoUnidadOrganizativa)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser

from .models import PlanMensualRegistro

EN_VENTANA = date(2026, 8, 22)


class BaseInformes(TestCase):
    """`tipo_unidad` es una UEB de hoja (ni principal ni subunidad), como
    "Florida" o "Nuevitas" en producción: declara directamente sobre sus
    propios cargos. Las Direcciones Principales ya no declaran — su estado se
    agrega a partir de sus hijas — así que no sirven para probar el flujo
    ordinario de declaración que este archivo ejercita.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo_unidad, grupo_nomina=1,
            orden_informe=1)
        cls.otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=cls.tipo_unidad, grupo_nomina=2,
            orden_informe=2)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad, orden_informe=1)
        cls.departamento_norte = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=cls.otra_unidad, orden_informe=1)

        cls.grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000, puesto_clave=True)

        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento,
            cant_aprobada=10, orden_informe=1)
        cls.cargo_norte = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento_norte,
            cant_aprobada=4, orden_informe=1)

        cls.provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        cls.municipio = NMunicipio.objects.create(
            nombre='Playa', provincia=cls.provincia, siglas='PLA')
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)

        cls.aspirante = Aspirante.objects.create(
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad='85010112345', estado='ACTIVO', sexo='F', raza='BL',
            unidad_organizativa=cls.unidad,
            provincia=cls.provincia, municipio=cls.municipio)
        cls.contrato = CAlta.objects.create(
            aspirante=cls.aspirante, no_expediente='00100',
            tipo=cls.tipo_contrato, cargo=cls.cargo, fecha_alta=date(2026, 1, 15))

        cls.admin = CustomUser.objects.create_user(
            username='admin_informes', password='x', es_admin=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def consolidado(self, **parametros):
        return self.client.get(reverse('informe_economia'), parametros)


class FuenteEnTiempoReal(BaseInformes):

    def test_por_defecto_es_la_informacion_actual(self):
        respuesta = self.consolidado()
        self.assertFalse(respuesta.context['es_historico'])

    def test_refleja_los_cambios_al_instante(self):
        antes = self.consolidado().context['totales']['aprob']
        CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=self.departamento,
            cant_aprobada=5, orden_informe=2)

        self.assertEqual(self.consolidado().context['totales']['aprob'], antes + 5)

    def test_un_periodo_inexistente_no_rompe_el_informe(self):
        """Ante un parámetro inválido se cae a modo actual, no a una pantalla de error."""
        respuesta = self.consolidado(fuente='cierre', periodo='2030-12')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.context['es_historico'])

    def test_un_periodo_con_basura_tampoco(self):
        respuesta = self.consolidado(fuente='cierre', periodo='no-es-un-mes')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.context['es_historico'])


class FuenteHistorica(BaseInformes):

    def setUp(self):
        super().setUp()
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=EN_VENTANA)
        servicios_cierres.declarar_actualizada(self.otra_unidad, self.admin, hoy=EN_VENTANA)

    def test_el_selector_solo_ofrece_cierres_existentes(self):
        disponibles = self.consolidado().context['periodos_disponibles']
        self.assertEqual([p.clave for p in disponibles], ['2026-08'])

    def test_el_cierre_no_se_mueve_al_borrar_un_contrato(self):
        """Al dar de baja, el CAlta se borra físicamente. Agosto no puede enterarse."""
        historico = self.consolidado(fuente='cierre', periodo='2026-08')
        totales_agosto = dict(historico.context['totales'])
        self.assertGreater(totales_agosto['t_tot'], 0)

        self.contrato.delete()

        de_nuevo = self.consolidado(fuente='cierre', periodo='2026-08')
        self.assertEqual(dict(de_nuevo.context['totales']), totales_agosto)
        self.assertEqual(de_nuevo.context['fuente_datos'].contratos.__len__(), 1)

        # Y el modo actual sí lo acusa: son dos lecturas distintas del mismo sistema.
        # Se pierde a la vez la plaza cubierta y el contrato determinado, así que
        # `t_tot` cae a cero, no baja de uno en uno.
        actuales = self.consolidado().context['totales']
        self.assertEqual(actuales['t_tot'], 0)
        self.assertEqual(actuales['cub'], 0)
        self.assertEqual(actuales['d_tot'], 0)
        # Las plazas aprobadas no dependen de los contratos: siguen igual.
        self.assertEqual(actuales['aprob'], totales_agosto['aprob'])

    def test_el_cierre_no_se_mueve_al_reclasificar_un_nomenclador(self):
        historico = self.consolidado(fuente='cierre', periodo='2026-08')
        tecnicos = historico.context['datos_tabla']['Técnico']['aprob']
        self.assertGreater(tecnicos, 0)

        NCargo.objects.filter(pk=self.ncargo.pk).update(cat_ocupacional='SER')

        de_nuevo = self.consolidado(fuente='cierre', periodo='2026-08')
        self.assertEqual(de_nuevo.context['datos_tabla']['Técnico']['aprob'], tecnicos)
        self.assertEqual(de_nuevo.context['datos_tabla']['Servicio']['aprob'], 0)

        # En tiempo real, en cambio, ya cuentan como Servicio.
        actual = self.consolidado()
        self.assertEqual(actual.context['datos_tabla']['Técnico']['aprob'], 0)

    def test_el_cierre_no_se_mueve_al_cambiar_las_plazas(self):
        historico = self.consolidado(fuente='cierre', periodo='2026-08')
        aprobadas = historico.context['totales']['aprob']

        CargoPlantilla.objects.filter(pk=self.cargo.pk).update(cant_aprobada=999)

        de_nuevo = self.consolidado(fuente='cierre', periodo='2026-08')
        self.assertEqual(de_nuevo.context['totales']['aprob'], aprobadas)

    def test_el_filtro_por_unidad_sigue_funcionando_en_modo_cierre(self):
        historico = self.consolidado(
            fuente='cierre', periodo='2026-08', ueb=str(self.unidad.pk))
        self.assertEqual(historico.context['totales']['aprob'], 10)

    def test_al_cambiar_de_informe_la_fuente_se_mantiene(self):
        """Todos los informes leen el mismo parámetro, no solo el consolidado."""
        for nombre in ('informe_puestos_clave', 'informe_misiones',
                       'informe_registro_diario', 'informe_motivos_contrato',
                       'informe_trabajadores_ueb'):
            with self.subTest(informe=nombre):
                respuesta = self.client.get(
                    reverse(nombre), {'fuente': 'cierre', 'periodo': '2026-08'})
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.context['es_historico'])


class UnidadesSinCierre(BaseInformes):
    """La regla decidida al planificar: excluir y avisar, nunca mezclar períodos."""

    def test_se_avisa_de_la_unidad_que_no_cerro(self):
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=date(2026, 7, 22))
        servicios_cierres.declarar_actualizada(self.otra_unidad, self.admin, hoy=date(2026, 7, 22))
        # En agosto solo cierra una de las dos.
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=EN_VENTANA)

        respuesta = self.consolidado(fuente='cierre', periodo='2026-08')

        self.assertEqual(respuesta.context['unidades_sin_cierre'], ['UEB Norte'])
        self.assertContains(respuesta, 'no incluye 1 unidad(es)')

    def test_el_total_excluye_a_la_unidad_que_falta(self):
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=date(2026, 7, 22))
        servicios_cierres.declarar_actualizada(self.otra_unidad, self.admin, hoy=date(2026, 7, 22))
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=EN_VENTANA)

        respuesta = self.consolidado(fuente='cierre', periodo='2026-08')

        # Solo las 10 plazas de UEB Central; las 4 de UEB Norte no se inventan.
        self.assertEqual(respuesta.context['totales']['aprob'], 10)

    def test_sin_unidades_faltantes_no_hay_aviso(self):
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=EN_VENTANA)
        servicios_cierres.declarar_actualizada(self.otra_unidad, self.admin, hoy=EN_VENTANA)

        respuesta = self.consolidado(fuente='cierre', periodo='2026-08')

        self.assertEqual(respuesta.context['unidades_sin_cierre'], [])
        self.assertNotContains(respuesta, 'no incluye')


class InformesGlobales(BaseInformes):
    """Trabajadores x UEB y Misiones comparan toda la empresa: no admiten filtro."""

    def test_trabajadores_ueb_ignora_el_parametro_ueb(self):
        con_filtro = self.client.get(
            reverse('informe_trabajadores_ueb'), {'ueb': str(self.otra_unidad.pk)})
        sin_filtro = self.client.get(reverse('informe_trabajadores_ueb'))

        self.assertEqual(con_filtro.context['total_general'],
                         sin_filtro.context['total_general'])

    def test_misiones_ignora_el_parametro_ueb(self):
        CAlta.objects.filter(pk=self.contrato.pk).update(mision=True, pais='Bolivia')

        con_filtro = self.client.get(
            reverse('informe_misiones'), {'ueb': str(self.otra_unidad.pk)})
        self.assertEqual(con_filtro.context['total_misiones'], 1)


class OrdenEstable(BaseInformes):

    def test_los_contratos_salen_siempre_en_el_mismo_orden(self):
        """Las consultas originales no llevaban ORDER BY: el orden lo decidía
        PostgreSQL y podía cambiar entre dos impresiones del mismo informe."""
        for i, nombre in enumerate(['Zoraida', 'Alberto', 'Mireya']):
            aspirante = Aspirante.objects.create(
                nombre=nombre, papellido='Ruiz', sapellido='Paz',
                doc_identidad=f'8501011234{i + 6}', estado='ACTIVO',
                sexo='M', raza='BL', unidad_organizativa=self.unidad,
                provincia=self.provincia, municipio=self.municipio)
            CAlta.objects.create(
                aspirante=aspirante, no_expediente=f'0020{i}',
                tipo=self.tipo_contrato, cargo=self.cargo, fecha_alta=date(2026, 2, 1))

        nombres = [c.aspirante_nombre for c in fuentes.fuente_actual().contratos]
        self.assertEqual(nombres, sorted(nombres, key=str.lower))


class FiltroHistoricoPorUnidadPrincipal(BaseInformes):
    """Las Direcciones Principales (padre) ya no declaran directamente: no
    tienen departamentos ni cargos propios, y su estado se agrega a partir de
    sus hijas (ver `cierres/integracion.py`). Consecuencia real para los
    informes: el padre NUNCA tendrá su propio `CierreUnidad`.

    `expandir_unidades()`, en modo histórico, buscaba al padre dentro del
    diccionario de unidades que SÍ tienen fotografía para poder expandir a sus
    hijas. Sin ese propio cierre, la búsqueda fallaba y filtrar el informe por
    el padre devolvía cero datos aunque las hijas sí hubieran declarado. Estos
    tests prueban el fix: la jerarquía del padre se resuelve contra la
    estructura viva, la de las hijas contra lo que declararon congelado.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tipo_padre = NTipoUnidadOrganizativa.objects.create(
            descripcion='Direccion Principal', es_principal=True)
        cls.padre = UnidadOrganizativa.objects.create(
            descripcion='Oficina Central', tipo=cls.tipo_padre, grupo_nomina=5,
            orden_informe=9)

        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True, tipo_padre=cls.tipo_padre)
        cls.hija_a = UnidadOrganizativa.objects.create(
            descripcion='Sub A', tipo=tipo_sub, padre=cls.padre, orden_informe=1)
        cls.hija_b = UnidadOrganizativa.objects.create(
            descripcion='Sub B', tipo=tipo_sub, padre=cls.padre, orden_informe=2)

        cls.dept_a = Departamento.objects.create(
            descripcion='Depto A', unidad_organizativa=cls.hija_a, orden_informe=1)
        cls.dept_b = Departamento.objects.create(
            descripcion='Depto B', unidad_organizativa=cls.hija_b, orden_informe=1)
        cls.cargo_padre_a = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.dept_a, cant_aprobada=6, orden_informe=1)
        cls.cargo_padre_b = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.dept_b, cant_aprobada=4, orden_informe=1)

        servicios_cierres.declarar_actualizada(cls.hija_a, cls.admin, hoy=EN_VENTANA)
        servicios_cierres.declarar_actualizada(cls.hija_b, cls.admin, hoy=EN_VENTANA)

    def test_el_padre_nunca_tiene_su_propio_cierre(self):
        """Confirma la premisa: nada en el flujo de declaración lo crea."""
        from cierres.models import CierreUnidad
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.padre).exists())

    def test_filtrar_por_el_padre_en_modo_historico_trae_los_datos_de_las_hijas(self):
        respuesta = self.consolidado(
            fuente='cierre', periodo='2026-08', ueb=str(self.padre.pk))

        self.assertEqual(respuesta.context['totales']['aprob'], 10)  # 6 + 4
        self.assertEqual(respuesta.context['unidades_sin_cierre'], [])

    def test_filtrar_por_una_hija_directamente_sigue_funcionando(self):
        """El fix no debe alterar el caso que ya funcionaba: filtrar por una
        unidad que sí tiene su propio cierre."""
        respuesta = self.consolidado(
            fuente='cierre', periodo='2026-08', ueb=str(self.hija_a.pk))

        self.assertEqual(respuesta.context['totales']['aprob'], 6)


class AuditoriaAdminTests(TestCase):
    """Crear/eliminar un PlanMensualRegistro desde el Admin de Django ahora deja
    rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_planmensual', password='x', es_admin=True)

    def test_eliminar_un_registro_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        registro = PlanMensualRegistro.objects.create(
            mes='08', anno='2026', ueb_id='1', familia_id='1', valor=5)
        self.client.force_login(self.admin)

        url = reverse('admin:informes_planmensualregistro_delete', args=[registro.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(PlanMensualRegistro.objects.filter(pk=registro.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(registro.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'informes')

    def test_editar_un_registro_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from informes.admin import PlanMensualRegistroAdmin

        registro = PlanMensualRegistro.objects.create(
            mes='08', anno='2026', ueb_id='2', familia_id='1', valor=5)

        admin_instance = PlanMensualRegistroAdmin(PlanMensualRegistro, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        registro.valor = 9
        admin_instance.save_model(request, registro, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(registro.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
