"""Nombres de los ficheros que se descargan de Orbith (decisión de RRHH, 24-10-2026).

Un fichero tiene que reconocerse en la carpeta de descargas sin abrirlo:

* Documentos de un trabajador: PREFIJO + nombre y apellidos + expediente.
  `MOV_Juan_Manuel_Yumar_Quiles_20355.docx`. Prefijos: `MOV` (movimiento de
  nómina), `ALTA` (alta inicial o recontratación), `BAJA`, `CON` (contrato de
  trabajo) y `MOD_CON` (su modificación).
* Informes: nombre del informe + unidad o período + fecha.
  `Anexo_17.2_UEB_Central_24-10-2026.xlsx`.

Sin tildes, sin ñ y con guion bajo en lugar de espacios: hay sistemas y
correos que estropean esos caracteres en el nombre de un fichero adjunto.
"""

import re
import unicodedata

from django.utils import timezone

NOMBRES_DE_MES = ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto',
                  'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')

#: Lo único que se conserva tal cual: letras y cifras sin tilde, punto y guion.
_NO_PERMITIDO = re.compile(r'[^A-Za-z0-9.\-]+')


def limpiar(texto):
    """«Camagüey (Taller nº 2)» → «Camaguey_Taller_no_2». Vacío si no queda nada."""
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace('º', 'o').replace('ª', 'a')
    return _NO_PERMITIDO.sub('_', texto).strip('_.-')


def _unir(partes, extension):
    nombre = '_'.join(p for p in (limpiar(p) for p in partes) if p)
    nombre = re.sub(r'_{2,}', '_', nombre) or 'Orbith'
    return '%s.%s' % (nombre, extension.lstrip('.'))


def nombre_de_persona(aspirante):
    if aspirante is None:
        return ''
    return ' '.join(p for p in (aspirante.nombre, aspirante.papellido, aspirante.sapellido) if p)


def documento_de_trabajador(prefijo, aspirante, expediente, extension):
    """`MOV_Juan_Manuel_Yumar_Quiles_20355.docx`."""
    return _unir([prefijo, nombre_de_persona(aspirante), expediente], extension)


def fecha_de_hoy():
    return timezone.localdate().strftime('%d-%m-%Y')


def nombre_de_informe(*partes, extension, fecha=True):
    """`Anexo_17.2_UEB_Central_24-10-2026.xlsx`. Con `fecha=False`, sin la fecha de
    hoy (los informes que ya llevan su mes y año en `partes`)."""
    partes = list(partes)
    if fecha:
        partes.append(fecha_de_hoy())
    return _unir(partes, extension)
