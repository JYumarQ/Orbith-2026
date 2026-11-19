"""Pruebas transversales de las plantillas."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ComentariosDePlantillaTests(SimpleTestCase):
    """`{# … #}` de Django solo vale para UNA línea: partido en varias, se pinta como
    texto en la página (pasó el 24-10-2026 con el comentario del token CSRF de
    `base.html`, visible en todas las pantallas). Para varias líneas, `{% comment %}`."""

    def test_no_hay_comentarios_de_una_linea_partidos_en_varias(self):
        carpetas = [Path(d) for d in settings.TEMPLATES[0].get('DIRS', [])]
        partidos = []
        for carpeta in carpetas:
            for plantilla in carpeta.rglob('*.html'):
                texto = plantilla.read_text(encoding='utf-8', errors='ignore')
                for numero, linea in enumerate(texto.splitlines(), start=1):
                    if re.search(r'\{#(?!.*#\})', linea):
                        partidos.append(f'{plantilla.relative_to(carpeta)}:{numero}')
        self.assertEqual(partidos, [], 'Use {% comment %} para los comentarios de varias líneas.')


class NombresDeDescargaTests(SimpleTestCase):
    """Nombres de los ficheros descargados (core/nombres_descarga.py, 24-10-2026)."""

    def test_documento_de_un_trabajador(self):
        from types import SimpleNamespace
        from core.nombres_descarga import documento_de_trabajador
        persona = SimpleNamespace(nombre='Juan Manuel', papellido='Yumar', sapellido='Quiles')
        self.assertEqual(documento_de_trabajador('MOV', persona, '20355', 'docx'),
                         'MOV_Juan_Manuel_Yumar_Quiles_20355.docx')

    def test_sin_tildes_ni_enes_ni_simbolos(self):
        from types import SimpleNamespace
        from core.nombres_descarga import documento_de_trabajador, limpiar
        self.assertEqual(limpiar('Camagüey (Taller nº 2)'), 'Camaguey_Taller_no_2')
        persona = SimpleNamespace(nombre='María José', papellido='Peña', sapellido='')
        self.assertEqual(documento_de_trabajador('MOD_CON', persona, '07', 'docx'),
                         'MOD_CON_Maria_Jose_Pena_07.docx')

    def test_informe_con_fecha(self):
        from unittest import mock
        from core import nombres_descarga
        with mock.patch.object(nombres_descarga, 'fecha_de_hoy', return_value='24-10-2026'):
            self.assertEqual(nombres_descarga.nombre_de_informe('Anexo 17.2', 'UEB Central', extension='xlsx'),
                             'Anexo_17.2_UEB_Central_24-10-2026.xlsx')


class CamposFueraDelFormularioTests(SimpleTestCase):
    """Un campo fuera de su <form> no se envía al guardar, y el error no se ve
    (27-10-2026: el interruptor «En Plantilla» de Cargo estaba en la cabecera del
    modal y todo cargo se guardó «Fuera de Plantilla» durante semanas). Esta prueba
    busca, en las plantillas que tienen <form>, campos con nombre fuera de cualquier
    formulario: en el HTML, los que pinta Django (`{{ form.campo }}`) y los parciales
    con campos incluidos fuera. Arreglo habitual: meterlo dentro del <form> o darle
    `form="id-del-formulario"`. Si el campo lo envía el JavaScript de la pantalla por
    su cuenta, se apunta en `PERMITIDOS` con el motivo."""

    #: (plantilla, campo) revisados a mano el 18-11-2026: no dependen del <form>.
    PERMITIDOS = {
        # Los lee el JavaScript de la pantalla y los envía él.
        ('base/partials/modales_usuario.html', 'pref_sidebar'),
        ('pages/contrato/partials/modal_baja.html', 'actividad_realizada'),
        # Filtros que viajan con hx-include / el JavaScript de los filtros.
        *(('pages/dashboard.html', c) for c in ('desde', 'hasta', 'uo', 'annos_desde', 'annos_hasta')),
        ('pages/dashboard.html', 'include pages/contrato/partials/modal_nuevo_contrato.html'),
        *(('pages/notificaciones/partials/tab_recordatorios.html', c) for c in ('tab', 'sub', 'prioridad')),
        *(('pages/solicitudes/list_solicitud.html', c)
          for c in ('tab', 'tipo', 'unidad', 'moderador', 'desde', 'hasta')),
        # «Activo» de Cargo: deshabilitado; el modelo lo calcula al guardar.
        ('pages/cargo/add_cargo.html', 'form.activo'),
        ('pages/cargo/updt_cargo.html', 'form.activo'),
        # Datos que solo se muestran (no son campos de formulario).
        *(('pages/informes/informe_motivos_contrato.html', c) for c in ('f.color_texto', 'f.color', 'f.unidad')),
        # Sus campos ya llevan form="formFiltrosAnexo17".
        ('pages/informes_anexo/anexo17.html', 'include pages/informes_anexo/partials/bloque_firmas.html'),
        ('pages/subsanacion/partials/panel_hallazgos.html', 'include base/partials/tabla_paginacion.html'),
    }

    VARIABLE = r'{{\s*((?:form|formulario|f|form_[a-z_]+|[a-z_]*form)\.[a-z_0-9]+)(?:\s*\|[^}]*)?\s*}}'
    NO_CAMPO = ('.label', '.errors', '.help_text', '.id_for_label', '.value', '.non_field_errors', '.media',
                '.name', '.initial', '.instance', '.cleaned_data', '.field', '.html_name', '.auto_id')

    def _limpiar(self, texto):
        texto = re.sub(r'<script.*?</script>', '', texto, flags=re.S | re.I)
        texto = re.sub(r'{%\s*comment\s*%}.*?{%\s*endcomment\s*%}', '', texto, flags=re.S)
        return re.sub(r'{#.*?#}', '', texto)

    def _parcial_con_campos(self, carpeta, ruta):
        fichero = carpeta / ruta
        if not fichero.exists():
            return False
        texto = self._limpiar(fichero.read_text(encoding='utf-8', errors='ignore'))
        if '<form' in texto.lower():
            return False
        return bool(re.search(r'<(input|select|textarea)[^>]*\sname=', texto, re.I)
                    or re.search(self.VARIABLE, texto, re.I))

    def _fuera_de_formulario(self, carpeta, texto):
        """Nombres de los campos (o parciales) que quedan fuera de todo <form>."""
        etiqueta = r'<(form|/form|input|select|textarea)\b([^>]*)>'
        incluir = r"""{%\s*include\s+['"]([^'"]+)['"]"""
        fuera, profundidad = [], 0
        for m in re.finditer(f'{etiqueta}|{self.VARIABLE}|{incluir}', texto, re.I):
            if m.group(1):
                nombre_etiqueta, atributos = m.group(1).lower(), m.group(2)
                if nombre_etiqueta == 'form':
                    profundidad += 1
                elif nombre_etiqueta == '/form':
                    profundidad = max(0, profundidad - 1)
                elif profundidad == 0:
                    nombre = re.search(r'\sname="([^"]+)"', atributos)
                    if (nombre and not re.search(r'\sform="', atributos) and ' hx-' not in f' {atributos}'
                            and not re.search(r'type="(button|submit|reset)"', atributos)):
                        fuera.append(nombre.group(1))
            elif profundidad:
                continue
            elif m.group(3):
                if not m.group(3).lower().endswith(self.NO_CAMPO):
                    fuera.append(m.group(3))
            elif self._parcial_con_campos(carpeta, m.group(4)):
                fuera.append(f'include {m.group(4)}')
        return fuera

    def test_ningun_campo_queda_fuera_de_su_formulario(self):
        sospechosos = []
        for carpeta in (Path(d) for d in settings.TEMPLATES[0].get('DIRS', [])):
            for plantilla in carpeta.rglob('*.html'):
                texto = self._limpiar(plantilla.read_text(encoding='utf-8', errors='ignore'))
                if '<form' not in texto.lower():
                    continue
                ruta = plantilla.relative_to(carpeta).as_posix()
                sospechosos += [f'{ruta}: {campo}' for campo in self._fuera_de_formulario(carpeta, texto)
                                if (ruta, campo) not in self.PERMITIDOS]
        self.assertEqual(sorted(set(sospechosos)), [],
                         'Campos fuera de su <form>: no se enviarán al guardar (ver la explicación de la prueba).')
