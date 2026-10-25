from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.urls import reverse

from usuarios.models import CustomUser

from .models import NCargo, NGrupoEscala, NMunicipio, NProvincia


class AuditoriaAdminTests(TestCase):
    """Crear/editar/eliminar un nomenclador (NCargo) desde el Admin de Django ahora
    deja rastro en `auditoria.EventoAuditoria`, gracias a `AuditoriaAdminMixin`
    (compartido con el resto de apps, ver `contratos.tests.AuditoriaAdminTests` para
    el caso original que motivó esto)."""

    @classmethod
    def setUpTestData(cls):
        cls.grupo_escala = NGrupoEscala.objects.create(nivel='G1')
        cls.admin = CustomUser.objects.create_user(
            username='admin_nomencladores', password='x', es_admin=True)

    def test_eliminar_un_cargo_en_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        cargo = NCargo.objects.create(
            descripcion='Cargo de prueba', cat_ocupacional='TEC',
            grupo_escala=self.grupo_escala, salario_basico=1000)
        self.client.force_login(self.admin)

        url = reverse('admin:nomencladores_ncargo_delete', args=[cargo.pk])
        self.client.post(url, {'post': 'yes'})

        self.assertFalse(NCargo.objects.filter(pk=cargo.pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(cargo.pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.modulo, 'nomencladores')

    def test_editar_un_cargo_desde_el_admin_queda_auditado(self):
        from auditoria.models import EventoAuditoria
        from nomencladores.admin import NCargoAdmin

        cargo = NCargo.objects.create(
            descripcion='Cargo de prueba', cat_ocupacional='TEC',
            grupo_escala=self.grupo_escala, salario_basico=1000)

        admin_instance = NCargoAdmin(NCargo, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.admin
        cargo.descripcion = 'Cargo corregido'
        admin_instance.save_model(request, cargo, form=None, change=True)

        evento = EventoAuditoria.objects.filter(
            object_id=str(cargo.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)


class AuditoriaInlineTests(TestCase):
    """El inline NMunicipioInline (dentro de NProvinciaAdmin) permite crear/editar/
    eliminar municipios sin pasar por save_model/delete_model — Django solo llama a
    `formset.save()`. `AuditoriaAdminMixin.save_formset` cierra ese hueco."""

    @classmethod
    def setUpTestData(cls):
        cls.provincia = NProvincia.objects.create(nombre='Provincia Auditoría')
        cls.municipio = NMunicipio.objects.create(
            nombre='Municipio Viejo', provincia=cls.provincia)
        cls.admin = CustomUser.objects.create_user(
            username='admin_inline_nomencladores', password='x', es_admin=True)

    def _datos_formset(self, total_forms, initial_forms):
        return {
            'nmunicipio_set-TOTAL_FORMS': str(total_forms),
            'nmunicipio_set-INITIAL_FORMS': str(initial_forms),
            'nmunicipio_set-MIN_NUM_FORMS': '0',
            'nmunicipio_set-MAX_NUM_FORMS': '1000',
        }

    def test_crear_y_editar_municipio_desde_el_inline_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        self.client.force_login(self.admin)
        url = reverse('admin:nomencladores_nprovincia_change', args=[self.provincia.pk])

        data = {'nombre': self.provincia.nombre, 'siglas': ''}
        data.update(self._datos_formset(total_forms=2, initial_forms=1))
        data['nmunicipio_set-0-id'] = str(self.municipio.pk)
        data['nmunicipio_set-0-nombre'] = 'Municipio Editado'
        data['nmunicipio_set-1-id'] = ''
        data['nmunicipio_set-1-nombre'] = 'Municipio Nuevo'

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        self.municipio.refresh_from_db()
        self.assertEqual(self.municipio.nombre, 'Municipio Editado')
        nuevo = NMunicipio.objects.get(nombre='Municipio Nuevo')

        evento_editado = EventoAuditoria.objects.filter(
            object_id=str(self.municipio.pk), accion='UPD').latest('fecha')
        self.assertEqual(evento_editado.usuario_id, self.admin.pk)
        evento_creado = EventoAuditoria.objects.filter(
            object_id=str(nuevo.pk), accion='ADD').latest('fecha')
        self.assertEqual(evento_creado.usuario_id, self.admin.pk)

    def test_eliminar_municipio_desde_el_inline_queda_auditado(self):
        from auditoria.models import EventoAuditoria

        self.client.force_login(self.admin)
        url = reverse('admin:nomencladores_nprovincia_change', args=[self.provincia.pk])

        data = {'nombre': self.provincia.nombre, 'siglas': ''}
        data.update(self._datos_formset(total_forms=1, initial_forms=1))
        data['nmunicipio_set-0-id'] = str(self.municipio.pk)
        data['nmunicipio_set-0-nombre'] = self.municipio.nombre
        data['nmunicipio_set-0-DELETE'] = 'on'

        municipio_pk = self.municipio.pk
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(NMunicipio.objects.filter(pk=municipio_pk).exists())
        evento = EventoAuditoria.objects.filter(
            object_id=str(municipio_pk), accion='DEL').latest('fecha')
        self.assertEqual(evento.usuario_id, self.admin.pk)


class ColoresDeCategoriaOcupacional(TestCase):
    """La paleta de las categorías ocupacionales.

    Los colores viven en Python, al lado de los códigos que colorean, y se
    repiten en `static/css/informes-rrhh.css` para poder pintar insignias sin
    JavaScript. Estas pruebas son la guarda de que los dos sitios no se
    separen: sin ellas, cambiar un color en uno y olvidar el otro deja la
    aplicación pintando la misma categoría de dos maneras.
    """

    def test_todas_las_categorias_tienen_color(self):
        """Añadir una categoría obliga a decidir su color: sin esto, la nueva
        saldría gris en todos los gráficos sin que nadie se entere."""
        from nomencladores.models import COLORES_CAT_OCUPACIONAL, NCargo

        codigos = {codigo for codigo, _ in NCargo._meta.get_field('cat_ocupacional').choices}
        self.assertEqual(codigos, set(COLORES_CAT_OCUPACIONAL))

    def test_los_dos_cuadros_comparten_color(self):
        """La aplicación los agrupa como «Cuadros» en todas partes."""
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        self.assertEqual(COLORES_CAT_OCUPACIONAL['CDI'],
                         COLORES_CAT_OCUPACIONAL['CEJ'])

    def test_ninguna_categoria_usa_un_color_de_alerta(self):
        """En los informes el naranja significa «falta» y el rojo «crítico». Si
        una categoría fuera naranja, una barra naranja dejaría de querer decir
        algo. Se comprueba que ningún color cae en la franja cálida."""
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        for codigo, color in COLORES_CAT_OCUPACIONAL.items():
            rojo = int(color[1:3], 16)
            verde = int(color[3:5], 16)
            azul = int(color[5:7], 16)
            with self.subTest(categoria=codigo):
                # Cálido = el rojo domina claramente sobre el azul.
                self.assertLessEqual(rojo, azul + 40,
                                     '%s (%s) tira a cálido' % (codigo, color))

    def test_ningun_color_desaparece_sobre_las_tarjetas_oscuras(self):
        """Varias pantallas tienen tarjetas de fondo oscuro —los gráficos del
        Registro Diario, el resumen de Contratos Determinados—, y un color casi
        negro se pierde contra ellas. Pasó de verdad: la primera versión de esta
        paleta puso Cuadros en pizarra `#0f172a` y su barra era invisible.

        Se exige un contraste mínimo de 2:1 contra ese fondo, que es lo que
        separa «se ve» de «hay que adivinarlo».
        """
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        def luminancia(hexadecimal):
            canales = []
            for i in (1, 3, 5):
                valor = int(hexadecimal[i:i + 2], 16) / 255
                canales.append(valor / 12.92 if valor <= 0.03928
                               else ((valor + 0.055) / 1.055) ** 2.4)
            rojo, verde, azul = canales
            return 0.2126 * rojo + 0.7152 * verde + 0.0722 * azul

        #: El más claro de los dos fondos oscuros que usa la aplicación.
        fondo = luminancia('#1e293b')

        for codigo, color in COLORES_CAT_OCUPACIONAL.items():
            contraste = (luminancia(color) + 0.05) / (fondo + 0.05)
            with self.subTest(categoria=codigo):
                self.assertGreaterEqual(
                    contraste, 2.0,
                    '%s (%s) se pierde sobre las tarjetas oscuras' % (codigo, color))

    def test_el_css_repite_exactamente_los_mismos_colores(self):
        import io
        import os

        from django.conf import settings
        from nomencladores.models import COLORES_CAT_OCUPACIONAL

        ruta = os.path.join(settings.BASE_DIR, 'static', 'css', 'informes-rrhh.css')
        css = io.open(ruta, encoding='utf-8').read().lower()

        for codigo, color in COLORES_CAT_OCUPACIONAL.items():
            with self.subTest(categoria=codigo):
                self.assertIn(color.lower(), css,
                              'El color de %s no está en informes-rrhh.css' % codigo)

    def test_un_codigo_desconocido_no_deja_el_grafico_sin_color(self):
        from nomencladores.models import COLOR_CAT_DESCONOCIDA, color_de_categoria

        self.assertEqual(color_de_categoria('XXX'), COLOR_CAT_DESCONOCIDA)
        self.assertEqual(color_de_categoria(None), COLOR_CAT_DESCONOCIDA)
        self.assertEqual(color_de_categoria(''), COLOR_CAT_DESCONOCIDA)


class ColoresYSiglasDelSexo(TestCase):
    """La paleta del sexo, con la misma guarda que la de las categorías.

    El sexo se escribe «F» o «M» y cada uno lleva su color en toda la
    aplicación. Antes había dos criterios: el Dashboard pintaba a las mujeres de
    rojo y a los hombres de cian, e Informe Inteligente usaba rosa para el
    femenino y nada para el masculino.
    """

    def test_los_dos_sexos_del_modelo_tienen_color(self):
        from bolsa.models import Aspirante
        from nomencladores.models import COLORES_SEXO

        codigos = {codigo for codigo, _ in Aspirante._meta.get_field('sexo').choices}
        self.assertEqual(codigos, set(COLORES_SEXO))

    def test_el_femenino_no_usa_un_color_de_alerta(self):
        """El rojo significa «crítico» en todos los informes: no puede
        significar también «mujer». El rosa es el que se eligió justamente para
        no chocar con esa lectura."""
        from nomencladores.models import COLORES_SEXO

        color = COLORES_SEXO['F']
        rojo, verde, azul = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(azul, verde,
                           'El femenino %s tira a rojo puro' % color)

    def test_el_css_repite_exactamente_los_mismos_colores(self):
        import io
        import os

        from django.conf import settings
        from nomencladores.models import COLORES_SEXO

        ruta = os.path.join(settings.BASE_DIR, 'static', 'css', 'informes-rrhh.css')
        css = io.open(ruta, encoding='utf-8').read().lower()

        for codigo, color in COLORES_SEXO.items():
            with self.subTest(sexo=codigo):
                self.assertIn(color.lower(), css,
                              'El color de %s no está en informes-rrhh.css' % codigo)

    def test_un_sexo_sin_declarar_no_deja_la_celda_sin_color(self):
        from nomencladores.models import COLOR_SEXO_DESCONOCIDO, color_de_sexo

        for valor in (None, '', 'X'):
            with self.subTest(valor=valor):
                self.assertEqual(color_de_sexo(valor), COLOR_SEXO_DESCONOCIDO)


class SiglasDelNivelEducacional(TestCase):
    """Lo que se guarda y lo que se muestra NO coinciden, y es a propósito.

    Los códigos guardados vienen de antiguo —`NG` para Nivel Medio— y
    renombrarlos exigiría migrar datos. Las siglas que se muestran son las que
    usa la empresa, y distinguen las dos ramas de Medio Superior.
    """

    def test_cada_nivel_del_modelo_tiene_su_sigla(self):
        """Añadir un nivel obliga a decidir cómo se escribe."""
        from bolsa.models import Aspirante
        from nomencladores.models import SIGLAS_NIVEL_EDUCACIONAL

        codigos = {codigo for codigo, _ in Aspirante._meta.get_field('nivel_educ').choices
                   if codigo}
        self.assertEqual(codigos, set(SIGLAS_NIVEL_EDUCACIONAL))

    def test_las_dos_ramas_de_medio_superior_se_distinguen(self):
        """Son el mismo nivel por caminos distintos, y en un informe de
        plantilla no da igual cuál de los dos."""
        from nomencladores.models import sigla_de_nivel_educacional

        self.assertEqual(sigla_de_nivel_educacional('TM'), 'MS(TM)')
        self.assertEqual(sigla_de_nivel_educacional('MS'), 'MS(DG)')

    def test_el_nivel_medio_se_muestra_como_nm(self):
        """La base guarda NG por razones históricas; nadie lo llama así."""
        from nomencladores.models import sigla_de_nivel_educacional

        self.assertEqual(sigla_de_nivel_educacional('NG'), 'NM')

    def test_un_codigo_desconocido_se_muestra_tal_cual(self):
        """Enseñar algo raro se puede investigar; un hueco, no."""
        from nomencladores.models import sigla_de_nivel_educacional

        self.assertEqual(sigla_de_nivel_educacional('ZZ'), 'ZZ')
        self.assertEqual(sigla_de_nivel_educacional(''), '')


class NombreYSiglasDelTerritorio(TestCase):
    """El seguro que evita otro «Florida      Flo».

    Aquel municipio se guardó con las siglas escritas DENTRO de la casilla del
    nombre y la de siglas vacía. Las dos columnas siempre estuvieron separadas:
    lo que falló fue quién escribió dónde, y no entró por la pantalla —cuyo
    modal ya validaba— sino por una vía sin JavaScript.

    Por eso la defensa está en el modelo, que es el único punto por el que pasan
    todas las vías: el modal, el admin, un script y una importación.
    """

    def setUp(self):
        from nomencladores.models import NProvincia

        self.provincia = NProvincia.objects.create(nombre='Camagüey',
                                                   siglas='CMG')

    def test_el_nombre_se_normaliza_al_guardar(self):
        """Aunque llegue de un script, que no ejecuta `clean()`."""
        from nomencladores.models import NMunicipio

        municipio = NMunicipio.objects.create(nombre='  Santa   Cruz  ',
                                              provincia=self.provincia)
        municipio.refresh_from_db()
        self.assertEqual(municipio.nombre, 'Santa Cruz')

    def test_un_nombre_con_la_sigla_dentro_se_rechaza(self):
        """El caso exacto que motivó todo esto."""
        from django.core.exceptions import ValidationError

        from nomencladores.models import NMunicipio

        municipio = NMunicipio(nombre='Florida      Flo',
                               provincia=self.provincia)
        with self.assertRaises(ValidationError) as capturado:
            municipio.full_clean()
        self.assertIn('nombre', capturado.exception.error_dict)

    def test_las_siglas_son_exactamente_tres_letras(self):
        from django.core.exceptions import ValidationError

        from nomencladores.models import NMunicipio

        for malas in ('FL', 'FLOR', 'F1O', 'F L'):
            with self.subTest(siglas=malas):
                municipio = NMunicipio(nombre='Florida', siglas=malas,
                                       provincia=self.provincia)
                with self.assertRaises(ValidationError) as capturado:
                    municipio.full_clean()
                self.assertIn('siglas', capturado.exception.error_dict)

    def test_las_siglas_siguen_siendo_opcionales(self):
        """Se pueden dejar en blanco; lo que no se puede es escribirlas mal."""
        from nomencladores.models import NMunicipio

        municipio = NMunicipio(nombre='Esmeralda', provincia=self.provincia)
        municipio.full_clean()   # no levanta nada

    def test_las_siglas_se_guardan_en_su_propia_columna(self):
        """El invariante que el usuario temía roto: son dos columnas.

        Se comprueba leyendo la tabla directamente, no el objeto de Python.
        """
        from django.db import connection

        from nomencladores.models import NMunicipio

        NMunicipio.objects.create(nombre='Florida', siglas='flo',
                                  provincia=self.provincia)
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT nombre, siglas FROM nomencladores_nmunicipio '
                'WHERE nombre = %s', ['Florida'])
            nombre, siglas = cursor.fetchone()

        self.assertEqual(nombre, 'Florida')
        self.assertEqual(siglas, 'FLO')   # y se normalizan a mayúsculas


class ProteccionCsrfTests(TestCase):
    """Las APIs de Nomencladores ya no llevan `@csrf_exempt` (Fase 3, 23-10-2026): una
    página ajena no puede cambiar nomencladores en nombre de un administrador con la
    sesión abierta. Las pantallas de Orbith mandan el token (ver `base.html`)."""

    def setUp(self):
        from django.test import Client
        from .models import NTridente
        self.tridente = NTridente.objects.create(tipo='I')
        admin = CustomUser.objects.create_user(username='admin_csrf', password='x', es_admin=True)
        self.cliente = Client(enforce_csrf_checks=True)
        self.cliente.force_login(admin)

    def test_sin_token_se_rechaza_y_con_token_pasa(self):
        url = reverse('tridente-update', args=[self.tridente.pk])
        sin = self.cliente.put(url, '{"tipo": "II"}', content_type='application/json')
        self.assertEqual(sin.status_code, 403)
        self.cliente.get(reverse('parametros'))   # la página deja la cookie del token
        token = self.cliente.cookies['csrftoken'].value
        con = self.cliente.put(url, '{"tipo": "II"}', content_type='application/json',
                               HTTP_X_CSRFTOKEN=token)
        self.assertEqual(con.status_code, 200)
        self.tridente.refresh_from_db()
        self.assertEqual(self.tridente.tipo, 'II')


class ColoresLegiblesTests(TestCase):
    """El color de un tipo de unidad lo elige el usuario: como letra sobre blanco
    se oscurece lo justo para leerse, sin cambiar de tono (24-10-2026)."""

    def test_un_color_oscuro_se_deja_igual(self):
        from .models import color_legible, es_color_claro
        self.assertFalse(es_color_claro('#1e3a8a'))
        self.assertEqual(color_legible('#1e3a8a'), '#1e3a8a')

    def test_un_amarillo_se_oscurece_hasta_leerse(self):
        from .models import CONTRASTE_MINIMO, color_legible, contraste_con_blanco, es_color_claro
        self.assertTrue(es_color_claro('#ffff00'))
        oscuro = color_legible('#ffff00')
        self.assertGreaterEqual(contraste_con_blanco(oscuro), CONTRASTE_MINIMO)
        # Mismo tono: rojo y verde iguales y sin azul, como el amarillo de partida.
        self.assertEqual(oscuro[1:3], oscuro[3:5])
        self.assertEqual(oscuro[5:7], '00')

    def test_valores_raros_no_rompen(self):
        from .models import color_legible, es_color_claro
        self.assertEqual(color_legible('#fff'), color_legible('#ffffff'))
        self.assertEqual(color_legible(None), None)
        self.assertEqual(color_legible('rojo'), 'rojo')
        self.assertFalse(es_color_claro(''))


class ExcelCargosTests(TestCase):
    """Importar/Exportar el nomenclador de cargos (24-10-2026). Un cargo se reconoce
    por NOMBRE y GRUPO: en la empresa hay cargos con el mismo nombre y otro grupo."""

    @classmethod
    def setUpTestData(cls):
        from .models import NGrupoEscala
        NGrupoEscala.objects.create(nivel='XI')
        NGrupoEscala.objects.create(nivel='XIV')

    def excel(self, filas):
        import io

        from openpyxl import Workbook
        libro = Workbook()
        hoja = libro.active
        hoja.title = 'CARGOS_CODIGO'
        hoja.append(['Cargos', 'Grupo  Escala', 'Categoría Ocupacional', 'Salario Básico'])
        for fila in filas:
            hoja.append(list(fila))
        salida = io.BytesIO()
        libro.save(salida)
        salida.seek(0)
        return salida

    def test_mismo_nombre_con_otro_grupo_son_dos_cargos(self):
        from .importacion import importar_cargos
        from .models import NCargo
        resultado = importar_cargos(self.excel([
            ('Especialista A (EP)', 'XI', 'Técnico', 3410),
            ('Especialista A (EP)', 'XIV', 'Técnico', 4010),
            ('Especialista A (EP)', 'XIV', 'Técnico', 4010)]))
        self.assertEqual(len(resultado['creados']), 2)
        self.assertEqual(len(resultado['repetidos']), 1)
        self.assertEqual(NCargo.objects.filter(descripcion='Especialista A (EP)').count(), 2)

    def test_un_error_no_guarda_nada_y_actualizar_cambia_el_salario(self):
        from .importacion import importar_cargos
        from .models import NCargo
        malo = importar_cargos(self.excel([('Chofer', 'XI', 'Operario', 3000), ('Otro', 'ZZ', 'Operario', 1)]))
        self.assertTrue(malo['errores'])
        self.assertFalse(NCargo.objects.exists())
        importar_cargos(self.excel([('Chofer', 'XI', 'Operario', 3000)]))
        saltar = importar_cargos(self.excel([('chofer', 'XI', 'Operario', 3500)]), 'SALTAR')
        self.assertEqual(len(saltar['saltados']), 1)
        importar_cargos(self.excel([('chofer', 'XI', 'Operario', 3500)]), 'ACTUALIZAR')
        self.assertEqual(NCargo.objects.get().salario_basico, 3500)

    def test_lo_exportado_se_vuelve_a_importar_sin_cambios(self):
        import io
        from .importacion import exportar_cargos, importar_cargos
        importar_cargos(self.excel([('Chofer', 'XI', 'Operario', 3000),
                                    ('Jefe', 'XIV', 'Cuadro Directivo', 6000)]))
        salida = io.BytesIO()
        exportar_cargos().save(salida)
        salida.seek(0)
        resultado = importar_cargos(salida, 'ACTUALIZAR')
        self.assertEqual((resultado['creados'], resultado['actualizados'], resultado['sin_cambios']),
                         ([], [], 2))
