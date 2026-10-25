"""Tipo de contrato obligatorio en el histórico y situación tras los cambios externos
(decisiones de RRHH del 25-10-2026)."""

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from . import editor_historico as eh
from .cambios_externos import motivo_de_cambio
from .models import CambioExterno, TMovimiento
from . import tests_cambios_externos
from . import tests_editor_historico


def _hallazgos_mov016(persona):
    from subsanacion.contexto import ContextoAnalisis
    from subsanacion.reglas import obtener_regla
    return [h for h in obtener_regla('MOV-016').ejecutar(ContextoAnalisis()) if h.object_id == str(persona.pk)]


class TipoDeContratoEnElHistoricoTests(TestCase):
    """Persona con un contrato cerrado (alta, movimiento y baja) y otro vigente (alta
    y movimiento). Se le quita el tipo a varios eventos, como en los datos antiguos."""

    @classmethod
    def setUpTestData(cls):
        tests_editor_historico.EditorHistoricoMotorTests.setUpTestData.__func__(cls)

    def quitar_tipo(self, *movimientos, antes=False):
        campos = {'tipo_contrato_nuevo': None}
        if antes:
            campos['tipo_contrato_anterior'] = None
        TMovimiento.objects.filter(pk__in=[m.pk for m in movimientos]).update(**campos)

    def test_el_editor_no_deja_guardar_un_evento_sin_tipo(self):
        self.quitar_tipo(self.m_alta1)
        _, _, errores, _ = eh.preparar(self.persona, [])
        self.assertTrue(any('falta el tipo de contrato' in e for e in errores), errores)

    def test_con_el_tipo_elegido_ya_se_puede_guardar(self):
        self.quitar_tipo(self.m_alta1)
        _, _, errores, _ = eh.preparar(self.persona, [
            {'op': 'editar', 'evento': 'mov:%d' % self.m_alta1.pk, 'campos': {'tipo_id': self.indeterminado.pk}}])
        self.assertEqual(errores, [])

    def test_un_tipo_que_ya_no_existe_tampoco_vale(self):
        TMovimiento.objects.filter(pk=self.m_mov2.pk).update(tipo_contrato_nuevo='Temporal')
        _, _, errores, _ = eh.preparar(self.persona, [])
        self.assertTrue(any('«Temporal» ya no existe' in e for e in errores), errores)

    def test_la_reparacion_rellena_solo_lo_seguro(self):
        # Contrato cerrado: el movimiento antes de la baja toma el tipo de la baja; el
        # alta, el «antes» de ese movimiento. Contrato vigente: el último evento toma el
        # tipo del contrato.
        self.quitar_tipo(self.m_alta1, self.m_mov1, self.m_mov2)
        call_command('reparar_tipos_historico', '--aplicar', stdout=_Nulo())
        for movimiento in (self.m_alta1, self.m_mov1, self.m_mov2):
            movimiento.refresh_from_db()
            self.assertEqual(movimiento.tipo_contrato_nuevo, 'Indeterminado', movimiento.tipo_movimiento)
        self.assertEqual(_hallazgos_mov016(self.persona), [])

    def test_la_simulacion_no_guarda_nada(self):
        self.quitar_tipo(self.m_mov2)
        call_command('reparar_tipos_historico', stdout=_Nulo())
        self.m_mov2.refresh_from_db()
        self.assertIsNone(self.m_mov2.tipo_contrato_nuevo)

    def test_lo_que_no_se_puede_saber_se_queda_y_lo_avisa_mov016(self):
        # El alta del contrato cerrado no tiene tipo y el movimiento siguiente tampoco
        # dice de qué tipo venía: no se puede saber.
        self.quitar_tipo(self.m_alta1)
        self.quitar_tipo(self.m_mov1, antes=True)
        TMovimiento.objects.filter(pk=self.m_mov1.pk).update(tipo_contrato_nuevo='Indeterminado')
        call_command('reparar_tipos_historico', '--aplicar', stdout=_Nulo())
        self.m_alta1.refresh_from_db()
        self.assertIsNone(self.m_alta1.tipo_contrato_nuevo)
        hallazgos = _hallazgos_mov016(self.persona)
        self.assertEqual(len(hallazgos), 1)
        self.assertIn('1 evento del histórico sin tipo de contrato o sin motivo', hallazgos[0].titulo)


    # --- El motivo, cuando el tipo lo pide -----------------------------------

    def contrato_determinado(self):
        """El contrato vigente pasa a Determinado con su motivo; su último movimiento
        tiene el tipo pero no el motivo, como las altas antiguas del asistente."""
        from .models import CAlta
        CAlta.objects.filter(pk=self.contrato.pk).update(tipo=self.determinado, motivo=self.motivo)
        TMovimiento.objects.filter(pk=self.m_mov2.pk).update(tipo_contrato_nuevo='Determinado', motivo_nuevo=None)

    def test_el_editor_exige_el_motivo_si_el_tipo_lo_pide(self):
        self.contrato_determinado()
        _, _, errores, _ = eh.preparar(self.persona, [])
        self.assertTrue(any('pide motivo y no lo tiene' in e for e in errores), errores)
        _, _, errores, _ = eh.preparar(self.persona, [
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk, 'campos': {'motivo_id': self.motivo.pk}}])
        self.assertEqual(errores, [])

    def test_la_reparacion_toma_el_motivo_del_contrato_vigente(self):
        self.contrato_determinado()
        call_command('reparar_tipos_historico', '--aplicar', stdout=_Nulo())
        self.m_mov2.refresh_from_db()
        self.assertEqual(self.m_mov2.motivo_nuevo, 'Sustitución')
        self.assertEqual(_hallazgos_mov016(self.persona), [])

    def test_mov016_avisa_del_motivo_que_falta(self):
        self.contrato_determinado()
        hallazgos = _hallazgos_mov016(self.persona)
        self.assertEqual(len(hallazgos), 1)
        self.assertIn('sin motivo', hallazgos[0].detalle)


class _Nulo:
    def write(self, *args, **kwargs):
        pass

    def flush(self):
        pass


class SituacionTrasCambioExternoTests(tests_cambios_externos.BaseCambios):
    """Cada cambio externo guarda cómo quedó el contrato y el histórico la enseña."""

    def renombrar_unidad(self, nombre):
        unidad = self.cargo.departamento.unidad_organizativa
        with motivo_de_cambio('Nueva denominación'):
            unidad.descripcion = nombre
            unidad.save()

    def test_el_cambio_guarda_la_situacion_nueva(self):
        self.renombrar_unidad('UEB Norte')
        cambio = CambioExterno.objects.get(contrato=self.contrato, origen=CambioExterno.Origen.UNIDAD)
        self.assertEqual(cambio.situacion['unidad'], 'UEB Norte')
        self.assertEqual(cambio.situacion['departamento'], self.cargo.departamento.descripcion)
        self.assertEqual(cambio.situacion['cargo'], self.cargo.ncargo.descripcion)

    def test_el_historico_ensena_la_situacion_debajo_del_cambio(self):
        # El Alta Inicial guarda la «foto» con el nombre de la unidad de entonces.
        departamento = self.cargo.departamento
        TMovimiento.objects.create(
            aspirante=self.aspirante, contrato=self.contrato, no_expediente=self.contrato.no_expediente,
            fecha_efectiva=self.contrato.fecha_alta, tipo_movimiento='Alta Inicial',
            cargo_anterior='---', cargo_nuevo=self.cargo.ncargo.descripcion,
            unidad_anterior='---', unidad_nueva=departamento.unidad_organizativa.descripcion,
            departamento_anterior='---', departamento_nuevo=departamento.descripcion,
            tipo_contrato_nuevo='Indeterminado', salario_anterior=0, salario_nuevo=4890)
        self.renombrar_unidad('UEB Norte')
        self.client.force_login(self.admin)
        datos = self.client.get(reverse('historico_trabajador', args=[self.aspirante.pk])).json()['data']
        posicion = next(i for i, d in enumerate(datos) if d.get('es_cambio_externo'))
        situacion = datos[posicion + 1]
        self.assertTrue(situacion.get('es_situacion'))
        self.assertEqual(situacion['evento'], 'Actualizado por cambio externo')
        self.assertEqual(situacion['unidad'], 'UEB Norte')
        alta = datos[0]
        # Mismas fechas que el movimiento al que afecta.
        self.assertEqual((situacion['fecha_inicio_str'], situacion['fecha_fin']),
                         (alta['fecha_inicio_str'], alta['fecha_fin']))
        # Sin cambios externos a la vista, el alta enseña la situación final.
        self.assertEqual(alta['final']['unidad'], 'UEB Norte')
        self.assertIn('departamento', alta)
        # Y sabe qué dato cambió respecto al movimiento, para marcarlo.
        cambio = alta['cambios_final']['unidad']
        self.assertEqual((cambio['despues'], cambio['veces']), ('UEB Norte', 1))
        self.assertNotIn('cargo', alta['cambios_final'])

    def test_el_pdf_sin_cambios_externos_muestra_la_situacion_final(self):
        self.renombrar_unidad('UEB Norte')
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('exportar_historico_pdf', args=[self.aspirante.pk]) + '?externos=0')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')


class SinSalarioEnLaListaTests(tests_cambios_externos.BaseCambios):
    """Un contrato sin escala para su combinación muestra «Sin salario», nunca «None»."""

    def test_la_lista_de_contratos_dice_sin_salario(self):
        from unittest import mock

        from .models import CAlta
        self.client.force_login(self.admin)
        with mock.patch.object(CAlta, 'calcular_salario_escala', lambda contrato: None):
            respuesta = self.client.get(reverse('search_contrato'), HTTP_HX_REQUEST='true')
        texto = respuesta.content.decode()
        self.assertIn('Sin salario', texto)
        self.assertNotIn('>None<', texto)
