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
    from .campana import q_bandeja
    return Notificacion.objects.filter(q_bandeja(usuario))


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


def notificaciones_json(request):
    """El número rojo de la campana (cada página y cada 5 minutos). Solo el número:
    antes devolvía TODOS los avisos sin leer con su texto (hasta 3 000) para que el
    navegador los contara. Cuenta solo lo accionable (`notificaciones/campana.py`).

    Es también lo primero que pide cualquiera al abrir Orbith, así que aquí se lanza
    la limpieza diaria (una vez al día, ver `limpieza.limpiar_si_toca`)."""
    from .campana import accionables
    from .limpieza import limpiar_si_toca

    limpiar_si_toca()
    return JsonResponse({'total': accionables(request.user).count()})

def _destino_de_linea(linea):
    """A dónde lleva una línea del desplegable de la campana."""
    lista = reverse('lista_notificaciones')
    tipo, codigo = linea['tipo'], linea['codigo_regla']
    if codigo == 'RANKING':
        return None                       # abre la ventana del Ranking
    if codigo == 'SOL-NUEVA':
        return reverse('list_solicitudes')
    if codigo == 'SOL-PERS-NUEVA':
        return reverse('list_solicitudes_personalizadas')
    if tipo == Notificacion.Tipo.ALERTA:
        return f'{lista}?tab=advertencias&abrir={codigo}'
    if tipo == Notificacion.Tipo.RECORDATORIO:
        if not codigo:
            return f'{lista}?tab=recordatorios&sub=administracion'
        return f'{lista}?tab=recordatorios&abrir={codigo}'
    return f'{lista}?tab=notificaciones'


def ultimas_notificaciones(request):
    """El desplegable de la campana (18-11-2026): lo que hay que hacer, AGRUPADO
    (una línea por regla o tipo: «CTR-018 · 3 nuevos»), lo más grave primero y los
    avisos del Ranking Mensual arriba (llegan una vez al mes y si no, no se verían).
    Debajo, la Actividad de hoy (altas, bajas…), que no cuenta en el número."""
    from .agrupar import lineas_de_la_campana

    # El Observador no tiene la bandeja (`gestion_required`): sus líneas no llevan
    # a ella, solo se marcan como leídas.
    con_bandeja = request.user.es_admin or request.user.es_moderador
    hoy = timezone.localdate()
    lineas, mas, actividad = lineas_de_la_campana(request.user)
    for linea in lineas:
        if linea['tipo'] == Notificacion.Tipo.RECORDATORIO and not linea['codigo_regla']:
            linea['nombre'] = 'Recordatorios de la administración'
        destino = _destino_de_linea(linea)
        linea['href'] = destino if con_bandeja or not (destino or '').startswith(reverse('lista_notificaciones')) else None
        linea['vencido'] = linea['objetivo'] is not None and linea['objetivo'] <= hoy
        linea['objetivo'] = linea['objetivo'].strftime('%d/%m/%Y') if linea['objetivo'] else None
    return JsonResponse({
        'lineas': lineas, 'mas': mas, 'actividad': actividad,
        'url_bandeja': reverse('lista_notificaciones') if con_bandeja else None,
    })


@login_required
@require_POST
def marcar_grupo_leido(request):
    """Marca como leídos los avisos de un grupo («ALE:CTR-018», «REC:REC-CONTRATO»…),
    solo las copias de quien lo pide. Lo usan la campana al pulsar una línea y el
    botón «Marcar leídos» de cada grupo. No resuelve nada: siguen activos hasta que
    se corrijan."""
    tipo, _, codigo = (request.POST.get('grupo') or '').partition(':')
    if tipo not in Notificacion.Tipo.values:
        return JsonResponse({'ok': False, 'mensaje': 'Grupo no válido.'}, status=400)
    actualizadas = (_notificaciones_del_usuario(request.user)
                    .filter(tipo=tipo, codigo_regla=codigo).update(leido=True))
    return JsonResponse({'ok': True, 'actualizadas': actualizadas})


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
    if notificacion.codigo_regla == 'REC-ANTIGUEDAD':
        texto_boton = 'Hacer el movimiento de años de servicio'
    notificacion.enlace = construir_enlace(
        etiqueta, notificacion.object_id, forzar_url=forzar_url,
        next_url=next_url, origen_label=origen_label, usuario=usuario, etiqueta=texto_boton
    ) if etiqueta else None
    # Años de servicio (19-11-2026): el movimiento se abre con la fecha del aniversario
    # y la observación ya puestas.
    if notificacion.enlace and notificacion.codigo_regla == 'REC-ANTIGUEDAD' and notificacion.fecha_objetivo:
        href = notificacion.enlace['href']
        notificacion.enlace['href'] = '%s%sfecha_efectiva=%s&annos_servicio=1' % (
            href, '&' if '?' in href else '?', notificacion.fecha_objetivo.isoformat())
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
    """Pestaña «Notificaciones» (18-11-2026), en dos partes:

    * Avisos: solicitudes, decisiones, Ranking, cierre corregido… uno a uno, como antes.
    * Actividad: altas, bajas, cargos nuevos y cambios salariales, agrupados por día y
      tipo («Hoy: 12 altas · 8 cargos nuevos»). Se abren día a día.

    Con `?dia=AAAA-MM-DD&codigo=EVT-…` («Ver todos» de un tipo en un día) enseña la
    lista completa de ese tipo y día. Solo las copias del usuario."""
    from datetime import date

    from .agrupar import dias_de_actividad, nombre_de_codigo
    from .campana import PREFIJO_ACTIVIDAD

    bandeja = _bandeja(request.user)
    codigo = request.GET.get('codigo', '')
    try:
        dia = date.fromisoformat(request.GET.get('dia', ''))
    except ValueError:
        dia = None
    if dia and codigo.startswith(PREFIJO_ACTIVIDAD):
        del_dia = (bandeja.filter(tipo=Notificacion.Tipo.EVENTO, codigo_regla=codigo, fecha_creado__date=dia)
                   .select_related('content_type', 'autor').order_by('-fecha_creado'))
        return {'actividad_de': {'dia': dia, 'nombre': nombre_de_codigo(codigo)},
                'notificaciones': _paginar_con_enlaces(request, del_dia, origen_label='Notificaciones')}

    avisos = (bandeja.filter(tipo=Notificacion.Tipo.EVENTO)
              .exclude(codigo_regla__startswith=PREFIJO_ACTIVIDAD)
              .select_related('content_type'))
    dias = Paginator(dias_de_actividad(bandeja), 7).get_page(request.GET.get('pagina_dias'))
    return {
        'notificaciones': _paginar_con_enlaces(request, avisos, origen_label='Notificaciones'),
        'dias': dias,
        'hoy': timezone.localdate(),
    }


@gestion_required
def actividad_dia(request):
    """Fragmento HTMX de «Actividad»: lo que pasó un día, por tipo, con la unidad y
    quién lo hizo («por ti» si fue el propio usuario)."""
    from datetime import date

    from .agrupar import FILAS_AL_ABRIR, actividad_de_un_dia

    try:
        dia = date.fromisoformat(request.GET.get('dia', ''))
    except ValueError:
        return HttpResponse(status=400)
    return render(request, 'pages/notificaciones/partials/_actividad_dia.html', {
        'dia': dia, 'tipos': actividad_de_un_dia(_bandeja(request.user), dia, request.user),
        'filas_al_abrir': FILAS_AL_ABRIR,
    })


def _resultados_advertencias(request, consulta, filtros):
    """Lo que va dentro de `#resultados-advertencias`: los grupos por regla
    (18-11-2026) o, si se eligió una regla o se busca un texto, la tabla de siempre
    con un aviso por fila («Ver todos»)."""
    from .agrupar import grupos_de_advertencias
    from .filtros import _deduplicar

    if filtros['reglas_actuales'] or filtros['q']:
        lista = _deduplicar(consulta, request.user)
        return {'vista_grupos': False,
                'notificaciones': _paginar_con_enlaces(request, lista, origen_label='Advertencias')}
    # Los filtros de la pestaña viajan al abrir cada grupo (sin pestaña, página ni búsqueda).
    filtros_qs = request.GET.copy()
    for parametro in ('tab', 'pagina', 'filas', 'abrir', 'regla', 'q'):
        filtros_qs.pop(parametro, None)
    return {'vista_grupos': True, 'grupos': grupos_de_advertencias(consulta, request.user),
            'abrir': request.GET.get('abrir', ''), 'filtros_qs': filtros_qs.urlencode()}


def _contexto_tab_advertencias(request):
    """Pestaña «Advertencias»: alertas de integridad agrupadas por regla, con el panel
    de filtros."""
    from .filtros import consulta_advertencias

    consulta, filtros_aplicados = consulta_advertencias(request, request.user)
    contexto = {
        'puede_escanear': request.user.es_admin or request.user.es_moderador,
        'mostrar_severidad': True,
    }
    contexto.update(filtros_aplicados)
    contexto.update(_resultados_advertencias(request, consulta, filtros_aplicados))
    return contexto


@gestion_required
def grupo_advertencias(request):
    """Fragmento HTMX: al abrir el grupo de una regla, sus primeros registros (con
    los mismos filtros de la pestaña) y el enlace «Ver todos» a la tabla."""
    from .agrupar import FILAS_AL_ABRIR
    from .filtros import filtrar_advertencias

    lista, filtros = filtrar_advertencias(request, request.user)
    codigo = (filtros['reglas_actuales'] or [''])[0]
    vuelta = f"{reverse('lista_notificaciones')}?tab=advertencias&sub={filtros['sub_activa']}"
    filas = [_con_enlace(n, next_url=f'{vuelta}&abrir={codigo}', origen_label='Advertencias',
                         usuario=request.user)
             for n in lista[:FILAS_AL_ABRIR]]
    return render(request, 'pages/notificaciones/partials/_grupo_filas.html', {
        'filas': filas, 'total': len(lista), 'ver_todos': f'{vuelta}&regla={codigo}',
    })


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


def _resultados_recordatorios(request, sub, recordatorios, filtros):
    """Lo que va dentro de `#resultados-recordatorios`. Los automáticos, agrupados por
    tipo con los más urgentes primero (18-11-2026); al buscar un texto o pulsar «Ver
    todos» de un tipo, la tabla de siempre. Los manuales, siempre en tabla."""
    from .agrupar import FILAS_AL_ABRIR, grupos_de_recordatorios

    if sub == 'sistema' and not filtros['q'] and not filtros['codigo_actual']:
        recordatorios = list(recordatorios)
        for recordatorio in recordatorios:
            recordatorio.prioridad = _color_prioridad(recordatorio.fecha_objetivo)
        grupos = grupos_de_recordatorios(recordatorios)
        vuelta = f"{reverse('lista_notificaciones')}?tab=recordatorios"
        for grupo in grupos:
            del_grupo = [r for r in recordatorios if r.codigo_regla == grupo['codigo_regla']]
            grupo['filas'] = [
                _con_enlace(r, next_url=f"{vuelta}&abrir={grupo['codigo_regla']}",
                            origen_label='Recordatorios', usuario=request.user)
                for r in del_grupo[:FILAS_AL_ABRIR]]
        return {'vista_grupos': True, 'grupos': grupos, 'abrir': request.GET.get('abrir', '')}

    pagina = _paginar_con_enlaces(request, recordatorios, origen_label='Recordatorios')
    for recordatorio in pagina:
        recordatorio.prioridad = _color_prioridad(recordatorio.fecha_objetivo)
    return {'vista_grupos': False, 'recordatorios': pagina}


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
    contexto = {
        'sub_activa': sub,
        'unidades_admin': (UnidadOrganizativa.objects.order_by('descripcion')
                            if request.user.es_admin else None),
        'puede_actualizar_recordatorios': request.user.es_admin or request.user.es_moderador,
    }
    contexto.update(filtros_aplicados)
    contexto.update(_resultados_recordatorios(request, sub, recordatorios, filtros_aplicados))
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
    from .campana import accionables

    tab = request.GET.get('tab', 'notificaciones')
    if tab not in TABS or (tab == 'supervision' and not request.user.es_admin):
        tab = 'notificaciones'

    contexto = {
        'tab_activa': tab,
        # Lo mismo que el número de la campana: solo lo que hay que hacer.
        'total_pendientes': accionables(request.user).count(),
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
    """Pestaña «Supervisión» (solo Administrador): por moderador, lo que tiene sin
    leer de lo que hay que hacer, regla a regla (18-11-2026), para ver de un vistazo
    quién va atrasado. Cada regla se abre (`supervision_grupo`). Es de solo lectura:
    no marca nada por nadie. Las cuentas se hacen en la base (`agrupar.py`)."""
    from .agrupar import supervision_por_moderador

    sub = request.GET.get('sub', 'pendientes')
    if sub not in SUBTABS_SUPERVISION:
        sub = 'pendientes'
    return {'moderadores': supervision_por_moderador(sub == 'pendientes'), 'sub_supervision': sub}


@admin_required
def supervision_grupo(request):
    """Fragmento HTMX de Supervisión: los avisos de UN moderador y UNA regla, sin leer
    primero. Solo lectura."""
    from .agrupar import FILAS_AL_ABRIR

    try:
        moderador = int(request.GET.get('moderador', ''))
    except ValueError:
        return HttpResponse(status=400)
    avisos = Notificacion.objects.filter(
        destinatario_id=moderador, tipo=request.GET.get('tipo', ''),
        codigo_regla=request.GET.get('codigo', ''))
    primeros = list(avisos.order_by('leido', '-fecha_creado')[:FILAS_AL_ABRIR])
    return render(request, 'pages/notificaciones/partials/_supervision_filas.html', {
        'avisos': primeros, 'resto': avisos.count() - len(primeros),
    })


# Fragmento interno de `lista_notificaciones`: se cierra al Observador por el
# mismo motivo que la página que lo contiene, y no porque llegue a pedirlo.
@gestion_required
def panel_advertencias(request):
    """Fragmento HTMX: solo los resultados de Advertencias (grupos o tabla), al
    cambiar los filtros de `tab_advertencias.html` (`hx-target="#resultados-advertencias"`;
    el propio formulario de filtros queda FUERA del swap para no perder el estado de
    Select2 en cada cambio). Reutiliza `consulta_advertencias()` y
    `_resultados_advertencias()` — lo mismo que la carga inicial de la pestaña — para
    que nunca pueda haber dos criterios distintos."""
    from .filtros import consulta_advertencias

    consulta, filtros = consulta_advertencias(request, request.user)
    contexto = {
        'querystring_sin_pagina': _querystring_sin_pagina(request),
        'hay_filtros': filtros['hay_filtros'],
        'mostrar_severidad': True,
        'sub_activa': filtros['sub_activa'],
    }
    contexto.update(_resultados_advertencias(request, consulta, filtros))
    respuesta = render(request, 'pages/notificaciones/partials/_resultados_advertencias.html', contexto)
    # Sin esto, htmx empujaría la URL de ESTE endpoint (panel-advertencias/?...), que al
    # refrescar solo devuelve el fragmento, sin layout. Se empuja la URL real de la
    # pestaña, que sí es recargable de forma independiente.
    url_lista = reverse('lista_notificaciones')
    respuesta['HX-Push-Url'] = f'{url_lista}?{request.GET.urlencode()}'
    return respuesta


@gestion_required
def panel_recordatorios(request):
    """Fragmento HTMX: solo los resultados de Recordatorios (grupos o tabla), al
    buscar o pulsar un chip de prioridad en `tab_recordatorios.html`
    (`hx-target="#resultados-recordatorios"`). Mismo patrón que `panel_advertencias`."""
    from .filtros import filtrar_recordatorios

    sub = request.GET.get('sub', 'sistema')
    if sub not in SUBTABS_RECORDATORIOS:
        sub = 'sistema'
    origen = (Notificacion.Origen.SISTEMA if sub == 'sistema'
              else Notificacion.Origen.ADMINISTRACION)

    recordatorios, filtros = filtrar_recordatorios(request, request.user, origen)
    contexto = {
        'sub_activa': sub,
        'querystring_sin_pagina': _querystring_sin_pagina(request),
        'hay_filtros': filtros['hay_filtros'],
    }
    contexto.update(_resultados_recordatorios(request, sub, recordatorios, filtros))
    respuesta = render(request, 'pages/notificaciones/partials/_resultados_recordatorios.html', contexto)
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
