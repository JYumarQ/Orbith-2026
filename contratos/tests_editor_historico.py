"""Motor del editor del histórico (fase 1): leer, aplicar el borrador, encadenar,
comprobar las reglas y resumir. Nada de esto escribe en la base de datos."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from bolsa.models import Aspirante
from nomencladores.models import NCargo, NCausaAltaBaja, NMotivoContrato, NTipoContrato
from strorganizativa.models import CargoPlantilla

from . import editor_historico as eh
from .models import CAlta, CBaja, TMovimiento
from .tests import _crear_departamento_con_cargo, _crear_provincia_municipio


class EditorHistoricoMotorTests(TestCase):
    """Persona con dos contratos: el primero cerrado con una baja y el segundo
    vigente, con un movimiento de nómina en cada uno."""

    @classmethod
    def setUpTestData(cls):
        cls.cargo = _crear_departamento_con_cargo()
        cls.otro_cargo = CargoPlantilla.objects.create(
            ncargo=NCargo.objects.create(descripcion='Especialista A', cat_ocupacional='TEC',
                                         grupo_escala=cls.cargo.ncargo.grupo_escala, salario_basico=5000),
            departamento=cls.cargo.departamento, cant_aprobada=5, orden_informe=2)
        provincia, municipio = _crear_provincia_municipio()
        cls.indeterminado = NTipoContrato.objects.create(descripcion='Indeterminado', requiere_motivo=False)
        cls.determinado = NTipoContrato.objects.create(descripcion='Determinado', requiere_motivo=True)
        cls.motivo = NMotivoContrato.objects.create(descripcion='Sustitución', tipo_contrato=cls.determinado)
        cls.causa = NCausaAltaBaja.objects.create(descripcion='Renuncia')
        cls.persona = Aspirante.objects.create(
            nivel_educ='SA', nombre='Juan', papellido='Pérez', sapellido='Gómez',
            doc_identidad='80010114007', estado='ACTIVO', sexo='M', raza='BL',
            provincia=provincia, municipio=municipio)
        hoy = timezone.localdate()
        cls.f = {n: hoy - timedelta(days=d) for n, d in
                 (('alta1', 1000), ('mov1', 900), ('baja1', 800), ('alta2', 500), ('mov2', 300))}

        def mov(tipo, fecha, antes, despues, salario_antes, salario_despues, contrato=None):
            return TMovimiento.objects.create(
                aspirante=cls.persona, contrato=contrato, no_expediente='01410', fecha_efectiva=fecha,
                tipo_movimiento=tipo, cargo_anterior=antes, cargo_nuevo=despues,
                salario_anterior=salario_antes, salario_nuevo=salario_despues,
                unidad_anterior='---' if antes == '---' else 'UEB Central',
                unidad_nueva='---' if despues == '---' else 'UEB Central',
                departamento_anterior='---' if antes == '---' else 'Contabilidad',
                departamento_nuevo='---' if despues == '---' else 'Contabilidad',
                tipo_contrato_anterior='---' if antes == '---' else 'Indeterminado',
                tipo_contrato_nuevo='---' if despues == '---' else 'Indeterminado',
                tipo_salario_anterior='---' if antes == '---' else 'Fijo',
                tipo_salario_nuevo='---' if despues == '---' else 'Fijo',
                otros_anterior=0, otros_nuevo=0)

        cls.m_alta1 = mov('Alta Inicial', cls.f['alta1'], '---', 'Especialista B', 0, 4000)
        cls.m_mov1 = mov('Movimiento de Nómina', cls.f['mov1'], 'Especialista B', 'Especialista A', 4000, 4500)
        cls.m_baja1 = mov('Baja', cls.f['baja1'], 'Especialista A', '---', 4500, 0)
        cls.baja = CBaja.objects.create(aspirante=cls.persona, no_expediente='01410', tipo=cls.indeterminado,
                                        cargo=cls.cargo, fecha_alta=cls.f['alta1'], fecha_baja=cls.f['baja1'],
                                        causa_baja=cls.causa)
        cls.contrato = CAlta.objects.create(aspirante=cls.persona, no_expediente='01410',
                                            tipo=cls.indeterminado, cargo=cls.cargo, fecha_alta=cls.f['alta2'])
        TMovimiento.objects.filter(pk__in=[cls.m_alta1.pk, cls.m_mov1.pk]).update(contrato=None)
        cls.m_alta2 = mov('Alta Inicial', cls.f['alta2'], '---', 'Especialista B', 0, 4000, cls.contrato)
        cls.m_mov2 = mov('Movimiento de Nómina', cls.f['mov2'], 'Especialista B', 'Especialista A',
                         4000, 4500, cls.contrato)

    def preparar(self, *cambios):
        return eh.preparar(self.persona, list(cambios))

    # --- Leer -------------------------------------------------------------

    def test_lee_dos_contratos_en_orden_y_enlaza_la_baja(self):
        h = eh.cargar(self.persona)
        self.assertEqual([e.tipo for e in h.eventos], [eh.ALTA, eh.MOV, eh.BAJA, eh.ALTA, eh.MOV])
        self.assertEqual(len(eh.ciclos(h)), 2)
        baja = h.evento('mov:%d' % self.m_baja1.pk)
        self.assertEqual((baja.baja_pk, baja.causa_baja), (self.baja.pk, 'Renuncia'))
        self.assertEqual(h.contrato_pk, self.contrato.pk)
        self.assertEqual(h.anomalias, [])
        self.assertEqual(h.version, eh.cargar(self.persona).version)

    def test_leer_no_escribe_nada(self):
        antes = list(TMovimiento.objects.order_by('pk').values_list('pk', 'salario_nuevo', 'fecha_efectiva'))
        self.preparar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '9999'}})
        self.assertEqual(antes, list(TMovimiento.objects.order_by('pk').values_list(
            'pk', 'salario_nuevo', 'fecha_efectiva')))

    # --- Corregir y encadenar ---------------------------------------------

    def test_corregir_un_movimiento_ajusta_el_antes_del_siguiente(self):
        _, propuesto, errores, res = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '4700.00'}})
        self.assertEqual(errores, [])
        self.assertIn(('Movimiento de Nómina del %s' % self.f['mov1'].strftime('%d/%m/%Y'),
                       'Salario', '4 500,00', '4 700,00'), res['cambios'])
        baja = propuesto.evento('mov:%d' % self.m_baja1.pk)
        self.assertEqual(baja.antes['salario'], Decimal('4700.00'))
        self.assertTrue(any('Baja' in a for a in res['ajustes']))

    def test_elegir_el_cargo_rellena_sus_datos(self):
        _, propuesto, errores, _ = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk, 'campos': {'cargo_id': self.cargo.pk}})
        e = propuesto.evento('mov:%d' % self.m_mov2.pk)
        self.assertEqual((e.estado['cargo'], e.estado['unidad'], e.ids['cargo_id']),
                         ('Especialista B', 'UEB Central', self.cargo.pk))
        self.assertEqual(errores, [])

    def test_un_tipo_sin_motivo_borra_el_motivo(self):
        h = eh.aplicar(eh.cargar(self.persona), [
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk,
             'campos': {'tipo_id': self.determinado.pk, 'motivo_id': self.motivo.pk}},
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk, 'campos': {'tipo_id': self.indeterminado.pk}}])
        e = h.evento('mov:%d' % self.m_mov2.pk)
        self.assertEqual((e.estado['tipo_contrato'], e.estado['motivo']), ('Indeterminado', '---'))

    # --- Reglas de la cronología -----------------------------------------

    def test_dos_eventos_el_mismo_dia_o_futuro_no_valen(self):
        _, _, errores, _ = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'fecha': self.f['alta1']}})
        self.assertTrue(any('el mismo día' in e for e in errores))
        manana = timezone.localdate() + timedelta(days=1)
        _, _, errores, _ = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk, 'campos': {'fecha': manana}})
        self.assertTrue(any('fecha futura' in e for e in errores))

    def test_mover_un_movimiento_detras_de_la_baja_no_vale(self):
        _, _, errores, _ = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk,
             'campos': {'fecha': self.f['baja1'] + timedelta(days=10)}})
        self.assertTrue(any('después de una baja' in e for e in errores))

    def test_insertar_entre_dos_eventos(self):
        entre = self.f['alta2'] + timedelta(days=50)
        _, propuesto, errores, res = self.preparar(
            {'op': 'insertar', 'tras': 'mov:%d' % self.m_alta2.pk,
             'campos': {'fecha': entre, 'salario': '4200'}})
        self.assertEqual(errores, [])
        nuevo = [e for e in propuesto.eventos if e.nuevo][0]
        self.assertEqual((nuevo.fecha, nuevo.antes['cargo'], nuevo.estado['salario']),
                         (entre, 'Especialista B', Decimal('4200.00')))
        # El movimiento siguiente parte ahora del insertado.
        self.assertEqual(propuesto.evento('mov:%d' % self.m_mov2.pk).antes['salario'], Decimal('4200.00'))
        self.assertTrue(any(c[1] == 'Nuevo movimiento' for c in res['cambios']))

    def test_no_se_inserta_detras_de_una_baja(self):
        with self.assertRaises(eh.ErrorDeBorrador):
            self.preparar({'op': 'insertar', 'tras': 'mov:%d' % self.m_baja1.pk,
                           'campos': {'fecha': self.f['baja1'] + timedelta(days=5)}})

    # --- Borrar -------------------------------------------------------------

    def test_un_alta_con_mas_eventos_no_se_borra(self):
        _, _, errores, _ = self.preparar({'op': 'borrar', 'evento': 'mov:%d' % self.m_alta2.pk})
        self.assertTrue(any('no se puede borrar mientras su contrato' in e for e in errores))

    def test_borrar_la_recontratacion_entera_deja_a_la_persona_de_baja(self):
        _, _, errores, res = self.preparar(
            {'op': 'borrar', 'evento': 'mov:%d' % self.m_mov2.pk},
            {'op': 'borrar', 'evento': 'mov:%d' % self.m_alta2.pk})
        self.assertEqual(errores, [])
        self.assertEqual(res['estado_persona'], ('ACTIVO', 'BAJA'))

    def test_borrar_todo_devuelve_a_aspirante(self):
        cambios = [{'op': 'borrar', 'evento': 'mov:%d' % m.pk}
                   for m in (self.m_mov2, self.m_alta2, self.m_mov1)]
        _, _, errores, _ = self.preparar(*cambios, {'op': 'borrar', 'evento': 'mov:%d' % self.m_baja1.pk})
        self.assertTrue(any('no se puede borrar: corrija' in e for e in errores))

    def test_una_baja_no_se_borra_pero_se_corrige(self):
        nueva = self.f['baja1'] - timedelta(days=10)
        _, propuesto, errores, res = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_baja1.pk, 'campos': {'fecha': nueva}})
        self.assertEqual(errores, [])
        self.assertEqual(propuesto.evento('mov:%d' % self.m_baja1.pk).fecha, nueva)
        with self.assertRaises(eh.ErrorDeBorrador):
            eh.aplicar(eh.cargar(self.persona), [
                {'op': 'editar', 'evento': 'mov:%d' % self.m_baja1.pk, 'campos': {'salario': '1'}}])

    def test_un_solo_contrato_borrado_entero_vuelve_a_aspirante(self):
        sola = Aspirante.objects.create(
            nivel_educ='SA', nombre='Ana', papellido='Sol', sapellido='Mar', doc_identidad='80010114008',
            estado='ACTIVO', sexo='F', raza='BL', provincia=self.persona.provincia,
            municipio=self.persona.municipio)
        alta = TMovimiento.objects.create(
            aspirante=sola, no_expediente='01411', fecha_efectiva=self.f['alta2'],
            tipo_movimiento='Alta Inicial', cargo_anterior='---', cargo_nuevo='x',
            salario_anterior=0, salario_nuevo=1)
        _, _, errores, res = eh.preparar(sola, [{'op': 'borrar', 'evento': 'mov:%d' % alta.pk}])
        self.assertEqual(errores, [])
        self.assertEqual(res['estado_persona'], ('ACTIVO', 'ASPIRANTE'))


class EditorHistoricoGuardarTests(EditorHistoricoMotorTests):
    """Fase 2: el guardado escribe todo o nada, con motivo, Auditoría y cambio
    externo, y deja el contrato vigente y la ficha como deben quedar. (Hereda los
    datos de la clase del motor; sus pruebas se repiten aquí, son rápidas.)"""

    def setUp(self):
        from usuarios.models import CustomUser
        self.admin = CustomUser.objects.create_user(username='adm_editor', password='x', es_admin=True)

    def guardar(self, *cambios, motivo='Error de tecleo en la resolución 45/26', version=None):
        return eh.guardar(self.persona, list(cambios), motivo, version=version, usuario=self.admin)

    def test_corregir_un_salario_lo_guarda_y_deja_rastro(self):
        from auditoria.models import EventoAuditoria
        from .models import CambioExterno
        self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '4700'}})
        self.m_mov1.refresh_from_db()
        self.m_baja1.refresh_from_db()
        self.assertEqual(self.m_mov1.salario_nuevo, Decimal('4700.00'))
        self.assertEqual(self.m_baja1.salario_anterior, Decimal('4700.00'))  # encadenado
        cambio = CambioExterno.objects.get(aspirante=self.persona)
        self.assertEqual((cambio.origen, cambio.motivo, cambio.valor_nuevo),
                         ('HIS', 'Error de tecleo en la resolución 45/26', '4 700,00'))
        self.assertTrue(EventoAuditoria.objects.filter(
            descriptor__startswith='Corrección del histórico (Error de tecleo').exists())

    def test_sin_motivo_o_con_errores_no_se_escribe_nada(self):
        with self.assertRaises(eh.ErrorDeBorrador):
            self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '1'}},
                         motivo='  ')
        with self.assertRaises(eh.ErrorDeBorrador):
            self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk,
                          'campos': {'salario': '1', 'fecha': self.f['alta1']}})
        self.m_mov1.refresh_from_db()
        self.assertEqual(self.m_mov1.salario_nuevo, Decimal('4500.00'))

    def test_si_otro_cambio_el_historico_hay_que_recargar(self):
        version = eh.cargar(self.persona).version
        TMovimiento.objects.filter(pk=self.m_mov2.pk).update(salario_nuevo=4600)
        with self.assertRaises(eh.ErrorDeBorrador) as error:
            self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '1'}},
                         version=version)
        self.assertIn('Recargue', str(error.exception))

    def test_corregir_el_ultimo_movimiento_actualiza_el_contrato(self):
        self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk,
                      'campos': {'cargo_id': self.otro_cargo.pk, 'tipo_salario': 'FIJ'}})
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.cargo_id, self.otro_cargo.pk)

    def test_borrar_el_ultimo_movimiento_devuelve_el_contrato_al_anterior(self):
        CAlta.objects.filter(pk=self.contrato.pk).update(cargo=self.otro_cargo)
        self.guardar({'op': 'borrar', 'evento': 'mov:%d' % self.m_mov2.pk})
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.cargo_id, self.cargo.pk)  # Especialista B, como el alta
        self.assertFalse(TMovimiento.objects.filter(pk=self.m_mov2.pk).exists())

    def test_borrar_la_recontratacion_entera_la_deja_de_baja_sin_avisos_falsos(self):
        from notificaciones.models import Notificacion
        avisos_antes = Notificacion.objects.count()
        bajas_antes = CBaja.objects.count()
        self.guardar({'op': 'borrar', 'evento': 'mov:%d' % self.m_mov2.pk},
                     {'op': 'borrar', 'evento': 'mov:%d' % self.m_alta2.pk})
        self.assertFalse(CAlta.objects.filter(pk=self.contrato.pk).exists())
        self.persona.refresh_from_db()
        self.assertEqual(self.persona.estado, 'BAJA')
        self.assertEqual(CBaja.objects.count(), bajas_antes)          # sin baja «vacía»
        self.assertEqual(Notificacion.objects.count(), avisos_antes)  # sin aviso de baja

    def test_corregir_una_baja_y_las_fechas_de_alta(self):
        nueva_baja = self.f['baja1'] - timedelta(days=5)
        nueva_alta = self.f['alta1'] - timedelta(days=3)
        nueva_alta2 = self.f['alta2'] - timedelta(days=2)
        otra_causa = NCausaAltaBaja.objects.create(descripcion='Jubilación')
        self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_baja1.pk,
                      'campos': {'fecha': nueva_baja, 'causa_baja_id': otra_causa.pk}},
                     {'op': 'editar', 'evento': 'mov:%d' % self.m_alta1.pk, 'campos': {'fecha': nueva_alta}},
                     {'op': 'editar', 'evento': 'mov:%d' % self.m_alta2.pk, 'campos': {'fecha': nueva_alta2}})
        self.baja.refresh_from_db()
        self.contrato.refresh_from_db()
        self.assertEqual((self.baja.fecha_baja, self.baja.causa_baja_id, self.baja.fecha_alta),
                         (nueva_baja, otra_causa.pk, nueva_alta))
        self.assertEqual(self.contrato.fecha_alta, nueva_alta2)

    def test_insertar_crea_el_movimiento_en_su_contrato(self):
        entre = self.f['alta2'] + timedelta(days=60)
        self.guardar({'op': 'insertar', 'tras': 'mov:%d' % self.m_alta2.pk,
                      'campos': {'fecha': entre, 'salario': '4100'}})
        nuevo = TMovimiento.objects.get(fecha_efectiva=entre)
        self.assertEqual((nuevo.contrato_id, nuevo.no_expediente, nuevo.salario_nuevo),
                         (self.contrato.pk, '01410', Decimal('4100.00')))

    def test_una_persona_con_solo_su_alta_vuelve_a_aspirante(self):
        sola = Aspirante.objects.create(
            nivel_educ='SA', nombre='Ana', papellido='Sol', sapellido='Mar', doc_identidad='80010114009',
            estado='ACTIVO', sexo='F', raza='BL', provincia=self.persona.provincia,
            municipio=self.persona.municipio)
        contrato = CAlta.objects.create(aspirante=sola, no_expediente='01412', tipo=self.indeterminado,
                                        cargo=self.cargo, fecha_alta=self.f['alta2'])
        alta = TMovimiento.objects.create(
            aspirante=sola, contrato=contrato, no_expediente='01412', fecha_efectiva=self.f['alta2'],
            tipo_movimiento='Alta Inicial', cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=1)
        eh.guardar(sola, [{'op': 'borrar', 'evento': 'mov:%d' % alta.pk}], 'Contratada por error',
                   usuario=self.admin)
        sola.refresh_from_db()
        self.assertEqual(sola.estado, 'ASPIRANTE')
        self.assertFalse(CAlta.objects.filter(aspirante=sola).exists())
        self.assertFalse(CBaja.objects.filter(aspirante=sola).exists())


class EditorHistoricoMesesCerradosTests(EditorHistoricoMotorTests):
    """Fase 3: corregir el histórico corrige también las fotografías de los meses ya
    cerrados (reglas 11a, 11b y 11c), sus plazas y totales, deja la marca y avisa al
    moderador. Tres cierres de la unidad: con la persona en su primer contrato, entre
    los dos contratos (sin ella) y en el segundo contrato."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from datetime import datetime, time

        from cierres.models import CierreCargo, CierreContrato, CierreUnidad
        from usuarios.models import CustomUser

        NTipoContrato.objects.filter(pk=cls.indeterminado.pk).update(ocupa_plaza=True)
        unidad = cls.cargo.departamento.unidad_organizativa
        cls.moderador = CustomUser.objects.create_user(username='mod_editor', password='x', es_moderador=True)
        cls.moderador.unidades.add(unidad)
        hoy = timezone.localdate()
        cls.cortes = {n: hoy - timedelta(days=d) for n, d in (('c1', 850), ('c2', 600), ('c3', 100))}
        cls.cierres = {}
        for nombre, dia in cls.cortes.items():
            cierre = CierreUnidad.objects.create(
                unidad=unidad, anno=dia.year, mes=dia.month, unidad_descripcion='UEB Central',
                fecha_declaracion=timezone.make_aware(datetime.combine(dia, time(10))),
                total_cargos=2, total_plazas_aprobadas=10,
                total_plazas_cubiertas=0 if nombre == 'c2' else 1,
                total_contratos=0 if nombre == 'c2' else 1)
            fila_b = CierreCargo.objects.create(
                cierre=cierre, cargo_id_original=cls.cargo.pk, ncargo_descripcion='Especialista B',
                departamento_descripcion='Contabilidad', cant_aprobada=5, cant_cubierta=0)
            fila_a = CierreCargo.objects.create(
                cierre=cierre, cargo_id_original=cls.otro_cargo.pk, ncargo_descripcion='Especialista A',
                departamento_descripcion='Contabilidad', cant_aprobada=5,
                cant_cubierta=0 if nombre == 'c2' else 1)
            if nombre != 'c2':
                CierreContrato.objects.create(
                    cierre=cierre, cierre_cargo=fila_a, aspirante_id_original=cls.persona.pk,
                    aspirante_vivo=cls.persona, aspirante_nombre='Juan Pérez Gómez', no_expediente='01410',
                    aspirante_estado='ACTIVO', ncargo_descripcion='Especialista A',
                    departamento_descripcion='Contabilidad', tipo_descripcion='Indeterminado',
                    tipo_id_original=cls.indeterminado.pk, ocupa_plaza=True, salario=4500,
                    fecha_alta=cls.f['alta1' if nombre == 'c1' else 'alta2'], mision=True, pais='Angola')
            cls.cierres[nombre] = cierre

    def setUp(self):
        from usuarios.models import CustomUser
        self.admin = CustomUser.objects.create_user(username='adm_editor', password='x', es_admin=True)

    def guardar(self, *cambios):
        with self.captureOnCommitCallbacks(execute=True):
            return eh.guardar(self.persona, list(cambios), 'Error de tecleo', usuario=self.admin)

    def fila(self, nombre):
        from cierres.models import CierreContrato
        return CierreContrato.objects.filter(cierre=self.cierres[nombre],
                                             aspirante_id_original=self.persona.pk).first()

    def cierre(self, nombre):
        self.cierres[nombre].refresh_from_db()
        return self.cierres[nombre]

    def test_un_salario_corregido_se_corrige_solo_en_su_mes(self):
        from notificaciones.models import Notificacion
        res = self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '4700'}})
        self.assertEqual(self.fila('c1').salario, Decimal('4700.00'))
        self.assertEqual(self.fila('c1').pais, 'Angola')          # lo que no es historia, intacto
        self.assertEqual(self.fila('c3').salario, Decimal('4500.00'))
        self.assertIn('Corregido el', self.cierre('c1').correcciones)
        self.assertIn('Error de tecleo', self.cierre('c1').correcciones)
        self.assertEqual(self.cierre('c3').correcciones, '')
        self.assertEqual(len(res['meses']), 1)
        self.assertTrue(Notificacion.objects.filter(
            destinatario=self.moderador, codigo_regla='CIE-CORREGIDO',
            object_id=str(self.cierres['c1'].pk)).exists())

    def test_adelantar_la_baja_la_saca_del_mes_y_libera_la_plaza(self):
        self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_baja1.pk,
                      'campos': {'fecha': self.cortes['c1'] - timedelta(days=20)}})
        self.assertIsNone(self.fila('c1'))
        cierre = self.cierre('c1')
        self.assertEqual((cierre.total_contratos, cierre.total_plazas_cubiertas), (0, 0))
        self.assertEqual(cierre.cargos.get(ncargo_descripcion='Especialista A').cant_cubierta, 0)

    def test_adelantar_la_recontratacion_la_mete_en_el_mes(self):
        nueva_alta = self.cortes['c2'] - timedelta(days=100)
        self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_alta2.pk, 'campos': {'fecha': nueva_alta}})
        fila = self.fila('c2')
        self.assertEqual((fila.ncargo_descripcion, fila.fecha_alta, fila.salario),
                         ('Especialista B', nueva_alta, Decimal('4000.00')))
        self.assertEqual(fila.cierre_cargo.ncargo_descripcion, 'Especialista B')
        cierre = self.cierre('c2')
        self.assertEqual((cierre.total_contratos, cierre.total_plazas_cubiertas), (1, 1))
        # El último mes también cambia: su fecha de alta es la nueva.
        self.assertEqual(self.fila('c3').fecha_alta, nueva_alta)

    def test_cambiar_el_cargo_mueve_la_plaza_dentro_del_mes(self):
        self.guardar({'op': 'editar', 'evento': 'mov:%d' % self.m_mov2.pk,
                      'campos': {'cargo_id': self.cargo.pk}})
        fila = self.fila('c3')
        self.assertEqual(fila.cierre_cargo.ncargo_descripcion, 'Especialista B')
        cierre = self.cierre('c3')
        self.assertEqual(cierre.cargos.get(ncargo_descripcion='Especialista A').cant_cubierta, 0)
        self.assertEqual(cierre.cargos.get(ncargo_descripcion='Especialista B').cant_cubierta, 1)
        self.assertEqual(cierre.total_plazas_cubiertas, 1)

    def test_la_vista_previa_dice_los_meses_sin_tocarlos(self):
        _, _, errores, res = self.preparar(
            {'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '4700'}})
        self.assertEqual(errores, [])
        self.assertEqual(len(res['meses']), 1)
        self.assertIn('se corrigen sus datos', res['meses'][0])
        self.assertEqual(self.fila('c1').salario, Decimal('4500.00'))


class EditorHistoricoPantallaTests(TestCase):
    """Fase 4: la pantalla solo la abre el Administrador; la vista previa no escribe y
    el guardado aplica el borrador con su motivo."""

    @classmethod
    def setUpTestData(cls):
        EditorHistoricoMotorTests.setUpTestData.__func__(cls)
        from usuarios.models import CustomUser
        cls.admin = CustomUser.objects.create_user(username='adm_pantalla', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(username='mod_pantalla', password='x', es_moderador=True)

    def url(self, sufijo=''):
        return '/contrato/editor-historico/%d/%s' % (self.persona.pk, sufijo)

    def post(self, sufijo, datos):
        import json
        return self.client.post(self.url(sufijo), json.dumps(datos), content_type='application/json')

    def test_solo_el_administrador(self):
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.post('previa/', {'cambios': []}).status_code, 403)
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Editor del histórico')

    def test_la_previa_no_escribe_y_el_guardado_si(self):
        self.client.force_login(self.admin)
        cambio = {'op': 'editar', 'evento': 'mov:%d' % self.m_mov1.pk, 'campos': {'salario': '4800'}}
        datos = self.post('previa/', {'cambios': [cambio]}).json()
        self.assertTrue(datos['ok'])
        self.assertEqual(datos['resumen']['cambios'][0][1], 'Salario')
        self.m_mov1.refresh_from_db()
        self.assertEqual(self.m_mov1.salario_nuevo, Decimal('4500.00'))

        datos = self.post('guardar/', {'cambios': [cambio], 'motivo': ''}).json()
        self.assertFalse(datos['ok'])
        self.assertIn('motivo', datos['errores'][0])

        version = eh.cargar(self.persona).version
        datos = self.post('guardar/', {'cambios': [cambio], 'motivo': 'Resolución 12/26', 'version': version}).json()
        self.assertTrue(datos['ok'])
        self.m_mov1.refresh_from_db()
        self.assertEqual(self.m_mov1.salario_nuevo, Decimal('4800.00'))

    def test_un_borrador_imposible_devuelve_el_error_en_espanol(self):
        self.client.force_login(self.admin)
        datos = self.post('previa/', {'cambios': [{'op': 'editar', 'evento': 'mov:999999', 'campos': {}}]}).json()
        self.assertFalse(datos['ok'])
        self.assertIn('ya no existe', datos['errores'][0])


class HistoricoQueNoEncajaTests(TestCase):
    """MOV-015: el «antes» de un movimiento distinto de lo que dejó el anterior se
    avisa una vez por persona, y desaparece al corregirlo con el editor."""

    @classmethod
    def setUpTestData(cls):
        EditorHistoricoMotorTests.setUpTestData.__func__(cls)
        # Como la persona 55 de la base local: el alta del segundo contrato sin tipo.
        TMovimiento.objects.filter(pk=cls.m_alta2.pk).update(tipo_contrato_nuevo=None)

    def hallazgos(self):
        from subsanacion.contexto import ContextoAnalisis
        from subsanacion.reglas import obtener_regla
        return [h for h in obtener_regla('MOV-015').ejecutar(ContextoAnalisis())
                if h.object_id == str(self.persona.pk)]

    def test_detecta_el_salto_una_vez_por_persona(self):
        hallazgos = self.hallazgos()
        self.assertEqual(len(hallazgos), 1)
        self.assertIn('1 punto', hallazgos[0].titulo)
        self.assertIn('tipo de contrato «Indeterminado», pero el anterior dejó «---»', hallazgos[0].detalle)

    def test_al_corregirlo_con_el_editor_desaparece(self):
        from usuarios.models import CustomUser
        admin = CustomUser.objects.create_user(username='adm_mov015', password='x', es_admin=True)
        eh.guardar(self.persona, [{'op': 'editar', 'evento': 'mov:%d' % self.m_alta2.pk,
                                   'campos': {'tipo_id': self.indeterminado.pk}}],
                   'El alta se creó sin tipo de contrato', usuario=admin)
        self.assertEqual(self.hallazgos(), [])

    def test_el_aviso_guardado_se_cierra_al_guardar_el_editor(self):
        from subsanacion.models import Hallazgo
        from subsanacion.por_registro import revisar_registros
        from usuarios.models import CustomUser
        revisar_registros(aspirantes=[self.persona.pk])
        aviso = Hallazgo.objects.get(codigo_regla='MOV-015', object_id=str(self.persona.pk))
        self.assertTrue(aviso.vigente)
        admin = CustomUser.objects.create_user(username='adm_mov015b', password='x', es_admin=True)
        eh.guardar(self.persona, [{'op': 'editar', 'evento': 'mov:%d' % self.m_alta2.pk,
                                   'campos': {'tipo_id': self.indeterminado.pk}}],
                   'El alta se creó sin tipo de contrato', usuario=admin)
        aviso.refresh_from_db()
        self.assertFalse(aviso.vigente)

    def test_el_boton_lleva_al_editor_solo_al_administrador(self):
        from subsanacion.enlaces import construir_enlace, destino_de_regla
        from subsanacion.reglas import obtener_regla
        from usuarios.models import CustomUser
        regla = obtener_regla('MOV-015')
        admin = CustomUser.objects.create_user(username='adm_boton', password='x', es_admin=True)
        moderador = CustomUser.objects.create_user(username='mod_boton', password='x', es_moderador=True)
        destino, texto = destino_de_regla(regla, admin)
        enlace = construir_enlace('bolsa.Aspirante', str(self.persona.pk), forzar_url=destino,
                                  usuario=admin, etiqueta=texto)
        self.assertEqual(enlace['href'], '/contrato/editor-historico/%d/' % self.persona.pk)
        self.assertEqual(enlace['etiqueta'], 'Abrir el editor del histórico')
        self.assertEqual(destino_de_regla(regla, moderador), (None, None))
