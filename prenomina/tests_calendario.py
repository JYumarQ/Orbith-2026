"""Pruebas de Pre-Nómina → Calendario.

Fichero aparte de `tests.py` porque ese ya cubre el reporte de pago y pasa de
las 2.000 líneas; el descubrimiento por defecto de Django (`test*.py`) recoge
los dos igual.

Se prueban las reglas que, si se rompen, corrompen datos o dinero:
el aislamiento entre usuarios, la intocabilidad de lo cerrado, la precisión
decimal y la sincronización con el cierre del reporte. Lo cosmético no se
prueba aquí.
"""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from cierres.periodos import Periodo
from usuarios.models import CustomUser

from . import servicios_calendario as sc
from .models import Calendario, CalendarioPago
from .servicios import ErrorDePreNomina
# `BasePreNomina` monta unidad, departamento, cargo y contrato activo. Se
# reutiliza para la prueba de sincronización con el cierre del reporte, que es
# lo único de aquí que necesita un reporte de verdad.
from .tests import BasePreNomina


class BaseCalendario(TestCase):
    """Dos usuarios con catálogos propios: casi todo aquí es sobre aislarlos."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = CustomUser.objects.create_user(
            username='mod_cal', password='x', es_moderador=True)
        cls.otro = CustomUser.objects.create_user(
            username='mod_cal_otro', password='x', es_moderador=True)
        cls.observador = CustomUser.objects.create_user(
            username='obs_cal', password='x', es_observador=True)

    def calendario(self, usuario=None, codigo=1, descripcion='Jornada Normal',
                   activo=True):
        return sc.crear_calendario(usuario or self.usuario, codigo=codigo,
                                   descripcion=descripcion, activo=activo)

    def periodo(self, usuario=None, anno=2026, mes=9):
        return sc.crear_periodo(usuario or self.usuario, anno=anno, mes=mes)


class ValidacionesDelCalendario(BaseCalendario):

    def test_el_codigo_es_obligatorio_y_numerico(self):
        for valor in ('', '   ', '01-A', 'uno'):
            with self.subTest(codigo=valor):
                with self.assertRaises(ErrorDePreNomina):
                    self.calendario(codigo=valor)

    def test_el_codigo_no_se_repite_dentro_del_mismo_usuario(self):
        self.calendario(codigo=1)
        with self.assertRaises(ErrorDePreNomina) as caja:
            self.calendario(codigo=1, descripcion='Otra')
        self.assertIn('01', str(caja.exception))

    def test_dos_usuarios_pueden_tener_el_mismo_codigo(self):
        """Son catálogos personales: el 01 de uno no le quita el 01 al otro."""
        self.calendario(codigo=1)
        self.calendario(usuario=self.otro, codigo=1, descripcion='Suya')
        self.assertEqual(Calendario.objects.filter(codigo=1).count(), 2)

    def test_la_descripcion_es_obligatoria_y_cabe_en_veinte(self):
        with self.assertRaises(ErrorDePreNomina):
            self.calendario(descripcion='')
        with self.assertRaises(ErrorDePreNomina):
            self.calendario(descripcion='x' * 21)

    def test_no_se_edita_el_calendario_de_otro(self):
        ajeno = self.calendario(usuario=self.otro)
        with self.assertRaises(ErrorDePreNomina):
            sc.editar_calendario(ajeno, self.usuario, codigo=9,
                                 descripcion='Robado', activo=True)


class EliminacionDelCalendario(BaseCalendario):

    def test_un_calendario_sin_usar_se_elimina(self):
        calendario = self.calendario()
        sc.eliminar_calendario(calendario, self.usuario)
        self.assertFalse(Calendario.objects.filter(pk=calendario.pk).exists())

    def test_un_calendario_usado_no_se_elimina_aunque_el_periodo_este_abierto(self):
        calendario = self.calendario()
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])

        with self.assertRaises(ErrorDePreNomina) as caja:
            sc.eliminar_calendario(calendario, self.usuario)
        self.assertIn('Septiembre 2026', str(caja.exception))
        self.assertIn('Inactivo', str(caja.exception))
        self.assertTrue(Calendario.objects.filter(pk=calendario.pk).exists())

    def test_tampoco_se_elimina_si_el_periodo_esta_cerrado(self):
        calendario = self.calendario()
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])
        sc.cerrar_periodo(self.usuario, anno=2026, mes=9)

        with self.assertRaises(ErrorDePreNomina):
            sc.eliminar_calendario(calendario, self.usuario)

    def test_marcarlo_inactivo_es_la_alternativa(self):
        calendario = self.calendario()
        sc.marcar_inactivo(calendario, self.usuario)
        calendario.refresh_from_db()
        self.assertFalse(calendario.activo)


class DecisionDeHistorico(BaseCalendario):
    """La regla más delicada: renombrar sin reescribir el pasado, o al revés."""

    def preparar(self):
        calendario = self.calendario(descripcion='Jornada Normal')
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])
        return calendario, periodo, periodo.detalles.get()

    def test_mantener_historico_deja_la_descripcion_antigua(self):
        calendario, _, detalle = self.preparar()
        sc.editar_calendario(calendario, self.usuario, codigo=1,
                             descripcion='Jornada Larga', activo=True,
                             actualizar_historico=False)
        calendario.refresh_from_db(); detalle.refresh_from_db()
        self.assertEqual(calendario.descripcion, 'Jornada Larga')
        self.assertEqual(detalle.descripcion_historica, 'Jornada Normal')

    def test_actualizar_historico_propaga_a_los_periodos(self):
        calendario, _, detalle = self.preparar()
        sc.editar_calendario(calendario, self.usuario, codigo=1,
                             descripcion='Jornada Larga', activo=True,
                             actualizar_historico=True)
        detalle.refresh_from_db()
        self.assertEqual(detalle.descripcion_historica, 'Jornada Larga')

    def test_propaga_incluso_a_periodos_cerrados(self):
        calendario, _, detalle = self.preparar()
        sc.cerrar_periodo(self.usuario, anno=2026, mes=9)
        sc.editar_calendario(calendario, self.usuario, codigo=1,
                             descripcion='Jornada Larga', activo=True,
                             actualizar_historico=True)
        detalle.refresh_from_db()
        self.assertEqual(detalle.descripcion_historica, 'Jornada Larga')

    def test_la_decision_nunca_toca_el_codigo_ni_las_horas(self):
        calendario, _, detalle = self.preparar()
        sc.guardar_horas(detalle, self.usuario, horas_q1='80', horas_q2='80')
        sc.editar_calendario(calendario, self.usuario, codigo=5,
                             descripcion='Otro Nombre', activo=True,
                             actualizar_historico=True)
        detalle.refresh_from_db()
        self.assertEqual(detalle.codigo_historico, 1)
        self.assertEqual(detalle.horas_q1, Decimal('80.00'))
        self.assertEqual(detalle.horas_q2, Decimal('80.00'))


class ReglasDelPeriodo(BaseCalendario):

    def test_el_primero_puede_ser_cualquier_fecha(self):
        periodo = self.periodo(anno=2025, mes=3)
        self.assertEqual(periodo.etiqueta, 'Marzo 2025')

    def test_no_se_duplica_el_mismo_anno_y_mes(self):
        self.periodo(anno=2026, mes=9)
        with self.assertRaises(ErrorDePreNomina) as caja:
            self.periodo(anno=2026, mes=9)
        self.assertIn('Ya existe', str(caja.exception))

    def test_no_se_crea_uno_anterior_al_ultimo(self):
        self.periodo(anno=2026, mes=9)
        for anno, mes in ((2026, 8), (2025, 12), (2026, 1)):
            with self.subTest(anno=anno, mes=mes):
                with self.assertRaises(ErrorDePreNomina):
                    self.periodo(anno=anno, mes=mes)

    def test_si_se_crea_uno_posterior(self):
        self.periodo(anno=2026, mes=9)
        self.assertEqual(self.periodo(anno=2026, mes=10).mes, 10)
        self.assertEqual(self.periodo(anno=2027, mes=1).anno, 2027)

    def test_el_limite_es_por_usuario(self):
        """El período de otro no bloquea el mío: los calendarios son personales."""
        self.periodo(usuario=self.otro, anno=2027, mes=12)
        self.assertEqual(self.periodo(anno=2026, mes=1).anno, 2026)


class SeleccionDeCalendarios(BaseCalendario):

    def test_solo_entran_los_activos(self):
        activo = self.calendario(codigo=1)
        inactivo = self.calendario(codigo=2, descripcion='Retirada', activo=False)
        periodo = self.periodo()

        sc.seleccionar_calendarios(periodo, self.usuario, [activo.pk, inactivo.pk])
        self.assertEqual(
            list(periodo.detalles.values_list('calendario_id', flat=True)),
            [activo.pk])

    def test_la_linea_congela_codigo_y_descripcion(self):
        calendario = self.calendario(codigo=3, descripcion='Turno Noche')
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])

        detalle = periodo.detalles.get()
        self.assertEqual(detalle.codigo_historico, 3)
        self.assertEqual(detalle.descripcion_historica, 'Turno Noche')

    def test_repetir_la_seleccion_no_duplica(self):
        calendario = self.calendario()
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])
        self.assertEqual(periodo.detalles.count(), 1)

    def test_no_se_cuelan_calendarios_de_otro_usuario(self):
        ajeno = self.calendario(usuario=self.otro)
        periodo = self.periodo()
        with self.assertRaises(ErrorDePreNomina):
            sc.seleccionar_calendarios(periodo, self.usuario, [ajeno.pk])


class HorasYPrecision(BaseCalendario):

    def detalle(self):
        calendario = self.calendario()
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])
        return periodo.detalles.get()

    def test_los_decimales_se_conservan(self):
        """El criterio de aceptación: 80.5 + 88.25 = 168.75, sin pérdida."""
        detalle = self.detalle()
        sc.guardar_horas(detalle, self.usuario, horas_q1='80.5', horas_q2='88.25')
        detalle.refresh_from_db()
        self.assertEqual(detalle.horas_q1, Decimal('80.50'))
        self.assertEqual(detalle.horas_q2, Decimal('88.25'))
        self.assertEqual(detalle.horas_mes, Decimal('168.75'))

    def test_se_admite_la_coma_como_separador(self):
        detalle = self.detalle()
        sc.guardar_horas(detalle, self.usuario, horas_q1='60,5')
        detalle.refresh_from_db()
        self.assertEqual(detalle.horas_q1, Decimal('60.50'))

    def test_no_se_admiten_negativas_ni_texto(self):
        detalle = self.detalle()
        for valor in ('-1', '-0.5', 'ocho', '8 horas'):
            with self.subTest(valor=valor):
                with self.assertRaises(ErrorDePreNomina):
                    sc.guardar_horas(detalle, self.usuario, horas_q1=valor)

    def test_editar_una_quincena_no_toca_la_otra(self):
        detalle = self.detalle()
        sc.guardar_horas(detalle, self.usuario, horas_q1='80', horas_q2='70')
        sc.guardar_horas(detalle, self.usuario, horas_q1='90')
        detalle.refresh_from_db()
        self.assertEqual(detalle.horas_q1, Decimal('90.00'))
        self.assertEqual(detalle.horas_q2, Decimal('70.00'))

    def test_horas_mes_no_se_persiste(self):
        """Es una propiedad calculada: no hay columna que pueda discrepar."""
        campos = {campo.name for campo in type(self.detalle())._meta.get_fields()}
        self.assertNotIn('horas_mes', campos)


class PeriodoCerrado(BaseCalendario):

    def preparar(self):
        calendario = self.calendario()
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])
        detalle = periodo.detalles.get()
        sc.guardar_horas(detalle, self.usuario, horas_q1='80', horas_q2='80')
        sc.cerrar_periodo(self.usuario, anno=2026, mes=9, cerrado_por=self.usuario)
        periodo.refresh_from_db()
        return periodo, detalle

    def test_no_admite_editar_las_horas(self):
        periodo, detalle = self.preparar()
        with self.assertRaises(ErrorDePreNomina) as caja:
            sc.guardar_horas(detalle, self.usuario, horas_q1='99')
        self.assertIn('cerrado', str(caja.exception).lower())
        detalle.refresh_from_db()
        self.assertEqual(detalle.horas_q1, Decimal('80.00'))

    def test_no_admite_eliminarse(self):
        periodo, _ = self.preparar()
        with self.assertRaises(ErrorDePreNomina):
            sc.eliminar_periodo(periodo, self.usuario)
        self.assertTrue(CalendarioPago.objects.filter(pk=periodo.pk).exists())

    def test_no_admite_anadir_ni_quitar_lineas(self):
        periodo, detalle = self.preparar()
        otro = self.calendario(codigo=2, descripcion='Otra')
        with self.assertRaises(ErrorDePreNomina):
            sc.seleccionar_calendarios(periodo, self.usuario, [otro.pk])
        with self.assertRaises(ErrorDePreNomina):
            sc.quitar_detalle(detalle, self.usuario)

    def test_guarda_quien_y_cuando_cerro(self):
        periodo, _ = self.preparar()
        self.assertTrue(periodo.cerrado)
        self.assertIsNotNone(periodo.fecha_cierre)
        self.assertEqual(periodo.cerrado_por_nombre, 'mod_cal')

    def test_reabrir_lo_devuelve_a_editable(self):
        periodo, detalle = self.preparar()
        sc.reabrir_periodo(self.usuario, anno=2026, mes=9)
        periodo.refresh_from_db()
        self.assertFalse(periodo.cerrado)
        self.assertIsNone(periodo.fecha_cierre)
        sc.guardar_horas(detalle, self.usuario, horas_q1='99')
        detalle.refresh_from_db()
        self.assertEqual(detalle.horas_q1, Decimal('99.00'))

    def test_cerrar_un_periodo_inexistente_no_falla(self):
        """El reporte puede cerrarse sin que exista calendario de ese mes."""
        self.assertIsNone(sc.cerrar_periodo(self.usuario, anno=2030, mes=5))

    def test_cerrar_dos_veces_es_idempotente(self):
        periodo, _ = self.preparar()
        primera = periodo.fecha_cierre
        sc.cerrar_periodo(self.usuario, anno=2026, mes=9)
        periodo.refresh_from_db()
        self.assertEqual(periodo.fecha_cierre, primera)


class AccesoALasVistas(BaseCalendario):
    """El alcance personal se comprueba también por HTTP, no solo en servicios."""

    def setUp(self):
        self.client = Client()

    def test_el_observador_no_entra(self):
        self.client.force_login(self.observador)
        self.assertEqual(
            self.client.get(reverse('prenomina:calendario')).status_code, 403)

    def test_el_moderador_entra(self):
        self.client.force_login(self.usuario)
        self.assertEqual(
            self.client.get(reverse('prenomina:calendario')).status_code, 200)

    def test_no_se_ve_el_catalogo_de_otro(self):
        self.calendario(usuario=self.otro, descripcion='Secreta')
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('prenomina:tarjeta_calendarios'))
        self.assertNotContains(respuesta, 'Secreta')

    def test_editar_el_calendario_de_otro_da_404_y_no_403(self):
        """404, no 403: un 403 confirmaría que ese identificador existe."""
        ajeno = self.calendario(usuario=self.otro)
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            reverse('prenomina:eliminar_calendario', args=[ajeno.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 404)
        self.assertTrue(Calendario.objects.filter(pk=ajeno.pk).exists())

    def test_eliminar_el_periodo_de_otro_da_404(self):
        ajeno = self.periodo(usuario=self.otro)
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            reverse('prenomina:eliminar_periodo', args=[ajeno.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 404)
        self.assertTrue(CalendarioPago.objects.filter(pk=ajeno.pk).exists())

    def test_al_cambiar_la_descripcion_de_uno_usado_se_pregunta_antes(self):
        calendario = self.calendario(descripcion='Jornada Normal')
        periodo = self.periodo()
        sc.seleccionar_calendarios(periodo, self.usuario, [calendario.pk])

        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            reverse('prenomina:editar_calendario', args=[calendario.pk]),
            {'codigo': '1', 'descripcion': 'Jornada Larga', 'activo': '1'},
            HTTP_HX_REQUEST='true')

        # No guarda todavía: devuelve el modal de decisión.
        self.assertContains(respuesta, 'Mantener histórico')
        calendario.refresh_from_db()
        self.assertEqual(calendario.descripcion, 'Jornada Normal')

    def test_sin_periodos_previos_no_se_pregunta_nada(self):
        calendario = self.calendario(descripcion='Jornada Normal')
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            reverse('prenomina:editar_calendario', args=[calendario.pk]),
            {'codigo': '1', 'descripcion': 'Jornada Larga', 'activo': '1'},
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        calendario.refresh_from_db()
        self.assertEqual(calendario.descripcion, 'Jornada Larga')


class SincronizacionConElReporte(BasePreNomina):
    """Cerrar el reporte desde Gestión de Reportes de Pagos cierra su calendario.

    Es la regla que une los dos módulos, y la única que no se puede comprobar
    llamando solo a `servicios_calendario`: hay que cerrar un reporte de verdad.
    Hereda de `tests.BasePreNomina` para reutilizar su escenario completo
    (unidad, departamento, cargo y un contrato activo) y su método `crear()`,
    igual que hacen las demás clases de `tests.py`.
    """

    def test_al_cerrar_el_reporte_se_cierra_el_calendario_de_ese_mes(self):
        from cierres.periodos import Periodo
        from . import servicios

        # `crear()` ya monta el Calendario de Pago del período (las horas del mes
        # salen de ahí), así que aquí solo hay que recuperarlo.
        reporte = self.crear(periodo=Periodo(2026, 7))
        periodo = CalendarioPago.objects.get(
            usuario=self.moderador, anno=2026, mes=7)
        self.assertFalse(periodo.cerrado)

        servicios.cerrar_reporte(reporte, self.moderador)

        periodo.refresh_from_db()
        self.assertTrue(periodo.cerrado)
        self.assertIsNotNone(periodo.fecha_cierre)

    def test_al_reabrir_el_reporte_el_calendario_vuelve_a_editable(self):
        from cierres.periodos import Periodo
        from . import servicios

        # `crear()` ya monta el Calendario de Pago del período (las horas del mes
        # salen de ahí), así que aquí solo hay que recuperarlo.
        reporte = self.crear(periodo=Periodo(2026, 7))
        periodo = CalendarioPago.objects.get(
            usuario=self.moderador, anno=2026, mes=7)
        servicios.cerrar_reporte(reporte, self.moderador)
        servicios.reabrir_reporte(reporte, self.moderador)

        periodo.refresh_from_db()
        self.assertFalse(periodo.cerrado)

    def test_el_cierre_solo_alcanza_al_mes_del_reporte(self):
        """Cerrar julio no puede tocar el calendario de agosto."""
        from cierres.periodos import Periodo
        from . import servicios

        reporte = self.crear(periodo=Periodo(2026, 7))
        julio = CalendarioPago.objects.get(
            usuario=self.moderador, anno=2026, mes=7)
        agosto = sc.crear_periodo(self.moderador, anno=2026, mes=8)

        servicios.cerrar_reporte(reporte, self.moderador)

        julio.refresh_from_db(); agosto.refresh_from_db()
        self.assertTrue(julio.cerrado)
        self.assertFalse(agosto.cerrado)

    def test_el_cierre_no_alcanza_al_calendario_de_otro_usuario(self):
        """Los calendarios son personales: cierra el de quien cierra el reporte."""
        from cierres.periodos import Periodo
        from . import servicios

        reporte = self.crear(periodo=Periodo(2026, 7))
        mio = CalendarioPago.objects.get(usuario=self.moderador, anno=2026, mes=7)
        ajeno = sc.crear_periodo(self.ajeno, anno=2026, mes=7)

        servicios.cerrar_reporte(reporte, self.moderador)

        mio.refresh_from_db(); ajeno.refresh_from_db()
        self.assertTrue(mio.cerrado)
        self.assertFalse(ajeno.cerrado)


class HorasDelMesPorTrabajador(BasePreNomina):
    """Fase 2: el fondo de tiempo sale del calendario de cada trabajador.

    Antes había un único `ReportePago.fondo_tiempo` tecleado a mano para todo el
    reporte. Ahora cada fila trae las horas de SU jornada, congeladas al crearse.
    """

    def test_el_trabajador_congela_las_horas_de_su_jornada(self):
        reporte = self.crear(horas_mes=Decimal('176.00'))
        fila = reporte.trabajadores.get()
        self.assertEqual(fila.horas_mes, Decimal('176.00'))
        self.assertEqual(fila.calendario_codigo, 1)
        self.assertEqual(fila.calendario_descripcion, 'Jornada Normal')

    def test_las_horas_trabajadas_se_calculan_sobre_las_suyas(self):
        """Sin ausencias, las horas trabajadas son las del mes de ESE trabajador.

        Se comprueba en los dos momentos que importan: al crear el reporte (donde
        antes salía 0.00 hasta que alguien configuraba conceptos) y tras el
        recálculo completo que hace el cierre.
        """
        from . import servicios

        reporte = self.crear(horas_mes=Decimal('100.00'))
        fila = reporte.trabajadores.get()
        self.assertEqual(fila.horas_trabajadas, Decimal('100.00'))

        servicios.cerrar_reporte(reporte, self.moderador)
        fila.refresh_from_db()
        self.assertEqual(fila.horas_trabajadas, Decimal('100.00'))

    def test_sin_jornada_asignada_no_se_crea_el_reporte(self):
        """Falla en vez de poner un cero: un cero no se nota hasta la nómina."""
        from . import servicios

        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear(con_calendario=False)
        mensaje = str(caja.exception)
        self.assertIn('horas del mes', mensaje)
        self.assertIn('Ana Pérez Gómez', mensaje)
        self.assertIn('Asignar Calendario', mensaje)

    def test_la_jornada_no_incluida_en_el_periodo_tambien_se_rechaza(self):
        """Tener calendario no basta: tiene que estar en el Calendario de Pago."""
        from . import servicios
        from .models import AsignacionCalendario, Calendario

        suelto = sc.crear_calendario(self.moderador, codigo=9,
                                     descripcion='Suelta')
        sc.crear_periodo(self.moderador, anno=2026, mes=7)   # período sin líneas
        AsignacionCalendario.objects.update_or_create(
            contrato=self.contrato,
            defaults={'calendario': suelto, 'asignado_por': self.moderador})

        with self.assertRaises(servicios.ErrorDePreNomina):
            self.crear(con_calendario=False)

    def test_reasignar_despues_no_reescribe_el_reporte(self):
        """El congelado manda: cambiar la jornada no toca los meses ya montados."""
        from .models import AsignacionCalendario

        reporte = self.crear(horas_mes=Decimal('184.00'))
        otra = sc.crear_calendario(self.moderador, codigo=2, descripcion='Media')

        AsignacionCalendario.objects.update_or_create(
            contrato=self.contrato,
            defaults={'calendario': otra, 'asignado_por': self.moderador})

        fila = reporte.trabajadores.get()
        fila.refresh_from_db()
        self.assertEqual(fila.horas_mes, Decimal('184.00'))
        self.assertEqual(fila.calendario_descripcion, 'Jornada Normal')

    def test_cambiar_las_horas_del_calendario_no_reescribe_el_reporte(self):
        from .models import CalendarioPago

        reporte = self.crear(horas_mes=Decimal('184.00'))
        detalle = (CalendarioPago.objects
                   .get(usuario=self.moderador, anno=2026, mes=7)
                   .detalles.get())
        sc.guardar_horas(detalle, self.moderador, horas_q1='10', horas_q2='10')

        fila = reporte.trabajadores.get()
        fila.refresh_from_db()
        self.assertEqual(fila.horas_mes, Decimal('184.00'))

    def test_la_cabecera_toma_la_jornada_mas_repetida(self):
        """`fondo_tiempo` queda como número de referencia del encabezado."""
        reporte = self.crear(horas_mes=Decimal('176.00'))
        reporte.refresh_from_db()
        self.assertEqual(reporte.fondo_tiempo, Decimal('176.00'))

    def test_no_se_puede_descontar_mas_que_sus_propias_horas(self):
        from . import servicios
        from .models import NClaveAusencia

        reporte = self.crear(horas_mes=Decimal('100.00'))
        NClaveAusencia.objects.create(codigo=12, descripcion='Vacaciones',
                                      resta_horas_mes=True)
        servicios.configurar_conceptos(reporte, self.moderador,
                                       codigos_ausencia=['12'],
                                       codigos_horas=[], codigos_importe=[])
        fila = reporte.trabajadores.get()

        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.guardar_valores(fila.pk, self.moderador,
                                      ausencias={12: '150'}, horas={})
        self.assertIn('100', str(caja.exception))


class ReglasDeSubsanacion(BasePreNomina):
    """Las dos reglas que Subsanación aporta al Calendario.

    Se prueban desde aquí y no desde `subsanacion/tests.py` porque todo el
    escenario que necesitan —contrato activo, calendario, período— ya lo monta
    `BasePreNomina`; repetirlo en el otro módulo sería duplicar el andamiaje.
    """

    def correr(self, codigo):
        from subsanacion.contexto import ContextoAnalisis
        from subsanacion.reglas import obtener_regla
        return list(obtener_regla(codigo).ejecutar(ContextoAnalisis()))

    def modulo_en_uso(self):
        """CAL-101 solo habla si el módulo ya se está usando.

        Crear una jornada cualquiera es lo que activa la regla (ver el
        guardarraíl de estreno), así que las pruebas que esperan un hallazgo
        tienen que llamar a esto primero.
        """
        return sc.crear_calendario(self.moderador, codigo=9,
                                   descripcion='Cualquiera')

    # --- CAL-101: trabajador sin jornada ---------------------------------

    def test_detecta_al_trabajador_activo_sin_jornada(self):
        self.modulo_en_uso()
        hallazgos = self.correr('CAL-101')
        self.assertEqual(len(hallazgos), 1)
        self.assertIn('sin jornada asignada', hallazgos[0].titulo)
        self.assertEqual(hallazgos[0].object_id, str(self.contrato.pk))

    def test_no_lo_detecta_una_vez_asignado(self):
        self.preparar_calendario(self.moderador, Periodo(2026, 7))
        self.assertEqual(self.correr('CAL-101'), [])

    def test_el_hallazgo_apunta_a_su_unidad_para_el_alcance_por_rol(self):
        self.modulo_en_uso()
        hallazgo = self.correr('CAL-101')[0]
        self.assertEqual(hallazgo.unidad_organizativa_id, self.unidad.pk)

    def test_no_dice_nada_mientras_nadie_haya_creado_calendarios(self):
        """Guardarraíl de estreno: sin un solo calendario, el módulo no se usa.

        Sin esto, el primer análisis tras instalar la funcionalidad marcaría a
        toda la plantilla de golpe por algo que nadie ha podido asignar todavía.
        """
        from .models import Calendario

        self.assertFalse(Calendario.objects.exists())
        self.assertEqual(self.correr('CAL-101'), [])

    def test_empieza_a_avisar_en_cuanto_existe_una_jornada(self):
        self.modulo_en_uso()
        self.assertEqual(len(self.correr('CAL-101')), 1)

    def test_un_trabajador_de_baja_no_genera_hallazgo(self):
        self.modulo_en_uso()
        self.aspirante.estado = 'BAJA'
        self.aspirante.save(update_fields=['estado'])
        self.assertEqual(self.correr('CAL-101'), [])

    # --- CAL-102: período sin horas --------------------------------------

    def test_detecta_el_periodo_sin_ninguna_jornada(self):
        sc.crear_periodo(self.moderador, anno=2026, mes=9)
        hallazgos = self.correr('CAL-102')
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].clave_extra, 'sin-lineas')

    def test_detecta_el_periodo_con_todas_las_jornadas_en_cero(self):
        calendario = sc.crear_calendario(self.moderador, codigo=3,
                                         descripcion='Vacía')
        periodo = sc.crear_periodo(self.moderador, anno=2026, mes=9)
        sc.seleccionar_calendarios(periodo, self.moderador, [calendario.pk])

        hallazgos = self.correr('CAL-102')
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].clave_extra, 'en-cero')

    def test_un_periodo_con_horas_no_genera_hallazgo(self):
        calendario = sc.crear_calendario(self.moderador, codigo=3,
                                         descripcion='Con horas')
        periodo = sc.crear_periodo(self.moderador, anno=2026, mes=9)
        sc.seleccionar_calendarios(periodo, self.moderador, [calendario.pk])
        sc.guardar_horas(periodo.detalles.get(), self.moderador,
                         horas_q1='92', horas_q2='92')
        self.assertEqual(self.correr('CAL-102'), [])

    def test_los_periodos_cerrados_se_ignoran(self):
        """Un cerrado es histórico: señalarlo sería pedir algo imposible."""
        sc.crear_periodo(self.moderador, anno=2026, mes=9)
        sc.cerrar_periodo(self.moderador, anno=2026, mes=9)
        self.assertEqual(self.correr('CAL-102'), [])


class BorradoDeCalendarioAsignado(BasePreNomina):
    """Un calendario asignado a trabajadores no se borra: la FK es PROTECT.

    Sin la comprobación explícita, el borrado reventaría con un `ProtectedError`
    crudo —error 500— en vez de con una explicación en español.
    """

    def test_no_se_elimina_si_lo_tienen_trabajadores(self):
        from .models import Calendario

        self.preparar_calendario(self.moderador, Periodo(2026, 7))
        calendario = Calendario.objects.get(usuario=self.moderador, codigo=1)

        with self.assertRaises(ErrorDePreNomina) as caja:
            sc.eliminar_calendario(calendario, self.moderador)

        mensaje = str(caja.exception)
        self.assertIn('asignado', mensaje)
        self.assertIn('Inactivo', mensaje)
        self.assertTrue(Calendario.objects.filter(pk=calendario.pk).exists())
