"""Pruebas de la búsqueda con prefijos (`core/busqueda.py`) y del Índice de Reglas.

Cubren las cuatro pantallas que la usan: Subsanación, Contratos, Aspirantes y Bajas.
"""

from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from auditoria.registro_automatico import sin_auditoria_automatica
from bolsa.models import Aspirante
from contratos.models import CAlta, CBaja
from core.busqueda import interpretar, normalizar
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio, NProvincia,
                                  NTipoContrato, NTipoUnidadOrganizativa)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.models import CustomUser

from .constantes import CRITICIDAD_MEDIA, MODULO_ASPIRANTES, MODULO_CONTRATOS
from .filtros import aplicar_busqueda
from .models import Hallazgo


class Interpretar(SimpleTestCase):

    def test_sin_prefijos_todo_es_texto_libre(self):
        busqueda = interpretar('  Juan Pérez ')
        self.assertEqual(busqueda.libre, 'Juan Pérez')
        self.assertEqual(busqueda.prefijos, {})

    def test_cada_prefijo_llega_hasta_el_siguiente(self):
        busqueda = interpretar('García n:Juan Pérez E:8855 u: Florida')
        self.assertEqual(busqueda.libre, 'García')
        self.assertEqual(busqueda.valores('N'), ['Juan Pérez'])
        self.assertEqual(busqueda.valores('E'), ['8855'])
        self.assertEqual(busqueda.valores('U'), ['Florida'])

    def test_ca_y_ci_no_se_confunden_con_otros(self):
        busqueda = interpretar('CA:ayudante CI:850101 COD:CTR')
        self.assertEqual(busqueda.valores('CA'), ['ayudante'])
        self.assertEqual(busqueda.valores('CI'), ['850101'])
        self.assertEqual(busqueda.valores('COD'), ['CTR'])

    def test_dos_puntos_dentro_de_una_palabra_no_es_prefijo(self):
        self.assertEqual(interpretar('hora 10:30').prefijos, {})

    def test_normalizar_quita_acentos(self):
        self.assertEqual(normalizar('Pérez Núñez'), 'perez nunez')


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        with sin_auditoria_automatica():
            tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
            cls.florida = UnidadOrganizativa.objects.create(
                descripcion='Florida', tipo=tipo, grupo_nomina=1, orden_informe=1)
            cls.nuevitas = UnidadOrganizativa.objects.create(
                descripcion='Nuevitas', tipo=tipo, grupo_nomina=2, orden_informe=2)
            dpto = Departamento.objects.create(
                descripcion='Taller', unidad_organizativa=cls.florida, orden_informe=1)
            dpto2 = Departamento.objects.create(
                descripcion='Almacén', unidad_organizativa=cls.nuevitas, orden_informe=1)
            grupo = NGrupoEscala.objects.create(nivel='IV')
            ayudante = NCargo.objects.create(descripcion='Ayudante de Cocina',
                                             cat_ocupacional='SER', grupo_escala=grupo,
                                             salario_basico=3000)
            tecnico = NCargo.objects.create(descripcion='Técnico Eléctrico',
                                            cat_ocupacional='TEC', grupo_escala=grupo,
                                            salario_basico=4000)
            cls.cargo_ayudante = CargoPlantilla.objects.create(
                ncargo=ayudante, departamento=dpto, cant_aprobada=5, orden_informe=1)
            cls.cargo_tecnico = CargoPlantilla.objects.create(
                ncargo=tecnico, departamento=dpto2, cant_aprobada=5, orden_informe=1)
            provincia = NProvincia.objects.create(nombre='Camagüey', siglas='CMG')
            municipio = NMunicipio.objects.create(nombre='Florida', provincia=provincia,
                                                  siglas='FLO')
            tipo_contrato = NTipoContrato.objects.create(
                descripcion='Determinado', ocupa_plaza=False, requiere_motivo=False)

            def persona(nombre, papellido, ci, unidad, estado='ACTIVO'):
                return Aspirante.objects.create(
                    nivel_educ='SA', nombre=nombre, papellido=papellido, sapellido='Ruiz',
                    doc_identidad=ci, estado=estado, sexo='M', raza='BL',
                    provincia=provincia, municipio=municipio, unidad_organizativa=unidad)

            cls.juan = persona('Juan', 'Pérez', '85010112345', cls.florida)
            cls.ana = persona('Ana', 'Núñez', '90020254321', cls.nuevitas)
            cls.contrato_juan = CAlta.objects.create(
                aspirante=cls.juan, no_expediente='00158', tipo=tipo_contrato,
                cargo=cls.cargo_ayudante, fecha_alta=date(2026, 1, 1))
            cls.contrato_ana = CAlta.objects.create(
                aspirante=cls.ana, no_expediente='1580', tipo=tipo_contrato,
                cargo=cls.cargo_tecnico, fecha_alta=date(2026, 1, 1))

            cls.aspirante_luis = persona('Luis', 'Gómez', '95030311111', cls.florida,
                                         estado='ASPIRANTE')
            cls.baja_pedro = persona('Pedro', 'Díaz', '80040422222', cls.florida,
                                     estado='BAJA')
            CBaja.objects.create(aspirante=cls.baja_pedro, no_expediente='0777',
                                 cargo=cls.cargo_ayudante)

            cls.admin = CustomUser.objects.create_user(
                username='admin_busqueda', password='x', es_admin=True)


class BusquedaEnSubsanacion(Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tipo = ContentType.objects.get_for_model(CAlta)
        ahora = timezone.now()

        def hallazgo(codigo, contrato, titulo, unidad):
            return Hallazgo.objects.create(
                codigo_regla=codigo, content_type=tipo, object_id=str(contrato.pk),
                modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_MEDIA, titulo=titulo,
                unidad_organizativa=unidad, ultima_deteccion=ahora,
                estado=Hallazgo.PENDIENTE)

        cls.h_juan = hallazgo('CTR-011', cls.contrato_juan,
                              'Pérez Ruiz, Juan (85010112345) · Expediente 00158 · sin motivo',
                              cls.florida)
        cls.h_ana = hallazgo('CTR-021', cls.contrato_ana,
                             'Núñez Ruiz, Ana (90020254321) · Expediente 1580 · misión sin días',
                             cls.nuevitas)

    def buscar(self, texto):
        return set(aplicar_busqueda(Hallazgo.objects.all(), texto))

    def test_expediente_exacto_con_o_sin_ceros(self):
        self.assertEqual(self.buscar('E:158'), {self.h_juan})
        self.assertEqual(self.buscar('E:00158'), {self.h_juan})
        self.assertEqual(self.buscar('E:1580'), {self.h_ana})

    def test_nombre_sin_acentos_y_solo_en_el_nombre(self):
        self.assertEqual(self.buscar('N:nunez'), {self.h_ana})
        self.assertEqual(self.buscar('N:Juan Perez'), {self.h_juan})
        # «misión» está en el título, pero no en el nombre.
        self.assertEqual(self.buscar('N:mision'), set())

    def test_carnet_por_el_principio(self):
        self.assertEqual(self.buscar('CI:8501'), {self.h_juan})

    def test_cargo_del_registro_afectado(self):
        self.assertEqual(self.buscar('CA:tecnico'), {self.h_ana})
        self.assertEqual(self.buscar('CA:ayudante'), {self.h_juan})

    def test_unidad_por_parte_del_nombre(self):
        self.assertEqual(self.buscar('U:flor'), {self.h_juan})

    def test_codigo_completo_o_por_el_principio(self):
        self.assertEqual(self.buscar('COD:CTR-011'), {self.h_juan})
        self.assertEqual(self.buscar('COD:ctr'), {self.h_juan, self.h_ana})

    def test_combinados_y_texto_libre_sin_acentos(self):
        self.assertEqual(self.buscar('COD:CTR N:ana'), {self.h_ana})
        self.assertEqual(self.buscar('mision'), {self.h_ana})


class IndiceDeReglas(BusquedaEnSubsanacion):

    def test_admin_ve_todas_las_reglas_y_sus_hallazgos(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('subsanacion:panel_reglas'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'CTR-021')
        self.assertContains(respuesta, 'COD:CTR-011')  # enlace «Ver sus hallazgos»
        self.assertContains(respuesta, 'Cómo buscar')

    def test_el_moderador_solo_cuenta_sus_unidades(self):
        moderador = CustomUser.objects.create_user(
            username='mod_indice', password='x', es_moderador=True)
        moderador.unidades.add(self.florida)
        self.client.force_login(moderador)
        respuesta = self.client.get(reverse('subsanacion:panel_reglas'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'COD:CTR-011')
        self.assertNotContains(respuesta, 'COD:CTR-021')

    def test_el_observador_no_entra(self):
        observador = CustomUser.objects.create_user(
            username='obs_indice', password='x', es_observador=True)
        self.client.force_login(observador)
        respuesta = self.client.get(reverse('subsanacion:panel_reglas'))
        self.assertIn(respuesta.status_code, (302, 403))


class BusquedaEnLasListas(Base):

    def setUp(self):
        self.client.force_login(self.admin)

    def contratos(self, texto):
        respuesta = self.client.get(reverse('search_contrato'), {'filter_contrato': texto})
        return {c.no_expediente for c in respuesta.context['object_list']}

    def personas(self, url, texto):
        respuesta = self.client.get(reverse(url), {'filter_aspirante': texto})
        return {a.nombre for a in respuesta.context['aspirantes']}

    def test_contratos(self):
        self.assertEqual(self.contratos('E:158'), {'00158'})
        self.assertEqual(self.contratos('N:nunez'), {'1580'})
        self.assertEqual(self.contratos('CA:tecnico'), {'1580'})
        self.assertEqual(self.contratos('U:flor'), {'00158'})
        self.assertEqual(self.contratos('CI:9002'), {'1580'})
        # COD: no se aplica aquí: no filtra nada.
        self.assertEqual(self.contratos('COD:CTR'), {'00158', '1580'})
        # Texto libre sin acentos y en cualquier orden.
        self.assertEqual(self.contratos('perez juan'), {'00158'})

    def test_aspirantes_ignoran_expediente_y_cargo(self):
        self.assertEqual(self.personas('search_aspirantes', 'N:gomez'), {'Luis'})
        self.assertEqual(self.personas('search_aspirantes', 'E:777 N:luis'), {'Luis'})
        self.assertEqual(self.personas('search_aspirantes', 'U:nuevitas'), set())

    def test_la_paginacion_de_bajas_sigue_en_bajas(self):
        """Tras buscar en Bajas, «Ver más» y las flechas apuntaban a Aspirantes."""
        respuesta = self.client.get(reverse('search_bajas'), {'filter_aspirante': ''})
        self.assertEqual(respuesta.context['search_url'], 'search_bajas')
        self.assertTrue(respuesta.context['es_baja_view'])

    def test_bajas_buscan_en_su_baja(self):
        self.assertEqual(self.personas('search_bajas', 'E:777'), {'Pedro'})
        self.assertEqual(self.personas('search_bajas', 'CA:ayudante'), {'Pedro'})
        self.assertEqual(self.personas('search_bajas', 'CA:tecnico'), set())
        self.assertEqual(self.personas('search_bajas', 'N:diaz'), {'Pedro'})
