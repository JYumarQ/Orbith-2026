from django import template

register = template.Library()


@register.filter
def get_item(diccionario, clave):
    """Permite acceder a un diccionario por clave variable dentro del template."""
    if not diccionario:
        return None
    return diccionario.get(clave)