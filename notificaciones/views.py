from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from strorganizativa.models import UnidadOrganizativa
from subsanacion.enlaces import construir_enlace
from usuarios.decorators import admin_required, gestion_required, write_required

from .escaneo import escanear_para_usuario
from .forms import RecordatorioManualForm
from .models import Notificacion
from .recordatorios import generar_recordatorios



def _notificaciones_visibles(usuario):
    """Notificaciones que PERTENECEN al usuario, leídas o no.

    Es la base de pertenencia, sin filtrar por `leido`: marcar como leída una
    notificación ya leída (un doble clic, o abrirla desde dos pestañas) no debe dar
    404. `_notificaciones_del_usuario()` la usa añadiendo el filtro de bandeja.

    `es_admin` ve TODO sin excepción: antes solo veía lo de su propia unidad o lo
    dirigido a él directamente, igual que un moderador — un admin sin unidades
    asignadas (el caso más común: administra todo, no una unidad concreta) podía no
    ver notificaciones que su rol sugiere que debería poder ver.

    Excepción: los avisos del Ranking Mensual (`ranking.avisos.CODIGO_AVISO`) son
    personales. El Administrador solo ve los suyos: si viera los de todos, al
    abrirlos se marcarían como leídos para su dueño sin que este los viera.
    """
    if usuario.es_admin:
        from ranking.avisos import CODIGO_AVISO
        return Notificacion.objects.exclude(
            Q(codigo_regla=CODIGO_AVISO) & ~Q(destinatario=usuario))
    unidades_usuario = usuario.unidades.all()
    return Notificacion.objects.filter(
        Q(unidad__in=unidades_usuario) | Q(destinatario=usuario))


def _bandeja(usuario):
    """La bandeja PERSONAL (decisión de RRHH del 25-10-2026): solo las copias que son
    de este usuario.

    Cada aviso se reparte en una copia por destinatario (el moderador de la unidad y
    cada administrador). Antes el Administrador veía las copias de todos: cada aviso
    salía repetido, su contador de «sin leer» sumaba lo de los demás y, al abrir o
    «Marcar todas como leídas», marcaba también las de los moderadores sin que las
    hubieran visto. Lo que tienen pendiente los moderadores lo ve en la pestaña
    «Supervisión», de solo lectura.

    Las filas sin destinatario (datos anteriores al reparto) se siguen viendo por
    unidad, como antes; el Administrador, todas.
    """
    sin_destinatario = Q(destinatario__isnull=True)
    if not usuario.es_admin:
        sin_destinatario &= Q(unidad__in=usuario.unidades.all())
    return Notificacion.objects.filter(Q(destinatario=usuario) | sin_destinatario)


def _notificaciones_del_usuario(usuario):
    """La bandeja: lo que aún no se ha leído de las copias del usuario."""
    return _bandeja(usuario).filter(leido=False)


def copia_propia(usuario, notificacion):
    """La copia de `usuario` del mismo aviso que `notificacion` (o ella misma si ya
    es suya; None si no le llegó). Advertencias y Recordatorios agrupan las copias y
    enseñan una sola fila: lo que se marque como leído es siempre la copia propia."""
    if notificacion.destinatario_id in (None, usuario.pk):
        return notificacion
    return (_bandeja(usuario)
            .filter(content_type_id=notificacion.content_type_id, object_id=notificacion.object_id,
                    codigo_regla=notificacion.codigo_regla, clave_extra=notificacion.clave_extra,
                    tipo=notificacion.tipo, titulo=notificacion.titulo)
            .order_by('-fecha_creado').first())


def _serializar(n):
    return {
        'id': n.pk,
        'titulo': n.titulo,
        'mensaje': n.mensaje,
        'fecha': n.fecha_creado.strftime('%Y-%m-%d %H:%M'),
        'tipo': n.tipo,
        'severidad': n.severidad,
        'estado': n.estado,
        # La campana abre la ventana del Ranking con los avisos de cierre de mes.
        'codigo_regla': n.codigo_regla,
    }


# Create your views here.
def notificaciones_json(request):
    notificaciones = _notificaciones_del_usuario(request.user)
    data = [_serializar(n) for n in notificaciones]
    return JsonResponse({'notificaciones': data})

# notificaciones/views.py
def ultimas_notificaciones(request):
    # Sin `.order_by()` explícito: se respeta `Meta.ordering` del modelo
    # (`['severidad', '-fecha_creado']`), para que una alerta crítica no quede tapada
    # por un evento reciente sin gravedad.
    # Excepción: los avisos del Ranking Mensual van primero. Llegan una vez al mes y,
    # sin esto, quedarían detrás de cualquier advertencia (hay usuarios con cientos)
    # y no se verían nunca en la campana.
    from django.db.models import Case, IntegerField, Value, When

    from ranking.avisos import CODIGO_AVISO
    notificaciones = (_notificaciones_del_usuario(request.user)
                      .annotate(_ranking_primero=Case(When(codigo_regla=CODIGO_AVISO, then=Value(0)),
                                                      default=Value(1), output_field=IntegerField()))
                      .order_by('_ranking_primero', *Notificacion._meta.ordering)[:5])
    data = [_serializar(n) for n in notificaciones]
    return JsonResponse({'notificaciones': data})


@login_required
@require_POST
def marcar_leida(request, pk):
    """Marca UNA notificación como leída, y solo la copia de quien la abre: nunca la
    de otra persona (25-10-2026). Nunca toca `estado`."""
    notificacion = copia_propia(request.user,
                                get_object_or_404(_notificaciones_visibles(request.user), pk=pk))
    if notificacion is not None and not notificacion.leido:
        notificacion.leido = True
        notificacion.save(update_fields=['leido'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def marcar_todas_leidas(request):
    """Marca como leídas todas las notificaciones pendientes del usuario."""
    actualizadas = _notificaciones_del_usuario(request.user).update(leido=True)
    return JsonResponse({'ok': True, 'actualizadas': actualizadas})


def _con_enlace(notificacion, next_url=None, origen_label=None, usuario=None):
    """Anota `.enlace` (o `None`) reutilizando `subsanacion.enlaces.construir_enlace`,
    una utilidad hoja que solo resuelve una URL a partir de `content_type`/
    `object_id` — no toca `Hallazgo`, `EjecucionAnalisis` ni ninguna otra tabla de
    Subsanación. `next_url` (la URL completa de la pestaña actual, con sus filtros y
    paginación) es lo que permite que "Corregir" vuelva exactamente aquí al guardar;
    `origen_label` es lo que verá el usuario en el aviso ("Está corrigiendo un registro
    desde Advertencias...")."""
    ct = notificacion.content_type
    modelo = ct.model_class()
    etiqueta = f'{ct.app_label}.{modelo.__name__}' if modelo else None
    # REC-CONTRATO (contrato próximo a vencer) y REC-ANTIGUEDAD (nuevo año de
    # antigüedad próximo) no se corrigen editando el contrato: la acción real es un
    # Movimiento de Nómina. Únicos códigos que se desvían del destino por defecto de
    # `ENLACES_POR_MODELO['contratos.CAlta']` — REC-CHOFER y las Advertencias de
    # Subsanación sobre CAlta siguen abriendo «Editar contrato».
    forzar_url = ('movimiento_contrato'
                   if notificacion.codigo_regla in ('REC-CONTRATO', 'REC-ANTIGUEDAD') else None)
    # Advertencias de Subsanación cuya regla lleva a otra pantalla (MOV-015 → editor
    # del histórico, solo para el Administrador).
    texto_boton = None
    if forzar_url is None:
        from subsanacion.enlaces import destino_de_regla
        from subsanacion.reglas import obtener_regla
        forzar_url, texto_boton = destino_de_regla(obtener_regla(notificacion.codigo_regla), usuario)
    notificacion.enlace = construir_enlace(
        etiqueta, notificacion.object_id, forzar_url=forzar_url,
        next_url=next_url, origen_label=origen_label, usuario=usuario, etiqueta=texto_boton
    ) if etiqueta else None
    return notificacion


TABS = ('notificaciones', 'advertencias', 'recordatorios', 'supervision')
#: «Supervisión» (solo Administrador): lo que recibieron los moderadores.
SUBTABS_SUPERVISION = ('pendientes', 'todos')
SUBTABS_RECORDATORIOS = ('sistema', 'administracion')


def _querystring_sin_pagina(request):
    """La querystring actual (pestaña + filtros) sin `pagina`, para que los enlaces de
    paginación no pierdan el resto del contexto. Mismo patrón (y mismo formato, con
    "&" inicial) que `subsanacion/filtros.py::querystring_sin_pagina`, consumido por
    `base/partials/tabla_paginacion_enlaces.html` como `?pagina=N…{{ querystring }}`."""
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    # `filas` lo añade el pie común de la tabla (base/partials/tabla_paginacion_enlaces.html).
    parametros.pop('filas', None)
    codificada = parametros.urlencode()
    return f'&{codificada}' if codificada else ''


def _paginar_con_enlaces(request, queryset, origen_label):
    """Pagina `queryset` y anota `.enlace` solo sobre la página actual (nunca sobre el
    queryset completo, para no pagar un reverse() de más por fila que no se muestra).
    Reutilizado por ambas pestañas: la única diferencia real entre ellas es el
    queryset de partida, no cómo se pagina/enlaza."""
    # Filas por página del usuario, comunes a todas las tablas (core/paginacion.py).
    from core.paginacion import filas_por_pagina
    pagina = Paginator(queryset, filas_por_pagina(request)).get_page(request.GET.get('pagina'))
    for notificacion in pagina:
        _con_enlace(notificacion, next_url=request.get_full_path(), origen_label=origen_label,
                    usuario=request.user)
    return pagina


def _contexto_tab_notificaciones(request):
    """Pestaña «Notificaciones»: solo eventos informativos, sin panel de filtros. Solo
    las copias del usuario: cada aviso una vez."""
    notificaciones = (_bandeja(request.user)
                      .filter(tipo=Notificacion.Tipo.EVENTO)
                      .select_related('content_type'))
    return {
        'notificaciones': _paginar_con_enlaces(request, notificaciones, origen_label='Notificaciones'),
    }


def _contexto_tab_advertencias(request):
    """Pestaña «Advertencias»: solo alertas de integridad, con el panel de filtros."""
    from .filtros import filtrar_advertencias

    notificaciones, filtros_aplicados = filtrar_advertencias(request, request.user)
    contexto = {
        'notificaciones': _paginar_con_enlaces(request, notificaciones, origen_label='Advertencias'),
        'puede_escanear': request.user.es_admin or request.user.es_moderador,
        'mostrar_severidad': True,
    }
    contexto.update(filtros_aplicados)
    return contexto


def _color_prioridad(fecha_objetivo):
    """Color/etiqueta de prioridad de un Recordatorio, calculado al vuelo a partir de
    `fecha_objetivo` — NO es un estado guardado (ver `notificaciones/recordatorios.py`,
    Sección D.2 del diseño): 🟢 ≥60 días, 🟠 16-59, 🟡 1-15, 🔴 hoy o vencido.

    `clave` (verde/naranja/amarillo/rojo/'') es el identificador estable que usa el
    filtro de prioridad (`filtrar_recordatorios`) y los chips de la plantilla —
    `emoji`/`etiqueta` son solo para mostrar, pueden cambiar sin romper el filtro.
    """
    if fecha_objetivo is None:
        return {'emoji': '', 'etiqueta': '', 'dias': None, 'clave': ''}

    dias = (fecha_objetivo - timezone.localdate()).days
    if dias <= 0:
        etiqueta = 'Vencido' if dias < 0 else 'Hoy'
        return {'emoji': '🔴', 'etiqueta': etiqueta, 'dias': dias, 'clave': 'rojo'}
    if dias <= 15:
        return {'emoji': '🟡', 'etiqueta': 'Próximo', 'dias': dias, 'clave': 'amarillo'}
    if dias <= 59:
        return {'emoji': '🟠', 'etiqueta': 'Cercano', 'dias': dias, 'clave': 'naranja'}
    return {'emoji': '🟢', 'etiqueta': 'Lejano', 'dias': dias, 'clave': 'verde'}


def _contexto_tab_recordatorios(request):
    """Pestaña «Recordatorios»: subpestañas Sistema/Administración
    (`?tab=recordatorios&sub=sistema|administracion`, por defecto `sistema`), NUNCA
    mezcladas en una sola lista (decisión ya tomada). Solo ACTIVA: la bandeja de
    Recordatorios, igual que Advertencias, se mantiene enfocada en lo vigente — lo
    RESUELTA se oculta y se purga a los 60 días (`notificaciones/limpieza.py`)."""
    from strorganizativa.models import UnidadOrganizativa

    from .filtros import filtrar_recordatorios

    sub = request.GET.get('sub', 'sistema')
    if sub not in SUBTABS_RECORDATORIOS:
        sub = 'sistema'
    origen = (Notificacion.Origen.SISTEMA if sub == 'sistema'
              else Notificacion.Origen.ADMINISTRACION)

    recordatorios, filtros_aplicados = filtrar_recordatorios(request, request.user, origen)
    pagina = _paginar_con_enlaces(request, recordatorios, origen_label='Recordatorios')
    for recordatorio in pagina:
        recordatorio.prioridad = _color_prioridad(recordatorio.fecha_objetivo)

    contexto = {
        'recordatorios': pagina,
        'sub_activa': sub,
        'unidades_admin': (UnidadOrganizativa.objects.order_by('descripcion')
                            if request.user.es_admin else None),
        'puede_actualizar_recordatorios': request.user.es_admin or request.user.es_moderador,
    }
    contexto.update(filtros_aplicados)
    return contexto


# `gestion_required` y no `login_required`: el panel de Notificaciones queda
# fuera del alcance del Observador (decisión explícita del usuario), tanto en la
# barra lateral como escribiendo la URL. Lo que SÍ conserva es la campana del pie
# de `sidebar.html`, que le sigue entregando sus avisos personales: esa usa
# `notificaciones_json` / `ultimas_notificaciones`, que quedan con `login_required`.
@gestion_required
def lista_notificaciones(request):
    """Bandeja de notificaciones, en pestañas (`?tab=notificaciones|advertencias`).

    Cada pestaña construye en el servidor SOLO su propio contexto — a diferencia del
    patrón de `configuracion`, que precarga las tres pestañas en una sola petición y
    cambia 100% en el navegador. Aquí no conviene: Advertencias tiene filtros y
    paginación propios que no hay que calcular cuando el usuario está viendo
    Notificaciones. Cambiar de pestaña es una navegación real (`?tab=...`), así que la
    URL siempre refleja dónde está el usuario — es lo que permite que "Corregir" vuelva
    exactamente aquí (ver `_con_enlace`/`core.mixins.VolverAlOrigenMixin`).
    """
    tab = request.GET.get('tab', 'notificaciones')
    if tab not in TABS or (tab == 'supervision' and not request.user.es_admin):
        tab = 'notificaciones'

    contexto = {
        'tab_activa': tab,
        'total_no_leidas': _notificaciones_del_usuario(request.user).count(),
        'querystring_sin_pagina': _querystring_sin_pagina(request),
    }
    if tab == 'advertencias':
        contexto.update(_contexto_tab_advertencias(request))
    elif tab == 'recordatorios':
        contexto.update(_contexto_tab_recordatorios(request))
    elif tab == 'supervision':
        contexto.update(_contexto_tab_supervision(request))
    else:
        contexto.update(_contexto_tab_notificaciones(request))

    return render(request, 'pages/notificaciones/lista.html', contexto)


def _contexto_tab_supervision(request):
    """Pestaña «Supervisión» (solo Administrador, 25-10-2026): los avisos que
    recibieron los moderadores, UNA fila por aviso, con a quién le llegó y quién lo
    ha leído. Es de solo lectura: no marca nada por nadie.

    Una sola consulta agrupada en la base (`ArrayAgg` de PostgreSQL) y solo cuando se
    abre esta pestaña. Un aviso es el mismo para todos sus destinatarios: mismo
    objeto, regla, clave, tipo, título y mensaje.
    """
    from django.contrib.postgres.aggregates import ArrayAgg
    from django.db.models import Count, Max

    from core.paginacion import filas_por_pagina

    sub = request.GET.get('sub', 'pendientes')
    if sub not in SUBTABS_SUPERVISION:
        sub = 'pendientes'
    grupos = (Notificacion.objects
              .filter(destinatario__es_moderador=True)
              .values('content_type_id', 'object_id', 'codigo_regla', 'clave_extra', 'tipo',
                      'titulo', 'mensaje', 'unidad__descripcion')
              .annotate(fecha=Max('fecha_creado'), total=Count('pk'),
                        sin_leer=Count('pk', filter=Q(leido=False)),
                        lectores=ArrayAgg('destinatario__username', ordering='destinatario__username'),
                        leidos=ArrayAgg('leido', ordering='destinatario__username'))
              .order_by('-fecha'))
    if sub == 'pendientes':
        grupos = grupos.filter(sin_leer__gt=0)
    pagina = Paginator(grupos, filas_por_pagina(request)).get_page(request.GET.get('pagina'))
    for grupo in pagina:
        grupo['moderadores'] = [{'usuario': u, 'leido': l} for u, l in zip(grupo['lectores'], grupo['leidos'])]
    return {'supervision': pagina, 'sub_supervision': sub}


# Fragmento interno de `lista_notificaciones`: se cierra al Observador por el
# mismo motivo que la página que lo contiene, y no porque llegue a pedirlo.
@gestion_required
def panel_advertencias(request):
    """Fragmento HTMX: solo la tabla+paginación de Advertencias, actualizada por el
    formulario de filtros de `tab_advertencias.html` (`hx-target="#resultados-advertencias"`,
    el propio formulario de filtros queda FUERA del swap para no perder el estado de
    Select2 en cada cambio). Reutiliza `filtrar_advertencias()` — la misma función que
    la carga inicial de la pestaña — para que nunca pueda haber dos criterios de
    filtrado distintos."""
    from .filtros import filtrar_advertencias

    notificaciones, filtros_aplicados = filtrar_advertencias(request, request.user)
    contexto = {
        'notificaciones': _paginar_con_enlaces(request, notificaciones, origen_label='Advertencias'),
        'querystring_sin_pagina': _querystring_sin_pagina(request),
        'hay_filtros': filtros_aplicados['hay_filtros'],
        'mostrar_severidad': True,
    }
    respuesta = render(request, 'pages/notificaciones/partials/_tabla.html', contexto)
    # Sin esto, htmx empujaría la URL de ESTE endpoint (panel-advertencias/?...), que al
    # refrescar solo devuelve el fragmento, sin layout. Se empuja la URL real de la
    # pestaña, que sí es recargable de forma independiente.
    url_lista = reverse('lista_notificaciones')
    respuesta['HX-Push-Url'] = f'{url_lista}?{request.GET.urlencode()}'
    return respuesta


@gestion_required
def panel_recordatorios(request):
    """Fragmento HTMX: solo la tabla+paginación de Recordatorios, actualizada por el
    buscador+chips de prioridad de `tab_recordatorios.html`
    (`hx-target="#resultados-recordatorios"`). Mismo patrón que `panel_advertencias`,
    reutilizando `filtrar_recordatorios()` para que nunca pueda haber dos criterios de
    filtrado distintos entre la carga inicial y esta actualización dinámica."""
    from .filtros import filtrar_recordatorios

    sub = request.GET.get('sub', 'sistema')
    if sub not in SUBTABS_RECORDATORIOS:
        sub = 'sistema'
    origen = (Notificacion.Origen.SISTEMA if sub == 'sistema'
              else Notificacion.Origen.ADMINISTRACION)

    recordatorios, filtros_aplicados = filtrar_recordatorios(request, request.user, origen)
    pagina = _paginar_con_enlaces(request, recordatorios, origen_label='Recordatorios')
    for recordatorio in pagina:
        recordatorio.prioridad = _color_prioridad(recordatorio.fecha_objetivo)

    contexto = {
        'recordatorios': pagina,
        'sub_activa': sub,
        'querystring_sin_pagina': _querystring_sin_pagina(request),
        'hay_filtros': filtros_aplicados['hay_filtros'],
    }
    respuesta = render(request, 'pages/notificaciones/partials/_tabla_recordatorios.html', contexto)
    url_lista = reverse('lista_notificaciones')
    respuesta['HX-Push-Url'] = f'{url_lista}?{request.GET.urlencode()}'
    return respuesta


@write_required
@require_POST
def buscar_incidencias(request):
    """Botón «Buscar incidencias»: escaneo bajo demanda, alcance según el rol de
    quien lo pulsa (ver `notificaciones/escaneo.py::escanear_para_usuario`).

    Va por trozos, un módulo de reglas por petición (24-10-2026): de una vez podía
    superar el tiempo máximo del servidor. El navegador manda `parte=0, 1, 2…`
    hasta que la respuesta trae `siguiente: null`, y suma los totales. Sin `parte`,
    todo de una vez (lo conservan las llamadas internas y las pruebas antiguas)."""
    from .escaneo import partes_de_la_busqueda

    if not request.user.es_admin and not request.user.unidades.exists():
        return JsonResponse({'ok': True, 'total': 0, 'siguiente': None, 'partes': 0, 'mensaje':
                             'No tiene ninguna unidad asignada, así que no hay nada que buscar en su alcance.'})

    parte = request.POST.get('parte')
    if parte is None:
        total = escanear_para_usuario(request.user)
        return JsonResponse({'ok': True, 'total': total, 'siguiente': None, 'partes': 1,
                             'mensaje': f'{total} incidencia(s) encontrada(s) y notificada(s).'})

    partes = partes_de_la_busqueda()
    try:
        indice = int(parte)
        modulo = partes[indice]
    except (ValueError, IndexError):
        return JsonResponse({'ok': False, 'mensaje': 'Parte de la búsqueda no válida.'}, status=400)
    total = escanear_para_usuario(request.user, modulo=modulo)
    return JsonResponse({'ok': True, 'total': total, 'partes': len(partes),
                         'siguiente': indice + 1 if indice + 1 < len(partes) else None})


@write_required
@require_POST
def actualizar_recordatorios(request):
    """Botón «Actualizar recordatorios» (subpestaña Sistema): corre los detectores
    automáticos bajo demanda, sin esperar a la tarea programada
    (`notificaciones/recordatorios.py::generar_recordatorios`). Mismo permiso que
    «Buscar incidencias» (`@write_required` = admin o moderador); a diferencia de ese
    botón, aquí no hay alcance por rol que aplicar: `generar_recordatorios()` siempre
    reparte cada recordatorio a los destinatarios de SU unidad, así que un moderador
    solo ve los suyos igual que si lo hubiera generado la tarea programada.
    """
    resumen = generar_recordatorios()
    mensaje = f"{resumen['generados']} recordatorio(s) actualizado(s)."
    if resumen['sin_unidad']:
        mensaje += (
            f" {resumen['sin_unidad']} sin unidad organizativa se enviaron "
            f"a los administradores activos.")
    return JsonResponse({'ok': True, 'mensaje': mensaje})


@admin_required
@require_POST
def descartar_advertencia(request, pk):
    """Descarta manualmente una Advertencia (falso positivo o caso aceptado): TODAS
    las notificaciones que representan el MISMO hallazgo pasan a `estado=DESCARTADA`
    —no solo la fila `pk` que el admin tenía delante—, porque el listado general las
    deduplica (`notificaciones/filtros.py::_deduplicar`) cuando el mismo problema se
    notificó a varios destinatarios: descartar tiene que resolverlo para todos, igual
    que ya se ve como una sola fila. `_registrar_notificacion_de_hallazgo()` ya
    respeta `DESCARTADA` desde hace tiempo (no la revierte en la próxima evaluación
    automática). Solo admin: es una decisión que afecta a toda la empresa, no solo a
    la unidad de quien la descarta. `fecha_resolucion` se fija igual que al
    resolverse, para que entre en la purga automática a 60 días
    (`notificaciones/limpieza.py`) igual que cualquier otra fila inactiva.
    """
    referencia = get_object_or_404(
        Notificacion, pk=pk, tipo=Notificacion.Tipo.ALERTA, estado=Notificacion.Estado.ACTIVA)

    actualizadas = Notificacion.objects.filter(
        content_type=referencia.content_type, object_id=referencia.object_id,
        codigo_regla=referencia.codigo_regla, clave_extra=referencia.clave_extra,
        tipo=Notificacion.Tipo.ALERTA, estado=Notificacion.Estado.ACTIVA,
    ).update(estado=Notificacion.Estado.DESCARTADA, fecha_resolucion=timezone.now())

    if request.headers.get('HX-Request'):
        return HttpResponse(status=204, headers={'HX-Trigger': 'advertenciaDescartada'})
    messages.success(request, f'Advertencia descartada ({actualizadas} notificación(es)).')
    return redirect(f"{reverse('lista_notificaciones')}?tab=advertencias")


@admin_required
@require_POST
def reactivar_advertencia(request, pk):
    """Deshace un descarte manual: TODAS las notificaciones del MISMO hallazgo (misma
    clave natural, sin filtrar por destinatario) vuelven a `estado=ACTIVA` con
    `fecha_resolucion=None` — simétrica a `descartar_advertencia`, que actúa sobre el
    mismo grupo completo por la misma razón (deduplicación por destinatario en el
    listado). Solo se puede reactivar una DESCARTADA, nunca una RESUELTA (esas se
    resuelven solas cuando el problema real desaparece, no es una decisión manual que
    deshacer)."""
    referencia = get_object_or_404(
        Notificacion, pk=pk, tipo=Notificacion.Tipo.ALERTA, estado=Notificacion.Estado.DESCARTADA)

    actualizadas = Notificacion.objects.filter(
        content_type=referencia.content_type, object_id=referencia.object_id,
        codigo_regla=referencia.codigo_regla, clave_extra=referencia.clave_extra,
        tipo=Notificacion.Tipo.ALERTA, estado=Notificacion.Estado.DESCARTADA,
    ).update(estado=Notificacion.Estado.ACTIVA, fecha_resolucion=None)

    if request.headers.get('HX-Request'):
        return HttpResponse(status=204, headers={'HX-Trigger': 'advertenciaReactivada'})
    messages.success(request, f'Advertencia reactivada ({actualizadas} notificación(es)).')
    return redirect(f"{reverse('lista_notificaciones')}?tab=advertencias&sub=descartadas")


@admin_required
@require_POST
def recordatorio_crear(request):
    """Crea un Recordatorio manual (subpestaña Administración). Solo `es_admin` puede
    crear uno; se reparte a los destinatarios de la unidad elegida con el mismo
    mecanismo que las Advertencias (`destinatarios_de_unidad()`), NO por
    `update_or_create`: cada envío es una acción explícita y deliberada del usuario,
    no un detector periódico idempotente, así que crea filas nuevas sin deduplicar.
    """
    from django.contrib.contenttypes.models import ContentType

    from .destinatarios import destinatarios_de_unidad

    form = RecordatorioManualForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Revise los datos del recordatorio: ' + '; '.join(
            f'{campo}: {", ".join(errores)}' for campo, errores in form.errors.items()))
        return redirect(f"{reverse('lista_notificaciones')}?tab=recordatorios&sub=administracion")

    unidad = form.cleaned_data['unidad']
    destinatarios = list(destinatarios_de_unidad(unidad))
    if not destinatarios:
        messages.warning(
            request,
            f'«{unidad}» no tiene moderador ni hay administradores activos: '
            f'el recordatorio no se pudo repartir a nadie.')
        return redirect(f"{reverse('lista_notificaciones')}?tab=recordatorios&sub=administracion")

    tipo_ct = ContentType.objects.get_for_model(UnidadOrganizativa)
    Notificacion.objects.bulk_create([
        Notificacion(
            titulo=form.cleaned_data['titulo'], mensaje=form.cleaned_data['mensaje'],
            tipo=Notificacion.Tipo.RECORDATORIO, origen=Notificacion.Origen.ADMINISTRACION,
            estado=Notificacion.Estado.ACTIVA, fecha_objetivo=form.cleaned_data['fecha_objetivo'],
            content_type=tipo_ct, object_id=str(unidad.pk),
            unidad=unidad, destinatario=destinatario,
        )
        for destinatario in destinatarios
    ])
    messages.success(request, 'Recordatorio creado y repartido correctamente.')
    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primer_recordatorio_creado')
    from ranking.models import Actividad
    from ranking.servicios import registrar_actividad
    registrar_actividad(request.user, Actividad.RECORDATORIO_CREADO, detalle=form.cleaned_data['titulo'])
    return redirect(f"{reverse('lista_notificaciones')}?tab=recordatorios&sub=administracion")


@write_required
@require_POST
def recordatorio_completar(request, pk):
    """«Marcar como completado» de un Recordatorio MANUAL (Administración): los
    automáticos se resuelven solos cuando `generar_recordatorios()` deja de
    detectarlos, así que esta acción explícita solo tiene sentido para los que creó
    un administrador a mano."""
    recordatorio = get_object_or_404(
        _notificaciones_visibles(request.user), pk=pk,
        tipo=Notificacion.Tipo.RECORDATORIO, origen=Notificacion.Origen.ADMINISTRACION)
    recordatorio.estado = Notificacion.Estado.RESUELTA
    recordatorio.fecha_resolucion = timezone.now()
    recordatorio.save(update_fields=['estado', 'fecha_resolucion'])

    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primer_recordatorio_completado')
    # XP solo si se completa a tiempo (sin fecha objetivo, no hay plazo que incumplir).
    if recordatorio.fecha_objetivo is None or timezone.localdate() <= recordatorio.fecha_objetivo:
        from ranking.models import Actividad
        from ranking.servicios import registrar_actividad
        registrar_actividad(request.user, Actividad.RECORDATORIO_COMPLETADO, detalle=recordatorio.titulo)

    if request.headers.get('HX-Request'):
        return HttpResponse(status=204, headers={'HX-Trigger': 'recordatorioCompletado'})
    messages.success(request, 'Recordatorio marcado como completado.')
    return redirect(f"{reverse('lista_notificaciones')}?tab=recordatorios&sub=administracion")
