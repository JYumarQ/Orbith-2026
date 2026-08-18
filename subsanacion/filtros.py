"""Filtros y búsqueda del listado de hallazgos.

Vive en su propio módulo para que la vista HTML y las exportaciones a Excel y PDF de
la Fase 2 usen exactamente la MISMA función: es la única forma de garantizar que lo
que el usuario exporta es lo que está viendo en pantalla.
"""

from django.db.models import Q

from .constantes import CLAVES_MODULOS, ETIQUETA_CRITICIDAD, MODULO_EXTRAS
from .models import Hallazgo
from .permisos import es_administrador, unidades_visibles


def _lista_de(request, parametro, validos=None, convertir=None):
    """Lee un parámetro repetido de la URL y descarta los valores no reconocidos.

    Descartar en silencio en vez de fallar es deliberado: un enlace guardado en
    favoritos con un filtro que ya no existe debe seguir mostrando el listado, no un
    error.
    """
    valores = []
    for crudo in request.GET.getlist(parametro):
        crudo = (crudo or '').strip()
        if not crudo:
            continue
        if convertir is not None:
            try:
                crudo = convertir(crudo)
            except (TypeError, ValueError):
                continue
        if validos is not None and crudo not in validos:
            continue
        valores.append(crudo)
    return valores


def filtrar_hallazgos(request):
    """Devuelve `(queryset, filtros_aplicados)` según los parámetros de la URL.

    Por defecto muestra los hallazgos VIGENTES y ABIERTOS (pendientes o en revisión),
    para que la bandeja enseñe trabajo real y no histórico ya cerrado.
    """
    parametros = request.GET

    criticidades = _lista_de(request, 'criticidad', ETIQUETA_CRITICIDAD, int)
    modulos = _lista_de(request, 'modulo', CLAVES_MODULOS)
    estados = _lista_de(request, 'estado', dict(Hallazgo.ESTADOS))
    busqueda = (parametros.get('q') or '').strip()

    solo_criticos = parametros.get('solo_criticos') in ('1', 'on', 'true')
    incluir_archivados = parametros.get('archivados') in ('1', 'on', 'true')

    # Sin `select_related` de la GenericForeignKey a propósito: el listado no resuelve
    # el objeto apuntado, así que no dispara consultas por fila y tolera que el
    # registro original haya sido borrado. `content_type` sí se precarga porque el
    # botón «Abrir registro» lo necesita para construir la url.
    consulta = Hallazgo.objects.select_related('content_type')

    # Alcance por rol (`subsanacion/permisos.py`): un Moderador solo ve hallazgos de
    # sus propias Unidades Organizativas. Un hallazgo SIN unidad (algunos globales,
    # de Configuración o de Usuarios) queda fuera de su alcance — mismo criterio que
    # ya usa `notificaciones/escaneo.py` para repartir avisos: sin unidad, es cosa
    # del Administrador. Se aplica ANTES que cualquier otro filtro para que ninguno
    # de los de abajo pueda ensanchar el alcance por error.
    if not es_administrador(request.user):
        uo_ids_visibles = unidades_visibles(request.user).values_list('pk', flat=True)
        consulta = consulta.filter(unidad_organizativa_id__in=uo_ids_visibles)

    if not incluir_archivados:
        consulta = consulta.filter(vigente=True)

    if estados:
        consulta = consulta.filter(estado__in=estados)
    else:
        consulta = consulta.filter(estado__in=Hallazgo.ESTADOS_ABIERTOS)

    if solo_criticos:
        from .constantes import CRITICIDAD_CRITICA
        consulta = consulta.filter(criticidad=CRITICIDAD_CRITICA)
    elif criticidades:
        consulta = consulta.filter(criticidad__in=criticidades)

    if modulos:
        consulta = consulta.filter(modulo__in=modulos)
    else:
        # «Todas» no incluye Extras: son datos complementarios (ver
        # `reglas/extras.py`), no problemas de calidad, y mezclarlos aquí es ruido.
        # Solo aparecen si el usuario los pide explícitamente filtrando por la
        # categoría Extras (mismo criterio que ya excluye Extras del índice de
        # salud en `servicios.finalizar_ejecucion()`).
        consulta = consulta.exclude(modulo=MODULO_EXTRAS)

    if busqueda:
        # La búsqueda NO puede hacer JOIN al registro original (el listado no resuelve
        # la GenericForeignKey), así que se busca sobre los campos denormalizados. Por
        # eso cada regla tiene la obligación de escribir el nombre, el carnet y el
        # expediente en el título: es lo que hace encontrable el hallazgo.
        # `datos__icontains` funciona porque PostgreSQL puede convertir el JSONB a texto.
        #
        # El título lo arma `formato.py::referencia_trabajador()` como «Apellidos,
        # Nombre (doc)» — apellidos primero. Un solo `icontains` con la frase completa
        # exige que el usuario la escriba EN ESE ORDEN EXACTO; si busca «Nombre
        # Apellido» (el orden natural en que la gente escribe un nombre) no encuentra
        # nada aunque el hallazgo exista. Se busca palabra por palabra en su lugar:
        # cada palabra escrita tiene que aparecer en ALGUNO de los campos (da igual en
        # cuál ni en qué orden), y se exigen TODAS las palabras (un `.filter()` por
        # palabra, que Django encadena con AND). Así «Fvdb Fdbfdb» y «Fdbfdb Fvdb»
        # encuentran el mismo hallazgo.
        for palabra in busqueda.split():
            consulta = consulta.filter(
                Q(titulo__icontains=palabra)
                | Q(detalle__icontains=palabra)
                | Q(datos__icontains=palabra)
                | Q(codigo_regla__icontains=palabra))

    filtros = {
        'q': busqueda,
        'criticidades': criticidades,
        'modulos': modulos,
        'estados': estados,
        'solo_criticos': solo_criticos,
        'archivados': incluir_archivados,
        'hay_filtros': bool(
            busqueda or criticidades or modulos or estados
            or solo_criticos or incluir_archivados),
    }
    return consulta, filtros


def querystring_sin_pagina(request):
    """La querystring actual sin `pagina`, para construir los enlaces de paginación."""
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    codificada = parametros.urlencode()
    return f'&{codificada}' if codificada else ''


def querystring_completa(request):
    """La querystring de filtros y búsqueda, sin paginación, para los enlaces de descarga.

    Igual que la anterior pero sin el `&` inicial, porque aquí se pega detrás de un `?`.
    Es lo que hace que el Excel y el PDF contengan exactamente lo que hay en pantalla.
    """
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    return parametros.urlencode()
