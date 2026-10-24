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
    """La hora se fija en cada prueba: a partir de las 16:00 no se comprueba nada."""

    def setUp(self):
        from unittest import mock
        parche = mock.patch('subsanacion.automatico._en_horario', return_value=True)
        self.en_horario = parche.start()
        self.addCleanup(parche.stop)

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

    def test_admin_cada_2_horas_y_observador_nunca(self):
        self.client.force_login(self.observador)
        self.assertFalse(self.client.get(reverse('subsanacion:auto_estado')).json()['buscar'])
        self.client.force_login(self.admin)
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
        self.assertFalse(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
        CustomUser.objects.filter(pk=self.admin.pk).update(
            ultima_busqueda_incidencias=timezone.now() - timedelta(minutes=125))
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])

    def test_moderador_cada_30_minutos_y_solo_sus_registros(self):
        from notificaciones.models import Notificacion
        moderador = CustomUser.objects.create_user(username='mod_f2', password='x', es_moderador=True)
        moderador.unidades.add(self.cargo.departamento.unidad_organizativa)
        self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.client.force_login(moderador)
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
        self.assertTrue(Notificacion.objects.filter(destinatario=moderador, codigo_regla='CTR-018').exists())
        CustomUser.objects.filter(pk=moderador.pk).update(
            ultima_busqueda_incidencias=timezone.now() - timedelta(minutes=20))
        self.assertFalse(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])
        CustomUser.objects.filter(pk=moderador.pk).update(
            ultima_busqueda_incidencias=timezone.now() - timedelta(minutes=31))
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])

    def _avisos(self, usuario):
        from notificaciones.models import Notificacion
        return set(Notificacion.objects.filter(destinatario=usuario, estado=Notificacion.Estado.ACTIVA,
                                               tipo=Notificacion.Tipo.ALERTA)
                   .values_list('codigo_regla', 'object_id'))

    def test_por_trozos_deja_lo_mismo_que_de_una_vez(self):
        """La búsqueda por trozos (24-10-2026) crea las mismas notificaciones que
        la de una sola petición, y cada trozo es un módulo."""
        from notificaciones.escaneo import escanear_para_usuario, partes_de_la_busqueda
        self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        escanear_para_usuario(self.admin)
        de_una_vez = self._avisos(self.admin)
        self.assertTrue(de_una_vez)
        from notificaciones.models import Notificacion
        Notificacion.objects.filter(destinatario=self.admin, tipo=Notificacion.Tipo.ALERTA).delete()

        self.client.force_login(self.admin)
        partes = partes_de_la_busqueda()
        parte, vistas = 0, 0
        while parte is not None:
            datos = self.client.post(reverse('subsanacion:auto_buscar'), {'parte': parte}).json()
            self.assertTrue(datos['hecho'])
            self.assertEqual(datos['partes'], len(partes))
            parte, vistas = datos['siguiente'], vistas + 1
        self.assertEqual(vistas, len(partes))
        self.assertEqual(self._avisos(self.admin), de_una_vez)

    def test_un_trozo_suelto_no_vale_sin_una_busqueda_empezada(self):
        self.client.force_login(self.admin)
        self.assertFalse(self.client.post(reverse('subsanacion:auto_buscar'),
                                          {'parte': 1}).json()['hecho'])
        CustomUser.objects.filter(pk=self.admin.pk).update(
            ultima_busqueda_incidencias=timezone.now() - timedelta(minutes=11))
        self.assertFalse(self.client.post(reverse('subsanacion:auto_buscar'),
                                          {'parte': 1}).json()['hecho'])
        CustomUser.objects.filter(pk=self.admin.pk).update(
            ultima_busqueda_incidencias=timezone.now() - timedelta(minutes=2))
        self.assertTrue(self.client.post(reverse('subsanacion:auto_buscar'),
                                         {'parte': 1}).json()['hecho'])

    def test_boton_de_advertencias_por_trozos(self):
        from notificaciones.escaneo import partes_de_la_busqueda
        self.contrato(fecha_alta=date.today() - timedelta(days=40), duracion=30)
        self.client.force_login(self.admin)
        url = reverse('buscar_incidencias')
        parte, total = 0, 0
        while parte is not None:
            datos = self.client.post(url, {'parte': parte}).json()
            total += datos['total']
            parte = datos['siguiente']
        self.assertGreater(total, 0)
        self.assertIn('CTR-018', {c for c, _ in self._avisos(self.admin)})
        self.assertEqual(self.client.post(url, {'parte': len(partes_de_la_busqueda())}).status_code, 400)

    def test_despues_de_las_4_no_se_comprueba_nada(self):
        self.en_horario.return_value = False
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('subsanacion:auto_estado')).json(),
                         {'analizar': False, 'buscar': False})
        self.assertEqual(self.client.post(reverse('subsanacion:auto_iniciar')).json(), {'ocupado': True})
        self.assertFalse(self.client.post(reverse('subsanacion:auto_buscar')).json()['hecho'])


class HorarioTests(TestCase):
    """La hora límite es la local de Orbith (America/Havana): a las 15:59 sí, a las
    16:00 ya no."""

    def test_limite_de_las_4_de_la_tarde(self):
        from unittest import mock
        from subsanacion import automatico
        base = timezone.localtime()
        with mock.patch('subsanacion.automatico.timezone.localtime',
                        return_value=base.replace(hour=15, minute=59)):
            self.assertTrue(automatico._en_horario())
        with mock.patch('subsanacion.automatico.timezone.localtime',
                        return_value=base.replace(hour=16, minute=0)):
            self.assertFalse(automatico._en_horario())
