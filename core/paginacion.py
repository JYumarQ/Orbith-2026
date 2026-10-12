"""Paginación común de las tablas de Orbith.

Un solo valor de "Filas por página" para todas las tablas, guardado en las
preferencias del usuario (`PreferenciasUsuario.filas_por_pagina`, 25 por
defecto). Se cambia en Configuración o en el pie de cualquier tabla: el pie
manda `filas` en la petición (para no esperar a que se guarde la preferencia)
y además la guarda (static/js/orbith_tablas.js).

Uso en una vista:

    from core.paginacion import paginar
    pagina = paginar(request, consulta)
    contexto.update({'page_obj': pagina, 'filas_por_pagina': pagina.paginator.per_page})

Y en la plantilla, el pie común: `base/partials/tabla_paginacion.html`.
"""
from django.core.paginator import Paginator

FILAS_POR_DEFECTO = 25
OPCIONES_FILAS = (10, 25, 50, 100)


def filas_por_pagina(request):
    """Las filas que pide la petición (`filas`) si es una opción válida; si no,
    las de las preferencias del usuario; si no tiene, 25."""
    try:
        pedidas = int(request.GET.get('filas', ''))
    except (TypeError, ValueError):
        pedidas = None
    if pedidas in OPCIONES_FILAS:
        return pedidas
    preferencias = getattr(getattr(request, 'user', None), 'preferencias', None)
    guardadas = getattr(preferencias, 'filas_por_pagina', None)
    return guardadas if guardadas in OPCIONES_FILAS else FILAS_POR_DEFECTO


def paginar(request, consulta):
    """Página pedida (`page`) de `consulta`, con las filas por página del usuario."""
    return Paginator(consulta, filas_por_pagina(request)).get_page(request.GET.get('page'))


def paginas_visibles(page_obj, alrededor=2):
    """Números de página a pintar, con None donde va un «…».

    Siempre la primera y la última, y `alrededor` páginas a cada lado de la
    actual: con 12 páginas y la 6 actual → 1 … 4 5 6 7 8 … 12.
    """
    total = page_obj.paginator.num_pages
    actual = page_obj.number
    numeros = sorted({1, total} | set(range(max(1, actual - alrededor), min(total, actual + alrededor) + 1)))
    resultado = []
    for numero in numeros:
        if resultado and numero - resultado[-1] > 1:
            resultado.append(None)
        resultado.append(numero)
    return resultado
