"""Filtro de las ventanas de la Dashboard: leer una columna de una fila."""

from django import template

register = template.Library()


@register.filter
def campo(fila, clave):
    """`{{ fila|campo:'nombre' }}`: el valor de esa columna (las filas son diccionarios)."""
    return fila.get(clave) if hasattr(fila, 'get') else getattr(fila, clave, None)
