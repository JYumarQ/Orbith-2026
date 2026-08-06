"""Filtros de la pestaña Advertencias.

Espejo deliberado de `subsanacion/filtros.py` (mismo patrón: parámetros repetidos en
la URL, descartados en silencio si no son válidos, para que un enlace guardado con un
filtro que ya no existe siga mostrando el listado en vez de fallar).
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from subsanacion.constantes import CLAVES_MODULOS, CRITICIDADES, MODULOS_CHOICES
from subsanacion.reglas import obtener_reglas

from .models import Notificacion


def _lista_de(request, parametro, validos=None, convertir=None):
    """Lee un parámetro repetido de la URL y descarta los valores no reconocidos."""
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


def _catalogo_reglas():
    """`{codigo: nombre}` de TODAS las reglas conocidas, activas o no — una regla
    retirada puede seguir teniendo notificaciones históricas, que deben poder
    filtrarse/mostrar su nombre igual que las de una regla vigente."""
    return {regla.codigo: regla.nombre for regla in obtener_reglas()}


def _codigos_del_modulo(modulos):
    """`Notificacion` no tiene columna de módulo — se resuelve indirectamente
    agrupando `codigo_regla` por el `modulo` de la regla que lo emitió."""
    return {regla.codigo for regla in obtener_reglas() if regla.modulo in modulos}


def opciones_de_filtro(usuario):
    """Las opciones para pintar los `<select>` del panel, derivadas de datos reales
    (no de un catálogo fijo) para no ofrecer filtros que no devolverían nada."""
    catalogo_reglas = _catalogo_reglas()
    base = Notificacion.objects.filter(tipo=Notificacion.Tipo.ALERTA)

    codigos_presentes = set(base.values_list('codigo_regla', flat=True).distinct())
    modulos_presentes = {
        regla.modulo for regla in obtener_reglas() if regla.codigo in codigos_presentes}

    content_types_presentes = ContentType.objects.filter(
        pk__in=base.values_list('content_type', flat=True).distinct())
    modelos = [
        (ct.pk, ct.model_class()._meta.verbose_name.title())
        for ct in content_types_presentes if ct.model_class() is not None
    ]

    opciones = {
        'modulos': [(clave, etiqueta) for clave, etiqueta in MODULOS_CHOICES
                    if clave in modulos_presentes],
        'reglas': sorted(
            ((codigo, catalogo_reglas.get(codigo, codigo)) for codigo in codigos_presentes if codigo),
            key=lambda par: par[1]),
        'severidades': CRITICIDADES,
        'unidades': [],
        'modelos': modelos,
        'destinatarios': [],
    }

    if usuario.es_admin:
        from strorganizativa.models import UnidadOrganizativa
        from usuarios.models import CustomUser

        unidades_presentes = base.values_list('unidad', flat=True).distinct()
        opciones['unidades'] = [
            (u.pk, u.descripcion) for u in
            UnidadOrganizativa.objects.filter(pk__in=unidades_presentes).order_by('descripcion')
        ]
        destinatarios_presentes = base.values_list('destinatario', flat=True).distinct()
        opciones['destinatarios'] = [
            (u.pk, u.username) for u in
            CustomUser.objects.filter(pk__in=destinatarios_presentes).order_by('username')
        ]

    return opciones


def _deduplicar(queryset):
    """Colapsa notificaciones que son el MISMO hallazgo notificado a varios
    destinatarios — misma clave natural salvo `destinatario`
    (`content_type`+`object_id`+`codigo_regla`+`clave_extra`, igual que usa
    `_registrar_notificacion_de_hallazgo` para deduplicar al escribir) — en una sola
    fila representativa por grupo, en el mismo orden en que ya vienen (el `queryset`
    respeta `Meta.ordering`: severidad primero, luego fecha). El listado general
    mostraba el mismo problema una vez POR destinatario; el panel de "otras
    advertencias del registro" (`core.mixins.AdvertenciasDelRegistroMixin`) ya
    deduplicaba así para un solo registro — aquí es el mismo criterio aplicado a todo
    el listado.

    Anota `.destinatarios_agrupados` (entero) en la fila representativa: cuántas
    notificaciones colapsó, para que la plantilla pueda avisar cuando "Descartar"
    (que actúa sobre el grupo completo, no solo sobre esta fila) afecta a más de una
    persona.
    """
    grupos = {}  # clave -> [representante, contador]
    orden = []
    for notificacion in queryset:
        clave = (notificacion.content_type_id, notificacion.object_id,
                  notificacion.codigo_regla, notificacion.clave_extra)
        if clave not in grupos:
            grupos[clave] = [notificacion, 0]
            orden.append(clave)
        grupos[clave][1] += 1

    resultado = []
    for clave in orden:
        representante, contador = grupos[clave]
        representante.destinatarios_agrupados = contador
        resultado.append(representante)
    return resultado


#: Subpestañas de Advertencias (`?tab=advertencias&sub=...`), por estado — no se
#: mezclan en una sola lista a propósito: activas es la bandeja de trabajo real,
#: resueltas/descartadas son consulta histórica de 60 días que no debe estorbar
#: visualmente (ver `notificaciones/limpieza.py` para la purga automática). Sustituye
#: al viejo filtro múltiple "Estado" del embudo, que permitía mezclar los tres.
SUBTABS_ADVERTENCIAS = {
    'activas': Notificacion.Estado.ACTIVA,
    'resueltas': Notificacion.Estado.RESUELTA,
    'descartadas': Notificacion.Estado.DESCARTADA,
}


def filtrar_advertencias(request, usuario):
    """Devuelve `(lista_deduplicada, contexto_de_filtros)` sobre las alertas visibles
    para `usuario`, según la subpestaña (`sub`) y los parámetros de filtro de la URL.

    Antes del punto de retorno partía de un queryset de `_notificaciones_visibles(usuario)`
    (el propio módulo lo importa de forma local para evitar un import circular:
    `views.py` ya importa `filtros.py`); se materializa y deduplica al final
    (`_deduplicar`), así que lo que devuelve ya no es un queryset perezoso — a esta
    escala de datos (cientos de filas, no millones) no compensa la complejidad de
    deduplicar en SQL con `DISTINCT ON`, que además obligaría a ordenar por la clave
    de deduplicación en vez de por severidad/fecha.
    """
    from .views import _notificaciones_visibles

    sub = request.GET.get('sub', 'activas')
    if sub not in SUBTABS_ADVERTENCIAS:
        sub = 'activas'

    busqueda = (request.GET.get('q') or '').strip()
    modulos = _lista_de(request, 'modulo', CLAVES_MODULOS)
    codigos_regla = _lista_de(request, 'regla')
    severidades = _lista_de(request, 'severidad', dict(CRITICIDADES), int)
    unidades = _lista_de(request, 'unidad', convertir=int)
    modelos = _lista_de(request, 'modelo', convertir=int)
    destinatarios = _lista_de(request, 'destinatario', convertir=int) if usuario.es_admin else []

    consulta = (_notificaciones_visibles(usuario)
                .filter(tipo=Notificacion.Tipo.ALERTA, estado=SUBTABS_ADVERTENCIAS[sub])
                .select_related('content_type'))

    if busqueda:
        # Mismo patrón que `subsanacion/filtros.py::filtrar_hallazgos`: se busca sobre
        # los campos propios de la notificación, sin resolver la GenericForeignKey.
        consulta = consulta.filter(
            Q(titulo__icontains=busqueda)
            | Q(mensaje__icontains=busqueda)
            | Q(codigo_regla__icontains=busqueda))
    if codigos_regla:
        consulta = consulta.filter(codigo_regla__in=codigos_regla)
    if modulos:
        consulta = consulta.filter(codigo_regla__in=_codigos_del_modulo(modulos))
    if severidades:
        consulta = consulta.filter(severidad__in=severidades)
    if unidades:
        consulta = consulta.filter(unidad_id__in=unidades)
    if modelos:
        consulta = consulta.filter(content_type_id__in=modelos)
    if destinatarios:
        consulta = consulta.filter(destinatario_id__in=destinatarios)

    contexto = {
        'sub_activa': sub,
        'q': busqueda,
        'modulos_actuales': modulos,
        'reglas_actuales': codigos_regla,
        'severidades_actuales': severidades,
        'unidades_actuales': unidades,
        'modelos_actuales': modelos,
        'destinatarios_actuales': destinatarios,
        'opciones_filtro': opciones_de_filtro(usuario),
        'hay_filtros': bool(
            busqueda or modulos or codigos_regla or severidades
            or unidades or modelos or destinatarios),
    }
    return _deduplicar(consulta), contexto


def filtrar_recordatorios(request, usuario, origen):
    """Devuelve `(recordatorios, contexto_de_filtros)` de Recordatorios ACTIVA del
    `origen` (SISTEMA/ADMINISTRACION) de la subpestaña actual, visibles para `usuario`.

    Sin embudo (a diferencia de Advertencias): Recordatorios no tiene tantas
    dimensiones de filtro como para justificarlo — solo búsqueda libre (`q`) y
    prioridad, ambas como controles siempre visibles en la plantilla.
    """
    from .views import _color_prioridad, _notificaciones_visibles

    busqueda = (request.GET.get('q') or '').strip()
    prioridad_cruda = (request.GET.get('prioridad') or '').strip()
    # Se descarta en silencio si no es una clave válida — mismo criterio que `_lista_de`
    # con el resto de filtros: un enlace guardado con un valor que ya no existe debe
    # seguir mostrando el listado (sin ese filtro), no fallar ni contarlo en `hay_filtros`.
    prioridad = prioridad_cruda if prioridad_cruda in {'verde', 'naranja', 'amarillo', 'rojo'} else ''

    consulta = (_notificaciones_visibles(usuario)
                .filter(tipo=Notificacion.Tipo.RECORDATORIO, origen=origen,
                        estado=Notificacion.Estado.ACTIVA)
                .select_related('content_type')
                .order_by('fecha_objetivo'))

    if busqueda:
        consulta = consulta.filter(
            Q(titulo__icontains=busqueda) | Q(mensaje__icontains=busqueda))

    if prioridad:
        # La prioridad no es una columna: se calcula al vuelo desde `fecha_objetivo`
        # (`_color_prioridad`). A esta escala de datos (decenas de recordatorios, no
        # miles) filtrar en Python sobre la lista ya materializada es más simple que
        # duplicar los mismos rangos de fecha como una expresión ORM aparte.
        consulta = [n for n in consulta if _color_prioridad(n.fecha_objetivo)['clave'] == prioridad]

    contexto = {
        'q': busqueda,
        'prioridad_actual': prioridad,
        'hay_filtros': bool(busqueda or prioridad),
    }
    return consulta, contexto
