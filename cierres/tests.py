"""Pruebas del ciclo de cierres mensuales.

Dos bloques con intención distinta:

* `ReglasDeCalendario` no toca la base de datos. Cubre los bordes que se rompen en
  silencio (el día 25 sí y el 26 no, el salto de diciembre a enero, la cola FIFO)
  y es la red que protege cualquier retoque futuro de `periodos.py`.
* El resto verifica que la fotografía es **realmente** inmutable. Ese es el motivo
  por el que existe el módulo: si cambiar un nomenclador moviera un cierre ya
  declarado, todo lo demás sobraría.

No se prueban plantillas ni HTML: se prueba `servicios.py`, único punto por el que
pasa cualquier cambio de estado.
"""

from contextlib import contextmanager
from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from cierres import integracion, servicios
from cierres.constantes import (COLOR_AZUL, COLOR_NARANJA, COLOR_ROJO,
                                COLOR_SIN_HIJAS, COLOR_VERDE)
from cierres.models import (CierreCargo, CierreUnidad, EstadoCierreUnidad,
                            EstadoUnidad)
from cierres.periodos import (Periodo, desde_clave, en_ventana, fue_en_plazo,
                              periodo_declarable, periodos_pendientes,
                              puede_reabrirse)
from contratos.models import CAlta
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio, NProvincia,
                                  NTipoContrato, NTipoUnidadOrganizativa)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser

AGOSTO = Periodo(2026, 8)
JULIO = Periodo(2026, 7)
JUNIO = Periodo(2026, 6)
SEPTIEMBRE = Periodo(2026, 9)
OCTUBRE = Periodo(2026, 10)


class ReglasDeCalendario(SimpleTestCase):
    """Aritmética de períodos. Sin base de datos, así que corre en milisegundos."""

    def test_la_ventana_incluye_el_dia_25_y_excluye_el_26(self):
        """El requisito se contradecía aquí: el 25 es válido para declarar, y es el
        barrido del 26 el que marca desactualizada."""
        self.assertFalse(en_ventana(date(2026, 8, 19)))
        self.assertTrue(en_ventana(date(2026, 8, 20)))
        self.assertTrue(en_ventana(date(2026, 8, 25)))
        self.assertFalse(en_ventana(date(2026, 8, 26)))

    def test_sin_primera_declaracion_no_se_reclama_nada(self):
        """Regla 4: la obligación empieza tras la primera declaración."""
        self.assertEqual(periodos_pendientes(None, date(2026, 8, 26)), [])

    def test_antes_del_dia_20_no_se_puede_declarar(self):
        self.assertIsNone(periodo_declarable(JULIO, date(2026, 8, 5)))

    def test_declaracion_ordinaria_dentro_de_la_ventana(self):
        self.assertEqual(periodo_declarable(JULIO, date(2026, 8, 22)), AGOSTO)

    def test_pasado_el_25_regulariza_su_propio_mes(self):
        """El 26 de agosto la unidad ya está desactualizada, pero lo que declara
        sigue siendo agosto, no septiembre (regla 7)."""
        self.assertEqual(periodo_declarable(JULIO, date(2026, 8, 26)), AGOSTO)
        self.assertEqual(periodo_declarable(JULIO, date(2026, 9, 10)), AGOSTO)

    def test_quien_ya_cerro_el_mes_no_puede_volver_a_declarar(self):
        self.assertIsNone(periodo_declarable(AGOSTO, date(2026, 8, 24)))
        self.assertIsNone(periodo_declarable(AGOSTO, date(2026, 9, 1)))

    def test_la_cola_es_fifo(self):
        """Regla 8: no se puede saltar un mes declarando el actual."""
        self.assertEqual(periodo_declarable(JUNIO, date(2026, 10, 15)), JULIO)
        self.assertEqual(
            periodos_pendientes(JUNIO, date(2026, 10, 15)),
            [JULIO, AGOSTO, SEPTIEMBRE])

    def test_el_mes_en_curso_solo_cuenta_tras_abrirse_su_ventana(self):
        self.assertNotIn(OCTUBRE, periodos_pendientes(JUNIO, date(2026, 10, 15)))
        self.assertIn(OCTUBRE, periodos_pendientes(JUNIO, date(2026, 10, 22)))

    def test_cambio_de_anno(self):
        self.assertEqual(Periodo(2026, 12).siguiente(), Periodo(2027, 1))
        self.assertEqual(Periodo(2026, 1).anterior(), Periodo(2025, 12))
        self.assertEqual(
            periodo_declarable(Periodo(2026, 12), date(2027, 1, 21)),
            Periodo(2027, 1))

    def test_solo_esta_en_plazo_el_mes_en_curso_dentro_de_su_ventana(self):
        self.assertTrue(fue_en_plazo(AGOSTO, date(2026, 8, 22)))
        self.assertFalse(fue_en_plazo(AGOSTO, date(2026, 8, 26)))
        self.assertFalse(fue_en_plazo(AGOSTO, date(2026, 9, 10)))

    def test_solo_se_reabre_dentro_de_la_ventana(self):
        """Pasado el 25 el cierre es definitivo: los cambios son del mes siguiente."""
        self.assertTrue(puede_reabrirse(AGOSTO, date(2026, 8, 22)))
        self.assertFalse(puede_reabrirse(AGOSTO, date(2026, 8, 26)))
        self.assertFalse(puede_reabrirse(AGOSTO, date(2026, 9, 22)))

    def test_las_claves_de_url_no_lanzan_con_basura(self):
        self.assertEqual(AGOSTO.clave, '2026-08')
        self.assertEqual(desde_clave('2026-08'), AGOSTO)
        self.assertIsNone(desde_clave('diciembre'))
        self.assertIsNone(desde_clave('2026-13'))


class BaseCierres(TestCase):
    """Una unidad con un departamento, dos cargos y un contrato.

    `tipo_unidad` es una UEB de hoja (ni principal ni subunidad): es la que
    declara de verdad, como cualquier unidad real con plantilla propia. Las
    unidades PRINCIPALES (padre) no declaran — su estado se deriva de sus
    hijas — así que los tests de ese comportamiento viven aparte, en
    `PadresEHijasNoSeCascadean`, con su propio tipo `es_principal=True`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo_unidad, grupo_nomina=1)
        cls.otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=cls.tipo_unidad, grupo_nomina=2)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad, orden_informe=1)

        cls.grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000, puesto_clave=True)
        cls.otro_ncargo = NCargo.objects.create(
            descripcion='Operario', cat_ocupacional='OPE',
            grupo_escala=cls.grupo, salario_basico=2000)

        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento,
            cant_aprobada=10, orden_informe=1)
        cls.cargo_dos = CargoPlantilla.objects.create(
            ncargo=cls.otro_ncargo, departamento=cls.departamento,
            cant_aprobada=4, orden_informe=2)

        cls.provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        cls.municipio = NMunicipio.objects.create(
            nombre='Playa', provincia=cls.provincia, siglas='PLA')
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True)
        cls.aspirante = Aspirante.objects.create(
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad='85010112345', estado='ACTIVO', sexo='F', raza='BL',
            unidad_organizativa=cls.unidad,
            provincia=cls.provincia, municipio=cls.municipio)
        cls.contrato = CAlta.objects.create(
            aspirante=cls.aspirante, no_expediente='00100',
            tipo=cls.tipo_contrato, cargo=cls.cargo, fecha_alta=date(2026, 1, 15))

        cls.admin = CustomUser.objects.create_user(
            username='admin_cierres', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_cierres', password='x', es_moderador=True)
        cls.moderador.unidades.add(cls.unidad)
        cls.ajeno = CustomUser.objects.create_user(
            username='mod_ajeno', password='x', es_moderador=True)
        cls.ajeno.unidades.add(cls.otra_unidad)

    def declarar(self, hoy=date(2026, 8, 22), usuario=None, unidad=None):
        return servicios.declarar_actualizada(
            unidad or self.unidad, usuario or self.admin, hoy=hoy)


@contextmanager
def fingir_hoy(dia):
    """Simula la fecha del sistema en la capa HTTP.

    Las vistas llaman a `date.today()` porque un usuario no elige en qué día
    declara — sería justo la puerta trasera que el módulo trata de cerrar. Para
    poder probarlas fuera de la ventana hay que fingir el calendario en los tres
    módulos que lo consultan: `integracion` decide qué botones ofrece el Gestor
    de Plantilla, `views` atiende la petición y `servicios` vuelve a comprobarlo
    por su cuenta antes de escribir nada.
    """
    class FechaFija(date):
        @classmethod
        def today(cls):
            return dia

    with mock.patch('cierres.views.date', FechaFija), \
            mock.patch('cierres.servicios.date', FechaFija), \
            mock.patch('cierres.integracion.date', FechaFija):
        yield


class CapturaDeLaFotografia(BaseCierres):

    def test_captura_todos_los_cargos_y_contratos_de_la_unidad(self):
        cierre = self.declarar()
        self.assertEqual(cierre.cargos.count(), 2)
        self.assertEqual(cierre.contratos.count(), 1)
        self.assertEqual(cierre.total_plazas_aprobadas, 14)

    def test_no_captura_lo_de_otras_unidades(self):
        Departamento.objects.create(
            descripcion='Ajeno', unidad_organizativa=self.otra_unidad, orden_informe=1)
        cierre = self.declarar()
        self.assertEqual(cierre.cargos.count(), 2)

    def test_cada_contrato_queda_enlazado_a_su_cargo(self):
        cierre = self.declarar()
        fila = cierre.contratos.first()
        self.assertIsNotNone(fila.cierre_cargo)
        self.assertEqual(fila.cierre_cargo.cargo_id_original, self.cargo.pk)

    def test_congela_los_atributos_del_nomenclador(self):
        cierre = self.declarar()
        fila = cierre.cargos.get(cargo_id_original=self.cargo.pk)
        self.assertEqual(fila.cat_ocupacional, 'TEC')
        self.assertTrue(fila.puesto_clave)
        self.assertEqual(fila.grupo_escala_nivel, 'IV')

    def test_cambiar_el_nomenclador_no_mueve_un_cierre_ya_declarado(self):
        """**La prueba que justifica todo el módulo.**

        Sin congelar `cat_ocupacional`, reclasificar un NCargo en octubre
        cambiaría en qué fila del consolidado aparece agosto, y el informe ya
        firmado dejaría de cuadrar.
        """
        cierre = self.declarar()

        NCargo.objects.filter(pk=self.ncargo.pk).update(
            cat_ocupacional='SER', descripcion='Renombrado', puesto_clave=False)

        fila = cierre.cargos.get(cargo_id_original=self.cargo.pk)
        self.assertEqual(fila.cat_ocupacional, 'TEC')
        self.assertEqual(fila.ncargo_descripcion, 'Especialista B')
        self.assertTrue(fila.puesto_clave)

    def test_borrar_un_contrato_no_mueve_el_cierre(self):
        """Al dar de baja, el CAlta se borra físicamente. Si el informe histórico
        dependiera de él, agosto perdería trabajadores retroactivamente."""
        cierre = self.declarar()
        self.contrato.delete()

        self.assertEqual(cierre.contratos.count(), 1)
        self.assertEqual(CAlta.objects.count(), 0)

    def test_congela_la_estructura_de_la_unidad(self):
        cierre = self.declarar()
        self.unidad.descripcion = 'Renombrada'
        self.unidad.save()

        cierre.refresh_from_db()
        self.assertEqual(cierre.unidad_descripcion, 'UEB Central')


class CicloDeDeclaracion(BaseCierres):

    def test_declarar_en_ventana_queda_en_plazo(self):
        cierre = self.declarar(hoy=date(2026, 8, 22))
        self.assertEqual(cierre.periodo, AGOSTO)
        self.assertTrue(cierre.en_plazo)

    def test_antes_del_dia_20_no_deja_declarar(self):
        with self.assertRaises(servicios.ErrorDeCierre):
            self.declarar(hoy=date(2026, 8, 5))

    def test_no_se_puede_declarar_dos_veces_el_mismo_mes(self):
        self.declarar()
        with self.assertRaises(servicios.ErrorDeCierre):
            self.declarar()

    def test_regularizar_marca_fuera_de_plazo_y_conserva_el_mes(self):
        """Declarar el 10 de septiembre cierra AGOSTO, no septiembre (regla 7)."""
        self.declarar(hoy=date(2026, 7, 22))
        cierre = self.declarar(hoy=date(2026, 9, 10))

        self.assertEqual(cierre.periodo, AGOSTO)
        self.assertFalse(cierre.en_plazo)

    def test_la_regularizacion_respeta_la_cola_fifo(self):
        self.declarar(hoy=date(2026, 6, 22))

        primero = self.declarar(hoy=date(2026, 10, 15))
        self.assertEqual(primero.periodo, JULIO)

        segundo = self.declarar(hoy=date(2026, 10, 15))
        self.assertEqual(segundo.periodo, AGOSTO)

    def test_la_fotografia_de_un_mes_regularizado_es_del_momento_de_declarar(self):
        """Contraintuitivo pero deliberado: solo la etiqueta es de agosto."""
        self.declarar(hoy=date(2026, 7, 22))
        CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=self.departamento,
            cant_aprobada=99, orden_informe=3)

        cierre = self.declarar(hoy=date(2026, 9, 10))
        self.assertEqual(cierre.periodo, AGOSTO)
        self.assertEqual(cierre.cargos.count(), 3)


class EstadoDeLaUnidad(BaseCierres):

    def test_una_unidad_que_nunca_declaro_esta_pendiente_sin_arrastre(self):
        calculo = servicios.calcular_estado(self.unidad, date(2026, 8, 26))
        self.assertEqual(calculo['estado'], EstadoUnidad.PENDIENTE)
        self.assertEqual(calculo['pendientes'], [])

    def test_tras_declarar_queda_actualizada(self):
        self.declarar()
        estado = servicios.refrescar_estado(self.unidad, hoy=date(2026, 8, 22))
        self.assertEqual(estado.estado, EstadoUnidad.ACTUALIZADA)
        self.assertEqual(estado.meses_pendientes, 0)

    def test_dentro_de_la_ventana_sin_declarar_es_pendiente_no_incumplimiento(self):
        self.declarar(hoy=date(2026, 7, 22))
        calculo = servicios.calcular_estado(self.unidad, date(2026, 8, 22))
        self.assertEqual(calculo['estado'], EstadoUnidad.PENDIENTE)

    def test_pasada_la_ventana_queda_desactualizada(self):
        self.declarar(hoy=date(2026, 7, 22))
        calculo = servicios.calcular_estado(self.unidad, date(2026, 8, 26))
        self.assertEqual(calculo['estado'], EstadoUnidad.DESACTUALIZADA)

    def test_regularizar_uno_de_varios_meses_no_la_pone_al_dia(self):
        self.declarar(hoy=date(2026, 6, 22))
        self.declarar(hoy=date(2026, 10, 15))

        calculo = servicios.calcular_estado(self.unidad, date(2026, 10, 15))
        self.assertEqual(calculo['estado'], EstadoUnidad.DESACTUALIZADA)
        self.assertEqual(calculo['declarable'], AGOSTO)


class Reapertura(BaseCierres):

    def test_reabrir_borra_la_fotografia_y_vuelve_a_pendiente(self):
        cierre = self.declarar()
        cierre_id = cierre.pk

        servicios.reabrir(self.unidad, self.admin, hoy=date(2026, 8, 24))

        self.assertFalse(CierreUnidad.objects.filter(pk=cierre_id).exists())
        self.assertEqual(CierreCargo.objects.filter(cierre_id=cierre_id).count(), 0)

    def test_tras_reabrir_se_puede_declarar_de_nuevo_el_mismo_mes(self):
        self.declarar()
        servicios.reabrir(self.unidad, self.admin, hoy=date(2026, 8, 24))

        nuevo = self.declarar(hoy=date(2026, 8, 25))
        self.assertEqual(nuevo.periodo, AGOSTO)
        self.assertTrue(nuevo.en_plazo)

    def test_la_redeclaracion_recoge_los_cambios_intermedios(self):
        """Regla 12: la fotografía válida es la de la última declaración."""
        self.declarar(hoy=date(2026, 8, 22))
        servicios.reabrir(self.unidad, self.admin, hoy=date(2026, 8, 24))
        CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=self.departamento,
            cant_aprobada=7, orden_informe=3)

        nuevo = self.declarar(hoy=date(2026, 8, 25))
        self.assertEqual(nuevo.cargos.count(), 3)
        self.assertEqual(nuevo.total_plazas_aprobadas, 21)

    def test_pasada_la_ventana_ya_no_se_reabre(self):
        self.declarar(hoy=date(2026, 8, 22))
        with self.assertRaises(servicios.ErrorDeCierre):
            servicios.reabrir(self.unidad, self.admin, hoy=date(2026, 8, 26))


class Permisos(BaseCierres):

    def test_el_moderador_declara_su_unidad(self):
        cierre = self.declarar(usuario=self.moderador)
        self.assertEqual(cierre.declarado_por, self.moderador)

    def test_el_moderador_no_declara_unidades_ajenas(self):
        with self.assertRaises(servicios.ErrorDeCierre):
            self.declarar(usuario=self.ajeno)

    def test_el_administrador_declara_cualquiera(self):
        cierre = self.declarar(usuario=self.admin, unidad=self.otra_unidad)
        self.assertEqual(cierre.unidad, self.otra_unidad)


class ConsultasParaInformes(BaseCierres):

    def test_solo_ofrece_periodos_que_existen(self):
        self.declarar(hoy=date(2026, 8, 22))
        self.assertEqual(servicios.periodos_disponibles(), [AGOSTO])

    def test_senala_las_unidades_que_faltan_por_cerrar(self):
        """Decisión de diseño: el informe excluye y avisa, nunca mezcla períodos."""
        self.declarar(hoy=date(2026, 7, 22), unidad=self.unidad)
        self.declarar(hoy=date(2026, 7, 22), unidad=self.otra_unidad)
        self.declarar(hoy=date(2026, 8, 22), unidad=self.unidad)

        faltan = servicios.unidades_sin_cierre(AGOSTO)
        self.assertEqual(faltan, ['UEB Norte'])

    def test_no_reclama_a_quien_aun_no_habia_empezado(self):
        """Una unidad cuya primera declaración es de septiembre no se echa en falta
        en el informe de agosto (regla 4)."""
        self.declarar(hoy=date(2026, 8, 22), unidad=self.unidad)
        self.declarar(hoy=date(2026, 9, 22), unidad=self.otra_unidad)

        self.assertEqual(servicios.unidades_sin_cierre(AGOSTO), [])


class AccionesDeDeclaracion(BaseCierres):
    """Las acciones que invoca la toolbar del Gestor de Plantilla.

    Responden JSON `{status, message}`, el mismo contrato que ya consumía el
    gestor para eliminar. Lo que se prueba aquí es el endpoint, no el JavaScript.
    """

    def declarar_por_http(self, unidad=None, hoy=date(2026, 8, 22)):
        url = reverse('declarar_cierre', args=[(unidad or self.unidad).pk])
        with fingir_hoy(hoy):
            return self.client.post(url, HTTP_HX_REQUEST='true')

    def test_declarar_devuelve_json_y_crea_el_cierre(self):
        self.client.force_login(self.moderador)

        respuesta = self.declarar_por_http()

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['status'], 'ok')
        cierre = CierreUnidad.objects.get(unidad=self.unidad)
        self.assertEqual(cierre.periodo, AGOSTO)
        self.assertEqual(cierre.declarado_por, self.moderador)

    def test_declarar_fuera_de_plazo_responde_error_sin_crear_nada(self):
        self.client.force_login(self.admin)

        respuesta = self.declarar_por_http(hoy=date(2026, 8, 5))

        self.assertEqual(respuesta.json()['status'], 'error')
        self.assertIn('día 20', respuesta.json()['message'])
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.unidad).exists())

    def test_declarar_dos_veces_el_mismo_mes_responde_error(self):
        self.client.force_login(self.admin)
        self.declarar_por_http()

        respuesta = self.declarar_por_http()

        self.assertEqual(respuesta.json()['status'], 'error')
        self.assertEqual(CierreUnidad.objects.filter(unidad=self.unidad).count(), 1)

    def test_reabrir_devuelve_json_y_borra_la_fotografia(self):
        self.declarar(hoy=date(2026, 8, 22))
        self.client.force_login(self.admin)
        url = reverse('reabrir_cierre', args=[self.unidad.pk])

        with fingir_hoy(date(2026, 8, 24)):
            respuesta = self.client.post(url, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.json()['status'], 'ok')
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.unidad).exists())

    def test_no_se_puede_declarar_por_GET(self):
        """Una acción que congela una fotografía no puede dispararse navegando."""
        self.client.force_login(self.admin)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.get(reverse('declarar_cierre', args=[self.unidad.pk]))
        self.assertEqual(respuesta.status_code, 405)


class PermisosDeDeclaracion(BaseCierres):
    """Los tres roles, contra el endpoint directamente.

    El alcance no puede depender de que el botón no se pinte: un moderador que
    copie la URL de otra unidad tiene que chocar con el servidor.
    """

    def test_el_moderador_declara_la_unidad_que_tiene_asignada(self):
        self.client.force_login(self.moderador)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.post(
                reverse('declarar_cierre', args=[self.unidad.pk]))

        self.assertEqual(respuesta.json()['status'], 'ok')

    def test_el_moderador_no_declara_una_unidad_ajena(self):
        self.client.force_login(self.moderador)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.post(
                reverse('declarar_cierre', args=[self.otra_unidad.pk]))

        self.assertEqual(respuesta.status_code, 404)
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.otra_unidad).exists())

    def test_el_moderador_no_reabre_una_unidad_ajena(self):
        servicios.declarar_actualizada(self.otra_unidad, self.admin, hoy=date(2026, 8, 22))
        self.client.force_login(self.moderador)

        with fingir_hoy(date(2026, 8, 24)):
            respuesta = self.client.post(
                reverse('reabrir_cierre', args=[self.otra_unidad.pk]))

        self.assertEqual(respuesta.status_code, 404)
        self.assertTrue(CierreUnidad.objects.filter(unidad=self.otra_unidad).exists())

    def test_el_administrador_declara_cualquier_unidad(self):
        self.client.force_login(self.admin)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.post(
                reverse('declarar_cierre', args=[self.otra_unidad.pk]))

        self.assertEqual(respuesta.json()['status'], 'ok')

    def test_el_observador_no_puede_declarar(self):
        observador = CustomUser.objects.create_user(
            username='obs_declara', password='x', es_observador=True)
        self.client.force_login(observador)

        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.post(
                reverse('declarar_cierre', args=[self.unidad.pk]))

        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.unidad).exists())

    def test_el_observador_no_puede_reabrir(self):
        self.declarar(hoy=date(2026, 8, 22))
        observador = CustomUser.objects.create_user(
            username='obs_reabre', password='x', es_observador=True)
        self.client.force_login(observador)

        with fingir_hoy(date(2026, 8, 24)):
            respuesta = self.client.post(
                reverse('reabrir_cierre', args=[self.unidad.pk]))

        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(CierreUnidad.objects.filter(unidad=self.unidad).exists())


class HabilitacionDeclararYReabrir(BaseCierres):
    """La habilitación de los botones NO es «¿hoy está en 20-25?».

    Es una función del **estado de la unidad** (nunca declarada / al día /
    desactualizada / con meses pendientes) cruzado con la fecha. Cada test
    aquí prueba un cruce concreto de esos dos ejes, usando `periodo_declarable`
    y `puede_reabrirse` directamente — la misma lógica que consume
    `integracion.acciones_por_unidad` para pintar los botones del gestor.
    """

    # --- Eje 1: unidad ACTUALIZADA (ya declaró el mes en curso) ---

    def test_actualizada_no_puede_redeclarar_ni_dentro_ni_fuera_de_ventana(self):
        """Una vez declarado el mes, «Declarar» no vuelve a ofrecerse: para
        corregirlo hay que pasar por «Reabrir» primero (regla 11)."""
        self.declarar(hoy=date(2026, 8, 22))

        for dia in (23, 25, 26, 31):
            with self.subTest(dia=dia):
                hoy = date(2026, 8, dia)
                declarable = periodo_declarable(JULIO.siguiente(), hoy)
                # JULIO.siguiente() == AGOSTO == último cerrado tras declarar
                self.assertIsNone(declarable,
                    f'día {dia}: no debería poder redeclarar agosto sin reabrir')

    def test_actualizada_dentro_de_ventana_si_puede_reabrir(self):
        self.declarar(hoy=date(2026, 8, 22))
        self.assertTrue(puede_reabrirse(AGOSTO, date(2026, 8, 25)))

    def test_actualizada_fuera_de_ventana_ya_no_puede_reabrir(self):
        """Pasado el día 25 el cierre es definitivo (regla 10): un cambio el
        27 de agosto pertenece a septiembre, no puede reescribir agosto."""
        self.declarar(hoy=date(2026, 8, 22))
        self.assertFalse(puede_reabrirse(AGOSTO, date(2026, 8, 26)))
        self.assertFalse(puede_reabrirse(AGOSTO, date(2026, 8, 31)))

    # --- Eje 2: unidad DESACTUALIZADA (arrastra meses) ---

    def test_desactualizada_puede_declarar_cualquier_dia_incluso_antes_del_20(self):
        """El punto central que pedías verificar: una unidad atrasada NO espera
        a que se abra una nueva ventana. Julio quedó sin cerrar; en octubre debe
        poder regularizarlo el día 3, el 15 o el 22 — da igual."""
        self.declarar(hoy=date(2026, 7, 22))
        # Agosto y septiembre se dejan pasar sin declarar → octubre, desactualizada.

        for dia in (1, 3, 15, 19):
            with self.subTest(dia=dia):
                hoy = date(2026, 10, dia)
                calculo = servicios.calcular_estado(self.unidad, hoy)
                self.assertEqual(calculo['estado'], EstadoUnidad.DESACTUALIZADA,
                    f'día {dia}: debería seguir desactualizada')
                self.assertEqual(calculo['declarable'], AGOSTO,
                    f'día {dia}: debería poder regularizar agosto ya mismo, '
                    f'sin esperar al día 20')

    def test_desactualizada_regulariza_el_mas_antiguo_no_el_mes_en_curso(self):
        """No se puede saltar un mes pendiente declarando el actual (regla 8)."""
        self.declarar(hoy=date(2026, 6, 22))
        calculo = servicios.calcular_estado(self.unidad, date(2026, 10, 5))
        self.assertEqual(calculo['declarable'], JULIO)
        self.assertNotEqual(calculo['declarable'], Periodo(2026, 10))

    # --- Eje 3: NUNCA declarada (sin obligación previa) ---

    def test_nunca_declarada_no_puede_antes_del_dia_20(self):
        for dia in (1, 10, 19):
            with self.subTest(dia=dia):
                self.assertIsNone(
                    periodo_declarable(None, date(2026, 8, dia)),
                    f'día {dia}: primera declaración no debería habilitarse aún')

    def test_nunca_declarada_no_arrastra_ningun_mes_anterior(self):
        """Regla 4: antes de la primera declaración no hay historial que
        regularizar, aunque hayan pasado varios meses desde que existe la unidad."""
        calculo = servicios.calcular_estado(self.unidad, date(2026, 11, 15))
        self.assertEqual(calculo['estado'], EstadoUnidad.PENDIENTE)
        self.assertEqual(calculo['pendientes'], [])

    # --- Eje 4: reabrir no aplica a una regularización de mes pasado ---

    def test_reabrir_no_aplica_a_una_regularizacion_de_mes_pasado(self):
        """Julio se regulariza en septiembre (fuera de plazo). Eso NO es
        reabribre: `puede_reabrirse` compara contra el mes en curso, y el mes
        en curso ya es septiembre, no julio."""
        self.declarar(hoy=date(2026, 6, 22))          # cierra junio
        self.declarar(hoy=date(2026, 9, 10))            # regulariza julio, fuera de plazo

        self.assertFalse(puede_reabrirse(JULIO, date(2026, 9, 10)))
        self.assertFalse(puede_reabrirse(JULIO, date(2026, 9, 15)))

    def test_el_gestor_no_ofrece_reabrir_sobre_un_mes_regularizado(self):
        self.declarar(hoy=date(2026, 6, 22))
        self.declarar(hoy=date(2026, 9, 10))

        acciones = integracion.acciones_por_unidad([self.unidad], self.admin,
                                                    hoy=date(2026, 9, 12))
        self.assertFalse(acciones[self.unidad.pk]['puede_reabrir'])

    # --- Eje 5: la habilitación del gestor refleja todo esto junto ---

    def test_el_gestor_habilita_declarar_para_una_desactualizada_un_dia_5(self):
        """Prueba de extremo a extremo del punto pedido: la fila del gestor debe
        mostrar el botón habilitado un día 5, si la unidad está desactualizada."""
        self.declarar(hoy=date(2026, 7, 22))

        acciones = integracion.acciones_por_unidad([self.unidad], self.admin,
                                                    hoy=date(2026, 10, 5))
        self.assertTrue(acciones[self.unidad.pk]['puede_declarar'])
        self.assertEqual(acciones[self.unidad.pk]['etiqueta_declarable'], 'Agosto 2026')

    def test_el_gestor_no_habilita_declarar_para_una_actualizada_fuera_de_ventana(self):
        self.declarar(hoy=date(2026, 8, 22))

        acciones = integracion.acciones_por_unidad([self.unidad], self.admin,
                                                    hoy=date(2026, 8, 28))
        self.assertFalse(acciones[self.unidad.pk]['puede_declarar'])
        self.assertFalse(acciones[self.unidad.pk]['puede_reabrir'])


class PadresEHijasNoSeCascadean(BaseCierres):
    """Las Direcciones Principales (padre) no tienen departamentos ni cargos
    propios — toda su plantilla vive en sus subunidades — así que no pueden
    declararse directamente, con ningún rol. Su color/estado se agrega a partir
    del de sus hijas. `cls.padre` es un tipo genuino `es_principal=True`,
    distinto de `cls.unidad` (que sigue siendo una UEB de hoja normal, para no
    tocar el resto de los tests de esta clase base).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tipo_padre = NTipoUnidadOrganizativa.objects.create(
            descripcion='Direccion Principal', es_principal=True)
        cls.padre = UnidadOrganizativa.objects.create(
            descripcion='Oficina Central', tipo=cls.tipo_padre, grupo_nomina=9)

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
        cls.cargo_a = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.dept_a, cant_aprobada=3, orden_informe=1)
        cls.cargo_b = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.dept_b, cant_aprobada=2, orden_informe=1)

    # --- El padre no declara, ni siquiera el Administrador ---

    def test_el_padre_no_puede_declararse_ni_el_administrador(self):
        with self.assertRaises(servicios.ErrorDeCierre):
            servicios.declarar_actualizada(self.padre, self.admin, hoy=date(2026, 8, 22))
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.padre).exists())

    def test_el_mensaje_de_error_es_especifico_no_generico(self):
        """No debe decir «no tiene asignada esta unidad» — eso confundiría al
        Administrador, que sí tiene acceso a todas."""
        try:
            servicios.declarar_actualizada(self.padre, self.admin, hoy=date(2026, 8, 22))
            self.fail('debía lanzar ErrorDeCierre')
        except servicios.ErrorDeCierre as error:
            self.assertIn('principales', str(error))

    def test_el_padre_tampoco_se_reabre(self):
        with self.assertRaises(servicios.ErrorDeCierre):
            servicios.reabrir(self.padre, self.admin, hoy=date(2026, 8, 22))

    def test_el_boton_declarar_nunca_se_ofrece_para_un_padre(self):
        acciones = integracion.acciones_por_unidad(
            [self.padre], self.admin, hoy=date(2026, 8, 22))
        self.assertFalse(acciones[self.padre.pk]['puede_declarar'])
        self.assertFalse(acciones[self.padre.pk]['puede_reabrir'])
        self.assertFalse(acciones[self.padre.pk]['autorizado'])

    # --- Independencia entre hijas (y frente al padre) ---

    def test_declarar_una_hija_no_declara_a_su_hermana_ni_al_padre(self):
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 8, 22))

        self.assertTrue(CierreUnidad.objects.filter(unidad=self.hija_a).exists())
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.hija_b).exists())
        self.assertFalse(CierreUnidad.objects.filter(unidad=self.padre).exists())

    def test_la_fotografia_de_una_hija_no_incluye_cargos_de_la_otra(self):
        """`Departamento.unidad_organizativa` apunta a una sola unidad."""
        cierre_a = servicios.declarar_actualizada(
            self.hija_a, self.admin, hoy=date(2026, 8, 22))

        ids_capturados = set(cierre_a.cargos.values_list('cargo_id_original', flat=True))
        self.assertIn(self.cargo_a.pk, ids_capturados)
        self.assertNotIn(self.cargo_b.pk, ids_capturados)

    def test_cada_hija_tiene_su_propio_estado_independiente(self):
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 8, 22))

        acciones = integracion.acciones_por_unidad(
            [self.hija_a, self.hija_b], self.admin, hoy=date(2026, 8, 22))

        self.assertFalse(acciones[self.hija_a.pk]['puede_declarar'])  # ya declaró
        self.assertTrue(acciones[self.hija_a.pk]['puede_reabrir'])
        self.assertTrue(acciones[self.hija_b.pk]['puede_declarar'])   # independiente
        self.assertFalse(acciones[self.hija_b.pk]['puede_reabrir'])

    def test_el_gestor_da_entradas_separadas_a_padre_e_hijas(self):
        """`anotar_acciones` (el que usa `gestor_plantilla_view`) recorre las
        hijas dentro de `direcciones_hijas` y les da SU PROPIA entrada."""
        unidades = list(UnidadOrganizativa.objects
                        .filter(pk=self.padre.pk)
                        .prefetch_related('direcciones_hijas'))
        integracion.anotar_acciones(unidades, self.admin, hoy=date(2026, 8, 22))

        padre = unidades[0]
        hijas_anotadas = {h.pk: h for h in padre.direcciones_hijas.all()}
        self.assertTrue(hasattr(padre, 'acciones_cierre'))
        self.assertIn(self.hija_a.pk, hijas_anotadas)
        self.assertTrue(hasattr(hijas_anotadas[self.hija_a.pk], 'acciones_cierre'))

    # --- Color agregado del padre: el peor color entre sus hijas ---

    def test_padre_verde_si_todas_las_hijas_declararon_el_mes_en_curso(self):
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 8, 22))
        servicios.declarar_actualizada(self.hija_b, self.admin, hoy=date(2026, 8, 22))

        acciones = integracion.acciones_por_unidad(
            [self.padre, self.hija_a, self.hija_b], self.admin, hoy=date(2026, 8, 24))

        self.assertEqual(acciones[self.hija_a.pk]['color'], COLOR_VERDE)
        self.assertEqual(acciones[self.hija_b.pk]['color'], COLOR_VERDE)
        self.assertEqual(acciones[self.padre.pk]['color'], COLOR_VERDE)

    def test_padre_rojo_si_una_sola_hija_esta_desactualizada(self):
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 7, 22))
        servicios.declarar_actualizada(self.hija_b, self.admin, hoy=date(2026, 7, 22))
        # hija_a se pone al día en agosto; hija_b deja pasar el plazo.
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 8, 22))

        acciones = integracion.acciones_por_unidad(
            [self.padre, self.hija_a, self.hija_b], self.admin, hoy=date(2026, 8, 27))

        self.assertEqual(acciones[self.hija_a.pk]['color'], COLOR_VERDE)
        self.assertEqual(acciones[self.hija_b.pk]['color'], COLOR_ROJO)
        self.assertEqual(acciones[self.padre.pk]['color'], COLOR_ROJO)

    def test_padre_naranja_si_ninguna_roja_pero_alguna_pendiente_en_ventana(self):
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 7, 22))
        servicios.declarar_actualizada(self.hija_b, self.admin, hoy=date(2026, 7, 22))
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 8, 22))
        # hija_b sigue sin declarar agosto; estamos dentro de la ventana.

        acciones = integracion.acciones_por_unidad(
            [self.padre, self.hija_a, self.hija_b], self.admin, hoy=date(2026, 8, 23))

        self.assertEqual(acciones[self.hija_b.pk]['color'], COLOR_NARANJA)
        self.assertEqual(acciones[self.padre.pk]['color'], COLOR_NARANJA)

    def test_padre_azul_si_todas_al_dia_pero_ninguna_declaro_este_mes(self):
        servicios.declarar_actualizada(self.hija_a, self.admin, hoy=date(2026, 7, 22))
        servicios.declarar_actualizada(self.hija_b, self.admin, hoy=date(2026, 7, 22))
        # Agosto, día 10: la ventana de agosto aún no ha abierto.

        acciones = integracion.acciones_por_unidad(
            [self.padre, self.hija_a, self.hija_b], self.admin, hoy=date(2026, 8, 10))

        self.assertEqual(acciones[self.hija_a.pk]['color'], COLOR_AZUL)
        self.assertEqual(acciones[self.hija_b.pk]['color'], COLOR_AZUL)
        self.assertEqual(acciones[self.padre.pk]['color'], COLOR_AZUL)

    def test_padre_rojo_si_ninguna_hija_ha_declarado_nunca(self):
        acciones = integracion.acciones_por_unidad(
            [self.padre, self.hija_a, self.hija_b], self.admin, hoy=date(2026, 8, 22))

        self.assertEqual(acciones[self.hija_a.pk]['color'], COLOR_ROJO)
        self.assertEqual(acciones[self.padre.pk]['color'], COLOR_ROJO)

    def test_padre_gris_sin_ninguna_hija(self):
        tipo_solo = NTipoUnidadOrganizativa.objects.create(
            descripcion='Direccion Sola', es_principal=True)
        padre_solo = UnidadOrganizativa.objects.create(
            descripcion='Sin Hijas', tipo=tipo_solo, grupo_nomina=1)

        acciones = integracion.acciones_por_unidad(
            [padre_solo], self.admin, hoy=date(2026, 8, 22))
        self.assertEqual(acciones[padre_solo.pk]['color'], COLOR_SIN_HIJAS)

    def test_procesar_barrido_no_avisa_a_los_padres(self):
        """Un padre nunca podrá declarar, así que reclamarle un cierre sería
        ruido: `procesar_barrido` debe saltárselo en el bucle de avisos."""
        from notificaciones.models import Notificacion
        from django.contrib.contenttypes.models import ContentType
        from strorganizativa.models import UnidadOrganizativa as UO

        servicios.procesar_barrido(usuario=self.admin, hoy=date(2026, 8, 26))

        ct_unidad = ContentType.objects.get_for_model(UO)
        avisos_al_padre = Notificacion.objects.filter(
            content_type=ct_unidad, object_id=str(self.padre.pk))
        self.assertFalse(avisos_al_padre.exists())


class ToolbarDelGestor(BaseCierres):
    """Lo que el Gestor de Plantilla necesita para pintar sus botones."""

    def _acciones(self, usuario, hoy):
        unidades = list(UnidadOrganizativa.objects.prefetch_related('direcciones_hijas'))
        integracion.anotar_acciones(unidades, usuario, hoy)
        return {u.pk: u.acciones_cierre for u in unidades}

    def test_dentro_de_la_ventana_se_ofrece_declarar(self):
        acciones = self._acciones(self.admin, date(2026, 8, 22))
        self.assertTrue(acciones[self.unidad.pk]['puede_declarar'])
        self.assertEqual(acciones[self.unidad.pk]['etiqueta_declarable'], 'Agosto 2026')

    def test_antes_del_dia_20_no_se_ofrece(self):
        acciones = self._acciones(self.admin, date(2026, 8, 5))
        self.assertFalse(acciones[self.unidad.pk]['puede_declarar'])

    def test_el_moderador_solo_puede_con_las_suyas(self):
        acciones = self._acciones(self.moderador, date(2026, 8, 22))
        self.assertTrue(acciones[self.unidad.pk]['puede_declarar'])
        self.assertFalse(acciones[self.otra_unidad.pk]['puede_declarar'])
        self.assertFalse(acciones[self.otra_unidad.pk]['autorizado'])

    def test_el_observador_no_puede_con_ninguna(self):
        observador = CustomUser.objects.create_user(
            username='obs_toolbar', password='x', es_observador=True)
        acciones = self._acciones(observador, date(2026, 8, 22))
        self.assertFalse(acciones[self.unidad.pk]['puede_declarar'])
        self.assertFalse(acciones[self.unidad.pk]['puede_reabrir'])

    def test_tras_declarar_se_ofrece_reabrir_y_ya_no_declarar(self):
        self.declarar(hoy=date(2026, 8, 22))
        acciones = self._acciones(self.admin, date(2026, 8, 24))

        self.assertFalse(acciones[self.unidad.pk]['puede_declarar'])
        self.assertTrue(acciones[self.unidad.pk]['puede_reabrir'])

    def test_pasada_la_ventana_ya_no_se_ofrece_reabrir(self):
        self.declarar(hoy=date(2026, 8, 22))
        acciones = self._acciones(self.admin, date(2026, 8, 26))
        self.assertFalse(acciones[self.unidad.pk]['puede_reabrir'])

    def test_una_unidad_desactualizada_puede_regularizar_cualquier_dia(self):
        self.declarar(hoy=date(2026, 7, 22))
        acciones = self._acciones(self.admin, date(2026, 9, 10))

        self.assertTrue(acciones[self.unidad.pk]['puede_declarar'])
        self.assertEqual(acciones[self.unidad.pk]['etiqueta_declarable'], 'Agosto 2026')

    def test_las_subunidades_tambien_reciben_sus_acciones(self):
        # Una subunidad solo puede colgar de una Dirección Principal
        # (`UnidadOrganizativa.clean()` lo exige) — `self.unidad` es una UEB de
        # hoja, así que hace falta un padre genuino para esta prueba.
        tipo_padre = NTipoUnidadOrganizativa.objects.create(
            descripcion='Direccion Principal', es_principal=True)
        padre = UnidadOrganizativa.objects.create(
            descripcion='Central Norte', tipo=tipo_padre, grupo_nomina=5)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True, tipo_padre=tipo_padre)
        hija = UnidadOrganizativa.objects.create(
            descripcion='Sub Norte', tipo=tipo_sub, padre=padre, orden_informe=9)

        acciones = self._acciones(self.admin, date(2026, 8, 22))
        self.assertIn(hija.pk, acciones)
        self.assertTrue(acciones[hija.pk]['puede_declarar'])

    def test_el_gestor_expone_los_datos_en_la_fila(self):
        """La plantilla lee estos `data-*`; si cambian de nombre, el botón muere."""
        self.client.force_login(self.admin)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.get(reverse('gestor_plantilla'))

        self.assertContains(respuesta, 'data-url-declarar')
        self.assertContains(respuesta, 'data-puede-declarar="true"')
        self.assertContains(respuesta, 'data-periodo-declarable="Agosto 2026"')


class ProcesamientoManual(BaseCierres):
    """El barrido es una acción manual del Administrador, no una tarea del sistema."""

    def test_no_existe_ningun_comando_de_gestion(self):
        """Se eliminó a propósito: no debe poder programarse con schtasks."""
        from django.core.management import get_commands
        self.assertNotIn('procesar_cierres', get_commands())

    def test_solo_el_administrador_puede_lanzarlo(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.post(reverse('procesar_cierres'))
        self.assertEqual(respuesta.status_code, 403)

    def test_el_observador_tampoco(self):
        observador = CustomUser.objects.create_user(
            username='obs_procesa', password='x', es_observador=True)
        self.client.force_login(observador)
        respuesta = self.client.post(reverse('procesar_cierres'))
        self.assertEqual(respuesta.status_code, 403)

    def test_el_administrador_lo_lanza_y_recibe_el_resumen(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('procesar_cierres'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['status'], 'ok')
        self.assertIn('actualizada(s)', respuesta.json()['message'])

    def test_no_se_lanza_por_GET(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse('procesar_cierres')).status_code, 405)

    def test_marca_desactualizada_a_quien_dejo_pasar_el_plazo(self):
        self.declarar(hoy=date(2026, 7, 22))

        servicios.procesar_barrido(usuario=self.admin, hoy=date(2026, 8, 26))

        estado = EstadoCierreUnidad.objects.get(unidad=self.unidad)
        self.assertEqual(estado.estado, EstadoUnidad.DESACTUALIZADA)

    def test_no_reclama_a_quien_nunca_declaro(self):
        """Regla 4: sin primera declaración no hay obligación que incumplir."""
        servicios.procesar_barrido(usuario=self.admin, hoy=date(2026, 8, 26))

        estado = EstadoCierreUnidad.objects.get(unidad=self.unidad)
        self.assertEqual(estado.estado, EstadoUnidad.PENDIENTE)
        self.assertEqual(estado.meses_pendientes, 0)

    def test_repetirlo_no_duplica_avisos(self):
        from notificaciones.models import Notificacion
        self.declarar(hoy=date(2026, 7, 22))

        servicios.procesar_barrido(usuario=self.admin, hoy=date(2026, 8, 26))
        tras_una = Notificacion.objects.count()
        servicios.procesar_barrido(usuario=self.admin, hoy=date(2026, 8, 26))

        self.assertEqual(Notificacion.objects.count(), tras_una)

    def test_queda_registrado_en_auditoria(self):
        from auditoria.models import EventoAuditoria

        servicios.procesar_barrido(usuario=self.admin, hoy=date(2026, 8, 26))

        evento = EventoAuditoria.objects.filter(modulo='cierres').latest('fecha')
        self.assertIn('Procesamiento manual', evento.descriptor)
        self.assertEqual(evento.usuario, self.admin)


class PantallaDeConsulta(BaseCierres):
    """La app de Cierres se mantiene, pero ya no declara: solo consulta."""

    def test_el_observador_no_entra_al_modulo(self):
        observador = CustomUser.objects.create_user(
            username='obs_cierres', password='x', es_observador=True)
        self.client.force_login(observador)

        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.get(reverse('list_cierres'))
        self.assertEqual(respuesta.status_code, 403)

    def test_el_moderador_solo_ve_sus_unidades(self):
        self.client.force_login(self.moderador)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.get(reverse('list_cierres'))

        self.assertContains(respuesta, 'UEB Central')
        self.assertNotContains(respuesta, 'UEB Norte')

    def test_ya_no_ofrece_declarar_y_remite_al_gestor(self):
        self.client.force_login(self.admin)
        with fingir_hoy(date(2026, 8, 22)):
            respuesta = self.client.get(reverse('list_cierres'))

        self.assertNotContains(respuesta, 'Declarar Agosto 2026')
        self.assertContains(respuesta, 'Gestor de Plantilla')

    def test_el_boton_de_procesar_es_solo_para_el_administrador(self):
        with fingir_hoy(date(2026, 8, 22)):
            self.client.force_login(self.admin)
            self.assertContains(self.client.get(reverse('list_cierres')), 'btn-procesar')

            self.client.force_login(self.moderador)
            self.assertNotContains(self.client.get(reverse('list_cierres')), 'btn-procesar')

    def test_el_historial_muestra_los_cierres(self):
        self.declarar(hoy=date(2026, 8, 22))
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse('historial_cierres', args=[self.unidad.pk]))

        self.assertContains(respuesta, 'Agosto 2026')
        self.assertContains(respuesta, 'En plazo')

    def test_el_detalle_muestra_la_fotografia_congelada(self):
        cierre = self.declarar(hoy=date(2026, 8, 22))
        NCargo.objects.filter(pk=self.ncargo.pk).update(descripcion='Renombrado')
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('detalle_cierre', args=[cierre.pk]))

        self.assertContains(respuesta, 'Especialista B')
        self.assertNotContains(respuesta, 'Renombrado')
