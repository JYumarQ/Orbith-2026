"""Plazas sobregiradas (25-10-2026): bloqueo en «Editar contrato», cambio de tipo en
el mismo cargo, EST-011 y no bajar las plazas aprobadas por debajo de las cubiertas."""

from datetime import date

from django.test import TestCase

from bolsa.models import Aspirante
from nomencladores.models import NTipoContrato

from .forms import CAltaForm, MovimientoForm
from .models import CAlta
from .plazas import sobregiro_de
from .tests import _crear_departamento_con_cargo, _crear_provincia_municipio


class PlazasSobregiradasTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.cargo = _crear_departamento_con_cargo()          # 5 plazas aprobadas
        provincia, municipio = _crear_provincia_municipio()
        cls.indeterminado = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True, requiere_motivo=False)
        cls.determinado = NTipoContrato.objects.create(
            descripcion='Determinado', ocupa_plaza=False, requiere_motivo=False)
        cls.contratos = []
        for n in range(3):
            persona = Aspirante.objects.create(
                nivel_educ='SA', nombre='Trab%d' % n, papellido='Plaza', sapellido='Test',
                doc_identidad='9001011%04d' % n, estado='ACTIVO', sexo='F', raza='BL',
                provincia=provincia, municipio=municipio)
            cls.contratos.append(CAlta.objects.create(
                aspirante=persona, no_expediente='0090%d' % n, tipo=cls.indeterminado,
                cargo=cls.cargo, fecha_alta=date(2026, 1, 1 + n)))

    def aprobar(self, n):
        type(self.cargo).objects.filter(pk=self.cargo.pk).update(cant_aprobada=n)
        self.cargo.refresh_from_db()

    def datos(self, contrato, tipo):
        return {'tipo': str(tipo.pk), 'cargo': str(contrato.cargo_id),
                'fecha_alta': contrato.fecha_alta.isoformat()}

    def errores_generales(self, form):
        form.is_valid()
        return ' '.join(form.non_field_errors())

    def test_sin_sobregiro_no_hay_aviso_ni_bloqueo(self):
        self.assertIsNone(sobregiro_de(self.contratos[0]))
        form = CAltaForm(instance=self.contratos[0], data=self.datos(self.contratos[0], self.indeterminado))
        self.assertNotIn('sobregirado', self.errores_generales(form))

    def test_un_cargo_sobregirado_bloquea_editar_contrato_a_todos_sus_ocupantes(self):
        self.aprobar(1)
        s = sobregiro_de(self.contratos[2])
        self.assertEqual((s['ocupadas'], s['aprobadas'], len(s['ocupantes'])), (3, 1, 3))
        for contrato in self.contratos:
            form = CAltaForm(instance=contrato, data=self.datos(contrato, self.indeterminado))
            self.assertIn('está sobregirado', self.errores_generales(form))

    def test_el_movimiento_de_nomina_no_se_bloquea(self):
        self.aprobar(1)
        contrato = self.contratos[1]
        form = MovimientoForm(instance=contrato, data=self.datos(contrato, self.indeterminado))
        self.assertNotIn('sobregirado', self.errores_generales(form))

    def test_pasar_a_un_tipo_que_ocupa_plaza_en_un_cargo_lleno_no_vale(self):
        self.aprobar(3)
        CAlta.objects.filter(pk=self.contratos[2].pk).update(tipo=self.determinado)
        self.aprobar(2)          # 2 Indeterminados en 2 plazas: lleno
        contrato = CAlta.objects.get(pk=self.contratos[2].pk)
        # En «Editar contrato» el tipo va bloqueado: solo lo cambia un movimiento.
        form = MovimientoForm(instance=contrato, data=self.datos(contrato, self.indeterminado))
        form.is_valid()
        self.assertIn('no tiene plazas disponibles', ' '.join(form.errors.get('cargo', [])))

    def test_est_011_encuentra_el_cargo_sobregirado(self):
        from subsanacion.contexto import ContextoAnalisis
        from subsanacion.reglas import obtener_regla
        regla = obtener_regla('EST-011')
        self.assertEqual(list(regla.ejecutar(ContextoAnalisis())), [])
        self.aprobar(2)
        hallazgos = list(regla.ejecutar(ContextoAnalisis()))
        self.assertEqual([h.object_id for h in hallazgos], [str(self.cargo.pk)])
        self.assertEqual(hallazgos[0].datos['sobran'], 1)

    def test_no_se_aprueban_menos_plazas_que_las_cubiertas(self):
        from strorganizativa.forms import CargoPlantillaForm
        form = CargoPlantillaForm(instance=self.cargo, data={'cant_aprobada': 2})
        form.is_valid()
        self.assertIn('no puede aprobar menos de 3', ' '.join(form.errors.get('cant_aprobada', [])))
        # Subir, o un cargo ya sobregirado que no baja, no se bloquea por esto.
        self.aprobar(1)
        form = CargoPlantillaForm(instance=self.cargo, data={'cant_aprobada': 1})
        form.is_valid()
        self.assertNotIn('cant_aprobada', form.errors)
