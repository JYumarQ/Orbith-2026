"""Pruebas del motor de Auditoría integrado con Solicitudes (Fase C, alcance inicial).

Reutiliza `BaseSolicitudes` de `solicitudes/tests.py` (un moderador, un administrador y
un NCargo real) para no repetir la infraestructura. Se centra en lo que no es evidente
leyendo el código: que se registra lo que realmente ocurrió (no lo propuesto), que las
decisiones sin efecto real no dejan `datos_antes`/`datos_despues`, y que el módulo es
exclusivo del Administrador.
"""

from django.test import TestCase

from auditoria.models import AccionAuditoria, EventoAuditoria
from solicitudes import servicios
from solicitudes.models import EstadoSolicitud
from solicitudes.tests import BaseSolicitudes
from usuarios.models import CustomUser


class RegistroAlAprobar(BaseSolicitudes):

    def test_registra_lo_que_realmente_aprobo_el_administrador(self):
        """El Moderador pide 9999, el Administrador aprueba 5500: Auditoría debe
        registrar 4000 -> 5500, no 4000 -> 9999."""
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        servicios.aprobar(solicitud, self.admin, self._datos_ncargo(salario_basico=5500))

        evento = EventoAuditoria.objects.get()
        self.assertEqual(evento.accion, AccionAuditoria.MODIFICAR)
        self.assertEqual(evento.usuario, self.admin)
        self.assertEqual(evento.solicitud, solicitud)
        self.assertEqual(evento.datos_antes['salario_basico'], '4000.00')
        self.assertEqual(evento.datos_despues['salario_basico'], '5500')
        self.assertEqual(evento.content_type, solicitud.content_type)
        self.assertEqual(evento.object_id, str(self.ncargo.pk))

    def test_creacion_registra_el_pk_real_del_nuevo_registro(self):
        from nomencladores.forms import NCargoForm

        formulario = NCargoForm({
            'descripcion': 'Analista A', 'cat_ocupacional': 'TEC',
            'grupo_escala': self.grupo.pk, 'salario_basico': 3000,
            'puesto_clave': False,
        })
        self.assertTrue(formulario.is_valid(), formulario.errors)
        solicitud = servicios.crear_solicitud(
            operacion='ncargo_add', usuario=self.moderador,
            formulario=formulario, objeto=None, motivo='Nueva plaza')
        servicios.iniciar_revision(solicitud, self.admin)

        servicios.aprobar(solicitud, self.admin, {
            'descripcion': 'Analista A', 'cat_ocupacional': 'TEC',
            'grupo_escala': self.grupo.pk, 'salario_basico': 3000,
            'puesto_clave': False,
        })

        from nomencladores.models import NCargo
        nuevo = NCargo.objects.get(descripcion='Analista A')

        evento = EventoAuditoria.objects.get()
        self.assertEqual(evento.accion, AccionAuditoria.CREAR)
        self.assertEqual(evento.object_id, str(nuevo.pk))
        self.assertEqual(evento.datos_antes, {})
        self.assertEqual(evento.datos_despues['descripcion'], 'Analista A')

    def test_eliminacion_no_deja_datos_despues(self):
        from strorganizativa.models import Departamento, UnidadOrganizativa
        from nomencladores.models import NTipoUnidadOrganizativa

        tipo = NTipoUnidadOrganizativa.objects.create(
            descripcion='Empresa', es_principal=True)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Auditoría', tipo=tipo, grupo_nomina=9)
        departamento = Departamento.objects.create(
            descripcion='A eliminar', unidad_organizativa=unidad, orden_informe=1)

        solicitud = servicios.crear_solicitud(
            operacion='dpto_del', usuario=self.moderador, formulario=None,
            objeto=departamento, motivo='Ya no se usa')
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin)

        evento = EventoAuditoria.objects.get()
        self.assertEqual(evento.accion, AccionAuditoria.ELIMINAR)
        self.assertEqual(evento.datos_despues, {})
        self.assertTrue(evento.datos_antes)
        # El registro ya no existe, pero el rastro de qué se borró sigue siendo válido.
        self.assertEqual(evento.object_id, str(departamento.pk))


class RegistroDeDecisionesSinEfecto(BaseSolicitudes):

    def test_rechazar_no_deja_datos_antes_ni_despues(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        servicios.rechazar(solicitud, self.admin, 'No procede este trimestre.')

        evento = EventoAuditoria.objects.get()
        self.assertEqual(evento.accion, AccionAuditoria.RECHAZAR)
        self.assertEqual(evento.datos_antes, {})
        self.assertEqual(evento.datos_despues, {})
        self.assertEqual(evento.solicitud, solicitud)

    def test_cancelar_revision_registra_evento(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)

        servicios.cancelar_revision(solicitud, self.admin)

        evento = EventoAuditoria.objects.get()
        self.assertEqual(evento.accion, AccionAuditoria.CANCELAR)

    def test_devolver_a_espera_registra_evento(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.rechazar(solicitud, self.admin, 'Error de criterio.')

        servicios.devolver_a_espera(solicitud, self.admin)

        eventos = list(EventoAuditoria.objects.order_by('id').values_list('accion', flat=True))
        self.assertEqual(eventos, [AccionAuditoria.RECHAZAR, AccionAuditoria.DEVOLVER_A_ESPERA])

    def test_crear_y_actualizar_propuesta_no_registran_nada(self):
        """Proponer no es un efecto real: no debe generar eventos de Auditoría."""
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.actualizar_propuesta(
            solicitud, self.moderador, self._form_ncargo(salario_basico=8888))

        self.assertEqual(EventoAuditoria.objects.count(), 0)


class AccesoAlModulo(BaseSolicitudes):

    def test_solo_administrador_entra_al_listado(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/auditoria/').status_code, 200)

    def test_moderador_no_entra(self):
        self.client.force_login(self.moderador)
        self.assertEqual(self.client.get('/auditoria/').status_code, 403)

    def test_observador_no_entra(self):
        observador = CustomUser.objects.create_user(
            username='observador_auditoria', password='x', es_observador=True)
        self.client.force_login(observador)
        self.assertEqual(self.client.get('/auditoria/').status_code, 403)

    def test_el_listado_muestra_el_evento_y_permite_filtrar(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin, self._datos_ncargo(salario_basico=5500))
        self.client.force_login(self.admin)

        respuesta = self.client.get('/auditoria/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Especialista B')

        respuesta = self.client.get('/auditoria/buscar/', {'accion': 'REC'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, 'Especialista B')

    def test_el_detalle_muestra_la_comparacion(self):
        solicitud = self._solicitud_de_edicion(salario_basico=9999)
        servicios.iniciar_revision(solicitud, self.admin)
        servicios.aprobar(solicitud, self.admin, self._datos_ncargo(salario_basico=5500))
        evento = EventoAuditoria.objects.get()
        self.client.force_login(self.admin)

        respuesta = self.client.get(f'/auditoria/{evento.pk}/detalle/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, '4000.00')
        self.assertContains(respuesta, '5500')
