# -*- coding: utf-8 -*-
"""Filtros de plantilla para mostrar valores con su forma y color globales.

Existen para que una misma cosa se vea igual en toda la aplicación sin que cada
plantilla repita el criterio. Las tres reglas que resuelven:

  * el SEXO se escribe «F» o «M», nunca «Femenino» ni «Masculino», y cada uno
    lleva su color;
  * el NIVEL EDUCACIONAL se escribe en siglas —MS(TM) y MS(DG) distinguen las
    dos ramas de Medio Superior—, no con el nombre completo;
  * la CATEGORÍA OCUPACIONAL se escribe con su inicial y su color.

La fuente de los tres criterios es `nomencladores.models`, que es también de
donde los leen los generadores de Word, PDF y Excel.
"""
from django import template
from nomencladores.models import (COLORES_CAT_OCUPACIONAL, color_de_categoria,
                                  color_de_sexo, sigla_de_nivel_educacional)

register = template.Library()


@register.filter
def sigla_sexo(valor):
    """«F» o «M» a partir del código o del nombre completo.

    Acepta las dos formas porque no todas las pantallas tienen el código a mano:
    algunas reciben ya el `get_sexo_display()` del modelo.
    """
    texto = str(valor or '').strip()
    if not texto:
        return ''
    inicial = texto[0].upper()
    return inicial if inicial in ('F', 'M') else texto


@register.filter
def color_sexo(valor):
    """El color global del sexo, listo para un `style="color: …"`."""
    return color_de_sexo(sigla_sexo(valor))


@register.filter
def sigla_nivel(valor):
    """La sigla del nivel educacional: NM, MS(TM), MS(DG), NS…"""
    return sigla_de_nivel_educacional(valor)


@register.filter
def inicial_categoria(codigo):
    """La inicial de la categoría ocupacional: O, T, A, S o C.

    Cuadro Directivo y Cuadro Ejecutivo comparten la C, igual que comparten
    color: la aplicación los agrupa como «Cuadros» en todas partes.
    """
    codigo = (codigo or '').strip().upper()
    return {'OPE': 'O', 'TEC': 'T', 'ADM': 'A',
            'SER': 'S', 'CDI': 'C', 'CEJ': 'C'}.get(codigo, codigo[:1])


@register.filter
def color_categoria(codigo):
    """El color global de la categoría ocupacional."""
    return color_de_categoria(codigo)


#: De la inicial al código. Las cinco iniciales son únicas, así que se puede
#: volver del texto que se imprime al código que decide el color. Hace falta
#: porque las tablas ya muestran la inicial y no guardan el código al lado.
_CODIGO_POR_INICIAL = {'O': 'OPE', 'T': 'TEC', 'A': 'ADM',
                       'S': 'SER', 'C': 'CDI'}


@register.filter
def color_por_inicial(inicial):
    """El color de la categoría a partir de su inicial (O, T, A, S, C)."""
    return color_de_categoria(_CODIGO_POR_INICIAL.get(
        (inicial or '').strip().upper()[:1], ''))


@register.filter
def es_categoria_conocida(codigo):
    return (codigo or '').strip().upper() in COLORES_CAT_OCUPACIONAL


@register.filter
def emparejar(columnas, valores):
    """Recorre a la vez las columnas y los valores de una fila.

    Las plantillas de Django no saben iterar dos listas en paralelo, y las
    tablas de Informe Inteligente lo necesitan: de cada celda hay que saber, a
    la vez, QUÉ vale y a QUÉ campo pertenece —para centrarla si es corta, o
    colorearla si es el sexo o la categoría—.

    Devuelve pares `(columna, valor)`, que en la plantilla se leen como
    `par.0` y `par.1`.
    """
    return list(zip(columnas or [], valores or []))
