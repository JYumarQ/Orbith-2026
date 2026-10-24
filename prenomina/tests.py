"""Pruebas del módulo Pre-Nómina.

Bloques con intención distinta, igual que `cierres/tests.py`:

* `MotorDeFormulas` no toca la base de datos. Cubre la lista blanca del
  evaluador con los vectores de escape clásicos: si esa lista se ablanda en un
  refactor, aquí se nota inmediatamente.
* `RolesYAlcance` verifica el reparto de permisos, en particular que un
  Administrador **no** pase por Moderador (`CustomUser.save()` le fuerza
  `is_superuser=True`, así que la exclusión hay que hacerla a mano).
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from bolsa.models import Aspirante
from cierres.periodos import Periodo
from contratos.models import CAlta
from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio, NProvincia,
                                  NTipoContrato, NTipoUnidadOrganizativa)
from prenomina import (calculos, captura, exportar, filtros, formulas,
                       importar, permisos, servicios)
from prenomina.constantes import (COLOR_AUSENCIA, COLOR_PAGO_HORAS,
                                  COLOR_PAGO_IMPORTE, COLOR_TRABAJADAS,
                                  COLOR_TRABAJADOR, FILA_COLUMNAS, FILA_GRUPOS,
                                  FILA_MAQUINA, HOJA_ESCALA, HOJA_METADATOS,
                                  HOJA_REPORTE, PRIMERA_FILA_DATOS)
from prenomina.formulas import ErrorDeFormula
from prenomina.forms import NPagoImporteForm, ReportePagoForm
from prenomina.models import (CalendarioPago, EstadoReporte, NClaveAusencia,
                              NEscalaAnnosServicio, NPagoHoras, NPagoImporte,
                              Quincena, ReportePago, ReporteTrabajador,
                              TipoValorImporte)
from strorganizativa.models import (CargoPlantilla, Departamento,
                                    UnidadOrganizativa)
from usuarios.models import CustomUser


class MotorDeFormulas(SimpleTestCase):
    """Gramática del evaluador. Sin base de datos: corre en milisegundos."""

    # --- Normalización -----------------------------------------------------

    def test_las_llaves_dobles_se_convierten_en_la_variable(self):
        self.assertEqual(formulas.normalizar('{{horas}} * 2'), 'horas * 2')

    def test_se_acepta_la_variable_sin_llaves(self):
        self.assertEqual(formulas.normalizar('horas * 2'), 'horas * 2')

    def test_una_llave_suelta_se_rechaza(self):
        with self.assertRaises(ErrorDeFormula):
            formulas.compilar('{horas} * 2')

    def test_la_formula_vacia_se_rechaza(self):
        for vacia in ('', '   ', None):
            with self.assertRaises(ErrorDeFormula):
                formulas.compilar(vacia)

    def test_se_rechaza_una_formula_demasiado_larga(self):
        with self.assertRaises(ErrorDeFormula):
            formulas.compilar('1 + ' * 200 + '1')

    # --- Expresiones válidas ------------------------------------------------

    def test_expresiones_validas(self):
        casos = {
            '200': Decimal('200'),
            '1.25': Decimal('1.25'),
            '-5 + 10': Decimal('5'),
            '2 + 3 * 4': Decimal('14'),          # precedencia
            '(2 + 3) * 4': Decimal('20'),        # paréntesis
            '10 / 4': Decimal('2.5'),
            '{{horas}} * 1.25': Decimal('200'),
            '({{horas}} - 8) * 2.5': Decimal('380'),
            '{{cnci}}': Decimal('30'),
            '{{horas}} * {{tarifa_horaria}}': Decimal('1600'),
        }
        contexto = {
            'horas': Decimal('160'),
            'tarifa_horaria': Decimal('10'),
            'cnci': Decimal('30'),
        }
        for expresion, esperado in casos.items():
            with self.subTest(expresion=expresion):
                self.assertEqual(formulas.evaluar(expresion, contexto), esperado)

    def test_todas_las_variables_declaradas_son_utilizables(self):
        """Si alguien añade una variable a VARIABLES sin cablearla, salta aquí."""
        for nombre in formulas.VARIABLES:
            with self.subTest(variable=nombre):
                valor = formulas.evaluar('{{%s}} + 1' % nombre, {nombre: Decimal('4')})
                self.assertEqual(valor, Decimal('5'))

    # --- Expresiones rechazadas: los vectores de escape ---------------------

    def test_se_rechazan_las_llamadas_a_funciones(self):
        for expresion in ('__import__("os")', 'open("x")', 'eval("1")', 'horas()'):
            with self.subTest(expresion=expresion):
                with self.assertRaises(ErrorDeFormula):
                    formulas.compilar(expresion)

    def test_se_rechaza_el_acceso_a_atributos(self):
        """La ruta clásica de escape: ().__class__.__bases__[0].__subclasses__()"""
        for expresion in ('horas.__class__', '().__class__', 'horas.real'):
            with self.subTest(expresion=expresion):
                with self.assertRaises(ErrorDeFormula):
                    formulas.compilar(expresion)

    def test_se_rechazan_los_corchetes(self):
        with self.assertRaises(ErrorDeFormula):
            formulas.compilar('horas[0]')

    def test_se_rechazan_las_comprensiones(self):
        with self.assertRaises(ErrorDeFormula):
            formulas.compilar('[i for i in range(9)]')

    def test_se_rechaza_la_potenciacion(self):
        """9**9**9 es una denegación de servicio de una línea."""
        with self.assertRaises(ErrorDeFormula) as caja:
            formulas.compilar('2 ** 64')
        self.assertIn('potenciación', str(caja.exception))

    def test_el_acento_circunflejo_avisa_de_que_no_es_potencia(self):
        """En Python ^ es XOR: sin aviso, «2^3» daría 1 en silencio."""
        with self.assertRaises(ErrorDeFormula) as caja:
            formulas.compilar('2 ^ 3')
        self.assertIn('^', str(caja.exception))

    def test_se_rechazan_los_condicionales_y_las_comparaciones(self):
        for expresion in ('1 if horas else 2', 'horas > 8', 'horas and 1'):
            with self.subTest(expresion=expresion):
                with self.assertRaises(ErrorDeFormula):
                    formulas.compilar(expresion)

    def test_se_rechaza_una_variable_desconocida(self):
        with self.assertRaises(ErrorDeFormula) as caja:
            formulas.compilar('{{salario}} * 2')
        # El mensaje nombra la variable y enumera las disponibles.
        self.assertIn('salario', str(caja.exception))
        self.assertIn('{{horas}}', str(caja.exception))

    def test_se_rechaza_el_texto(self):
        for expresion in ('"hola"', 'f"{horas}"'):
            with self.subTest(expresion=expresion):
                with self.assertRaises(ErrorDeFormula):
                    formulas.compilar(expresion)

    def test_los_booleanos_no_cuelan_como_numeros(self):
        """isinstance(True, int) es True y True + True == 2."""
        with self.assertRaises(ErrorDeFormula):
            formulas.compilar('True + True')

    def test_se_rechaza_el_resto_y_la_division_entera(self):
        for expresion in ('10 % 3', '10 // 3'):
            with self.subTest(expresion=expresion):
                with self.assertRaises(ErrorDeFormula):
                    formulas.compilar(expresion)

    def test_se_rechaza_la_sintaxis_rota(self):
        for expresion in ('2 +', '(2 + 3', '* 5'):
            with self.subTest(expresion=expresion):
                with self.assertRaises(ErrorDeFormula):
                    formulas.compilar(expresion)

    def test_los_parentesis_redundantes_no_cuentan_como_anidamiento(self):
        """`ast.parse` los colapsa: «((((1))))» es una constante, profundidad 0."""
        self.assertEqual(formulas.evaluar('(' * 30 + '1' + ')' * 30), Decimal('1'))

    def test_se_rechaza_el_encadenamiento_excesivo_de_operaciones(self):
        """Guarda anti-DoS: el recorrido del árbol es recursivo."""
        profunda = '1+' * (formulas.PROFUNDIDAD_MAXIMA + 5) + '1'
        with self.assertRaises(ErrorDeFormula) as caja:
            formulas.compilar(profunda)
        self.assertIn('compleja', str(caja.exception))

    # --- División entre cero ------------------------------------------------

    def test_la_division_entre_cero_literal_se_rechaza_al_guardar(self):
        with self.assertRaises(ErrorDeFormula):
            formulas.validar('1 / 0')

    def test_dividir_entre_una_variable_se_rechaza_al_guardar(self):
        """No es detectable estáticamente: lo atrapa el ensayo en seco con 0."""
        with self.assertRaises(ErrorDeFormula) as caja:
            formulas.validar('1000 / {{horas}}')
        self.assertIn('0', str(caja.exception))

    def test_una_formula_sana_pasa_la_validacion(self):
        for expresion in ('200', '{{horas}} * 1.25', '{{cnci}} + {{instructor}}'):
            with self.subTest(expresion=expresion):
                formulas.validar(expresion)  # no debe lanzar

    # --- Precisión ----------------------------------------------------------

    def test_la_aritmetica_es_decimal_exacta(self):
        """Con float, 0.1 + 0.2 es 0.30000000000000004."""
        self.assertEqual(formulas.evaluar('0.1 + 0.2'), Decimal('0.3'))

    def test_evaluar_no_redondea(self):
        """El redondeo se aplica una sola vez, al almacenar el importe."""
        self.assertEqual(formulas.evaluar('10 / 3').quantize(Decimal('0.0001')),
                         Decimal('3.3333'))

    def test_una_variable_ausente_del_contexto_vale_cero(self):
        self.assertEqual(formulas.evaluar('{{horas}} + 5'), Decimal('5'))

    # --- variables_usadas ---------------------------------------------------

    def test_variables_usadas_las_enumera(self):
        self.assertEqual(
            formulas.variables_usadas('{{horas}} * {{tarifa_horaria}} + 1'),
            {'horas', 'tarifa_horaria'})

    def test_variables_usadas_esta_vacio_en_una_constante(self):
        self.assertEqual(formulas.variables_usadas('200'), set())


class RolesYAlcance(TestCase):
    """Reparto de permisos del módulo."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_pn', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_pn', password='x', es_moderador=True)
        cls.observador = CustomUser.objects.create_user(
            username='obs_pn', password='x', es_observador=True)

    def test_un_administrador_no_pasa_por_moderador(self):
        """`CustomUser.save()` le fuerza is_superuser=True: hay que excluirlo."""
        self.assertTrue(permisos.es_administrador(self.admin))
        self.assertFalse(permisos.es_moderador(self.admin))
        self.assertFalse(permisos.es_observador(self.admin))

    def test_cada_rol_se_reconoce_a_si_mismo(self):
        self.assertTrue(permisos.es_moderador(self.moderador))
        self.assertTrue(permisos.es_observador(self.observador))

    def test_administrador_y_moderador_tienen_acceso_al_modulo(self):
        for usuario in (self.admin, self.moderador):
            with self.subTest(usuario=usuario.username):
                self.assertTrue(permisos.tiene_acceso(usuario))

    def test_el_observador_no_tiene_acceso_al_modulo(self):
        self.assertFalse(permisos.tiene_acceso(self.observador))

    def test_el_observador_no_escribe(self):
        self.assertTrue(permisos.puede_escribir(self.admin))
        self.assertTrue(permisos.puede_escribir(self.moderador))
        self.assertFalse(permisos.puede_escribir(self.observador))

    def test_los_nomencladores_son_exclusivos_del_administrador(self):
        self.assertTrue(permisos.puede_gestionar_nomencladores(self.admin))
        self.assertFalse(permisos.puede_gestionar_nomencladores(self.moderador))
        self.assertFalse(permisos.puede_gestionar_nomencladores(self.observador))

    def test_un_anonimo_no_tiene_acceso(self):
        from django.contrib.auth.models import AnonymousUser
        anonimo = AnonymousUser()
        self.assertFalse(permisos.tiene_acceso(anonimo))
        self.assertFalse(permisos.puede_escribir(anonimo))
        self.assertFalse(permisos.puede_gestionar_nomencladores(anonimo))


class NomencladoresDeConfiguracion(TestCase):
    """Validación de los cuatro nomencladores, en el modelo y en la base de datos."""

    @classmethod
    def setUpTestData(cls):
        cls.extras = NPagoHoras.objects.create(codigo=2, descripcion='Horas Extra')

    # --- Códigos ------------------------------------------------------------

    def test_el_codigo_es_unico(self):
        with self.assertRaises(IntegrityError):
            NPagoHoras.objects.create(codigo=2, descripcion='Otro')

    def test_el_codigo_cero_se_rechaza_en_la_base_de_datos(self):
        """El CHECK protege incluso contra escrituras que se saltan `clean()`."""
        with self.assertRaises(IntegrityError):
            NPagoHoras.objects.create(codigo=0, descripcion='Sin código')

    def test_la_etiqueta_compone_codigo_y_descripcion(self):
        """Es lo que se escribe en la cabecera del Excel exportado."""
        self.assertEqual(self.extras.etiqueta, '2 Horas Extra')

    # --- Coherencia del valor de un pago por importe ------------------------

    def test_un_importe_fijo_valido_se_guarda(self):
        pago = NPagoImporte(codigo=10, descripcion='Fijo',
                            tipo_valor=TipoValorImporte.IMPORTE,
                            importe_fijo=Decimal('150.00'))
        pago.full_clean()
        pago.save()
        self.assertEqual(pago.importe_fijo, Decimal('150.00'))

    def test_un_importe_fijo_sin_valor_se_rechaza(self):
        pago = NPagoImporte(codigo=11, descripcion='Sin valor',
                            tipo_valor=TipoValorImporte.IMPORTE)
        with self.assertRaises(ValidationError) as caja:
            pago.full_clean()
        self.assertIn('importe_fijo', caja.exception.error_dict)

    def test_una_formula_invalida_se_rechaza_al_guardar(self):
        """El requisito exige validar al guardar, no al generar el reporte."""
        pago = NPagoImporte(codigo=12, descripcion='Rota',
                            tipo_valor=TipoValorImporte.FORMULA,
                            formula='horas.__class__',
                            relacionado_con=self.extras)
        with self.assertRaises(ValidationError) as caja:
            pago.full_clean()
        self.assertIn('formula', caja.exception.error_dict)

    def test_una_formula_con_horas_exige_concepto_relacionado(self):
        pago = NPagoImporte(codigo=13, descripcion='Sin relación',
                            tipo_valor=TipoValorImporte.FORMULA,
                            formula='{{horas}} * 1.25')
        with self.assertRaises(ValidationError) as caja:
            pago.full_clean()
        self.assertIn('relacionado_con', caja.exception.error_dict)

    def test_una_formula_sin_horas_no_exige_relacion(self):
        """C.N.C.I es la fórmula {{cnci}}: no toma horas de ningún concepto."""
        pago = NPagoImporte(codigo=14, descripcion='C.N.C.I',
                            tipo_valor=TipoValorImporte.FORMULA,
                            formula='{{cnci}}')
        pago.full_clean()
        pago.save()
        self.assertIsNone(pago.relacionado_con)

    def test_la_base_de_datos_rechaza_una_combinacion_incoherente(self):
        """`clean()` no cubre `objects.create()` directo; el CHECK sí."""
        with self.assertRaises(IntegrityError):
            NPagoImporte.objects.create(
                codigo=15, descripcion='Incoherente',
                tipo_valor=TipoValorImporte.FORMULA,
                importe_fijo=Decimal('10'), formula='{{cnci}}')

    def test_el_tipo_escala_exige_que_la_escala_no_este_vacia(self):
        NEscalaAnnosServicio.objects.all().delete()
        pago = NPagoImporte(codigo=16, descripcion='Años de servicio',
                            tipo_valor=TipoValorImporte.ESCALA)
        with self.assertRaises(ValidationError):
            pago.full_clean()

        NEscalaAnnosServicio.objects.create(annos=1, cuantia=Decimal('200'))
        pago.full_clean()  # ya no debe lanzar

    # --- El formulario limpia los restos del tipo anterior ------------------

    def test_el_formulario_vacia_el_importe_al_pasar_a_formula(self):
        """Sin esto, el importe viejo del POST haría saltar el CHECK."""
        formulario = NPagoImporteForm(data={
            'codigo': 20, 'descripcion': 'Cambiado',
            'tipo_valor': TipoValorImporte.FORMULA,
            'importe_fijo': '99.00',
            'formula': '{{cnci}} * 2',
        })
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertIsNone(formulario.cleaned_data['importe_fijo'])

    def test_el_formulario_vacia_la_formula_al_pasar_a_importe(self):
        formulario = NPagoImporteForm(data={
            'codigo': 21, 'descripcion': 'Cambiado',
            'tipo_valor': TipoValorImporte.IMPORTE,
            'importe_fijo': '99.00',
            'formula': '{{cnci}} * 2',
        })
        self.assertTrue(formulario.is_valid(), formulario.errors)
        self.assertEqual(formulario.cleaned_data['formula'], '')

    # --- Relaciones protegidas ---------------------------------------------

    def test_no_se_puede_borrar_un_pago_por_horas_en_uso(self):
        """PROTECT: si no, la fórmula quedaría no evaluable en silencio."""
        from django.db.models import ProtectedError
        NClaveAusencia.objects.create(
            codigo=99, descripcion='Vacaciones', relacionado_con=self.extras)
        with self.assertRaises(ProtectedError):
            self.extras.delete()

    # --- Escala de años de servicio ----------------------------------------

    def test_la_migracion_siembra_los_treinta_tramos(self):
        """Los datos vienen de la hoja Rangos del Excel de RRHH."""
        self.assertEqual(NEscalaAnnosServicio.objects.count(), 30)
        self.assertEqual(
            NEscalaAnnosServicio.objects.get(annos=1).cuantia, Decimal('200.00'))
        self.assertEqual(
            NEscalaAnnosServicio.objects.get(annos=30).cuantia, Decimal('3000.00'))

    def test_la_busqueda_en_la_escala_congelada(self):
        escala = NEscalaAnnosServicio.como_diccionario()
        self.assertEqual(
            NEscalaAnnosServicio.cuantia_de(escala, 5), Decimal('1000'))

    def test_por_encima_del_ultimo_tramo_se_cobra_el_ultimo(self):
        """En la hoja de RRHH 30 es el techo: quien lleva 35 cobra como 30."""
        escala = NEscalaAnnosServicio.como_diccionario()
        self.assertEqual(
            NEscalaAnnosServicio.cuantia_de(escala, 40), Decimal('3000'))

    def test_por_debajo_del_primer_tramo_no_se_cobra_nada(self):
        escala = NEscalaAnnosServicio.como_diccionario()
        self.assertEqual(NEscalaAnnosServicio.cuantia_de(escala, 0), Decimal('0'))

    def test_una_escala_vacia_devuelve_cero(self):
        self.assertEqual(NEscalaAnnosServicio.cuantia_de({}, 5), Decimal('0'))


class CierreDeLosEndpointsDeConfiguracion(TestCase):
    """Ocultar el botón no es la protección: se comprueba la URL directa.

    Es el mismo cierre que documenta `nomencladores/urls.py`, donde las APIs
    quedaban abiertas a cualquier usuario autenticado y un Moderador podía crear
    y borrar nomencladores con una petición directa.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_cfg', password='clave', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_cfg', password='clave', es_moderador=True)
        cls.observador = CustomUser.objects.create_user(
            username='obs_cfg', password='clave', es_observador=True)
        cls.concepto = NPagoHoras.objects.create(codigo=3, descripcion='Doble Turno')

    def _rutas(self):
        return [
            ('get', reverse('prenomina:tarjeta_nomenclador', args=['pagos-horas'])),
            ('get', reverse('prenomina:nuevo_nomenclador', args=['pagos-horas'])),
            ('post', reverse('prenomina:nuevo_nomenclador', args=['pagos-horas'])),
            ('get', reverse('prenomina:editar_nomenclador',
                            args=['pagos-horas', self.concepto.pk])),
            ('post', reverse('prenomina:eliminar_nomenclador',
                             args=['pagos-horas', self.concepto.pk])),
            ('post', reverse('prenomina:validar_formula')),
        ]

    def test_un_moderador_no_entra_en_ninguna_ruta_de_configuracion(self):
        self.client.force_login(self.moderador)
        for metodo, ruta in self._rutas():
            with self.subTest(ruta=ruta):
                respuesta = getattr(self.client, metodo)(ruta, HTTP_HX_REQUEST='true')
                self.assertEqual(respuesta.status_code, 403)

    def test_un_observador_tampoco(self):
        self.client.force_login(self.observador)
        for metodo, ruta in self._rutas():
            with self.subTest(ruta=ruta):
                respuesta = getattr(self.client, metodo)(ruta, HTTP_HX_REQUEST='true')
                self.assertEqual(respuesta.status_code, 403)

    def test_el_administrador_ve_las_tarjetas(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('prenomina:tarjeta_nomenclador', args=['pagos-horas']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Doble Turno')

    def test_el_administrador_crea_un_concepto_y_se_dispara_el_refresco(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(
            reverse('prenomina:nuevo_nomenclador', args=['pagos-horas']),
            {'codigo': 7, 'descripcion': 'Feriado Trabajado'},
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('prenominaPagosHorasActualizado', respuesta['HX-Trigger'])
        self.assertTrue(NPagoHoras.objects.filter(codigo=7).exists())

    def test_un_alta_invalida_devuelve_el_modal_con_el_error(self):
        """200 con el fragmento, no 204: el usuario ve el error junto al campo."""
        self.client.force_login(self.admin)
        respuesta = self.client.post(
            reverse('prenomina:nuevo_nomenclador', args=['pagos-importe']),
            {'codigo': 8, 'descripcion': 'Rota',
             'tipo_valor': TipoValorImporte.FORMULA, 'formula': 'horas.__class__'},
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'atributos')
        self.assertFalse(NPagoImporte.objects.filter(codigo=8).exists())

    def test_borrar_un_concepto_en_uso_avisa_de_quien_lo_usa(self):
        self.client.force_login(self.admin)
        NClaveAusencia.objects.create(
            codigo=12, descripcion='Vacaciones', relacionado_con=self.concepto)
        respuesta = self.client.post(
            reverse('prenomina:eliminar_nomenclador',
                    args=['pagos-horas', self.concepto.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('Vacaciones', respuesta['HX-Trigger'])
        self.assertTrue(NPagoHoras.objects.filter(pk=self.concepto.pk).exists())

    def test_un_slug_inventado_da_404_sin_tocar_ningun_modelo(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse('prenomina:tarjeta_nomenclador', args=['inventado']))
        self.assertEqual(respuesta.status_code, 404)

    def test_el_comprobador_de_formulas_responde_en_espanol(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(
            reverse('prenomina:validar_formula'), {'formula': '{{horas}} * 1.25'},
            HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'Fórmula válida')

        respuesta = self.client.post(
            reverse('prenomina:validar_formula'), {'formula': '2 ^ 3'},
            HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'multiplicar')


class IntegracionConParametrosGenerales(TestCase):
    """Las tarjetas viven dentro de una pantalla que NO es de este módulo.

    Estas pruebas son la red que protege esa frontera: si alguien mueve el
    `{% include %}` de `_3_tiempo.html`, renombra una ruta o toca el acordeón,
    aquí se nota. Y a la inversa: comprueban que Horarios y Jornadas —lo que ya
    había en esa pantalla— siguen funcionando.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_param', password='clave', es_admin=True)

    def _pagina(self):
        self.client.force_login(self.admin)
        return self.client.get('/config/parametros/')

    def test_la_pantalla_de_parametros_sigue_cargando(self):
        self.assertEqual(self._pagina().status_code, 200)

    def test_las_cuatro_tarjetas_quedan_cableadas_en_la_pagina(self):
        contenido = self._pagina().content.decode()
        for tipo in ('claves-ausencia', 'pagos-horas', 'pagos-importe', 'escala-annos'):
            with self.subTest(tipo=tipo):
                self.assertIn(
                    reverse('prenomina:tarjeta_nomenclador', args=[tipo]), contenido)

    def test_las_tarjetas_se_cargan_al_revelarse_y_no_al_abrir_la_pagina(self):
        """Con `load` se consultaría aunque el acordeón siguiera colapsado."""
        contenido = self._pagina().content.decode()
        self.assertIn('revealed', contenido)

    def test_no_se_reutiliza_ninguna_clase_del_js_de_nomencladores(self):
        """Contrato de compatibilidad con el `switch` de `nomencladores_base.html`.

        Ese fichero engancha `.add-row-btn` en tiempo de parseo y delega
        `.edit-btn` / `.delete-btn` contra una lista cerrada de `table.id`. Si
        nuestras tarjetas usaran esas clases, sus manejadores intentarían
        gestionarlas. Se comprueba sobre el fragmento propio, no sobre la página
        entera, que sí las trae legítimamente de las tarjetas existentes.
        """
        from django.template.loader import render_to_string
        prohibidas = ('add-row-btn', 'edit-btn', 'delete-btn', 'save-create-btn',
                      'save-edit-btn', 'cancel-edit-btn', 'insert-row')
        fragmentos = [
            'pages/config/nomencladores/_5_prenomina_cards.html',
            'pages/prenomina/partials/_encabezado_tarjeta.html',
            'pages/prenomina/partials/_acciones_fila.html',
        ]
        for plantilla in fragmentos:
            html = render_to_string(plantilla, {'tipo': 'pagos-horas',
                                                'objeto': self.admin,
                                                'nombre': 'x'})
            for clase in prohibidas:
                with self.subTest(plantilla=plantilla, clase=clase):
                    self.assertNotIn(clase, html)

    def test_convivimos_con_lo_demas_de_tiempo_de_trabajo(self):
        """Regresión: no hemos desplazado lo que comparte acordeón con nosotros.

        «Tiempo de Trabajo» ya no contiene Horarios ni Jornadas —esas dos
        tarjetas se retiraron a petición de RRHH y en su lugar entraron
        Nocturnidad y Condiciones Laborales, que venían de «Laborales y
        Profesionales»—. Lo que esta prueba vigila es que las tarjetas de
        Pre-Nómina sigan conviviendo con las que sí están.
        """
        contenido = self._pagina().content.decode()
        self.assertIn('tabla-nocturnidad', contenido)
        self.assertIn('condiciones-table', contenido)
        # Y que lo retirado no haya vuelto por accidente.
        self.assertNotIn('horarios-table', contenido)
        self.assertNotIn('jornadas-table', contenido)


class BasePreNomina(TestCase):
    """Plantilla mínima con la que probar el reporte.

    Reproduce la cadena real trabajador → unidad de Orbith:
    `CAlta.cargo → CargoPlantilla.departamento → Departamento.unidad_organizativa`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=cls.tipo_unidad, grupo_nomina=1,
            orden_informe=1)
        cls.otra_unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=cls.tipo_unidad, grupo_nomina=2,
            orden_informe=2)
        cls.departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=cls.unidad,
            orden_informe=1)

        cls.grupo = NGrupoEscala.objects.create(nivel='IV')
        cls.ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=cls.grupo, salario_basico=Decimal('4000'))
        cls.cargo = CargoPlantilla.objects.create(
            ncargo=cls.ncargo, departamento=cls.departamento,
            cant_aprobada=10, orden_informe=1)

        cls.provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        cls.municipio = NMunicipio.objects.create(
            nombre='Playa', provincia=cls.provincia)
        cls.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True)

        # Los importes salen del nomenclador (el contrato ya no los guarda).
        from nomencladores.models import NImporteGradoCientifico, NPagoAdicional
        NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('1.00'))
        cls.cnci = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.CNCI, descripcion='Etapa I', importe=Decimal('30.00'))
        cls.cnci_2 = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.CNCI, descripcion='Etapa II', importe=Decimal('75.00'))
        cls.instructor = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.INSTRUCTOR, descripcion='15h', importe=Decimal('5.00'))

        cls.aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Ana', papellido='Pérez', sapellido='Gómez',
            doc_identidad='85010112345', estado='ACTIVO', sexo='F', raza='BL',
            provincia=cls.provincia, municipio=cls.municipio, grado_cientifico='MC')
        cls.contrato = CAlta.objects.create(
            aspirante=cls.aspirante, no_expediente='00100',
            tipo=cls.tipo_contrato, cargo=cls.cargo,
            tipo_salario='FIJ',
            fecha_alta=date(2020, 1, 15), fecha_alta_entidad=date(2020, 1, 15),
            cnci_nomenclador=cls.cnci, instructor_nomenclador=cls.instructor)

        cls.admin = CustomUser.objects.create_user(
            username='admin_pn3', password='clave', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_pn3', password='clave', es_moderador=True)
        cls.moderador.unidades.add(cls.unidad)
        cls.ajeno = CustomUser.objects.create_user(
            username='mod_ajeno_pn3', password='clave', es_moderador=True)
        cls.ajeno.unidades.add(cls.otra_unidad)
        cls.observador = CustomUser.objects.create_user(
            username='obs_pn3', password='clave', es_observador=True)
        cls.observador.unidades.add(cls.unidad)

    def preparar_calendario(self, usuario, periodo, horas=Decimal('184.00')):
        """Jornada, período de calendario y asignación del trabajador.

        Desde la fase 2 las horas del mes salen del Calendario de Pago: sin esto,
        `crear_reporte()` se niega a montar el reporte porque no sabría con qué
        fondo de tiempo calcular a cada trabajador. Se hace en un método aparte
        para que las pruebas que comprueban justamente esa negativa puedan no
        llamarlo.

        Es idempotente: varias llamadas para el mismo usuario y período
        reutilizan lo que ya exista, que es lo que necesitan las pruebas que
        crean dos reportes seguidos.
        """
        from . import servicios_calendario as sc
        from .models import AsignacionCalendario, Calendario, CalendarioPago

        calendario, _ = Calendario.objects.get_or_create(
            usuario=usuario, codigo=1,
            defaults={'descripcion': 'Jornada Normal', 'activo': True})
        pago, _ = CalendarioPago.objects.get_or_create(
            usuario=usuario, anno=periodo.anno, mes=periodo.mes)
        if not pago.detalles.filter(calendario=calendario).exists():
            sc.seleccionar_calendarios(pago, usuario, [calendario.pk])
        detalle = pago.detalles.get(calendario=calendario)
        if detalle.horas_q1 + detalle.horas_q2 != horas:
            detalle.horas_q1 = horas
            detalle.horas_q2 = Decimal('0')
            detalle.save(update_fields=['horas_q1', 'horas_q2'])

        for contrato in CAlta.objects.all():
            AsignacionCalendario.objects.update_or_create(
                contrato=contrato,
                defaults={'calendario': calendario, 'asignado_por': usuario})
        return calendario

    def plantilla_de(self, usuario=None, descripcion='Plantilla de prueba',
                     ausencias=(), horas=(), importes=()):
        """Plantilla mínima para las pruebas que pasan por la pantalla de alta.

        El formulario de «Nuevo reporte» exige una plantilla desde que los
        conceptos salen de ahí; las pruebas que llaman directamente al servicio
        `crear_reporte()` no la necesitan y pueden seguir sin ella.

        Si no se pide ningún concepto se crea uno cualquiera: una plantilla vacía
        no se puede guardar, y estas pruebas no van de eso.
        """
        from . import servicios_plantilla

        if not (ausencias or horas or importes):
            pago, _ = NPagoHoras.objects.get_or_create(
                codigo=99, defaults={'descripcion': 'Concepto de prueba'})
            horas = [pago.codigo]

        return servicios_plantilla.crear_plantilla(
            usuario or self.moderador, descripcion=descripcion,
            codigos_ausencia=ausencias, codigos_horas=horas,
            codigos_importe=importes)

    def crear(self, periodo=None, usuario=None, unidad=None,
              horas_mes=Decimal('184.00'), con_calendario=True, **extra):
        periodo = periodo or Periodo(2026, 7)
        usuario = usuario or self.moderador
        if con_calendario:
            self.preparar_calendario(usuario, periodo, horas_mes)

        datos = {
            'fondo_tarifa': Decimal('190.60'),
            'fecha_desde': date(2026, 7, 1),
            'fecha_hasta': date(2026, 7, 31),
        }
        datos.update(extra)
        return servicios.crear_reporte(
            unidad or self.unidad, periodo, usuario, **datos)


class CreacionDelReporte(BasePreNomina):

    def test_al_crear_se_cargan_los_trabajadores_de_la_unidad(self):
        reporte = self.crear()
        self.assertEqual(reporte.trabajadores.count(), 1)
        self.assertEqual(reporte.total_trabajadores, 1)
        fila = reporte.trabajadores.first()
        self.assertEqual(fila.no_expediente, '00100')
        self.assertEqual(fila.nombre_completo, 'Ana Pérez Gómez')

    def test_la_estructura_de_la_unidad_queda_congelada_en_la_cabecera(self):
        reporte = self.crear()
        self.assertEqual(reporte.unidad_descripcion, 'UEB Central')
        self.assertEqual(reporte.unidad_grupo_nomina, 1)
        self.assertEqual(reporte.unidad_codigo_original, self.unidad.pk)

    def test_no_se_pueden_crear_dos_reportes_para_la_misma_unidad_y_periodo(self):
        self.crear()
        servicios.cerrar_reporte(
            ReportePago.objects.get(anno=2026, mes=7), self.moderador)
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear()
        self.assertIn('Ya existe un reporte', str(caja.exception))

    def test_la_base_de_datos_impide_la_duplicidad_unidad_mes_anno(self):
        """La regla no depende de que alguien llame al servicio."""
        self.crear()
        with self.assertRaises(IntegrityError):
            ReportePago.objects.create(
                unidad=self.unidad, anno=2026, mes=7,
                estado=EstadoReporte.CERRADO,
                fondo_tiempo=Decimal('184'), fondo_tarifa=Decimal('190.6'),
                fecha_desde=date(2026, 7, 1), fecha_hasta=date(2026, 7, 31))

    def test_una_unidad_solo_admite_un_borrador_a_la_vez(self):
        self.crear()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear(periodo=Periodo(2026, 8))
        self.assertIn('Borrador', str(caja.exception))

    def test_la_base_de_datos_impide_el_segundo_borrador(self):
        """Índice único parcial: protege aunque no se pase por el servicio."""
        self.crear()
        with self.assertRaises(IntegrityError):
            ReportePago.objects.create(
                unidad=self.unidad, anno=2026, mes=8,
                estado=EstadoReporte.BORRADOR,
                fondo_tiempo=Decimal('184'), fondo_tarifa=Decimal('190.6'),
                fecha_desde=date(2026, 8, 1), fecha_hasta=date(2026, 8, 31))

    def test_el_reporte_de_una_unidad_principal_recoge_sus_subunidades(self):
        """El alcance expande hacia abajo: el padre paga la nómina de su rama."""
        padre, hija = self._rama_con_subunidad()

        reporte = self.crear(unidad=padre, usuario=self.admin)

        # El trabajador vive en la hija y aparece en el reporte del padre.
        self.assertEqual(reporte.total_trabajadores, 1)
        self.assertEqual(reporte.trabajadores.first().no_expediente, '00700')

    def test_un_trabajador_no_puede_estar_en_dos_reportes_del_mismo_mes(self):
        """La contrapartida de expandir a subunidades: nadie se paga dos veces."""
        padre, hija = self._rama_con_subunidad()
        self.crear(unidad=hija, usuario=self.admin)

        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear(unidad=padre, usuario=self.admin)
        self.assertIn('00700', str(caja.exception))
        self.assertIn('dos nóminas', str(caja.exception))

    def test_el_solape_solo_mira_el_mismo_periodo(self):
        """Un reporte de otro mes no estorba."""
        padre, hija = self._rama_con_subunidad()
        servicios.cerrar_reporte(
            self.crear(unidad=hija, usuario=self.admin), self.admin)

        # Agosto del padre: el de julio de la hija no debe bloquearlo.
        reporte = self.crear(unidad=padre, usuario=self.admin,
                             periodo=Periodo(2026, 8),
                             fecha_desde=date(2026, 8, 1),
                             fecha_hasta=date(2026, 8, 31))
        self.assertEqual(reporte.total_trabajadores, 1)

    def _rama_con_subunidad(self):
        """Una Dirección Principal con una subunidad que sí tiene trabajadores."""
        tipo_padre = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección Principal', es_principal=True)
        padre = UnidadOrganizativa.objects.create(
            descripcion='Oficina Central', tipo=tipo_padre, grupo_nomina=9,
            orden_informe=10)
        tipo_hija = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True, tipo_padre=tipo_padre)
        hija = UnidadOrganizativa.objects.create(
            descripcion='Sub A', tipo=tipo_hija, padre=padre, orden_informe=1)

        departamento = Departamento.objects.create(
            descripcion='Depto Sub', unidad_organizativa=hija, orden_informe=1)
        cargo = CargoPlantilla.objects.create(
            ncargo=self.ncargo, departamento=departamento, cant_aprobada=5,
            orden_informe=1)
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Sub', papellido='Trabajador', sapellido='Uno',
            doc_identidad='90030376543', estado='ACTIVO', sexo='M', raza='BL',
            provincia=self.provincia, municipio=self.municipio)
        CAlta.objects.create(
            aspirante=aspirante, no_expediente='00700', tipo=self.tipo_contrato,
            cargo=cargo, tipo_salario='FIJ', fecha_alta=date(2020, 1, 15),
            fecha_alta_entidad=date(2020, 1, 15))

        self.admin.unidades.add(padre, hija)
        return padre, hija

    def test_las_fechas_del_periodo_deben_ser_coherentes(self):
        with self.assertRaises(servicios.ErrorDePreNomina):
            self.crear(fecha_desde=date(2026, 7, 31), fecha_hasta=date(2026, 7, 1))

    def test_un_moderador_no_crea_reportes_de_unidades_ajenas(self):
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear(usuario=self.ajeno)
        self.assertIn('asignadas', str(caja.exception))

    def test_un_observador_no_crea_reportes(self):
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear(usuario=self.observador)
        self.assertIn('consultar', str(caja.exception))

    def test_la_creacion_queda_auditada(self):
        from auditoria.models import EventoAuditoria
        self.crear()
        self.assertTrue(
            EventoAuditoria.objects.filter(modulo='prenomina').exists())


class PagoQuincenal(BasePreNomina):
    """Con período de pago Quincenal caben DOS reportes por unidad y mes.

    Lo decide `Configuracion.periodo` (15 Quincenal, 30 Mensual). El resto de
    las pruebas del módulo corren sin ninguna `Configuracion` creada, así que
    para ellas la entidad es Mensual y todo se comporta como antes: aquí se
    prueba justamente lo contrario.
    """

    def setUp(self):
        super().setUp()
        from configuracion.models import Configuracion
        Configuracion.objects.all().delete()
        Configuracion.objects.create(
            nombre_empresa='Prueba',
            periodo=Configuracion.PERIODO_QUINCENAL)

    def test_el_primer_reporte_del_mes_es_la_primera_quincena(self):
        reporte = self.crear()
        self.assertEqual(reporte.quincena, Quincena.PRIMERA)
        self.assertIn('1ra Quincena', reporte.etiqueta_periodo)

    def test_el_segundo_reporte_del_mes_es_la_segunda_quincena(self):
        primero = self.crear()
        servicios.cerrar_reporte(primero, self.moderador)

        segundo = self.crear()
        self.assertEqual(segundo.quincena, Quincena.SEGUNDA)
        self.assertEqual(segundo.anno, primero.anno)
        self.assertEqual(segundo.mes, primero.mes)

    def test_no_cabe_una_tercera_quincena(self):
        servicios.cerrar_reporte(self.crear(), self.moderador)
        servicios.cerrar_reporte(self.crear(), self.moderador)

        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear()
        self.assertIn('las dos quincenas', str(caja.exception))

    def test_el_mismo_trabajador_puede_estar_en_las_dos_quincenas(self):
        """Lo que `_exigir_sin_solape` NO debe bloquear.

        Antes de las quincenas, esa comprobación miraba solo año y mes, así que
        habría rechazado la 2da quincena por «doble pago» del mismo trabajador.
        """
        primera = self.crear()
        servicios.cerrar_reporte(primera, self.moderador)
        segunda = self.crear()

        self.assertEqual(primera.trabajadores.first().no_expediente, '00100')
        self.assertEqual(segunda.trabajadores.first().no_expediente, '00100')

    def test_la_base_de_datos_sigue_impidiendo_repetir_la_misma_quincena(self):
        """La clave única pasó a incluir la quincena, no a desaparecer."""
        self.crear()
        with self.assertRaises(IntegrityError):
            ReportePago.objects.create(
                unidad=self.unidad, anno=2026, mes=7,
                quincena=Quincena.PRIMERA, estado=EstadoReporte.CERRADO,
                fondo_tiempo=Decimal('184'), fondo_tarifa=Decimal('190.6'),
                fecha_desde=date(2026, 7, 1), fecha_hasta=date(2026, 7, 15))

    def test_hay_que_cerrar_la_primera_antes_de_empezar_la_segunda(self):
        self.crear()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            self.crear()
        self.assertIn('Borrador', str(caja.exception))

    def test_la_segunda_quincena_archiva_a_la_primera(self):
        primera = self.crear()
        servicios.cerrar_reporte(primera, self.moderador)
        self.crear()

        primera.refresh_from_db()
        self.assertEqual(primera.estado, EstadoReporte.HISTORICO)
        self.assertFalse(primera.es_ultimo)

    def test_las_fechas_propuestas_parten_el_mes(self):
        self.assertEqual(
            servicios.limites_del_periodo(2026, 7, Quincena.PRIMERA),
            (date(2026, 7, 1), date(2026, 7, 15)))
        self.assertEqual(
            servicios.limites_del_periodo(2026, 7, Quincena.SEGUNDA),
            (date(2026, 7, 16), date(2026, 7, 31)))
        # Febrero: la 2da quincena termina el 28, no el 30.
        self.assertEqual(
            servicios.limites_del_periodo(2026, 2, Quincena.SEGUNDA),
            (date(2026, 2, 16), date(2026, 2, 28)))

    def test_con_pago_mensual_la_etiqueta_no_menciona_quincenas(self):
        from configuracion.models import Configuracion
        Configuracion.objects.update(periodo=Configuracion.PERIODO_MENSUAL)
        reporte = self.crear()
        self.assertEqual(reporte.quincena, Quincena.MES_COMPLETO)
        self.assertNotIn('Quincena', reporte.etiqueta_periodo)


class FirmasRecordadas(BasePreNomina):
    """«Hecho por», «Revisado por» y «Aprobado por» se recuerdan por usuario."""

    def test_al_crear_un_reporte_se_guardan_las_tres_firmas(self):
        from configuracion.models import Configuracion
        Configuracion.objects.create(nombre_empresa='Prueba')
        self.client.force_login(self.moderador)
        plantilla = self.plantilla_de()
        # Sin Calendario de Pago, `crear_reporte()` se niega antes de llegar a
        # las firmas: esta prueba va de las firmas, no de esa negativa.
        self.preparar_calendario(self.moderador, Periodo(2026, 7))

        respuesta = self.client.post(reverse('prenomina:nuevo_reporte'), {
            'unidad': self.unidad.pk, 'anno': 2026, 'mes': 7,
            'plantilla': plantilla.pk,
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
            'hecho_por': 'Ana Gestora', 'revisado_por': 'Luis Revisor',
            'aprobado_por': 'Marta Directora',
        }, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)

        reporte = ReportePago.objects.get(anno=2026, mes=7)
        self.assertEqual(reporte.revisado_por, 'Luis Revisor')
        self.assertEqual(reporte.aprobado_por, 'Marta Directora')

        preferencias = self.moderador.obtener_preferencias()
        self.assertEqual(preferencias.reporte_hecho_por, 'Ana Gestora')
        self.assertEqual(preferencias.reporte_revisado_por, 'Luis Revisor')
        self.assertEqual(preferencias.reporte_aprobado_por, 'Marta Directora')

    def test_el_formulario_llega_con_las_firmas_de_la_vez_anterior(self):
        preferencias = self.moderador.obtener_preferencias()
        preferencias.reporte_hecho_por = 'Ana Gestora'
        preferencias.reporte_revisado_por = 'Luis Revisor'
        preferencias.reporte_aprobado_por = 'Marta Directora'
        preferencias.save()

        formulario = ReportePagoForm(usuario=self.moderador)
        self.assertEqual(formulario.initial['hecho_por'], 'Ana Gestora')
        self.assertEqual(formulario.initial['revisado_por'], 'Luis Revisor')
        self.assertEqual(formulario.initial['aprobado_por'], 'Marta Directora')

    def test_sin_nada_recordado_se_propone_el_nombre_del_propio_usuario(self):
        formulario = ReportePagoForm(usuario=self.moderador)
        self.assertTrue(formulario.initial['hecho_por'])
        self.assertEqual(formulario.initial['revisado_por'], '')

    def test_el_formulario_muestra_el_periodo_de_pago_de_la_configuracion(self):
        from configuracion.models import Configuracion
        Configuracion.objects.all().delete()
        Configuracion.objects.create(
            nombre_empresa='Prueba',
            periodo=Configuracion.PERIODO_QUINCENAL)
        formulario = ReportePagoForm(usuario=self.moderador)
        self.assertEqual(formulario.initial['periodo_pago'], 'Quincenal')


class CongeladoDelTrabajador(BasePreNomina):
    """El hito de la fase: la fotografía tiene que sobrevivir a los datos vivos."""

    def test_se_congela_la_base_economica_del_contrato(self):
        reporte = self.crear()
        fila = reporte.trabajadores.first()
        self.assertEqual(fila.salario_escala, Decimal('4000.00'))
        self.assertEqual(fila.cnci, Decimal('30.00'))
        self.assertEqual(fila.maestria, 1)
        self.assertEqual(fila.instructor, Decimal('5.00'))
        self.assertEqual(fila.cat_ocupacional, 'TEC')
        self.assertEqual(fila.cat_ocupacional_desc, 'Técnico')

    def test_la_tarifa_horaria_sale_del_fondo_de_tarifa_y_no_del_fondo_del_mes(self):
        """Son dos magnitudes distintas: 190.6 divide, 184 son las horas del mes."""
        reporte = self.crear()
        fila = reporte.trabajadores.first()
        self.assertEqual(fila.tarifa_horaria,
                         (Decimal('4000') / Decimal('190.60')).quantize(Decimal('0.0001')))

    def test_los_annos_de_servicio_se_miden_al_cierre_del_periodo(self):
        """Y no contra la fecha de hoy: el documento es de SU mes."""
        reporte = self.crear()
        # Alta 15/01/2020, período que termina el 31/07/2026 -> 6 años completos.
        self.assertEqual(reporte.trabajadores.first().anos_servicio, 6)

    def test_annos_de_servicio_sin_fecha_de_alta_es_cero(self):
        self.assertEqual(captura.annos_de_servicio(None, date(2026, 7, 31)), 0)

    def test_annos_de_servicio_solo_cuenta_anos_completos(self):
        """Alta en diciembre de 2020 y corte en julio de 2026 son CINCO años:
        el sexto no se cumple hasta diciembre. Con alta en enero, sí son seis."""
        self.assertEqual(
            captura.annos_de_servicio(date(2020, 12, 1), date(2026, 7, 31)), 5)
        self.assertEqual(
            captura.annos_de_servicio(date(2020, 1, 1), date(2026, 7, 31)), 6)

    def test_annos_de_servicio_no_es_negativo(self):
        """Un alta posterior al período no debe dar antigüedad negativa."""
        self.assertEqual(
            captura.annos_de_servicio(date(2027, 1, 1), date(2026, 7, 31)), 0)

    def test_cambiar_el_salario_despues_no_altera_el_reporte(self):
        reporte = self.crear()
        original = reporte.trabajadores.first().salario_escala

        self.ncargo.salario_basico = Decimal('9999')
        self.ncargo.save()
        self.contrato.save()  # recalcula salario_actual

        reporte.refresh_from_db()
        self.assertEqual(reporte.trabajadores.first().salario_escala, original)

    def test_cambiar_la_categoria_despues_no_altera_el_reporte(self):
        reporte = self.crear()
        self.ncargo.cat_ocupacional = 'OPE'
        self.ncargo.save()
        self.assertEqual(reporte.trabajadores.first().cat_ocupacional, 'TEC')

    def test_borrar_el_contrato_no_rompe_el_reporte(self):
        """EL escenario que este módulo existe para sobrevivir.

        Al dar de baja a un trabajador, Orbith BORRA físicamente su `CAlta` y
        crea un `CBaja`. Con una ForeignKey, el reporte de julio quedaría
        inconsultable en agosto.
        """
        reporte = self.crear()
        antes = {
            'expediente': reporte.trabajadores.first().no_expediente,
            'nombre': reporte.trabajadores.first().nombre_completo,
            'salario': reporte.trabajadores.first().salario_escala,
            'ci': reporte.trabajadores.first().doc_identidad,
        }

        self.contrato.delete()
        self.assertFalse(CAlta.objects.filter(no_expediente='00100').exists())

        reporte.refresh_from_db()
        fila = reporte.trabajadores.first()
        self.assertIsNotNone(fila)
        self.assertEqual(fila.no_expediente, antes['expediente'])
        self.assertEqual(fila.nombre_completo, antes['nombre'])
        self.assertEqual(fila.salario_escala, antes['salario'])
        self.assertEqual(fila.doc_identidad, antes['ci'])

    def test_borrar_la_unidad_no_puede_borrar_un_reporte(self):
        """PROTECT: un reporte de pago es el respaldo documental de un pago."""
        from django.db.models import ProtectedError
        self.crear()
        with self.assertRaises(ProtectedError):
            self.unidad.delete()


class TrabajadoresDelReporte(BasePreNomina):

    def test_se_puede_quitar_y_volver_a_agregar_un_trabajador(self):
        reporte = self.crear()
        fila = reporte.trabajadores.first()

        servicios.quitar_trabajador(reporte, fila.pk, self.moderador)
        reporte.refresh_from_db()
        self.assertEqual(reporte.trabajadores.count(), 0)
        self.assertEqual(reporte.total_trabajadores, 0)

        servicios.agregar_trabajador(reporte, '00100', self.moderador)
        reporte.refresh_from_db()
        self.assertEqual(reporte.trabajadores.count(), 1)
        self.assertEqual(reporte.total_trabajadores, 1)

    def test_no_se_puede_agregar_a_quien_no_trabaja_en_la_unidad(self):
        """El reporte nunca inventa datos de un trabajador."""
        reporte = self.crear()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.agregar_trabajador(reporte, '99999', self.moderador)
        self.assertIn('99999', str(caja.exception))

    def test_importes_reales_de_tres_y_cuatro_cifras(self):
        """Instructor tenía tope en 99,99 y Maestría era entera: un instructor de 1000
        (Res. 458/23) hacía fallar la creación del reporte (23-10-2026)."""
        from nomencladores.models import NImporteGradoCientifico
        self.instructor.importe = Decimal('1000.00')
        self.instructor.save()
        NImporteGradoCientifico.objects.filter(grado='MC').update(importe=Decimal('440.50'))
        fila = self.crear().trabajadores.first()
        self.assertEqual((fila.instructor, fila.maestria), (Decimal('1000.00'), Decimal('440.50')))

    def test_reagregar_a_alguien_ya_presente_recongela_su_ficha(self):
        """Es el botón «Actualizar datos del trabajador»."""
        reporte = self.crear()
        self.contrato.cnci_nomenclador = self.cnci_2
        self.contrato.save()

        servicios.agregar_trabajador(reporte, '00100', self.moderador)
        reporte.refresh_from_db()
        self.assertEqual(reporte.trabajadores.count(), 1)
        self.assertEqual(reporte.trabajadores.first().cnci, Decimal('75.00'))

    def test_un_trabajador_dado_de_baja_no_entra_en_el_reporte(self):
        self.aspirante.estado = 'BAJA'
        self.aspirante.save()
        reporte = self.crear()
        self.assertEqual(reporte.trabajadores.count(), 0)

    def test_un_moderador_ajeno_no_toca_los_trabajadores(self):
        reporte = self.crear()
        fila = reporte.trabajadores.first()
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.quitar_trabajador(reporte, fila.pk, self.ajeno)


class CicloDeVidaDelReporte(BasePreNomina):
    """La regla acordada: se reabre mientras sea el último de su unidad."""

    def test_no_se_cierra_un_reporte_sin_trabajadores(self):
        reporte = self.crear()
        reporte.trabajadores.all().delete()
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.cerrar_reporte(reporte, self.moderador)

    def test_al_cerrar_se_congela_quien_lo_cerro(self):
        reporte = servicios.cerrar_reporte(self.crear(), self.moderador)
        self.assertEqual(reporte.estado, EstadoReporte.CERRADO)
        self.assertEqual(reporte.cerrado_por, self.moderador)
        self.assertEqual(reporte.cerrado_por_nombre, 'mod_pn3')
        self.assertIsNotNone(reporte.fecha_cierre)

    def test_un_reporte_cerrado_no_admite_cambios(self):
        reporte = servicios.cerrar_reporte(self.crear(), self.moderador)
        fila = reporte.trabajadores.first()
        for llamada in (
            lambda: servicios.quitar_trabajador(reporte, fila.pk, self.moderador),
            lambda: servicios.agregar_trabajador(reporte, '00100', self.moderador),
            lambda: servicios.cerrar_reporte(reporte, self.moderador),
        ):
            with self.subTest(llamada=llamada):
                with self.assertRaises(servicios.ErrorDePreNomina):
                    llamada()

    def test_el_ultimo_cerrado_se_puede_reabrir(self):
        reporte = servicios.cerrar_reporte(self.crear(), self.moderador)
        reabierto = servicios.reabrir_reporte(reporte, self.moderador)
        self.assertEqual(reabierto.estado, EstadoReporte.BORRADOR)
        self.assertIsNone(reabierto.fecha_cierre)
        self.assertEqual(reabierto.cerrado_por_nombre, '')

    def test_al_crear_el_mes_siguiente_el_anterior_pasa_a_historico(self):
        julio = servicios.cerrar_reporte(self.crear(), self.moderador)
        self.crear(periodo=Periodo(2026, 8),
                   fecha_desde=date(2026, 8, 1), fecha_hasta=date(2026, 8, 31))

        julio.refresh_from_db()
        self.assertEqual(julio.estado, EstadoReporte.HISTORICO)

    def test_un_reporte_historico_ya_no_se_reabre(self):
        julio = servicios.cerrar_reporte(self.crear(), self.moderador)
        self.crear(periodo=Periodo(2026, 8),
                   fecha_desde=date(2026, 8, 1), fecha_hasta=date(2026, 8, 31))
        julio.refresh_from_db()

        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.reabrir_reporte(julio, self.moderador)
        self.assertIn('histórico', str(caja.exception).lower())

    def test_es_ultimo_distingue_el_reporte_vigente(self):
        julio = servicios.cerrar_reporte(self.crear(), self.moderador)
        self.assertTrue(julio.es_ultimo)
        self.assertTrue(julio.reabrible)

        agosto = self.crear(periodo=Periodo(2026, 8),
                            fecha_desde=date(2026, 8, 1),
                            fecha_hasta=date(2026, 8, 31))
        julio.refresh_from_db()
        self.assertFalse(julio.es_ultimo)
        self.assertFalse(julio.reabrible)
        self.assertTrue(agosto.es_ultimo)

    def test_un_borrador_no_se_reabre(self):
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.reabrir_reporte(self.crear(), self.moderador)

    def test_un_observador_no_cierra_ni_reabre(self):
        reporte = self.crear()
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.cerrar_reporte(reporte, self.observador)


class AlcancePorUnidad(BasePreNomina):

    def test_cada_rol_ve_lo_que_le_corresponde(self):
        mio = self.crear()
        servicios.cerrar_reporte(mio, self.moderador)
        ajeno = self.crear(unidad=self.otra_unidad, usuario=self.ajeno)

        self.assertEqual(filtros.reportes_visibles(self.admin).count(), 2)
        self.assertEqual(
            list(filtros.reportes_visibles(self.moderador)), [mio])
        self.assertEqual(
            list(filtros.reportes_visibles(self.ajeno)), [ajeno])
        # El Observador no tiene acceso al módulo: no ve nada, ni lo de su unidad.
        self.assertEqual(
            list(filtros.reportes_visibles(self.observador)), [])

    def test_un_anonimo_no_ve_nada(self):
        """Un usuario sin rol es imposible (`CustomUser` tiene un CheckConstraint
        de exactamente-un-rol), así que el caso alcanzable es el anónimo."""
        from django.contrib.auth.models import AnonymousUser
        self.crear()
        self.assertEqual(filtros.reportes_visibles(AnonymousUser()).count(), 0)
        self.assertEqual(filtros.unidades_gestionables(AnonymousUser()).count(), 0)

    def test_las_unidades_principales_si_son_gestionables(self):
        """A diferencia de Cierres: aquí el padre paga la nómina de su rama."""
        tipo_padre = NTipoUnidadOrganizativa.objects.create(
            descripcion='Principal', es_principal=True)
        padre = UnidadOrganizativa.objects.create(
            descripcion='Central', tipo=tipo_padre, grupo_nomina=9)
        self.assertIn(padre, filtros.unidades_gestionables(self.admin))
        self.assertIn(self.unidad, filtros.unidades_gestionables(self.admin))

    def test_el_observador_no_gestiona_ninguna_unidad(self):
        self.assertEqual(filtros.unidades_gestionables(self.observador).count(), 0)


class SelectorDePeriodo(BasePreNomina):
    """Las parejas de <select> «Año»/«Mes» son ahora el selector común de período.

    Lo que se fija aquí es el contrato entre las vistas y la rejilla de meses:
    qué meses existen ya, entre qué años se navega y —en «Crear Período»— cuál es
    el mínimo. Las tres pantallas conservan los `id` `filtro_anno`/`filtro_mes`
    porque varios `hx-include` de Pre-Nómina apuntan a ellos.
    """

    def setUp(self):
        self.client.force_login(self.admin)

    def test_el_calendario_dice_que_periodos_existen(self):
        CalendarioPago.objects.create(usuario=self.admin, anno=2026, mes=8)
        CalendarioPago.objects.create(usuario=self.admin, anno=2026, mes=9)

        respuesta = self.client.get(reverse('prenomina:tarjeta_periodo'))

        self.assertEqual(respuesta.context['periodos_existentes'], ['2026-09', '2026-08'])

    def test_el_calendario_conserva_los_ids_que_usan_los_hx_include(self):
        respuesta = self.client.get(reverse('prenomina:tarjeta_periodo'))
        contenido = respuesta.content.decode()
        self.assertIn('id="filtro_anno"', contenido)
        self.assertIn('id="filtro_mes"', contenido)
        self.assertIn('caja_periodo_calendario', contenido)

    def test_crear_periodo_apaga_lo_anterior_al_ultimo(self):
        """La regla de `crear_periodo()` se ve en la rejilla en vez de descubrirse
        al recibir el error."""
        CalendarioPago.objects.create(usuario=self.admin, anno=2026, mes=9)

        respuesta = self.client.get(reverse('prenomina:nuevo_periodo'))

        self.assertEqual(respuesta.context['minimo_periodo'], '2026-09')
        self.assertEqual(respuesta.context['periodos_existentes'], ['2026-09'])

    def test_sin_ningun_periodo_no_hay_minimo(self):
        respuesta = self.client.get(reverse('prenomina:nuevo_periodo'))
        self.assertEqual(respuesta.context['minimo_periodo'], '')
        self.assertEqual(respuesta.context['periodos_existentes'], [])

    def test_crear_periodo_repinta_lo_elegido_tras_un_error(self):
        """Reabrir la rejilla en blanco obligaría a empezar de cero."""
        CalendarioPago.objects.create(usuario=self.admin, anno=2026, mes=9)

        # Junio es anterior al último período: `crear_periodo()` lo rechaza.
        respuesta = self.client.post(reverse('prenomina:nuevo_periodo'),
                                     {'anno': '2026', 'mes': '6'})

        self.assertTrue(respuesta.context['error'])
        self.assertEqual(respuesta.context['anno_inicial'], '2026')
        self.assertEqual(respuesta.context['mes_inicial'], '6')

    def test_el_formulario_sigue_enviando_anno_y_mes(self):
        """Los campos ocultos del componente se llaman igual que los <select> que
        sustituyen, así que el POST de alta no cambia."""
        respuesta = self.client.post(reverse('prenomina:nuevo_periodo'),
                                     {'anno': '2026', 'mes': '11'})

        self.assertTrue(CalendarioPago.objects.filter(
            usuario=self.admin, anno=2026, mes=11).exists())
        self.assertEqual(respuesta.status_code, 204)


class PantallaDeReportes(BasePreNomina):
    """Las vistas del listado, con los tres roles."""

    def test_administrador_y_moderador_entran_en_el_listado(self):
        for usuario in (self.admin, self.moderador):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                self.assertEqual(
                    self.client.get(reverse('prenomina:lista_reportes')).status_code,
                    200)

    def test_el_observador_no_entra_en_el_listado(self):
        self.client.force_login(self.observador)
        self.assertEqual(
            self.client.get(reverse('prenomina:lista_reportes')).status_code, 403)

    def test_el_listado_solo_muestra_los_reportes_del_alcance(self):
        mio = self.crear()
        servicios.cerrar_reporte(mio, self.moderador)
        self.crear(unidad=self.otra_unidad, usuario=self.ajeno)

        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('prenomina:lista_reportes'))
        self.assertContains(respuesta, 'UEB Central')
        self.assertNotContains(respuesta, 'UEB Norte')

    def test_el_moderador_si_ve_el_boton_de_crear(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('prenomina:lista_reportes'))
        self.assertContains(respuesta, 'Nuevo reporte')

    def test_el_observador_no_puede_abrir_el_alta_ni_forzando_la_url(self):
        """Ocultar el botón no es la protección."""
        self.client.force_login(self.observador)
        respuesta = self.client.get(reverse('prenomina:nuevo_reporte'),
                                    HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 403)

    def test_el_observador_no_puede_cerrar_ni_reabrir(self):
        reporte = self.crear()
        self.client.force_login(self.observador)
        for ruta in ('prenomina:cerrar_reporte', 'prenomina:reabrir_reporte'):
            with self.subTest(ruta=ruta):
                respuesta = self.client.post(reverse(ruta, args=[reporte.pk]),
                                             HTTP_HX_REQUEST='true')
                self.assertEqual(respuesta.status_code, 403)

    def test_un_moderador_ajeno_recibe_404_y_no_403(self):
        """404, no 403: un 403 le confirmaría que ese reporte existe."""
        reporte = self.crear()
        self.client.force_login(self.ajeno)
        respuesta = self.client.post(
            reverse('prenomina:cerrar_reporte', args=[reporte.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 404)

    def test_el_alta_desde_la_pantalla_crea_el_reporte(self):
        from configuracion.models import Configuracion
        Configuracion.objects.create(nombre_empresa='Prueba')
        # Las horas del mes salen del Calendario de Pago: hay que tenerlo montado
        # antes de dar de alta el reporte, igual que en el uso real.
        self.preparar_calendario(self.moderador, Periodo(2026, 7))
        plantilla = self.plantilla_de()
        self.client.force_login(self.moderador)
        respuesta = self.client.post(reverse('prenomina:nuevo_reporte'), {
            'unidad': self.unidad.pk, 'anno': 2026, 'mes': 7,
            'fondo_tarifa': '190.60', 'plantilla': plantilla.pk,
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
            'hecho_por': 'Ana',
        }, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('actualizarListaReportes', respuesta['HX-Trigger'])
        reporte = ReportePago.objects.get(unidad=self.unidad, anno=2026, mes=7)
        self.assertEqual(reporte.total_trabajadores, 1)

    def test_el_desplegable_solo_ofrece_las_unidades_del_moderador(self):
        self.plantilla_de()
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('prenomina:nuevo_reporte'),
                                    HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'UEB Central')
        self.assertNotContains(respuesta, 'UEB Norte')

    def test_sin_plantillas_el_alta_explica_que_falta_crear_una(self):
        """Los conceptos salen de una plantilla: sin ninguna no hay reporte."""
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('prenomina:nuevo_reporte'),
                                    HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'Primero necesita una plantilla')
        self.assertContains(respuesta, 'Mis Plantillas')

    def test_el_alta_de_una_unidad_ajena_se_rechaza_aunque_se_fuerce_el_post(self):
        """El desplegable es comodidad; la seguridad la impone el servicio."""
        self.client.force_login(self.moderador)
        respuesta = self.client.post(reverse('prenomina:nuevo_reporte'), {
            'unidad': self.otra_unidad.pk, 'anno': 2026, 'mes': 7,
            'fondo_tiempo': '184.00', 'fondo_tarifa': '190.60',
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
        }, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 200)  # vuelve el modal con error
        self.assertFalse(ReportePago.objects.filter(unidad=self.otra_unidad).exists())

    def test_el_error_del_servicio_se_muestra_en_el_modal(self):
        self.crear()
        plantilla = self.plantilla_de()
        self.client.force_login(self.moderador)
        respuesta = self.client.post(reverse('prenomina:nuevo_reporte'), {
            'unidad': self.unidad.pk, 'anno': 2026, 'mes': 8,
            'fondo_tarifa': '190.60', 'plantilla': plantilla.pk,
            'fecha_desde': '2026-08-01', 'fecha_hasta': '2026-08-31',
        }, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Borrador')

    def test_el_reporte_congela_el_fondo_de_tarifa_de_la_configuracion(self):
        """El fondo de la tarifa dejó de preguntarse: sale de Configuración.

        `fondo_tarifa=None` es el alta normal, la que ya no incluye ese campo en
        el formulario. El número se sigue COPIANDO en el reporte para que cerrar
        y recalcular años después dé lo mismo aunque el parámetro cambie.
        """
        from configuracion.models import Configuracion
        Configuracion.objects.create(
            nombre_empresa='Prueba', fondo_tiempo_calc_tarif=Decimal('176.00'),
            periodo=Configuracion.PERIODO_MENSUAL)
        reporte = self.crear(fondo_tarifa=None)
        self.assertEqual(reporte.fondo_tarifa, Decimal('176.00'))

    def test_sin_fondo_en_la_configuracion_no_se_crea(self):
        """Sin valor fijo de respaldo (23-10-2026): sin fondo de tiempo válido en
        Configuración el reporte no se crea y se explica dónde definirlo."""
        from prenomina.servicios import ErrorDePreNomina
        with self.assertRaisesMessage(ErrorDePreNomina, 'falta el fondo de tiempo'):
            self.crear(fondo_tarifa=None)

    def test_cerrar_y_reabrir_desde_la_pantalla(self):
        reporte = self.crear()
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:cerrar_reporte', args=[reporte.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        reporte.refresh_from_db()
        self.assertEqual(reporte.estado, EstadoReporte.CERRADO)

        respuesta = self.client.post(
            reverse('prenomina:reabrir_reporte', args=[reporte.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        reporte.refresh_from_db()
        self.assertEqual(reporte.estado, EstadoReporte.BORRADOR)

    def test_el_filtro_por_estado_funciona(self):
        servicios.cerrar_reporte(self.crear(), self.moderador)
        self.client.force_login(self.moderador)

        respuesta = self.client.get(reverse('prenomina:buscar_reportes'),
                                    {'estado': EstadoReporte.BORRADOR})
        self.assertNotContains(respuesta, 'UEB Central')

        respuesta = self.client.get(reverse('prenomina:buscar_reportes'),
                                    {'estado': EstadoReporte.CERRADO})
        self.assertContains(respuesta, 'UEB Central')


class BaseConConceptos(BasePreNomina):
    """Reporte con los conceptos del Excel real de RRHH ya configurados."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Pagos por horas (grupo púrpura del Excel).
        cls.h_extra = NPagoHoras.objects.create(codigo=2, descripcion='Horas Extra')
        cls.h_promedio = NPagoHoras.objects.create(
            codigo=5, descripcion='Horas por promedio')

        # Claves de ausencia (grupo verde).
        cls.a_vacaciones = NClaveAusencia.objects.create(
            codigo=12, descripcion='Vacaciones', resta_horas_mes=True,
            relacionado_con=cls.h_promedio)
        cls.a_injustificada = NClaveAusencia.objects.create(
            codigo=19, descripcion='Ausencia Injustificada', resta_horas_mes=True,
            resta_sistema_pago=False, resta_utilidades=False)
        cls.a_promedio = NClaveAusencia.objects.create(
            codigo=47, descripcion='Aplicar Sal Promedio', resta_horas_mes=False,
            relacionado_con=cls.h_promedio)

        # Pagos por importe (grupo rojo).
        cls.i_extras = NPagoImporte.objects.create(
            codigo=3, descripcion='Importe Horas Extras',
            tipo_valor=TipoValorImporte.FORMULA,
            formula='{{horas}} * {{tarifa_horaria}} * 1.25',
            relacionado_con=cls.h_extra)
        cls.i_cnci = NPagoImporte.objects.create(
            codigo=5, descripcion='C.N.C.I',
            tipo_valor=TipoValorImporte.FORMULA, formula='{{cnci}}')
        cls.i_annos = NPagoImporte.objects.create(
            codigo=9, descripcion='Años de servicio',
            tipo_valor=TipoValorImporte.ESCALA)

    def preparar(self, **extra):
        """Reporte con todos los conceptos seleccionados."""
        reporte = self.crear(**extra)
        servicios.configurar_conceptos(
            reporte, self.moderador,
            codigos_ausencia=[12, 19, 47],
            codigos_horas=[2, 5],
            codigos_importe=[5, 9])
        reporte.refresh_from_db()
        return reporte

    def fila(self, reporte):
        return reporte.trabajadores.first()


class ConfiguracionDeConceptos(BaseConConceptos):

    def test_los_conceptos_quedan_congelados_en_el_reporte(self):
        reporte = self.preparar()
        self.assertEqual(reporte.conceptos_ausencia.count(), 3)
        self.assertEqual(reporte.conceptos_horas.count(), 2)
        # 2 pedidos + «Importe Horas Extras», que entra solo por su relación.
        self.assertEqual(reporte.conceptos_importe.count(), 3)

    def test_un_importe_relacionado_entra_automaticamente(self):
        reporte = self.preparar()
        automatico = reporte.conceptos_importe.get(codigo=3)
        self.assertTrue(automatico.automatico)
        manual = reporte.conceptos_importe.get(codigo=5)
        self.assertFalse(manual.automatico)

    def test_pedir_a_mano_uno_ya_automatico_no_lo_duplica(self):
        """Es la misma intención: se ignora en vez de dar error."""
        reporte = self.crear()
        servicios.configurar_conceptos(
            reporte, self.moderador, codigos_ausencia=[],
            codigos_horas=[2], codigos_importe=[3])
        self.assertEqual(reporte.conceptos_importe.filter(codigo=3).count(), 1)

    def test_un_concepto_alimentado_por_una_ausencia_queda_marcado_derivado(self):
        reporte = self.preparar()
        self.assertTrue(reporte.conceptos_horas.get(codigo=5).es_derivado)
        self.assertFalse(reporte.conceptos_horas.get(codigo=2).es_derivado)

    def test_una_ausencia_exige_que_su_concepto_por_horas_este_seleccionado(self):
        reporte = self.crear()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.configurar_conceptos(
                reporte, self.moderador, codigos_ausencia=[12], codigos_horas=[])
        self.assertIn('Horas por promedio', str(caja.exception))

    def test_un_importe_con_horas_exige_su_concepto_por_horas(self):
        reporte = self.crear()
        manual = NPagoImporte.objects.create(
            codigo=99, descripcion='Suelto', tipo_valor=TipoValorImporte.FORMULA,
            formula='{{horas}} * 2', relacionado_con=self.h_extra)
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.configurar_conceptos(
                reporte, self.moderador, codigos_horas=[], codigos_importe=[99])

    def test_un_codigo_inexistente_se_rechaza(self):
        reporte = self.crear()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.configurar_conceptos(
                reporte, self.moderador, codigos_ausencia=[404])
        self.assertIn('404', str(caja.exception))

    def test_la_escala_de_annos_se_congela_entera_en_el_concepto(self):
        reporte = self.preparar()
        concepto = reporte.conceptos_importe.get(codigo=9)
        self.assertEqual(len(concepto.escala_congelada), 30)
        self.assertEqual(concepto.escala_congelada['5'], '1000.00')

    def test_cambiar_la_escala_despues_no_altera_el_reporte(self):
        reporte = self.preparar()
        NEscalaAnnosServicio.objects.filter(annos=6).update(cuantia=Decimal('9999'))
        concepto = reporte.conceptos_importe.get(codigo=9)
        self.assertEqual(concepto.escala_congelada['6'], '1080.00')

    def test_se_crea_una_celda_por_trabajador_y_concepto(self):
        """Filas densas: cada celda tiene identidad estable."""
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.assertEqual(fila.valores_ausencia.count(), 3)
        self.assertEqual(fila.valores_horas.count(), 2)
        self.assertEqual(fila.valores_importe.count(), 3)

    def test_quitar_un_concepto_avisa_de_los_valores_que_se_pierden(self):
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  ausencias={19: Decimal('8')})

        resumen = servicios.configurar_conceptos(
            reporte, self.moderador, codigos_ausencia=[12, 47],
            codigos_horas=[2, 5], codigos_importe=[5, 9])
        self.assertEqual(resumen['valores_perdidos'], 1)
        self.assertEqual(reporte.conceptos_ausencia.count(), 2)

    def test_un_reporte_cerrado_no_admite_reconfigurar_conceptos(self):
        reporte = self.preparar()
        servicios.cerrar_reporte(reporte, self.moderador)
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.configurar_conceptos(reporte, self.moderador,
                                           codigos_horas=[2])


class CalculoPuro(SimpleTestCase):
    """`calculos.py` sin base de datos."""

    class ConceptoFalso:
        def __init__(self, codigo, resta_horas_mes=True, relacionado=None):
            self.codigo = codigo
            self.resta_horas_mes = resta_horas_mes
            self.relacionado_con_codigo = relacionado

    def test_solo_restan_las_ausencias_marcadas(self):
        conceptos = [self.ConceptoFalso(12, True), self.ConceptoFalso(47, False)]
        horas = {12: Decimal('16'), 47: Decimal('8')}
        self.assertEqual(calculos.horas_descontadas(horas, conceptos), Decimal('16'))

    def test_las_horas_trabajadas_no_bajan_de_cero(self):
        self.assertEqual(
            calculos.horas_trabajadas(Decimal('184'), Decimal('200')), Decimal('0'))
        self.assertEqual(
            calculos.horas_trabajadas(Decimal('184'), Decimal('16')), Decimal('168'))

    def test_varias_ausencias_suman_en_el_mismo_concepto_derivado(self):
        """Suma, no 1:1: dos licencias pueden pagarse ambas por promedio."""
        conceptos = [self.ConceptoFalso(12, relacionado=5),
                     self.ConceptoFalso(47, relacionado=5),
                     self.ConceptoFalso(19)]
        horas = {12: Decimal('16'), 47: Decimal('8'), 19: Decimal('4')}
        self.assertEqual(calculos.derivar_horas(horas, conceptos),
                         {5: Decimal('24')})

    def test_el_redondeo_es_comercial_y_no_bancario(self):
        """El defecto de Python es ROUND_HALF_EVEN, que daría 2.34."""
        self.assertEqual(calculos.redondear(Decimal('2.345')), Decimal('2.35'))
        self.assertEqual(calculos.redondear(Decimal('2.355')), Decimal('2.36'))


class CapturaDeValores(BaseConConceptos):

    def test_la_identidad_aritmetica_se_cumple(self):
        """horas_trabajadas + Σ(ausencias que restan) == fondo del mes."""
        reporte = self.preparar()
        servicios.guardar_valores(
            self.fila(reporte).pk, self.moderador,
            ausencias={12: Decimal('16'), 19: Decimal('8'), 47: Decimal('4')})

        fila = self.fila(reporte)
        self.assertEqual(fila.total_horas_descontadas, Decimal('24.00'))
        self.assertEqual(fila.horas_trabajadas, Decimal('160.00'))
        self.assertEqual(fila.horas_trabajadas + fila.total_horas_descontadas,
                         reporte.fondo_tiempo)

    def test_una_ausencia_que_no_resta_no_reduce_las_horas(self):
        """Y aun así puede pagarse: los dos interruptores son independientes."""
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  ausencias={47: Decimal('8')})
        fila = self.fila(reporte)
        self.assertEqual(fila.total_horas_descontadas, Decimal('0.00'))
        self.assertEqual(fila.horas_trabajadas, Decimal('184.00'))
        # Pero sus horas SÍ alimentan el concepto por horas relacionado.
        derivado = fila.valores_horas.get(concepto__codigo=5)
        self.assertEqual(derivado.horas, Decimal('8.00'))

    def test_el_concepto_derivado_es_la_suma_de_sus_ausencias(self):
        reporte = self.preparar()
        servicios.guardar_valores(
            self.fila(reporte).pk, self.moderador,
            ausencias={12: Decimal('16'), 47: Decimal('8')})
        derivado = self.fila(reporte).valores_horas.get(concepto__codigo=5)
        self.assertEqual(derivado.horas, Decimal('24.00'))

    def test_no_se_puede_escribir_a_mano_un_concepto_derivado(self):
        reporte = self.preparar()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                      horas={5: Decimal('99')})
        self.assertIn('Horas por promedio', str(caja.exception))

    def test_un_concepto_no_derivado_si_se_escribe(self):
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  horas={2: Decimal('10')})
        self.assertEqual(
            self.fila(reporte).valores_horas.get(concepto__codigo=2).horas,
            Decimal('10.00'))

    def test_las_horas_negativas_se_rechazan_en_el_backend(self):
        """Nunca confiar solo en el JavaScript."""
        reporte = self.preparar()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                      ausencias={12: Decimal('-4')})
        self.assertIn('negativas', str(caja.exception))

    def test_no_se_puede_descontar_mas_que_el_fondo_del_mes(self):
        reporte = self.preparar()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                      ausencias={12: Decimal('200')})
        self.assertIn('184', str(caja.exception))

    def test_un_valor_disparatado_se_atrapa(self):
        """Teclear las horas del mes en la casilla de un concepto."""
        reporte = self.preparar()
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                      horas={2: Decimal('600')})

    def test_un_texto_donde_se_espera_un_numero_se_rechaza(self):
        reporte = self.preparar()
        with self.assertRaises(servicios.ErrorDePreNomina):
            servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                      ausencias={12: 'ocho'})

    def test_un_codigo_ajeno_al_reporte_se_rechaza(self):
        reporte = self.preparar()
        with self.assertRaises(servicios.ErrorDePreNomina) as caja:
            servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                      ausencias={999: Decimal('4')})
        self.assertIn('999', str(caja.exception))

    def test_la_base_de_datos_tambien_rechaza_las_horas_negativas(self):
        reporte = self.preparar()
        valor = self.fila(reporte).valores_ausencia.first()
        valor.horas = Decimal('-1')
        with self.assertRaises(IntegrityError):
            valor.save()


class CalculoDeImportes(BaseConConceptos):

    def test_una_formula_con_horas_usa_las_horas_del_concepto_relacionado(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        servicios.guardar_valores(fila.pk, self.moderador, horas={2: Decimal('10')})

        fila.refresh_from_db()
        valor = fila.valores_importe.get(concepto__codigo=3)
        esperado = calculos.redondear(
            Decimal('10') * fila.tarifa_horaria * Decimal('1.25'))
        self.assertEqual(valor.importe, esperado)
        self.assertEqual(valor.horas_base, Decimal('10.00'))

    def test_una_formula_sobre_un_campo_del_trabajador_no_necesita_horas(self):
        """C.N.C.I es «{{cnci}}»: sale del contrato congelado."""
        reporte = self.preparar()
        valor = self.fila(reporte).valores_importe.get(concepto__codigo=5)
        self.assertEqual(valor.importe, Decimal('30.00'))
        self.assertIsNone(valor.horas_base)

    def test_el_tipo_escala_busca_por_los_annos_de_servicio(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.assertEqual(fila.anos_servicio, 6)
        valor = fila.valores_importe.get(concepto__codigo=9)
        self.assertEqual(valor.importe, Decimal('1080.00'))

    def test_el_total_del_trabajador_suma_sus_importes(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        servicios.guardar_valores(fila.pk, self.moderador, horas={2: Decimal('10')})
        fila.refresh_from_db()
        suma = sum(v.importe for v in fila.valores_importe.all())
        self.assertEqual(fila.total_importe, suma)

    def test_los_totales_de_la_cabecera_cuadran(self):
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  ausencias={12: Decimal('16')})
        reporte.refresh_from_db()
        fila = self.fila(reporte)
        self.assertEqual(reporte.total_horas_trabajadas, fila.horas_trabajadas)
        self.assertEqual(reporte.total_importes, fila.total_importe)
        self.assertEqual(reporte.total_trabajadores, 1)

    def test_cambiar_la_formula_del_nomenclador_no_altera_el_reporte(self):
        """El histórico: la fórmula congelada es procedencia, no dependencia."""
        reporte = self.preparar()
        fila = self.fila(reporte)
        servicios.guardar_valores(fila.pk, self.moderador, horas={2: Decimal('10')})
        fila.refresh_from_db()
        antes = fila.valores_importe.get(concepto__codigo=3).importe

        self.i_extras.formula = '{{horas}} * 999'
        self.i_extras.save()

        calculos.recalcular_reporte(reporte)
        fila.refresh_from_db()
        self.assertEqual(fila.valores_importe.get(concepto__codigo=3).importe, antes)

    def test_el_recalculo_es_idempotente(self):
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  ausencias={12: Decimal('16')},
                                  horas={2: Decimal('10')})
        calculos.recalcular_reporte(reporte)
        primera = list(self.fila(reporte).valores_importe
                       .order_by('concepto__codigo').values_list('importe', flat=True))

        calculos.recalcular_reporte(reporte)
        segunda = list(self.fila(reporte).valores_importe
                       .order_by('concepto__codigo').values_list('importe', flat=True))
        self.assertEqual(primera, segunda)

    def test_verificar_integridad_no_encuentra_nada_en_un_reporte_sano(self):
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  ausencias={12: Decimal('16')})
        self.assertEqual(calculos.verificar_integridad(reporte), [])

    def test_verificar_integridad_detecta_un_desfase(self):
        reporte = self.preparar()
        ReporteTrabajador.objects.filter(pk=self.fila(reporte).pk).update(
            horas_trabajadas=Decimal('99'))
        self.assertTrue(calculos.verificar_integridad(reporte))


class TrabajadorAnadidoDespues(BaseConConceptos):

    def test_recibe_sus_celdas_y_sus_importes(self):
        """Sin esto, la fila saldría vacía y la importación no sabría dónde escribir."""
        reporte = self.preparar()
        fila = self.fila(reporte)
        servicios.quitar_trabajador(reporte, fila.pk, self.moderador)

        nueva = servicios.agregar_trabajador(reporte, '00100', self.moderador)
        self.assertEqual(nueva.valores_ausencia.count(), 3)
        self.assertEqual(nueva.valores_horas.count(), 2)
        self.assertEqual(nueva.valores_importe.count(), 3)
        # Y sus importes que no dependen de horas ya están calculados.
        self.assertEqual(
            nueva.valores_importe.get(concepto__codigo=5).importe, Decimal('30.00'))


class PantallaDeLaRejilla(BaseConConceptos):
    """Detalle del reporte y sus modales."""

    def test_la_rejilla_pinta_las_cinco_zonas_del_excel(self):
        reporte = self.preparar()
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:detalle_reporte', args=[reporte.pk]))

        self.assertEqual(respuesta.status_code, 200)
        for texto in ('Descuentos en horas (ausencias)', 'Horas trabajadas',
                      'Pagos asociados por horas', 'Pagos asociados por Importe',
                      'Salario Escala', 'Total a descontar'):
            with self.subTest(texto=texto):
                self.assertContains(respuesta, texto)

    def _poblar(self, reporte, cuantos):
        for indice in range(2, 2 + cuantos):
            aspirante = Aspirante.objects.create(nivel_educ='SA', 
                nombre=f'Trabajador{indice}', papellido='Prueba', sapellido='Test',
                doc_identidad=f'9002025432{indice}', estado='ACTIVO',
                sexo='M', raza='BL', provincia=self.provincia,
                municipio=self.municipio)
            CAlta.objects.create(
                aspirante=aspirante, no_expediente=f'0010{indice}',
                tipo=self.tipo_contrato, cargo=self.cargo, tipo_salario='FIJ',
                fecha_alta=date(2020, 1, 15), fecha_alta_entidad=date(2020, 1, 15))
            # Los contratos nacen después de `crear()`, así que no los alcanzó su
            # asignación de calendario: sin esto no tendrían horas del mes y
            # `agregar_trabajador` los rechazaría.
            self.preparar_calendario(self.moderador, reporte.periodo)
            servicios.agregar_trabajador(reporte, f'0010{indice}', self.moderador)

    def _consultas_de_la_rejilla(self, reporte):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as capturadas:
            self.client.get(reverse('prenomina:detalle_reporte', args=[reporte.pk]))
        return len(capturadas)

    def test_la_rejilla_no_dispara_una_consulta_por_fila(self):
        """El pivote se hace en Python, no en la plantilla.

        Se compara el coste de un reporte de 1 trabajador con el de 8, en vez de
        fijar un número absoluto: el absoluto depende de middlewares y context
        processors ajenos a este módulo, y se rompería sin que nada nuestro
        cambie. Lo que de verdad importa es que la rejilla sea de coste
        CONSTANTE.
        """
        self.client.force_login(self.moderador)

        reporte = self.preparar()
        self.assertEqual(reporte.trabajadores.count(), 1)

        # Petición de calentamiento: la primera de la sesión consulta cosas que
        # después quedan cacheadas (sesión, usuario), y ese coste de arranque no
        # tiene nada que ver con la rejilla. Sin esto la comparación mide eso.
        self._consultas_de_la_rejilla(reporte)

        coste_pequeno = self._consultas_de_la_rejilla(reporte)

        self._poblar(reporte, 7)
        self.assertEqual(reporte.trabajadores.count(), 8)
        coste_grande = self._consultas_de_la_rejilla(reporte)

        self.assertEqual(
            coste_pequeno, coste_grande,
            f'La rejilla consulta por fila: el coste pasó de {coste_pequeno} a '
            f'{coste_grande} al ir de 1 a 8 trabajadores.')

    def test_una_fila_suelta_se_devuelve_para_el_intercambio(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse(
            'prenomina:fila_trabajador', args=[reporte.pk, fila.pk]))
        self.assertContains(respuesta, f'id="fila-{fila.pk}"')
        self.assertContains(respuesta, '00100')

    def test_el_observador_no_ve_la_rejilla(self):
        reporte = self.preparar()
        self.client.force_login(self.observador)
        respuesta = self.client.get(
            reverse('prenomina:detalle_reporte', args=[reporte.pk]))
        self.assertEqual(respuesta.status_code, 403)

    def test_el_observador_no_abre_el_modal_de_captura(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.observador)
        respuesta = self.client.get(
            reverse('prenomina:valores_trabajador', args=[reporte.pk, fila.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 403)

    def test_un_moderador_ajeno_recibe_404_en_el_detalle(self):
        reporte = self.preparar()
        self.client.force_login(self.ajeno)
        respuesta = self.client.get(
            reverse('prenomina:detalle_reporte', args=[reporte.pk]))
        self.assertEqual(respuesta.status_code, 404)

    def test_el_modal_de_captura_bloquea_los_conceptos_derivados(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:valores_trabajador', args=[reporte.pk, fila.pk]),
            HTTP_HX_REQUEST='true')

        self.assertContains(respuesta, 'disabled readonly')
        self.assertContains(respuesta, 'Se calcula sumando')

    def test_guardar_desde_el_modal_actualiza_solo_esa_fila(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:valores_trabajador', args=[reporte.pk, fila.pk]),
            {'ausencia_12': '16', 'ausencia_19': '0', 'ausencia_47': '0',
             'horas_2': '10'},
            HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('filaActualizada', respuesta['HX-Trigger'])
        fila.refresh_from_db()
        self.assertEqual(fila.horas_trabajadas, Decimal('168.00'))

    def test_un_valor_invalido_devuelve_el_modal_con_el_error(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:valores_trabajador', args=[reporte.pk, fila.pk]),
            {'ausencia_12': '500'}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'superan')
        fila.refresh_from_db()
        self.assertEqual(fila.horas_trabajadas, Decimal('184.00'))

    def test_forjar_un_concepto_derivado_en_el_post_se_rechaza(self):
        """El campo va `disabled`, pero eso solo lo respeta el navegador."""
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:valores_trabajador', args=[reporte.pk, fila.pk]),
            {'horas_5': '99'}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no se pueden escribir a mano')

    def test_aplicar_una_plantilla_desde_la_pantalla_del_reporte(self):
        """Sustituye al antiguo marcado de conceptos, que ya no existe aquí."""
        reporte = self.crear()
        plantilla = self.plantilla_de(
            ausencias=['19'], horas=['2'], importes=['5'])
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:cambiar_plantilla', args=[reporte.pk]),
            {'plantilla': plantilla.pk}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('recargarReporte', respuesta['HX-Trigger'])
        self.assertEqual(reporte.conceptos_ausencia.count(), 1)
        self.assertEqual(reporte.conceptos_horas.count(), 1)
        reporte.refresh_from_db()
        self.assertEqual(reporte.plantilla_id, plantilla.pk)

    def test_no_se_aplica_una_plantilla_de_otro_usuario(self):
        reporte = self.crear()
        ajena = self.plantilla_de(usuario=self.ajeno, descripcion='Suya',
                                  horas=['2'])
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:cambiar_plantilla', args=[reporte.pk]),
            {'plantilla': ajena.pk}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Seleccione una de sus plantillas')
        self.assertEqual(reporte.conceptos_horas.count(), 0)

    def test_agregar_y_quitar_trabajador_desde_la_pantalla(self):
        reporte = self.preparar()
        fila = self.fila(reporte)
        self.client.force_login(self.moderador)

        respuesta = self.client.post(
            reverse('prenomina:quitar_trabajador', args=[reporte.pk, fila.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        self.assertEqual(reporte.trabajadores.count(), 0)

        respuesta = self.client.post(
            reverse('prenomina:agregar_trabajador', args=[reporte.pk]),
            {'no_expediente': '00100'}, HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 204)
        self.assertEqual(reporte.trabajadores.count(), 1)

    def test_el_modal_de_agregar_solo_ofrece_a_los_que_faltan(self):
        reporte = self.preparar()
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:agregar_trabajador', args=[reporte.pk]),
            HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'ya están en el reporte')

    def test_un_reporte_cerrado_no_ofrece_acciones_de_edicion(self):
        reporte = self.preparar()
        servicios.cerrar_reporte(reporte, self.moderador)
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:detalle_reporte', args=[reporte.pk]))
        self.assertNotContains(respuesta, 'Añadir trabajador')
        self.assertContains(respuesta, 'Reabrir')


class ExportacionAExcel(BaseConConceptos):
    """El fichero tiene que parecerse al de RRHH y poder volver a importarse."""

    def libro(self, reporte):
        from io import BytesIO
        from openpyxl import load_workbook
        memoria = BytesIO()
        exportar.construir_libro(reporte).save(memoria)
        memoria.seek(0)
        return load_workbook(memoria)

    ESPERADOS = {
        'trabajador': COLOR_TRABAJADOR, 'ausencia': COLOR_AUSENCIA,
        'trabajadas': COLOR_TRABAJADAS, 'horas': COLOR_PAGO_HORAS,
        'importe': COLOR_PAGO_IMPORTE,
    }

    def _primera_columna_de_cada_grupo(self, reporte):
        primeras = {}
        for indice, columna in enumerate(exportar.construir_columnas(reporte), start=1):
            primeras.setdefault(columna['grupo'], indice)
        return primeras

    def test_los_colores_de_la_cabecera_son_los_del_excel_de_rrhh(self):
        """Se mira la fila 7, que es donde vive el color de las cinco zonas.

        En las columnas sin grupo (identidad, horas trabajadas) la fila 7 es la
        celda ancla de un `merge` vertical, y openpyxl deja el estilo en el ancla:
        la celda de la fila 8 pasa a ser `MergedCell` y pierde el suyo. Mirar la
        fila 8 daría negro y no significaría nada.
        """
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        primeras = self._primera_columna_de_cada_grupo(reporte)

        for grupo, esperado in self.ESPERADOS.items():
            with self.subTest(grupo=grupo):
                celda = hoja.cell(row=FILA_GRUPOS, column=primeras[grupo])
                self.assertEqual(celda.fill.start_color.rgb[-6:], esperado)

    def test_las_celdas_de_datos_tambien_llevan_el_color_de_su_zona(self):
        """Las filas 9 a 19 del original vienen pre-pintadas por columna."""
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        primeras = self._primera_columna_de_cada_grupo(reporte)

        for grupo, esperado in self.ESPERADOS.items():
            with self.subTest(grupo=grupo):
                celda = hoja.cell(row=PRIMERA_FILA_DATOS, column=primeras[grupo])
                self.assertEqual(celda.fill.start_color.rgb[-6:], esperado)
                self.assertEqual(celda.border.bottom.style, 'thin')

    def test_la_estructura_reproduce_la_del_excel(self):
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]

        self.assertEqual(hoja['A1'].value, 'REPORTE DE PAGO')
        self.assertIn('Horas del mes', hoja['G2'].value)
        self.assertEqual(hoja['I2'].value, reporte.fondo_tiempo)
        self.assertIn('Período de Pago', hoja['A4'].value)
        self.assertIn('Hecho por', hoja['A5'].value)
        self.assertIn('Revisado por', hoja['F5'].value)
        self.assertIn('Aprobado por', hoja['K5'].value)

    def test_los_encabezados_de_grupo_estan_en_su_sitio(self):
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        textos = [celda.value for celda in hoja[FILA_GRUPOS] if celda.value]
        for esperado in ('Descuentos en horas (ausencias)', 'Horas trabajadas',
                         'Pagos asociados por horas', 'Pagos asociados por Importe'):
            with self.subTest(esperado=esperado):
                self.assertIn(esperado, textos)

    def test_la_fila_maquina_es_biyectiva_con_los_conceptos(self):
        """Es lo que permite reimportar aunque el usuario mueva las columnas."""
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]

        claves = [celda.value for celda in hoja[FILA_MAQUINA] if celda.value]
        esperadas = [c['clave'] for c in exportar.construir_columnas(reporte)]
        self.assertEqual(claves, esperadas)
        self.assertEqual(len(claves), len(set(claves)), 'hay claves repetidas')

        # Cada concepto congelado tiene exactamente una columna.
        for concepto in reporte.conceptos_ausencia.all():
            self.assertIn(f'AUS:{concepto.codigo}', claves)
        for concepto in reporte.conceptos_horas.all():
            self.assertIn(f'HOR:{concepto.codigo}', claves)
        for concepto in reporte.conceptos_importe.all():
            self.assertIn(f'IMP:{concepto.codigo}', claves)

    def test_la_fila_maquina_va_oculta(self):
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        self.assertTrue(hoja.row_dimensions[FILA_MAQUINA].hidden)

    def test_la_columna_del_carnet_va_oculta_y_lleva_el_ci(self):
        """Detecta las filas desplazadas al reordenar mal en Excel."""
        from openpyxl.utils import get_column_letter
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        columnas = exportar.construir_columnas(reporte)

        letra = get_column_letter(len(columnas))
        self.assertTrue(hoja.column_dimensions[letra].hidden)
        self.assertEqual(hoja.cell(row=FILA_MAQUINA, column=len(columnas)).value, 'CI')
        self.assertEqual(
            hoja.cell(row=PRIMERA_FILA_DATOS, column=len(columnas)).value,
            '85010112345')

    def test_los_datos_del_trabajador_se_escriben(self):
        reporte = self.preparar()
        servicios.guardar_valores(self.fila(reporte).pk, self.moderador,
                                  ausencias={12: Decimal('16')})
        hoja = self.libro(reporte)[HOJA_REPORTE]
        columnas = exportar.construir_columnas(reporte)
        indices = {c['clave']: i for i, c in enumerate(columnas, start=1)}

        def valor(clave):
            return hoja.cell(row=PRIMERA_FILA_DATOS, column=indices[clave]).value

        self.assertEqual(valor('EXP'), '00100')
        self.assertEqual(valor('NOM'), 'Ana Pérez Gómez')
        self.assertEqual(valor('CAT'), 'TEC')
        self.assertEqual(valor('AUS:12'), Decimal('16.00'))
        self.assertEqual(valor('TOTDESC'), Decimal('16.00'))
        self.assertEqual(valor('HTRAB'), Decimal('168.00'))

    def test_la_firma_verifica_sobre_el_reporte_de_origen(self):
        reporte = self.preparar()
        libro = self.libro(reporte)
        metadatos = {fila[0].value: fila[1].value
                     for fila in libro[HOJA_METADATOS].iter_rows(min_row=1, max_col=2)}

        columnas = exportar.construir_columnas(reporte)
        self.assertTrue(exportar.firma_valida(reporte, columnas, metadatos['firma']))
        self.assertEqual(metadatos['reporte_id'], reporte.pk)
        self.assertEqual(metadatos['anno'], reporte.anno)
        self.assertEqual(metadatos['mes'], reporte.mes)

    def test_la_firma_no_verifica_si_cambian_las_columnas(self):
        """Es lo que atrapa un fichero fabricado o de otra configuración."""
        reporte = self.preparar()
        columnas = exportar.construir_columnas(reporte)
        firma = exportar.firmar(reporte, columnas)

        manipuladas = columnas[:-1]
        self.assertFalse(exportar.firma_valida(reporte, manipuladas, firma))

    def test_la_hoja_de_metadatos_esta_muy_oculta(self):
        reporte = self.preparar()
        self.assertEqual(self.libro(reporte)[HOJA_METADATOS].sheet_state,
                         'veryHidden')

    def test_la_escala_congelada_se_exporta_como_referencia(self):
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_ESCALA]
        self.assertEqual(hoja['A1'].value, 'Años')
        self.assertEqual(hoja['B1'].value, 'Cuantía')
        self.assertEqual(hoja['A2'].value, 1)
        self.assertEqual(hoja['B2'].value, 200.0)

    def test_las_columnas_calculadas_quedan_bloqueadas(self):
        """Ayuda de usabilidad: Excel avisa si se escribe en una calculada."""
        reporte = self.preparar()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        columnas = exportar.construir_columnas(reporte)
        indices = {c['clave']: i for i, c in enumerate(columnas, start=1)}

        def bloqueada(clave):
            return hoja.cell(row=PRIMERA_FILA_DATOS,
                             column=indices[clave]).protection.locked

        self.assertFalse(bloqueada('AUS:12'))     # editable
        self.assertFalse(bloqueada('HOR:2'))      # editable, no derivado
        self.assertTrue(bloqueada('HOR:5'))       # derivado
        self.assertTrue(bloqueada('HTRAB'))       # calculada
        self.assertTrue(bloqueada('IMP:5'))       # todo el grupo rojo
        self.assertTrue(hoja.protection.sheet)

    def test_la_descarga_lleva_el_content_type_que_detecta_progreso(self):
        """`DeteccionExportacionMiddleware` la marca sin cablear nada."""
        reporte = self.preparar()
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:exportar_reporte', args=[reporte.pk]))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], exportar.TIPO_XLSX)
        self.assertIn('attachment; filename=', respuesta['Content-Disposition'])
        self.assertIn('.xlsx', respuesta['Content-Disposition'])

    def test_el_observador_no_puede_exportar(self):
        """El Observador no tiene acceso al módulo: ni de lectura."""
        reporte = self.preparar()
        self.client.force_login(self.observador)
        respuesta = self.client.get(
            reverse('prenomina:exportar_reporte', args=[reporte.pk]))
        self.assertEqual(respuesta.status_code, 403)

    def test_un_moderador_ajeno_no_exporta(self):
        reporte = self.preparar()
        self.client.force_login(self.ajeno)
        respuesta = self.client.get(
            reverse('prenomina:exportar_reporte', args=[reporte.pk]))
        self.assertEqual(respuesta.status_code, 404)

    def test_un_reporte_sin_conceptos_se_exporta_igual(self):
        """El esqueleto existe siempre, aunque no haya ni un concepto elegido."""
        reporte = self.crear()
        hoja = self.libro(reporte)[HOJA_REPORTE]
        claves = [celda.value for celda in hoja[FILA_MAQUINA] if celda.value]
        self.assertEqual(claves, ['EXP', 'NOM', 'CAT', 'SAL', 'HTRAB', 'CI'])


class ImportacionDesdeExcel(BaseConConceptos):
    """El fichero exportado tiene que poder volver, y fallar entero si algo no cuadra."""

    def exportar_a_memoria(self, reporte):
        from io import BytesIO
        memoria = BytesIO()
        exportar.construir_libro(reporte).save(memoria)
        memoria.seek(0)
        return memoria

    def como_subida(self, memoria, nombre='reporte.xlsx'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(nombre, memoria.getvalue(),
                                  content_type=exportar.TIPO_XLSX)

    def mutar(self, reporte, cambios, *, hoja_nombre=None):
        """Exporta, cambia las celdas indicadas y devuelve el fichero subible.

        `cambios` es `{clave_de_columna: valor}` para la primera fila de datos.
        """
        from io import BytesIO
        from openpyxl import load_workbook

        libro = load_workbook(self.exportar_a_memoria(reporte))
        hoja = libro[hoja_nombre or HOJA_REPORTE]
        mapa = {c.value: c.column for c in hoja[FILA_MAQUINA] if c.value}
        for clave, valor in cambios.items():
            hoja.cell(row=PRIMERA_FILA_DATOS, column=mapa[clave], value=valor)

        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        return salida

    def analizar(self, archivo, reporte=None, usuario=None):
        return importar.analizar(self.como_subida(archivo),
                                 reporte or self.reporte, usuario or self.moderador)

    def setUp(self):
        super().setUp()
        self.reporte = self.preparar()

    # --- Ida y vuelta ------------------------------------------------------

    def test_el_fichero_exportado_vuelve_sin_cambios(self):
        """Exportar e importar sin tocar nada deja el reporte igual."""
        antes = self.fila(self.reporte).horas_trabajadas
        resultado = self.analizar(self.exportar_a_memoria(self.reporte))

        self.assertTrue(resultado.valido, resultado.errores)
        servicios.importar_valores(self.reporte, resultado.filas, self.moderador)
        self.assertEqual(self.fila(self.reporte).horas_trabajadas, antes)

    def test_ida_y_vuelta_cambiando_dos_celdas(self):
        """Cambian exactamente esas dos, y los importes se recalculan."""
        archivo = self.mutar(self.reporte, {'AUS:12': 16, 'HOR:2': 10})
        resultado = self.analizar(archivo)
        self.assertTrue(resultado.valido, resultado.errores)

        servicios.importar_valores(self.reporte, resultado.filas, self.moderador)
        fila = self.fila(self.reporte)

        self.assertEqual(fila.valores_ausencia.get(concepto__codigo=12).horas,
                         Decimal('16.00'))
        self.assertEqual(fila.valores_horas.get(concepto__codigo=2).horas,
                         Decimal('10.00'))
        self.assertEqual(fila.horas_trabajadas, Decimal('168.00'))
        # El importe por fórmula se recalculó a partir de las horas importadas.
        esperado = calculos.redondear(
            Decimal('10') * fila.tarifa_horaria * Decimal('1.25'))
        self.assertEqual(fila.valores_importe.get(concepto__codigo=3).importe,
                         esperado)

    def test_reordenar_las_columnas_no_rompe_la_importacion(self):
        """Es la edición externa benigna más probable."""
        from io import BytesIO
        from openpyxl import load_workbook

        libro = load_workbook(self.exportar_a_memoria(self.reporte))
        hoja = libro[HOJA_REPORTE]
        mapa = {c.value: c.column for c in hoja[FILA_MAQUINA] if c.value}

        # Se intercambian dos columnas de ausencia enteras (clave y valor).
        a, b = mapa['AUS:12'], mapa['AUS:19']
        for numero in (FILA_MAQUINA, PRIMERA_FILA_DATOS):
            va = hoja.cell(row=numero, column=a).value
            vb = hoja.cell(row=numero, column=b).value
            hoja.cell(row=numero, column=a, value=vb)
            hoja.cell(row=numero, column=b, value=va)
        hoja.cell(row=PRIMERA_FILA_DATOS, column=b, value=8)

        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)

        resultado = self.analizar(salida)
        self.assertTrue(resultado.valido, resultado.errores)
        servicios.importar_valores(self.reporte, resultado.filas, self.moderador)
        # El 8 fue a parar a la clave 12, que es donde estaba la columna movida.
        self.assertEqual(
            self.fila(self.reporte).valores_ausencia.get(concepto__codigo=12).horas,
            Decimal('8.00'))

    # --- Clases de error, todas sin escribir nada --------------------------

    def _sin_escrituras(self, archivo, fragmento, **kwargs):
        antes = list(self.fila(self.reporte).valores_ausencia
                     .order_by('concepto__codigo').values_list('horas', flat=True))
        resultado = self.analizar(archivo, **kwargs)

        self.assertFalse(resultado.valido)
        self.assertTrue(any(fragmento.lower() in e.lower() for e in resultado.errores),
                        f'ningún error menciona «{fragmento}»: {resultado.errores}')
        despues = list(self.fila(self.reporte).valores_ausencia
                       .order_by('concepto__codigo').values_list('horas', flat=True))
        self.assertEqual(antes, despues, 'se escribió algo pese al error')
        return resultado

    def test_un_archivo_de_otro_reporte_se_rechaza(self):
        otro = self.crear(unidad=self.otra_unidad, usuario=self.ajeno)
        self._sin_escrituras(self.exportar_a_memoria(otro), 'otro reporte')

    def test_un_archivo_sin_hoja_de_control_se_rechaza(self):
        from io import BytesIO
        from openpyxl import load_workbook
        libro = load_workbook(self.exportar_a_memoria(self.reporte))
        del libro[HOJA_METADATOS]
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        self._sin_escrituras(salida, 'no procede de Orbith')

    def test_una_firma_manipulada_se_rechaza(self):
        from io import BytesIO
        from openpyxl import load_workbook
        libro = load_workbook(self.exportar_a_memoria(self.reporte))
        hoja = libro[HOJA_METADATOS]
        for fila in hoja.iter_rows(min_row=1, max_col=2):
            if fila[0].value == 'firma':
                fila[1].value = 'a' * 64
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        self._sin_escrituras(salida, 'estructura del archivo')

    def test_un_expediente_desconocido_se_rechaza(self):
        self._sin_escrituras(self.mutar(self.reporte, {'EXP': '99999'}),
                             'no pertenece a este reporte')

    def test_un_carnet_discordante_se_rechaza(self):
        """Atrapa las filas desplazadas al ordenar mal en Excel."""
        self._sin_escrituras(self.mutar(self.reporte, {'CI': '11111111111'}),
                             'reordenadas')

    def test_un_texto_donde_va_un_numero_se_rechaza(self):
        self._sin_escrituras(self.mutar(self.reporte, {'AUS:12': 'ocho'}),
                             'no es un número válido')

    def test_un_valor_negativo_se_rechaza(self):
        self._sin_escrituras(self.mutar(self.reporte, {'AUS:12': -5}),
                             'no pueden ser negativas')

    def test_pasarse_del_fondo_del_mes_se_rechaza(self):
        self._sin_escrituras(self.mutar(self.reporte, {'AUS:12': 500}),
                             'superan las horas del mes')

    def test_editar_una_columna_calculada_se_rechaza(self):
        """En pantalla va bloqueada; en Excel el error es la única defensa."""
        self._sin_escrituras(self.mutar(self.reporte, {'HOR:5': 99}),
                             'columna calculada')

    def test_un_trabajador_ausente_del_archivo_se_rechaza(self):
        """Perder filas por accidente sin que nadie se entere es peor."""
        from io import BytesIO
        from openpyxl import load_workbook
        servicios.agregar_trabajador  # noqa: B018  (documenta la dependencia)

        libro = load_workbook(self.exportar_a_memoria(self.reporte))
        hoja = libro[HOJA_REPORTE]
        hoja.delete_rows(PRIMERA_FILA_DATOS)
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        self._sin_escrituras(salida, 'Faltan')

    def test_un_expediente_duplicado_se_rechaza(self):
        from io import BytesIO
        from openpyxl import load_workbook
        libro = load_workbook(self.exportar_a_memoria(self.reporte))
        hoja = libro[HOJA_REPORTE]
        mapa = {c.value: c.column for c in hoja[FILA_MAQUINA] if c.value}
        for clave in ('EXP', 'CI'):
            hoja.cell(row=PRIMERA_FILA_DATOS + 1, column=mapa[clave],
                      value=hoja.cell(row=PRIMERA_FILA_DATOS,
                                      column=mapa[clave]).value)
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        self._sin_escrituras(salida, 'aparece dos veces')

    def test_un_reporte_cerrado_no_admite_importacion(self):
        servicios.cerrar_reporte(self.reporte, self.moderador)
        self.reporte.refresh_from_db()
        resultado = self.analizar(self.exportar_a_memoria(self.reporte))
        self.assertFalse(resultado.valido)
        self.assertTrue(any('Cerrado' in e for e in resultado.errores))

    def test_un_observador_no_puede_importar(self):
        resultado = self.analizar(self.exportar_a_memoria(self.reporte),
                                  usuario=self.observador)
        self.assertFalse(resultado.valido)
        self.assertTrue(any('permiso' in e for e in resultado.errores))

    def test_un_moderador_ajeno_no_puede_importar(self):
        resultado = self.analizar(self.exportar_a_memoria(self.reporte),
                                  usuario=self.ajeno)
        self.assertFalse(resultado.valido)

    def test_un_archivo_que_no_es_excel_se_rechaza(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        basura = SimpleUploadedFile('reporte.xlsx', b'esto no es un excel',
                                    content_type=exportar.TIPO_XLSX)
        resultado = importar.analizar(basura, self.reporte, self.moderador)
        self.assertFalse(resultado.valido)

    def test_una_extension_incorrecta_se_rechaza(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        archivo = SimpleUploadedFile(
            'reporte.csv', self.exportar_a_memoria(self.reporte).getvalue())
        resultado = importar.analizar(archivo, self.reporte, self.moderador)
        self.assertFalse(resultado.valido)
        self.assertTrue(any('.xlsx' in e for e in resultado.errores))

    # --- La pantalla -------------------------------------------------------

    def test_el_modal_avisa_antes_de_pedir_el_archivo(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('prenomina:importar_reporte', args=[self.reporte.pk]),
            HTTP_HX_REQUEST='true')
        self.assertContains(respuesta, 'no se puede deshacer')
        self.assertContains(respuesta, 'He leído la advertencia')

    def test_la_importacion_desde_la_pantalla_aplica_los_cambios(self):
        self.client.force_login(self.moderador)
        archivo = self.mutar(self.reporte, {'AUS:12': 16})
        respuesta = self.client.post(
            reverse('prenomina:importar_reporte', args=[self.reporte.pk]),
            {'archivo': self.como_subida(archivo)}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 204)
        self.assertIn('recargarReporte', respuesta['HX-Trigger'])
        self.assertEqual(self.fila(self.reporte).horas_trabajadas, Decimal('168.00'))

    def test_un_archivo_con_errores_devuelve_el_modal_con_la_lista(self):
        self.client.force_login(self.moderador)
        archivo = self.mutar(self.reporte, {'AUS:12': -5})
        respuesta = self.client.post(
            reverse('prenomina:importar_reporte', args=[self.reporte.pk]),
            {'archivo': self.como_subida(archivo)}, HTTP_HX_REQUEST='true')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No se importó nada')
        self.assertContains(respuesta, 'negativas')

    def test_el_observador_no_abre_el_modal_de_importacion(self):
        self.client.force_login(self.observador)
        respuesta = self.client.get(
            reverse('prenomina:importar_reporte', args=[self.reporte.pk]),
            HTTP_HX_REQUEST='true')
        self.assertEqual(respuesta.status_code, 403)
