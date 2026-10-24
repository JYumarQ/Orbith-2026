"""Fase 2 (23-10-2026): revisión por registro, triángulos (cascada roja, ámbar sin
cascada), ventana del ⚠️, filtro «Con problemas» y búsqueda automática."""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bolsa.models import Aspirante
from contratos.models import CAlta
from contratos.tests import _crear_departamento_con_cargo, _crear_provincia_municipio
from nomencladores.models import NTipoContrato
from usuarios.models import CustomUser

from .indicadores import (cascada_critica, contratos_con_problemas, problemas_por_contrato)
from .models import EjecucionAnalisis, Hallazgo


class BaseFase2(TestCase):

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import NRol
        from strorganizativa.models import CargoPlantilla
        cls.cargo = _crear_departamento_con_cargo()
        # Con rol: si no, EST-008 («cargo sin rol», Crítica) lo pondría en rojo.
        CargoPlantilla.objects.filter(pk=cls.cargo.pk).update(rol=NRol.objects.create(tipo='Apoyo'))
        cls.cargo.refresh_from_db()
        provincia, municipio = _crear_provincia_municipio()
        cls.aspirante = Aspirante.objects.create(
            nivel_educ='SA', nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad='80010113197', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.tipo = NTipoContrato.objects.create(descripcion='Determinado', ocupa_plaza=False,
                                                requiere_motivo=False)
        cls.admin = CustomUser.objects.create_user(username='admin_f2', password='x', es_admin=True)
        cls.observador = CustomUser.objects.create_user(username='obs_f2', password='x',
                                                        es_observador=True)

    def contrato(self, **extra):
        datos = dict(aspirante=self.aspirante, no_expediente='03001', tipo=self.tipo,
                     cargo=self.cargo, fecha_alta=date.today(), tipo_salario='FIJ',
                     fecha_alta_entidad=date(2020, 1, 1))
        datos.update(extra)
        return CAlta.objects.create(**datos)

    def abiertos(self, contrato):
        return set(Hallazgo.objects.filter(
            object_id=str(contrato.pk), content_type__model='calta', vigente=True,
            estado__in=Hallazgo.ESTADOS_ABIERTOS).values_list('codigo_regla', flat=True))


class RevisionPorRegistroTests(BaseFase2):

    def test_al_guardar_aparece_y_al_corregir_se_cierra(self):
        # Vencido hace 10 días: CTR-018 (Crítica) al momento, sin análisis.
        contrato = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.assertIn('CTR-018', self.abiertos(contrato))
        contrato.duracion = 365
        contrato.save()
        self.assertNotIn('CTR-018', self.abiertos(contrato))
        cerrado = Hallazgo.objects.get(codigo_regla='CTR-018', object_id=str(contrato.pk))
        self.assertEqual(cerrado.estado, Hallazgo.CORREGIDO)

    def test_lo_ignorado_no_se_reabre_ni_pinta(self):
        contrato = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        Hallazgo.objects.filter(codigo_regla='CTR-018').update(estado=Hallazgo.IGNORADO)
        contrato.save()
        self.assertEqual(Hallazgo.objects.get(codigo_regla='CTR-018').estado, Hallazgo.IGNORADO)
        self.assertEqual(problemas_por_contrato([contrato]), {})

    def test_borrar_el_contrato_cierra_sus_hallazgos(self):
        contrato = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        pk = contrato.pk
        contrato.delete()
        self.assertFalse(Hallazgo.objects.filter(object_id=str(pk), content_type__model='calta',
                                                 vigente=True).exists())


class TriangulosTests(BaseFase2):

    def test_rojo_en_cascada_y_ambar_sin_cascada(self):
        critico = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.assertEqual(problemas_por_contrato([critico])[critico.pk]['nivel'], 'critico')
        cascada = cascada_critica()
        self.assertIn(self.cargo.pk, cascada['cargos'])
        self.assertIn(self.cargo.departamento_id, cascada['departamentos'])
        self.assertIn(self.cargo.departamento.unidad_organizativa_id, cascada['unidades'])

        # Solo un problema Alto (CTR-016, sin F. Alta Entidad): ámbar y no sube.
        critico.duracion = 365
        critico.fecha_alta_entidad = None
        critico.save()
        self.assertEqual(problemas_por_contrato([critico])[critico.pk]['nivel'], 'alto')
        self.assertNotIn(self.cargo.pk, cascada_critica()['cargos'])

    def test_filtro_con_problemas(self):
        critico = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.assertIn(str(critico.pk), contratos_con_problemas('criticos'))
        self.assertNotIn(str(critico.pk), contratos_con_problemas('altos'))
        self.client.force_login(self.admin)
        r = self.client.get(reverse('search_contrato'), {'problemas': 'criticos'},
                            HTTP_HX_REQUEST='true')
        self.assertContains(r, 'row-problema-critico')

    def test_ventana_del_triangulo(self):
        contrato = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.client.force_login(self.observador)
        r = self.client.get(reverse('subsanacion:problemas_registro', args=['contrato', contrato.pk]))
        self.assertContains(r, 'CTR-018')
        self.assertContains(r, 'Cómo se soluciona')

    def test_el_gestor_pinta_los_triangulos(self):
        contrato = self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.client.force_login(self.admin)
        r = self.client.get(reverse('htmx_load_contratos', args=[self.cargo.pk]))
        self.assertContains(r, 'triangulo-problema critico')
        self.assertContains(r, reverse('subsanacion:problemas_registro', args=['contrato', contrato.pk]))
        r = self.client.get(reverse('htmx_load_cargos', args=[self.cargo.departamento_id]))
        self.assertContains(r, 'triangulo-problema critico')


class BusquedaAutomaticaTests(BaseFase2):

    def test_analisis_diario_una_vez_al_dia(self):
        self.client.force_login(self.observador)
        self.assertTrue(self.client.get(reverse('subsanacion:auto_estado')).json()['analizar'])
        datos = self.client.post(reverse('subsanacion:auto_iniciar')).json()
        for modulo in datos['modulos']:
            self.assertTrue(self.client.post(
                reverse('subsanacion:auto_modulo', args=[datos['pk'], modulo])).json()['ok'])
        self.client.post(reverse('subsanacion:auto_finalizar', args=[datos['pk']]))
        ejecucion = EjecucionAnalisis.objects.get(pk=datos['pk'])
        self.assertEqual((ejecucion.origen, ejecucion.lanzada_por),
                         (EjecucionAnalisis.PROGRAMADA, None))
        self.assertFalse(self.client.get(reverse('subsanacion:auto_estado')).json()['analizar'])

    def test_busqueda_al_entrar_segun_el_rol_y_cada_4_horas(self):
        self.client.force_login(self.observador)
        self.assertFalse(self.client.get(reverse('subsanacion:auto_estado')).json()['buscar'])
        self.client.force_login(self.admin)
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
        self.assertFalse(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
        CustomUser.objects.filter(pk=self.admin.pk).update(
            ultima_busqueda_incidencias=timezone.now() - timedelta(hours=5))
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
