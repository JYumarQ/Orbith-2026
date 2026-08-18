"""Filtros del listado de Solicitudes.

Espejo de `notificaciones/filtros.py` y `subsanacion/filtros.py`: mismo helper para
parámetros repetidos en la URL, mismo criterio de descartar en silencio los valores no
reconocidos (un enlace guardado con un filtro que ya no existe debe seguir mostrando el
listado, no fallar) y mismas claves de contexto, para que las plantillas se parezcan
entre módulos.

El **estado no es un `<select>`**: son las tres pestañas que pidió RRHH. Un desplegable
de estado además de la pestaña permitiría combinaciones que no devuelven nada («pestaña
Aprobadas, filtro Rechazadas») y obligaría al usuario a mirar en dos sitios para saber
qué está viendo.
"""

from django.db.models import Q

from solicitudes.models import EstadoSolicitud, Solicitud
from solicitudes.operaciones import opciones_de_tipo
from solicitudes.permisos import es_administrador

#: Pestañas del listado -> estados que agrupan. «En Espera» incluye las que un
#: Administrador tiene abiertas en ese momento (`EN_REVISION`): siguen sin decidirse, y
#: sacarlas de la pestaña las haría desaparecer de la vista justo mientras se trabajan.
PESTANAS = {
    'espera': EstadoSolicitud.pendientes(),
    'aprobadas': [EstadoSolicitud.APROBADA],
    'rechazadas': [EstadoSolicitud.RECHAZADA],
}

PESTANA_POR_DEFECTO = 'espera'


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


def solicitudes_visibles(usuario):
    """Base del listado: el Administrador ve todas, el Moderador solo las suyas.

    Es el único punto donde se decide el alcance. Cualquier vista que liste solicitudes
    parte de aquí, para que no pueda existir una pantalla que se salte la regla.
    """
    consulta = Solicitud.objects.select_related(
        'solicitante', 'revisor', 'decidida_por', 'unidad', 'content_type')
    if es_administrador(usuario):
        return consulta
    return consulta.filter(solicitante=usuario)


def contar_pendientes(usuario):
    """Solicitudes en espera/en revisión visibles para `usuario`, para el badge de
    "Solicitudes" en `sidebar.html`. Mismo alcance que el listado: reutiliza
    `solicitudes_visibles`, que es el único punto donde se decide qué puede ver cada rol.
    """
    return solicitudes_visibles(usuario).filter(estado__in=EstadoSolicitud.pendientes()).count()


def opciones_de_filtro(usuario):
    """Opciones de los desplegables, derivadas de los datos que existen de verdad.

    Se calculan sobre lo visible para el usuario y no sobre el catálogo completo: ofrecer
    un moderador o una unidad que no aparece en ninguna fila solo genera búsquedas vacías.
    """
    base = solicitudes_visibles(usuario)

    tipos_presentes = set(base.values_list('operacion', flat=True).distinct())
    opciones = {
        'tipos': [(clave, etiqueta) for clave, etiqueta in opciones_de_tipo()
                  if clave in tipos_presentes],
        'unidades': [],
        'moderadores': [],
    }

    # Un Moderador solo ve sus propias solicitudes, así que filtrar por moderador no le
    # aporta nada; el filtro por unidad tampoco, porque todas serán de las suyas.
    if es_administrador(usuario):
        from strorganizativa.models import UnidadOrganizativa
        from usuarios.models import CustomUser

        unidades_presentes = base.values_list('unidad', flat=True).distinct()
        opciones['unidades'] = [
            (unidad.pk, unidad.descripcion) for unidad in
            UnidadOrganizativa.objects.filter(pk__in=unidades_presentes).order_by('descripcion')
        ]
        moderadores_presentes = base.values_list('solicitante', flat=True).distinct()
        opciones['moderadores'] = [
            (persona.pk, persona.get_full_name() or persona.username) for persona in
            CustomUser.objects.filter(pk__in=moderadores_presentes).order_by('username')
        ]

    return opciones


def filtrar_solicitudes(request, usuario):
    """Devuelve `(queryset, contexto_de_filtros)` según la pestaña y los filtros de la URL."""
    pestana = request.GET.get('tab', PESTANA_POR_DEFECTO)
    if pestana not in PESTANAS:
        pestana = PESTANA_POR_DEFECTO

    busqueda = (request.GET.get('q') or '').strip()
    tipos = _lista_de(request, 'tipo')
    es_admin = es_administrador(usuario)
    unidades = _lista_de(request, 'unidad', convertir=int) if es_admin else []
    moderadores = _lista_de(request, 'moderador', convertir=int) if es_admin else []
    desde = (request.GET.get('desde') or '').strip()
    hasta = (request.GET.get('hasta') or '').strip()

    consulta = solicitudes_visibles(usuario).filter(estado__in=PESTANAS[pestana])

    if busqueda:
        # Se busca sobre campos propios de la solicitud, sin resolver la
        # GenericForeignKey: `descriptor` y `solicitante_nombre` están congelados justo
        # para que esto funcione incluso cuando el registro afectado ya no existe.
        consulta = consulta.filter(
            Q(descriptor__icontains=busqueda)
            | Q(motivo__icontains=busqueda)
            | Q(solicitante_nombre__icontains=busqueda))
    if tipos:
        consulta = consulta.filter(operacion__in=tipos)
    if unidades:
        consulta = consulta.filter(unidad_id__in=unidades)
    if moderadores:
        consulta = consulta.filter(solicitante_id__in=moderadores)
    # Fechas inválidas se ignoran, igual que el resto de filtros: `__date__gte` con una
    # cadena mal formada lanzaría, y un enlace viejo no debe romper el listado.
    if desde:
        try:
            consulta = consulta.filter(created_at__date__gte=desde)
        except (ValueError, TypeError):
            desde = ''
    if hasta:
        try:
            consulta = consulta.filter(created_at__date__lte=hasta)
        except (ValueError, TypeError):
            hasta = ''

    contexto = {
        'tab_activa': pestana,
        'q': busqueda,
        'tipos_actuales': tipos,
        'unidades_actuales': unidades,
        'moderadores_actuales': moderadores,
        'desde': desde,
        'hasta': hasta,
        'opciones_filtro': opciones_de_filtro(usuario),
        'hay_filtros': bool(busqueda or tipos or unidades or moderadores or desde or hasta),
    }
    return consulta, contexto


#: Nombre visible de cada pestaña. Separado de `PESTANAS` para no mezclar el mapeo
#: funcional (pestaña -> estados) con el texto que ve el usuario.
ETIQUETAS_PESTANA = {
    'espera': 'En Espera',
    'aprobadas': 'Aprobadas',
    'rechazadas': 'Rechazadas',
}


def pestanas_con_contadores(usuario):
    """`[{'clave', 'etiqueta', 'total'}]` listo para pintar.

    Se resuelve aquí y no en la plantilla porque Django no permite indexar un diccionario
    por una variable, y crear un filtro de plantilla solo para eso añadiría un archivo y
    un import a cambio de nada.
    """
    base = solicitudes_visibles(usuario)
    return [
        {
            'clave': clave,
            'etiqueta': ETIQUETAS_PESTANA[clave],
            'total': base.filter(estado__in=estados).count(),
        }
        for clave, estados in PESTANAS.items()
    ]
