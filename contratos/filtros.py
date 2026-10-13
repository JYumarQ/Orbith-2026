"""Filtros del listado de Contratos.

`aplicar_filtros()` es el único punto donde se traduce la querystring a
condiciones de queryset — antes vivía duplicado (a medias) solo dentro de
`search_contratos`, así que la carga inicial de `ContratoListView` (sin pasar
por la búsqueda AJAX) nunca respetaba un `?raza=NE` en la URL. Ahora ambas
vistas llaman a la misma función, mismo patrón que `cierres/filtros.py` /
`subsanacion/filtros.py`.
"""

from datetime import date

from django.db.models import Exists, OuterRef, Q

from strorganizativa.jerarquia import expandir

from usuarios.alcance import tiene_alcance_acotado

from .permisos import es_administrador  # noqa: F401  (lo usan otras vistas del módulo)


def contratos_visibles(usuario):
    """Base del listado: alcance por rol, único punto donde se decide.

    El Administrador ve todos los contratos. El Moderador solo ve los contratos
    cuyo cargo cuelga de una de sus Unidades Organizativas asignadas
    (`CustomUser.unidades`), mismo criterio que
    `cierres/filtros.py::unidades_visibles()` y
    `solicitudes/filtros.py::solicitudes_visibles()`.

    El Observador ve todos los contratos mientras no tenga unidades asignadas
    (el listado es informativo, no expone acciones de edición, y así lo pidió
    RRHH). En cuanto el Administrador le asigna unidades, se filtra exactamente
    igual que un Moderador. La regla la decide `usuarios.alcance`.
    """
    from .models import CAlta

    qs = CAlta.objects.all()
    if tiene_alcance_acotado(usuario):
        return qs.filter(
            cargo__departamento__unidad_organizativa__in=usuario.unidades.all())
    return qs


def fecha_de(request, parametro):
    """La fecha AAAA-MM-DD de `?parametro=`, o None si falta o no es válida (una
    fecha mal escrita en la URL se ignora, igual que cualquier otro filtro)."""
    try:
        return date.fromisoformat((request.GET.get(parametro) or '').strip())
    except ValueError:
        return None


def anotar_recontratado(qs):
    """Marca cada contrato con `es_recontratado`: la persona ya tuvo una baja antes
    (mientras un contrato está vivo, toda baja suya es anterior). La lista de
    Contratos lo señala con una línea verde fina (decisión de RRHH del 12-10-2026)."""
    from .models import CBaja
    return qs.annotate(es_recontratado=Exists(
        CBaja.objects.filter(aspirante_id=OuterRef('aspirante_id'))))


def altas_que_causaron_baja(request):
    """Aviso de Contratos al filtrar por fecha de alta: quien entró en ese rango y
    ya se fue (su contrato es hoy una `CBaja`, así que no puede salir en la tabla).
    Mismo alcance por rol y mismos filtros de la lista, salvo los que solo tienen
    sentido para un contrato vivo. None si no se filtra por fecha de alta."""
    from .models import CBaja

    if not (fecha_de(request, 'alta_desde') or fecha_de(request, 'alta_hasta')):
        return None
    qs = CBaja.objects.all()
    if tiene_alcance_acotado(request.user):
        qs = qs.filter(cargo__departamento__unidad_organizativa__in=request.user.unidades.all())
    return aplicar_filtros(request, qs, solo_comunes=True)


def aplicar_filtros(request, qs, solo_comunes=False):
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

    # Fecha de alta del contrato, desde y/o hasta (ambas incluidas). La Dashboard
    # llega con «desde» relleno al pulsar «Nuevas Altas (últimos 30 días)».
    alta_desde = fecha_de(request, 'alta_desde')
    alta_hasta = fecha_de(request, 'alta_hasta')
    if alta_desde:
        qs = qs.filter(fecha_alta__gte=alta_desde)
    if alta_hasta:
        qs = qs.filter(fecha_alta__lte=alta_hasta)

    if not solo_comunes:
        qs = _filtrar_recontratados(request, qs)

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


def _filtrar_recontratados(request, qs):
    """Filtros de contrato vivo (decisión de RRHH del 12-10-2026):

    * `recontratado=si|no`: la persona tuvo, o no, una baja antes de este contrato.
    * `baja_anterior_desde/hasta`: recontratados cuya baja cayó en esas fechas. Es
      a donde lleva el aviso de la lista de Bajas («fueron recontratadas»).
    * `jubilado=si|no`: la casilla «Jubilado Recontratado» del contrato.
    """
    from .models import CBaja

    recontratado = request.GET.get('recontratado')
    desde = fecha_de(request, 'baja_anterior_desde')
    hasta = fecha_de(request, 'baja_anterior_hasta')
    if recontratado in ('si', 'no') or desde or hasta:
        bajas = CBaja.objects.filter(aspirante_id=OuterRef('aspirante_id'))
        if desde:
            bajas = bajas.filter(fecha_baja__gte=desde)
        if hasta:
            bajas = bajas.filter(fecha_baja__lte=hasta)
        if recontratado == 'no' and not (desde or hasta):
            qs = qs.exclude(Exists(bajas))
        else:
            qs = qs.filter(Exists(bajas))

    jubilado = request.GET.get('jubilado')
    if jubilado in ('si', 'no'):
        qs = qs.filter(jubilado_recontratado=(jubilado == 'si'))
    return qs
