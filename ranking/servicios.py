"""Motor del Ranking Mensual Orbith.

- `registrar_actividad()`: el único punto de escritura. Lo llaman las vistas
  (crear un aspirante, un alta, decidir una solicitud...), los receptores de
  Subsanación y el middleware de descargas.
- `cerrar_mes_si_toca()`: la primera petición de cada mes cierra el mes
  anterior (ganadores) y borra lo que tenga más de 3 meses. Sin tareas
  programadas.
- `clasificacion()`: el ranking de un rol en un mes, con empates.
"""
import logging
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from usuarios.alcance import es_administrador, es_moderador, es_observador

from .models import Actividad, ActividadXP, GanadorMes, MesCerrado, Rol
from .puntos import PUNTOS, XP_DIA_ACTIVO, nivel_de

logger = logging.getLogger(__name__)

# Meses que se conservan: el actual y los 2 anteriores.
MESES_CONSERVADOS = 3

# Puestos que reciben medalla en cada rol.
PUESTOS_PREMIADOS = 3


def rol_de(usuario):
    """Rol del Ranking de `usuario` (`Rol`), o None si no tiene ninguno."""
    if es_administrador(usuario):
        return Rol.ADMINISTRADOR
    if es_moderador(usuario):
        return Rol.MODERADOR
    if es_observador(usuario):
        return Rol.OBSERVADOR
    return None


# ----------------------------------------------------------------------
# Registro
# ----------------------------------------------------------------------
def registrar_actividad(usuario, actividad, detalle='', formato=''):
    """Anota una acción de `usuario` y le da su XP si no pasó del tope diario.

    Defensiva, como `progreso.servicios.completar_tarea`: NUNCA rompe la
    operación real que la originó. Cualquier error se registra en el log y se
    traga. Va dentro de su propio `atomic()` (un punto de guardado) para que un
    fallo aquí tampoco estropee la transacción de la vista que la llama.

    Devuelve la fila creada, o None si no se registró (usuario anónimo o
    desactivado, actividad que no es de su rol, o error).
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return None
    if not getattr(usuario, 'is_active', False):
        return None
    try:
        rol = rol_de(usuario)
        regla = PUNTOS.get(rol, {}).get(actividad)
        if regla is None:
            return None
        valor, tope = regla
        ahora = timezone.now()
        dia = timezone.localdate(ahora)
        with transaction.atomic():
            xp = valor
            if tope is not None:
                hechas = ActividadXP.objects.filter(usuario=usuario, dia=dia, actividad=actividad).count()
                if hechas >= tope:
                    xp = 0
            fila = ActividadXP.objects.create(
                usuario=usuario, rol=rol, actividad=actividad, fecha=ahora, dia=dia, xp=xp,
                detalle=str(detalle or '')[:200], formato=formato or '')
        _marcar_dia_activo(usuario, rol, dia, ahora)
        return fila
    except Exception:
        logger.exception("No se pudo registrar la actividad '%s' del Ranking para %s", actividad, usuario)
        return None


def _marcar_dia_activo(usuario, rol, dia, ahora):
    """El "Día con actividad" se da con la primera acción del día."""
    if ActividadXP.objects.filter(usuario=usuario, dia=dia, actividad=Actividad.DIA_ACTIVO).exists():
        return
    try:
        with transaction.atomic():
            ActividadXP.objects.create(usuario=usuario, rol=rol, actividad=Actividad.DIA_ACTIVO,
                                       fecha=ahora, dia=dia, xp=XP_DIA_ACTIVO)
    except IntegrityError:
        # Otra petición simultánea ya lo marcó.
        pass


# ----------------------------------------------------------------------
# Meses
# ----------------------------------------------------------------------
def mes_anterior(anno, mes, cuantos=1):
    """(año, mes) `cuantos` meses antes de (anno, mes)."""
    indice = anno * 12 + (mes - 1) - cuantos
    return indice // 12, indice % 12 + 1


def limites_mes(anno, mes):
    """Primer día del mes y primer día del mes siguiente."""
    siguiente_anno, siguiente_mes = (anno + 1, 1) if mes == 12 else (anno, mes + 1)
    return date(anno, mes, 1), date(siguiente_anno, siguiente_mes, 1)


def totales_del_mes(anno, mes):
    """{usuario_id: XP del mes}."""
    inicio, fin = limites_mes(anno, mes)
    return dict(
        ActividadXP.objects.filter(dia__gte=inicio, dia__lt=fin)
        .values('usuario').annotate(total=Sum('xp')).values_list('usuario', 'total'))


def clasificacion(anno, mes, rol, incluir_sin_xp=False):
    """Ranking de `rol` en el mes: lista de dicts {usuario, xp, puesto, nivel},
    de más a menos XP.

    - Agrupa por el rol ACTUAL del usuario (si cambió de rol a mitad de mes,
      su XP cuenta en el nuevo).
    - Excluye a los usuarios desactivados.
    - Empates: comparten puesto y el siguiente salta (1, 1, 3).
    - `incluir_sin_xp=True` añade a los que tienen 0 XP (página del
      Administrador); si no, solo salen los que sumaron algo.
    """
    totales = totales_del_mes(anno, mes)
    # El nombre público sale del trabajador vinculado: se trae de una vez.
    usuarios = get_user_model().objects.filter(is_active=True).select_related('contrato__aspirante')
    if not incluir_sin_xp:
        usuarios = usuarios.filter(pk__in=list(totales))
    filas = [{'usuario': u, 'xp': totales.get(u.pk) or 0}
             for u in usuarios if rol_de(u) == rol]
    filas.sort(key=lambda f: (-f['xp'], f['usuario'].username.lower()))
    for indice, fila in enumerate(filas):
        if indice and fila['xp'] == filas[indice - 1]['xp']:
            fila['puesto'] = filas[indice - 1]['puesto']
        else:
            fila['puesto'] = indice + 1
        fila['nivel'] = nivel_de(rol, fila['xp'])
    return filas


def cerrar_mes(anno, mes):
    """Reparte las medallas del mes (los 3 primeros puestos de cada rol, con
    XP), avisa a todos en la campana y borra lo que ya no se conserva.
    Devuelve False si el mes ya estaba cerrado."""
    from .avisos import avisar_cierre

    try:
        with transaction.atomic():
            cerrado = MesCerrado.objects.create(anno=anno, mes=mes)
            clasificaciones = {rol: clasificacion(anno, mes, rol, incluir_sin_xp=True)
                               for rol in Rol.values}
            ganadores = [
                GanadorMes(anno=anno, mes=mes, rol=rol, usuario=fila['usuario'],
                           puesto=fila['puesto'], xp=fila['xp'])
                for rol, filas in clasificaciones.items()
                for fila in filas
                if fila['xp'] > 0 and fila['puesto'] <= PUESTOS_PREMIADOS
            ]
            GanadorMes.objects.bulk_create(ganadores)
            # Un mes sin ninguna actividad (antes de activar el Ranking) se
            # cierra en silencio: no tiene sentido avisar "no sumaste XP" a todos.
            inicio, fin = limites_mes(anno, mes)
            if ActividadXP.objects.filter(dia__gte=inicio, dia__lt=fin).exists():
                avisar_cierre(cerrado, clasificaciones)
            limpiar_meses_antiguos(*mes_anterior(anno, mes, -1))
    except IntegrityError:
        # Otra petición lo cerró a la vez.
        return False
    return True


def limpiar_meses_antiguos(anno, mes):
    """Siendo (anno, mes) el mes en curso, borra todo lo anterior a los
    `MESES_CONSERVADOS` últimos meses."""
    limite_anno, limite_mes = mes_anterior(anno, mes, MESES_CONSERVADOS - 1)
    ActividadXP.objects.filter(dia__lt=date(limite_anno, limite_mes, 1)).delete()
    anteriores = Q(anno__lt=limite_anno) | Q(anno=limite_anno, mes__lt=limite_mes)
    GanadorMes.objects.filter(anteriores).delete()
    MesCerrado.objects.filter(anteriores).delete()


# Mes que ESTE proceso ya comprobó: evita ir a la base de datos en cada
# petición. Cada proceso del servidor lo comprueba una vez al mes.
_mes_revisado = None


def cerrar_mes_si_toca(hoy=None):
    """Cierra el mes anterior si nadie lo ha cerrado aún. La llama el
    middleware en cada petición, pero solo consulta la base de datos la
    primera vez de cada mes. Nunca lanza excepciones."""
    global _mes_revisado
    hoy = hoy or timezone.localdate()
    actual = (hoy.year, hoy.month)
    if _mes_revisado == actual:
        return False
    try:
        anno, mes = mes_anterior(*actual)
        cerrado = False
        if not MesCerrado.objects.filter(anno=anno, mes=mes).exists():
            cerrado = cerrar_mes(anno, mes)
        _mes_revisado = actual
        return cerrado
    except Exception:
        logger.exception('No se pudo cerrar el mes del Ranking')
        return False


# ----------------------------------------------------------------------
# Ventana "Ranking Mensual Orbith" del usuario
# ----------------------------------------------------------------------
MESES = ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto',
         'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')

SIN_NOMBRE = 'Usuario sin nombre'

# Puestos que se ven en la ventana del usuario.
TOP_VENTANA = 10

# Icono (Boxicons) de cada actividad en "Mi detalle".
ICONOS = {
    Actividad.ASPIRANTE: 'bx-user-plus',
    Actividad.ALTA: 'bx-id-card',
    Actividad.MOVIMIENTO: 'bx-transfer',
    Actividad.ENVIO_MOVIMIENTO: 'bx-sync',
    Actividad.BAJA: 'bx-user-minus',
    Actividad.SOLICITUD_APROBADA: 'bx-check-circle',
    Actividad.CIERRE_EN_PLAZO: 'bx-lock-alt',
    Actividad.HALLAZGO_REVISADO: 'bx-search-alt',
    Actividad.RECORDATORIO_COMPLETADO: 'bx-task',
    Actividad.SOLICITUD_DECIDIDA: 'bx-list-check',
    Actividad.ANALISIS_SUBSANACION: 'bx-analyse',
    Actividad.RECORDATORIO_CREADO: 'bx-bell-plus',
    Actividad.INFORME: 'bx-bar-chart-alt-2',
    Actividad.DESCARGA: 'bx-download',
    Actividad.DIA_ACTIVO: 'bx-calendar-check',
}


METALES = {1: 'oro', 2: 'plata', 3: 'bronce'}


def distincion_de(usuario, hoy=None):
    """La distinción que `usuario` luce este mes por su puesto del mes
    anterior: {'metal': 'oro'|'plata'|'bronce', 'puesto'}, o None.

    La pide el context processor en cada página: es una sola consulta por la
    restricción única (anno, mes, usuario) de `GanadorMes`. Si el ganador
    cambió de rol, la conserva: la ganó.
    """
    hoy = hoy or timezone.localdate()
    anno, mes = mes_anterior(hoy.year, hoy.month)
    puesto = (GanadorMes.objects.filter(anno=anno, mes=mes, usuario=usuario)
              .values_list('puesto', flat=True).first())
    if puesto not in METALES:
        return None
    return {'metal': METALES[puesto], 'puesto': puesto}


def nombre_publico(usuario):
    """Nombre que ven los demás en el Ranking. NUNCA el nombre de usuario con
    el que se inicia sesión (sería un problema de seguridad): el del
    trabajador vinculado, o el nombre y apellidos de la ficha del usuario."""
    nombre = usuario.nombre_completo or (usuario.get_full_name() or '').strip()
    return nombre or SIN_NOMBRE


def iniciales(nombre):
    if nombre == SIN_NOMBRE:
        return ''
    partes = nombre.split()
    return ''.join(p[0] for p in partes[:2]).upper()


def _persona(fila, usuario_actual):
    usuario = fila['usuario']
    nombre = nombre_publico(usuario)
    return {
        **fila,
        'nombre': nombre,
        'iniciales': iniciales(nombre),
        'avatar': usuario.avatar.url if usuario.avatar else '',
        'soy_yo': usuario.pk == usuario_actual.pk,
    }


def progreso_nivel(rol, xp):
    """Nivel actual, el siguiente, los XP que faltan y el % de la barra."""
    from .puntos import NIVELES, UMBRALES
    umbrales = UMBRALES[rol]
    indice = max(i for i, minimo in enumerate(umbrales) if xp >= minimo)
    if indice == len(umbrales) - 1:
        return {'nivel': NIVELES[indice], 'siguiente': None, 'faltan': 0, 'porcentaje': 100}
    desde, hasta = umbrales[indice], umbrales[indice + 1]
    return {
        'nivel': NIVELES[indice],
        'siguiente': NIVELES[indice + 1],
        'faltan': hasta - xp,
        'porcentaje': round(100 * (xp - desde) / (hasta - desde)),
    }


def datos_ventana(usuario, hoy=None):
    """Todo lo que muestra la ventana "Ranking Mensual Orbith" del usuario,
    siempre del mes en curso. None si el usuario no tiene rol."""
    rol = rol_de(usuario)
    if rol is None:
        return None
    hoy = hoy or timezone.localdate()
    anno, mes = hoy.year, hoy.month

    filas = [_persona(f, usuario) for f in clasificacion(anno, mes, rol)]
    mia = next((f for f in filas if f['soy_yo']), None)
    xp = mia['xp'] if mia else 0
    top = [f for f in filas if f['puesto'] <= TOP_VENTANA]
    fuera_del_top = None
    if not any(f['soy_yo'] for f in top):
        fuera_del_top = mia or _persona({'usuario': usuario, 'xp': 0, 'puesto': None}, usuario)
        # Para entrar basta con igualar al último del top 10 (los empates
        # comparten puesto); si aún no hay 10, basta con sumar algo.
        fuera_del_top['faltan_top'] = (top[-1]['xp'] - xp) if len(top) >= TOP_VENTANA else 1

    inicio, fin = limites_mes(anno, mes)
    etiquetas = dict(Actividad.choices)
    detalle = [
        {'actividad': codigo, 'etiqueta': etiquetas.get(codigo, codigo), 'xp': total,
         'icono': ICONOS.get(codigo, 'bx-star')}
        for codigo, total in ActividadXP.objects
        .filter(usuario=usuario, dia__gte=inicio, dia__lt=fin)
        .values('actividad').annotate(total=Sum('xp')).filter(total__gt=0)
        .order_by('-total').values_list('actividad', 'total')
    ]

    meses = []
    for atras in range(MESES_CONSERVADOS - 1, -1, -1):
        a, m = mes_anterior(anno, mes, atras)
        total = totales_del_mes(a, m).get(usuario.pk) or 0
        meses.append({'etiqueta': MESES[m - 1], 'xp': total, 'nivel': nivel_de(rol, total),
                      'en_curso': atras == 0})
    maximo = max(m['xp'] for m in meses) or 1
    for m in meses:
        m['porcentaje'] = max(4, round(100 * m['xp'] / maximo)) if m['xp'] else 0

    ganadores = []
    for g in (GanadorMes.objects.filter(rol=rol).select_related('usuario__contrato__aspirante')
              .order_by('-anno', '-mes', 'puesto')):
        etiqueta = f'{MESES[g.mes - 1]} {g.anno}'
        if not ganadores or ganadores[-1]['etiqueta'] != etiqueta:
            ganadores.append({'etiqueta': etiqueta, 'personas': []})
        ganadores[-1]['personas'].append(
            _persona({'usuario': g.usuario, 'xp': g.xp, 'puesto': g.puesto}, usuario))

    return {
        'rol': rol,
        'rol_etiqueta': Rol(rol).label,
        'mes_etiqueta': f'{MESES[mes - 1]} {anno}',
        'xp': xp,
        'puesto': mia['puesto'] if mia else None,
        'participantes': len(filas),
        'progreso': progreso_nivel(rol, xp),
        'top': top,
        'fuera_del_top': fuera_del_top,
        'detalle': detalle,
        'meses': meses,
        'ganadores': ganadores,
    }
