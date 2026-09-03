"""Filtros del listado de Contratos.

`aplicar_filtros()` es el único punto donde se traduce la querystring a
condiciones de queryset — antes vivía duplicado (a medias) solo dentro de
`search_contratos`, así que la carga inicial de `ContratoListView` (sin pasar
por la búsqueda AJAX) nunca respetaba un `?raza=NE` en la URL. Ahora ambas
vistas llaman a la misma función, mismo patrón que `cierres/filtros.py` /
`subsanacion/filtros.py`.
"""

from django.db.models import Q

from strorganizativa.jerarquia import expandir

from .permisos import es_administrador, es_moderador


def contratos_visibles(usuario):
    """Base del listado: alcance por rol, único punto donde se decide.

    Administrador y Observador ven todos los contratos (el listado es
    informativo, no expone acciones de edición). El Moderador solo ve los
    contratos cuyo cargo cuelga de una de sus Unidades Organizativas
    asignadas (`CustomUser.unidades`), mismo criterio que
    `cierres/filtros.py::unidades_visibles()` y
    `solicitudes/filtros.py::solicitudes_visibles()`.
    """
    from .models import CAlta

    qs = CAlta.objects.all()
    if es_moderador(usuario):
        return qs.filter(
            cargo__departamento__unidad_organizativa__in=usuario.unidades.all())
    return qs


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

    # --- Estructura: unidad organizativa, departamento y cargo ---
    #
    # Los tres admiten VARIOS valores (`?unidad=3&unidad=7`), porque la pregunta
    # habitual no es «cómo va esta unidad» sino «cómo van estas dos».
    #
    # La unidad se EXPANDE a sus subunidades: una Unidad Principal no tiene
    # cargos propios —todo cuelga de sus hijas—, así que sin expandir, filtrar
    # por una principal devolvería un listado vacío. Mismo criterio que el
    # Dashboard, Informes RRHH e Informe Inteligente.
    # `expandir()` descarta lo que no sea un id, asi que se comprueba el
    # resultado y no el parametro: con `?unidad=basura` no queda ningun id, y
    # filtrar por una lista vacia dejaria el listado en blanco en vez de
    # ignorar el filtro.
    unidades = expandir([v for v in request.GET.getlist('unidad') if v])
    if unidades:
        qs = qs.filter(cargo__departamento__unidad_organizativa_id__in=unidades)

    departamentos = [v for v in request.GET.getlist('departamento') if v.isdigit()]
    if departamentos:
        qs = qs.filter(cargo__departamento_id__in=departamentos)

    # Por el NOMENCLADOR de cargo, no por la fila de plantilla: «Especialista B»
    # existe una vez en cada departamento, y quien filtra por un cargo quiere
    # verlos todos, no el de un departamento concreto.
    cargos = [v for v in request.GET.getlist('cargo') if v.isdigit()]
    if cargos:
        qs = qs.filter(cargo__ncargo_id__in=cargos)

    return qs
