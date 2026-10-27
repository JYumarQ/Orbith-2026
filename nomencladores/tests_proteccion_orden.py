"""Nomencladores 3.8.2 (27-10-2026): borrados protegidos, sin repetidos, tridentes,
orden por arrastre, red de seguridad y escala salarial dinámica.

Errores que motivaron estas pruebas: crear Tridente o Rol no hacía nada; borrar uno
en uso daba «Unexpected token»; borrar el Tridente III se llevó en silencio sus 66
importes de la escala salarial.
"""
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from usuarios.models import CustomUser

from .models import (NCausaAltaBaja, NCondicionLaboralAnormal, NFamiliaCargo, NGrupoEscala,
                     NMotivoContrato, NMunicipio, NNocturnidad, NProvincia, NRol, NSalario,
                     NTipoContrato, NTipoFamilia, NTridente, clave_nomenclador)


class Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username='adm_nom382', password='x', es_admin=True)
        cls.observador = CustomUser.objects.create_user(username='obs_nom382', password='x', es_observador=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def json(self, metodo, url, datos=None):
        respuesta = getattr(self.client, metodo)(url, data=json.dumps(datos or {}), content_type='application/json')
        return respuesta, respuesta.json()


class BorradosProtegidosTests(Base):

    def test_tridente_con_importes_en_la_escala_no_se_borra(self):
        tridente = NTridente.objects.create(tipo='III')
        grupo = NGrupoEscala.objects.create(nivel='V')
        rol = NRol.objects.create(tipo='Decisorio')
        NSalario.objects.create(grupo_escala=grupo, rol=rol, tridente=tridente, monto=Decimal('4000'))

        respuesta, datos = self.json('delete', reverse('tridente-delete', args=[tridente.pk]))

        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('1 importe de la escala salarial', datos['error'])
        self.assertIn('Parámetros → Escala salarial', datos['error'])
        self.assertTrue(NTridente.objects.filter(pk=tridente.pk).exists())
        self.assertEqual(NSalario.objects.count(), 1)  # nada en cadena

    def test_tridente_sin_nada_se_borra(self):
        tridente = NTridente.objects.create(tipo='II')
        respuesta, datos = self.json('delete', reverse('tridente-delete', args=[tridente.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(datos['success'])
        self.assertFalse(NTridente.objects.exists())

    def test_rol_asignado_a_un_grupo_no_se_borra(self):
        rol = NRol.objects.create(tipo='Apoyo')
        NGrupoEscala.objects.create(nivel='VI').roles.add(rol)
        respuesta, datos = self.json('delete', reverse('rol-delete', args=[rol.pk]))
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('1 grupo escala', datos['error'])

    def test_provincia_en_uso_explica_quien_la_usa(self):
        """Antes: error 500 y «Unexpected token» en pantalla."""
        provincia = NProvincia.objects.create(nombre='Camagüey', siglas='CMG')
        municipio = NMunicipio.objects.create(nombre='Florida', provincia=provincia, siglas='FLA')
        Aspirante.objects.create(nivel_educ='SA', nombre='Ana', papellido='P', sapellido='G',
                                 doc_identidad='85010112345', sexo='F', raza='BL',
                                 provincia=provincia, municipio=municipio)
        respuesta, datos = self.json('delete', reverse('provincia-delete', args=[provincia.pk]))
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('No se puede eliminar «Camagüey»', datos['error'])
        self.assertIn('1 persona', datos['error'])
        self.assertIn('1 municipio', datos['error'])

    def test_tipo_de_familia_con_familias_no_se_borra(self):
        tipo = NTipoFamilia.objects.create(nombre='Técnicos')
        NFamiliaCargo.objects.create(nombre='Informática', tipo_familia=tipo)
        respuesta, datos = self.json('delete', reverse('tipo_familia_delete', args=[tipo.pk]))
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('1 familia de cargos', datos['error'])
        self.assertEqual(NFamiliaCargo.objects.count(), 1)

    def test_nocturnidad_de_una_condicion_no_se_borra(self):
        """Antes la condición se quedaba sin nocturnidad en silencio (SET_NULL)."""
        nocturnidad = NNocturnidad.objects.create(codigo='N1', hora_inicio='23:00', hora_fin='07:00')
        NCondicionLaboralAnormal.objects.create(nombre='Noct', nocturnidad=nocturnidad)
        respuesta, datos = self.json('delete', reverse('nocturnidad_delete', args=[nocturnidad.pk]))
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('1 condición laboral', datos['error'])

    def test_tipo_de_contrato_con_motivos_no_se_borra(self):
        tipo = NTipoContrato.objects.create(descripcion='Determinado', requiere_motivo=True)
        NMotivoContrato.objects.create(descripcion='Sustitución', tipo_contrato=tipo)
        respuesta, datos = self.json('delete', reverse('tipo_contrato_delete', args=[tipo.pk]))
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('1 motivo de contrato', datos['error'])


class SinRepetidosTests(Base):

    def test_la_clave_ignora_mayusculas_acentos_y_espacios(self):
        self.assertEqual(clave_nomenclador('  Flórida   Sur '), clave_nomenclador('florida sur'))

    def test_no_deja_crear_un_rol_repetido(self):
        NRol.objects.create(tipo='Decisorio')
        respuesta, datos = self.json('post', reverse('rol-create'), {'tipo': ' decisorio '})
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Ya existe «Decisorio»', datos['error'])
        self.assertEqual(NRol.objects.count(), 1)

    def test_tampoco_por_otras_vias(self):
        """La regla vive en el modelo: el admin, los importadores y los scripts también."""
        NCausaAltaBaja.objects.create(descripcion='Renuncia')
        with self.assertRaises(ValidationError):
            NCausaAltaBaja.objects.create(descripcion='RENUNCIA')

    def test_el_motivo_puede_repetirse_en_otro_tipo(self):
        determinado = NTipoContrato.objects.create(descripcion='Determinado')
        adiestrado = NTipoContrato.objects.create(descripcion='Adiestrado')
        NMotivoContrato.objects.create(descripcion='Sustitución', tipo_contrato=determinado)
        NMotivoContrato.objects.create(descripcion='Sustitución', tipo_contrato=adiestrado)
        with self.assertRaises(ValidationError):
            NMotivoContrato.objects.create(descripcion='sustitucion', tipo_contrato=determinado)

    def test_el_municipio_puede_repetirse_en_otra_provincia(self):
        una = NProvincia.objects.create(nombre='Holguín', siglas='HOL')
        otra = NProvincia.objects.create(nombre='Santiago de Cuba', siglas='SCU')
        NMunicipio.objects.create(nombre='San Luis', provincia=una, siglas='SLU')
        NMunicipio.objects.create(nombre='San Luis', provincia=otra, siglas='SLS')
        with self.assertRaises(ValidationError):
            NMunicipio.objects.create(nombre='san luís', provincia=una, siglas='SLX')


class TridentesTests(Base):

    def test_crear_el_tridente_iii_ahora_funciona(self):
        respuesta, datos = self.json('post', reverse('tridente-create'), {'tipo': 'iii'})
        self.assertEqual(respuesta.status_code, 200, datos)
        self.assertEqual(datos['tipo'], 'III')

    def test_solo_i_ii_o_iii(self):
        respuesta, datos = self.json('post', reverse('tridente-create'), {'tipo': 'IV'})
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('I, II o III', datos['error'])

    def test_no_se_repite(self):
        NTridente.objects.create(tipo='II')
        respuesta, datos = self.json('post', reverse('tridente-create'), {'tipo': 'ii'})
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Ya existe', datos['error'])

    def test_se_ordenan_de_menor_a_mayor(self):
        for tipo in ('III', 'I', 'II'):
            NTridente.objects.create(tipo=tipo)
        self.assertEqual(list(NTridente.objects.values_list('tipo', flat=True)), ['I', 'II', 'III'])


class OrdenPorArrastreTests(Base):

    def setUp(self):
        super().setUp()
        self.decisorio = NRol.objects.create(tipo='Decisorio')
        self.fundamental = NRol.objects.create(tipo='Fundamental')
        self.apoyo = NRol.objects.create(tipo='Apoyo')

    def test_los_nuevos_van_al_final(self):
        self.assertEqual(list(NRol.objects.values_list('tipo', flat=True)), ['Decisorio', 'Fundamental', 'Apoyo'])

    def test_guardar_el_orden_lo_cambia_en_todo_orbith(self):
        ids = [self.apoyo.pk, self.decisorio.pk, self.fundamental.pk]
        respuesta, datos = self.json('post', reverse('nomenclador_orden', args=['rol']), {'ids': ids})
        self.assertEqual(respuesta.status_code, 200, datos)
        self.assertEqual(list(NRol.objects.values_list('pk', flat=True)), ids)

    def test_una_lista_incompleta_se_rechaza(self):
        respuesta, datos = self.json('post', reverse('nomenclador_orden', args=['rol']),
                                     {'ids': [self.apoyo.pk, self.decisorio.pk]})
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('Recargue la página', datos['error'])

    def test_el_observador_no_puede_ordenar(self):
        self.client.force_login(self.observador)
        respuesta = self.client.post(reverse('nomenclador_orden', args=['rol']),
                                     data=json.dumps({'ids': [self.apoyo.pk]}), content_type='application/json')
        self.assertIn(respuesta.status_code, (302, 403))


class RedDeSeguridadTests(Base):

    def test_un_fallo_inesperado_no_llega_como_error_tecnico(self):
        from unittest import mock

        with mock.patch('nomencladores.views.NRol.objects.get', side_effect=RuntimeError('fallo')), \
                mock.patch('nomencladores.views.get_object_or_404', side_effect=RuntimeError('fallo')):
            respuesta, datos = self.json('put', reverse('rol-update', args=[1]), {'tipo': 'X'})
        self.assertEqual(respuesta.status_code, 500)
        self.assertIn('No se pudo completar la operación', datos['error'])

    def test_no_existe_sigue_siendo_404(self):
        respuesta = self.client.delete(reverse('tridente-delete', args=[999999]))
        self.assertEqual(respuesta.status_code, 404)


class EscalaSalarialDinamicaTests(Base):

    def test_cada_importe_en_su_celda_y_los_estados(self):
        from configuracion.views import escala_salarial

        decisorio = NRol.objects.create(tipo='Decisorio')
        apoyo = NRol.objects.create(tipo='Apoyo')
        uno, dos = NTridente.objects.create(tipo='I'), NTridente.objects.create(tipo='II')
        grupo = NGrupoEscala.objects.create(nivel='XXIV')
        grupo.roles.add(decisorio)   # como XXIV: solo Decisorio
        NSalario.objects.create(grupo_escala=grupo, rol=decisorio, tridente=dos, monto=Decimal('9000'))

        datos = escala_salarial()
        self.assertEqual([r.tipo for r in datos['escala_roles']], ['Decisorio', 'Apoyo'])
        celdas = datos['salarios'][0]['celdas']
        # Decisorio I falta, Decisorio II en SU celda (antes se corría a la I), Apoyo no aplica.
        self.assertEqual([c['estado'] for c in celdas], ['falta', 'ok', 'no_aplica', 'no_aplica'])
        self.assertEqual(celdas[1]['monto'], Decimal('9000'))
