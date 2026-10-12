from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import TareaGuia, TareaGuiaParte, TareaGuiaUsuario
from .servicios import ETIQUETAS_CATEGORIA, partes_de, resumen_progreso, tareas_en_desarrollo, tareas_visibles


@login_required
@never_cache
def panel_guia(request):
    """Contenido del modal "Guía de Orbith", cargado bajo demanda (fetch) al
    abrir el modal — no se computa en cada petición vía context processor,
    solo cuando el usuario realmente lo consulta.

    `@never_cache` es obligatorio aquí: es contenido personalizado por
    usuario (qué tiene completado) servido a través de una URL fija — sin
    esto, un navegador (o un proxy intermedio) podría servir una copia en
    caché con el estado de OTRO momento o de otro usuario en una sesión
    compartida del mismo navegador.
    """
    # Solo las tareas de su rol: un Observador no ve "Crea tu primer Aspirante".
    tareas = tareas_visibles(request.user)
    completadas = set(
        TareaGuiaUsuario.objects.filter(usuario=request.user).values_list('tarea_id', flat=True)
    )

    # Partes hechas de las tareas con avance, en una sola consulta.
    partes_hechas = {}
    for tarea_id, parte in TareaGuiaParte.objects.filter(usuario=request.user).values_list('tarea_id', 'parte'):
        partes_hechas.setdefault(tarea_id, set()).add(parte)

    # Las de módulos en construcción se intercalan en su sitio, atenuadas.
    en_desarrollo = list(tareas_en_desarrollo(request.user))
    todas = sorted(list(tareas) + en_desarrollo, key=lambda t: (t.orden, t.id))

    grupos = {}
    for tarea in todas:
        icono, etiqueta = ETIQUETAS_CATEGORIA.get(tarea.categoria, ('', tarea.categoria))
        grupo = grupos.setdefault(tarea.categoria, {'icono': icono, 'etiqueta': etiqueta, 'tareas': []})
        if tarea.en_desarrollo:
            grupo['tareas'].append({'tarea': tarea, 'completada': False, 'en_desarrollo': True})
            continue
        item = {'tarea': tarea, 'completada': tarea.id in completadas}
        if tarea.lista_partes:
            item['partes'] = partes_de(request.user, tarea, partes_hechas.get(tarea.id, set()))
            item['partes_hechas'] = sum(1 for p in item['partes'] if p['hecha'])
        grupo['tareas'].append(item)

    # Orden fijo de categorías (no el de aparición en la BD).
    orden_categorias = [c for c, _ in TareaGuia.Categoria.choices]
    grupos_ordenados = [grupos[c] for c in orden_categorias if c in grupos]
    # Una categoría está completa (su medalla se enciende) cuando el usuario
    # tiene hechas todas SUS tareas de esa categoría.
    # Las "en desarrollo" no cuentan.
    for grupo in grupos_ordenados:
        normales = [item for item in grupo['tareas'] if not item.get('en_desarrollo')]
        grupo['completa'] = bool(normales) and all(item['completada'] for item in normales)

    # Mismos números que el badge del navbar (`core/context_processors.py`):
    # salen de la misma función para que no puedan contradecirse.
    resumen = resumen_progreso(request.user)
    contexto = {
        'grupos': grupos_ordenados,
        'total': resumen['total'],
        'completadas': resumen['completadas'],
        'pendientes': resumen['total'] - resumen['completadas'],
        'porcentaje': resumen['porcentaje'],
    }
    return render(request, 'pages/progreso/partials/panel_guia.html', contexto)


@login_required
@never_cache
@require_POST
def marcar_vistas(request):
    """Marca como vistas todas las tareas completadas pendientes de ver, al
    abrir el modal de la Guía. Acción explícita del usuario (POST), separada
    de `panel_guia` (GET) a propósito."""
    TareaGuiaUsuario.objects.filter(usuario=request.user, visto=False).update(visto=True)
    return JsonResponse({'ok': True})


@login_required
@never_cache
def tarea_guiada(request, codigo):
    """Datos de una tarea para el "modo guiado" (acompañamiento paso a paso).

    Lo consume el widget flotante definido en `static/js/progreso_guia.js`,
    que solo se activa cuando el usuario pulsa "Ir a X" desde el panel de la
    Guía (nunca de forma automática al navegar). El widget guía paso a paso
    siempre igual, esté `completada` en `True` o `False`: quien vuelve a
    pulsar "Ir a X" sobre una tarea ya hecha antes está pidiendo un repaso
    supervisado, no un aviso de que ya la completó. Se devuelve `completada`
    igualmente por si el panel u otra pantalla lo necesita en el futuro.

    `@never_cache` es crítico en particular para este endpoint: se consulta
    en cada carga de página del "modo guiado" para decidir si mostrar el
    widget o cerrarlo — una respuesta cacheada con `completada` desactualizado
    haría que el widget nunca aparezca (o se cierre solo con un aviso de
    "completado" que en realidad no ocurrió).
    """
    tarea = get_object_or_404(tareas_visibles(request.user), codigo=codigo)
    completada = TareaGuiaUsuario.objects.filter(usuario=request.user, tarea=tarea).exists()
    return JsonResponse({
        'codigo': tarea.codigo,
        'titulo': tarea.titulo,
        'pasos': tarea.pasos,
        'completada': completada,
    })


@login_required
@never_cache
def partes_tarea(request, codigo):
    """Qué partes de una tarea con avance tiene hechas el usuario. Lo usan los
    recorridos de exportar para marcar los formatos ya hechos (✔ PDF)."""
    tarea = get_object_or_404(tareas_visibles(request.user), codigo=codigo)
    completada = TareaGuiaUsuario.objects.filter(usuario=request.user, tarea=tarea).exists()
    return JsonResponse({'partes': partes_de(request.user, tarea), 'completada': completada})
