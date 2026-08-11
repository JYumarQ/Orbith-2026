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
from contratos.models import CAlta
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
