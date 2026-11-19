"""Salud de los datos y botones de las reglas (revisión del 19-11-2026).

    python manage.py test subsanacion.tests_salud
"""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from nomencladores.models import NProvincia

from .constantes import CRITICIDAD_ALTA, CRITICIDAD_INFORMATIVA, MODULO_CONTRATOS, MODULO_EXTRAS
from .models import EjecucionAnalisis, Hallazgo


class _ConProvincias(TestCase):

    def setUp(self):
        self.provincias = [NProvincia.objects.create(nombre=f'Provincia {i}', siglas=f'P{i}')
                           for i in range(4)]
        self.tipo = ContentType.objects.get_for_model(NProvincia)

    def _hallazgo(self, codigo, provincia, criticidad=CRITICIDAD_ALTA, modulo=MODULO_CONTRATOS):
        return Hallazgo.objects.create(
            codigo_regla=codigo, content_type=self.tipo, object_id=str(provincia.pk),
            modulo=modulo, criticidad=criticidad, titulo=codigo,
            ultima_deteccion=timezone.now(), estado=Hallazgo.PENDIENTE)


class SaludSinInformativasTests(_ConProvincias):

    def test_las_informativas_no_bajan_la_nota(self):
        from .servicios import finalizar_ejecucion

        # CTR-012 es Informativa; CTR-016, Alta.
        self._hallazgo('CTR-012', self.provincias[0], CRITICIDAD_INFORMATIVA)
        self._hallazgo('CTR-016', self.provincias[1])
        ejecucion = EjecucionAnalisis.objects.create(
            estado=EjecucionAnalisis.EN_CURSO,
            modulos_solicitados=[MODULO_CONTRATOS], modulos_completados=[MODULO_CONTRATOS],
            codigos_regla_ejecutados=['CTR-012', 'CTR-016'],
            modelos_analizados=['nomencladores.NProvincia'])

        finalizar_ejecucion(ejecucion)
        ejecucion.refresh_from_db()

        self.assertEqual(ejecucion.hallazgos_vigentes, 2)        # se siguen viendo
        self.assertEqual(ejecucion.indice_salud, Decimal('75.00'))  # 1 de 4 afectado
        self.assertEqual(ejecucion.version_indice, 3)

    def test_por_categoria_cuenta_registros_y_extras_no_lleva_nota(self):
        from .servicios import resumen_por_modulo

        # Dos avisos del MISMO registro: un solo registro afectado.
        self._hallazgo('CTR-016', self.provincias[0])
        self._hallazgo('CTR-005', self.provincias[0])
        self._hallazgo('EXT-001', self.provincias[1], CRITICIDAD_INFORMATIVA, MODULO_EXTRAS)
        ejecucion = EjecucionAnalisis.objects.create(
            estado=EjecucionAnalisis.COMPLETA,
            registros_por_modulo={MODULO_CONTRATOS: 100, MODULO_EXTRAS: 100})

        filas = {f['clave']: f for f in resumen_por_modulo(ejecucion)}
        self.assertEqual((filas[MODULO_CONTRATOS]['total'], filas[MODULO_CONTRATOS]['afectados']), (2, 1))
        self.assertEqual(filas[MODULO_CONTRATOS]['indice'], Decimal('99.00'))
        self.assertEqual((filas[MODULO_EXTRAS]['situacion'], filas[MODULO_EXTRAS]['indice']),
                         ('no_cuenta', None))


class BotonesDeLasReglasTests(TestCase):

    def setUp(self):
        from usuarios.models import CustomUser

        self.admin = CustomUser.objects.create_user(username='admin_botones', password='x', es_admin=True)
        self.moderador = CustomUser.objects.create_user(username='mod_botones', password='x', es_moderador=True)

    def _enlace(self, codigo, modelo, object_id, usuario):
        from .enlaces import construir_enlace, destino_de_regla
        from .reglas import obtener_regla

        url, etiqueta = destino_de_regla(obtener_regla(codigo), usuario)
        return construir_enlace(modelo, object_id, forzar_url=url, usuario=usuario, etiqueta=etiqueta)

    def test_cada_aviso_lleva_a_donde_se_arregla(self):
        casos = {
            ('MOV-001', 'contratos.TMovimiento'): reverse('editor_historico_movimiento', args=[7]),
            ('MOV-005', 'contratos.CBaja'): reverse('editor_historico_baja', args=[7]),
            ('CTR-001', 'contratos.CAlta'): reverse('editor_historico_contrato', args=[7]),
            ('CTR-018', 'contratos.CAlta'): reverse('movimiento_contrato', args=[7]),
            ('CTR-011', 'contratos.CAlta'): reverse('parametros'),
            ('CIE-001', 'strorganizativa.UnidadOrganizativa'): reverse('list_cierres'),
            ('CTR-008', 'bolsa.Aspirante'): reverse('contratos_del_trabajador', args=[7]),
        }
        for (codigo, modelo), esperado in casos.items():
            with self.subTest(codigo=codigo):
                self.assertEqual(self._enlace(codigo, modelo, '7', self.admin)['href'], esperado)

    def test_el_moderador_sin_permiso_va_al_destino_de_siempre(self):
        enlace = self._enlace('MOV-001', 'contratos.TMovimiento', '7', self.moderador)
        self.assertEqual(enlace['href'], reverse('list_movimientos'))

    def test_mov_012_retirada(self):
        from .reglas import obtener_regla, obtener_reglas

        self.assertNotIn('MOV-012', {r.codigo for r in obtener_reglas()})
        self.assertIsNotNone(obtener_regla('MOV-017'))

    def test_las_rutas_del_editor_son_del_administrador(self):
        cliente = Client()
        cliente.force_login(self.moderador)
        self.assertEqual(cliente.get(reverse('editor_historico_movimiento', args=[999999])).status_code, 403)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.get(reverse('editor_historico_movimiento', args=[999999])).status_code, 404)

    def test_ver_los_contratos_de_un_trabajador(self):
        from bolsa.models import Aspirante
        from nomencladores.models import NMunicipio

        provincia = NProvincia.objects.create(nombre='Camagüey', siglas='CMG')
        municipio = NMunicipio.objects.create(nombre='Florida', provincia=provincia, siglas='FLO')
        persona = Aspirante.objects.create(
            nivel_educ='SA', nombre='Ana', papellido='Pérez', sapellido='Gil', doc_identidad='90010154399',
            estado='ACTIVO', sexo='F', raza='BL', provincia=provincia, municipio=municipio)
        cliente = Client()
        cliente.force_login(self.admin)
        respuesta = cliente.get(reverse('contratos_del_trabajador', args=[persona.pk]))
        self.assertRedirects(respuesta, f"{reverse('list_contrato')}?filter_contrato=90010154399",
                             fetch_redirect_response=False)
