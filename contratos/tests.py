"""Pruebas del "escudo" de `CAlta.save()` sobre el campo `tridente`.

El tridente solo aplica a un contrato de salario dinámico cuyo cargo NO es de
categoría Cuadro (Directivo o Ejecutivo) — misma "REGLA DE ORO" que
`CAltaForm.clean()` y que `contratos/salarios.py::calcular_salario()`. Estas
pruebas cubren el "escudo" de `save()`, que es la última línea de defensa para
cualquier guardado que no pase por el formulario (admin de Django, scripts).
"""

from datetime import date, timedelta
from decimal import Decimal

from django import forms
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from bolsa.models import Aspirante
from contratos.filtros import aplicar_filtros
from contratos.forms import CAltaForm, MovimientoForm
from contratos.models import CAlta, CBaja, TMovimiento
from nomencladores.models import (NCargo, NGrupoEscala, NImporteGradoCientifico,
                                  NMunicipio, NPagoAdicional, NProvincia,
                                   NTipoContrato, NTipoUnidadOrganizativa, NTridente)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser


def _crear_provincia_municipio():
    provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
    municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')
    return provincia, municipio


class EscudoTridenteTests(TestCase):
    """`CAlta.save()` debe dejar el tridente en el mismo estado que
    `CAltaForm.clean()` dejaría, sin pasar por el formulario."""

    @classmethod
    def setUpTestData(cls):
        cls.tridente_i = NTridente.objects.create(tipo='I')

        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Dirección', unidad_organizativa=unidad, orden_informe=1)

        cls.grupo = NGrupoEscala.objects.create(nivel='IV')

        cls.ncargo_cuadro = NCargo.objects.create(
            descripcion='Director', cat_ocupacional='CDI',
            grupo_escala=cls.grupo, salario_basico=8000)
        cls.cargo_cuadro = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_cuadro, departamento=cls.departamento,
            cant_aprobada=1, orden_informe=1)

        cls.ncargo_no_cuadro = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000)
        cls.cargo_no_cuadro = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_no_cuadro, departamento=cls.departamento,
            cant_aprobada=10, orden_informe=2)

        provincia, municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)

        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112345', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)

    def _crear_alta(self, cargo, tipo_salario, tridente=None, no_expediente='00001'):
        return CAlta.objects.create(
            aspirante=self.aspirante, no_expediente=no_expediente, tipo=self.tipo_contrato,
            cargo=cargo, fecha_alta=date.today(), tipo_salario=tipo_salario, tridente=tridente)

    def test_dinamico_en_cuadro_limpia_el_tridente(self):
        """Caso real reportado ("Fvdb Fdbfdb Dfb"): dinámico + cargo Cuadro + tridente."""
        alta = self._crear_alta(self.cargo_cuadro, 'DIN', tridente=self.tridente_i)
        alta.refresh_from_db()
        self.assertIsNone(alta.tridente_id)

    def test_fijo_limpia_el_tridente(self):
        alta = self._crear_alta(self.cargo_no_cuadro, 'FIJ', tridente=self.tridente_i)
        alta.refresh_from_db()
        self.assertIsNone(alta.tridente_id)

    def test_dinamico_sin_cuadro_y_sin_tridente_no_recibe_uno_por_defecto(self):
        """Sin «Tridente I» automático (decisión de RRHH del 23-10-2026): nadie lo
        habría elegido. Se queda sin tridente y SAL-002 avisa."""
        alta = self._crear_alta(self.cargo_no_cuadro, 'DIN', tridente=None)
        alta.refresh_from_db()
        self.assertIsNone(alta.tridente_id)

    def test_dinamico_sin_cuadro_conserva_el_tridente_asignado(self):
        otro_tridente = NTridente.objects.create(tipo='II')
        alta = self._crear_alta(self.cargo_no_cuadro, 'DIN', tridente=otro_tridente)
        alta.refresh_from_db()
        self.assertEqual(alta.tridente_id, otro_tridente.pk)

    def test_guardar_cierra_el_hallazgo_de_subsanacion_sin_esperar_al_analisis(self):
        """El caso real reportado: un hallazgo CTR-009 quedó pendiente de un
        análisis anterior; el usuario abre el contrato y lo guarda (sin tocar nada
        más), y el hallazgo debe quedar Corregido de inmediato, no solo cuando
        alguien vuelva a ejecutar un análisis completo."""
        from django.contrib.contenttypes.models import ContentType

        from subsanacion.constantes import CRITICIDAD_BAJA, MODULO_CONTRATOS
        from subsanacion.models import Hallazgo

        alta = self._crear_alta(self.cargo_no_cuadro, 'DIN', tridente=self.tridente_i)

        # Se fuerza el estado inconsistente saltándose save()/el escudo (igual que lo
        # haría un bulk_update, un script o el admin de Django sin CAltaForm), para
        # reproducir el caso real sin depender de que el escudo tenga un agujero.
        CAlta.objects.filter(pk=alta.pk).update(cargo=self.cargo_cuadro)

        tipo = ContentType.objects.get_for_model(CAlta, for_concrete_model=True)
        pendiente = Hallazgo.objects.create(
            codigo_regla='CTR-009', content_type=tipo, object_id=str(alta.pk),
            clave_extra='cuadro_con_tridente', modulo=MODULO_CONTRATOS,
            criticidad=CRITICIDAD_BAJA, titulo='Tridente indebido',
            ultima_deteccion=timezone.now(), estado=Hallazgo.PENDIENTE)

        # El usuario abre el contrato y lo guarda: instancia nueva, como la que
        # construye el formulario, no la misma que hizo el .update() de arriba.
        CAlta.objects.get(pk=alta.pk).save()

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, Hallazgo.CORREGIDO)
        self.assertFalse(pendiente.vigente)
        self.assertTrue(pendiente.resuelto_automaticamente)


class AplicarFiltrosTests(TestCase):
    """`contratos/filtros.py::aplicar_filtros` — filtros nuevos añadidos para
    que los gráficos del Dashboard puedan redirigir a Contratos filtrado:
    `cat_ocupacional` (incluyendo el sentinel "CUA" que agrupa Cuadro
    Directivo/Ejecutivo) y `tipo`; más el sentinel `grado_cientifico=NINGUNO`
    para quienes no tienen grado científico registrado."""

    @classmethod
    def setUpTestData(cls):
        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=unidad, orden_informe=1)
        cls.grupo = NGrupoEscala.objects.create(nivel='IV')

        cls.ncargo_tecnico = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000)
        cls.ncargo_cuadro = NCargo.objects.create(
            descripcion='Director', cat_ocupacional='CDI',
            grupo_escala=cls.grupo, salario_basico=6000)

        cls.cargo_tecnico = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_tecnico, departamento=cls.departamento, cant_aprobada=5, orden_informe=1)
        cls.cargo_cuadro = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_cuadro, departamento=cls.departamento, cant_aprobada=1, orden_informe=2)

        provincia, municipio = _crear_provincia_municipio()

        cls.tipo_determinado = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        cls.tipo_indeterminado = NTipoContrato.objects.create(
            descripcion='Contrato Indeterminado', ocupa_plaza=True, requiere_motivo=False)

        def _crear_aspirante(seq, grado_cientifico=None):
            return Aspirante.objects.create(nivel_educ='SA', 
                nombre=f'Trab{seq}', papellido='Prueba', sapellido='Test',
                doc_identidad=f'{seq:011d}', estado='ACTIVO', sexo='F', raza='BL',
                grado_cientifico=grado_cientifico,
                provincia=provincia, municipio=municipio)

        cls.asp_tecnico = _crear_aspirante(1)
        cls.contrato_tecnico = CAlta.objects.create(
            aspirante=cls.asp_tecnico, no_expediente='00001', tipo=cls.tipo_determinado,
            cargo=cls.cargo_tecnico)

        cls.asp_cuadro = _crear_aspirante(2)
        cls.contrato_cuadro = CAlta.objects.create(
            aspirante=cls.asp_cuadro, no_expediente='00002', tipo=cls.tipo_indeterminado,
            cargo=cls.cargo_cuadro)

        cls.asp_master = _crear_aspirante(3, grado_cientifico='MC')
        cls.contrato_master = CAlta.objects.create(
            aspirante=cls.asp_master, no_expediente='00003', tipo=cls.tipo_determinado,
            cargo=cls.cargo_tecnico)

    def _filtrar(self, **params):
        request = RequestFactory().get('/contrato/', params)
        return set(aplicar_filtros(request, CAlta.objects.all()).values_list('pk', flat=True))

    def test_cat_ocupacional_filtra_por_codigo_directo(self):
        resultado = self._filtrar(cat_ocupacional='TEC')
        self.assertEqual(resultado, {self.contrato_tecnico.pk, self.contrato_master.pk})

    def test_cat_ocupacional_cua_agrupa_cdi_y_cej(self):
        resultado = self._filtrar(cat_ocupacional='CUA')
        self.assertEqual(resultado, {self.contrato_cuadro.pk})

    def test_tipo_filtra_por_descripcion_exacta(self):
        resultado = self._filtrar(tipo='Contrato Indeterminado')
        self.assertEqual(resultado, {self.contrato_cuadro.pk})

    def test_grado_cientifico_ninguno_incluye_null_y_vacio(self):
        resultado = self._filtrar(grado_cientifico='NINGUNO')
        self.assertEqual(resultado, {self.contrato_tecnico.pk, self.contrato_cuadro.pk})

    def test_grado_cientifico_master_filtra_exacto(self):
        resultado = self._filtrar(grado_cientifico='MC')
        self.assertEqual(resultado, {self.contrato_master.pk})

    def test_sin_filtros_devuelve_todo(self):
        resultado = self._filtrar()
        self.assertEqual(
            resultado,
            {self.contrato_tecnico.pk, self.contrato_cuadro.pk, self.contrato_master.pk})


class ContratoListViewCargaInicialTests(TestCase):
    """La carga inicial de `/contrato/list_contrato/` (sin pasar por la
    búsqueda AJAX `search_contrato`) debe respetar los filtros de la
    querystring — es lo que hace que un enlace desde el Dashboard llegue ya
    filtrado, sin depender de que el usuario toque un `<select>`."""

    @classmethod
    def setUpTestData(cls):
        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
        departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=unidad, orden_informe=1)
        grupo = NGrupoEscala.objects.create(nivel='IV')
        ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=grupo, salario_basico=4000)
        cargo = CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=departamento, cant_aprobada=5, orden_informe=1)
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)

        asp_negra = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Ana', papellido='Perez', sapellido='Gomez',
            doc_identidad='00000000001', estado='ACTIVO', sexo='F', raza='NE',
            provincia=provincia, municipio=municipio)
        cls.contrato_negra = CAlta.objects.create(
            aspirante=asp_negra, no_expediente='00001', tipo=tipo_contrato, cargo=cargo)

        asp_blanca = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Beto', papellido='Lopez', sapellido='Diaz',
            doc_identidad='00000000002', estado='ACTIVO', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.contrato_blanca = CAlta.objects.create(
            aspirante=asp_blanca, no_expediente='00002', tipo=tipo_contrato, cargo=cargo)

        cls.admin = CustomUser.objects.create_user(
            username='admin_list_contrato', password='x', es_admin=True)

    def test_carga_inicial_respeta_filtro_de_querystring(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('list_contrato'), {'raza': 'NE'})
        pks = {c.pk for c in respuesta.context['object_list']}
        self.assertEqual(pks, {self.contrato_negra.pk})

    def test_carga_inicial_sin_filtro_muestra_todo(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('list_contrato'))
        pks = {c.pk for c in respuesta.context['object_list']}
        self.assertEqual(pks, {self.contrato_negra.pk, self.contrato_blanca.pk})


class ExportarMovimientoDesdeHistoricoTests(TestCase):
    """Regresión del bug reportado en producción: desde el modal «Histórico del
    Trabajador» (`templates/pages/contrato/partials/modal_historico_include.html`),
    exportar el movimiento de un trabajador A a veces descargaba el documento de
    OTRO trabajador (B).

    Causa raíz: el botón llamaba a la URL genérica `imprimir_modelo_movimiento`
    (`ModeloMovimientoDocxView` sin `origen`), que resuelve el pk probando
    PRIMERO como `CAlta` y solo si falla como `TMovimiento` (ver el propio
    comentario de la vista en `contratos/views.py`, línea ~1386). Como las
    secuencias de `CAlta.pk` y `TMovimiento.pk` son independientes y ambas
    arrancan en 1, un `TMovimiento.pk` que coincidiera con un `CAlta.pk` de
    otro trabajador hacía que se exportara el contrato/movimiento equivocado.

    La ruta correcta — ya usada en todos los demás puntos de exportación del
    proyecto — es `imprimir_movimiento` (con `origen='movimiento'` fijo),
    que nunca prueba `CAlta`. El fix cambia el JS del modal para usarla."""

    @classmethod
    def setUpTestData(cls):
        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
        departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=unidad, orden_informe=1)
        grupo = NGrupoEscala.objects.create(nivel='IV')
        ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=grupo, salario_basico=4000)
        cargo = CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=departamento, cant_aprobada=5, orden_informe=1)
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)

        cls.trabajador_a = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Ana', papellido='Perez', sapellido='Gomez',
            doc_identidad='00000000011', estado='ACTIVO', sexo='F', raza='NE',
            provincia=provincia, municipio=municipio)
        cls.trabajador_b = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Beto', papellido='Lopez', sapellido='Diaz',
            doc_identidad='00000000012', estado='ACTIVO', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)

        # Choque de pk deliberado: un TMovimiento de A con el MISMO pk que un
        # CAlta de B. En producción esto ocurre solo por coincidencia (dos
        # secuencias independientes); aquí se fija a mano para reproducirlo
        # siempre, sin depender del azar de autoincremento.
        cls.pk_colision = 5000

        cls.movimiento_a = TMovimiento.objects.create(
            pk=cls.pk_colision, aspirante=cls.trabajador_a, no_expediente='00011',
            fecha_efectiva=date.today(), cargo_anterior='Técnico A',
            cargo_nuevo='Técnico B', salario_anterior=1000, salario_nuevo=1200,
            tipo_movimiento='Movimiento Salario')

        cls.contrato_b = CAlta.objects.create(
            pk=cls.pk_colision, aspirante=cls.trabajador_b, no_expediente='00012',
            tipo=tipo_contrato, cargo=cargo, fecha_alta=date.today())
        cls.movimiento_alta_b = TMovimiento.objects.create(
            aspirante=cls.trabajador_b, contrato=cls.contrato_b, no_expediente='00012',
            fecha_efectiva=date.today(), cargo_anterior='---',
            cargo_nuevo='Especialista B', salario_anterior=0, salario_nuevo=4000,
            tipo_movimiento='Alta Inicial')

        cls.admin = CustomUser.objects.create_user(
            username='admin_export_historico', password='x', es_admin=True)

    def test_ruta_segura_exporta_el_movimiento_correcto_pese_al_choque_de_pk(self):
        """Es la ruta que ahora usa el botón «Exportar Movimiento» del Histórico:
        debe devolver SIEMPRE el documento del propio TMovimiento, nunca el de un
        CAlta ajeno con el mismo pk."""
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('imprimir_movimiento', kwargs={'pk': self.movimiento_a.pk}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('_00011.docx', respuesta['Content-Disposition'])
        self.assertIn('MOV_Ana_Perez_Gomez', respuesta['Content-Disposition'])

    def test_ruta_generica_es_la_que_confundia_los_trabajadores(self):
        """Documenta el bug tal cual ocurría en producción: por la ruta vieja
        (todavía viva para otros usos y por compatibilidad), el mismo pk de
        TMovimiento que arriba dio el documento correcto aquí devuelve el
        documento del contrato/trabajador B. Es la prueba de que el problema
        era la URL usada por el modal, no un fallo genérico de exportación."""
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('imprimir_modelo_movimiento', kwargs={'pk': self.movimiento_a.pk}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('_00012.docx', respuesta['Content-Disposition'])

    def test_el_boton_del_historico_ya_no_referencia_la_ruta_ambigua(self):
        """Guarda contra reintroducir la URL hardcodeada `.../reporte/modelo_movimiento/`
        en el JS del modal de Histórico."""
        import pathlib
        plantilla = (pathlib.Path(__file__).resolve().parent.parent
                     / 'templates' / 'pages' / 'contrato' / 'partials'
                     / 'modal_historico_include.html')
        contenido = plantilla.read_text(encoding='utf-8')
        self.assertNotIn('reporte/modelo_movimiento', contenido)
        self.assertIn("url 'imprimir_movimiento'", contenido)

    def test_historico_de_a_no_expone_ids_de_movimientos_de_b(self):
        """El histórico de A debe listar únicamente ids de movimientos que
        pertenecen a A — es la garantía de que, aunque el botón exportara con
        el id equivocado, el id que se le ofrece al usuario para seleccionar
        nunca es el de otro trabajador."""
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('historico_trabajador', kwargs={'aspirante_id': self.trabajador_a.pk}))
        ids = {item['id'] for item in respuesta.json()['data'] if item['id']}
        self.assertIn(self.movimiento_a.pk, ids)
        self.assertNotIn(self.movimiento_alta_b.pk, ids)


def _crear_departamento_con_cargo():
    """Helper compartido por las pruebas de la cascada de baja / auditoría: una UO
    con un Departamento y un cargo de plantilla, listos para asignar a un CAlta."""
    tipo_unidad = NTipoUnidadOrganizativa.objects.create(
        descripcion='UEB', es_principal=False, es_subunidad=False)
    unidad = UnidadOrganizativa.objects.create(
        descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
    departamento = Departamento.objects.create(
        descripcion='Contabilidad', unidad_organizativa=unidad, orden_informe=1)
    grupo = NGrupoEscala.objects.create(nivel='IV')
    ncargo = NCargo.objects.create(
        descripcion='Especialista B', cat_ocupacional='TEC',
        grupo_escala=grupo, salario_basico=4000)
    return CargoPlantilla.objects.create(
        ncargo=ncargo, departamento=departamento, cant_aprobada=5, orden_informe=1)


class CascadaAlVaciarHistoricoTests(TestCase):
    """`contratos.models._al_eliminar_movimiento` (conectada a `post_delete` de
    TMovimiento). Caso real reportado en producción: se borró desde el Admin de
    Django TODO el histórico de movimientos de un trabajador y quedó en un estado
    inconsistente (seguía "activo" pero sin ningún rastro documental).

    Comportamiento acordado: si borrar un movimiento deja al trabajador sin NINGÚN
    TMovimiento (de cualquier expediente), Orbith cierra su ciclo — la `CAlta`
    vigente si la tenía, o el estado del `Aspirante` directamente si no — y crea un
    `CBaja` sin `cargo`, para que aparezca en el listado de Bajas
    (`bolsa.BajaListView`, que filtra por `estado='BAJA'`) y para que la regla
    MOV-007 de Subsanación pueda alertar sobre la pérdida de histórico."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo = _crear_departamento_con_cargo()
        cls.provincia, cls.municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)

    def _crear_aspirante(self, doc, estado='ACTIVO'):
        return Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad=doc, estado=estado, sexo='F', raza='BL',
            provincia=self.provincia, municipio=self.municipio)

    def test_borrar_el_ultimo_movimiento_con_calta_vigente_cierra_el_contrato(self):
        aspirante = self._crear_aspirante('90010112340')
        contrato = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00040', tipo=self.tipo_contrato,
            cargo=self.cargo, fecha_alta=date.today())
        movimiento = TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato, no_expediente='00040',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

        movimiento.delete()

        aspirante.refresh_from_db()
        self.assertEqual(aspirante.estado, 'BAJA')
        self.assertFalse(CAlta.objects.filter(pk=contrato.pk).exists())
        baja = CBaja.objects.get(aspirante=aspirante, no_expediente='00040')
        self.assertIsNone(baja.cargo_id)

    def test_borrar_movimientos_huerfanos_sin_calta_marca_la_baja_directamente(self):
        """El caso real: el trabajador ya no tenía CAlta (solo movimientos sueltos
        de una baja anterior). Al borrarle el último, pasa a Bajas igual."""
        aspirante = self._crear_aspirante('90010112341')
        movimiento = TMovimiento.objects.create(
            aspirante=aspirante, contrato=None, no_expediente='00041',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

        movimiento.delete()

        aspirante.refresh_from_db()
        self.assertEqual(aspirante.estado, 'BAJA')
        baja = CBaja.objects.get(aspirante=aspirante, no_expediente='00041')
        self.assertIsNone(baja.cargo_id)

    def test_borrar_un_movimiento_sin_vaciar_el_historico_no_toca_nada(self):
        aspirante = self._crear_aspirante('90010112342')
        contrato = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00042', tipo=self.tipo_contrato,
            cargo=self.cargo, fecha_alta=date.today())
        mov_1 = TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato, no_expediente='00042',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')
        TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato, no_expediente='00042',
            fecha_efectiva=date.today(), cargo_anterior='Especialista B',
            cargo_nuevo='Especialista A', salario_anterior=4000, salario_nuevo=4500,
            tipo_movimiento='Movimiento Salario')

        mov_1.delete()

        aspirante.refresh_from_db()
        self.assertEqual(aspirante.estado, 'ACTIVO')
        self.assertTrue(CAlta.objects.filter(pk=contrato.pk).exists())
        self.assertFalse(CBaja.objects.filter(aspirante=aspirante).exists())

    def test_no_duplica_la_baja_si_el_aspirante_ya_estaba_de_baja(self):
        aspirante = self._crear_aspirante('90010112343', estado='BAJA')
        movimiento = TMovimiento.objects.create(
            aspirante=aspirante, contrato=None, no_expediente='00043',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

        movimiento.delete()  # no debe lanzar ni crear nada raro

        self.assertFalse(CBaja.objects.filter(aspirante=aspirante).exists())


class RecontratacionTrasVaciarHistoricoTests(TestCase):
    """Pregunta del usuario: si un trabajador que perdió TODO su histórico
    (`CascadaAlVaciarHistoricoTests`) se vuelve a contratar, el nuevo ciclo debe
    detectarse como 'Alta Inicial', no 'Recontratación' — no queda ningún rastro
    documental del ciclo anterior con el que "reconectar". Por eso el `CBaja` que
    genera la cascada se crea con `fecha_alta=None` (ver
    `contratos.models._al_eliminar_movimiento`): `historico_trabajador()` solo
    genera un hito de alta para una `CBaja` si tiene `fecha_alta`."""

    def test_la_nueva_contratacion_se_detecta_como_alta_inicial(self):
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112390', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        contrato_viejo = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00090', tipo=tipo_contrato,
            cargo=cargo, fecha_alta=date(2020, 1, 1))
        movimiento = TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato_viejo, no_expediente='00090',
            fecha_efectiva=date(2020, 1, 1), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

        movimiento.delete()  # dispara la cascada: cierra el contrato, crea el CBaja

        aspirante.refresh_from_db()
        self.assertEqual(aspirante.estado, 'BAJA')

        # Se le vuelve a contratar (simulando lo que hace `finalizar_contrato_wizard`,
        # que SIEMPRE crea el TMovimiento con tipo_movimiento="Alta Inicial" — ver
        # `contratos/views.py`, creación del movimiento de alta del wizard).
        aspirante.estado = 'ACTIVO'
        aspirante.save(update_fields=['estado'])
        contrato_nuevo = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00091', tipo=tipo_contrato,
            cargo=cargo, fecha_alta=date(2024, 6, 1))
        nuevo_movimiento = TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato_nuevo, no_expediente='00091',
            fecha_efectiva=date(2024, 6, 1), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

        admin_user = CustomUser.objects.create_user(
            username='admin_recontratacion', password='x', es_admin=True)
        self.client.force_login(admin_user)
        respuesta = self.client.get(
            reverse('historico_trabajador', kwargs={'aspirante_id': aspirante.pk}))
        datos = respuesta.json()['data']

        eventos_del_nuevo = [h['evento'] for h in datos if h.get('id') == nuevo_movimiento.pk]
        self.assertEqual(eventos_del_nuevo, ['Alta Inicial'])
        self.assertNotIn('Recontratación', [h['evento'] for h in datos])


class AvisoOrigenEdicionTests(TestCase):
    """`templates/base/partials/aviso_origen_edicion.html` y
    `core.mixins.AdvertenciasDelRegistroMixin.mensaje_de_guardado_exitoso`: el aviso
    "está corrigiendo un registro desde una advertencia" debe depender de `origen`
    (que solo pone `subsanacion/enlaces.py::construir_enlace()`), no de `next` (que
    también usan enlaces de navegación normales — p. ej. "Editar Personal" desde la
    lista de Contratos manda `next` para volver al listado, sin `origen`)."""

    @classmethod
    def setUpTestData(cls):
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112380', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.contrato = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00080', tipo=tipo_contrato,
            cargo=cargo, fecha_alta=date.today())
        cls.admin = CustomUser.objects.create_user(
            username='admin_aviso_origen', password='x', es_admin=True)

    def test_next_sin_origen_no_muestra_el_aviso(self):
        """Caso real reportado: 'Editar Personal' desde la lista de Contratos manda
        `next` (para volver al listado) pero nunca `origen`."""
        self.client.force_login(self.admin)
        url = f"{reverse('updt_contrato', args=[self.contrato.pk])}?next={reverse('list_contrato')}"
        respuesta = self.client.get(url)
        self.assertNotContains(respuesta, 'Está corrigiendo un registro desde')

    def test_next_con_origen_muestra_el_aviso(self):
        self.client.force_login(self.admin)
        url = (f"{reverse('updt_contrato', args=[self.contrato.pk])}"
               f"?next={reverse('list_contrato')}&origen=Advertencias")
        respuesta = self.client.get(url)
        self.assertContains(respuesta, 'Está corrigiendo un registro desde')


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar TMovimiento, CAlta y CBaja desde el Admin de Django
    ahora deja rastro en `auditoria.EventoAuditoria` — antes no dejaba ninguno,
    porque solo el flujo de Solicitudes escribía ahí."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112350', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.admin = CustomUser.objects.create_user(
            username='admin_auditoria', password='x', es_admin=True)

    def test_eliminar_un_contrato_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        contrato = CAlta.objects.create(
            aspirante=self.aspirante, no_expediente='00050', tipo=self.tipo_contrato,
            cargo=self.cargo, fecha_alta=date.today())
        self.client.force_login(self.admin)

        url = reverse('admin:contratos_calta_delete', args=[contrato.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(CAlta.objects.filter(pk=contrato.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(contrato.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)

    def test_eliminar_un_movimiento_en_el_admin_audita_una_sola_vez(self):
        """Guarda contra duplicar el evento: `TMovimientoAdmin` NO debe auditar el
        borrado por su cuenta (ver `AuditoriaSoloEdicionAdminMixin`), porque ya lo
        hace la señal `post_delete`, que cubre también los otros caminos de borrado
        (selección múltiple, acción agrupada)."""
        from auditoria.models import EventoAuditoria

        movimiento = TMovimiento.objects.create(
            aspirante=self.aspirante, contrato=None, no_expediente='00051',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Movimiento Salario')
        self.client.force_login(self.admin)

        url = reverse('admin:contratos_tmovimiento_delete', args=[movimiento.pk])
        self.client.post(url, {'post': 'yes'})

        eventos = EventoAuditoria.objects.filter(object_id=str(movimiento.pk), accion='DEL')
        self.assertEqual(eventos.count(), 1)

    def test_editar_un_movimiento_desde_el_admin_queda_auditado(self):
        """Prueba el hook `save_model` del mixin directamente (en vez de simular el
        POST completo del formulario), igual que otras pruebas del proyecto usan
        `RequestFactory` para aislar la lógica que importa sin depender de que el
        formulario de Admin esté completo."""
        from auditoria.models import EventoAuditoria
        from contratos.admin import TMovimientoAdmin
        from django.contrib.admin.sites import AdminSite

        movimiento = TMovimiento.objects.create(
            aspirante=self.aspirante, contrato=None, no_expediente='00052',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Movimiento Salario')

        admin_instance = TMovimientoAdmin(TMovimiento, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        movimiento.observaciones = 'Corregido a mano desde el Admin'
        admin_instance.save_model(request, movimiento, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(movimiento.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)


class ReglaBajaSinMovimientosNiCargoTests(TestCase):
    """MOV-007 (`subsanacion/reglas/nomina.py`): la alerta que hace visible, en
    Subsanación, a los trabajadores que quedaron en Bajas sin cargo ni movimientos
    tras la cascada probada en `CascadaAlVaciarHistoricoTests`."""

    def _ejecutar(self):
        from subsanacion.contexto import ContextoAnalisis
        from subsanacion.models import EjecucionAnalisis
        from subsanacion.reglas.nomina import BajaSinMovimientosNiCargo

        ejecucion = EjecucionAnalisis.objects.create(estado=EjecucionAnalisis.COMPLETA)
        return list(BajaSinMovimientosNiCargo().ejecutar(ContextoAnalisis(ejecucion)))

    def test_detecta_baja_sin_cargo_ni_movimientos(self):
        provincia, municipio = _crear_provincia_municipio()
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112360', estado='BAJA', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        baja = CBaja.objects.create(
            aspirante=aspirante, no_expediente='00060', cargo=None, fecha_baja=date.today())

        hallazgos = self._ejecutar()

        self.assertEqual({h.object_id for h in hallazgos}, {str(baja.pk)})

    def test_no_reporta_baja_sin_cargo_si_todavia_tiene_movimientos(self):
        """Una baja sin cargo completado a mano, pero con histórico intacto, no es
        el mismo problema — no debe confundirse con la pérdida de histórico."""
        provincia, municipio = _crear_provincia_municipio()
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab2', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112361', estado='BAJA', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        CBaja.objects.create(
            aspirante=aspirante, no_expediente='00061', cargo=None, fecha_baja=date.today())
        TMovimiento.objects.create(
            aspirante=aspirante, contrato=None, no_expediente='00061',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='---',
            salario_anterior=0, salario_nuevo=0, tipo_movimiento='Baja')

        self.assertEqual(self._ejecutar(), [])


class BorradoAgrupadoAdminTests(TestCase):
    """La acción `eliminar_historico_completo` de `TMovimientoAgrupadoAdmin`: borra
    TODOS los movimientos del grupo (no solo la fila "representante" que se ve en
    la lista), dispara la cascada de baja y audita cada movimiento eliminado."""

    def test_borra_todo_el_grupo_y_dispara_la_cascada(self):
        from django.contrib.admin.sites import AdminSite

        from auditoria.models import EventoAuditoria
        from contratos.admin import TMovimientoAgrupadoAdmin
        from contratos.models import TMovimientoAgrupado

        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112370', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        contrato = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00070', tipo=tipo_contrato,
            cargo=cargo, fecha_alta=date.today())
        TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato, no_expediente='00070',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')
        TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato, no_expediente='00070',
            fecha_efectiva=date.today(), cargo_anterior='Especialista B',
            cargo_nuevo='Especialista A', salario_anterior=4000, salario_nuevo=4500,
            tipo_movimiento='Movimiento Salario')

        admin_user = CustomUser.objects.create_user(
            username='admin_borrado_agrupado', password='x', es_admin=True)
        self.client.force_login(admin_user)

        # El pk "representante" del grupo lo decide el DISTINCT ON del propio
        # ModelAdmin (ver `get_queryset`) — se resuelve así en vez de asumir cuál de
        # los dos TMovimiento creados arriba ganó el desempate.
        admin_instance = TMovimientoAgrupadoAdmin(TMovimientoAgrupado, AdminSite())
        representante = admin_instance.get_queryset(
            RequestFactory().get('/')).get(aspirante_id=aspirante.pk)

        url = reverse('admin:contratos_tmovimientoagrupado_changelist')
        self.client.post(url, {
            'action': 'eliminar_historico_completo',
            '_selected_action': [str(representante.pk)],
        })

        self.assertFalse(TMovimiento.objects.filter(aspirante_id=aspirante.pk).exists())
        aspirante.refresh_from_db()
        self.assertEqual(aspirante.estado, 'BAJA')
        self.assertTrue(CBaja.objects.filter(
            aspirante=aspirante, no_expediente='00070', cargo__isnull=True).exists())
        # Los dos movimientos eliminados, más el CAlta que la cascada cerró.
        self.assertEqual(
            EventoAuditoria.objects.filter(modulo='contratos', accion='DEL').count(), 3)

    def test_no_se_puede_borrar_una_sola_fila_representante(self):
        """El borrado individual de fila (`.../<id>/delete/`) sigue bloqueado: solo
        borraría el representante y dejaría el resto del grupo huérfano."""
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112371', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        contrato = CAlta.objects.create(
            aspirante=aspirante, no_expediente='00071', tipo=tipo_contrato,
            cargo=cargo, fecha_alta=date.today())
        movimiento = TMovimiento.objects.create(
            aspirante=aspirante, contrato=contrato, no_expediente='00071',
            fecha_efectiva=date.today(), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

        admin_user = CustomUser.objects.create_user(
            username='admin_sin_borrado_fila', password='x', es_admin=True)
        self.client.force_login(admin_user)

        url = reverse('admin:contratos_tmovimientoagrupado_delete', args=[movimiento.pk])
        respuesta = self.client.get(url)

        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(TMovimiento.objects.filter(pk=movimiento.pk).exists())


class FechaAltaEntidadTests(TestCase):
    """Casos A-F del requisito de F. Alta Entidad: obligatoria y nunca posterior
    a F. de Contratación en el formulario normal, pero libre en el Admin."""

    @classmethod
    def setUpTestData(cls):
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=False, requiere_motivo=False)
        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Fae',
            doc_identidad='90010112399', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)

    def _datos_minimos(self, fecha_alta, fecha_alta_entidad):
        """Solo los campos de fecha que ejercitan CAltaForm.clean(); el resto
        del formulario puede quedar inválido sin afectar el error que se prueba,
        porque Django siempre puebla `cleaned_data` de los campos que sí
        validan individualmente antes de llamar a `clean()`."""
        datos = {'tipo': str(self.tipo_contrato.pk)}
        if fecha_alta is not None:
            datos['fecha_alta'] = fecha_alta.isoformat()
        if fecha_alta_entidad is not None:
            datos['fecha_alta_entidad'] = fecha_alta_entidad.isoformat()
        return datos

    def test_caso_a_fecha_igual_es_valida(self):
        hoy = date.today()
        form = CAltaForm(data=self._datos_minimos(hoy, hoy))
        form.is_valid()
        self.assertNotIn('fecha_alta_entidad', form.errors)

    def test_caso_a_fecha_anterior_es_valida(self):
        hoy = date.today()
        form = CAltaForm(data=self._datos_minimos(hoy, date(2020, 3, 15)))
        form.is_valid()
        self.assertNotIn('fecha_alta_entidad', form.errors)

    def test_caso_b_fecha_posterior_es_invalida(self):
        hoy = date.today()
        posterior = date.fromordinal(hoy.toordinal() + 1)
        form = CAltaForm(data=self._datos_minimos(hoy, posterior))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_alta_entidad', form.errors)

    def test_caso_c_fecha_vacia_es_invalida_por_requerida(self):
        form = CAltaForm(data=self._datos_minimos(date.today(), None))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_alta_entidad', form.errors)

    def test_caso_d_admin_permite_fecha_posterior(self):
        """El ModelForm autogenerado del Admin (no CAltaForm) no exige el campo
        ni valida la relación con fecha_alta."""
        from django.contrib.admin.sites import AdminSite

        from contratos.admin import CAltaAdmin

        admin_instance = CAltaAdmin(CAlta, AdminSite())
        request = RequestFactory().get('/admin/contratos/calta/add/')
        FormClass = admin_instance.get_form(request)

        self.assertIn('fecha_alta_entidad', FormClass.base_fields)
        self.assertIn(
            'Excepción de Admin',
            FormClass.base_fields['fecha_alta_entidad'].help_text)

        hoy = date.today()
        posterior = date.fromordinal(hoy.toordinal() + 1)
        form = FormClass(data={
            'tipo': str(self.tipo_contrato.pk),
            'aspirante': str(self.aspirante.pk),
            'fecha_alta': hoy.isoformat(),
            'fecha_alta_entidad': posterior.isoformat(),
            'tipo_salario': 'DIN',
        })
        form.is_valid()
        self.assertNotIn('fecha_alta_entidad', form.errors)

    def test_caso_f_registro_historico_sin_fecha_alta_entidad_no_rompe_nada(self):
        """El modelo permite NULL: un contrato histórico se guarda sin el campo
        sin lanzar ninguna excepción (la obligatoriedad vive solo en el form)."""
        contrato = CAlta.objects.create(
            aspirante=self.aspirante, no_expediente='00099', tipo=self.tipo_contrato,
            fecha_alta=date.today())
        contrato.refresh_from_db()
        self.assertIsNone(contrato.fecha_alta_entidad)

    def test_movimiento_form_no_incluye_fecha_alta_entidad(self):
        """Un movimiento no es una alta nueva del trabajador en la entidad:
        igual que 'fecha_alta', 'fecha_alta_entidad' no forma parte de
        MovimientoForm.Meta.fields."""
        form = MovimientoForm()
        self.assertNotIn('fecha_alta', form.fields)
        self.assertNotIn('fecha_alta_entidad', form.fields)

    def test_caso_g_ano_anterior_a_1900_es_invalido(self):
        """El año a medio teclear («0002» al escribir 2022) es el origen de las
        fechas imposibles que llegaban a producción: el servidor lo rechaza."""
        form = CAltaForm(data=self._datos_minimos(date.today(), date(2, 5, 10)))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_alta_entidad', form.errors)
        self.assertIn('1900', str(form.errors['fecha_alta_entidad']))

    def test_caso_g_ano_1900_es_valido(self):
        """El corte es inclusivo: 1900 se acepta, 1899 no."""
        form = CAltaForm(data=self._datos_minimos(date.today(), date(1900, 1, 1)))
        form.is_valid()
        self.assertNotIn('fecha_alta_entidad', form.errors)

        form = CAltaForm(data=self._datos_minimos(date.today(), date(1899, 12, 31)))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_alta_entidad', form.errors)

    def test_caso_g_la_validacion_alcanza_a_las_demas_fechas_del_contrato(self):
        """No solo F. Alta Entidad: cualquier fecha propia del contrato."""
        datos = self._datos_minimos(date.today(), date.today())
        datos['profesional'] = 'on'
        datos['fecha_vence_lic'] = date(2, 5, 10).isoformat()
        form = CAltaForm(data=datos)
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_vence_lic', form.errors)

    def test_caso_h_una_fecha_imposible_ya_guardada_no_bloquea_la_edicion(self):
        """Un contrato histórico con la fecha ya mal registrada tiene que poder
        editarse: si se reenvía el MISMO valor no se rechaza (lo reporta CTR-017
        en Subsanación). En cuanto se cambia por otro valor imposible, sí."""
        contrato = CAlta.objects.create(
            aspirante=self.aspirante, no_expediente='00098', tipo=self.tipo_contrato,
            fecha_alta=date.today(), fecha_alta_entidad=date(2, 5, 10))

        form = CAltaForm(instance=contrato,
                         data=self._datos_minimos(date.today(), date(2, 5, 10)))
        form.is_valid()
        self.assertNotIn('fecha_alta_entidad', form.errors)

        form = CAltaForm(instance=contrato,
                         data=self._datos_minimos(date.today(), date(3, 5, 10)))
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_alta_entidad', form.errors)


class BotonesSoloLecturaContratosTests(TestCase):
    """El Observador solo conserva las acciones que NO modifican nada.

    En el listado de Contratos eso es el botón de exportar el Word (Contrato o
    Modificación al Contrato, según el caso) y la exportación a Excel. Editar
    contrato, editar datos personales, enviar a Movimiento de Nómina y dar de
    baja salen inhabilitados. El backend ya los bloquea
    (`RequiereEdicionMixin`/`requiere_edicion` en contratos/views.py); esto
    comprueba que además se VEA.
    """

    ESCRITURA = ('btn-edit-contrato', 'btn-edit-personal', 'btn-movimiento', 'btn-baja')

    @classmethod
    def setUpTestData(cls):
        cls.observador = CustomUser.objects.create_user(
            username='obs_contratos', password='ClaveSegura123', es_observador=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_contratos', password='ClaveSegura123', es_moderador=True)

    def _html(self, usuario):
        self.client.force_login(usuario)
        return self.client.get(reverse('list_contrato')).content.decode()

    def _etiqueta(self, html, id_boton):
        import re
        encontrado = re.search(r'<button[^>]*id="%s".*?>' % re.escape(id_boton), html, re.S)
        self.assertIsNotNone(encontrado, f'No se encontró el botón {id_boton}')
        return encontrado.group(0)

    def test_observador_no_puede_usar_las_acciones_de_escritura(self):
        html = self._html(self.observador)
        for boton in self.ESCRITURA:
            with self.subTest(boton=boton):
                self.assertIn('disabled', self._etiqueta(html, boton))

    def test_observador_si_conserva_la_exportacion_a_word(self):
        html = self._html(self.observador)
        self.assertIn('id="btn-pdf"', html)
        # btn-pdf es un <a>: si estuviera bloqueado llevaría la clase `disabled`.
        import re
        etiqueta = re.search(r'<a[^>]*id="btn-pdf".*?>', html, re.S).group(0)
        self.assertNotIn('disabled', etiqueta)

    def test_observador_si_conserva_la_exportacion_a_excel(self):
        self.assertIn('id="btnExportarExcel"', self._html(self.observador))

    def test_observador_no_ve_el_boton_nuevo(self):
        self.assertNotIn('id="btn-nuevo-contrato"', self._html(self.observador))

    def test_moderador_conserva_todas_las_acciones(self):
        html = self._html(self.moderador)
        for boton in self.ESCRITURA:
            with self.subTest(boton=boton):
                self.assertNotIn('disabled', self._etiqueta(html, boton))
        self.assertIn('id="btn-nuevo-contrato"', html)


class ImportesDelContratoTests(TestCase):
    """Los cuatro importes dejaron de escribirse a mano.

    Maestria y doctorado salen del grado cientifico del trabajador y del
    nomenclador; instructor y CNCI, de la entrada elegida en su desplegable. Desde
    el 23-10-2026 el contrato no guarda el numero: el nomenclador manda (la nomina
    ya emitida la protegen las copias de Pre-Nomina y cierres).
    """

    @classmethod
    def setUpTestData(cls):
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True)

        def aspirante(doc, grado):
            return Aspirante.objects.create(
                nivel_educ='SA', nombre='Trab', papellido='Prueba', sapellido='Test',
                doc_identidad=doc, estado='ACTIVO', sexo='F', raza='BL',
                grado_cientifico=grado, provincia=provincia, municipio=municipio)

        cls.sin_grado = aspirante('90010112345', None)
        cls.master = aspirante('90010112346', 'MC')
        cls.doctor = aspirante('90010112347', 'DC')

        cls.instructor = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.INSTRUCTOR, descripcion='Instructor Principal',
            importe=Decimal('150.00'))
        cls.cnci = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.CNCI, descripcion='CNCI Nivel I',
            importe=Decimal('220.00'))

    # ---- Maestria y doctorado: de solo lectura y autorrellenados ----

    def test_sin_grado_cientifico_no_aplica_ninguno(self):
        f = CAltaForm(aspirante=self.sin_grado)
        self.assertEqual(f.texto_maestria, 'No aplica')
        self.assertEqual(f.texto_doctorado, 'No aplica')
        self.assertEqual(f.importes_del_grado['maestria'], Decimal('0.00'))

    def test_el_master_recibe_el_importe_del_nomenclador(self):
        NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('500.00'))

        f = CAltaForm(aspirante=self.master)

        self.assertEqual(f.texto_maestria, '500.00')
        self.assertEqual(f.importes_del_grado['maestria'], Decimal('500.00'))
        # Nunca los dos a la vez: lo garantiza el modelo del aspirante, donde el
        # grado cientifico es UN campo con opciones y no dos casillas.
        self.assertEqual(f.texto_doctorado, 'No aplica')
        self.assertEqual(f.importes_del_grado['doctorado'], Decimal('0.00'))

    def test_el_doctor_recibe_el_importe_del_nomenclador(self):
        NImporteGradoCientifico.objects.create(grado='DC', importe=Decimal('900.50'))

        f = CAltaForm(aspirante=self.doctor)

        self.assertEqual(f.texto_doctorado, '900.50')
        self.assertEqual(f.importes_del_grado['doctorado'], Decimal('900.50'))
        self.assertEqual(f.texto_maestria, 'No aplica')

    def test_con_el_nomenclador_vacio_avisa_y_guarda_cero(self):
        """El caso decidido: se avisa en el campo, se guarda 0, y la regla CFG-003
        de Subsanacion es la que reclama el nomenclador al Administrador."""
        f = CAltaForm(aspirante=self.master)

        self.assertEqual(f.texto_maestria, 'Nomenc. Vac\u00edo')
        self.assertEqual(f.importes_del_grado['maestria'], Decimal('0.00'))

    def test_los_importes_no_son_campos_del_formulario(self):
        """Desde el 23-10-2026 el contrato no guarda los importes: lo que se ve es
        una caja de solo lectura (maestria y doctorado) o un desplegable."""
        f = CAltaForm(aspirante=self.sin_grado)
        for campo in ('maestria', 'doctorado', 'instructor', 'cnci'):
            self.assertNotIn(campo, f.fields)

    # ---- Instructor y CNCI: desplegables del nomenclador ----

    def test_cada_desplegable_solo_ofrece_su_tipo(self):
        f = CAltaForm(aspirante=self.sin_grado)
        self.assertEqual(list(f.fields['instructor_nomenclador'].queryset),
                         [self.instructor])
        self.assertEqual(list(f.fields['cnci_nomenclador'].queryset), [self.cnci])

    # ---- El nomenclador manda (23-10-2026) ----

    def _contrato(self, aspirante, **extra):
        return CAlta.objects.create(
            aspirante=aspirante, no_expediente=aspirante.doc_identidad[-5:],
            tipo=self.tipo_contrato, fecha_alta=date.today(), **extra)

    def test_los_importes_se_leen_siempre_del_nomenclador(self):
        grado = NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('500.00'))
        contrato = self._contrato(self.master, instructor_nomenclador=self.instructor,
                                  cnci_nomenclador=self.cnci)
        self.assertEqual((contrato.importe_maestria, contrato.importe_doctorado,
                          contrato.importe_instructor, contrato.importe_cnci),
                         (Decimal('500.00'), Decimal('0.00'), Decimal('150.00'), Decimal('220.00')))

        # Cambiar el nomenclador cambia lo que cobra desde hoy, sin tocar el contrato.
        from contratos.models import invalidar_importes_de_grado
        grado.importe = Decimal('440.00')
        grado.save()
        self.cnci.importe = Decimal('329.00')
        self.cnci.save()
        invalidar_importes_de_grado()
        contrato = CAlta.objects.get(pk=contrato.pk)
        self.assertEqual(contrato.importe_maestria, Decimal('440.00'))
        self.assertEqual(contrato.importe_cnci, Decimal('329.00'))

    def test_sin_elegir_nada_los_pagos_quedan_en_cero(self):
        contrato = self._contrato(self.sin_grado)
        self.assertEqual((contrato.importe_instructor, contrato.importe_cnci,
                          contrato.importe_maestria), (Decimal('0.00'),) * 3)

    def test_no_se_puede_borrar_una_entrada_que_usan_contratos(self):
        from django.db.models import ProtectedError
        self._contrato(self.sin_grado, cnci_nomenclador=self.cnci)
        with self.assertRaises(ProtectedError):
            self.cnci.delete()

    def test_al_editar_el_aspirante_sale_del_propio_contrato(self):
        """En edicion no hace falta pasarlo: sale de la instancia."""
        NImporteGradoCientifico.objects.create(grado='DC', importe=Decimal('900.00'))
        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
        departamento = Departamento.objects.create(
            descripcion='Direccion', unidad_organizativa=unidad, orden_informe=1)
        grupo = NGrupoEscala.objects.create(nivel='IV')
        ncargo = NCargo.objects.create(
            descripcion='Especialista', cat_ocupacional='TEC',
            grupo_escala=grupo, salario_basico=4000)
        cargo = CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=departamento, cant_aprobada=5, orden_informe=1)
        contrato = CAlta.objects.create(
            aspirante=self.doctor, no_expediente='00777', tipo=self.tipo_contrato,
            cargo=cargo, fecha_alta=date.today())

        f = CAltaForm(instance=contrato)

        self.assertEqual(f.texto_doctorado, '900.00')

    def test_admite_decimales_y_cifras_de_tres_digitos(self):
        """Antes maestria y doctorado eran enteros (los centavos se perdian) e
        instructor era Decimal(4, 2), con tope en 99,99."""
        NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('1234.56'))
        instructor = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.INSTRUCTOR, descripcion='Instructor Jefe',
            importe=Decimal('345.67'))
        contrato = self._contrato(self.master, instructor_nomenclador=instructor)
        self.assertEqual(contrato.importe_maestria, Decimal('1234.56'))
        self.assertEqual(contrato.importe_instructor, Decimal('345.67'))


class FiltrosEstructuraContratosTests(TestCase):
    """Los tres filtros del listado de contratos por estructura: Unidad
    Organizativa, Departamento y Cargo.

    Lo que de verdad hay que proteger aquí es la EXPANSIÓN de la unidad: una
    Unidad Principal no tiene cargos propios —todo cuelga de sus subunidades—,
    así que filtrar por una principal sin expandir devolvería el listado vacío,
    que es justo el fallo que se veía en el Dashboard y en los informes antes de
    unificar el criterio en `strorganizativa/jerarquia.py`.
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
        # Fuera de la rama de la principal: sirve para comprobar que expandir no
        # se lleva por delante a media empresa.
        cls.suelta = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=tipo_ueb, grupo_nomina=2, orden_informe=4)

        cls.dep_taller = Departamento.objects.create(
            descripcion='Mantenimiento', unidad_organizativa=cls.taller, orden_informe=1)
        cls.dep_almacen = Departamento.objects.create(
            descripcion='Insumos', unidad_organizativa=cls.almacen, orden_informe=1)
        cls.dep_suelta = Departamento.objects.create(
            descripcion='Ventas', unidad_organizativa=cls.suelta, orden_informe=1)

        grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo_especialista = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=grupo, salario_basico=4000)
        cls.ncargo_operario = NCargo.objects.create(
            descripcion='Operario', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=2000)

        # El MISMO nomenclador de cargo en dos departamentos distintos: es lo que
        # obliga a que el filtro vaya por `ncargo` y no por la fila de plantilla.
        cls.plantilla_esp_taller = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_especialista, departamento=cls.dep_taller,
            cant_aprobada=3, orden_informe=1)
        cls.plantilla_esp_suelta = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_especialista, departamento=cls.dep_suelta,
            cant_aprobada=3, orden_informe=1)
        cls.plantilla_operario = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_operario, departamento=cls.dep_almacen,
            cant_aprobada=2, orden_informe=1)

        provincia, municipio = _crear_provincia_municipio()
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Indeterminado', ocupa_plaza=True, requiere_motivo=False)

        def _contrato(seq, plantilla):
            aspirante = Aspirante.objects.create(
                nivel_educ='SA', nombre='Trab%d' % seq, papellido='Prueba',
                sapellido='Test', doc_identidad='%011d' % seq, estado='ACTIVO',
                sexo='F', raza='BL', provincia=provincia, municipio=municipio)
            return CAlta.objects.create(
                aspirante=aspirante, no_expediente='%05d' % seq,
                tipo=cls.tipo_contrato, cargo=plantilla)

        cls.contrato_taller = _contrato(1, cls.plantilla_esp_taller)
        cls.contrato_almacen = _contrato(2, cls.plantilla_operario)
        cls.contrato_suelta = _contrato(3, cls.plantilla_esp_suelta)

    def _filtrar(self, params):
        request = RequestFactory().get('/contrato/', params)
        return set(aplicar_filtros(request, CAlta.objects.all()).values_list('pk', flat=True))

    def test_unidad_principal_arrastra_sus_subunidades(self):
        """Elegir la principal trae lo de sus hijas, que es donde están los
        cargos; sin la expansión el resultado sería vacío."""
        resultado = self._filtrar({'unidad': [self.principal.pk]})
        self.assertEqual(
            resultado, {self.contrato_taller.pk, self.contrato_almacen.pk})

    def test_subunidad_sola_no_arrastra_a_sus_hermanas(self):
        resultado = self._filtrar({'unidad': [self.taller.pk]})
        self.assertEqual(resultado, {self.contrato_taller.pk})

    def test_varias_unidades_suman(self):
        resultado = self._filtrar({'unidad': [self.taller.pk, self.suelta.pk]})
        self.assertEqual(
            resultado, {self.contrato_taller.pk, self.contrato_suelta.pk})

    def test_unidad_vacia_se_ignora(self):
        """El selector envía el parámetro aunque no haya nada marcado; eso no
        puede vaciar el listado."""
        resultado = self._filtrar({'unidad': ['']})
        self.assertEqual(len(resultado), 3)

    def test_departamento_filtra_solo_el_suyo(self):
        resultado = self._filtrar({'departamento': [self.dep_almacen.pk]})
        self.assertEqual(resultado, {self.contrato_almacen.pk})

    def test_cargo_filtra_por_nomenclador_en_todos_los_departamentos(self):
        resultado = self._filtrar({'cargo': [self.ncargo_especialista.pk]})
        self.assertEqual(
            resultado, {self.contrato_taller.pk, self.contrato_suelta.pk})

    def test_los_tres_filtros_se_combinan(self):
        resultado = self._filtrar({
            'unidad': [self.principal.pk],
            'cargo': [self.ncargo_especialista.pk],
        })
        self.assertEqual(resultado, {self.contrato_taller.pk})

    def test_valores_no_numericos_no_revientan(self):
        """La querystring la escribe cualquiera; un valor basura debe ignorarse,
        no lanzar `ValueError`."""
        resultado = self._filtrar({'departamento': ['x'], 'cargo': ['y'], 'unidad': ['z']})
        self.assertEqual(len(resultado), 3)


class ContextoFiltrosEstructuraTests(TestCase):
    """El contexto que alimenta a los tres selectores del listado."""

    @classmethod
    def setUpTestData(cls):
        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección', es_principal=True, es_subunidad=False)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True, tipo_padre=tipo_principal)

        cls.principal = UnidadOrganizativa.objects.create(
            descripcion='Oficina Central', tipo=tipo_principal,
            grupo_nomina=1, orden_informe=1)
        cls.taller = UnidadOrganizativa.objects.create(
            descripcion='Taller', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=2)
        cls.departamento = Departamento.objects.create(
            descripcion='Mantenimiento', unidad_organizativa=cls.taller, orden_informe=1)

        cls.admin = CustomUser.objects.create_user(
            username='admin_filtros', password='clave-de-prueba-123', es_admin=True)

    def test_unidades_llegan_ordenadas_con_su_nivel(self):
        """Padre primero y subunidad detrás, con `nivel` para indentarla."""
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('list_contrato'))
        unidades = respuesta.context['unidades_filtro']
        self.assertEqual([u.pk for u in unidades], [self.principal.pk, self.taller.pk])
        self.assertEqual([u.nivel for u in unidades], [0, 1])

    def test_departamento_lleva_su_unidad_como_padre(self):
        """Es lo que permite buscar los departamentos por el nombre de su unidad
        dentro del selector."""
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('list_contrato'))
        departamentos = respuesta.context['departamentos_filtro']
        self.assertEqual([d.padre for d in departamentos], [self.taller])

    def test_moderador_solo_ve_sus_unidades_en_el_desplegable(self):
        """Ofrecer una unidad fuera de su alcance sería un filtro que siempre
        devuelve vacío."""
        moderador = CustomUser.objects.create_user(
            username='mod_filtros', password='clave-de-prueba-123', es_moderador=True)
        moderador.unidades.set([self.taller])

        self.client.force_login(moderador)
        respuesta = self.client.get(reverse('list_contrato'))
        self.assertEqual(
            [u.pk for u in respuesta.context['unidades_filtro']], [self.taller.pk])


class MensajesExpedienteTests(TestCase):
    """Cada error del Exp. Laboral tiene su propio mensaje, en español. Antes
    la vista anunciaba cualquiera de ellos como "ya está en uso por un
    contrato activo", y el error real (por ejemplo, más de 5 dígitos) salía
    en inglés."""

    def setUp(self):
        self.usuario = CustomUser.objects.create_user(
            username='admin_expediente', password='ClaveSegura123', es_admin=True)

    def _error(self, valor):
        form = CAltaForm(data={'no_expediente': valor}, user=self.usuario)
        form.is_valid()
        return form.errors['no_expediente'][0]

    def test_mas_de_cinco_digitos(self):
        self.assertEqual(self._error('123456'), 'El expediente admite como máximo 5 dígitos.')

    def test_solo_numeros(self):
        self.assertEqual(self._error('abc'), 'El expediente solo puede contener números.')

    def test_el_campo_limita_a_cinco_caracteres(self):
        self.assertIn('maxlength="5"', str(CAltaForm(user=self.usuario)['no_expediente']))


class DatosDeMisionTests(TestCase):
    """Días e Importe de la Misión: solo en `CAlta`, validados en español y
    vaciados junto con el País cuando el switch Misión está apagado."""

    @classmethod
    def setUpTestData(cls):
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=False, requiere_motivo=False)

    def _formulario(self, **datos):
        datos.setdefault('tipo', str(self.tipo_contrato.pk))
        form = CAltaForm(data=datos)
        form.is_valid()
        return form

    def test_la_mision_solo_existe_en_calta(self):
        nombres_calta = {f.name for f in CAlta._meta.get_fields()}
        nombres_cbaja = {f.name for f in CBaja._meta.get_fields()}
        for campo in ('mision', 'pais', 'mision_dias', 'mision_importe'):
            self.assertIn(campo, nombres_calta)
            self.assertNotIn(campo, nombres_cbaja)

    def test_con_mision_conserva_pais_dias_e_importe(self):
        form = self._formulario(mision='on', pais='Venezuela',
                                mision_dias='30', mision_importe='1250.50')
        self.assertNotIn('mision_dias', form.errors)
        self.assertNotIn('mision_importe', form.errors)
        self.assertEqual(form.cleaned_data['pais'], 'Venezuela')
        self.assertEqual(form.cleaned_data['mision_dias'], 30)
        self.assertEqual(form.cleaned_data['mision_importe'], Decimal('1250.50'))

    def test_sin_mision_se_vacian_pais_dias_e_importe(self):
        # Aunque el envío los traiga (p. ej. una petición manipulada).
        form = self._formulario(pais='Venezuela', mision_dias='30', mision_importe='10')
        self.assertIsNone(form.cleaned_data['pais'])
        self.assertIsNone(form.cleaned_data['mision_dias'])
        self.assertIsNone(form.cleaned_data['mision_importe'])

    def test_dias_e_importe_pueden_quedar_vacios(self):
        form = self._formulario(mision='on', pais='Bolivia')
        self.assertNotIn('mision_dias', form.errors)
        self.assertNotIn('mision_importe', form.errors)
        self.assertIsNone(form.cleaned_data['mision_dias'])

    def test_el_cero_es_un_valor_valido(self):
        form = self._formulario(mision='on', mision_dias='0', mision_importe='0')
        self.assertNotIn('mision_dias', form.errors)
        self.assertNotIn('mision_importe', form.errors)

    def test_limites_con_mensajes_en_espanol(self):
        form = self._formulario(mision='on', mision_dias='10000', mision_importe='-1')
        self.assertEqual(form.errors['mision_dias'],
                         ['Los días de misión admiten como máximo 9999.'])
        self.assertEqual(form.errors['mision_importe'],
                         ['El importe de misión no puede ser negativo.'])

        form = self._formulario(mision='on', mision_dias='-3', mision_importe='12345678')
        self.assertEqual(form.errors['mision_dias'],
                         ['Los días de misión no pueden ser negativos.'])
        self.assertIn('7 cifras enteras', form.errors['mision_importe'][0])

    def test_el_importe_admite_siete_cifras_enteras(self):
        form = self._formulario(mision='on', mision_importe='9999999.99')
        self.assertNotIn('mision_importe', form.errors)

    def test_los_widgets_nacen_deshabilitados_como_el_pais(self):
        form = CAltaForm()
        for campo in ('pais', 'mision_dias', 'mision_importe'):
            self.assertEqual(form.fields[campo].widget.attrs.get('disabled'), 'disabled')
        self.assertEqual(form.fields['mision_dias'].label, 'Días')
        self.assertEqual(form.fields['mision_importe'].label, 'Importe')

    def test_el_moderador_puede_guardarlos_directo(self):
        from solicitudes.operaciones import definicion_de
        definicion = definicion_de('contrato_upd')
        for campo in ('mision_dias', 'mision_importe'):
            self.assertIn(campo, definicion['campos_libres'])
            self.assertIn(campo, definicion['campos_condicionales'])
        # Activar la misión o cambiar el país sigue necesitando aprobación.
        self.assertNotIn('mision', definicion['campos_libres'])
        self.assertNotIn('pais', definicion['campos_libres'])

    def test_informe_inteligente_los_ofrece_solo_en_contratos_vigentes(self):
        from informe_inteligente import metadata
        campos_alta = metadata._campos_calta()
        campos_baja = metadata._campos_cbaja()
        campos_cierre = metadata._campos_historico_contrato()
        for campo in ('mision', 'pais', 'mision_dias', 'mision_importe'):
            self.assertIn(campo, campos_alta)
            self.assertIn(campo, campos_cierre)
            self.assertNotIn(campo, campos_baja)


class FechaEfectivaDeFirmaTests(TestCase):
    """Error reportado por la empresa (12-10-2026): al exportar el Contrato de
    Trabajo o su Modificación, la «Fecha Efectiva de Firma» salía con la fecha de
    alta. Debe proponer la del último movimiento de nómina del contrato (el alta
    cuenta como uno), buscado por el enlace y no por el número de expediente."""

    def setUp(self):
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=True, requiere_motivo=False)
        self.aspirante = Aspirante.objects.create(nivel_educ='SA',
            nombre='Trab', papellido='Firma', sapellido='Test',
            doc_identidad='90010112391', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        self.contrato = CAlta.objects.create(
            aspirante=self.aspirante, no_expediente='12131', tipo=tipo_contrato,
            cargo=cargo, fecha_alta=date(2026, 8, 20))

    def _movimiento(self, fecha, expediente='12131', tipo='Movimiento de Nómina'):
        return TMovimiento.objects.create(
            aspirante=self.aspirante, contrato=self.contrato, no_expediente=expediente,
            fecha_efectiva=fecha, cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento=tipo)

    def test_sin_movimientos_propone_la_fecha_de_alta(self):
        self.assertEqual(self.contrato.fecha_efectiva_vigente(), date(2026, 8, 20))

    def test_propone_la_del_ultimo_movimiento(self):
        self._movimiento(date(2026, 8, 20), tipo='Alta Inicial')
        self._movimiento(date(2026, 9, 20))
        self._movimiento(date(2026, 9, 1))
        self.assertEqual(self.contrato.fecha_efectiva_vigente(), date(2026, 9, 20))

    def test_cuenta_el_movimiento_aunque_su_expediente_este_escrito_distinto(self):
        # Caso real: el expediente se corrigió después y el movimiento conservó el viejo.
        self._movimiento(date(2026, 9, 20), expediente='1213')
        self.assertEqual(self.contrato.fecha_efectiva_vigente(), date(2026, 9, 20))

    def test_nunca_propone_una_fecha_anterior_al_alta(self):
        self._movimiento(date(2026, 7, 14), tipo='Alta Inicial')
        self.assertEqual(self.contrato.fecha_efectiva_vigente(), date(2026, 8, 20))

    def test_el_asistente_de_exportacion_la_propone(self):
        self._movimiento(date(2026, 9, 20), expediente='1213')
        admin = CustomUser.objects.create_user(username='admin_firma', password='x', es_admin=True)
        self.client.force_login(admin)
        respuesta = self.client.get(
            reverse('exportar_contrato_word', kwargs={'pk': self.contrato.pk}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['form'].initial['fecha_efectiva'], date(2026, 9, 20))

    def test_la_fecha_minima_de_la_baja_usa_el_mismo_criterio(self):
        self._movimiento(date(2026, 9, 20), expediente='1213')
        self.assertEqual(self.contrato.fecha_ultima_accion, date(2026, 9, 20))

    def test_en_la_lista_se_calcula_sin_una_consulta_por_fila(self):
        self._movimiento(date(2026, 9, 20), expediente='1213')
        contrato = CAlta.con_fecha_ultimo_movimiento(CAlta.objects.filter(pk=self.contrato.pk)).get()
        with self.assertNumQueries(0):
            self.assertEqual(contrato.fecha_ultima_accion, date(2026, 9, 20))


class FiltroFechaDeAltaTests(TestCase):
    """Filtro «Alta desde / hasta» de la lista de Contratos (lo usa la Dashboard)."""

    def test_filtra_por_rango_de_fecha_de_alta(self):
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo = NTipoContrato.objects.create(
            descripcion='Determinado', ocupa_plaza=True, requiere_motivo=False)
        for seq, alta in ((1, date(2026, 9, 1)), (2, date(2026, 9, 20)), (3, date(2026, 11, 1))):
            aspirante = Aspirante.objects.create(
                nivel_educ='SA', nombre=f'Alta{seq}', papellido='P', sapellido='T',
                doc_identidad=f'9001011250{seq}', estado='ACTIVO', sexo='F', raza='BL',
                provincia=provincia, municipio=municipio)
            CAlta.objects.create(aspirante=aspirante, no_expediente=f'0070{seq}', tipo=tipo,
                                 cargo=cargo, fecha_alta=alta)

        def expedientes(**params):
            request = RequestFactory().get('/', params)
            return sorted(aplicar_filtros(request, CAlta.objects.all())
                          .values_list('no_expediente', flat=True))
        self.assertEqual(expedientes(alta_desde='2026-09-10', alta_hasta='2026-10-12'), ['00702'])
        self.assertEqual(expedientes(alta_desde='2026-09-10'), ['00702', '00703'])
        self.assertEqual(expedientes(alta_desde='mal'), ['00701', '00702', '00703'])


class RecontratadosYAvisosTests(TestCase):
    """Recontratados (decisiones de RRHH del 12-10-2026): filtros de Contratos
    «Recontratados», «Baja anterior desde/hasta» y «Jubilados recontratados»; el
    aviso de Contratos (altas del período que ya causaron baja) y el de Bajas (bajas
    del período ya recontratadas), cuya cifra coincide con la lista a la que lleva."""

    @classmethod
    def setUpTestData(cls):
        from contratos.models import CBaja
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo = NTipoContrato.objects.create(
            descripcion='Determinado', ocupa_plaza=True, requiere_motivo=False)

        def persona(seq, estado='ACTIVO'):
            return Aspirante.objects.create(
                nivel_educ='SA', nombre=f'Pers{seq}', papellido='P', sapellido='T',
                doc_identidad=f'8001011260{seq}', estado=estado, sexo='F', raza='BL',
                provincia=provincia, municipio=municipio)

        # Volvió: baja el 20/09 y contrato nuevo el 01/10 (jubilado recontratado).
        cls.volvio = persona(1)
        CBaja.objects.create(aspirante=cls.volvio, no_expediente='00901', tipo=tipo, cargo=cargo,
                             fecha_alta=date(2025, 1, 1), fecha_baja=date(2026, 9, 20))
        CAlta.objects.create(aspirante=cls.volvio, no_expediente='00902', tipo=tipo, cargo=cargo,
                             fecha_alta=date(2026, 10, 1), jubilado_recontratado=True)
        # Nunca se fue.
        CAlta.objects.create(aspirante=persona(2), no_expediente='00903', tipo=tipo, cargo=cargo,
                             fecha_alta=date(2026, 9, 15))
        # Entró el 18/09 y se fue el 30/09: sigue de baja.
        CBaja.objects.create(aspirante=persona(3, estado='BAJA'), no_expediente='00904', tipo=tipo,
                             cargo=cargo, fecha_alta=date(2026, 9, 18), fecha_baja=date(2026, 9, 30))
        cls.admin = CustomUser.objects.create_user(username='admin_recontr', password='x', es_admin=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def expedientes(self, **params):
        respuesta = self.client.get(reverse('search_contrato'), params)
        return sorted(c.no_expediente for c in respuesta.context['object_list'])

    def test_filtros_de_recontratados_y_jubilados(self):
        self.assertEqual(self.expedientes(recontratado='si'), ['00902'])
        self.assertEqual(self.expedientes(recontratado='no'), ['00903'])
        self.assertEqual(self.expedientes(baja_anterior_desde='2026-09-01',
                                          baja_anterior_hasta='2026-09-25'), ['00902'])
        self.assertEqual(self.expedientes(baja_anterior_desde='2026-09-21'), [])
        self.assertEqual(self.expedientes(jubilado='si'), ['00902'])

    def test_marca_de_recontratado_en_la_fila(self):
        # Sin filtros, la lista se ve como siempre.
        self.assertNotContains(self.client.get(reverse('search_contrato')), 'row-recontratado')
        # Con un filtro de recontratados, de baja anterior o de fecha de alta, sí.
        for params in ({'recontratado': 'si'}, {'baja_anterior_desde': '2026-09-01'},
                       {'alta_desde': '2026-01-01'}):
            respuesta = self.client.get(reverse('search_contrato'), params)
            self.assertContains(respuesta, 'row-recontratado', count=1)
            self.assertContains(respuesta, 'title="Recontratado"', count=1)

    def test_aviso_de_altas_que_ya_causaron_baja(self):
        params = {'alta_desde': '2026-09-10', 'alta_hasta': '2026-10-12'}
        # El aviso viaja fuera de banda en las respuestas HTMX de la búsqueda.
        respuesta = self.client.get(reverse('search_contrato'), params, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.context['altas_con_baja_total'], 1)
        self.assertContains(respuesta, 'ya fue dado de baja')
        ventana = self.client.get(reverse('contratos_altas_con_baja'), params)
        self.assertEqual([b.no_expediente for b in ventana.context['bajas']], ['00904'])
        # Sin fechas de alta no hay aviso.
        self.assertEqual(self.client.get(reverse('search_contrato')).context['altas_con_baja_total'], 0)

    def test_aviso_de_bajas_recontratadas_coincide_con_contratos(self):
        respuesta = self.client.get(reverse('list_baja'),
                                    {'baja_desde': '2026-09-12', 'baja_hasta': '2026-10-12'})
        # En la tabla solo quien sigue de baja; el recontratado va en el aviso.
        self.assertEqual([a.nombre for a in respuesta.context['aspirantes']], ['Pers3'])
        self.assertEqual(respuesta.context['recontratados_total'], 1)
        destino = self.client.get(respuesta.context['recontratados_url'])
        self.assertEqual([c.no_expediente for c in destino.context['object_list']], ['00902'])


class VariosMovimientosEnElPeriodoTests(TestCase):
    """Quien causa baja y vuelve varias veces en el mismo período cuenta como UNA
    persona, con la nota «N bajas/altas en el período» (decisión de RRHH del
    13-10-2026). Lista + aviso = cifra de la Dashboard."""

    @classmethod
    def setUpTestData(cls):
        from contratos.models import CBaja
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo = NTipoContrato.objects.create(descripcion='Determinado', ocupa_plaza=False, requiere_motivo=False)
        cls.ida_y_vuelta = Aspirante.objects.create(
            nivel_educ='SA', nombre='Vuelve', papellido='P', sapellido='T', doc_identidad='80010112801',
            estado='ACTIVO', sexo='F', raza='BL', provincia=provincia, municipio=municipio)
        # En septiembre: entra el 1, se va el 5, vuelve el 8, se va el 15 y vuelve el 20.
        CBaja.objects.create(aspirante=cls.ida_y_vuelta, no_expediente='00811', tipo=tipo, cargo=cargo,
                             fecha_alta=date(2026, 9, 1), fecha_baja=date(2026, 9, 5))
        CBaja.objects.create(aspirante=cls.ida_y_vuelta, no_expediente='00811', tipo=tipo, cargo=cargo,
                             fecha_alta=date(2026, 9, 8), fecha_baja=date(2026, 9, 15))
        CAlta.objects.create(aspirante=cls.ida_y_vuelta, no_expediente='00811', tipo=tipo, cargo=cargo,
                             fecha_alta=date(2026, 9, 20))
        cls.admin = CustomUser.objects.create_user(username='admin_varias', password='x', es_admin=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_altas_una_persona_con_nota(self):
        r = self.client.get(reverse('search_contrato'),
                            {'alta_desde': '2026-09-01', 'alta_hasta': '2026-09-30'}, HTTP_HX_REQUEST='true')
        filas = list(r.context['object_list'])
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0].altas_periodo, 3)
        # Ya sale en la lista: el aviso no la repite.
        self.assertEqual(r.context['altas_con_baja_total'], 0)
        self.assertContains(r, '3 altas en el período')

    def test_bajas_una_persona_con_nota(self):
        r = self.client.get(reverse('search_bajas'), {'baja_desde': '2026-09-01', 'baja_hasta': '2026-09-30'})
        self.assertEqual(r.context['recontratados_total'], 1)
        destino = self.client.get(r.context['recontratados_url'])
        filas = list(destino.context['object_list'])
        self.assertEqual([c.bajas_periodo for c in filas], [2])
        self.assertContains(destino, '2 bajas en el período')


class AsistenteDeContratacionErroresTests(TestCase):
    """El asistente de contratación (paso 2) enseña los errores en su pantalla en vez
    de un error interno (500), y no acepta años imposibles (13-10-2026)."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo_libre = _crear_departamento_con_cargo()
        cls.cargo_lleno = CargoPlantilla.objects.create(
            ncargo=NCargo.objects.create(descripcion='Lleno', cat_ocupacional='TEC',
                                         grupo_escala=cls.cargo_libre.ncargo.grupo_escala,
                                         salario_basico=4000),
            departamento=cls.cargo_libre.departamento, cant_aprobada=1, orden_informe=99)
        provincia, municipio = _crear_provincia_municipio()
        cls.indeterminado = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True, requiere_motivo=False)
        ocupante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Ocupa', papellido='P', sapellido='T', doc_identidad='80010112901',
            estado='ACTIVO', sexo='F', raza='BL', provincia=provincia, municipio=municipio)
        CAlta.objects.create(aspirante=ocupante, no_expediente='00901', tipo=cls.indeterminado,
                             cargo=cls.cargo_lleno, fecha_alta=date(2026, 1, 1))
        cls.cargo_lleno.refrescar_conteo_plazas()
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Nuevo', papellido='P', sapellido='T', doc_identidad='80010112902',
            estado='ASPIRANTE', sexo='M', raza='BL', provincia=provincia, municipio=municipio)
        cls.admin = CustomUser.objects.create_user(username='admin_asistente', password='x', es_admin=True)

    def _contratar(self, cargo_paso2, fecha):
        self.client.force_login(self.admin)
        xhr = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        unidad = self.cargo_libre.departamento.unidad_organizativa_id
        paso1 = self.client.post(reverse('add_contrato', args=[self.aspirante.doc_identidad]), {
            'no_expediente': '00902', 'fecha_alta_entidad': '2026-10-01', 'fecha_alta': '2026-10-01',
            'cargo': self.cargo_libre.pk, 'reg_militar': 'NIN', 'tipo_salario': 'FIJ',
            'unidad': unidad, 'departamento': self.cargo_libre.departamento_id,
            'tipo': self.indeterminado.pk}, **xhr)
        self.assertTrue(paso1.json().get('redirect_to_wizard'), paso1.content[:300])
        return self.client.post(reverse('finalizar_contrato_wizard', args=[self.aspirante.doc_identidad]), {
            'generar_movimiento': 'true', 'fecha_efectiva': fecha, 'fecha_solicitud': '2026-10-01',
            'unidad': unidad, 'departamento': cargo_paso2.departamento_id, 'cargo': cargo_paso2.pk,
            'tipo_salario': 'FIJ', 'tipo': self.indeterminado.pk, 'salarioEscala': '4000'}, **xhr)

    def test_un_error_del_formulario_se_ensena_y_no_es_un_500(self):
        respuesta = self._contratar(self.cargo_lleno, '2026-10-01')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('no tiene plazas disponibles', respuesta.json()['error_popup'])
        self.assertTrue(respuesta.json()['html_form'])
        self.assertFalse(CAlta.objects.filter(no_expediente='00902').exists())

    def test_no_acepta_un_ano_imposible(self):
        respuesta = self._contratar(self.cargo_libre, '0026-10-01')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('1900 o posterior', respuesta.json()['error_popup'])
        self.assertFalse(CAlta.objects.filter(no_expediente='00902').exists())

    def test_con_datos_correctos_contrata(self):
        respuesta = self._contratar(self.cargo_libre, '2026-10-01')
        self.assertTrue(respuesta.json()['form_is_valid'], respuesta.content[:300])
        self.assertTrue(CAlta.objects.filter(no_expediente='00902').exists())

    def test_el_alta_inicial_guarda_el_tipo_de_contrato(self):
        # Antes el Alta Inicial nacía sin tipo de contrato ni motivo, y el siguiente
        # movimiento no encajaba con ella (regla MOV-015, 24-10-2026).
        self._contratar(self.cargo_libre, '2026-10-01')
        alta = TMovimiento.objects.get(no_expediente='00902', tipo_movimiento='Alta Inicial')
        self.assertEqual((alta.tipo_contrato_nuevo, alta.motivo_nuevo), ('Indeterminado', '---'))


class AvisosAlCausarBajaTests(TestCase):
    """Al causar baja se borran los avisos del contrato y las alertas de la ficha
    (no los Eventos), el análisis no las vuelve a crear, y un enlace a un contrato
    que ya no existe muestra una página clara en vez del 404 (13-10-2026)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.contenttypes.models import ContentType
        from notificaciones.models import Notificacion
        cls.Notificacion = Notificacion
        cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo = NTipoContrato.objects.create(descripcion='Determinado', ocupa_plaza=False, requiere_motivo=False)
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Se', papellido='Va', sapellido='T', doc_identidad='80010113101',
            estado='ACTIVO', sexo='F', raza='BL', provincia=provincia, municipio=municipio)
        cls.contrato = CAlta.objects.create(aspirante=cls.aspirante, no_expediente='01101', tipo=tipo,
                                            cargo=cargo, fecha_alta=date(2026, 1, 1))
        cls.admin = CustomUser.objects.create_user(username='admin_avisos_baja', password='x', es_admin=True)
        cls.ct_contrato = ContentType.objects.get_for_model(CAlta)
        cls.ct_ficha = ContentType.objects.get_for_model(Aspirante)

    def _aviso(self, ct, object_id, tipo, codigo):
        return self.Notificacion.objects.create(
            titulo=codigo, mensaje='', tipo=tipo, codigo_regla=codigo, content_type=ct,
            object_id=str(object_id), destinatario=self.admin)

    def test_la_baja_borra_avisos_del_contrato_y_alertas_de_la_ficha(self):
        N = self.Notificacion
        self._aviso(self.ct_contrato, self.contrato.pk, N.Tipo.ALERTA, 'CTR-X')
        self._aviso(self.ct_ficha, self.aspirante.pk, N.Tipo.ALERTA, 'ASP-X')
        evento = self._aviso(self.ct_ficha, self.aspirante.pk, N.Tipo.EVENTO, 'BAJA-X')
        pk = self.contrato.pk
        self.aspirante.estado = 'BAJA'
        self.aspirante.save(update_fields=['estado'])
        self.contrato.delete()
        self.assertFalse(N.objects.filter(content_type=self.ct_contrato, object_id=str(pk)).exists())
        quedan = N.objects.filter(content_type=self.ct_ficha)
        # Ninguna alerta; los Eventos se quedan (también el «Baja de contrato» que
        # crea la propia baja).
        self.assertFalse(quedan.filter(tipo=N.Tipo.ALERTA).exists())
        self.assertTrue(quedan.filter(pk=evento.pk).exists())

    def test_el_analisis_no_crea_alertas_para_fichas_de_baja(self):
        from types import SimpleNamespace
        from notificaciones.escaneo import notificar_resultados
        from subsanacion.reglas import obtener_regla
        self.aspirante.estado = 'BAJA'
        self.aspirante.save(update_fields=['estado'])
        regla = obtener_regla('ASP-006')
        hallazgo = SimpleNamespace(object_id=str(self.aspirante.pk), clave_extra='', titulo='Sin dirección',
                                   detalle='', unidad_organizativa_id=None, campo_formulario='direccion')
        notificar_resultados([(regla, [hallazgo])], self.admin)
        self.assertFalse(self.Notificacion.objects.filter(content_type=self.ct_ficha).exists())

    def test_enlace_a_un_contrato_que_ya_no_existe(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('updt_contrato', args=[999999]), {'next': '/notificaciones/'})
        self.assertEqual(respuesta.status_code, 404)
        self.assertContains(respuesta, 'Este contrato ya no existe', status_code=404)
        self.assertContains(respuesta, 'href="/notificaciones/"', status_code=404)


class RolDelCargoTests(TestCase):
    """El rol de pago es del CARGO, no del contrato (producción, 23-10-2026): tras un
    movimiento de nómina a un cargo con otro rol, el Word del contrato salía con el
    salario del rol anterior. Cambiar el rol de un cargo o la escala salarial
    recalcula el salario guardado de sus contratos y avisa."""

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import NRol, NSalario
        cargo = _crear_departamento_con_cargo()
        cls.grupo = cargo.ncargo.grupo_escala
        cls.fundamental = NRol.objects.create(tipo='Fundamental')
        cls.decisorio = NRol.objects.create(tipo='Decisorio')
        cls.tridente = NTridente.objects.create(tipo='I')
        NSalario.objects.create(grupo_escala=cls.grupo, rol=cls.fundamental, tridente=cls.tridente, monto=4890)
        NSalario.objects.create(grupo_escala=cls.grupo, rol=cls.decisorio, tridente=cls.tridente, monto=5379)
        cargo.rol = cls.fundamental
        cargo.save()
        cls.cargo_fundamental = cargo
        cls.cargo_decisorio = CargoPlantilla.objects.create(
            ncargo=NCargo.objects.create(descripcion='Técnico de Comunicaciones', cat_ocupacional='TEC',
                                         grupo_escala=cls.grupo, salario_basico=4000),
            departamento=cargo.departamento, rol=cls.decisorio, cant_aprobada=5, orden_informe=2)
        provincia, municipio = _crear_provincia_municipio()
        aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Osiel', papellido='Torres', sapellido='Pérez',
            doc_identidad='80010113199', estado='ACTIVO', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        tipo = NTipoContrato.objects.create(descripcion='Indeterminado', ocupa_plaza=False, requiere_motivo=False)
        cls.contrato = CAlta.objects.create(
            aspirante=aspirante, no_expediente='02890', tipo=tipo, cargo=cargo,
            tridente=cls.tridente, tipo_salario='DIN', fecha_alta=date(2025, 1, 20))
        cls.admin = CustomUser.objects.create_user(username='admin_rol_cargo', password='x', es_admin=True)

    def test_tras_cambiar_de_cargo_el_word_usa_el_rol_del_cargo_nuevo(self):
        self.assertEqual(self.contrato.salario_actual, Decimal('4890.00'))
        # Lo que hace el movimiento de nómina: cambia el cargo y guarda.
        self.contrato.cargo = self.cargo_decisorio
        self.contrato.save()
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.salario_actual, Decimal('5379.00'))

        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('exportar_contrato_word', args=[self.contrato.pk]))
        self.assertEqual(respuesta.context['salario_escala'], '5379.00')
        vista = respuesta.context['view']
        ctx = vista._compilar_contexto_word(self.contrato, {}, None)
        self.assertEqual((ctx['check_decisorio'], ctx['check_fundamental']), ('X', ''))

    def test_cambiar_el_rol_del_cargo_recalcula_y_avisa(self):
        from notificaciones.models import Notificacion
        self.cargo_fundamental.rol = self.decisorio
        self.cargo_fundamental.save()
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.salario_actual, Decimal('5379.00'))
        aviso = Notificacion.objects.get(codigo_regla='EVT-ROL', destinatario=self.admin)
        self.assertEqual(aviso.titulo, 'Cambio de rol en un cargo')
        self.assertIn('cambió de rol: Fundamental a Decisorio', aviso.mensaje)
        self.assertIn('se actualizó el salario de 1 contrato asignado a dicho cargo', aviso.mensaje)

    def test_guardar_el_cargo_sin_cambiar_el_rol_no_avisa(self):
        from notificaciones.models import Notificacion
        self.cargo_fundamental.cant_aprobada = 6
        self.cargo_fundamental.save()
        self.assertFalse(Notificacion.objects.filter(codigo_regla='EVT-ROL').exists())

    def test_editar_la_escala_recalcula_y_avisa(self):
        from notificaciones.models import Notificacion
        self.client.force_login(self.admin)
        self.client.post(reverse('editar_salarios', args=[self.grupo.pk]), {
            f'salario_{self.fundamental.pk}_{self.tridente.pk}': '5000',
            f'salario_{self.decisorio.pk}_{self.tridente.pk}': '5379',
            'motivo_cambio': 'Ajuste salarial',
        })
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.salario_actual, Decimal('5000.00'))
        aviso = Notificacion.objects.get(codigo_regla='EVT-ESCALA', destinatario=self.admin)
        self.assertIn('La escala salarial del grupo IV cambió', aviso.mensaje)
        self.assertIn('1 contrato de ese grupo', aviso.mensaje)


class CronologiaDelHistoricoTests(TestCase):
    """Regla única del histórico (`contratos/cronologia.py`, decisión de RRHH del
    23-10-2026): ningún evento futuro, dos eventos del trabajador nunca el mismo día,
    recontratar como pronto el día siguiente a la baja y todo contrato con su Alta
    Inicial. Lo comprueba el SERVIDOR, no solo el JavaScript."""

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import NCausaAltaBaja
        cls.cargo = _crear_departamento_con_cargo()
        cls.otro_cargo = CargoPlantilla.objects.create(
            ncargo=NCargo.objects.create(descripcion='Especialista A', cat_ocupacional='TEC',
                                         grupo_escala=cls.cargo.ncargo.grupo_escala,
                                         salario_basico=4000),
            departamento=cls.cargo.departamento, cant_aprobada=5, orden_informe=2)
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True, requiere_motivo=False)
        cls.causa = NCausaAltaBaja.objects.create(descripcion='Renuncia')
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Vuelve', papellido='P', sapellido='T',
            doc_identidad='80010114001', estado='BAJA', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.activo = Aspirante.objects.create(
            nivel_educ='SA', nombre='Sigue', papellido='P', sapellido='T',
            doc_identidad='80010114002', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.admin = CustomUser.objects.create_user(username='admin_cronologia', password='x', es_admin=True)

    def setUp(self):
        self.hoy = timezone.localdate()
        self.ayer = self.hoy - timedelta(days=1)
        self.manana = self.hoy + timedelta(days=1)
        self.hace_10 = self.hoy - timedelta(days=10)
        self.client.force_login(self.admin)
        self.xhr = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    # --- Asistente de alta / recontratación ---------------------------------

    def _recontratar(self, fecha, generar='true'):
        unidad = self.cargo.departamento.unidad_organizativa_id
        doc = self.aspirante.doc_identidad
        paso1 = self.client.post(reverse('add_contrato', args=[doc]), {
            'no_expediente': '01401',
            'fecha_alta_entidad': (self.hace_10 - timedelta(days=30)).isoformat(),
            'fecha_alta': self.hace_10.isoformat(), 'cargo': self.cargo.pk,
            'reg_militar': 'NIN', 'tipo_salario': 'FIJ', 'unidad': unidad,
            'departamento': self.cargo.departamento_id, 'tipo': self.tipo.pk}, **self.xhr)
        self.assertTrue(paso1.json().get('redirect_to_wizard'), paso1.content[:300])
        return self.client.post(reverse('finalizar_contrato_wizard', args=[doc]), {
            'generar_movimiento': generar, 'fecha_efectiva': fecha.isoformat(),
            'unidad': unidad, 'departamento': self.cargo.departamento_id,
            'cargo': self.cargo.pk, 'tipo_salario': 'FIJ', 'tipo': self.tipo.pk,
            'salarioEscala': '4000'}, **self.xhr)

    def _baja_previa(self, fecha):
        CBaja.objects.create(aspirante=self.aspirante, no_expediente='01401', tipo=self.tipo,
                             cargo=self.cargo, fecha_alta=fecha - timedelta(days=30),
                             fecha_baja=fecha)

    def test_recontratar_el_mismo_dia_de_la_baja_se_rechaza(self):
        self._baja_previa(self.hace_10)
        respuesta = self._recontratar(self.hace_10)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('debe ser posterior al último evento', respuesta.json()['error_popup'])
        self.assertFalse(CAlta.objects.filter(aspirante=self.aspirante).exists())

    def test_recontratar_antes_de_la_baja_se_rechaza(self):
        self._baja_previa(self.hace_10)
        respuesta = self._recontratar(self.hace_10 - timedelta(days=5))
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(CAlta.objects.filter(aspirante=self.aspirante).exists())

    def test_alta_con_fecha_futura_se_rechaza(self):
        respuesta = self._recontratar(self.manana)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('no puede ser una fecha futura', respuesta.json()['error_popup'])
        self.assertFalse(CAlta.objects.filter(aspirante=self.aspirante).exists())

    def test_recontratar_al_dia_siguiente_crea_siempre_el_alta_inicial(self):
        self._baja_previa(self.hace_10)
        dia_siguiente = self.hace_10 + timedelta(days=1)
        # Aunque llegue «omitir movimiento» (la opción ya no existe en pantalla), el
        # contrato nace con su Alta Inicial en la misma fecha.
        respuesta = self._recontratar(dia_siguiente, generar='false')
        self.assertTrue(respuesta.json()['form_is_valid'], respuesta.content[:300])
        contrato = CAlta.objects.get(aspirante=self.aspirante)
        self.assertEqual(contrato.fecha_alta, dia_siguiente)
        self.assertTrue(contrato.trazabilidad.filter(
            tipo_movimiento='Alta Inicial', fecha_efectiva=dia_siguiente).exists())

    # --- Movimiento de nómina y baja ----------------------------------------

    def _contrato_activo(self):
        contrato = CAlta.objects.create(aspirante=self.activo, no_expediente='01402', tipo=self.tipo,
                                        cargo=self.cargo, tipo_salario='FIJ', fecha_alta=self.hace_10)
        TMovimiento.objects.create(contrato=contrato, aspirante=self.activo, no_expediente='01402',
                                   fecha_efectiva=self.hace_10, cargo_anterior='---',
                                   cargo_nuevo='Especialista B', salario_anterior=0,
                                   salario_nuevo=4000, tipo_movimiento='Alta Inicial')
        return contrato

    def _movimiento(self, contrato, fecha):
        return self.client.post(reverse('movimiento_contrato', args=[contrato.pk]), {
            'fecha_efectiva': fecha.isoformat(),
            'unidad': self.cargo.departamento.unidad_organizativa_id,
            'departamento': self.cargo.departamento_id, 'cargo': self.otro_cargo.pk,
            'tipo': self.tipo.pk, 'tipo_salario': 'FIJ', 'salarioEscala': '4000'}, **self.xhr)

    def test_movimiento_el_mismo_dia_que_el_ultimo_evento_se_rechaza(self):
        contrato = self._contrato_activo()
        respuesta = self._movimiento(contrato, self.hace_10)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('No se permiten dos eventos el mismo día', respuesta.json()['error_popup'])
        self.assertEqual(contrato.trazabilidad.count(), 1)

    def test_movimiento_con_fecha_futura_se_rechaza(self):
        contrato = self._contrato_activo()
        respuesta = self._movimiento(contrato, self.manana)
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(contrato.trazabilidad.count(), 1)

    def test_movimiento_al_dia_siguiente_se_registra(self):
        contrato = self._contrato_activo()
        respuesta = self._movimiento(contrato, self.hace_10 + timedelta(days=1))
        self.assertTrue(respuesta.json()['form_is_valid'], respuesta.content[:300])
        self.assertEqual(contrato.trazabilidad.count(), 2)

    def test_el_movimiento_guarda_el_salario_de_la_escala_y_no_el_del_navegador(self):
        # 24-10-2026: el salario lo calcula el servidor. Aunque la página mande otro,
        # se guarda el de la escala (Fijo: el básico del cargo nuevo, 4 000).
        contrato = self._contrato_activo()
        datos = {'fecha_efectiva': (self.hace_10 + timedelta(days=1)).isoformat(),
                 'unidad': self.cargo.departamento.unidad_organizativa_id,
                 'departamento': self.cargo.departamento_id, 'cargo': self.otro_cargo.pk,
                 'tipo': self.tipo.pk, 'tipo_salario': 'FIJ', 'salarioEscala': '99999'}
        respuesta = self.client.post(reverse('movimiento_contrato', args=[contrato.pk]), datos, **self.xhr)
        self.assertTrue(respuesta.json()['form_is_valid'], respuesta.content[:300])
        movimiento = contrato.trazabilidad.order_by('-fecha_efectiva').first()
        self.assertEqual(movimiento.salario_nuevo, Decimal('4000.00'))

    def test_sin_salario_en_la_escala_no_se_registra_el_movimiento(self):
        contrato = self._contrato_activo()
        NCargo.objects.filter(pk=self.otro_cargo.ncargo_id).update(salario_basico=0)
        respuesta = self._movimiento(contrato, self.hace_10 + timedelta(days=1))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Salario no calculado', respuesta.json()['error_popup'])
        self.assertEqual(contrato.trazabilidad.count(), 1)

    def _baja(self, contrato, fecha_baja, fecha_documento=None):
        return self.client.post(reverse('del_contrato', args=[contrato.pk]), {
            'fecha_baja': fecha_baja.isoformat(),
            'fecha_efectiva': (fecha_documento or fecha_baja).isoformat(),
            'causa_baja': self.causa.pk})

    def test_baja_el_mismo_dia_que_el_alta_se_rechaza(self):
        contrato = self._contrato_activo()
        respuesta = self._baja(contrato, self.hace_10)
        self.assertEqual(respuesta.status_code, 400)
        self.assertTrue(CAlta.objects.filter(pk=contrato.pk).exists())

    def test_baja_futura_o_documento_futuro_se_rechazan(self):
        contrato = self._contrato_activo()
        self.assertEqual(self._baja(contrato, self.manana).status_code, 400)
        self.assertEqual(self._baja(contrato, self.ayer, fecha_documento=self.manana).status_code, 400)
        self.assertTrue(CAlta.objects.filter(pk=contrato.pk).exists())

    def test_baja_posterior_se_registra(self):
        contrato = self._contrato_activo()
        respuesta = self._baja(contrato, self.ayer)
        self.assertTrue(respuesta.json()['success'], respuesta.content[:300])
        self.assertFalse(CAlta.objects.filter(pk=contrato.pk).exists())

    # --- Formularios ----------------------------------------------------------

    def test_el_formulario_de_movimiento_no_acepta_fechas_futuras(self):
        contrato = self._contrato_activo()
        form = MovimientoForm(data={'fecha_efectiva': self.manana, 'fecha_solicitud': self.manana},
                              instance=contrato, user=self.admin)
        form.is_valid()
        self.assertIn('fecha_efectiva', form.errors)
        self.assertIn('fecha_solicitud', form.errors)


class SabanaExcelTests(TestCase):
    """La sábana de Excel exporta lo que se ve en la lista: mismos filtros, misma
    búsqueda y el alcance del usuario (24-10-2026). Y el nombre del fichero."""

    @classmethod
    def setUpTestData(cls):
        from bolsa.models import Aspirante
        from nomencladores.models import NTipoContrato
        from usuarios.models import CustomUser
        cls.cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        tipo = NTipoContrato.objects.create(descripcion='Indeterminado')
        for doc, nombre, exp in (('80010113197', 'Ana', '03001'), ('80010113198', 'Berta', '03002')):
            aspirante = Aspirante.objects.create(
                nivel_educ='SA', nombre=nombre, papellido='Pérez', sapellido='Gómez',
                doc_identidad=doc, estado='ACTIVO', sexo='F', raza='BL',
                provincia=provincia, municipio=municipio, direccion='Calle 1')
            CAlta.objects.create(aspirante=aspirante, no_expediente=exp, tipo=tipo, cargo=cls.cargo,
                                 fecha_alta=date(2026, 1, 15), fecha_alta_entidad=date(2020, 1, 1),
                                 tipo_salario='FIJ')
        cls.admin = CustomUser.objects.create_user(username='adm_sab', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(username='mod_sab', password='x', es_moderador=True)

    def _filas(self, usuario, **params):
        import io
        import openpyxl
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse('exportar_contratos_excel'), params)
        self.assertEqual(respuesta.status_code, 200)
        hoja = openpyxl.load_workbook(io.BytesIO(respuesta.content)).active
        filas = list(hoja.iter_rows(values_only=True))
        return respuesta, filas[0], filas[1:]

    def test_exporta_todo_y_cada_cabecera_con_su_dato(self):
        respuesta, cabecera, filas = self._filas(self.admin)
        self.assertEqual(len(filas), 2)
        self.assertTrue(all(len(f) == len(cabecera) for f in filas))
        for columna in ('Serie CI', 'F. Alta Entidad', 'Otros', 'Años de Servicio', 'No. Res. Designado'):
            self.assertIn(columna, cabecera)
        self.assertEqual(filas[0][cabecera.index('Dirección')], 'Calle 1')
        self.assertRegex(respuesta['Content-Disposition'],
                         r'filename="Sabana_Contratos_\d{2}-\d{2}-\d{4}\.xlsx"')

    def test_respeta_la_busqueda_de_la_lista(self):
        respuesta, cabecera, filas = self._filas(self.admin, filter_contrato='Berta')
        self.assertEqual([f[cabecera.index('Nombre')] for f in filas], ['Berta'])
        self.assertIn('filtrado', respuesta['Content-Disposition'])

    def test_el_moderador_sin_esa_unidad_no_exporta_nada(self):
        _, _, filas = self._filas(self.moderador)
        self.assertEqual(filas, [])
        self.moderador.unidades.add(self.cargo.departamento.unidad_organizativa)
        _, _, filas = self._filas(self.moderador)
        self.assertEqual(len(filas), 2)


class ConfianzaResolucionesYOtrosTests(TestCase):
    """Bloque del 24-10-2026: De Confianza (del cargo), números de resolución desde el
    movimiento de nómina y «Otros» congelado en el movimiento."""

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal
        from nomencladores.models import NImporteGradoCientifico, NPagoAdicional
        cls.cargo = _crear_departamento_con_cargo()
        cls.cargo_nuevo = CargoPlantilla.objects.create(
            ncargo=NCargo.objects.create(descripcion='Jefe de Grupo', cat_ocupacional='TEC',
                                         grupo_escala=cls.cargo.ncargo.grupo_escala, salario_basico=4500),
            departamento=cls.cargo.departamento, cant_aprobada=5, orden_informe=2,
            funcionario=True, de_confianza=True)
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo = NTipoContrato.objects.create(descripcion='Indeterminado', ocupa_plaza=True,
                                                requiere_motivo=False)
        NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('300.00'))
        cls.instructor = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.INSTRUCTOR, descripcion='Instructor', importe=Decimal('150.00'))
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='NS', nombre='Rosa', papellido='Mora', sapellido='Paz', grado_cientifico='MC',
            doc_identidad='80010114003', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.admin = CustomUser.objects.create_user(username='admin_b4', password='x', es_admin=True)

    def setUp(self):
        self.hace_10 = timezone.localdate() - timedelta(days=10)
        self.contrato = CAlta.objects.create(
            aspirante=self.aspirante, no_expediente='01403', tipo=self.tipo, cargo=self.cargo,
            tipo_salario='FIJ', fecha_alta=self.hace_10, instructor_nomenclador=self.instructor,
            designado_res='99/25')
        TMovimiento.objects.create(contrato=self.contrato, aspirante=self.aspirante, no_expediente='01403',
                                   fecha_efectiva=self.hace_10, cargo_anterior='---', cargo_nuevo='x',
                                   salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')
        self.client.force_login(self.admin)

    def _movimiento(self, cargo, **extra):
        datos = {'fecha_efectiva': (self.hace_10 + timedelta(days=1)).isoformat(),
                 'unidad': cargo.departamento.unidad_organizativa_id,
                 'departamento': cargo.departamento_id, 'cargo': cargo.pk,
                 'tipo': self.tipo.pk, 'tipo_salario': 'FIJ', 'salarioEscala': '4500',
                 'designado_res': '99/25'}
        datos.update(extra)
        return self.client.post(reverse('movimiento_contrato', args=[self.contrato.pk]), datos,
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_de_confianza_es_del_cargo(self):
        self.assertFalse(self.contrato.de_confianza)
        self.contrato.cargo = self.cargo_nuevo
        self.assertTrue(self.contrato.de_confianza)

    def test_el_movimiento_escribe_las_resoluciones_que_pide_el_cargo_nuevo(self):
        respuesta = self._movimiento(self.cargo_nuevo, funcionario_res='11/26', confianza_res='12/26')
        self.assertTrue(respuesta.json()['form_is_valid'], respuesta.content[:300])
        self.contrato.refresh_from_db()
        self.assertEqual((self.contrato.funcionario_res, self.contrato.confianza_res), ('11/26', '12/26'))
        # El cargo nuevo no es Designado: su número deja de aplicar y se vacía.
        self.assertIsNone(self.contrato.designado_res)

    def test_solo_escribir_resoluciones_no_es_un_movimiento(self):
        respuesta = self._movimiento(self.cargo, funcionario_res='11/26')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('No se ha aplicado ningún cambio', respuesta.json()['error_popup'])

    def test_otros_queda_congelado_en_el_movimiento(self):
        from decimal import Decimal
        from nomencladores.models import NPagoAdicional
        self.assertEqual(self.contrato.importe_otros, Decimal('450.00'))  # 300 Maestría + 150 Instructor
        self.assertTrue(self._movimiento(self.cargo_nuevo).json()['form_is_valid'])
        movimiento = self.contrato.trazabilidad.get(tipo_movimiento='Movimiento de Nómina')
        self.assertEqual((movimiento.otros_anterior, movimiento.otros_nuevo),
                         (Decimal('450.00'), Decimal('450.00')))
        # Sube el nomenclador: el movimiento ya emitido no cambia.
        NPagoAdicional.objects.filter(pk=self.instructor.pk).update(importe=Decimal('999.00'))
        movimiento.refresh_from_db()
        self.assertEqual(movimiento.otros_nuevo, Decimal('450.00'))

    def test_falta_la_resolucion_de_confianza_avisa(self):
        from subsanacion.reglas.contratos import FuncionarioODesignadoSinCodigo
        self.contrato.cargo = self.cargo_nuevo
        claves = {h.clave_extra for h in FuncionarioODesignadoSinCodigo().evaluar_instancia(self.contrato)}
        self.assertIn('confianza_sin_codigo', claves)
        self.contrato.confianza_res = '12/26'
        self.contrato.funcionario_res = '11/26'
        self.assertIsNone(FuncionarioODesignadoSinCodigo().evaluar_instancia(self.contrato))

    # --- El tipo de contrato es obligatorio (24-10-2026): antes, un envío sin
    # tipo —el segundo paso del asistente o un movimiento— lo BORRABA. ---

    def test_un_movimiento_sin_tipo_se_rechaza_y_no_borra_el_tipo(self):
        respuesta = self._movimiento(self.cargo_nuevo, tipo='')
        self.assertNotEqual(respuesta.status_code, 200)
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.tipo_id, self.tipo.pk)
        self.assertEqual(self.contrato.trazabilidad.count(), 1)

    def test_el_formulario_del_contrato_exige_el_tipo(self):
        from .forms import CAltaForm
        # Al CREAR (al editar, el tipo va bloqueado y conserva el suyo).
        formulario = CAltaForm(data={}, user=self.admin)
        self.assertFalse(formulario.is_valid())
        self.assertEqual(formulario.errors['tipo'], ['Seleccione el tipo de contrato.'])


class EdicionBloqueaCamposDelMovimientoTests(TestCase):
    """Al editar un contrato, lo que solo cambia un movimiento de nómina va bloqueado
    (24-10-2026): el servidor IGNORA esos campos aunque lleguen cambiados. La
    duración sí se puede editar."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo = _crear_departamento_con_cargo()
        cls.otro_cargo = CargoPlantilla.objects.create(
            ncargo=NCargo.objects.create(descripcion='Otro Cargo', cat_ocupacional='TEC',
                                         grupo_escala=cls.cargo.ncargo.grupo_escala, salario_basico=4000),
            departamento=cls.cargo.departamento, cant_aprobada=5, orden_informe=2)
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo = NTipoContrato.objects.create(descripcion='Indeterminado', ocupa_plaza=False,
                                                requiere_motivo=False)
        cls.otro_tipo = NTipoContrato.objects.create(descripcion='Otro', ocupa_plaza=False,
                                                     requiere_motivo=False)
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Luis', papellido='Gil', sapellido='Sol',
            doc_identidad='80010114004', estado='ACTIVO', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.admin = CustomUser.objects.create_user(username='admin_bloqueo', password='x', es_admin=True)

    def test_el_servidor_ignora_los_campos_del_movimiento_y_guarda_la_duracion(self):
        hace_un_mes = timezone.localdate() - timedelta(days=30)
        contrato = CAlta.objects.create(
            aspirante=self.aspirante, no_expediente='01404', tipo=self.tipo, cargo=self.cargo,
            tipo_salario='FIJ', fecha_alta=hace_un_mes, fecha_alta_entidad=hace_un_mes, duracion=90)
        self.client.force_login(self.admin)
        self.client.post(reverse('updt_contrato', args=[contrato.pk]), {
            'no_expediente': '01404', 'tipo': self.otro_tipo.pk, 'cargo': self.otro_cargo.pk,
            'unidad': self.cargo.departamento.unidad_organizativa_id,
            'departamento': self.cargo.departamento_id, 'tipo_salario': 'DIN',
            'fecha_alta': (hace_un_mes - timedelta(days=5)).isoformat(),
            'fecha_alta_entidad': hace_un_mes.isoformat(), 'reg_militar': 'NIN', 'duracion': 120,
        }, HTTP_HX_REQUEST='true')
        contrato.refresh_from_db()
        self.assertEqual(contrato.duracion, 120)
        self.assertEqual((contrato.cargo_id, contrato.tipo_id, contrato.tipo_salario, contrato.fecha_alta),
                         (self.cargo.pk, self.tipo.pk, 'FIJ', hace_un_mes))


class ExpedienteUnicoDeLaPersonaTests(TestCase):
    """El expediente es único e irrepetible y una persona nunca tiene dos (24-10-2026):
    corregirlo en el contrato lo cambia en TODA la persona, y no se puede dar a otra."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo = _crear_departamento_con_cargo()
        provincia, municipio = _crear_provincia_municipio()
        cls.tipo = NTipoContrato.objects.create(descripcion='Indeterminado')
        cls.persona = Aspirante.objects.create(
            nivel_educ='SA', nombre='Eva', papellido='Ruiz', sapellido='Paz',
            doc_identidad='80010114005', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.otra = Aspirante.objects.create(
            nivel_educ='SA', nombre='Otro', papellido='Gil', sapellido='Sol',
            doc_identidad='80010114006', estado='BAJA', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        hoy = timezone.localdate()
        # La otra persona, ya de baja, tuvo el 07777.
        CBaja.objects.create(aspirante=cls.otra, no_expediente='07777', tipo=cls.tipo, cargo=cls.cargo,
                             fecha_alta=hoy - timedelta(days=900), fecha_baja=hoy - timedelta(days=800))

    def test_corregirlo_cambia_toda_la_persona(self):
        hoy = timezone.localdate()
        CBaja.objects.create(aspirante=self.persona, no_expediente='01405', tipo=self.tipo, cargo=self.cargo,
                             fecha_alta=hoy - timedelta(days=700), fecha_baja=hoy - timedelta(days=600))
        viejo = TMovimiento.objects.create(
            aspirante=self.persona, no_expediente='01405', fecha_efectiva=hoy - timedelta(days=650),
            cargo_anterior='x', cargo_nuevo='y', salario_anterior=0, salario_nuevo=0,
            tipo_movimiento='Movimiento de Nómina')
        contrato = CAlta.objects.create(aspirante=self.persona, no_expediente='01405', tipo=self.tipo,
                                        cargo=self.cargo, fecha_alta=hoy - timedelta(days=100))
        contrato.no_expediente = '01406'
        contrato.save()
        viejo.refresh_from_db()
        self.assertEqual(viejo.no_expediente, '01406')
        self.assertEqual(set(CBaja.objects.filter(aspirante=self.persona).values_list('no_expediente', flat=True)),
                         {'01406'})

    def test_no_se_puede_dar_el_de_otra_persona(self):
        from .forms import CAltaForm
        formulario = CAltaForm(data={'no_expediente': '07777'}, aspirante=self.persona)
        formulario.is_valid()
        self.assertIn('ya pertenece a Otro Gil Sol', formulario.errors['no_expediente'][0])
