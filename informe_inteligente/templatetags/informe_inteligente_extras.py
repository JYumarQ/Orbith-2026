import json

from django import template

register = template.Library()


@register.filter
def como_json(valor):
    """
    Serializa un valor a JSON para incrustarlo en un atributo HTML
    (por ejemplo data-choices). Django escapa las comillas al renderizar
    y el navegador las devuelve intactas al leer el dataset.
    """
    return json.dumps(valor or [], ensure_ascii=False)


@register.filter
def get_item(diccionario, clave):
    """Permite acceder a un diccionario por clave variable dentro del template."""
    if not diccionario:
        return None
    return diccionario.get(clave)


@register.filter
def rango_paginas(paginator, pagina_actual):
    """
    Devuelve el rango de páginas a mostrar en el paginador, recortado con
    puntos suspensivos cuando hay muchas páginas (ej. 1 … 4 5 6 … 65).
    Usa el algoritmo que ya trae Django, así no hay que reinventarlo.
    """
    try:
        return list(paginator.get_elided_page_range(pagina_actual, on_each_side=1, on_ends=1))
    except Exception:
        return list(paginator.page_range)
