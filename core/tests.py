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
