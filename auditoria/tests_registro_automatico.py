"""Pruebas del registro automático de Auditoría (`auditoria/registro_automatico.py`).

Lo que se comprueba es lo que no se ve leyendo el código: que solo queda lo que
cambió de verdad y legible, que lo derivado y lo borrado en cascada no generan
eventos propios, que los procesos auditados a mano no se duplican, y que la
limpieza respeta el plazo de Parámetros Generales.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auditoria import registro_automatico
from auditoria.limpieza import borrar_auditoria_antigua, fecha_limite
from auditoria.middleware import _user_ctx_var
from auditoria.models import AccionAuditoria, EventoAuditoria
from bolsa.models import Aspirante
from configuracion.forms import ConfiguracionForm
from configuracion.models import Configuracion
from contratos.models import CAlta, CBaja
from nomencladores.models import (NCargo, NCausaAltaBaja, NGrupoEscala, NMunicipio,
                                  NProvincia, NSalario, NTipoContrato,
                                  NTipoUnidadOrganizativa, NTridente)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser


def eventos(**filtros):
    """Los eventos de cambios (los inicios de sesión de los tests no cuentan)."""
    return EventoAuditoria.objects.exclude(
        accion__in=[AccionAuditoria.ACCESO, AccionAuditoria.ACCESO_FALLIDO,
                    AccionAuditoria.SALIDA]).filter(**filtros)


class BaseRegistro(TestCase):

    @classmethod
    def setUpTestData(cls):
        with registro_automatico.sin_auditoria_automatica():
            cls.admin = CustomUser.objects.create_user(
                username='admin_registro', password='x', es_admin=True,
                first_name='Ana', last_name='Admin')
            tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
            cls.unidad = UnidadOrganizativa.objects.create(
                descripcion='UEB Central', tipo=tipo, grupo_nomina=1, orden_informe=1)
            cls.otra_unidad = UnidadOrganizativa.objects.create(
                descripcion='UEB Norte', tipo=tipo, grupo_nomina=2, orden_informe=2)
            cls.departamento = Departamento.objects.create(
                descripcion='Contabilidad', unidad_organizativa=cls.unidad, orden_informe=1)
            cls.grupo = NGrupoEscala.objects.create(nivel='IV')
            cls.ncargo = NCargo.objects.create(
                descripcion='Especialista B', cat_ocupacional='TEC',
                grupo_escala=cls.grupo, salario_basico=4000)
            cls.cargo = CargoPlantilla.objects.create(
                ncargo=cls.ncargo, departamento=cls.departamento,
                cant_aprobada=10, orden_informe=1)
            cls.provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
            cls.municipio = NMunicipio.objects.create(
                nombre='Playa', provincia=cls.provincia, siglas='PLA')
            cls.tipo_contrato = NTipoContrato.objects.create(
                descripcion='Contrato Determinado', ocupa_plaza=False, requiere_motivo=False)

    def setUp(self):
        # Lo que hace `CurrentUserMiddleware` en cada petición.
        self._token = _user_ctx_var.set(self.admin)

    def tearDown(self):
        _user_ctx_var.reset(self._token)

    def aspirante(self, ci='85010112345', **campos):
        return Aspirante.objects.create(
            nivel_educ='SA', nombre='Luis', papellido='Díaz', sapellido='Mora',
            doc_identidad=ci, estado='ASPIRANTE', sexo='M', raza='BL',
            provincia=self.provincia, municipio=self.municipio, **campos)


class CrearEditarEliminar(BaseRegistro):

    def test_crear_editar_y_eliminar_un_nomenclador(self):
        tridente = NTridente.objects.create(tipo='IX')
        creado = eventos(accion=AccionAuditoria.CREAR).get()
        self.assertEqual(creado.modulo, 'nomencladores')
        self.assertEqual(creado.usuario, self.admin)
        self.assertEqual(creado.datos_despues, {'Tipo': 'IX'})
        # Nombre legible, no el técnico del modelo («NTridente»).
        self.assertEqual(creado.descriptor, 'Tridente «Tridente IX»')

        tridente.tipo = 'X'
        tridente.save()
        editado = eventos(accion=AccionAuditoria.MODIFICAR).get()
        self.assertEqual(editado.datos_antes, {'Tipo': 'IX'})
        self.assertEqual(editado.datos_despues, {'Tipo': 'X'})

        pk = tridente.pk
        tridente.delete()
        borrado = eventos(accion=AccionAuditoria.ELIMINAR).get()
        self.assertEqual(borrado.object_id, str(pk))
        self.assertEqual(borrado.datos_antes, {'Tipo': 'X'})

    def test_guardar_sin_cambios_no_registra_nada(self):
        tridente = NTridente.objects.create(tipo='IX')
        tridente.save()
        tridente.save()
        self.assertEqual(eventos().count(), 1)  # solo la creación

    def test_valores_legibles_y_solo_lo_que_cambio(self):
        departamento = Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=self.unidad, orden_informe=2)
        departamento.unidad_organizativa = self.otra_unidad
        departamento.save()

        evento = eventos(accion=AccionAuditoria.MODIFICAR).get()
        self.assertEqual(evento.modulo, 'estructura')
        self.assertEqual(list(evento.datos_antes.values()), ['UEB Central'])
        self.assertEqual(list(evento.datos_despues.values()), ['UEB Norte'])
        self.assertEqual(evento.unidad_id, self.otra_unidad.pk)
        self.assertIn('Almacén', evento.descriptor)

    def test_campos_calculados_no_cuentan(self):
        self.cargo.cant_cubierta = 7
        self.cargo.save()
        self.assertFalse(eventos().exists())

    def test_sin_usuario_firma_sistema(self):
        _user_ctx_var.set(None)
        NTridente.objects.create(tipo='IX')
        evento = eventos().get()
        self.assertIsNone(evento.usuario)
        self.assertEqual(evento.usuario_nombre, 'Sistema')

    def test_en_pausa_no_registra(self):
        with registro_automatico.sin_auditoria_automatica():
            NTridente.objects.create(tipo='IX')
        self.assertFalse(eventos().exists())


class DerivadosYCascadas(BaseRegistro):

    def test_al_contratar_no_se_registra_el_cambio_de_estado_del_aspirante(self):
        aspirante = self.aspirante()
        EventoAuditoria.objects.all().delete()

        CAlta.objects.create(aspirante=aspirante, no_expediente='00100',
                             tipo=self.tipo_contrato, cargo=self.cargo,
                             fecha_alta=date(2026, 1, 15))

        aspirante.refresh_from_db()
        self.assertEqual(aspirante.estado, 'ACTIVO')
        self.assertEqual(list(eventos().values_list('modulo', 'accion')),
                         [('contratos', AccionAuditoria.CREAR)])

    def test_lo_borrado_en_cascada_no_genera_eventos_propios(self):
        aspirante = self.aspirante()
        CBaja.objects.create(aspirante=aspirante, no_expediente='00100')
        EventoAuditoria.objects.all().delete()

        aspirante.delete()

        self.assertEqual(list(eventos().values_list('modulo', 'accion')),
                         [('aspirantes', AccionAuditoria.ELIMINAR)])


class ProcesosAuditadosAMano(BaseRegistro):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_la_baja_es_un_solo_evento_con_los_datos_de_la_baja(self):
        with registro_automatico.sin_auditoria_automatica():
            contrato = CAlta.objects.create(
                aspirante=self.aspirante(), no_expediente='00100',
                tipo=self.tipo_contrato, cargo=self.cargo, fecha_alta=date(2026, 1, 15))
            causa = NCausaAltaBaja.objects.create(descripcion='Jubilación')

        respuesta = self.client.post(reverse('del_contrato', args=[contrato.pk]), {
            'fecha_baja': '2026-09-30', 'fecha_efectiva': '2026-09-30',
            'causa_baja': causa.pk, 'observaciones': 'Se jubila'})
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

        evento = eventos().get()
        # Una baja tiene su propia acción: no es borrar el contrato.
        self.assertEqual(evento.accion, AccionAuditoria.BAJA)
        self.assertEqual(evento.get_accion_display(), 'Baja')
        self.assertEqual(evento.object_id, str(contrato.pk))
        self.assertTrue(evento.descriptor.startswith('Contrato'))
        self.assertEqual(evento.datos_despues['Causa de baja'], 'Jubilación')
        self.assertEqual(evento.datos_despues['Observaciones'], 'Se jubila')
        self.assertIn('Fecha alta', evento.datos_antes)

    def test_un_movimiento_se_registra_aunque_no_cambie_ningun_dato(self):
        contrato = CAlta(pk=1, no_expediente='00100')
        evento = registro_automatico.registrar(
            contrato, AccionAuditoria.MOVIMIENTO, antes={'Cargo': 'A'}, despues={'Cargo': 'A'})
        self.assertEqual(evento.accion, AccionAuditoria.MOVIMIENTO)
        self.assertEqual((evento.datos_antes, evento.datos_despues), ({}, {}))
        # Una modificación sin cambios, en cambio, no se escribe.
        self.assertIsNone(registro_automatico.registrar(
            contrato, AccionAuditoria.MODIFICAR, antes={'Cargo': 'A'}, despues={'Cargo': 'A'}))

    def test_la_escala_salarial_es_un_evento_por_grupo(self):
        with registro_automatico.sin_auditoria_automatica():
            NGrupoEscala.objects.filter(pk=self.grupo.pk).update(es_cuadro=True)
            NSalario.objects.create(grupo_escala=self.grupo, monto=Decimal('4000'))

        respuesta = self.client.post(
            reverse('editar_salarios', args=[self.grupo.pk]), {'salario_cuadro': '4500'})
        self.assertEqual(respuesta.status_code, 302)

        evento = eventos().get()
        self.assertEqual(evento.accion, AccionAuditoria.MODIFICAR)
        self.assertTrue(evento.descriptor.startswith('Escala salarial'))
        self.assertEqual(evento.datos_antes, {'Salario de cuadro': '4000.00'})
        self.assertEqual(evento.datos_despues, {'Salario de cuadro': '4500.00'})

    def test_el_admin_no_duplica_los_modelos_del_registro_automatico(self):
        from auditoria.admin_mixins import AuditoriaAdminMixin
        tridente = NTridente.objects.create(tipo='IX')
        AuditoriaAdminMixin()._registrar(
            None, AccionAuditoria.CREAR, instancia=tridente)
        self.assertEqual(eventos().count(), 1)


class Conservacion(BaseRegistro):

    def configurar(self, borrar, anios=None):
        Configuracion.objects.all().delete()
        Configuracion.objects.create(
            nombre_empresa='Empresa', auditoria_borrar_antigua=borrar,
            auditoria_anios_conservar=anios)

    def evento_de_hace(self, dias):
        evento = registro_automatico.registrar(
            NTridente.objects.create(tipo='T%d' % dias), AccionAuditoria.CREAR,
            despues={'Tipo': 'x'})
        EventoAuditoria.objects.filter(pk=evento.pk).update(
            fecha=timezone.now() - timedelta(days=dias))
        return evento

    def test_nunca_no_borra_nada(self):
        self.configurar(False)
        self.evento_de_hace(4000)
        self.assertEqual(borrar_auditoria_antigua(), 0)

    def test_borra_solo_lo_que_supera_el_plazo(self):
        self.configurar(True, 2)
        viejo = self.evento_de_hace(800)
        reciente = self.evento_de_hace(300)
        borrados = borrar_auditoria_antigua()
        self.assertGreaterEqual(borrados, 1)
        self.assertFalse(EventoAuditoria.objects.filter(pk=viejo.pk).exists())
        self.assertTrue(EventoAuditoria.objects.filter(pk=reciente.pk).exists())

    def test_abrir_la_pantalla_hace_la_limpieza(self):
        self.configurar(True, 2)
        viejo = self.evento_de_hace(800)
        self.client.force_login(self.admin)
        self.client.get(reverse('auditoria:index'))
        self.assertFalse(EventoAuditoria.objects.filter(pk=viejo.pk).exists())

    def test_29_de_febrero(self):
        self.assertEqual(fecha_limite(2, date(2028, 2, 29)), date(2026, 2, 28))

    def test_formulario_de_parametros_generales(self):
        def errores(**datos):
            base = {'nombre_empresa': 'Empresa', 'moneda_local': 'CUP', 'periodo': 15,
                    'fondo_tiempo_calc_tarif': '190.6', 'porcentaje_horas_extras': '0.25'}
            base.update(datos)
            form = ConfiguracionForm(data=base)
            form.is_valid()
            return form.errors.get('auditoria_anios_conservar'), form

        self.assertIn('Indique cuántos años',
                      errores(auditoria_borrar_antigua='on')[0][0])
        self.assertIn('mínimo 2', errores(auditoria_borrar_antigua='on',
                                          auditoria_anios_conservar='1')[0][0])
        self.assertIn('máximo 99', errores(auditoria_borrar_antigua='on',
                                           auditoria_anios_conservar='100')[0][0])
        sin_error, form = errores(auditoria_anios_conservar='5')
        self.assertIsNone(sin_error)
        self.assertIsNone(form.cleaned_data['auditoria_anios_conservar'])


class PantallaDeAuditoria(BaseRegistro):

    def test_filtro_por_modulo_y_detalle_legible(self):
        NTridente.objects.create(tipo='IX')
        Departamento.objects.create(
            descripcion='Almacén', unidad_organizativa=self.unidad, orden_informe=2)
        self.client.force_login(self.admin)

        respuesta = self.client.get(reverse('auditoria:buscar_eventos'),
                                    {'modulo': 'nomencladores'})
        self.assertContains(respuesta, 'Tridente')
        self.assertNotContains(respuesta, 'Almacén')

        pantalla = self.client.get(reverse('auditoria:index'))
        self.assertIn(('nomencladores', 'Nomencladores'),
                      pantalla.context['opciones_filtro']['modulos'])

        evento = eventos(modulo='estructura').get()
        detalle = self.client.get(reverse('auditoria:detalle_evento', args=[evento.pk]))
        self.assertContains(detalle, 'Estructura Organizativa')
        self.assertContains(detalle, 'UEB Central')
