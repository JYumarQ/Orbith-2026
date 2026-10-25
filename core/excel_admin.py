"""Piezas comunes de los importadores/exportadores de Excel del admin de Django
(24-10-2026): cargos (nomencladores) y estructura organizativa (strorganizativa).

Mismas reglas para los dos:

* **Todo o nada.** Primero se revisa el Excel entero; si una sola fila tiene un
  error, no se guarda nada y se dice cuál es y en qué fila.
* **Simular.** Hace la importación completa dentro de una transacción que se
  deshace al final: se ve exactamente qué pasaría sin cambiar nada.
* **Nunca borra.** Lo que no viene en el Excel se queda como está.
* **Lo que exporta, lo importa.** El Excel exportado tiene el mismo formato que el
  importador espera, así se puede descargar, corregir y volver a subir.
* Queda en Auditoría: cada registro se guarda con `save()`, y el registro
  automático de Auditoría lo anota con el usuario del admin.
"""

import unicodedata

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

TIPO_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class Simulacion(Exception):
    """Se lanza al final de una simulación para deshacer la transacción."""


def clave(texto):
    """Para comparar nombres: sin tildes, sin mayúsculas y sin espacios de más."""
    texto = ' '.join(str(texto or '').split()).lower()
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def limpio(valor):
    """Texto de una celda, sin espacios de más; '' si está vacía."""
    if valor is None:
        return ''
    texto = ' '.join(str(valor).split())
    return '' if texto.lower() == 'nan' else texto


def columnas(hoja, requeridas, opcionales=()):
    """`{nombre lógico: índice}` buscando la fila de títulos en las 5 primeras filas.
    Los títulos se comparan sin tildes ni mayúsculas. Lanza ValueError si falta una
    requerida."""
    buscadas = {**{c: alias for c, alias in requeridas}, **{c: alias for c, alias in opcionales}}
    for numero, fila in enumerate(hoja.iter_rows(min_row=1, max_row=5, values_only=True), start=1):
        titulos = {clave(v): i for i, v in enumerate(fila) if v not in (None, '')}
        encontradas = {}
        for logico, alias in buscadas.items():
            for nombre in alias:
                if clave(nombre) in titulos:
                    encontradas[logico] = titulos[clave(nombre)]
                    break
        if all(c in encontradas for c, _ in requeridas):
            return numero, encontradas
    faltan = ', '.join('«%s»' % alias[0] for _, alias in requeridas)
    raise ValueError('No se encontró la fila de títulos. La hoja «%s» debe tener las columnas %s.'
                     % (hoja.title, faltan))


def hoja_con_titulos(libro, nombre, titulos, filas, anchos):
    """Una hoja con su fila de títulos en negrita, filtro y la fila 1 inmovilizada."""
    hoja = libro.create_sheet(nombre)
    hoja.append(titulos)
    for celda in hoja[1]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor='1E3A8A')
        celda.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for fila in filas:
        hoja.append(list(fila))
    for i, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.freeze_panes = 'A2'
    if filas:
        hoja.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(titulos)), len(filas) + 1)
    return hoja


def libro_vacio():
    libro = Workbook()
    libro.remove(libro.active)
    return libro


def descarga(libro, nombre_fichero):
    respuesta = HttpResponse(content_type=TIPO_MIME)
    respuesta['Content-Disposition'] = 'attachment; filename="%s"' % nombre_fichero
    libro.save(respuesta)
    return respuesta


# --------------------------------------------------------------------------
# Pantalla común del admin: formulario, simulación y resultado
# --------------------------------------------------------------------------

def formulario_importar():
    from django import forms

    class ImportarExcelForm(forms.Form):
        archivo = forms.FileField(label='Excel (.xlsx)')
        estrategia = forms.ChoiceField(
            label='Si ya existe…', widget=forms.RadioSelect, initial='SALTAR',
            choices=[('SALTAR', 'Dejarlo como está (solo se añade lo nuevo)'),
                     ('ACTUALIZAR', 'Ponerlo como dice el Excel')])
        simular = forms.BooleanField(
            label='Solo simular: enseñar qué pasaría sin guardar nada', required=False, initial=True)

        def clean_archivo(self):
            archivo = self.cleaned_data['archivo']
            if not archivo.name.lower().endswith('.xlsx'):
                raise forms.ValidationError('Tiene que ser un Excel .xlsx.')
            return archivo

    return ImportarExcelForm


def vista_importar(modeladmin, request, importar, titulo, ayuda, url_exportar):
    """La pantalla «Importar Excel» de un ModelAdmin. `importar(archivo, estrategia,
    simular)` devuelve el resultado que se pinta debajo del formulario."""
    from django.shortcuts import render

    Formulario = formulario_importar()
    resultado = None
    if request.method == 'POST':
        form = Formulario(request.POST, request.FILES)
        if form.is_valid():
            resultado = importar(form.cleaned_data['archivo'], form.cleaned_data['estrategia'],
                                 form.cleaned_data['simular'])
    else:
        form = Formulario()
    contexto = dict(modeladmin.admin_site.each_context(request), form=form, resultado=resultado,
                    title=titulo, ayuda=ayuda, url_exportar=url_exportar,
                    opts=modeladmin.model._meta)
    return render(request, 'admin/importar_excel.html', contexto)
