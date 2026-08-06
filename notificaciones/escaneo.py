"""Escaneo bajo demanda de las reglas evaluables en caliente, FUERA del flujo de
auditoría de Subsanación: nunca importa `subsanacion.servicios`, `subsanacion.models`
ni `subsanacion.signals` — no crea `EjecucionAnalisis`, no escribe `Hallazgo`, no
dispara `analisis_finalizado`. Solo reutiliza las reglas y sus funciones puras de
detección (`ejecutar()`), igual que `subsanacion/en_caliente.py` hace con
`evaluar_instancia()` para el guardado en caliente.

Es el único módulo que conoce a la vez `subsanacion.reglas`/`ContextoAnalisis` y las
funciones de `notificaciones/avisos.py`, del mismo modo que `avisos.py` ya es el único
puente para el flujo en caliente.

La detección SIEMPRE es global (`regla.ejecutar()` recorre toda la empresa, como ya
documenta `subsanacion/reglas/base.py`). El alcance (unidad del moderador, o global
para el admin) decide A QUIÉN se notifica un hallazgo, nunca si el hallazgo existe —
por eso `escanear_para_usuario()` resuelve siempre contra el resultado GLOBAL, no
contra el subconjunto filtrado: un moderador que pierde una unidad no debe dejar
notificaciones "colgadas" en ACTIVA para siempre.
"""

from collections import defaultdict

from django.contrib.contenttypes.models import ContentType

from subsanacion.contexto import ContextoAnalisis
from subsanacion.reglas import obtener_reglas

from .avisos import _registrar_notificacion_de_hallazgo, _resolver_notificaciones_obsoletas
from .destinatarios import destinatarios_de_unidad


def evaluar_reglas_en_caliente(reglas=None):
    """Ejecuta `ejecutar()` de cada regla evaluable en caliente (o de `reglas`),
    con un `ContextoAnalisis()` nuevo y desechable. Devuelve
    `[(regla, [HallazgoDetectado, ...]), ...]`, solo pares con al menos un hallazgo.
    """
    contexto = ContextoAnalisis()
    if reglas is None:
        reglas = [r for r in obtener_reglas() if r.evaluable_en_caliente]

    resultados = []
    for regla in reglas:
        detectados = list(regla.ejecutar(contexto))
        if detectados:
            resultados.append((regla, detectados))
    return resultados


def filtrar_por_unidades(resultados, unidades):
    """`unidades=None` -> alcance global, no filtra. En otro caso, `unidades` es un
    iterable de ids de `UnidadOrganizativa`: solo pasan los hallazgos cuyo
    `unidad_organizativa_id` esté en ese conjunto. Un hallazgo sin unidad
    (`unidad_organizativa_id=None`) queda excluido salvo alcance global.
    """
    if unidades is None:
        return resultados

    unidades = set(unidades)
    filtrados = []
    for regla, detectados in resultados:
        seleccion = [h for h in detectados if h.unidad_organizativa_id in unidades]
        if seleccion:
            filtrados.append((regla, seleccion))
    return filtrados


def _claves_vigentes_de(resultados):
    """`{(content_type_id, object_id, codigo_regla, clave_extra), ...}` de `resultados`."""
    claves = set()
    for regla, detectados in resultados:
        tipo_ct = ContentType.objects.get_for_model(regla.obtener_modelo())
        for hallazgo in detectados:
            claves.add((tipo_ct.id, hallazgo.object_id, regla.codigo, hallazgo.clave_extra or ''))
    return claves


def notificar_resultados(resultados_creacion, destinatario, *, resultados_globales=None):
    """Traduce `resultados_creacion` (ya filtrado por alcance) en `Notificacion` para
    `destinatario`, reutilizando el helper de `avisos.py`. Resuelve comparando contra
    `resultados_globales` (por defecto, los mismos `resultados_creacion`).

    `codigos_relevantes` para la resolución se calcula sobre TODAS las reglas
    evaluables en caliente (`obtener_reglas()`), no sobre las que aparecen en
    `resultados_globales`: una regla que ya no detecta NADA (el problema se corrigió
    en todas partes) desaparece de `resultados_globales` por completo, y aun así hay
    que poder resolver sus notificaciones activas. Derivarlo solo de los hallazgos
    encontrados dejaría esas notificaciones «colgadas» en ACTIVA para siempre.
    """
    resultados_globales = (
        resultados_globales if resultados_globales is not None else resultados_creacion)

    for regla, detectados in resultados_creacion:
        tipo_ct = ContentType.objects.get_for_model(regla.obtener_modelo())
        for hallazgo in detectados:
            _registrar_notificacion_de_hallazgo(
                tipo_ct=tipo_ct, object_id=hallazgo.object_id,
                destinatario=destinatario, regla=regla, hallazgo=hallazgo)

    codigos_relevantes = {r.codigo for r in obtener_reglas() if r.evaluable_en_caliente}
    claves_vigentes = _claves_vigentes_de(resultados_globales)
    _resolver_notificaciones_obsoletas(
        destinatario=destinatario, codigos_relevantes=codigos_relevantes,
        claves_vigentes=claves_vigentes)


def escanear_para_usuario(usuario):
    """Escaneo MANUAL (botón «Buscar incidencias»).

    Admin -> alcance global (sin filtro). Moderador -> sus unidades asignadas
    (`usuario.unidades`); si no tiene ninguna, el alcance es un conjunto VACÍO (no
    global) y el escaneo no encuentra nada en su nombre. Devuelve el total de
    incidencias notificadas.
    """
    resultados_globales = evaluar_reglas_en_caliente()
    unidades = None if usuario.es_admin else list(
        usuario.unidades.values_list('pk', flat=True))
    resultados_creacion = filtrar_por_unidades(resultados_globales, unidades)
    notificar_resultados(resultados_creacion, usuario, resultados_globales=resultados_globales)
    return sum(len(detectados) for _, detectados in resultados_creacion)


def escanear_globalmente_y_notificar_por_unidad():
    """Escaneo AUTOMÁTICO (comando de gestión `escanear_incidencias`).

    Recorre toda la empresa UNA sola vez y reparte cada hallazgo a
    `destinatarios_de_unidad()` de su unidad. Los hallazgos sin unidad se notifican a
    todos los administradores activos (el admin es el único rol de alcance global; un
    moderador no puede "adoptar" un hallazgo sin unidad con la que emparejarlo).
    Devuelve `{'notificados': N, 'sin_unidad': M}`.
    """
    from usuarios.models import CustomUser

    from .models import Notificacion

    resultados_globales = evaluar_reglas_en_caliente()

    por_unidad = defaultdict(list)   # unidad_id -> [(regla, hallazgo), ...]
    sin_unidad = []
    for regla, detectados in resultados_globales:
        for hallazgo in detectados:
            if hallazgo.unidad_organizativa_id is None:
                sin_unidad.append((regla, hallazgo))
            else:
                por_unidad[hallazgo.unidad_organizativa_id].append((regla, hallazgo))

    hallazgos_por_destinatario = defaultdict(list)
    for unidad_id, pares in por_unidad.items():
        for destinatario in destinatarios_de_unidad(unidad_id):
            hallazgos_por_destinatario[destinatario].extend(pares)

    if sin_unidad:
        for admin in CustomUser.objects.filter(es_admin=True, is_active=True):
            hallazgos_por_destinatario[admin].extend(sin_unidad)

    # Además de quienes tienen hallazgos en ESTA pasada, hay que volver a evaluar a
    # cualquier destinatario que hoy tenga una notificación ACTIVA de una regla
    # evaluable en caliente: si su unidad dejó de tener hallazgos por completo (se
    # corrigieron todos), ese destinatario no aparece en `hallazgos_por_destinatario`
    # y sin este añadido nunca volvería a pasar por `notificar_resultados()` — sus
    # notificaciones quedarían `ACTIVA` para siempre en vez de resolverse, salvo que
    # alguien vuelva a guardar el registro individualmente (que sí resuelve en
    # caliente). `notificar_resultados()` ya calcula `codigos_relevantes`/
    # `claves_vigentes` de forma global (no a partir de `resultados_creacion`), así que
    # llamarla con una lista vacía para estos destinatarios basta para resolver.
    codigos_relevantes = {r.codigo for r in obtener_reglas() if r.evaluable_en_caliente}
    destinatarios_con_activas = CustomUser.objects.filter(
        notificaciones_personales__tipo=Notificacion.Tipo.ALERTA,
        notificaciones_personales__estado=Notificacion.Estado.ACTIVA,
        notificaciones_personales__codigo_regla__in=codigos_relevantes,
    ).distinct()

    notificados = 0
    destinatarios_a_procesar = set(hallazgos_por_destinatario) | set(destinatarios_con_activas)
    for destinatario in destinatarios_a_procesar:
        pares = hallazgos_por_destinatario.get(destinatario, [])
        agrupado = defaultdict(list)
        for regla, hallazgo in pares:
            agrupado[regla].append(hallazgo)
        resultados_creacion = list(agrupado.items())
        notificar_resultados(
            resultados_creacion, destinatario, resultados_globales=resultados_globales)
        notificados += sum(len(detectados) for _, detectados in resultados_creacion)

    return {'notificados': notificados, 'sin_unidad': len(sin_unidad)}
