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
from informes import altas_bajas as altas_bajas_modulo
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

        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
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
        # Un NCargo distinto del de la base: un departamento no puede repetir el
        # mismo cargo del mismo lado de la plantilla. Lo que prueba el test es
        # que el informe recoge una plaza nueva, no de qué cargo es.
        otro_ncargo = NCargo.objects.create(
            descripcion='Especialista A', cat_ocupacional='TEC',
            grupo_escala=self.grupo, salario_basico=4500)
        CargoPlantilla.objects.create(
            ncargo=otro_ncargo, departamento=self.departamento,
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
    """Trabajadores x UEB y Misiones TAMBIÉN admiten el filtro por unidad.

    Antes no lo admitían a propósito (`usar_filtro_ueb=False`), porque con un
    desplegable de una sola unidad Trabajadores x UEB se quedaba en una tabla de
    una fila. Con el selector múltiple el filtro sí tiene sentido —«compara estas
    unidades», «quién de mi UEB está en misión»— y todos los informes se
    comportan igual. Sin nada elegido siguen viéndose enteros, que es lo que
    comprueban estas pruebas junto al caso filtrado.
    """

    def test_trabajadores_ueb_sin_filtro_muestra_todas_las_unidades(self):
        sin_filtro = self.client.get(reverse('informe_trabajadores_ueb'))
        self.assertEqual(sin_filtro.context['total_general'], 1)

    def test_trabajadores_ueb_aplica_el_filtro_por_unidad(self):
        # El contrato de la base vive en `self.unidad`, no en `self.otra_unidad`.
        con_otra = self.client.get(
            reverse('informe_trabajadores_ueb'), {'ueb': str(self.otra_unidad.pk)})
        con_suya = self.client.get(
            reverse('informe_trabajadores_ueb'), {'ueb': str(self.unidad.pk)})

        self.assertEqual(con_otra.context['total_general'], 0)
        self.assertEqual(con_suya.context['total_general'], 1)

    def test_misiones_aplica_el_filtro_por_unidad(self):
        CAlta.objects.filter(pk=self.contrato.pk).update(mision=True, pais='Bolivia')

        sin_filtro = self.client.get(reverse('informe_misiones'))
        con_otra = self.client.get(
            reverse('informe_misiones'), {'ueb': str(self.otra_unidad.pk)})
        con_suya = self.client.get(
            reverse('informe_misiones'), {'ueb': str(self.unidad.pk)})

        self.assertEqual(sin_filtro.context['total_misiones'], 1)
        self.assertEqual(con_otra.context['total_misiones'], 0)
        self.assertEqual(con_suya.context['total_misiones'], 1)

    def test_el_filtro_admite_varias_unidades_a_la_vez(self):
        """La razón de ser del cambio: `?ueb=A&ueb=B` suma las dos."""
        respuesta = self.client.get(
            reverse('informe_trabajadores_ueb'),
            {'ueb': [str(self.unidad.pk), str(self.otra_unidad.pk)]})

        self.assertEqual(respuesta.context['total_general'], 1)


class SelectorDePeriodo(BaseInformes):
    """El toolbar dejó de tener dos <select> y usa el selector común de período.

    Lo que se comprueba es el contrato entre la vista y ese componente: la rejilla
    de meses necesita saber QUÉ meses tienen cierre y ENTRE QUÉ AÑOS moverse, y eso
    lo calcula `resolver_fuente` porque una plantilla de Django no puede desmontar
    un `Periodo` en año y mes.
    """

    def test_sin_cierres_la_rejilla_no_ofrece_ningun_mes(self):
        contexto = self.consolidado().context
        self.assertEqual(contexto['periodos_claves'], [])
        self.assertEqual(contexto['periodos_annos'], [])
        self.assertEqual(contexto['periodo_anno'], '')

    def test_los_meses_con_cierre_llegan_a_la_rejilla(self):
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=date(2026, 7, 22))
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=EN_VENTANA)

        contexto = self.consolidado().context

        self.assertEqual(sorted(contexto['periodos_claves']), ['2026-07', '2026-08'])
        self.assertEqual(contexto['periodos_annos'], [2026])

    def test_el_periodo_elegido_llega_partido_en_anno_y_mes(self):
        servicios_cierres.declarar_actualizada(self.unidad, self.admin, hoy=EN_VENTANA)

        contexto = self.consolidado(fuente='cierre', periodo='2026-08').context

        self.assertEqual(contexto['periodo_anno'], 2026)
        self.assertEqual(contexto['periodo_mes'], 8)

    def test_el_toolbar_pinta_el_componente_y_no_los_selects_viejos(self):
        respuesta = self.consolidado()
        self.assertContains(respuesta, 'caja_periodo_informes')
        self.assertContains(respuesta, 'data-selector-periodo')
        self.assertNotContains(respuesta, 'id="selector-fuente"')
        self.assertNotContains(respuesta, 'id="selector-periodo"')


class FiltroJerarquicoPorUnidad(TestCase):
    """Elegir una Unidad Principal SUMA sus subunidades; elegir una hija la aísla.

    Las dos mitades importan y son la razón de que el filtro sea jerárquico:

    * Una Dirección Principal no tiene cargos propios —todo cuelga de sus
      hijas—, así que sin la suma, filtrar por ella devuelve un informe vacío.
    * Y sin poder elegir la hija por separado no hay forma de responder «¿cómo
      va SOLO este taller?», que es la otra pregunta que se hace a diario.

    Antes el desplegable solo ofrecía unidades raíz, así que la segunda mitad
    era imposible.
    """

    @classmethod
    def setUpTestData(cls):
        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección', es_principal=True, es_subunidad=False)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_principal=False, es_subunidad=True)
        tipo_ueb = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)

        cls.principal = UnidadOrganizativa.objects.create(
            descripcion='Dirección Técnica', tipo=tipo_principal, grupo_nomina=1,
            orden_informe=1)
        cls.taller = UnidadOrganizativa.objects.create(
            descripcion='Taller', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=2)
        cls.almacen = UnidadOrganizativa.objects.create(
            descripcion='Almacén', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=3)
        cls.suelta = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=tipo_ueb, grupo_nomina=2,
            orden_informe=4)

        grupo = NGrupoEscala.objects.create(nivel='V')
        ncargo = NCargo.objects.create(
            descripcion='Mecánico', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=3000)

        # Plazas: 7 en el Taller, 5 en el Almacén, 3 en la UEB suelta.
        # La principal NO tiene cargos propios, como en la realidad.
        for unidad, plazas in ((cls.taller, 7), (cls.almacen, 5), (cls.suelta, 3)):
            departamento = Departamento.objects.create(
                descripcion='Dpto ' + unidad.descripcion,
                unidad_organizativa=unidad, orden_informe=1)
            CargoPlantilla.objects.create(
                ncargo=ncargo, departamento=departamento,
                cant_aprobada=plazas, orden_informe=1)

        cls.admin = CustomUser.objects.create_user(
            username='admin_jerarquia', password='x', es_admin=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def plazas(self, *unidades):
        parametros = {'ueb': [str(u.pk) for u in unidades]} if unidades else {}
        respuesta = self.client.get(reverse('informe_economia'), parametros)
        return respuesta.context['totales']['aprob']

    def test_la_principal_suma_sus_subunidades(self):
        """7 del Taller + 5 del Almacén. La principal no aporta plazas propias."""
        self.assertEqual(self.plazas(self.principal), 12)

    def test_cada_subunidad_se_puede_ver_por_separado(self):
        self.assertEqual(self.plazas(self.taller), 7)
        self.assertEqual(self.plazas(self.almacen), 5)

    def test_sin_filtro_se_ve_todo(self):
        self.assertEqual(self.plazas(), 15)

    def test_se_pueden_combinar_una_principal_y_una_suelta(self):
        self.assertEqual(self.plazas(self.principal, self.suelta), 15)

    def test_el_desplegable_ofrece_las_subunidades_bajo_su_padre(self):
        """Antes solo salían las raíces, así que una subunidad no era elegible."""
        respuesta = self.client.get(reverse('informe_economia'))
        unidades = list(respuesta.context['unidades'])

        nombres = [(u.descripcion, u.nivel) for u in unidades]
        self.assertIn(('Dirección Técnica', 0), nombres)
        self.assertIn(('Taller', 1), nombres)
        self.assertIn(('Almacén', 1), nombres)
        self.assertIn(('UEB Norte', 0), nombres)

    def test_las_hijas_salen_justo_despues_de_su_padre(self):
        """El orden es jerárquico, no alfabético: sin eso la indentación mentiría."""
        respuesta = self.client.get(reverse('informe_economia'))
        nombres = [u.descripcion for u in respuesta.context['unidades']]

        posicion = nombres.index('Dirección Técnica')
        self.assertEqual(nombres[posicion + 1:posicion + 3], ['Taller', 'Almacén'])


class ExportacionesAWord(BaseInformes):
    """Las tres exportaciones a Word tienen que producir un documento de verdad.

    Dos de ellas devolvían un error 500 y nadie se enteraba: no había ninguna
    prueba que las tocara, y el fallo solo se ve al pulsar el botón.

      * «Resumen UEB» tenía el `{%tr for %}` y el `{%tr endfor %}` en la MISMA
        fila de la tabla. docxtpl sustituye la fila ENTERA que contiene una
        etiqueta `{%tr%}` por la etiqueta sola, así que la fila de datos
        desaparecía y jinja se encontraba un `endfor` suelto.
      * «Puestos Clave» apuntaba a una plantilla que no existía.

    Estas pruebas comprueban lo que de verdad importa y no se puede deducir
    leyendo el código: que el .docx se genera, que es un fichero válido, y que no
    quedan etiquetas de plantilla sin sustituir —una etiqueta mal escrita no
    lanza ningún error, simplemente sale impresa en el documento final—.
    """

    def documento(self, nombre_url):
        """Descarga la exportación y devuelve todo su texto."""
        import io as _io
        import zipfile

        respuesta = self.client.get(reverse(nombre_url))
        self.assertEqual(respuesta.status_code, 200,
                         f'{nombre_url} devolvió {respuesta.status_code}: '
                         f'{respuesta.content[:200]}')
        # Un .docx es un ZIP; si la vista devolvió una página de error, no lo es.
        self.assertTrue(zipfile.is_zipfile(_io.BytesIO(respuesta.content)),
                        f'{nombre_url} no devolvió un .docx')

        from docx import Document
        doc = Document(_io.BytesIO(respuesta.content))
        partes = [p.text for p in doc.paragraphs]
        partes += [celda.text for tabla in doc.tables
                   for fila in tabla.rows for celda in fila.cells]
        return '\n'.join(partes)

    def test_el_consolidado_se_genera(self):
        self.documento('exportar_consolidado_word')

    def test_el_resumen_ueb_se_genera(self):
        self.documento('exportar_resumen_ueb_word')

    def test_puestos_clave_se_genera(self):
        self.documento('exportar_puestos_clave_word')

    def test_ninguna_deja_etiquetas_sin_sustituir(self):
        """Una etiqueta mal escrita no falla: se imprime tal cual en el Word."""
        import re

        for nombre_url in ('exportar_consolidado_word',
                           'exportar_resumen_ueb_word',
                           'exportar_puestos_clave_word'):
            texto = self.documento(nombre_url)
            sobrantes = re.findall(r'\{[%{][^}]*[%}]\}', texto)
            self.assertEqual(sobrantes, [],
                             f'{nombre_url} dejó etiquetas sin renderizar: {sobrantes}')

    def test_el_resumen_ueb_repite_una_fila_por_unidad(self):
        """La razón de ser del bucle: si la plantilla vuelve a romperse, la tabla
        saldría con una sola fila o con ninguna."""
        texto = self.documento('exportar_resumen_ueb_word')

        self.assertIn('UEB Central', texto)
        self.assertIn('UEB Norte', texto)


class AlcancePorRol(BaseInformes):
    """Hasta ahora los informes de RRHH no acotaban NADA por usuario.

    Un Moderador de una sola UEB abría el Consolidado y veía la plantilla de toda
    la empresa — mientras que el mismo usuario, en Informe Inteligente, solo veía
    lo suyo. Estas pruebas fijan el criterio nuevo, que es el de aquel módulo:
    Administrador y Observador ven todo; el Moderador, solo sus unidades.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.observador = CustomUser.objects.create_user(
            username='obs_informes', password='x', es_observador=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_informes', password='x', es_moderador=True)
        cls.moderador.unidades.set([cls.unidad])
        cls.moderador_sin_unidades = CustomUser.objects.create_user(
            username='mod_vacio_informes', password='x', es_moderador=True)

    def plazas_de(self, usuario, **parametros):
        self.client.force_login(usuario)
        return self.consolidado(**parametros).context['totales']['aprob']

    def test_el_administrador_ve_la_empresa_entera(self):
        # 10 plazas de UEB Central + 4 de UEB Norte.
        self.assertEqual(self.plazas_de(self.admin), 14)

    def test_el_observador_ve_lo_mismo_que_el_administrador(self):
        """Es un rol de consulta global, igual que en Informe Inteligente."""
        self.assertEqual(self.plazas_de(self.observador), 14)

    def test_el_moderador_solo_ve_sus_unidades(self):
        self.assertEqual(self.plazas_de(self.moderador), 10)

    def test_el_moderador_no_amplia_su_alcance_por_la_url(self):
        """El punto clave: escribir a mano el `?ueb=` de otra unidad no sirve."""
        self.assertEqual(
            self.plazas_de(self.moderador, ueb=str(self.otra_unidad.pk)), 0)

    def test_el_moderador_puede_acotar_dentro_de_lo_suyo(self):
        self.assertEqual(
            self.plazas_de(self.moderador, ueb=str(self.unidad.pk)), 10)

    def test_un_moderador_sin_unidades_no_ve_nada(self):
        """Y NO la empresa entera, que es lo que pasaría si una lista de unidades
        vacía se confundiera con «sin filtro». La regla VIS-007 de Subsanación ya
        reclama a estos usuarios."""
        self.assertEqual(self.plazas_de(self.moderador_sin_unidades), 0)

    def test_el_combo_solo_ofrece_las_unidades_del_moderador(self):
        self.client.force_login(self.moderador)
        unidades = list(self.consolidado().context['unidades'])
        self.assertEqual([u.pk for u in unidades], [self.unidad.pk])


class AlcanceDelModeradorConUnidadPrincipal(TestCase):
    """Una unidad PRINCIPAL no tiene cargos propios: todo cuelga de sus hijas.

    Si el alcance del Moderador no expandiera a las subunidades, quien tuviera
    asignada una Dirección Principal no vería ni una fila. Es la única diferencia
    deliberada con `informe_inteligente.motor._aplicar_alcance_por_rol`, y esta
    prueba es la que la sostiene.
    """

    @classmethod
    def setUpTestData(cls):
        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección', es_principal=True, es_subunidad=False)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_principal=False, es_subunidad=True)

        cls.principal = UnidadOrganizativa.objects.create(
            descripcion='Dirección Técnica', tipo=tipo_principal, grupo_nomina=1,
            orden_informe=1)
        cls.hija = UnidadOrganizativa.objects.create(
            descripcion='Taller', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=2)

        departamento = Departamento.objects.create(
            descripcion='Mantenimiento', unidad_organizativa=cls.hija, orden_informe=1)
        grupo = NGrupoEscala.objects.create(nivel='V')
        ncargo = NCargo.objects.create(
            descripcion='Mecánico', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=3000)
        CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=departamento, cant_aprobada=7, orden_informe=1)

        cls.moderador = CustomUser.objects.create_user(
            username='mod_principal', password='x', es_moderador=True)
        cls.moderador.unidades.set([cls.principal])

    def test_el_moderador_ve_las_plazas_de_las_subunidades(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('informe_economia'))
        self.assertEqual(respuesta.context['totales']['aprob'], 7)


class OrdenEstable(BaseInformes):

    def test_los_contratos_salen_siempre_en_el_mismo_orden(self):
        """Las consultas originales no llevaban ORDER BY: el orden lo decidía
        PostgreSQL y podía cambiar entre dos impresiones del mismo informe."""
        for i, nombre in enumerate(['Zoraida', 'Alberto', 'Mireya']):
            aspirante = Aspirante.objects.create(nivel_educ='SA', 
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


class PuestosClavePorUnidad(TestCase):
    """El informe de Puestos Clave repartido por Unidad Organizativa.

    El modelo oficial no lista los cargos en una sola tabla: los agrupa por
    unidad, y una dirección principal encabeza toda su rama. Hasta ahora el
    informe sumaba cada cargo de todas las unidades juntas, así que no se podía
    saber a quién le faltaban las plazas.
    """

    @classmethod
    def setUpTestData(cls):
        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección', es_principal=True, es_subunidad=False)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True, tipo_padre=tipo_principal)
        tipo_ueb = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)

        cls.principal = UnidadOrganizativa.objects.create(
            descripcion='Oficina Central', tipo=tipo_principal,
            grupo_nomina=1, orden_informe=1)
        cls.taller = UnidadOrganizativa.objects.create(
            descripcion='Taller', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=2)
        cls.almacen = UnidadOrganizativa.objects.create(
            descripcion='Almacén', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=3)
        cls.suelta = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=tipo_ueb, grupo_nomina=2, orden_informe=4)
        # Sin ningún puesto clave: tiene que quedar fuera del informe.
        cls.vacia = UnidadOrganizativa.objects.create(
            descripcion='UEB Sur', tipo=tipo_ueb, grupo_nomina=3, orden_informe=5)

        cls.provincia = NProvincia.objects.create(nombre='Camagüey', siglas='CMG')
        cls.municipio = NMunicipio.objects.create(
            nombre='Nuevitas', provincia=cls.provincia, siglas='NVT')
        cls.principal.municipio = cls.municipio
        cls.principal.save()

        grupo = NGrupoEscala.objects.create(nivel='V')
        cls.clave = NCargo.objects.create(
            descripcion='Liniero', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=3000, puesto_clave=True)
        cls.corriente = NCargo.objects.create(
            descripcion='Auxiliar', cat_ocupacional='SER',
            grupo_escala=grupo, salario_basico=2000, puesto_clave=False)

        def plantilla(unidad, ncargo, aprobadas):
            departamento = Departamento.objects.create(
                descripcion='Dpto ' + unidad.descripcion + ncargo.descripcion,
                unidad_organizativa=unidad, orden_informe=1)
            return CargoPlantilla.objects.create(
                ncargo=ncargo, departamento=departamento,
                cant_aprobada=aprobadas, orden_informe=1)

        cls.plantilla_taller = plantilla(cls.taller, cls.clave, 6)
        cls.plantilla_almacen = plantilla(cls.almacen, cls.clave, 4)
        cls.plantilla_suelta = plantilla(cls.suelta, cls.clave, 5)
        # En la unidad vacía solo hay un cargo que NO es puesto clave.
        plantilla(cls.vacia, cls.corriente, 7)

        # La cabecera de los documentos lee la provincia de Parámetros Generales.
        from configuracion.models import Configuracion
        Configuracion.objects.create(
            nombre_empresa='Empresa de prueba', provincia_entidad=cls.provincia)

        cls.admin = CustomUser.objects.create_user(
            username='admin_puestos', password='x', es_admin=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def informe(self, **parametros):
        # Estas pruebas van del reparto por unidad, así que piden el modo
        # desglosado explícitamente: el informe arranca en consolidado.
        parametros.setdefault('agrupar', 'desglosado')
        return self.client.get(reverse('informe_puestos_clave'), parametros)

    def unidades(self, respuesta):
        familias = respuesta.context['datos_familias']
        self.assertEqual(len(familias), 1, 'se esperaba la familia de Puestos Clave')
        return familias[0]['unidades']

    # --- Estructura ------------------------------------------------------

    def test_cada_unidad_encabeza_sus_propios_cargos(self):
        unidades = self.unidades(self.informe())
        nombres = [u['nombre'] for u in unidades]
        self.assertEqual(nombres, ['Oficina Central', 'UEB Norte'])

    def test_la_principal_arrastra_a_sus_subunidades(self):
        principal = self.unidades(self.informe())[0]
        self.assertEqual(
            [s['nombre'] for s in principal['subunidades']], ['Taller', 'Almacén'])

    def test_los_totales_de_la_principal_suman_los_de_sus_hijas(self):
        principal = self.unidades(self.informe())[0]
        self.assertEqual(principal['subtotales']['aprob'], 10)   # 6 + 4
        self.assertEqual(principal['subunidades'][0]['subtotales']['aprob'], 6)
        self.assertEqual(principal['subunidades'][1]['subtotales']['aprob'], 4)

    def test_una_unidad_sin_puestos_clave_no_aparece(self):
        nombres = [u['nombre'] for u in self.unidades(self.informe())]
        self.assertNotIn('UEB Sur', nombres)

    def test_las_unidades_van_en_el_orden_del_organigrama(self):
        """`orden_informe`, no alfabético: es el orden que la empresa reconoce."""
        principal = self.unidades(self.informe())[0]
        # Taller (orden 2) antes que Almacén (orden 3), pese a la «A».
        self.assertEqual(
            [s['nombre'] for s in principal['subunidades']], ['Taller', 'Almacén'])

    def test_el_mismo_cargo_aparece_una_vez_por_unidad(self):
        """Antes «Liniero» salía una sola vez con las 15 plazas sumadas; ahora
        sale en cada unidad con las suyas, que es lo que permite ver dónde
        falta."""
        principal = self.unidades(self.informe())[0]
        taller, almacen = principal['subunidades']
        self.assertEqual([p['nombre'] for p in taller['puestos']], ['Liniero'])
        self.assertEqual(taller['puestos'][0]['aprob'], 6)
        self.assertEqual(almacen['puestos'][0]['aprob'], 4)

    def test_el_total_del_informe_no_duplica_la_rama(self):
        """Los totales de una principal ya incluyen a sus hijas: sumarlas otra
        vez daría el doble en el resumen de arriba."""
        respuesta = self.informe()
        self.assertEqual(respuesta.context['stats']['aprobada'], 15)  # 6 + 4 + 5

    def test_una_subunidad_sin_su_padre_a_la_vista_sube_a_primer_nivel(self):
        """Le pasa al Moderador que solo lleva una UEB: su unidad no puede
        desaparecer del informe por no estar la principal."""
        moderador = CustomUser.objects.create_user(
            username='mod_puestos', password='x', es_moderador=True)
        moderador.unidades.set([self.taller])
        self.client.force_login(moderador)

        unidades = self.unidades(self.informe())
        self.assertEqual([u['nombre'] for u in unidades], ['Taller'])
        self.assertEqual(unidades[0]['subtotales']['aprob'], 6)

    # --- Cabecera de los documentos --------------------------------------

    def test_sin_unidades_la_cabecera_lleva_provincia_y_firma(self):
        contexto = self.informe().context
        self.assertEqual(contexto['cab_provincia'], 'Camagüey')
        self.assertEqual(contexto['cab_municipio'], '')
        self.assertEqual(contexto['cab_unidades_resumen'], 'Todas las unidades')
        self.assertEqual(contexto['cab_exportado_por'], 'admin_puestos')

    def test_con_una_unidad_la_cabecera_lleva_su_municipio(self):
        contexto = self.informe(ueb=self.principal.pk).context
        self.assertEqual(contexto['cab_provincia'], 'Camagüey')
        self.assertEqual(contexto['cab_municipio'], 'Nuevitas')
        self.assertEqual(contexto['cab_unidades'], ['Oficina Central'])

    def test_con_varias_unidades_no_se_pone_municipio(self):
        """Con dos unidades no hay UN municipio del informe: ponerlo mentiría."""
        contexto = self.informe(ueb=[self.principal.pk, self.suelta.pk]).context
        self.assertEqual(contexto['cab_municipio'], '')
        self.assertEqual(contexto['cab_unidades'],
                         ['Oficina Central', 'UEB Norte'])
        self.assertFalse(contexto['cab_lista_aparte'])

    def test_con_muchas_unidades_la_cabecera_se_resume(self):
        """La cabecera se repite en cada página: no puede crecer con el número
        de unidades. La lista completa se imprime aparte, una sola vez."""
        contexto = self.informe(
            ueb=[self.principal.pk, self.taller.pk, self.almacen.pk,
                 self.suelta.pk]).context
        self.assertTrue(contexto['cab_lista_aparte'])
        self.assertTrue(contexto['cab_unidades_resumen'].endswith('y 2 más'))
        self.assertEqual(len(contexto['cab_unidades']), 4)

    def test_el_nombre_del_trabajador_manda_sobre_el_usuario(self):
        self.admin.contrato = None
        contexto = self.informe().context
        self.assertEqual(contexto['cab_exportado_por'], 'admin_puestos')

    # --- Exportaciones ---------------------------------------------------

    def test_el_word_sale_y_se_llama_por_su_unidad_y_periodo(self):
        respuesta = self.client.get(
            reverse('exportar_puestos_clave_word'), {'ueb': self.principal.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'PK'))
        self.assertIn('Oficina_Central', respuesta['Content-Disposition'])

    def test_el_pdf_sale_con_los_filtros_de_la_pantalla(self):
        respuesta = self.client.get(
            reverse('exportar_puestos_clave_pdf'), {'ueb': self.principal.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')

    def test_una_unidad_que_no_es_un_numero_no_tumba_la_exportacion(self):
        """`?ueb=[]` es lo que escribían los botones de exportar cuando el
        filtro pasó a admitir varias unidades: respondía 500."""
        respuesta = self.client.get(
            reverse('exportar_puestos_clave_pdf'), {'ueb': '[]'})
        self.assertEqual(respuesta.status_code, 200)


class ModoDeAgrupacionPuestosClave(PuestosClavePorUnidad):
    """El selector Desglosado / Consolidado.

    Son los dos informes que la empresa necesita: uno para ver a quién le faltan
    plazas —repartido por unidad— y otro para saber cuántas plazas hay en total
    de un cargo. Antes solo existía el segundo.
    """

    def pedir(self, **parametros):
        return self.client.get(reverse('informe_puestos_clave'), parametros)

    def test_por_defecto_el_informe_sale_consolidado(self):
        respuesta = self.pedir()
        self.assertEqual(respuesta.context['agrupacion'], 'consolidado')

    def test_consolidado_suma_el_cargo_de_todas_las_unidades(self):
        """«Liniero» aparece UNA vez con las 15 plazas de las tres unidades."""
        unidades = self.pedir(agrupar='consolidado').context['datos_familias'][0]['unidades']
        self.assertEqual(len(unidades), 1)
        self.assertEqual(unidades[0]['nombre'], '')
        self.assertEqual([p['nombre'] for p in unidades[0]['puestos']], ['Liniero'])
        self.assertEqual(unidades[0]['puestos'][0]['aprob'], 15)

    def test_desglosado_reparte_el_cargo_por_unidad(self):
        unidades = self.pedir(agrupar='desglosado').context['datos_familias'][0]['unidades']
        self.assertEqual([u['nombre'] for u in unidades],
                         ['Oficina Central', 'UEB Norte'])

    def test_los_totales_generales_no_cambian_entre_modos(self):
        """Lo que cambia es cómo se presenta, no lo que se cuenta."""
        consolidado = self.pedir(agrupar='consolidado').context['stats']
        desglosado = self.pedir(agrupar='desglosado').context['stats']
        self.assertEqual(consolidado, desglosado)

    def test_el_modo_elegido_se_recuerda_en_la_sesion(self):
        """Ir a otro informe y volver no debe devolver al modo por defecto."""
        self.pedir(agrupar='desglosado')
        self.assertEqual(self.pedir().context['agrupacion'], 'desglosado')

    def test_un_modo_inventado_se_ignora(self):
        self.assertEqual(self.pedir(agrupar='xyz').context['agrupacion'],
                         'consolidado')

    def test_las_exportaciones_respetan_el_modo(self):
        respuesta = self.client.get(reverse('exportar_puestos_clave_word'),
                                    {'agrupar': 'desglosado'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'PK'))


class TrabajadoresPorUEB(BaseInformes):
    """El informe por UEB: sus cifras de cabecera y sus dos exportaciones.

    Era el más pobre de los seis —una tabla plana sin cifras— y el único sin
    PDF. Estas pruebas fijan lo que ahora calcula la vista, que es lo que
    comparten la pantalla, el Word y el PDF.
    """

    def informe(self, **parametros):
        return self.client.get(reverse('informe_trabajadores_ueb'), parametros)

    def test_reparte_los_trabajadores_por_unidad(self):
        contexto = self.informe().context
        filas = {d['nombre']: d['total'] for d in contexto['datos_uebs']}
        self.assertEqual(filas['UEB Central'], 1)
        self.assertEqual(filas['UEB Norte'], 0)
        self.assertEqual(contexto['total_general'], 1)

    def test_cada_fila_lleva_su_peso_sobre_el_total(self):
        """Sin el porcentaje la tabla es una lista de números; con él, una
        comparación."""
        filas = {d['nombre']: d['porciento'] for d in self.informe().context['datos_uebs']}
        self.assertEqual(filas['UEB Central'], 100.0)
        self.assertEqual(filas['UEB Norte'], 0)

    def test_las_cifras_de_cabecera_resumen_el_informe(self):
        contexto = self.informe().context
        self.assertEqual(contexto['total_mujeres'], 1)
        self.assertEqual(contexto['porciento_mujeres'], 100.0)
        self.assertEqual(contexto['unidades_con_personal'], 1)
        self.assertEqual(contexto['unidad_mayor']['nombre'], 'UEB Central')

    def test_sin_trabajadores_no_se_divide_por_cero(self):
        """Una unidad recién creada, o un filtro que no devuelve nada, no puede
        tumbar el informe."""
        CAlta.objects.all().delete()
        contexto = self.informe().context
        self.assertEqual(contexto['total_general'], 0)
        self.assertEqual(contexto['porciento_mujeres'], 0)
        self.assertEqual(contexto['unidades_con_personal'], 0)
        self.assertIsNone(contexto['unidad_mayor'])

    def test_exporta_a_pdf(self):
        respuesta = self.client.get(reverse('exportar_resumen_ueb_pdf'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertIn('Trabajadores_UEB', respuesta['Content-Disposition'])

    def test_exporta_a_word(self):
        respuesta = self.client.get(reverse('exportar_resumen_ueb_word'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b'PK'))

    def test_el_pdf_respeta_el_filtro_de_unidad(self):
        respuesta = self.client.get(reverse('exportar_resumen_ueb_pdf'),
                                    {'ueb': self.unidad.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')


class ExportacionesDeMisionesYMotivos(BaseInformes):
    """Las cuatro exportaciones nuevas: Misiones y Contratos Determinados.

    Los dos informes tenían pantalla y nada más. Se comprueba que salen, que
    respetan el filtro de unidad y que la estructura que alimenta al documento
    es la que las plantillas esperan.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contrato.mision = True
        cls.contrato.pais = 'Venezuela'
        cls.contrato.save()

    # --- Misiones --------------------------------------------------------

    def test_misiones_agrupa_por_unidad(self):
        respuesta = self.client.get(reverse('informe_misiones'))
        unidades = respuesta.context['misiones_por_unidad']
        self.assertEqual([u['nombre'] for u in unidades], ['UEB Central'])
        self.assertEqual(unidades[0]['total'], 1)
        self.assertEqual(respuesta.context['total_misiones'], 1)
        self.assertEqual(respuesta.context['paises'], 1)

    def test_misiones_exporta_a_word_y_pdf(self):
        word = self.client.get(reverse('exportar_misiones_word'))
        self.assertEqual(word.status_code, 200)
        self.assertTrue(word.content.startswith(b'PK'))

        pdf = self.client.get(reverse('exportar_misiones_pdf'))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_misiones_respeta_el_filtro_de_unidad(self):
        """Filtrando por la otra unidad no queda nadie en misión."""
        respuesta = self.client.get(reverse('informe_misiones'),
                                    {'ueb': self.otra_unidad.pk})
        self.assertEqual(respuesta.context['total_misiones'], 0)
        self.assertEqual(respuesta.context['misiones_por_unidad'], [])

    # --- Contratos Determinados ------------------------------------------

    def test_cada_motivo_indexa_sus_contratos_de_las_dos_formas(self):
        """`uebs` los reparte por unidad —modo desglosado— y `contratos` los
        guarda todos juntos —modo consolidado—. Son dos índices de los MISMOS
        contratos, así que los totales tienen que coincidir."""
        respuesta = self.client.get(reverse('informe_motivos_contrato'))
        for tipo in respuesta.context['datos_agrupados'].values():
            for motivo in tipo['motivos'].values():
                por_unidad = sum(len(u['contratos']) for u in motivo['uebs'].values())
                self.assertEqual(len(motivo['contratos']), por_unidad)
                self.assertEqual(len(motivo['contratos']), motivo['total'])
                # La unidad viaja con el contrato: en consolidado deja de ser
                # una cabecera y pasa a ser una columna.
                self.assertIn('unidad', motivo['contratos'][0])

    def test_motivos_exporta_a_word_y_pdf(self):
        word = self.client.get(reverse('exportar_motivos_word'))
        self.assertEqual(word.status_code, 200)
        self.assertTrue(word.content.startswith(b'PK'))

        pdf = self.client.get(reverse('exportar_motivos_pdf'))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_los_documentos_llevan_la_fecha_de_generacion(self):
        """Un documento archivado tiene que decir cuándo se sacó. La fecha la
        pone `_cabecera_documento`, común a todos los informes."""
        for nombre in ('informe_misiones', 'informe_motivos_contrato',
                       'informe_trabajadores_ueb', 'informe_puestos_clave'):
            with self.subTest(informe=nombre):
                contexto = self.client.get(reverse(nombre)).context
                self.assertTrue(contexto['fecha_generacion'])
                self.assertIn('cab_provincia', contexto)


class ModoDeAgrupacionMotivos(BaseInformes):
    """El conmutador Desglosado / Consolidado de Contratos Determinados.

    Mismas dos palabras que en Puestos Clave, pero aquí lo que se desglosa son
    tres niveles —tipo de contrato, motivo y unidad— y allí uno. Cada informe
    recuerda su propio modo.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # El informe solo mira los tipos de contrato que exigen motivo.
        cls.tipo_contrato.requiere_motivo = True
        cls.tipo_contrato.save()

    def pedir(self, **parametros):
        return self.client.get(reverse('informe_motivos_contrato'), parametros)

    def test_arranca_desglosado(self):
        """Es como se ha visto siempre esta pantalla: el conmutador solo añade
        la posibilidad de verla corrida."""
        self.assertEqual(self.pedir().context['agrupacion'], 'desglosado')

    def test_desglosado_agrupa_en_tres_niveles(self):
        contexto = self.pedir(agrupar='desglosado').context
        agrupados = contexto['datos_agrupados']
        self.assertTrue(agrupados)
        tipo = list(agrupados.values())[0]
        self.assertIn('motivos', tipo)
        motivo = list(tipo['motivos'].values())[0]
        self.assertIn('uebs', motivo)
        unidad = list(motivo['uebs'].values())[0]
        self.assertIn('contratos', unidad)

    def test_consolidado_agrupa_por_tipo_y_motivo_sin_la_unidad(self):
        """Lo único que se quita es el nivel de la Unidad Organizativa: el tipo
        y el motivo siguen encabezando, como en la pantalla de siempre."""
        contexto = self.pedir(agrupar='consolidado').context
        contratos = 0
        for tipo in contexto['datos_agrupados'].values():
            for motivo in tipo['motivos'].values():
                contratos += len(motivo['contratos'])
        self.assertEqual(contratos, contexto['total_contratos'])

    def test_las_cifras_no_cambian_entre_modos(self):
        desglosado = self.pedir(agrupar='desglosado').context
        consolidado = self.pedir(agrupar='consolidado').context
        for clave in ('total_contratos', 'total_mujeres', 'vencen_critico',
                      'vencen_alerta', 'vencen_vigente'):
            self.assertEqual(desglosado[clave], consolidado[clave], clave)

    def test_cada_informe_recuerda_su_propio_modo(self):
        """Cambiar el de Contratos Determinados no puede cambiar el de Puestos
        Clave: son dos claves de sesión distintas."""
        self.pedir(agrupar='consolidado')
        puestos = self.client.get(reverse('informe_puestos_clave'))
        self.assertEqual(puestos.context['agrupacion'], 'consolidado')

        self.client.get(reverse('informe_puestos_clave'),
                        {'agrupar': 'desglosado'})
        self.assertEqual(self.pedir().context['agrupacion'], 'consolidado')

    def test_el_modo_se_recuerda_en_la_sesion(self):
        self.pedir(agrupar='consolidado')
        self.assertEqual(self.pedir().context['agrupacion'], 'consolidado')

    def test_los_documentos_salen_en_los_dos_modos(self):
        for modo in ('desglosado', 'consolidado'):
            with self.subTest(modo=modo):
                word = self.client.get(reverse('exportar_motivos_word'),
                                       {'agrupar': modo})
                self.assertEqual(word.status_code, 200)
                self.assertTrue(word.content.startswith(b'PK'))

                pdf = self.client.get(reverse('exportar_motivos_pdf'),
                                      {'agrupar': modo})
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(pdf['Content-Type'], 'application/pdf')


class RegistroDiarioExportaYPlan(BaseInformes):
    """El Registro Diario: sus cifras del plan y sus dos exportaciones.

    Era el único informe sin Word ni PDF. Las cifras de la Eficiencia del Plan
    las calculaba solo el JavaScript de la pantalla, así que fuera del navegador
    no existían.
    """

    def informe(self, **parametros):
        return self.client.get(reverse('informe_registro_diario'), parametros)

    def test_las_cifras_del_plan_se_calculan_en_el_servidor(self):
        """Sin esto, el Word y el PDF salían con la eficiencia en blanco: en
        pantalla la calcula JavaScript porque el plan se edita ahí mismo."""
        contexto = self.informe().context
        self.assertEqual(contexto['plan_real'], 1)
        self.assertEqual(contexto['total_mujeres'], 1)
        self.assertEqual(contexto['plan_diferencia'],
                         contexto['plan_real'] - contexto['plan_editable'])
        esperado = round(contexto['plan_real'] * 100 / contexto['plan_editable'], 1)
        self.assertEqual(contexto['plan_cumplimiento'], esperado)

    def test_las_misiones_no_cuentan_como_trabajadores_fisicos(self):
        """«Misiones» es un indicador aparte: sumarlo al total contaría dos
        veces a quien está en misión, que ya está en su categoría."""
        contexto = self.informe().context
        suma_categorias = sum(
            d['tot'] for llave, d in contexto['datos'].items() if llave != 'Misiones')
        self.assertEqual(contexto['plan_real'], suma_categorias)

    def test_un_plan_en_cero_no_divide_por_cero(self):
        from informes.models import PlanMensualRegistro
        from datetime import date

        hoy = date.today()
        PlanMensualRegistro.objects.create(
            mes=str(hoy.month), anno=str(hoy.year), ueb_id='', familia_id='',
            valor=0)
        self.assertEqual(self.informe().context['plan_cumplimiento'], 0)

    def test_exporta_a_word_y_pdf(self):
        word = self.client.get(reverse('exportar_registro_diario_word'))
        self.assertEqual(word.status_code, 200)
        self.assertTrue(word.content.startswith(b'PK'))
        self.assertIn('Registro_Diario', word['Content-Disposition'])

        pdf = self.client.get(reverse('exportar_registro_diario_pdf'))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_los_seis_informes_exportan_en_los_dos_formatos(self):
        """Guarda: que ninguno se quede sin una de las dos salidas."""
        parejas = [
            ('exportar_consolidado_word', 'exportar_consolidado_pdf'),
            ('exportar_resumen_ueb_word', 'exportar_resumen_ueb_pdf'),
            ('exportar_puestos_clave_word', 'exportar_puestos_clave_pdf'),
            ('exportar_misiones_word', 'exportar_misiones_pdf'),
            ('exportar_registro_diario_word', 'exportar_registro_diario_pdf'),
            ('exportar_motivos_word', 'exportar_motivos_pdf'),
        ]
        for ruta_word, ruta_pdf in parejas:
            with self.subTest(informe=ruta_word):
                word = self.client.get(reverse(ruta_word))
                self.assertEqual(word.status_code, 200)
                self.assertTrue(word.content.startswith(b'PK'))

                pdf = self.client.get(reverse(ruta_pdf))
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(pdf['Content-Type'], 'application/pdf')


class AltasYBajasDelMes(BaseInformes):
    """El informe del modelo de la UNE.

    Lo que de verdad se prueba aquí es que las altas se busquen en las DOS
    tablas. Es el único de los siete informes que no puede leer solo `CAlta`:
    dar de baja a alguien BORRA su contrato, así que quien entra y sale el mismo
    mes desaparecería del informe de ese mes.
    """

    def setUp(self):
        super().setUp()
        from contratos.models import CBaja
        self.CBaja = CBaja

        # Entró en marzo y sigue en plantilla.
        self.aspirante_activo = Aspirante.objects.create(
            nivel_educ='NS', nombre='Luis', papellido='Ruiz', sapellido='Mora',
            doc_identidad='90020254321', estado='ACTIVO', sexo='M', raza='BL',
            unidad_organizativa=self.unidad,
            provincia=self.provincia, municipio=self.municipio)
        CAlta.objects.create(
            aspirante=self.aspirante_activo, no_expediente='00200',
            tipo=self.tipo_contrato, cargo=self.cargo,
            fecha_alta=date(2026, 3, 10))

        # Entró en marzo y se fue en abril: solo existe ya como CBaja.
        self.aspirante_ida = Aspirante.objects.create(
            nivel_educ='NG', nombre='Rosa', papellido='Lima', sapellido='Paz',
            doc_identidad='88030398765', estado='BAJA', sexo='F', raza='BL',
            unidad_organizativa=self.unidad,
            provincia=self.provincia, municipio=self.municipio)
        self.baja = CBaja.objects.create(
            aspirante=self.aspirante_ida, no_expediente='00300',
            tipo=self.tipo_contrato, cargo=self.cargo,
            fecha_alta=date(2026, 3, 20), fecha_baja=date(2026, 4, 5),
            fecha_alta_entidad=date(2020, 3, 20))

    def informe(self, **parametros):
        parametros.setdefault('mes', 3)
        parametros.setdefault('anno', 2026)
        return self.client.get(reverse('informe_altas_bajas'), parametros)

    def test_las_altas_incluyen_a_quien_ya_fue_dado_de_baja(self):
        """Rosa entró en marzo y se fue en abril: marzo tiene que contarla.

        Si esta prueba falla, el informe de un mes cerrado devolvería cifras
        distintas cada vez que se genere, que es justo lo que no puede pasar en
        un documento que se archiva.
        """
        respuesta = self.informe()
        nombres = [f.nombre for f in respuesta.context['altas']]
        self.assertIn('Rosa Lima Paz', nombres)
        self.assertIn('Luis Ruiz Mora', nombres)
        self.assertEqual(respuesta.context['resumen_altas']['total'], 2)

    def test_la_baja_sale_en_su_propio_mes_y_no_en_otro(self):
        self.assertEqual(
            self.informe(mes=4).context['resumen_bajas']['total'], 1)
        self.assertEqual(
            self.informe(mes=3).context['resumen_bajas']['total'], 0)

    def test_el_desglose_suma_el_total_de_puestos_clave(self):
        """Si estas dos cifras no cuadran, la hoja de resumen se contradice."""
        resumen = self.informe().context['resumen_altas']
        self.assertEqual(sum(cantidad for _, cantidad in resumen['desglose']),
                         resumen['total_claves'])

    def test_la_antiguedad_se_mide_desde_la_entrada_a_la_entidad(self):
        """Rosa lleva seis años en la empresa aunque su contrato sea de marzo."""
        fila = self.informe(mes=4).context['bajas'][0]
        self.assertEqual(fila.antiguedad, '6 años')

    def test_sin_fecha_de_entidad_se_cae_a_la_del_contrato(self):
        """Las bajas anteriores a la migración no tienen el dato nuevo."""
        self.baja.fecha_alta_entidad = None
        self.baja.save()
        fila = self.informe(mes=4).context['bajas'][0]
        self.assertEqual(fila.antiguedad, '16 días')

    def test_un_mes_imposible_no_revienta(self):
        """La URL se escribe a mano: `?mes=99` cae al mes en curso."""
        self.assertEqual(self.informe(mes=99).status_code, 200)
        self.assertEqual(self.informe(mes='marzo').status_code, 200)

    def test_las_tres_exportaciones_responden(self):
        for nombre in ('exportar_altas_bajas_word',
                       'exportar_altas_bajas_pdf',
                       'exportar_altas_bajas_excel'):
            with self.subTest(exportacion=nombre):
                respuesta = self.client.get(
                    reverse(nombre), {'mes': 3, 'anno': 2026})
                self.assertEqual(respuesta.status_code, 200)
                self.assertGreater(len(respuesta.content), 3000)

    def test_el_moderador_no_ve_los_movimientos_de_otra_unidad(self):
        """El alcance se aplica en el servidor, no limitando el desplegable."""
        moderador = CustomUser.objects.create_user(
            username='mod_altas_bajas', password='x', es_moderador=True)
        moderador.unidades.set([self.otra_unidad])
        self.client.force_login(moderador)

        # Pide explícitamente la unidad que NO tiene asignada.
        respuesta = self.informe(ueb=self.unidad.pk)
        self.assertEqual(respuesta.context['resumen_altas']['total'], 0)

    def test_por_defecto_se_abre_en_el_mes_anterior(self):
        """El que se envía a la UNE es el último mes COMPLETO.

        Abrir en el mes en curso enseñaría un total a medio hacer con toda la
        apariencia de estar terminado.
        """
        from datetime import timedelta
        hoy = date.today()
        anterior = date(hoy.year, hoy.month, 1) - timedelta(days=1)

        contexto = self.client.get(reverse('informe_altas_bajas')).context
        self.assertEqual(contexto['mes_actual'], str(anterior.month))
        self.assertEqual(contexto['anno_actual'], str(anterior.year))

    def test_el_municipio_es_el_de_la_unidad_de_cada_persona(self):
        self.unidad.municipio = self.municipio
        self.unidad.save()
        fila = self.informe().context['altas'][0]
        self.assertEqual(fila.municipio, self.municipio.nombre)

    def test_sin_municipio_declarado_se_escribe_la_marca_de_hueco(self):
        """Una celda en blanco no distingue «no lo tiene» de «se olvidó»."""
        self.unidad.municipio = None
        self.unidad.save()
        fila = self.informe().context['altas'][0]
        self.assertEqual(fila.municipio, altas_bajas_modulo.SIN_MUNICIPIO)

    def test_los_meses_resaltados_son_los_que_tuvieron_movimiento(self):
        """La rejilla del selector marca meses con altas o bajas, no con cierre."""
        claves = self.informe().context['periodos_claves']
        self.assertIn('2026-03', claves)   # las dos altas
        self.assertIn('2026-04', claves)   # la baja
        self.assertNotIn('2026-02', claves)

    def test_el_desglose_de_no_clave_suma_su_propio_total(self):
        """Los dos desgloses juntos tienen que sumar el total del mes."""
        resumen = self.informe().context['resumen_altas']
        suma_clave = sum(c for _, c in resumen['desglose'])
        suma_no_clave = sum(c for _, c in resumen['desglose_no_clave'])

        self.assertEqual(suma_clave, resumen['total_claves'])
        self.assertEqual(suma_no_clave, resumen['total_no_claves'])
        self.assertEqual(suma_clave + suma_no_clave, resumen['total'])

    def test_los_dos_desgloses_se_emparejan_a_la_longitud_del_mayor(self):
        """Las cuatro salidas recorren UNA lista, así que vienen ya cuadradas.

        El de Word son bucles de docxtpl, que no saben ir por dos colecciones a
        la vez; emparejar en Python es lo que permite pintarlos uno al lado del
        otro en los cuatro formatos.
        """
        resumen = self.informe().context['resumen_altas']
        esperado = max(len(resumen['desglose']), len(resumen['desglose_no_clave']))
        self.assertEqual(len(resumen['desglose_par']), esperado)

        # Las celdas sobrantes del bloque más corto van vacías, no a cero: un
        # cero significaría «este cargo tuvo cero movimientos», que es falso.
        for par in resumen['desglose_par']:
            self.assertIn(par['cantidad_clave'].__class__, (int, str))

    def test_las_pantallas_de_detalle_no_repiten_la_provincia(self):
        """Es la misma en todas las filas y ya la declara la cabecera."""
        html = self.informe().content.decode()
        self.assertIn('Municipio', html)
        # El resumen sí la lleva —una vez por cada una de las dos hojas—; las
        # dos listas de personas, no.
        self.assertEqual(html.count('>Provincia</th>'), 2)


class ExportacionesAExcel(BaseInformes):
    """Los SIETE informes de RRHH tienen que producir un libro de verdad.

    Es la misma guardia que `ExportacionesAWord` monta sobre los Word, y por el
    mismo motivo: un fallo en una exportación no se ve hasta que alguien pulsa
    el botón, y son siete botones. La lista se recorre entera, así que añadir un
    informe nuevo sin su Excel hace saltar esta prueba.
    """

    EXPORTACIONES = (
        ('exportar_consolidado_excel', 'Consolidado'),
        ('exportar_resumen_ueb_excel', 'Trabajadores por UEB'),
        ('exportar_puestos_clave_excel', 'Puestos Clave'),
        ('exportar_misiones_excel', 'Misiones'),
        ('exportar_registro_diario_excel', 'Indicadores'),
        ('exportar_motivos_excel', 'Contratos Determinados'),
        ('exportar_altas_bajas_excel', None),
    )

    def libro(self, nombre_url):
        """Descarga la exportación y devuelve el libro ya abierto."""
        import io as _io

        from openpyxl import load_workbook

        respuesta = self.client.get(reverse(nombre_url))
        self.assertEqual(respuesta.status_code, 200,
                         '%s devolvió %s: %s' % (nombre_url,
                                                 respuesta.status_code,
                                                 respuesta.content[:200]))
        return load_workbook(_io.BytesIO(respuesta.content))

    def test_los_siete_generan_un_libro_valido(self):
        for nombre_url, hoja_de_datos in self.EXPORTACIONES:
            with self.subTest(exportacion=nombre_url):
                libro = self.libro(nombre_url)
                # La portada es obligatoria en los siete: es lo que identifica
                # de quién es el documento cuando se envía suelto.
                self.assertIn('Portada', libro.sheetnames)
                if hoja_de_datos:
                    self.assertIn(hoja_de_datos, libro.sheetnames)

    def test_los_seis_propios_llevan_hoja_de_resumen(self):
        """«Altas y Bajas» no la lleva: su resumen son dos hojas del modelo UNE."""
        for nombre_url, _ in self.EXPORTACIONES[:-1]:
            with self.subTest(exportacion=nombre_url):
                self.assertIn('Resumen', self.libro(nombre_url).sheetnames)

    def test_los_informes_con_niveles_traen_las_dos_vistas(self):
        """Una hoja plana y filtrable, y otra que imita los niveles."""
        for nombre_url, plana, niveles in (
                ('exportar_puestos_clave_excel', 'Puestos Clave', 'Por niveles'),
                ('exportar_misiones_excel', 'Misiones', 'Por unidad'),
                ('exportar_motivos_excel', 'Contratos Determinados', 'Por niveles')):
            with self.subTest(exportacion=nombre_url):
                hojas = self.libro(nombre_url).sheetnames
                self.assertIn(plana, hojas)
                self.assertIn(niveles, hojas)

    def test_el_conmutador_manda_sobre_el_volcado(self):
        """En consolidado desaparece el nivel de unidad, como en pantalla.

        Se ejercita el volcado directamente y no la vista porque el juego de
        datos de estas pruebas no tiene contratos determinados, y sin ellos las
        dos hojas saldrían vacías y la comparación no probaría nada.

        La regresión que vigila: antes el modo se decidía mirando si el motivo
        traía `uebs`, y como la vista indexa cada contrato SIEMPRE de las dos
        formas, «Desglosado» y «Consolidado» devolvían el mismo desglose.
        """
        from informes.views import ExportarMotivosExcelView

        class ContratoFalso:
            no_expediente = '00777'
            aspirante_nombre = 'Ana Pérez'
            sexo = 'F'

        contrato = ContratoFalso()
        agrupados = {
            'Determinado': {
                'total': 1,
                'motivos': {
                    'Sustitución': {
                        'total': 1,
                        'uebs': {'UEB Central': {'contratos': [contrato]}},
                        'contratos': [{'contrato': contrato,
                                       'unidad': 'UEB Central'}],
                    },
                },
            },
        }

        vista = ExportarMotivosExcelView()
        _, con_unidad = vista._volcar(agrupados, consolidado=False)
        _, sin_unidad = vista._volcar(agrupados, consolidado=True)

        # Las filas son ternas (papel, profundidad, valores).
        self.assertEqual(len(con_unidad) - len(sin_unidad), 1)
        self.assertTrue(any('UEB Central' in fila[0]
                            for _, _, fila in con_unidad))
        self.assertFalse(any('UEB Central' in fila[0]
                             for _, _, fila in sin_unidad))

        # Y sin el nivel de unidad, el contrato sube un escalón.
        profundidad = {papel: nivel for papel, nivel, _ in sin_unidad}
        self.assertEqual(profundidad['dato'], 2)
