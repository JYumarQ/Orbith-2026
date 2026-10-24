"""Fase 1 del 23-10-2026: cálculo único del salario, cambios externos con motivo,
nomenclador de cargo (paso a Cuadro y salida), «Ocupa plaza», Tridente I y las
reglas CFG-004, CFG-005 y EST-008."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from configuracion.models import Configuracion
from contratos.cambios_externos import MotivoRequerido, motivo_de_cambio
from contratos.models import CAlta, CambioExterno
from contratos.tests import _crear_departamento_con_cargo, _crear_provincia_municipio
from nomencladores.models import (NCargo, NGrupoEscala, NImporteGradoCientifico, NPagoAdicional,
                                  NRol, NSalario, NTipoContrato, NTridente)
from strorganizativa.models import CargoPlantilla
from usuarios.models import CustomUser


class BaseCambios(TestCase):

    @classmethod
    def setUpTestData(cls):
        Configuracion.objects.create(nombre_empresa='Prueba', fondo_tiempo_calc_tarif=Decimal('190.6'),
                                     porcentaje_horas_extras=Decimal('0.25'))
        cls.cargo = _crear_departamento_con_cargo()           # grupo IV, Técnico, básico 4000
        cls.grupo = cls.cargo.ncargo.grupo_escala
        cls.fundamental = NRol.objects.create(tipo='Fundamental')
        cls.decisorio = NRol.objects.create(tipo='Decisorio')
        cls.tridente = NTridente.objects.create(tipo='I')
        NSalario.objects.create(grupo_escala=cls.grupo, rol=cls.fundamental, tridente=cls.tridente, monto=4890)
        NSalario.objects.create(grupo_escala=cls.grupo, rol=cls.decisorio, tridente=cls.tridente, monto=5379)
        NSalario.objects.create(grupo_escala=cls.grupo, rol=None, tridente=None, monto=8550)
        CargoPlantilla.objects.filter(pk=cls.cargo.pk).update(rol=cls.fundamental)
        cls.cargo.refresh_from_db()
        provincia, municipio = _crear_provincia_municipio()
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Osiel', papellido='Torres', sapellido='Pérez',
            doc_identidad='80010113199', estado='ACTIVO', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.tipo = NTipoContrato.objects.create(descripcion='Indeterminado', ocupa_plaza=True,
                                                requiere_motivo=False)
        cls.contrato = CAlta.objects.create(
            aspirante=cls.aspirante, no_expediente='02890', tipo=cls.tipo, cargo=cls.cargo,
            tridente=cls.tridente, tipo_salario='DIN', fecha_alta=date(2025, 1, 20))
        cls.admin = CustomUser.objects.create_user(username='admin_fase1', password='x', es_admin=True)


class CalculoUnicoTests(BaseCambios):
    """Todas las pantallas calculan el salario y las tarifas igual que el Word."""

    def test_pantalla_editar_usa_el_calculo_unico(self):
        self.client.force_login(self.admin)
        contexto = self.client.get(reverse('updt_contrato', args=[self.contrato.pk])).context
        self.assertEqual(contexto['initial_salario_escala'], 4890.0)
        self.assertEqual(contexto['initial_tarifa_horaria'], round(4890 / 190.6, 5))
        self.assertEqual(contexto['initial_tarifa_extras'], round(4890 / 190.6 * 1.25, 5))

    def test_salario_fijo_y_cuadro_en_la_pantalla_editar(self):
        """Antes la pantalla ignoraba el Fijo y dejaba vacío el de los cuadros."""
        CAlta.objects.filter(pk=self.contrato.pk).update(tipo_salario='FIJ', tridente=None)
        self.client.force_login(self.admin)
        contexto = self.client.get(reverse('updt_contrato', args=[self.contrato.pk])).context
        self.assertEqual(contexto['initial_salario_escala'], 4000.0)

    def test_calculo_en_vivo_horas_extras_con_el_porcentaje(self):
        """Antes: «salario ÷ 160.6» fijo en el código."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse('cargar_salarios'), {
            'cargo': self.cargo.pk, 'tridente': self.tridente.pk, 'tipo_salario': 'DIN'})
        self.assertEqual(r.context['salario'], 4890.0)
        self.assertEqual(r.context['extras'], round(4890 / 190.6 * 1.25, 5))

    def test_sin_fondo_de_tiempo_no_se_inventa_la_tarifa(self):
        from contratos.tarifas import calcular_tarifas
        self.assertEqual(calcular_tarifas(4890, (None, Decimal('0.25'))),
                         {'salario': 4890.0, 'tarifa': None, 'extras': None})


class CambiosExternosTests(BaseCambios):

    def test_cambiar_el_rol_con_motivo_queda_en_el_historico(self):
        with motivo_de_cambio('Reorganización de la UEB'):
            self.cargo.rol = self.decisorio
            self.cargo.save()
        cambio = CambioExterno.objects.get(contrato=self.contrato)
        self.assertEqual(cambio.origen, CambioExterno.Origen.CARGO)
        self.assertIn('cambió de rol: Fundamental a Decisorio', cambio.descripcion)
        self.assertEqual((cambio.valor_anterior, cambio.valor_nuevo), ('Salario 4890.00', 'Salario 5379.00'))
        self.assertEqual(cambio.motivo, 'Reorganización de la UEB')

        self.client.force_login(self.admin)
        datos = self.client.get(reverse('historico_trabajador', args=[self.aspirante.pk])).json()['data']
        externos = [d for d in datos if d.get('es_cambio_externo')]
        self.assertEqual(len(externos), 1)
        self.assertEqual(externos[0]['motivo'], 'Reorganización de la UEB')

    def test_sin_motivo_desde_una_pantalla_no_se_guarda(self):
        with self.assertRaises(MotivoRequerido):
            with motivo_de_cambio(''):
                self.cargo.rol = self.decisorio
                self.cargo.save()

    def test_la_pantalla_del_cargo_pide_el_motivo(self):
        self.client.force_login(self.admin)
        datos = {'ncargo': self.cargo.ncargo_id, 'departamento': self.cargo.departamento_id,
                 'rol': self.decisorio.pk, 'cant_aprobada': 5, 'cant_cubierta': 1,
                 'orden_informe': 1, 'en_plantilla': 'on',
                 'unidad': self.cargo.departamento.unidad_organizativa_id}
        r = self.client.post(reverse('updt_cargo', args=[self.cargo.pk]), datos, HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Indique el motivo del cambio')
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.rol_id, self.fundamental.pk)
        self.assertFalse(CambioExterno.objects.exists())

        datos['motivo_cambio'] = 'Reorganización'
        r = self.client.post(reverse('updt_cargo', args=[self.cargo.pk]), datos, HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 204)
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.rol_id, self.decisorio.pk)
        self.assertTrue(CambioExterno.objects.filter(motivo='Reorganización').exists())

    def test_error_humano_oculta_y_anula_el_cambio_anterior(self):
        with motivo_de_cambio('Cambio real'):
            self.cargo.rol = self.decisorio
            self.cargo.save()
        with motivo_de_cambio('', error_humano=True):
            self.cargo.rol = self.fundamental
            self.cargo.save()
        self.assertEqual(CambioExterno.objects.filter(anulado=True).count(), 1)
        self.assertEqual(CambioExterno.objects.filter(error_humano=True).count(), 1)
        self.client.force_login(self.admin)
        datos = self.client.get(reverse('historico_trabajador', args=[self.aspirante.pk])).json()['data']
        self.assertFalse([d for d in datos if d.get('es_cambio_externo')])

    def test_la_escala_sin_motivo_no_se_guarda(self):
        self.client.force_login(self.admin)
        datos = {f'salario_{self.fundamental.pk}_{self.tridente.pk}': '5000',
                 f'salario_{self.decisorio.pk}_{self.tridente.pk}': '5379'}
        self.client.post(reverse('editar_salarios', args=[self.grupo.pk]), datos)
        self.assertTrue(NSalario.objects.filter(grupo_escala=self.grupo, monto=4890).exists())
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.salario_actual, Decimal('4890.00'))

    def test_cambiar_el_importe_de_cnci_queda_en_el_historico(self):
        cnci = NPagoAdicional.objects.create(tipo=NPagoAdicional.CNCI, descripcion='Etapa I',
                                             importe=Decimal('329.00'))
        CAlta.objects.filter(pk=self.contrato.pk).update(cnci_nomenclador=cnci)
        with motivo_de_cambio('Res. nueva'):
            cnci.importe = Decimal('350.00')
            cnci.save()
        cambio = CambioExterno.objects.get(origen=CambioExterno.Origen.IMPORTE)
        self.assertEqual(cambio.valor_nuevo, 'CNCI «Etapa I»: 350.00')

    def test_no_se_puede_borrar_una_entrada_de_cnci_en_uso(self):
        cnci = NPagoAdicional.objects.create(tipo=NPagoAdicional.CNCI, descripcion='Etapa I',
                                             importe=Decimal('329.00'))
        CAlta.objects.filter(pk=self.contrato.pk).update(cnci_nomenclador=cnci)
        self.client.force_login(self.admin)
        self.client.post(reverse('importe_eliminar', args=['cnci', cnci.pk]))
        self.assertTrue(NPagoAdicional.objects.filter(pk=cnci.pk).exists())

    def test_cambiar_el_grado_de_la_ficha_queda_en_el_historico(self):
        NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('440.00'))
        with motivo_de_cambio('Defendió la maestría'):
            self.aspirante.grado_cientifico = 'MC'
            self.aspirante.save()
        cambio = CambioExterno.objects.get(origen=CambioExterno.Origen.FICHA)
        self.assertIn('Maestría 440.00', cambio.valor_nuevo)

    def test_renombrar_el_departamento_queda_en_el_historico(self):
        with motivo_de_cambio('Nueva estructura'):
            departamento = self.cargo.departamento
            departamento.descripcion = 'Economía'
            departamento.save()
        cambio = CambioExterno.objects.get(origen=CambioExterno.Origen.DEPARTAMENTO)
        self.assertEqual((cambio.valor_anterior, cambio.valor_nuevo), ('Contabilidad', 'Economía'))


class NomencladorDeCargoTests(BaseCambios):

    def test_pasar_a_cuadro_quita_rol_y_tridente(self):
        ncargo = self.cargo.ncargo
        ncargo.cat_ocupacional = 'CDI'
        ncargo.save()
        self.cargo.refresh_from_db()
        self.contrato.refresh_from_db()
        self.assertIsNone(self.cargo.rol_id)
        self.assertIsNone(self.contrato.tridente_id)
        self.assertEqual(self.contrato.salario_actual, Decimal('8550.00'))
        self.assertTrue(CambioExterno.objects.filter(origen=CambioExterno.Origen.NOMENCLADOR_CARGO).exists())

    def test_dejar_de_ser_cuadro_avisa_cargo_sin_rol(self):
        from subsanacion.reglas.estructura import CargoSinRol
        ncargo = self.cargo.ncargo
        ncargo.cat_ocupacional = 'CDI'
        ncargo.save()
        self.assertEqual(list(CargoSinRol().ejecutar(None)), [])
        ncargo.cat_ocupacional = 'TEC'
        ncargo.save()
        self.assertEqual([h.object_id for h in CargoSinRol().ejecutar(None)], [str(self.cargo.pk)])
        self.contrato.refresh_from_db()
        self.assertIsNone(self.contrato.salario_actual)

    def test_cambiar_el_salario_basico_recalcula_los_fijos(self):
        CAlta.objects.filter(pk=self.contrato.pk).update(tipo_salario='FIJ', tridente=None,
                                                          salario_actual=4000)
        ncargo = self.cargo.ncargo
        ncargo.salario_basico = Decimal('4200')
        ncargo.save()
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.salario_actual, Decimal('4200.00'))


class OtrosCasosTests(BaseCambios):

    def test_ocupa_plaza_recuenta_las_plazas(self):
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.cant_cubierta, 1)
        self.tipo.ocupa_plaza = False
        self.tipo.save()
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.cant_cubierta, 0)

    def test_sin_tridente_i_por_defecto(self):
        contrato = CAlta.objects.create(
            aspirante=Aspirante.objects.create(
                nivel_educ='SA', nombre='Sin', papellido='Tri', sapellido='Dente',
                doc_identidad='80010113198', estado='ACTIVO', sexo='M', raza='BL',
                provincia=self.aspirante.provincia, municipio=self.aspirante.municipio),
            no_expediente='02891', tipo=self.tipo, cargo=self.cargo, tipo_salario='DIN',
            fecha_alta=date(2025, 1, 20))
        self.assertIsNone(contrato.tridente_id)
        self.assertIsNone(contrato.salario_actual)


class ReglasDeConfiguracionTests(BaseCambios):

    def test_cfg004_fondo_y_porcentaje(self):
        from subsanacion.reglas.configuracion import ParametrosDeTarifaInvalidos
        self.assertEqual(list(ParametrosDeTarifaInvalidos().ejecutar(None)), [])
        Configuracion.objects.update(fondo_tiempo_calc_tarif=0, porcentaje_horas_extras=25)
        claves = {h.clave_extra for h in ParametrosDeTarifaInvalidos().ejecutar(None)}
        self.assertEqual(claves, {'fondo', 'porcentaje'})

    def test_cfg005_escala_sin_el_importe_que_usa_un_contrato(self):
        from subsanacion.reglas.configuracion import EscalaSalarialIncompleta
        self.assertEqual(list(EscalaSalarialIncompleta().ejecutar(None)), [])
        NSalario.objects.filter(grupo_escala=self.grupo, rol=self.fundamental).delete()
        hallazgos = list(EscalaSalarialIncompleta().ejecutar(None))
        self.assertEqual(len(hallazgos), 1)
        self.assertIn('Fundamental · Tridente I', hallazgos[0].detalle)

    def test_el_formulario_rechaza_un_porcentaje_mayor_que_uno(self):
        from configuracion.forms import ConfiguracionForm
        form = ConfiguracionForm()
        form.cleaned_data = {'porcentaje_horas_extras': Decimal('25')}
        with self.assertRaises(Exception):
            form.clean_porcentaje_horas_extras()
