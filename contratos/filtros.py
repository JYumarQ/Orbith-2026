"""Filtros del listado de Contratos.

`aplicar_filtros()` es el único punto donde se traduce la querystring a
condiciones de queryset — antes vivía duplicado (a medias) solo dentro de
`search_contratos`, así que la carga inicial de `ContratoListView` (sin pasar
por la búsqueda AJAX) nunca respetaba un `?raza=NE` en la URL. Ahora ambas
vistas llaman a la misma función, mismo patrón que `cierres/filtros.py` /
`subsanacion/filtros.py`.
"""

from django.db.models import Q


def aplicar_filtros(request, qs):
    """Aplica sobre `qs` (queryset de `CAlta`) los filtros presentes en
    `request.GET`. Cualquier parámetro ausente o vacío se ignora — un enlace
    sin filtros sigue mostrando el listado completo."""
    provincia_id = request.GET.get('provincia')
    municipio_id = request.GET.get('municipio')
    nivel_educ = request.GET.get('nivel_educ')
    especialidad_id = request.GET.get('especialidad')
    sexo = request.GET.get('sexo')
    raza = request.GET.get('raza')
    grado_cientifico = request.GET.get('grado_cientifico')
    cat_ocupacional = request.GET.get('cat_ocupacional')
    tipo = request.GET.get('tipo')

    if provincia_id:
        qs = qs.filter(aspirante__provincia_id=provincia_id)
    if municipio_id:
        qs = qs.filter(aspirante__municipio_id=municipio_id)
    if nivel_educ:
        qs = qs.filter(aspirante__nivel_educ=nivel_educ)
    if especialidad_id:
        qs = qs.filter(aspirante__especialidad_id=especialidad_id)
    if sexo:
        qs = qs.filter(aspirante__sexo=sexo)
    if raza:
        qs = qs.filter(aspirante__raza=raza)

    if grado_cientifico == 'NINGUNO':
        qs = qs.filter(Q(aspirante__grado_cientifico__isnull=True) | Q(aspirante__grado_cientifico=''))
    elif grado_cientifico:
        qs = qs.filter(aspirante__grado_cientifico=grado_cientifico)

    # 'CUA' no es un valor real de `NCargo.cat_ocupacional` — el Dashboard
    # agrupa Cuadro Directivo (CDI) y Cuadro Ejecutivo (CEJ) bajo esa etiqueta
    # solo para mostrar, así que el filtro traduce el sentinel de vuelta a los
    # dos códigos reales.
    if cat_ocupacional == 'CUA':
        qs = qs.filter(cargo__ncargo__cat_ocupacional__in=['CDI', 'CEJ'])
    elif cat_ocupacional:
        qs = qs.filter(cargo__ncargo__cat_ocupacional=cat_ocupacional)

    if tipo:
        qs = qs.filter(tipo__descripcion=tipo)

    return qs
