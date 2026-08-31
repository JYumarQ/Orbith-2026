"""Pruebas de Pre-Nómina → Mis Plantillas.

Se centran en lo que, si se rompe, corrompe datos o dinero: el aislamiento entre
usuarios, que editar una plantilla no toque un reporte ya creado, las reglas de
duplicado y que una plantilla usada no se pueda borrar.

Todas las validaciones se prueban **contra el servicio y contra la vista**: el
requisito es explícito en que no debe poder saltárselas nadie manipulando el
formulario, así que probar solo la pantalla no bastaría.
"""

from decimal import Decimal

from django.test import Client
from django.urls import reverse

from cierres.periodos import Periodo

from . import servicios, servicios_plantilla as sp
from .models import (NClaveAusencia, NPagoHoras, NPagoImporte, PlantillaReporte,
                     TipoValorImporte)
from .servicios import ErrorDePreNomina
from .tests import BasePreNomina


class BasePlantillas(BasePreNomina):
    """Escenario con conceptos reales de los tres grupos.

    Se montan aquí y no en `BasePreNomina` para no cambiar el coste de las
    pruebas del reporte, que no los necesitan.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.h_extra = NPagoHoras.objects.create(codigo=2, descripcion='Horas Extra')
        cls.h_promedio = NPagoHoras.objects.create(
            codigo=5, descripcion='Salario Promedio')

        cls.a_vacaciones = NClaveAusencia.objects.create(
            codigo=12, descripcion='Vacaciones', resta_horas_mes=True)
        # Alimenta a `h_promedio`: es la relación que obliga a llevar también el
        # concepto por horas.
        cls.a_licencia = NClaveAusencia.objects.create(
            codigo=19, descripcion='Licencia', resta_horas_mes=True,
            relacionado_con=cls.h_promedio)

        cls.i_fijo = NPagoImporte.objects.create(
            codigo=30, descripcion='Estímulo', tipo_valor=TipoValorImporte.IMPORTE,
            importe_fijo=Decimal('100'))
        # Automático: entra solo cuando se elige `h_extra`.
        cls.i_extra = NPagoImporte.objects.create(
            codigo=31, descripcion='Importe Extra',
            tipo_valor=TipoValorImporte.FORMULA,
            formula='{{horas}} * {{tarifa_horaria}}',
            relacionado_con=cls.h_extra)

    def plantilla(self, usuario=None, descripcion='Base', ausencias=(12,),
                  horas=(2,), importes=()):
        return sp.crear_plantilla(
            usuario or self.moderador, descripcion=descripcion,
            codigos_ausencia=ausencias, codigos_horas=horas,
            codigos_importe=importes)


class ValidacionesDeLaPlantilla(BasePlantillas):

    def test_la_descripcion_es_obligatoria(self):
        for valor in ('', '   ', None):
            with self.subTest(descripcion=valor):
                with self.assertRaises(ErrorDePreNomina):
                    self.plantilla(descripcion=valor)

    def test_la_descripcion_no_pasa_de_treinta_caracteres(self):
        with self.assertRaises(ErrorDePreNomina) as caja:
            self.plantilla(descripcion='x' * 31)
        self.assertIn('30', str(caja.exception))

    def test_la_descripcion_no_se_repite_en_el_mismo_usuario(self):
        self.plantilla(descripcion='Oficina')
        with self.assertRaises(ErrorDePreNomina):
            self.plantilla(descripcion='Oficina')

    def test_la_comparacion_de_descripcion_ignora_mayusculas(self):
        self.plantilla(descripcion='Oficina')
        with self.assertRaises(ErrorDePreNomina):
            self.plantilla(descripcion='OFICINA')

    def test_dos_usuarios_pueden_usar_la_misma_descripcion(self):
        """Son catálogos personales: el «Oficina» de uno no bloquea al otro."""
        self.plantilla(descripcion='Oficina')
        self.plantilla(usuario=self.ajeno, descripcion='Oficina')
        self.assertEqual(
            PlantillaReporte.objects.filter(descripcion='Oficina').count(), 2)

    def test_no_se_guarda_una_plantilla_sin_conceptos(self):
        with self.assertRaises(ErrorDePreNomina) as caja:
            self.plantilla(ausencias=(), horas=(), importes=())
        self.assertEqual(str(caja.exception), sp.MENSAJE_SIN_CONCEPTOS)

    def test_una_ausencia_exige_el_concepto_por_horas_que_alimenta(self):
        """Misma regla de coherencia que impone el reporte, pero antes."""
        with self.assertRaises(ErrorDePreNomina) as caja:
            self.plantilla(ausencias=(19,), horas=())
        self.assertIn('Salario Promedio', str(caja.exception))

    def test_un_codigo_inexistente_se_rechaza(self):
        with self.assertRaises(ErrorDePreNomina):
            self.plantilla(horas=(999,))

    def test_un_codigo_que_no_es_numero_se_rechaza(self):
        with self.assertRaises(ErrorDePreNomina):
            self.plantilla(horas=('; DROP TABLE',))

    def test_los_importes_automaticos_no_se_guardan_en_la_plantilla(self):
        """Entran solos al aplicarla: guardarlos duplicaría esa regla."""
        plantilla = self.plantilla(horas=(2,), importes=(31,))
        self.assertEqual(list(plantilla.pagos_importe.all()), [])
        self.assertIn(self.h_extra, plantilla.pagos_horas.all())


class EdicionDeLaPlantilla(BasePlantillas):

    def test_se_puede_cambiar_solo_la_descripcion(self):
        plantilla = self.plantilla(descripcion='Antes')
        antes = plantilla.codigos()

        sp.editar_plantilla(plantilla, self.moderador, descripcion='Después',
                            codigos_ausencia=(12,), codigos_horas=(2,))

        plantilla.refresh_from_db()
        self.assertEqual(plantilla.descripcion, 'Después')
        self.assertEqual(plantilla.codigos(), antes)

    def test_se_puede_cambiar_solo_los_conceptos(self):
        plantilla = self.plantilla(descripcion='Igual')
        sp.editar_plantilla(plantilla, self.moderador, descripcion='Igual',
                            codigos_ausencia=(), codigos_horas=(2, 5))

        plantilla.refresh_from_db()
        self.assertEqual(plantilla.descripcion, 'Igual')
        self.assertEqual(plantilla.codigos(), (set(), {2, 5}, set()))

    def test_editar_no_exige_que_cambie_nada(self):
        """La regla de «cambia las dos cosas» es exclusiva de duplicar."""
        plantilla = self.plantilla(descripcion='Igual')
        sp.editar_plantilla(plantilla, self.moderador, descripcion='Igual',
                            codigos_ausencia=(12,), codigos_horas=(2,))
        plantilla.refresh_from_db()
        self.assertEqual(plantilla.descripcion, 'Igual')

    def test_no_se_edita_la_plantilla_de_otro(self):
        ajena = self.plantilla(usuario=self.ajeno, descripcion='Suya')
        with self.assertRaises(ErrorDePreNomina):
            sp.editar_plantilla(ajena, self.moderador, descripcion='Robada',
                                codigos_horas=(2,))

    def test_editarla_sigue_exigiendo_al_menos_un_concepto(self):
        plantilla = self.plantilla()
        with self.assertRaises(ErrorDePreNomina):
            sp.editar_plantilla(plantilla, self.moderador, descripcion='Vacía',
                                codigos_ausencia=(), codigos_horas=(),
                                codigos_importe=())


class DuplicadoDeLaPlantilla(BasePlantillas):
    """Los cinco casos del requisito, sobre la misma función que valida al guardar."""

    def setUp(self):
        self.original = self.plantilla(descripcion='Original',
                                       ausencias=(12,), horas=(2,))

    def test_sin_cambiar_nada_pide_las_dos_cosas(self):
        aviso = sp.comprobar_duplicado(
            self.original, 'Original', ({12}, {2}, set()))
        self.assertEqual(aviso, sp.MENSAJE_DUPLICAR_TODO)

    def test_cambiando_solo_la_descripcion_pide_los_conceptos(self):
        aviso = sp.comprobar_duplicado(
            self.original, 'Otra', ({12}, {2}, set()))
        self.assertEqual(aviso, sp.MENSAJE_DUPLICAR_CONCEPTOS)

    def test_cambiando_solo_los_conceptos_pide_la_descripcion(self):
        aviso = sp.comprobar_duplicado(
            self.original, 'Original', ({12}, {2, 5}, set()))
        self.assertEqual(aviso, sp.MENSAJE_DUPLICAR_DESCRIPCION)

    def test_cambiando_ambas_cosas_no_hay_aviso(self):
        aviso = sp.comprobar_duplicado(
            self.original, 'Otra', ({12}, {2, 5}, set()))
        self.assertIsNone(aviso)

    def test_quedarse_sin_conceptos_manda_sobre_todo_lo_demas(self):
        """Aunque cambie la descripción: una plantilla vacía nunca se guarda."""
        aviso = sp.comprobar_duplicado(self.original, 'Otra', (set(), set(), set()))
        self.assertEqual(aviso, sp.MENSAJE_SIN_CONCEPTOS)

    def test_el_backend_rechaza_un_duplicado_sin_cambios(self):
        with self.assertRaises(ErrorDePreNomina):
            sp.duplicar_plantilla(self.original, self.moderador,
                                  descripcion='Original',
                                  codigos_ausencia=(12,), codigos_horas=(2,))

    def test_un_duplicado_valido_crea_una_plantilla_independiente(self):
        copia = sp.duplicar_plantilla(
            self.original, self.moderador, descripcion='Copia',
            codigos_ausencia=(12,), codigos_horas=(2, 5))

        self.assertNotEqual(copia.pk, self.original.pk)
        self.assertEqual(copia.codigos(), ({12}, {2, 5}, set()))
        # La original no se toca.
        self.original.refresh_from_db()
        self.assertEqual(self.original.codigos(), ({12}, {2}, set()))

    def test_no_se_duplica_la_plantilla_de_otro(self):
        ajena = self.plantilla(usuario=self.ajeno, descripcion='Suya')
        with self.assertRaises(ErrorDePreNomina):
            sp.duplicar_plantilla(ajena, self.moderador, descripcion='Mía',
                                  codigos_horas=(2, 5))


class BorradoDeLaPlantilla(BasePlantillas):

    def test_una_plantilla_sin_usar_se_elimina(self):
        plantilla = self.plantilla()
        sp.eliminar_plantilla(plantilla, self.moderador)
        self.assertFalse(PlantillaReporte.objects.filter(pk=plantilla.pk).exists())

    def test_una_plantilla_usada_no_se_elimina(self):
        plantilla = self.plantilla()
        reporte = self.crear()
        sp.aplicar_a_reporte(reporte, plantilla, self.moderador)

        with self.assertRaises(ErrorDePreNomina) as caja:
            sp.eliminar_plantilla(plantilla, self.moderador)
        self.assertIn('ya se ha utilizado', str(caja.exception))
        self.assertTrue(PlantillaReporte.objects.filter(pk=plantilla.pk).exists())

    def test_tampoco_si_el_reporte_que_la_uso_esta_cerrado(self):
        plantilla = self.plantilla()
        reporte = self.crear()
        sp.aplicar_a_reporte(reporte, plantilla, self.moderador)
        servicios.cerrar_reporte(reporte, self.moderador)

        with self.assertRaises(ErrorDePreNomina):
            sp.eliminar_plantilla(plantilla, self.moderador)


class HistoricoDelReporte(BasePlantillas):
    """La regla fundamental: editar la plantilla no toca ningún reporte."""

    def test_editar_la_plantilla_no_cambia_un_reporte_ya_creado(self):
        plantilla = self.plantilla(ausencias=(12,), horas=(2,))
        reporte = self.crear()
        sp.aplicar_a_reporte(reporte, plantilla, self.moderador)

        antes_ausencias = set(reporte.conceptos_ausencia.values_list('codigo', flat=True))
        antes_horas = set(reporte.conceptos_horas.values_list('codigo', flat=True))

        # La plantilla cambia por completo después de haberse usado.
        sp.editar_plantilla(plantilla, self.moderador, descripcion='Cambiada',
                            codigos_ausencia=(19,), codigos_horas=(5,))

        self.assertEqual(
            set(reporte.conceptos_ausencia.values_list('codigo', flat=True)),
            antes_ausencias)
        self.assertEqual(
            set(reporte.conceptos_horas.values_list('codigo', flat=True)),
            antes_horas)

    def test_el_reporte_guarda_de_que_plantilla_salio(self):
        plantilla = self.plantilla()
        reporte = self.crear()
        sp.aplicar_a_reporte(reporte, plantilla, self.moderador)
        reporte.refresh_from_db()
        self.assertEqual(reporte.plantilla_id, plantilla.pk)

    def test_renombrar_la_plantilla_no_cambia_la_descripcion_congelada(self):
        plantilla = self.plantilla(ausencias=(12,), horas=(2,))
        reporte = self.crear()
        sp.aplicar_a_reporte(reporte, plantilla, self.moderador)

        self.a_vacaciones.descripcion = 'Vacaciones Anuales'
        self.a_vacaciones.save(update_fields=['descripcion'])

        congelada = reporte.conceptos_ausencia.get(codigo=12)
        self.assertEqual(congelada.descripcion, 'Vacaciones')


class PantallaDePlantillas(BasePlantillas):
    """Permisos y comportamiento por HTTP, no solo por servicio."""

    def setUp(self):
        self.client = Client()

    def test_el_observador_no_entra(self):
        self.client.force_login(self.observador)
        self.assertEqual(
            self.client.get(reverse('prenomina:plantillas')).status_code, 403)

    def test_el_moderador_entra(self):
        self.client.force_login(self.moderador)
        self.assertEqual(
            self.client.get(reverse('prenomina:plantillas')).status_code, 200)

    def test_no_se_ven_las_plantillas_de_otro(self):
        self.plantilla(usuario=self.ajeno, descripcion='Secreta')
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('prenomina:lista_plantillas'))
        self.assertNotContains(respuesta, 'Secreta')

    def test_editar_la_de_otro_da_404_y_no_403(self):
        ajena = self.plantilla(usuario=self.ajeno, descripcion='Suya')
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:editar_plantilla', args=[ajena.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 404)

    def test_eliminar_la_de_otro_da_404(self):
        ajena = self.plantilla(usuario=self.ajeno, descripcion='Suya')
        self.client.force_login(self.moderador)
        respuesta = self.client.post(
            reverse('prenomina:eliminar_plantilla', args=[ajena.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 404)
        self.assertTrue(PlantillaReporte.objects.filter(pk=ajena.pk).exists())

    def test_el_observador_no_crea_plantillas_ni_forzando_el_post(self):
        self.client.force_login(self.observador)
        respuesta = self.client.post(
            reverse('prenomina:nueva_plantilla'),
            {'descripcion': 'Colada', 'horas': ['2']}, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(PlantillaReporte.objects.filter(descripcion='Colada').exists())

    def test_el_alta_por_la_pantalla_crea_la_plantilla(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.post(
            reverse('prenomina:nueva_plantilla'),
            {'descripcion': 'Oficina', 'ausencias': ['12'], 'horas': ['2']},
            HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('recargarPlantillas', respuesta['HX-Trigger'])
        plantilla = PlantillaReporte.objects.get(descripcion='Oficina')
        self.assertEqual(plantilla.codigos(), ({12}, {2}, set()))

    def test_una_plantilla_vacia_se_rechaza_aunque_se_fuerce_el_post(self):
        """El requisito es explícito: no basta con deshabilitar el botón."""
        self.client.force_login(self.moderador)
        respuesta = self.client.post(
            reverse('prenomina:nueva_plantilla'), {'descripcion': 'Vacía'},
            HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, sp.MENSAJE_SIN_CONCEPTOS)
        self.assertFalse(PlantillaReporte.objects.filter(descripcion='Vacía').exists())

    def test_un_duplicado_sin_cambios_se_rechaza_aunque_se_fuerce_el_post(self):
        original = self.plantilla(descripcion='Original', ausencias=(12,), horas=(2,))
        self.client.force_login(self.moderador)
        respuesta = self.client.post(
            reverse('prenomina:duplicar_plantilla', args=[original.pk]),
            {'descripcion': 'Original', 'ausencias': ['12'], 'horas': ['2']},
            HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(PlantillaReporte.objects.count(), 1)

    def test_la_validacion_en_vivo_devuelve_el_boton_deshabilitado(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:validar_plantilla'),
            {'modo': 'crear', 'descripcion': 'Algo'}, HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, sp.MENSAJE_SIN_CONCEPTOS)
        self.assertContains(respuesta, 'disabled')

    def test_la_validacion_en_vivo_habilita_el_boton_con_conceptos(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:validar_plantilla'),
            {'modo': 'crear', 'descripcion': 'Algo', 'horas': ['2']},
            HTTP_HX_REQUEST='true')
        self.assertNotContains(respuesta, 'disabled')

    def test_la_vista_previa_ensena_las_columnas_sin_trabajadores(self):
        plantilla = self.plantilla(ausencias=(12,), horas=(2,))
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:previa_plantilla', args=[plantilla.pk]))

        self.assertContains(respuesta, 'Vacaciones')
        self.assertContains(respuesta, 'Horas Extra')
        self.assertContains(respuesta, 'Así quedará la estructura del reporte')

    def test_la_vista_previa_incluye_los_importes_automaticos(self):
        """Entran solos al aplicarla, así que la previa debe enseñarlos."""
        plantilla = self.plantilla(ausencias=(), horas=(2,))
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:previa_plantilla', args=[plantilla.pk]))
        self.assertContains(respuesta, 'Importe Extra')
