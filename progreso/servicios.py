import logging
from contextvars import ContextVar

from usuarios.alcance import es_administrador, es_moderador, es_observador

from .models import TareaGuia, TareaGuiaParte, TareaGuiaUsuario

logger = logging.getLogger(__name__)

# Icono y nombre de cada categoría: los usan el panel de la Guía y los logros
# de categoría, así que viven aquí y no repetidos en cada sitio.
ETIQUETAS_CATEGORIA = {
    TareaGuia.Categoria.PRIMEROS_PASOS: ('🎓', 'Primeros pasos'),
    TareaGuia.Categoria.EXPLORAR: ('🔎', 'Explorar Orbith'),
    TareaGuia.Categoria.EXPORTAR: ('📤', 'Exportar'),
    TareaGuia.Categoria.DOMINAR: ('🧩', 'Dominar Orbith'),
}

# Cómo se llama cada parte de una tarea con avance (`TareaGuia.partes`) en el
# panel y en los avisos. Una clave sin etiqueta se muestra tal cual.
ETIQUETAS_PARTE = {
    'pdf': 'PDF',
    'word': 'Word',
    'excel': 'Excel',
    'creacion': 'Contrato de Trabajo',
    'modificacion': 'Modificación',
    '17': 'Anexo 17',
    '17_1': 'Anexo 17.1',
    '17_2': 'Anexo 17.2',
}


def etiqueta_parte(clave):
    return ETIQUETAS_PARTE.get(clave, clave)

# Logros conseguidos durante la petición en curso. Lo abre y lo vacía
# `progreso.middleware.LogrosGuiaMiddleware`, que los entrega al navegador.
# Es una ContextVar (como `auditoria.middleware`) para que `completar_tarea`
# registre el logro venga de donde venga —una vista, un middleware o un
# receptor de señal— sin que nadie tenga que pasarle el `request`.
_logros_peticion = ContextVar('logros_guia', default=None)


def abrir_logros(usuario):
    """Empieza a recoger los logros de `usuario` en esta petición.
    Devuelve el token para `cerrar_logros`."""
    return _logros_peticion.set({'usuario_id': getattr(usuario, 'pk', None), 'logros': []})


def cerrar_logros(token):
    """Termina la recogida y devuelve la lista de logros conseguidos."""
    datos = _logros_peticion.get()
    _logros_peticion.reset(token)
    return datos['logros'] if datos else []


def campo_de_rol(usuario):
    """Nombre del campo de `TareaGuia` que dice si el rol de `usuario` ve una
    tarea, o `None` si el usuario no tiene un rol reconocido.

    Se usan las funciones de `usuarios/alcance.py` y no los booleanos a pelo:
    allí ya está resuelto que un Administrador (o superusuario) no cuente
    también como Moderador u Observador.
    """
    if es_administrador(usuario):
        return 'para_admin'
    if es_moderador(usuario):
        return 'para_moderador'
    if es_observador(usuario):
        return 'para_observador'
    return None


def tareas_visibles(usuario):
    """Tareas activas que corresponden al rol de `usuario`. Único sitio donde
    se decide qué tareas cuentan para alguien: el panel, el contador del
    navbar, la lista de Usuarios y `completar_tarea` pasan todos por aquí."""
    campo = campo_de_rol(usuario)
    if campo is None:
        return TareaGuia.objects.none()
    # Las tareas "en desarrollo" se enseñan atenuadas en el panel
    # (`tareas_en_desarrollo`), pero no cuentan ni se pueden completar.
    return TareaGuia.objects.filter(activo=True, en_desarrollo=False, **{campo: True})


def tareas_en_desarrollo(usuario):
    """Tareas del rol de `usuario` de módulos que aún se están construyendo:
    el panel las enseña atenuadas con "En desarrollo" y nada más."""
    campo = campo_de_rol(usuario)
    if campo is None:
        return TareaGuia.objects.none()
    return TareaGuia.objects.filter(activo=True, en_desarrollo=True, **{campo: True})


def resumen_progreso(usuario):
    """Total de tareas del usuario, cuántas completó y cuántas no ha visto.

    Las completadas se cuentan SOLO entre sus tareas visibles: si una tarea se
    desactiva, o deja de corresponder a su rol, no debe seguir sumando. Antes
    se contaban todas sus filas de `TareaGuiaUsuario` y el contador podía
    llegar a decir «15/14».
    """
    visibles = tareas_visibles(usuario)
    hechas = TareaGuiaUsuario.objects.filter(usuario=usuario, tarea__in=visibles)
    total = visibles.count()
    completadas = hechas.count()
    return {
        'total': total,
        'completadas': completadas,
        'sin_ver': hechas.filter(visto=False).count(),
        'porcentaje': round(100 * completadas / total) if total else 0,
    }


def anotar_progreso(usuarios):
    """Añade `progreso_total` y `progreso_completadas_count` a cada usuario de
    la lista, para la tabla de Usuarios. Cada rol tiene su propio total, así
    que no basta con un único número para toda la tabla.

    Hace dos consultas en total, no dos por usuario: el catálogo de tareas es
    de unas pocas filas y las tareas completadas se traen todas de una vez.
    Devuelve una lista (el queryset queda evaluado).
    """
    usuarios = list(usuarios)
    tareas = list(TareaGuia.objects.filter(activo=True, en_desarrollo=False).values(
        'id', 'para_admin', 'para_moderador', 'para_observador'))
    visibles_por_campo = {
        campo: {t['id'] for t in tareas if t[campo]}
        for campo in ('para_admin', 'para_moderador', 'para_observador')
    }

    hechas_por_usuario = {}
    filas = TareaGuiaUsuario.objects.filter(usuario__in=usuarios).values_list('usuario_id', 'tarea_id')
    for usuario_id, tarea_id in filas:
        hechas_por_usuario.setdefault(usuario_id, set()).add(tarea_id)

    for usuario in usuarios:
        visibles = visibles_por_campo.get(campo_de_rol(usuario), set())
        usuario.progreso_total = len(visibles)
        usuario.progreso_completadas_count = len(hechas_por_usuario.get(usuario.pk, set()) & visibles)
    return usuarios


def completar_tarea(usuario, codigo_tarea):
    """Único punto de escritura de la Guía de Orbith. Idempotente: si el
    usuario ya tenía la tarea, no hace nada y devuelve `None`.

    Defensivo a propósito: esta función NUNCA debe poder romper la operación
    de negocio real que la originó (crear un Aspirante, procesar una
    contratación/baja, revisar un hallazgo...). Cualquier error se registra
    en el log y se traga aquí — nunca se propaga al llamador. Esto es
    especialmente importante para los receptores de señal en
    `progreso/receptores.py`, que se conectan a señales de `subsanacion`
    despachadas con `Signal.send()` (no `send_robust()`): una excepción sin
    capturar ahí rompería el flujo real de Subsanación.

    Solo completa tareas del rol del usuario: un aviso «Nuevo en tu Guía» de
    una tarea que no aparece en su panel solo confundiría.

    Devuelve la `TareaGuia` si se acaba de completar (para mostrar el toast),
    o `None` si ya estaba completada, la tarea no existe/está inactiva/no es
    de su rol, o algo falló.
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return None
    try:
        tarea = tareas_visibles(usuario).get(codigo=codigo_tarea)
    except TareaGuia.DoesNotExist:
        return None
    try:
        _, creada = TareaGuiaUsuario.objects.get_or_create(usuario=usuario, tarea=tarea)
    except Exception:
        logger.exception("No se pudo registrar la tarea de guía '%s' para %s", codigo_tarea, usuario)
        return None
    if not creada:
        return None
    _registrar_logros(usuario, tarea)
    return tarea


def partes_de(usuario, tarea, hechas=None):
    """Las partes de `tarea` como [{clave, etiqueta, hecha}], en su orden.
    `hechas` (conjunto de claves) evita la consulta si ya se tiene."""
    if hechas is None:
        hechas = set(TareaGuiaParte.objects.filter(usuario=usuario, tarea=tarea)
                     .values_list('parte', flat=True))
    return [{'clave': c, 'etiqueta': etiqueta_parte(c), 'hecha': c in hechas} for c in tarea.lista_partes]


def completar_parte(usuario, codigo_tarea, parte):
    """Anota una parte de una tarea con avance y, si con ella el usuario ya
    tiene todas, completa la tarea (con su logro de siempre). Si la tarea no
    tiene partes, equivale a `completar_tarea`.

    Igual de defensiva que `completar_tarea`: nunca rompe la operación real
    (la descarga del documento). Devuelve True si anotó algo nuevo.
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return False
    try:
        tarea = tareas_visibles(usuario).get(codigo=codigo_tarea)
    except TareaGuia.DoesNotExist:
        return False
    requeridas = tarea.lista_partes
    if not requeridas:
        return completar_tarea(usuario, codigo_tarea) is not None
    if parte not in requeridas:
        return False
    try:
        _, creada = TareaGuiaParte.objects.get_or_create(usuario=usuario, tarea=tarea, parte=parte)
        if not creada:
            return False
        hechas = set(TareaGuiaParte.objects.filter(usuario=usuario, tarea=tarea).values_list('parte', flat=True))
    except Exception:
        logger.exception("No se pudo registrar la parte '%s' de '%s' para %s", parte, codigo_tarea, usuario)
        return False
    if hechas.issuperset(requeridas):
        completar_tarea(usuario, codigo_tarea)
    else:
        _registrar_avance(usuario, tarea, parte, len(hechas & set(requeridas)), len(requeridas))
    return True


def _registrar_avance(usuario, tarea, parte, hechas, total):
    """Aviso pequeño de una parte nueva ("✔ PDF — Exporta un Informe RRHH:
    1 de 3"). Sin `completadas`/`total`: no es un logro de la Guía, así que el
    aviso no pinta la barra de progreso general."""
    datos = _logros_peticion.get()
    if not datos or datos['usuario_id'] != usuario.pk:
        return
    datos['logros'].append({
        'id': f'parte:{tarea.codigo}:{parte}', 'tipo': 'avance',
        'titulo': f'✔ {etiqueta_parte(parte)}',
        'texto': f'{tarea.titulo}: {hechas} de {total}',
    })


def _registrar_logros(usuario, tarea):
    """Anota los logros que acaba de conseguir `usuario` al completar
    `tarea`: el de la propia tarea y, si con ella cierra su categoría o la
    Guía entera, el logro especial correspondiente.

    Solo se anotan si la petición en curso es del mismo usuario (un receptor
    de señal podría completar la tarea de otro). Igual de defensiva que
    `completar_tarea`: un fallo aquí no debe romper la operación real.
    """
    datos = _logros_peticion.get()
    if not datos or datos['usuario_id'] != usuario.pk:
        return
    try:
        resumen = resumen_progreso(usuario)
        progreso = {'completadas': resumen['completadas'], 'total': resumen['total']}
        datos['logros'].append({
            'id': f'tarea:{tarea.codigo}', 'tipo': 'tarea',
            'titulo': '🏆 ¡Logro desbloqueado!', 'texto': tarea.titulo, **progreso,
        })

        de_su_categoria = tareas_visibles(usuario).filter(categoria=tarea.categoria)
        pendientes = de_su_categoria.exclude(
            pk__in=TareaGuiaUsuario.objects.filter(usuario=usuario).values('tarea_id'))
        if not pendientes.exists():
            icono, nombre = ETIQUETAS_CATEGORIA.get(tarea.categoria, ('🏅', tarea.get_categoria_display()))
            datos['logros'].append({
                'id': f'categoria:{tarea.categoria}', 'tipo': 'categoria',
                'titulo': f'{icono} ¡Completaste {nombre}!',
                'texto': 'Terminaste todas las tareas de esta categoría.', **progreso,
            })

        if resumen['total'] and resumen['completadas'] >= resumen['total']:
            datos['logros'].append({
                'id': 'total', 'tipo': 'total',
                'titulo': '🏆 ¡Dominas Orbith!',
                'texto': 'Completaste toda tu Guía de Orbith. ¡Enhorabuena!', **progreso,
            })
    except Exception:
        logger.exception("No se pudieron calcular los logros de '%s' para %s", tarea.codigo, usuario)
