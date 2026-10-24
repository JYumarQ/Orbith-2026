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
