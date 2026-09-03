"""Pruebas de la máquina de estados de Solicitudes.

Se centran en las reglas que no son evidentes leyendo el código y que, si se rompen,
fallan en silencio: que la propuesta no toque la base de datos hasta aprobarse, que la
fotografía sea inmutable, que el bloqueo de revisión realmente impida al Moderador actuar,
y que al aprobar se apliquen los valores del Administrador y no los del Moderador.

No se prueban las plantillas ni el HTML: se prueba `solicitudes/servicios.py`, que es el
único punto por el que pasa cualquier cambio de estado.
"""

import json
from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bolsa.models import Aspirante
from contratos.models import CAlta, CBaja
from nomencladores.forms import NCargoForm
from nomencladores.models import NCargo, NGrupoEscala
from solicitudes import filtros, serializacion, servicios
from solicitudes.models import EstadoSolicitud, Solicitud
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser


class BaseSolicitudes(TestCase):
    """Datos mínimos comunes: un moderador, un administrador y un NCargo real."""

    @classmethod
    def setUpTestData(cls):
        cls.grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista B',
            cat_ocupacional='TEC',
            grupo_escala=cls.grupo,
            salario_basico=4000)

        cls.admin = CustomUser.objects.create_user(
            username='admin_prueba', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='moderador_prueba', password='x', es_moderador=True)
        cls.otro_moderador = CustomUser.objects.create_user(
            username='moderador_dos', password='x', es_moderador=True)

    def _datos_ncargo(self, **cambios):
        """Datos de un NCargo, con los valores actuales salvo los que se cambien."""
        datos = {
            'descripcion': self.ncargo.descripcion,
            'cat_ocupacional': self.ncargo.cat_ocupacional,
            'grupo_escala': self.grupo.pk,
            'salario_basico': self.ncargo.salario_basico,
            'puesto_clave': self.ncargo.puesto_clave,
        }
        datos.update(cambios)
        return datos

    def _form_ncargo(self, **cambios):
        """Formulario válido de NCargo, para las llamadas que reciben un formulario."""
        formulario = NCargoForm(self._datos_ncargo(**cambios), instance=self.ncargo)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        return formulario

    def _solicitud_de_edicion(self, **cambios):
        return servicios.crear_solicitud(
            operacion='ncargo_upd',
            usuario=self.moderador,
            formulario=self._form_ncargo(**cambios),
            objeto=self.ncargo,
            motivo='Reajuste salarial')


class CreacionDeSolicitud(BaseSolicitudes):

    def test_no_modifica_el_registro_real(self):
        """Lo esencial del módulo: proponer no es aplicar."""
        self._solicitud_de_edicion(salario_basico=9999)

        self.ncargo.refresh_from_db()
        self.assertEqual(self.ncargo.salario_basico, 4000)

    def test_guarda_la_fotografia_del_estado_original(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)

        self.assertEqual(solicitud.datos_originales['salario_basico'], '4000.00')
        self.assertEqual(solicitud.datos_propuestos['salario_basico'], '9999')
        self.assertEqual(solicitud.estado, EstadoSolicitud.EN_ESPERA)

    def test_bloquea_una_segunda_solicitud_sobre_el_mismo_registro(self):
        self._solicitud_de_edicion(salario_basico=9999)

        with self.assertRaises(servicios.ErrorDeSolicitud) as contexto:
            servicios.crear_solicitud(
                operacion='ncargo_upd',
                usuario=self.otro_moderador,
                formulario=self._form_ncargo(salario_basico=5555),
                objeto=self.ncargo,
                motivo='Otro cambio')

        self.assertIn('Ya existe una solicitud pendiente', str(contexto.exception))
        self.assertEqual(Solicitud.objects.count(), 1)

    def test_ncargo_no_tiene_unidad_organizativa(self):
        """NCargo es un nomenclador global: se notifica a todos los administradores."""
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        self.assertIsNone(solicitud.unidad)


class NotificacionesDeSolicitud(BaseSolicitudes):
    """`solicitudes/avisos.py`: una fila de `Notificacion` por administrador y por
    solicitud, sin duplicarse aunque el aviso se dispare más de una vez para el mismo
    hecho (doble envío, reintento de red, workers concurrentes) — el bug real reportado
    en producción: una misma solicitud nueva le aparecía repetida varias veces (tantas
    como procesos/intentos coincidieran) a cada administrador."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.otro_admin = CustomUser.objects.create_user(
            username='admin_dos', password='x', es_admin=True)

    def _notificaciones_nueva_solicitud(self, solicitud):
        from notificaciones.models import Notificacion
        from solicitudes.avisos import CODIGO_NUEVA
        return Notificacion.objects.filter(
            content_type=ContentType.objects.get_for_model(solicitud),
            object_id=str(solicitud.pk), codigo_regla=CODIGO_NUEVA)

    def test_una_notificacion_por_administrador_activo(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)

        notificaciones = self._notificaciones_nueva_solicitud(solicitud)
        self.assertEqual(notificaciones.count(), 2)  # self.admin + self.otro_admin
        self.assertEqual(
            set(notificaciones.values_list('destinatario_id', flat=True)),
            {self.admin.pk, self.otro_admin.pk})

    def test_repetir_el_aviso_de_la_misma_solicitud_no_duplica(self):
        """Simula el disparo repetido del mismo aviso (reintento/doble envío): debe
        actualizar la fila existente, no crear una segunda."""
        from solicitudes import avisos

        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        for _ in range(7):  # mismo orden de magnitud que el caso real en producción
            avisos.avisar_nueva_solicitud(solicitud)

        notificaciones = self._notificaciones_nueva_solicitud(solicitud)
        self.assertEqual(notificaciones.count(), 2)  # sigue siendo una por administrador

    def test_la_restriccion_de_bd_impide_el_duplicado_directo(self):
        """La misma `UniqueConstraint` que protege Advertencias/Recordatorios cubre
        también estos avisos, ahora que llevan `codigo_regla` no vacío."""
        from django.db import IntegrityError, transaction

        from notificaciones.models import Notificacion
        from solicitudes.avisos import CODIGO_NUEVA

        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        tipo_ct = ContentType.objects.get_for_model(solicitud)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Notificacion.objects.create(
                    content_type=tipo_ct, object_id=str(solicitud.pk),
                    destinatario=self.admin, codigo_regla=CODIGO_NUEVA, clave_extra='',
                    titulo='Duplicado directo', mensaje='...', tipo=Notificacion.Tipo.EVENTO)

    def test_decision_no_duplica_al_repetirse(self):
        from notificaciones.models import Notificacion
        from solicitudes.avisos import CODIGO_DECISION

        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.rechazar(solicitud, self.admin, 'No procede.')
        solicitud.refresh_from_db()

        from solicitudes import avisos
        for _ in range(3):
            avisos.avisar_decision(solicitud)

        notificaciones = Notificacion.objects.filter(
            content_type=ContentType.objects.get_for_model(solicitud),
            object_id=str(solicitud.pk), codigo_regla=CODIGO_DECISION,
            destinatario=self.moderador)
        self.assertEqual(notificaciones.count(), 1)


class Visibilidad(BaseSolicitudes):

    def test_moderador_no_ve_las_solicitudes_de_otro_moderador(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)

        self.assertTrue(solicitud.es_visible_para(self.moderador))
        self.assertTrue(solicitud.es_visible_para(self.admin))
        self.assertFalse(solicitud.es_visible_para(self.otro_moderador))

    def test_observador_no_ve_ninguna(self):
        observador = CustomUser.objects.create_user(
            username='observador_prueba', password='x', es_observador=True)
        solicitud = self._solicitud_de_edicion(salario_basico=9999)

        self.assertFalse(solicitud.es_visible_para(observador))


class BloqueoDeRevision(BaseSolicitudes):

    def test_el_moderador_no_puede_editar_mientras_se_revisa(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        solicitud.refresh_from_db()

        self.assertTrue(solicitud.bloqueada)
        self.assertFalse(solicitud.puede_editarla(self.moderador))
        self.assertFalse(solicitud.puede_retirarla(self.moderador))

        with self.assertRaises(servicios.ErrorDeSolicitud):
            servicios.actualizar_propuesta(
                solicitud, self.moderador, self._form_ncargo(salario_basico=1))

    def test_otro_administrador_no_puede_revisar_a_la_vez(self):
        otro_admin = CustomUser.objects.create_user(
            username='admin_dos', password='x', es_admin=True)
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        solicitud.refresh_from_db()

        with self.assertRaises(servicios.ErrorDeSolicitud):
            servicios.iniciar_revision(solicitud, otro_admin)

    def test_el_bloqueo_caduca_a_los_treinta_minutos(self):
        """Si un Administrador cierra el navegador sin cancelar, la solicitud debe
        liberarse sola en vez de quedar inaccesible para siempre."""
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        Solicitud.objects.filter(pk=solicitud.pk).update(
            revision_iniciada=timezone.now() - timedelta(minutes=31))
        solicitud.refresh_from_db()

        self.assertFalse(solicitud.bloqueada)
        self.assertTrue(solicitud.puede_editarla(self.moderador))


class CancelarRevision(BaseSolicitudes):

    def test_devuelve_a_espera_sin_decidir_ni_guardar(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        solicitud = servicios.cancelar_revision(solicitud, self.admin)

        self.assertEqual(solicitud.estado, EstadoSolicitud.EN_ESPERA)
        self.assertIsNone(solicitud.revisor)
        self.assertIsNone(solicitud.revision_iniciada)
        self.assertFalse(solicitud.bloqueada)
        # Ni aprobada ni rechazada, y sin tocar el registro real.
        self.assertIsNone(solicitud.fecha_decision)
        self.ncargo.refresh_from_db()
        self.assertEqual(self.ncargo.salario_basico, 4000)

    def test_el_moderador_recupera_el_control(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        solicitud = servicios.cancelar_revision(solicitud, self.admin)

        self.assertTrue(solicitud.puede_editarla(self.moderador))
        self.assertTrue(solicitud.puede_retirarla(self.moderador))


class EdicionPorElModerador(BaseSolicitudes):

    def test_no_recaptura_la_fotografia(self):
        """El punto 10 de la especificación: la fotografía es del momento de creación.

        Aunque el registro real cambie por otra vía, la columna «Situación Actual» debe
        seguir contando cómo estaba cuando el Moderador propuso el cambio.
        """
        solicitud = self._solicitud_de_edicion(salario_basico=9999)

        # Alguien modifica el registro real por otra vía.
        NCargo.objects.filter(pk=self.ncargo.pk).update(salario_basico=7777)

        servicios.actualizar_propuesta(
            solicitud, self.moderador, self._form_ncargo(salario_basico=8888))
        solicitud.refresh_from_db()

        self.assertEqual(solicitud.datos_originales['salario_basico'], '4000.00')
        self.assertEqual(solicitud.datos_propuestos['salario_basico'], '8888')

    def test_detecta_que_el_registro_original_cambio(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        self.assertTrue(serializacion.coincide_con_registro(solicitud, NCargoForm))

        NCargo.objects.filter(pk=self.ncargo.pk).update(salario_basico=7777)
        solicitud.refresh_from_db()

        self.assertFalse(serializacion.coincide_con_registro(solicitud, NCargoForm))


class Decision(BaseSolicitudes):

    def test_aprobar_aplica_los_valores_del_administrador(self):
        """El Moderador pide 9999, el Administrador aprueba 5500: manda el Administrador."""
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        servicios.aprobar(solicitud, self.admin, self._datos_ncargo(salario_basico=5500))

        self.ncargo.refresh_from_db()
        self.assertEqual(int(self.ncargo.salario_basico), 5500)

        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)
        self.assertEqual(solicitud.decidida_por, self.admin)
        # Queda constancia de lo aprobado, no de lo pedido.
        self.assertEqual(solicitud.datos_propuestos['salario_basico'], '5500')

    def test_rechazar_no_toca_el_registro(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        servicios.rechazar(solicitud, self.admin, 'No procede este trimestre.')

        self.ncargo.refresh_from_db()
        self.assertEqual(self.ncargo.salario_basico, 4000)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.RECHAZADA)
        self.assertEqual(solicitud.motivo_decision, 'No procede este trimestre.')

    def test_el_moderador_no_puede_aprobar_ni_rechazar(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)

        with self.assertRaises(servicios.ErrorDeSolicitud):
            servicios.aprobar(solicitud, self.moderador, self._datos_ncargo())
        with self.assertRaises(servicios.ErrorDeSolicitud):
            servicios.rechazar(solicitud, self.moderador, 'no')

    def test_devolver_a_espera_solo_desde_rechazada(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.rechazar(solicitud, self.admin, 'Error de criterio.')

        solicitud = servicios.devolver_a_espera(solicitud, self.admin)
        self.assertEqual(solicitud.estado, EstadoSolicitud.EN_ESPERA)
        self.assertEqual(solicitud.motivo_decision, '')

        # Una aprobada ya aplicó su cambio: reabrirla no tendría sentido.
        servicios.aprobar(solicitud, self.admin, self._datos_ncargo(salario_basico=5000))
        with self.assertRaises(servicios.ErrorDeSolicitud):
            servicios.devolver_a_espera(solicitud, self.admin)

    def test_el_moderador_no_puede_devolver_una_rechazada(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.rechazar(solicitud, self.admin, 'No procede.')

        with self.assertRaises(servicios.ErrorDeSolicitud):
            servicios.devolver_a_espera(solicitud, self.moderador)


class FormularioDePropuesta(BaseSolicitudes):
    """Construir una propuesta no es guardar: se omiten solo las comprobaciones que
    protegen la escritura, nunca las reglas de negocio."""

    def test_no_rechaza_por_choque_con_lo_ya_guardado(self):
        """El Moderador debe poder proponer algo que hoy chocaría con la tabla; el
        conflicto lo resuelve el Administrador al aprobar."""
        Propuesta = serializacion.formulario_de_propuesta(NCargoForm)
        formulario = Propuesta(self._datos_ncargo(descripcion='Especialista B'))

        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_sigue_rechazando_los_datos_mal_puestos(self):
        Propuesta = serializacion.formulario_de_propuesta(NCargoForm)
        formulario = Propuesta(self._datos_ncargo(descripcion=''))

        self.assertFalse(formulario.is_valid())
        self.assertIn('descripcion', formulario.errors)

    def test_los_campos_solo_admin_conservan_su_valor(self):
        """Lo que usa `uniorg_upd` con `orden_informe`: el campo llega deshabilitado y
        conserva su valor aunque alguien manipule la petición."""
        Propuesta = serializacion.formulario_de_propuesta(
            NCargoForm, campos_solo_admin=('salario_basico',))
        formulario = Propuesta(
            self._datos_ncargo(salario_basico=9999), instance=self.ncargo)

        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(int(formulario.cleaned_data['salario_basico']), 4000)

    def test_campos_condicionales_respetan_lo_que_llega_en_el_post(self):
        """A diferencia de un campo con el widget deshabilitado a secas,
        `campos_condicionales` sí deja pasar lo que el Moderador propuso —lo habilitó su
        propio JavaScript según otra elección del formulario (ver `motivo` de
        `CAltaForm`, condicionado al tipo de contrato)."""
        from contratos.forms import CAltaForm

        Propuesta = serializacion.formulario_de_propuesta(
            CAltaForm, campos_condicionales=('motivo',))
        formulario = Propuesta()

        self.assertFalse(formulario.fields['motivo'].disabled)
        # El resto de los campos con widget deshabilitado sigue protegido igual.
        self.assertTrue(formulario.fields['fecha_alta'].disabled)


class FormularioDeAprobacion(BaseSolicitudes):
    """La pantalla de aprobación no tiene el JavaScript que la pantalla de edición usa
    para poder enviar campos con `disabled` fijo en el widget (ver
    `contratos/forms.py::CAltaForm.Meta.widgets`). `formulario_de_aprobacion` protege
    esos campos igual que `formulario_de_propuesta`, pero sin tocar `campos_solo_admin`:
    esos el Administrador sí debe poder decidirlos en este paso."""

    def test_neutraliza_los_campos_con_widget_deshabilitado(self):
        from contratos.forms import CAltaForm

        Aprobacion = serializacion.formulario_de_aprobacion(CAltaForm)
        formulario = Aprobacion()

        for nombre in ('fecha_alta', 'motivo', 'duracion', 'fecha_vence_lic',
                       'fecha_vence_recal', 'fecha_vence_seg', 'c_formal_res',
                       'funcionario_res', 'designado_res', 'pais'):
            self.assertTrue(formulario.fields[nombre].disabled, nombre)
        # Un campo normal, editable en cualquier pantalla, no se toca.
        self.assertFalse(formulario.fields['no_expediente'].disabled)

    def test_no_neutraliza_campos_solo_admin(self):
        """A diferencia de `formulario_de_propuesta`, esta variante no recibe
        `campos_solo_admin`: no tiene forma de deshabilitarlos aunque quisiera, y es
        justo lo que se necesita, porque el Administrador sí puede decidirlos aquí."""
        Aprobacion = serializacion.formulario_de_aprobacion(NCargoForm)
        formulario = Aprobacion()

        self.assertFalse(formulario.fields['salario_basico'].disabled)


class Comparacion(BaseSolicitudes):

    def test_solo_marca_los_campos_que_cambian(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        cambiados = serializacion.comparar(
            solicitud.datos_originales, solicitud.datos_propuestos)

        self.assertEqual(cambiados, {'salario_basico'})

    def test_no_marca_diferencias_de_formato(self):
        """'4000.00' y '4000' son el mismo número: no debe resaltarse como cambio."""
        solicitud = self._solicitud_de_edicion()
        cambiados = serializacion.comparar(
            solicitud.datos_originales, solicitud.datos_propuestos)

        self.assertEqual(cambiados, set())

    def test_muestra_valores_legibles_y_no_claves(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        textos = serializacion.para_mostrar(NCargoForm, solicitud.datos_originales)

        self.assertEqual(textos['grupo_escala'], 'IV')
        self.assertEqual(textos['cat_ocupacional'], 'Técnico')


class SolicitudDeCreacion(BaseSolicitudes):
    """Un alta propuesta no debe existir en la base de datos hasta que se apruebe."""

    def _datos_nuevo(self, descripcion='Analista A'):
        return {
            'descripcion': descripcion,
            'cat_ocupacional': 'TEC',
            'grupo_escala': self.grupo.pk,
            'salario_basico': 3000,
            'puesto_clave': False,
        }

    def _form_nuevo(self, descripcion='Analista A'):
        formulario = NCargoForm(self._datos_nuevo(descripcion))
        self.assertTrue(formulario.is_valid(), formulario.errors)
        return formulario

    def test_el_registro_no_existe_hasta_aprobar(self):
        solicitud = servicios.crear_solicitud(
            operacion='ncargo_add', usuario=self.moderador,
            formulario=self._form_nuevo(), objeto=None, motivo='Nueva plaza')

        self.assertFalse(NCargo.objects.filter(descripcion='Analista A').exists())
        self.assertEqual(solicitud.datos_originales, {})

        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin, self._datos_nuevo())

        self.assertTrue(NCargo.objects.filter(descripcion='Analista A').exists())


class ContadorDePendientes(BaseSolicitudes):
    """`solicitudes.filtros.contar_pendientes`, la fuente del badge rojo de "Solicitudes"
    en la sidebar (ver `core/context_processors.py::_contar_solicitudes_pendientes`)."""

    def _solicitud_de_alta(self, usuario, descripcion='Analista A'):
        formulario = NCargoForm({
            'descripcion': descripcion, 'cat_ocupacional': 'TEC',
            'grupo_escala': self.grupo.pk, 'salario_basico': 3000,
            'puesto_clave': False,
        })
        self.assertTrue(formulario.is_valid(), formulario.errors)
        return servicios.crear_solicitud(
            operacion='ncargo_add', usuario=usuario, formulario=formulario,
            objeto=None, motivo='Nueva plaza')

    def test_el_administrador_ve_el_total_de_todas(self):
        self._solicitud_de_edicion(salario_basico=9999)
        self._solicitud_de_alta(self.otro_moderador)

        self.assertEqual(filtros.contar_pendientes(self.admin), 2)

    def test_el_moderador_ve_solo_las_suyas(self):
        self._solicitud_de_edicion(salario_basico=9999)
        self._solicitud_de_alta(self.otro_moderador)

        self.assertEqual(filtros.contar_pendientes(self.moderador), 1)
        self.assertEqual(filtros.contar_pendientes(self.otro_moderador), 1)

    def test_no_cuenta_las_ya_decididas(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin, self._datos_ncargo(salario_basico=5000))

        self.assertEqual(filtros.contar_pendientes(self.admin), 0)
        self.assertEqual(filtros.contar_pendientes(self.moderador), 0)


class Pantallas(BaseSolicitudes):
    """Recorrido por HTTP: comprueba que las plantillas se renderizan de verdad y que los
    permisos se aplican en las vistas, no solo en los servicios."""

    def test_el_listado_carga_para_moderador_y_administrador(self):
        self._solicitud_de_edicion(salario_basico=9999)

        for usuario in (self.moderador, self.admin):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                respuesta = self.client.get('/solicitudes/')
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'Especialista B')

    def test_el_observador_no_entra_al_modulo(self):
        observador = CustomUser.objects.create_user(
            username='observador_web', password='x', es_observador=True)
        self.client.force_login(observador)

        self.assertEqual(self.client.get('/solicitudes/').status_code, 403)

    def test_el_moderador_no_ve_las_solicitudes_de_otros_en_el_listado(self):
        self._solicitud_de_edicion(salario_basico=9999)
        self.client.force_login(self.otro_moderador)

        respuesta = self.client.get('/solicitudes/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, 'Especialista B')

    def test_la_pantalla_de_revision_muestra_ambas_columnas(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        self.client.force_login(self.admin)

        respuesta = self.client.get(f'/solicitudes/{solicitud.pk}/revisar/')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Situación Actual')
        self.assertContains(respuesta, 'Cambio propuesto por')
        # El campo modificado debe venir resaltado.
        self.assertContains(respuesta, 'campo-modificado')
        # Y la solicitud queda bloqueada por haber entrado a revisarla.
        solicitud.refresh_from_db()
        self.assertTrue(solicitud.bloqueada)

    def test_el_moderador_no_puede_abrir_la_revision(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        self.client.force_login(self.moderador)

        respuesta = self.client.get(f'/solicitudes/{solicitud.pk}/revisar/')
        self.assertEqual(respuesta.status_code, 403)

    def test_el_moderador_no_puede_editar_mientras_se_revisa(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        self.client.force_login(self.moderador)
        respuesta = self.client.get(f'/solicitudes/{solicitud.pk}/editar/', follow=True)

        # Se le devuelve al listado con el aviso, sin abrir el formulario.
        self.assertNotContains(respuesta, 'Guardar cambios en la solicitud')

    def test_cancelar_revision_no_guarda_lo_escrito(self):
        """El Administrador cambia un valor y pulsa Cancelar: no debe quedar rastro."""
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)

        self.client.post(f'/solicitudes/{solicitud.pk}/cancelar/', {
            'descripcion': 'Nombre cambiado por el admin',
            'salario_basico': 1234,
        })

        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.EN_ESPERA)
        self.assertEqual(solicitud.datos_propuestos['salario_basico'], '9999')
        self.assertEqual(solicitud.datos_propuestos['descripcion'], 'Especialista B')
        self.ncargo.refresh_from_db()
        self.assertEqual(self.ncargo.salario_basico, 4000)

    def test_aprobar_por_http_aplica_los_valores_del_administrador(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)

        self.client.post(f'/solicitudes/{solicitud.pk}/aprobar/', {
            'descripcion': 'Especialista B',
            'cat_ocupacional': 'TEC',
            'grupo_escala': self.grupo.pk,
            'salario_basico': 5500,
            'puesto_clave': False,
        })

        self.ncargo.refresh_from_db()
        self.assertEqual(int(self.ncargo.salario_basico), 5500)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)

    def test_rechazar_sin_motivo_no_decide_nada(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)

        respuesta = self.client.post(f'/solicitudes/{solicitud.pk}/rechazar/', {
            'motivo_decision': ''})

        self.assertEqual(respuesta.status_code, 422)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.EN_REVISION)

    def test_la_pantalla_de_lectura_no_trae_formulario_editable(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.rechazar(solicitud, self.admin, 'No procede.')

        self.client.force_login(self.moderador)
        respuesta = self.client.get(f'/solicitudes/{solicitud.pk}/')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No procede.')
        self.assertNotContains(respuesta, 'Aprobar solicitud')

    def test_la_busqueda_htmx_devuelve_solo_las_filas(self):
        self._solicitud_de_edicion(salario_basico=9999)
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            '/solicitudes/buscar/', {'q': 'Especialista'}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Especialista B')
        self.assertNotContains(respuesta, '<html')


class ConfiguracionCerrada(BaseSolicitudes):
    """El flujo de NCargo solo tiene sentido si el Moderador no puede editarlo por su
    cuenta. Antes las APIs de nomencladores no comprobaban rol."""

    def test_el_moderador_no_entra_a_parametros_generales(self):
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.get(reverse('parametros')).status_code, 403)

    def test_el_moderador_no_puede_editar_un_ncargo_por_la_api(self):
        self.client.force_login(self.moderador)

        respuesta = self.client.put(
            reverse('cargo-update', args=[self.ncargo.pk]),
            data=json.dumps({
                'descripcion': 'Colado', 'cat_ocupacional': 'TEC',
                'grupo_escala_id': self.grupo.pk, 'salario_basico': 1}),
            content_type='application/json')

        self.assertEqual(respuesta.status_code, 403)
        self.ncargo.refresh_from_db()
        self.assertEqual(self.ncargo.descripcion, 'Especialista B')

    def test_el_administrador_si_puede(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('parametros')).status_code, 200)


class BaseDepartamento(TestCase):
    """Estructura mínima para probar el desvío de los formularios de Departamento."""

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import NTipoUnidadOrganizativa

        cls.tipo = NTipoUnidadOrganizativa.objects.create(
            descripcion='Empresa', es_principal=True)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo, grupo_nomina=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad, orden_informe=1)

        cls.admin = CustomUser.objects.create_user(
            username='admin_del', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='moderador_del', password='x', es_moderador=True)
        # El formulario acota las unidades a las del usuario: sin esto, el desplegable
        # llegaría vacío y la validación fallaría por un motivo que no se está probando.
        cls.moderador.unidades.add(cls.unidad)


class DesvioDeFormulariosExistentes(BaseDepartamento):
    """Las operaciones de Departamento nacen de su propio formulario, no de la tabla de
    Solicitudes. Para el Moderador, ese formulario deja de guardar y pasa a proponer."""

    def test_el_moderador_no_crea_el_departamento_sino_una_solicitud(self):
        self.client.force_login(self.moderador)

        self.client.post(reverse('add_dpto'), {
            'descripcion': 'Recursos Humanos',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 5,
        }, HTTP_HX_REQUEST='true')

        self.assertFalse(Departamento.objects.filter(descripcion='Recursos Humanos').exists())
        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.operacion, 'dpto_add')
        self.assertEqual(solicitud.solicitante, self.moderador)
        self.assertEqual(solicitud.unidad, self.unidad)
        self.assertEqual(solicitud.datos_originales, {})

    def test_el_administrador_guarda_directamente(self):
        """El desvío es transparente para quien no necesita aprobación."""
        self.client.force_login(self.admin)

        self.client.post(reverse('add_dpto'), {
            'descripcion': 'Recursos Humanos',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 5,
        }, HTTP_HX_REQUEST='true')

        self.assertTrue(Departamento.objects.filter(descripcion='Recursos Humanos').exists())
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_la_edicion_guarda_la_fotografia_anterior(self):
        """Comprueba el punto delicado: la fotografía no puede salir contaminada con los
        datos que trae el formulario."""
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_dpto', args=[self.departamento.pk]), {
            'descripcion': 'Contabilidad y Finanzas',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 1,
        }, HTTP_HX_REQUEST='true')

        self.departamento.refresh_from_db()
        self.assertEqual(self.departamento.descripcion, 'Contabilidad')

        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.datos_originales['descripcion'], 'Contabilidad')
        self.assertEqual(solicitud.datos_propuestos['descripcion'], 'Contabilidad y Finanzas')
        self.assertEqual(
            serializacion.comparar(solicitud.datos_originales, solicitud.datos_propuestos),
            {'descripcion'})

    def test_el_moderador_no_elimina_sino_que_lo_solicita(self):
        self.client.force_login(self.moderador)

        self.client.post(reverse('del_dpto', args=[self.departamento.pk]))

        self.assertTrue(Departamento.objects.filter(pk=self.departamento.pk).exists())
        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.operacion, 'dpto_del')
        self.assertTrue(solicitud.es_eliminacion)

    def test_el_moderador_propone_una_posicion_ocupada_sin_mover_nada(self):
        """Proponer no es ejecutar.

        El Moderador puede pedir la posición 2 aunque esté tomada: al enviar no se
        desplaza ni un registro. El conflicto lo resuelve el Administrador al aprobar.
        """
        otro = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=self.unidad, orden_informe=2)
        self.client.force_login(self.moderador)

        self.client.post(reverse('add_dpto'), {
            'descripcion': 'Nuevo',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 2,
        }, HTTP_HX_REQUEST='true')

        # La propuesta queda registrada...
        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.datos_propuestos['orden_informe'], 2)
        # ...y la plantilla real sigue intacta.
        otro.refresh_from_db()
        self.assertEqual(otro.orden_informe, 2)
        self.assertFalse(Departamento.objects.filter(descripcion='Nuevo').exists())

    def test_al_aprobar_se_desplazan_las_posiciones(self):
        """El desplazamiento ocurre en la aprobación, con la posición final del Administrador."""
        otro = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=self.unidad, orden_informe=2)
        self.client.force_login(self.moderador)
        self.client.post(reverse('add_dpto'), {
            'descripcion': 'Nuevo',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 2,
        }, HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)

        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]), {
            'descripcion': 'Nuevo',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 2,
        })

        # Ahora sí: el departamento existe en la posición 2 y «Almacén» se corrió.
        nuevo = Departamento.objects.get(descripcion='Nuevo')
        self.assertEqual(nuevo.orden_informe, 2)
        otro.refresh_from_db()
        self.assertEqual(otro.orden_informe, 3)

    def test_el_administrador_puede_cambiar_la_posicion_al_aprobar(self):
        """Se ejecuta el estado final que dejó el Administrador, no el que pidió el Moderador."""
        otro = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=self.unidad, orden_informe=2)
        self.client.force_login(self.moderador)
        self.client.post(reverse('add_dpto'), {
            'descripcion': 'Nuevo',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 2,
        }, HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)

        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]), {
            'descripcion': 'Nuevo',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 7,          # el Administrador decide otra posición
        })

        nuevo = Departamento.objects.get(descripcion='Nuevo')
        self.assertEqual(nuevo.orden_informe, 7)
        # Como la posición elegida estaba libre, no se descoloca nada.
        otro.refresh_from_db()
        self.assertEqual(otro.orden_informe, 2)

    def test_el_administrador_sigue_desplazando_al_guardar_directamente(self):
        """El desvío no debe alterar el comportamiento de quien no necesita aprobación."""
        otro = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=self.unidad, orden_informe=2)
        self.client.force_login(self.admin)

        self.client.post(reverse('add_dpto'), {
            'descripcion': 'Nuevo',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 2,
            'autoriza_desplazamiento': 'true',
        }, HTTP_HX_REQUEST='true')

        otro.refresh_from_db()
        self.assertEqual(otro.orden_informe, 3)
        self.assertTrue(Departamento.objects.filter(descripcion='Nuevo').exists())
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_una_propuesta_invalida_no_crea_solicitud(self):
        """Las reglas de negocio siguen aplicando al proponer: solo se omiten las
        restricciones que protegen la escritura, que aquí no ocurre."""
        self.client.force_login(self.moderador)

        respuesta = self.client.post(reverse('add_dpto'), {
            'descripcion': '',                       # obligatorio
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 9,
        }, HTTP_HX_REQUEST='true')

        self.assertEqual(Solicitud.objects.count(), 0)
        self.assertEqual(respuesta.status_code, 200)   # se repinta el formulario

    def test_al_aprobar_se_aplica_el_cambio_de_verdad(self):
        """Recorrido completo: el Moderador propone por HTTP y el Administrador aprueba."""
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_dpto', args=[self.departamento.pk]), {
            'descripcion': 'Contabilidad y Finanzas',
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 1,
        }, HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)

        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]), {
            'descripcion': 'Contabilidad General',   # el Administrador ajusta la propuesta
            'unidad_organizativa': self.unidad.pk,
            'orden_informe': 1,
        })

        self.departamento.refresh_from_db()
        self.assertEqual(self.departamento.descripcion, 'Contabilidad General')
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)

    def test_el_moderador_no_puede_solicitar_edicion_fuera_de_su_unidad(self):
        otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=self.tipo, grupo_nomina=2)
        ajeno = Departamento.objects.create(
            descripcion='Nómina', unidad_organizativa=otra_unidad, orden_informe=1)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(reverse('updt_dpto', args=[ajeno.pk]), {
            'descripcion': 'Nómina Modificada',
            'unidad_organizativa': otra_unidad.pk,
            'orden_informe': 1,
        }, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.descripcion, 'Nómina')

    def test_el_moderador_no_puede_crear_departamento_en_otra_unidad(self):
        otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=self.tipo, grupo_nomina=2)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(reverse('add_dpto'), {
            'descripcion': 'Intruso',
            'unidad_organizativa': otra_unidad.pk,
            'orden_informe': 5,
        }, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)
        self.assertFalse(Departamento.objects.filter(descripcion='Intruso').exists())


class CargoPlantillaDesviado(BaseDepartamento):
    """Cargo Plantilla sigue el mismo criterio que Departamento."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from nomencladores.models import NGrupoEscala, NRol

        cls.grupo = NGrupoEscala.objects.create(nivel='IX')
        cls.rol = NRol.objects.create(tipo='Técnico')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista A', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=4000)
        cls.otro_ncargo = NCargo.objects.create(
            descripcion='Analista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=3000)
        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento, rol=cls.rol,
            cant_aprobada=3, orden_informe=1)

    def _url_add_cargo(self):
        """La aplicación abre este modal con `?departamento=` y postea a esa misma URL
        (`hx-post="{{ request.get_full_path }}"`), de donde la vista saca el contexto
        visual del formulario. El test replica ese flujo."""
        return f"{reverse('add_cargo')}?departamento={self.departamento.pk}"

    def _datos_cargo(self, **cambios):
        datos = {
            'unidad': self.unidad.pk,
            'ncargo': self.ncargo.pk,
            'departamento': self.departamento.pk,
            'rol': self.rol.pk,
            'cant_aprobada': 3,
            'cant_cubierta': 0,
            'orden_informe': 1,
        }
        datos.update(cambios)
        return datos

    def test_el_moderador_no_crea_el_cargo_sino_una_solicitud(self):
        self.client.force_login(self.moderador)

        self.client.post(self._url_add_cargo(), self._datos_cargo(
            ncargo=self.otro_ncargo.pk, orden_informe=2), HTTP_HX_REQUEST='true')

        self.assertEqual(CargoPlantilla.objects.count(), 1)
        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.operacion, 'cargo_add')
        # La unidad se resuelve por departamento, para el filtro y las notificaciones.
        self.assertEqual(solicitud.unidad, self.unidad)
        self.assertIn('Analista B', solicitud.descriptor)

    def test_la_edicion_guarda_la_fotografia_anterior(self):
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_cargo', args=[self.cargo.pk]),
                         self._datos_cargo(cant_aprobada=9), HTTP_HX_REQUEST='true')

        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.cant_aprobada, 3)

        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.datos_originales['cant_aprobada'], 3)
        self.assertEqual(solicitud.datos_propuestos['cant_aprobada'], 9)
        self.assertEqual(
            serializacion.comparar(solicitud.datos_originales, solicitud.datos_propuestos),
            {'cant_aprobada'})

    def test_el_moderador_no_elimina_sino_que_lo_solicita(self):
        self.client.force_login(self.moderador)

        self.client.post(reverse('del_cargoplantilla', args=[self.cargo.pk]))

        self.assertTrue(CargoPlantilla.objects.filter(pk=self.cargo.pk).exists())
        self.assertEqual(Solicitud.objects.get().operacion, 'cargo_del')

    def test_el_moderador_propone_posicion_ocupada_y_se_desplaza_al_aprobar(self):
        self.client.force_login(self.moderador)
        self.client.post(self._url_add_cargo(), self._datos_cargo(
            ncargo=self.otro_ncargo.pk, orden_informe=1), HTTP_HX_REQUEST='true')

        # Al proponer no se movió nada.
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.orden_informe, 1)

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]),
                         self._datos_cargo(ncargo=self.otro_ncargo.pk, orden_informe=1))

        # Al aprobar sí: el nuevo ocupa la posición 1 y el anterior se corre.
        nuevo = CargoPlantilla.objects.get(ncargo=self.otro_ncargo)
        self.assertEqual(nuevo.orden_informe, 1)
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.orden_informe, 2)

    def test_el_administrador_guarda_directamente(self):
        self.client.force_login(self.admin)

        self.client.post(self._url_add_cargo(), self._datos_cargo(
            ncargo=self.otro_ncargo.pk, orden_informe=5), HTTP_HX_REQUEST='true')

        self.assertEqual(CargoPlantilla.objects.count(), 2)
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_el_moderador_no_puede_solicitar_edicion_fuera_de_su_unidad(self):
        otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=self.tipo, grupo_nomina=2)
        otro_departamento = Departamento.objects.create(
            descripcion='Otro', unidad_organizativa=otra_unidad, orden_informe=1)
        ajeno = CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=otro_departamento, rol=self.rol,
            cant_aprobada=1, orden_informe=1)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('updt_cargo', args=[ajeno.pk]),
            self._datos_cargo(departamento=otro_departamento.pk, unidad=otra_unidad.pk),
            HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)


class UnidadOrganizativaDesviada(BaseDepartamento):
    """Editar una unidad asignada se pide por solicitud; crear y eliminar, ni eso.

    Y dentro de la edición, `orden_informe` queda fuera de lo que un Moderador puede
    proponer: reordenar el organigrama lo decide el Administrador.
    """

    def _datos_unidad(self, **cambios):
        datos = {
            'descripcion': self.unidad.descripcion,
            'tipo': self.tipo.pk,
            'grupo_nomina': self.unidad.grupo_nomina,
            'orden_informe': self.unidad.orden_informe or 1,
        }
        datos.update(cambios)
        return datos

    def test_el_moderador_no_modifica_la_unidad_sino_que_lo_solicita(self):
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_uniorg', args=[self.unidad.pk]),
                         self._datos_unidad(descripcion='UEB Norte'), HTTP_HX_REQUEST='true')

        self.unidad.refresh_from_db()
        self.assertEqual(self.unidad.descripcion, 'UEB Central')

        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.operacion, 'uniorg_upd')
        self.assertEqual(solicitud.datos_propuestos['descripcion'], 'UEB Norte')
        # La unidad de contexto es ella misma. `object_id` se guarda como texto porque su
        # clave primaria es `codigo_interno`, no un `id` autonumérico.
        self.assertEqual(solicitud.unidad, self.unidad)
        self.assertEqual(solicitud.object_id, str(self.unidad.pk))

    def test_solo_puede_editar_las_unidades_que_tiene_asignadas(self):
        ajena = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=self.tipo, grupo_nomina=2)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('updt_uniorg', args=[ajena.pk]),
            self._datos_unidad(descripcion='Intento'))

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_no_puede_crearlas_ni_eliminarlas(self):
        """Estas dos operaciones no están en el catálogo: no se pueden ni solicitar."""
        self.client.force_login(self.moderador)

        self.assertEqual(self.client.get(reverse('add_uniorg')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('del_uniorg', args=[self.unidad.pk])).status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)
        self.assertTrue(UnidadOrganizativa.objects.filter(pk=self.unidad.pk).exists())

    def test_el_moderador_no_puede_proponer_un_cambio_de_orden(self):
        """El campo llega deshabilitado, así que Django descarta lo que venga en el POST
        aunque alguien lo manipule."""
        self.unidad.orden_informe = 4
        self.unidad.save()
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_uniorg', args=[self.unidad.pk]),
                         self._datos_unidad(descripcion='UEB Norte', orden_informe=99),
                         HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.datos_propuestos['orden_informe'], 4)
        self.assertNotIn(
            'orden_informe',
            serializacion.comparar(solicitud.datos_originales, solicitud.datos_propuestos))

    def test_el_administrador_si_puede_cambiar_el_orden_al_aprobar(self):
        self.unidad.orden_informe = 4
        self.unidad.save()
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_uniorg', args=[self.unidad.pk]),
                         self._datos_unidad(descripcion='UEB Norte'), HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)

        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]),
                         self._datos_unidad(descripcion='UEB Norte', orden_informe=8))

        self.unidad.refresh_from_db()
        self.assertEqual(self.unidad.descripcion, 'UEB Norte')
        self.assertEqual(self.unidad.orden_informe, 8)

    def test_el_administrador_las_edita_directamente(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('updt_uniorg', args=[self.unidad.pk]),
                         self._datos_unidad(descripcion='UEB Sur'), HTTP_HX_REQUEST='true')

        self.unidad.refresh_from_db()
        self.assertEqual(self.unidad.descripcion, 'UEB Sur')
        self.assertEqual(Solicitud.objects.count(), 0)


class ContratoDesviado(BaseDepartamento):
    """Editar un contrato es la operación más delicada: al aprobar hay que dejarlo igual
    que si lo hubiera guardado un Administrador desde la pantalla de siempre."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from decimal import Decimal

        from nomencladores.models import (
            NGrupoEscala, NMotivoContrato, NMunicipio, NPagoAdicional, NProvincia,
            NRol, NTipoContrato, NTridente)

        # El importe sensible con el que se prueba el flujo de propuesta.
        #
        # Antes se usaba `maestria`, pero ese campo dejó de ser editable: se
        # rellena solo desde el nomenclador según el grado científico del
        # trabajador, así que un POST que lo cambie ya no produce ningún cambio.
        # `instructor_nomenclador` es su equivalente en el diseño nuevo — afecta
        # a la nómina, lo elige el usuario en un desplegable, y sigue estando
        # fuera de `campos_libres`, que es lo que estas pruebas ejercitan.
        cls.instructor = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.INSTRUCTOR, descripcion='Instructor Principal',
            importe=Decimal('150.00'))
        cls.otro_instructor = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.INSTRUCTOR, descripcion='Instructor Auxiliar',
            importe=Decimal('75.00'))

        cls.grupo = NGrupoEscala.objects.create(nivel='VII')
        cls.rol = NRol.objects.create(tipo='Técnico')
        cls.otro_rol = NRol.objects.create(tipo='Operario')
        cls.tridente = NTridente.objects.create(tipo='I')
        cls.tipo_contrato = NTipoContrato.objects.create(descripcion='Indeterminado')
        cls.motivo = NMotivoContrato.objects.create(
            descripcion='Renovación', tipo_contrato=cls.tipo_contrato)
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista C', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=3500)
        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento, rol=cls.rol,
            cant_aprobada=10, orden_informe=1)

        cls.provincia = NProvincia.objects.create(nombre='Artemisa', siglas='ART')
        cls.municipio = NMunicipio.objects.create(
            nombre='Bauta', provincia=cls.provincia, siglas='BAU')
        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Carlos', papellido='Soto', sapellido='Lima',
            doc_identidad='90010154321', estado='ACTIVO', sexo='M', raza='BL',
            unidad_organizativa=cls.unidad,
            provincia=cls.provincia, municipio=cls.municipio)
        cls.contrato = CAlta.objects.create(
            aspirante=cls.aspirante, no_expediente='00500',
            tipo=cls.tipo_contrato, cargo=cls.cargo, tridente=cls.tridente,
            fecha_alta=date(2026, 1, 15),
            # `CAltaForm` la exige (contratos/forms.py), asi que tiene que estar
            # tanto aqui como en `_datos_contrato`: si el POST la mandara y el
            # contrato no la tuviera, los atajos de "solo cambia campos libres"
            # la verian como un cambio mas y pedirian aprobacion.
            fecha_alta_entidad=date(2020, 3, 1),
            tipo_salario='DIN',
            # `rol` lo deriva del cargo la vista al guardar; se parte de otro valor a
            # propósito para comprobar que el ejecutor lo corrige igual que ella.
            rol=cls.otro_rol)

    def _datos_contrato(self, **cambios):
        datos = {
            'no_expediente': '00500',
            'tipo': self.tipo_contrato.pk,
            'fecha_alta': '2026-01-15',
            # Obligatoria en `CAltaForm`. Debe coincidir con la de la fixture y
            # no ser posterior a `fecha_alta` (lo valida `CAltaForm.clean`).
            'fecha_alta_entidad': '2020-03-01',
            'unidad': self.unidad.pk,
            'departamento': self.departamento.pk,
            'cargo': self.cargo.pk,
            'tridente': self.tridente.pk,
            'tipo_salario': 'DIN',
            'reg_militar': 'NIN',
            # Los cuatro importes (`maestria`, `doctorado`, `cnci`, `instructor`)
            # ya NO se mandan: viajan ocultos y `CAltaForm.clean()` los reescribe
            # en el servidor desde el nomenclador, así que lo que llegue en el
            # POST se ignora. Lo que el usuario sí elige son los desplegables
            # `instructor_nomenclador` y `cnci_nomenclador`.
            'instructor_nomenclador': '',
            'cnci_nomenclador': '',
        }
        datos.update(cambios)
        return datos

    def test_el_moderador_no_modifica_el_contrato_sino_que_lo_solicita(self):
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(instructor_nomenclador=self.instructor.pk), HTTP_HX_REQUEST='true')

        self.contrato.refresh_from_db()
        self.assertIsNone(self.contrato.instructor_nomenclador_id)

        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.operacion, 'contrato_upd')
        self.assertEqual(solicitud.datos_propuestos['instructor_nomenclador'],
                         self.instructor.pk)
        # La unidad se resuelve por la cadena cargo -> departamento -> unidad.
        self.assertEqual(solicitud.unidad, self.unidad)
        self.assertIn('Carlos', solicitud.descriptor)
        self.assertIn('00500', solicitud.descriptor)

    def test_el_moderador_guarda_directo_si_solo_cambia_reg_militar(self):
        """`reg_militar` está en `campos_libres` de `contrato_upd`: no requiere
        aprobación cuando es lo único que cambia."""
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(reg_militar='IMP'), HTTP_HX_REQUEST='true')

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.reg_militar, 'IMP')
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_el_moderador_guarda_directo_si_solo_cambia_motivo(self):
        """`motivo` también está en `campos_libres`. A diferencia del formulario de
        propuesta (que lo vería siempre como "sin cambios" por su widget deshabilitado
        en `Meta.widgets`), el atajo se decide con el ModelForm normal, que sí refleja
        el valor real que el Moderador quiso guardar."""
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(motivo=self.motivo.pk), HTTP_HX_REQUEST='true')

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.motivo, self.motivo)
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_el_moderador_guarda_directo_si_solo_cambia_fecha_alta_entidad(self):
        """`fecha_alta_entidad` está en `campos_libres` desde 2026-09: Subsanación se la
        reclama al Moderador contrato por contrato (CTR-016/CTR-017) y no tiene sentido
        que cada corrección genere una solicitud que el Administrador solo puede aceptar
        a ciegas."""
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(fecha_alta_entidad='2019-07-04'),
                         HTTP_HX_REQUEST='true')

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.fecha_alta_entidad, date(2019, 7, 4))
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_la_fecha_alta_entidad_propuesta_sobrevive_a_la_propuesta_y_a_la_aprobacion(self):
        """`fecha_alta_entidad` es `campos_condicionales`: su widget nace deshabilitado
        en `CAltaForm.Meta.widgets` y el propio formulario se lo habilita al cargar. Sin
        declararla, el formulario de propuesta la descartaba y al Administrador le
        llegaba el valor VIEJO del contrato por muy bien que el Moderador la enviara.

        Se combina con `instructor_nomenclador` (sensible) para que NO entre por el atajo de
        `campos_libres` y recorra el flujo completo, que es donde se perdía."""
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(fecha_alta_entidad='2019-07-04',
                                              instructor_nomenclador=self.instructor.pk),
                         HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        # La propuesta la capturó bien: no se quedó en el valor anterior (2020-03-01).
        self.assertEqual(solicitud.datos_propuestos['fecha_alta_entidad'], '2019-07-04')

        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]),
                         self._datos_contrato(fecha_alta_entidad='2019-07-04',
                                              instructor_nomenclador=self.instructor.pk))

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.fecha_alta_entidad, date(2019, 7, 4))
        self.assertEqual(self.contrato.instructor_nomenclador_id, self.instructor.pk)
        # El importe se copia del nomenclador, no viene del POST.
        self.assertEqual(self.contrato.instructor, self.instructor.importe)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)

    def test_el_administrador_puede_corregir_la_fecha_al_aprobar(self):
        """Al estar en `campos_condicionales`, la pantalla de revisión la pinta editable
        (`formulario_de_aprobacion`), así que lo que deje el Administrador manda."""
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(fecha_alta_entidad='2019-07-04',
                                              instructor_nomenclador=self.instructor.pk),
                         HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]),
                         self._datos_contrato(fecha_alta_entidad='2018-02-02',
                                              instructor_nomenclador=self.instructor.pk))

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.fecha_alta_entidad, date(2018, 2, 2))

    def test_el_moderador_sigue_necesitando_aprobacion_si_ademas_cambia_algo_sensible(self):
        """Si el envío toca `reg_militar` (libre) Y `instructor_nomenclador`
        (sensible) a la vez, todo
        el envío —incluido `reg_militar`— vuelve a pasar por el flujo normal."""
        self.client.force_login(self.moderador)

        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(reg_militar='IMP',
                                              instructor_nomenclador=self.instructor.pk),
                         HTTP_HX_REQUEST='true')

        self.contrato.refresh_from_db()
        # Ninguno de los dos se aplicó: al no ser subconjunto de `campos_libres`, todo
        # el envío pasa por el flujo normal de aprobación.
        self.assertIsNone(self.contrato.reg_militar)
        self.assertIsNone(self.contrato.instructor_nomenclador_id)

        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.datos_propuestos['reg_militar'], 'IMP')
        self.assertEqual(solicitud.datos_propuestos['instructor_nomenclador'],
                         self.instructor.pk)

    def test_el_motivo_propuesto_sobrevive_a_la_propuesta_y_a_la_aprobacion(self):
        """`motivo` es `campos_condicionales`: su widget nace deshabilitado igual que
        `fecha_alta` (ver `contratos/forms.py::CAltaForm.Meta.widgets`), pero a
        diferencia de ese sí debe aplicarse el valor que el Moderador eligió, no el que
        ya tenía el contrato. Se combina con `instructor_nomenclador` (sensible) para que NO entre por
        el atajo de `campos_libres` y pase por el flujo normal de propuesta/aprobación,
        que es donde antes se perdía en silencio."""
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(motivo=self.motivo.pk,
                                              instructor_nomenclador=self.instructor.pk),
                         HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        # La propuesta ya lo capturó bien: no quedó en el valor anterior (None).
        self.assertEqual(solicitud.datos_propuestos['motivo'], self.motivo.pk)

        servicios.iniciar_revision(solicitud, self.admin)
        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]),
                         self._datos_contrato(motivo=self.motivo.pk,
                                              instructor_nomenclador=self.instructor.pk))

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.motivo, self.motivo)
        self.assertEqual(self.contrato.instructor_nomenclador_id, self.instructor.pk)
        # El importe se copia del nomenclador, no viene del POST.
        self.assertEqual(self.contrato.instructor, self.instructor.importe)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)

    def test_al_aprobar_se_aplica_y_el_rol_sale_del_cargo(self):
        """`ContratoUpdateView.form_valid` deriva el rol del cargo en lugar de tomarlo
        del formulario. El ejecutor tiene que hacer lo mismo, o el resultado dependería
        de por dónde se guardó."""
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(instructor_nomenclador=self.instructor.pk), HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)

        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]),
                         self._datos_contrato(instructor_nomenclador=self.otro_instructor.pk))

        self.contrato.refresh_from_db()
        # Manda la elección del Administrador, no la que pidió el Moderador.
        self.assertEqual(self.contrato.instructor_nomenclador_id, self.otro_instructor.pk)
        self.assertEqual(self.contrato.rol, self.rol)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)

    def test_el_administrador_guarda_directamente(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(instructor_nomenclador=self.instructor.pk), HTTP_HX_REQUEST='true')

        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.instructor_nomenclador_id, self.instructor.pk)
        self.assertEqual(Solicitud.objects.count(), 0)

    def test_al_aprobar_no_se_pierde_fecha_alta_aunque_el_post_no_la_incluya(self):
        """Regresión: la pantalla de aprobación (`aprobar_solicitud`) no tiene el
        JavaScript que `updt_contrato.html` usa para poder enviar `fecha_alta` pese a su
        `disabled` fijo en el widget — un navegador real nunca la manda ahí.
        `_datos_contrato()` sí la incluye porque refleja el POST real de la pantalla de
        EDICIÓN; aquí se quita a propósito para reproducir el POST real de la pantalla
        de APROBACIÓN. Antes del arreglo, esto dejaba `fecha_alta` en `None`."""
        self.client.force_login(self.moderador)
        self.client.post(reverse('updt_contrato', args=[self.contrato.pk]),
                         self._datos_contrato(instructor_nomenclador=self.instructor.pk), HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)

        datos_aprobacion = self._datos_contrato(instructor_nomenclador=self.otro_instructor.pk)
        del datos_aprobacion['fecha_alta']

        self.client.force_login(self.admin)
        self.client.post(reverse('aprobar_solicitud', args=[solicitud.pk]), datos_aprobacion)

        self.contrato.refresh_from_db()
        # No se tocó: sigue con el valor real, no None.
        self.assertEqual(self.contrato.fecha_alta, date(2026, 1, 15))
        # Lo que sí cambió (el instructor) se aplicó con normalidad.
        self.assertEqual(self.contrato.instructor_nomenclador_id, self.otro_instructor.pk)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)

    def test_el_moderador_no_puede_solicitar_edicion_fuera_de_su_unidad(self):
        otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=self.tipo, grupo_nomina=2)
        otro_departamento = Departamento.objects.create(
            descripcion='Otro Depto', unidad_organizativa=otra_unidad, orden_informe=1)
        otro_cargo = CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=otro_departamento, rol=self.rol,
            cant_aprobada=2, orden_informe=1)
        otro_aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Luis', papellido='Diaz', sapellido='Rey',
            doc_identidad='90020198765', estado='ACTIVO', sexo='M', raza='BL',
            unidad_organizativa=otra_unidad,
            provincia=self.provincia, municipio=self.municipio)
        ajeno = CAlta.objects.create(
            aspirante=otro_aspirante, no_expediente='00999',
            tipo=self.tipo_contrato, cargo=otro_cargo, tridente=self.tridente,
            fecha_alta=date(2026, 2, 1), tipo_salario='DIN', rol=self.rol)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('updt_contrato', args=[ajeno.pk]),
            self._datos_contrato(cargo=otro_cargo.pk, departamento=otro_departamento.pk,
                                 unidad=otra_unidad.pk),
            HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.no_expediente, '00999')


class BorradoDeTrabajador(BaseDepartamento):
    """El botón «Eliminar» de la Lista de Bajas, que RRHH llama «eliminar contrato».

    Cubre además el arreglo del `on_delete`: `ContratoBase.aspirante` era `RESTRICT` y lo
    heredaban tanto `CAlta` como `CBaja`, así que toda persona de esa lista —que por
    definición tiene un `CBaja`— quedaba protegida y el botón fallaba siempre.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from nomencladores.models import (
            NGrupoEscala, NMunicipio, NProvincia, NTipoContrato)

        cls.grupo = NGrupoEscala.objects.create(nivel='V')
        cls.tipo_contrato = NTipoContrato.objects.create(descripcion='Determinado')
        cls.ncargo = NCargo.objects.create(
            descripcion='Auxiliar', cat_ocupacional='SER',
            grupo_escala=cls.grupo, salario_basico=2500)
        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento,
            cant_aprobada=5, orden_informe=1)
        # `Aspirante.clean()` exige que el municipio pertenezca a la provincia indicada.
        cls.provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        cls.municipio = NMunicipio.objects.create(
            nombre='Playa', provincia=cls.provincia, siglas='PLA')

    def _crear_aspirante(self, doc='85010112345', estado='BAJA', unidad=None):
        return Aspirante.objects.create(nivel_educ='SA', 
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad=doc, estado=estado, sexo='F', raza='BL',
            unidad_organizativa=unidad or self.unidad,
            provincia=self.provincia, municipio=self.municipio)

    def _dar_de_baja(self, aspirante, expediente='00101'):
        """Crea el registro histórico que antes bloqueaba el borrado."""
        return CBaja.objects.create(
            aspirante=aspirante, no_expediente=expediente,
            tipo=self.tipo_contrato, cargo=self.cargo)

    def test_el_administrador_ya_puede_eliminar_a_quien_tiene_baja(self):
        """Antes fallaba siempre con «tiene un historial de contratos o bajas asociado»."""
        aspirante = self._crear_aspirante()
        self._dar_de_baja(aspirante)
        self.client.force_login(self.admin)

        self.client.post(reverse('del_aspir', args=[aspirante.pk]), HTTP_HX_REQUEST='true')

        self.assertFalse(Aspirante.objects.filter(pk=aspirante.pk).exists())
        # El historial se va con la persona: es la consecuencia asumida del cambio.
        self.assertFalse(CBaja.objects.filter(aspirante_id=aspirante.pk).exists())

    def test_sigue_protegido_quien_tiene_contrato_activo(self):
        """`CAlta` conserva su RESTRICT: nadie con contrato vigente debe poder borrarse."""
        aspirante = self._crear_aspirante(doc='85010199999', estado='ACTIVO')
        CAlta.objects.create(
            aspirante=aspirante, no_expediente='00202',
            tipo=self.tipo_contrato, cargo=self.cargo)
        self.client.force_login(self.admin)

        self.client.post(reverse('del_aspir', args=[aspirante.pk]), HTTP_HX_REQUEST='true')

        self.assertTrue(Aspirante.objects.filter(pk=aspirante.pk).exists())

    def test_los_accesores_inversos_siguen_existiendo(self):
        """`cbaja_contratos` y `calta_contratos` los usa otro código del proyecto
        (por ejemplo `notificaciones/recordatorios.py`); redeclarar el campo no debe
        haberlos renombrado."""
        aspirante = self._crear_aspirante()
        self._dar_de_baja(aspirante)

        self.assertEqual(aspirante.cbaja_contratos.count(), 1)
        self.assertEqual(aspirante.calta_contratos.count(), 0)

    def test_el_moderador_no_elimina_sino_que_lo_solicita(self):
        aspirante = self._crear_aspirante()
        self._dar_de_baja(aspirante)
        self.client.force_login(self.moderador)

        self.client.post(reverse('del_aspir', args=[aspirante.pk]), HTTP_HX_REQUEST='true')

        self.assertTrue(Aspirante.objects.filter(pk=aspirante.pk).exists())
        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.operacion, 'aspirante_del')
        self.assertTrue(solicitud.es_eliminacion)
        self.assertIn('Ana', solicitud.descriptor)
        self.assertEqual(solicitud.unidad, self.unidad)

    def test_al_aprobar_se_elimina_de_verdad(self):
        aspirante = self._crear_aspirante()
        self._dar_de_baja(aspirante)
        self.client.force_login(self.moderador)
        self.client.post(reverse('del_aspir', args=[aspirante.pk]), HTTP_HX_REQUEST='true')

        solicitud = Solicitud.objects.get()
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin)

        self.assertFalse(Aspirante.objects.filter(pk=aspirante.pk).exists())
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.APROBADA)
        # El descriptor sobrevive al borrado, para el listado y la notificación.
        self.assertIn('Ana', solicitud.descriptor)

    def test_el_moderador_no_puede_solicitar_fuera_de_su_unidad(self):
        otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Ajena', tipo=self.tipo, grupo_nomina=2)
        ajeno = self._crear_aspirante(doc='85010177777', unidad=otra_unidad)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(reverse('del_aspir', args=[ajeno.pk]))

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Solicitud.objects.count(), 0)
        self.assertTrue(Aspirante.objects.filter(pk=ajeno.pk).exists())


class SolicitudDeEliminacion(BaseDepartamento):
    """La eliminación no propone datos: propone que desaparezca lo que hay."""

    def test_el_registro_sobrevive_hasta_la_aprobacion(self):
        solicitud = servicios.crear_solicitud(
            operacion='dpto_del', usuario=self.moderador, formulario=None,
            objeto=self.departamento, motivo='Ya no se usa')

        self.assertTrue(Departamento.objects.filter(pk=self.departamento.pk).exists())
        self.assertEqual(solicitud.datos_propuestos, {})
        self.assertTrue(solicitud.es_eliminacion)
        # La unidad se resuelve para el filtro y para saber a quién notificar.
        self.assertEqual(solicitud.unidad, self.unidad)

        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin)

        self.assertFalse(Departamento.objects.filter(pk=self.departamento.pk).exists())

    def test_el_descriptor_sobrevive_al_borrado(self):
        """Tras aprobar una eliminación, el listado y las notificaciones siguen
        pudiendo decir de qué registro se trataba."""
        solicitud = servicios.crear_solicitud(
            operacion='dpto_del', usuario=self.moderador, formulario=None,
            objeto=self.departamento, motivo='Ya no se usa')
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin)

        solicitud.refresh_from_db()
        self.assertIn('Contabilidad', solicitud.descriptor)
        self.assertIsNone(solicitud.objeto_afectado)
