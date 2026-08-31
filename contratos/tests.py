"""Pruebas del "escudo" de `CAlta.save()` sobre el campo `tridente`.

El tridente solo aplica a un contrato de salario dinámico cuyo cargo NO es de
categoría Cuadro (Directivo o Ejecutivo) — misma "REGLA DE ORO" que
`CAltaForm.clean()` y que `contratos/salarios.py::calcular_salario()`. Estas
pruebas cubren el "escudo" de `save()`, que es la última línea de defensa para
cualquier guardado que no pase por el formulario (admin de Django, scripts).
"""

from datetime import date

from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from bolsa.models import Aspirante
from contratos.filtros import aplicar_filtros
from contratos.forms import CAltaForm, MovimientoForm
from contratos.models import CAlta, CBaja, TMovimiento
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio, NProvincia,
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

        cls.aspirante = Aspirante.objects.create(
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

    def test_dinamico_sin_cuadro_y_sin_tridente_asigna_el_por_defecto(self):
        alta = self._crear_alta(self.cargo_no_cuadro, 'DIN', tridente=None)
        alta.refresh_from_db()
        self.assertEqual(alta.tridente_id, self.tridente_i.pk)

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
            return Aspirante.objects.create(
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

        asp_negra = Aspirante.objects.create(
            nombre='Ana', papellido='Perez', sapellido='Gomez',
            doc_identidad='00000000001', estado='ACTIVO', sexo='F', raza='NE',
            provincia=provincia, municipio=municipio)
        cls.contrato_negra = CAlta.objects.create(
            aspirante=asp_negra, no_expediente='00001', tipo=tipo_contrato, cargo=cargo)

        asp_blanca = Aspirante.objects.create(
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

        cls.trabajador_a = Aspirante.objects.create(
            nombre='Ana', papellido='Perez', sapellido='Gomez',
            doc_identidad='00000000011', estado='ACTIVO', sexo='F', raza='NE',
            provincia=provincia, municipio=municipio)
        cls.trabajador_b = Aspirante.objects.create(
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
        self.assertIn('Movimiento_00011.docx', respuesta['Content-Disposition'])

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
        self.assertIn('Movimiento_00012.docx', respuesta['Content-Disposition'])

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
        return Aspirante.objects.create(
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
        aspirante = Aspirante.objects.create(
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
        aspirante = Aspirante.objects.create(
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
        cls.aspirante = Aspirante.objects.create(
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
        aspirante = Aspirante.objects.create(
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
        aspirante = Aspirante.objects.create(
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
        aspirante = Aspirante.objects.create(
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
        aspirante = Aspirante.objects.create(
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
        cls.aspirante = Aspirante.objects.create(
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
        self.assertIn('modalExportarExcel', self._html(self.observador))

    def test_observador_no_ve_el_boton_nuevo(self):
        self.assertNotIn('id="btn-nuevo-contrato"', self._html(self.observador))

    def test_moderador_conserva_todas_las_acciones(self):
        html = self._html(self.moderador)
        for boton in self.ESCRITURA:
            with self.subTest(boton=boton):
                self.assertNotIn('disabled', self._etiqueta(html, boton))
        self.assertIn('id="btn-nuevo-contrato"', html)
