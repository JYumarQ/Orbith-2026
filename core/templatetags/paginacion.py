"""`{% paginas_visibles page_obj as paginas %}`: los números del pie común de
las tablas (`base/partials/tabla_paginacion.html`). Ver core/paginacion.py."""
from django import template

from core.paginacion import OPCIONES_FILAS, paginas_visibles as _paginas_visibles

register = template.Library()


@register.simple_tag
def paginas_visibles(page_obj):
    return _paginas_visibles(page_obj)


@register.simple_tag
def opciones_filas():
    return OPCIONES_FILAS
