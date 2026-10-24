import json

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from usuarios.models import CustomUser

from .models import InformeFavorito, InformePersonalizado


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar un InformePersonalizado desde el Admin de Django ahora
    deja rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests`
    para el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='admin_informe_inteligente', password='x', es_admin=True)

    def test_eliminar_un_informe_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        informe = InformePersonalizado.objects.create(
            nombre='Informe de prueba', modelo_raiz='CAlta', configuracion={})
        self.client.force_login(self.admin)

        url = reverse('admin:informe_inteligente_informepersonalizado_delete', args=[informe.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(InformePersonalizado.objects.filter(pk=informe.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(informe.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'informe_inteligente')

    def test_editar_un_informe_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from informe_inteligente.admin import InformePersonalizadoAdmin

        informe = InformePersonalizado.objects.create(
            nombre='Informe de prueba', modelo_raiz='CAlta', configuracion={})

        admin_instance = InformePersonalizadoAdmin(InformePersonalizado, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        informe.nombre = 'Informe renombrado'
        admin_instance.save_model(request, informe, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(informe.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)


class EditarFavoritoTests(TestCase):
    """Editar un informe guardado, en vez de tener que volver a guardarlo.

    Antes solo existía `guardar_favorito`, que siempre hace `create()`: renombrar
    un favorito dejaba dos copias del mismo informe. Lo que estas pruebas fijan es
    que renombrar y reemplazar la configuración son dos acciones independientes,
    porque lo que hay en pantalla puede pertenecer a otro informe distinto del que
    se está editando.
    """

    CONFIG_ORIGINAL = {'campos': ['nombre_completo', 'doc_identidad'], 'filtros': []}

    @classmethod
    def setUpTestData(cls):
        cls.duenno = CustomUser.objects.create_user(
            username='duenno_favorito', password='x', es_admin=True)
        cls.otro = CustomUser.objects.create_user(
            username='otro_usuario_favorito', password='x', es_admin=True)

    def setUp(self):
        self.informe = InformePersonalizado.objects.create(
            nombre='Nombre original', descripcion='Descripción original',
            modelo_raiz='CAlta', configuracion=dict(self.CONFIG_ORIGINAL),
            usuario=self.duenno)
        InformeFavorito.objects.create(usuario=self.duenno, informe=self.informe)
        self.url = reverse('informe_inteligente:editar_favorito', args=[self.informe.pk])
        self.client.force_login(self.duenno)

    def test_renombrar_no_toca_la_configuracion_guardada(self):
        respuesta = self.client.post(self.url, {
            'nombre': 'Nombre nuevo',
            'descripcion': 'Descripción nueva',
            # Se envía una configuración distinta a propósito, SIN pedir el
            # reemplazo: el servidor debe ignorarla.
            'modelo_raiz': 'Aspirante',
            'configuracion': json.dumps({'campos': ['sexo'], 'filtros': []}),
        })

        self.assertEqual(respuesta.status_code, 200)
        self.informe.refresh_from_db()
        self.assertEqual(self.informe.nombre, 'Nombre nuevo')
        self.assertEqual(self.informe.descripcion, 'Descripción nueva')
        self.assertEqual(self.informe.configuracion, self.CONFIG_ORIGINAL)
        self.assertEqual(self.informe.modelo_raiz, 'CAlta')

    def test_reemplazar_configuracion_actualiza_tambien_el_modelo_raiz(self):
        respuesta = self.client.post(self.url, {
            'nombre': 'Nombre original',
            'descripcion': '',
            'reemplazar_configuracion': 'true',
            'modelo_raiz': 'Aspirante',
            'configuracion': json.dumps({'campos': ['sexo'], 'filtros': []}),
        })

        self.assertEqual(respuesta.status_code, 200)
        self.informe.refresh_from_db()
        self.assertEqual(self.informe.configuracion, {'campos': ['sexo'], 'filtros': []})
        # El modelo raíz viaja con la configuración: dejarlo en 'CAlta' con
        # campos de Aspirante rompería el informe al ejecutarlo.
        self.assertEqual(self.informe.modelo_raiz, 'Aspirante')
        self.assertIsNone(self.informe.descripcion)

    def test_editar_no_crea_un_informe_nuevo(self):
        self.client.post(self.url, {'nombre': 'Renombrado', 'descripcion': ''})

        self.assertEqual(InformePersonalizado.objects.filter(usuario=self.duenno).count(), 1)
        self.assertEqual(InformeFavorito.objects.filter(usuario=self.duenno).count(), 1)

    def test_no_se_puede_editar_el_informe_de_otro_usuario(self):
        self.client.force_login(self.otro)

        respuesta = self.client.post(self.url, {'nombre': 'Secuestrado', 'descripcion': ''})

        self.assertEqual(respuesta.status_code, 404)
        self.informe.refresh_from_db()
        self.assertEqual(self.informe.nombre, 'Nombre original')

    def test_nombre_vacio_se_rechaza_sin_tocar_el_informe(self):
        respuesta = self.client.post(self.url, {'nombre': '   ', 'descripcion': ''})

        self.assertEqual(respuesta.status_code, 400)
        self.informe.refresh_from_db()
        self.assertEqual(self.informe.nombre, 'Nombre original')

    def test_compartir_no_toca_los_favoritos_del_receptor(self):
        """Compartir manda un aviso, no añade nada a la lista del que recibe."""
        from notificaciones.models import Notificacion

        url = reverse('informe_inteligente:compartir_favorito', args=[self.informe.pk])
        respuesta = self.client.post(url, {'destinatarios': [self.otro.pk]})

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['enviados'], 1)
        # Lo único que recibe es la notificación.
        self.assertEqual(
            InformeFavorito.objects.filter(usuario=self.otro).count(), 0)
        self.assertEqual(
            InformePersonalizado.objects.filter(usuario=self.otro).count(), 0)
        aviso = Notificacion.objects.get(destinatario=self.otro)
        self.assertEqual(aviso.object_id, str(self.informe.pk))
        self.assertEqual(aviso.tipo, Notificacion.Tipo.EVENTO)

    def test_no_se_puede_compartir_un_informe_ajeno(self):
        self.client.force_login(self.otro)

        url = reverse('informe_inteligente:compartir_favorito', args=[self.informe.pk])
        respuesta = self.client.post(url, {'destinatarios': [self.duenno.pk]})

        self.assertEqual(respuesta.status_code, 404)

    def test_ver_compartido_exige_una_notificacion_dirigida_al_usuario(self):
        """La notificación ES el permiso: sin ella, el informe no se abre."""
        url = reverse('informe_inteligente:ver_compartido', args=[self.informe.pk])

        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(url).status_code, 404)

        # Se lo comparten y ahora sí puede abrirlo.
        self.client.force_login(self.duenno)
        self.client.post(
            reverse('informe_inteligente:compartir_favorito', args=[self.informe.pk]),
            {'destinatarios': [self.otro.pk]})

        self.client.force_login(self.otro)
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['informe_compartido'].pk, self.informe.pk)

    def test_el_duenno_siempre_puede_abrir_su_propio_informe(self):
        url = reverse('informe_inteligente:ver_compartido', args=[self.informe.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_compartir_consigo_mismo_no_genera_aviso(self):
        from notificaciones.models import Notificacion

        url = reverse('informe_inteligente:compartir_favorito', args=[self.informe.pk])
        respuesta = self.client.post(url, {'destinatarios': [self.duenno.pk]})

        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(Notificacion.objects.exists())

    def test_el_boton_ver_informe_de_la_notificacion_apunta_al_informe(self):
        """El enlace de la notificación se construye desde el diccionario central
        de `subsanacion.enlaces`; sin su entrada, el aviso llegaría sin botón."""
        from subsanacion.enlaces import construir_enlace

        enlace = construir_enlace(
            'informe_inteligente.InformePersonalizado', self.informe.pk)

        self.assertIsNotNone(enlace)
        self.assertEqual(enlace['etiqueta'], 'Ver informe')
        self.assertIn(str(self.informe.pk), enlace['href'])

    def test_reemplazar_con_configuracion_sin_campos_se_rechaza(self):
        respuesta = self.client.post(self.url, {
            'nombre': 'Nombre original',
            'descripcion': '',
            'reemplazar_configuracion': 'true',
            'modelo_raiz': 'CAlta',
            'configuracion': json.dumps({'campos': [], 'filtros': []}),
        })

        self.assertEqual(respuesta.status_code, 400)
        self.informe.refresh_from_db()
        self.assertEqual(self.informe.configuracion, self.CONFIG_ORIGINAL)


class FiltroJerarquicoPorUnidadTests(TestCase):
    """Elegir una Unidad Principal SUMA sus subunidades, pero NO colapsa la vista.

    Las dos mitades son igual de importantes:

    * Filtrar por una Dirección Principal debe traer a sus hijas. Antes el filtro
      comparaba la descripción con un `=` exacto, y como una principal no tiene
      cargos propios —todo cuelga de sus hijas—, el informe salía VACÍO.
    * Pero cada fila debe seguir mostrando SU unidad. Por eso la expansión se
      aplica solo al construir el filtro y no con `grupos_valores`, el mecanismo
      vecino, que sí colapsa la etiqueta: con aquel, un trabajador del Taller
      aparecería en la tabla y en el desglose como «Dirección Técnica».
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from bolsa.models import Aspirante
        from contratos.models import CAlta
        from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio,
                                          NProvincia, NTipoContrato,
                                          NTipoUnidadOrganizativa)
        from strorganizativa.models import (CargoPlantilla, Departamento,
                                            UnidadOrganizativa)

        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección', es_principal=True)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True)

        cls.principal = UnidadOrganizativa.objects.create(
            descripcion='Dirección Técnica', tipo=tipo_principal, grupo_nomina=1,
            orden_informe=1)
        cls.taller = UnidadOrganizativa.objects.create(
            descripcion='Taller', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=2)
        cls.almacen = UnidadOrganizativa.objects.create(
            descripcion='Almacén', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=3)

        grupo = NGrupoEscala.objects.create(nivel='V')
        ncargo = NCargo.objects.create(
            descripcion='Mecánico', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=3000)
        provincia = NProvincia.objects.create(nombre='Camagüey', siglas='CMG')
        municipio = NMunicipio.objects.create(
            nombre='Centro', provincia=provincia, siglas='CEN')
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True)

        # Dos trabajadores en el Taller y uno en el Almacén. La principal, ninguno.
        documento = 90010100000
        for unidad, cuantos in ((cls.taller, 2), (cls.almacen, 1)):
            departamento = Departamento.objects.create(
                descripcion='Dpto ' + unidad.descripcion,
                unidad_organizativa=unidad, orden_informe=1)
            cargo = CargoPlantilla.objects.create(
                ncargo=ncargo, departamento=departamento, cant_aprobada=10,
                orden_informe=1)
            for _ in range(cuantos):
                documento += 1
                aspirante = Aspirante.objects.create(
                    nivel_educ='SA', nombre='Trab', papellido='Prueba',
                    sapellido='Test', doc_identidad=str(documento),
                    estado='ACTIVO', sexo='M', raza='BL',
                    provincia=provincia, municipio=municipio)
                CAlta.objects.create(
                    aspirante=aspirante, no_expediente=str(documento)[-5:],
                    tipo=tipo_contrato, cargo=cargo, fecha_alta=date(2026, 1, 15))

        cls.admin = CustomUser.objects.create_user(
            username='admin_ii_jerarquia', password='x', es_admin=True)

    def contar(self, valor, operador='igual'):
        from informe_inteligente import motor

        configuracion = {'filtros': [{'campo': 'unidad_organizativa',
                                      'operador': operador, 'valor': valor}]}
        return motor.construir_queryset('CAlta', configuracion, self.admin).count()

    def test_la_principal_trae_a_sus_subunidades(self):
        """Antes daba 0: la principal no tiene cargos propios."""
        self.assertEqual(self.contar('Dirección Técnica'), 3)

    def test_cada_subunidad_se_puede_aislar(self):
        self.assertEqual(self.contar('Taller'), 2)
        self.assertEqual(self.contar('Almacén'), 1)

    def test_es_alguno_de_suma_las_expansiones(self):
        self.assertEqual(self.contar(['Taller', 'Almacén'], 'en_lista'), 3)

    def test_el_operador_negativo_excluye_toda_la_rama(self):
        self.assertEqual(self.contar('Dirección Técnica', 'diferente'), 0)

    def test_la_expansion_no_colapsa_lo_que_se_muestra(self):
        """El punto que decide el diseño: filtrar por la principal trae las tres
        filas, pero cada una conserva el nombre de SU unidad."""
        from collections import Counter

        from informe_inteligente import motor

        configuracion = {'filtros': [{'campo': 'unidad_organizativa',
                                      'operador': 'igual',
                                      'valor': 'Dirección Técnica'}]}
        queryset = motor.construir_queryset('CAlta', configuracion, self.admin)
        vistas = Counter(queryset.values_list(
            'cargo__departamento__unidad_organizativa__descripcion', flat=True))

        self.assertEqual(dict(vistas), {'Taller': 2, 'Almacén': 1})

    def test_el_desplegable_sigue_ofreciendo_todas_las_unidades(self):
        from informe_inteligente.metadata import REGISTRO_MODELOS, opciones_visibles

        campo = REGISTRO_MODELOS['CAlta']['campos']['unidad_organizativa']
        valores = {valor for valor, _ in opciones_visibles(campo)}

        self.assertLessEqual(
            {'Dirección Técnica', 'Taller', 'Almacén'}, valores)

    def test_una_unidad_sin_hijas_se_expande_a_si_misma(self):
        from informe_inteligente.metadata import _expansion_jerarquica_unidades

        # Admite una etiqueta suelta y también la lista entera: el motor le pasa
        # todas las unidades marcadas de una vez, para resolverlo en una consulta.
        self.assertEqual(_expansion_jerarquica_unidades('Taller'), ['Taller'])
        self.assertEqual(
            _expansion_jerarquica_unidades('Dirección Técnica'),
            ['Almacén', 'Dirección Técnica', 'Taller'])
        self.assertEqual(
            _expansion_jerarquica_unidades(['Dirección Técnica', 'Taller']),
            ['Almacén', 'Dirección Técnica', 'Taller'])

    def test_la_expansion_se_resuelve_en_una_sola_consulta(self):
        """Con varias unidades marcadas, una consulta por etiqueta serían varios
        viajes a la base de datos para construir un único filtro."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        from informe_inteligente.metadata import _expansion_jerarquica_unidades

        with CaptureQueriesContext(connection) as consultas:
            _expansion_jerarquica_unidades(
                ['Dirección Técnica', 'Taller', 'Almacén'])

        self.assertEqual(len(consultas), 1)


class IndicadoresYEvolucionTests(TestCase):
    """Las medidas del panel de resumen y de la línea de Evolución mensual.

    El desplegable «Medir» sale de `INDICADORES_POR_MODELO`, así que ambas
    cosas se prueban juntas: si una medida aparece en la lista tiene que poder
    calcularse, y al revés.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from bolsa.models import Aspirante
        from contratos.models import CAlta
        from nomencladores.models import (NCargo, NGrupoEscala, NMunicipio,
                                          NProvincia, NTipoContrato,
                                          NTipoUnidadOrganizativa)
        from strorganizativa.models import (CargoPlantilla, Departamento,
                                            UnidadOrganizativa)

        tipo_ueb = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')
        cls.unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Centro', tipo=tipo_ueb, grupo_nomina=1, orden_informe=1)
        departamento = Departamento.objects.create(
            descripcion='Produccion', unidad_organizativa=cls.unidad, orden_informe=1)

        grupo = NGrupoEscala.objects.create(nivel='V')
        # Un cargo marcado como Puesto Clave y otro que no: es lo que separa el
        # indicador nuevo de un simple total.
        cls.ncargo_clave = NCargo.objects.create(
            descripcion='Jefe de Brigada', cat_ocupacional='CDI',
            grupo_escala=grupo, salario_basico=6000, puesto_clave=True)
        cls.ncargo_normal = NCargo.objects.create(
            descripcion='Operario', cat_ocupacional='OPE',
            grupo_escala=grupo, salario_basico=3000)

        cls.plantilla_clave = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_clave, departamento=departamento,
            cant_aprobada=4, cant_cubierta=1, orden_informe=1)
        cls.plantilla_normal = CargoPlantilla.objects.create(
            ncargo=cls.ncargo_normal, departamento=departamento,
            cant_aprobada=10, cant_cubierta=6, orden_informe=2)

        provincia = NProvincia.objects.create(nombre='Camaguey', siglas='CMG')
        municipio = NMunicipio.objects.create(
            nombre='Centro', provincia=provincia, siglas='CEN')
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=True)

        def contrato(seq, plantilla, sexo, mision=False):
            aspirante = Aspirante.objects.create(
                nivel_educ='SA', nombre='Trab%d' % seq, papellido='Prueba',
                sapellido='Test', doc_identidad='%011d' % (90010100000 + seq),
                estado='ACTIVO', sexo=sexo, raza='BL',
                provincia=provincia, municipio=municipio)
            return CAlta.objects.create(
                aspirante=aspirante, no_expediente='%05d' % seq,
                tipo=tipo_contrato, cargo=plantilla, mision=mision,
                fecha_alta=date(2020, 1, 15),
                fecha_alta_entidad=date(2020, 1, 15))

        # 1 en puesto clave (mujer), 2 normales (una de ellas en mision).
        cls.en_puesto_clave = contrato(1, cls.plantilla_clave, 'F')
        cls.en_mision = contrato(2, cls.plantilla_normal, 'M', mision=True)
        contrato(3, cls.plantilla_normal, 'M')

        cls.admin = CustomUser.objects.create_user(
            username='admin_ii_indicadores', password='x', es_admin=True)

    def _indicadores(self, modelo_raiz='CAlta', keys=None):
        """Las tarjetas calculadas. Por omisión, TODAS las del modelo.

        Estas pruebas comprueban la aritmética de cada tarjeta, no cuáles se
        muestran: eso lo elige el usuario y se prueba aparte. Por eso se piden
        todas explícitamente en vez de confiar en un valor por defecto.
        """
        from informe_inteligente import motor
        from informe_inteligente.metadata import INDICADORES_POR_MODELO

        if keys is None:
            keys = [spec['key'] for spec in INDICADORES_POR_MODELO[modelo_raiz]]

        queryset, definicion = motor._construir_queryset_filtrado(
            modelo_raiz, {'filtros': []}, self.admin)
        tarjetas, total = motor.calcular_indicadores(
            queryset, definicion, modelo_raiz, keys)
        return {t['label']: t for t in tarjetas}, total

    def test_sin_tarjetas_pedidas_no_se_calcula_ninguna(self):
        """El resumen aparece cuando se pide, igual que el desglose.

        Antes se pintaban las dieciséis siempre y no había forma de quitarlas.
        """
        tarjetas, total = self._indicadores(keys=[])
        self.assertEqual(tarjetas, {})
        # El total sigue viniendo: lo necesitan la paginación, los porcentajes
        # del desglose y el aviso de tamaño al exportar.
        self.assertEqual(total, 3)

    def test_solo_se_calculan_las_tarjetas_pedidas(self):
        tarjetas, _ = self._indicadores(keys=['mujeres'])
        self.assertEqual(list(tarjetas), ['Mujeres'])

    # --- Tarjetas del resumen -------------------------------------------

    def test_mujeres_muestra_el_numero_entero_ademas_del_porcentaje(self):
        """El porcentaje sale de una cantidad; las dos tienen que verse."""
        tarjetas, total = self._indicadores()
        self.assertEqual(total, 3)
        self.assertEqual(tarjetas['Mujeres']['valor'], '1')
        self.assertEqual(tarjetas['Mujeres']['porcentaje'], 33.3)

    def test_cuenta_los_trabajadores_en_puestos_clave(self):
        tarjetas, _ = self._indicadores()
        self.assertEqual(tarjetas['En puestos clave']['valor'], '1')

    def test_cuenta_los_trabajadores_en_mision(self):
        tarjetas, _ = self._indicadores()
        self.assertEqual(tarjetas['En misión internacional']['valor'], '1')

    def test_calcula_la_antiguedad_promedio_sin_pedir_esa_columna(self):
        """La antigüedad no tiene columna propia: se calcula. El indicador se
        muestra siempre, elija o no el usuario ese campo en el informe, así que
        no puede depender de la anotación."""
        tarjetas, _ = self._indicadores()
        self.assertIn('Antigüedad promedio', tarjetas)
        self.assertNotEqual(tarjetas['Antigüedad promedio']['valor'], '—')

    def test_plazas_vacantes_es_la_resta_de_aprobadas_menos_cubiertas(self):
        """`cant_cubierta` no es un dato que se escriba a mano: lo lleva el
        propio modelo a partir de los contratos vivos. Aqui hay 3 contratos
        (1 en el cargo clave y 2 en el normal) sobre 14 plazas aprobadas."""
        tarjetas, _ = self._indicadores('CargoPlantilla')
        self.assertEqual(tarjetas['Plazas aprobadas']['valor'], '14')
        self.assertEqual(tarjetas['Plazas cubiertas']['valor'], '3')
        self.assertEqual(tarjetas['Plazas vacantes']['valor'], '11')

    # --- Desplegable de la evolución ------------------------------------

    def test_el_desplegable_de_medidas_incluye_las_de_porcentaje(self):
        """«Mujeres» quedaba fuera por llevar porcentaje en su tarjeta, y lo que
        se dibuja es su cantidad, que es perfectamente graficable."""
        from informe_inteligente import motor

        etiquetas = [etiqueta for _, etiqueta in motor.indicadores_graficables('CAlta')]
        self.assertIn('Mujeres', etiquetas)
        self.assertIn('En puestos clave', etiquetas)
        self.assertIn('Antigüedad promedio', etiquetas)

    def test_solo_las_fuentes_con_fotografia_tienen_evolucion(self):
        from informe_inteligente import motor

        self.assertEqual(motor.indicadores_graficables('CBaja'), [])
        self.assertTrue(motor.indicadores_graficables('CargoPlantilla'))

    def test_vacantes_tambien_se_puede_pedir_como_columna(self):
        """El campo derivado tiene que funcionar en el listado, no solo como
        indicador: ahí sí se resuelve por anotación."""
        from informe_inteligente import motor

        queryset = motor.construir_queryset(
            'CargoPlantilla', {'campos': ['cargo', 'vacantes'], 'filtros': []},
            self.admin)
        # Cargo clave: 4 aprobadas - 1 contrato = 3. Cargo normal: 10 - 2 = 8.
        vacantes = sorted(queryset.values_list('vacantes', flat=True))
        self.assertEqual(vacantes, [3, 8])

    def test_conteos_de_contratos_por_cargo(self):
        """«Datos del Contrato» de Estructura y Plantilla Aprobada (24-10-2026):
        conteos por cargo, sin repetir el cargo una vez por contrato."""
        from informe_inteligente import motor

        queryset = motor.construir_queryset(
            'CargoPlantilla', {'campos': ['cargo', 'contratos_activos', 'contratos_ocupan_plaza',
                                          'contratos_no_ocupan_plaza'], 'filtros': []},
            self.admin)
        filas = sorted(queryset.values_list('contratos_activos', 'contratos_ocupan_plaza',
                                            'contratos_no_ocupan_plaza'))
        # Un cargo con 1 contrato y otro con 2: cada cargo es UNA fila.
        self.assertEqual([f[0] for f in filas], [1, 2])
        self.assertTrue(all(f[0] == f[1] + f[2] for f in filas))

        con_dos = motor.construir_queryset(
            'CargoPlantilla', {'campos': ['cargo'], 'filtros': [
                {'campo': 'contratos_activos', 'operador': 'mayor', 'valor': '1'}]}, self.admin)
        self.assertEqual(con_dos.count(), 1)

    # --- Condiciones por lista, cruzadas y razones ------------------------

    def test_una_condicion_por_lista_agrupa_varios_codigos(self):
        """«Cuadros» son dos categorías distintas —Directivo y Ejecutivo— y una
        sola idea. Sin condiciones por lista harían falta dos indicadores."""
        tarjetas, _ = self._indicadores()
        self.assertEqual(tarjetas['Cuadros']['valor'], '1')

    def test_un_indicador_puede_cruzar_dos_condiciones(self):
        """La única mujer del juego de datos ocupa el cargo de puesto clave."""
        tarjetas, _ = self._indicadores()
        self.assertEqual(tarjetas['Mujeres en puestos clave']['valor'], '1')

    def test_la_cobertura_es_el_porcentaje_de_plazas_ocupadas(self):
        """3 contratos sobre 14 plazas aprobadas."""
        tarjetas, _ = self._indicadores('CargoPlantilla')
        self.assertEqual(tarjetas['Cobertura de la plantilla']['valor'], '21,4 %')

    def test_la_cobertura_sin_plazas_aprobadas_no_es_cero(self):
        """Una plantilla sin plazas no tiene un 0 % de cobertura: no tiene
        cobertura ninguna. Un cero rotundo diría algo que no es."""
        from informe_inteligente.motor import _razon

        self.assertIsNone(_razon(0, 0))
        self.assertIsNone(_razon(5, None))
        self.assertEqual(_razon(1, 4), 25.0)

    def test_cuenta_los_cargos_que_nadie_ocupa(self):
        from strorganizativa.models import CargoPlantilla, Departamento
        from nomencladores.models import NCargo, NGrupoEscala

        departamento = Departamento.objects.get(descripcion='Produccion')
        # NCargo propio: 'Operario' ya está en este departamento y un cargo no
        # puede repetirse del mismo lado de la plantilla. Al test le da igual
        # cuál sea: lo que cuenta es que nadie lo ocupe.
        ncargo_vacante = NCargo.objects.create(
            descripcion='Auxiliar', cat_ocupacional='SER',
            grupo_escala=NGrupoEscala.objects.first(), salario_basico=2500)
        CargoPlantilla.objects.create(
            ncargo=ncargo_vacante, departamento=departamento,
            cant_aprobada=2, orden_informe=3)

        tarjetas, _ = self._indicadores('CargoPlantilla')
        self.assertEqual(tarjetas['Cargos sin cubrir']['valor'], '1')

    def test_un_indicador_cuyo_campo_no_existe_se_omite_sin_romper(self):
        """La gemela histórica no siempre reproduce todos los campos. Un
        indicador huérfano tiene que desaparecer de la tarjeta, no tumbar el
        informe entero."""
        from informe_inteligente import motor

        definicion = {'campos': {'sexo': {'ruta_orm': 'aspirante__sexo'}}}
        condiciones = [{'campo': 'sexo', 'valor': 'F'},
                       {'campo': 'campo_que_no_existe', 'valor': True}]

        self.assertIsNone(motor._q_de_condiciones(definicion, condiciones))

    def test_la_forma_corta_y_la_larga_son_equivalentes(self):
        from informe_inteligente import motor

        corta = motor._condiciones_de({'campo': 'sexo', 'valor': 'F'})
        larga = motor._condiciones_de(
            {'condiciones': [{'campo': 'sexo', 'valor': 'F'}]})
        self.assertEqual(corta, larga)

    def test_todas_las_medidas_del_desplegable_se_pueden_calcular(self):
        """Guarda: si una medida se ofrece, tiene que poder dibujarse. Es lo que
        evita que añadir un indicador nuevo deje el gráfico con un error."""
        from informe_inteligente import motor

        for modelo in ('CAlta', 'CargoPlantilla'):
            for clave, etiqueta in motor.indicadores_graficables(modelo):
                with self.subTest(modelo=modelo, medida=etiqueta):
                    puntos, _, _ = motor.calcular_evolucion(
                        modelo, {'campos': [], 'filtros': []}, self.admin,
                        clave, 2026)
                    self.assertEqual(len(puntos), 12)
