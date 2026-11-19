"""Avisos en la campana al cerrar el mes del Ranking.

- A TODOS los usuarios con rol (también con 0 XP): su resultado, o su medalla.
- A cada Administrador, además, un resumen con los ganadores de los tres roles.

Se reconocen por `codigo_regla = CODIGO_AVISO`. Por eso:
- la restricción única de `Notificacion` impide duplicarlos (uno por persona y
  mes, más el resumen);
- `notificaciones.views._notificaciones_visibles` no se los enseña a un
  Administrador que no es su destinatario (el Administrador ve todas las
  notificaciones de la app, y el "leído" es uno solo por notificación);
- la campana abre el Ranking al pulsarlos (templates/base/navbar.html).
"""
from django.contrib.contenttypes.models import ContentType

from .models import Rol

CODIGO_AVISO = 'RANKING'
CLAVE_RESUMEN = 'RESUMEN'
#: Aviso de ánimo a mitad de mes (18-11-2026). Mismo código que el resto de avisos
#: del Ranking (personal, abre la ventana); se distingue por `clave_extra`.
CLAVE_ANIMO = 'ANIMO-%04d-%02d'

MEDALLAS = {1: ('🥇', 'oro'), 2: ('🥈', 'plata'), 3: ('🥉', 'bronce')}

ROLES_PLURAL = {
    Rol.ADMINISTRADOR: 'Administradores',
    Rol.MODERADOR: 'Moderadores',
    Rol.OBSERVADOR: 'Observadores',
}


def texto_aviso(fila, rol, total_participantes, nombre_mes, subida=None):
    """(título, mensaje) del aviso personal de una fila de `clasificacion()`.
    `subida`: los XP que subió si es el «Más mejorado del mes»."""
    xp, puesto = fila['xp'], fila['puesto']
    grupo = ROLES_PLURAL[rol]
    if subida:
        return (f'📈 ¡Más mejorado de {nombre_mes}!',
                f'Subiste {subida} XP respecto al mes anterior y terminaste con {xp} XP '
                f'(nivel {fila["nivel"]}). ¡Enhorabuena! Lucirás la distinción todo este mes.')
    if xp > 0 and puesto in MEDALLAS:
        emoji, metal = MEDALLAS[puesto]
        return (f'{emoji} ¡Medalla de {metal} en {nombre_mes}!',
                f'Terminaste {puesto}º de los {grupo} con {xp} XP (nivel {fila["nivel"]}). '
                f'¡Enhorabuena! Mira los ganadores en «Ranking Mensual Orbith».')
    if xp > 0:
        return (f'Ranking de {nombre_mes} cerrado',
                f'Terminaste {puesto}º de {total_participantes} {grupo} con {xp} XP '
                f'(nivel {fila["nivel"]}). ¡Este mes puedes subir más!')
    return (f'Ranking de {nombre_mes} cerrado',
            f'En {nombre_mes.lower()} no sumaste XP. Cada día que trabajas en Orbith suma: '
            f'¡empieza este mes!')


def texto_resumen(clasificaciones, nombre_mes, anno, mejorados=None):
    """(título, mensaje) del resumen para los Administradores. Como solo lo leen
    ellos, quien no tiene nombre sale con su nombre de usuario, igual que en
    Estadísticas de uso (`estadisticas.nombre_para_admin`)."""
    from .estadisticas import nombre_para_admin
    from .servicios import PUESTOS_PREMIADOS

    partes = []
    for rol in (Rol.ADMINISTRADOR, Rol.MODERADOR, Rol.OBSERVADOR):
        ganadores = [f for f in clasificaciones.get(rol, [])
                     if f['xp'] > 0 and f['puesto'] <= PUESTOS_PREMIADOS]
        if ganadores:
            nombres = ', '.join(f'{MEDALLAS[f["puesto"]][0]} {nombre_para_admin(f["usuario"])} ({f["xp"]} XP)'
                                for f in ganadores)
        else:
            nombres = 'nadie sumó XP'
        del_rol = [g for g in (mejorados or {}).values() if g.rol == rol]
        if del_rol:
            nombres += '; más mejorado: ' + ', '.join(
                f'📈 {nombre_para_admin(g.usuario)} (+{g.subida} XP)' for g in del_rol)
        partes.append(f'{ROLES_PLURAL[rol]}: {nombres}.')
    return f'Ranking de {nombre_mes} {anno}: ganadores', ' '.join(partes)


def avisar_cierre(mes_cerrado, clasificaciones, mejorados=None):
    """Crea los avisos del mes recién cerrado. `clasificaciones` es
    {rol: clasificacion(..., incluir_sin_xp=True)}. Va dentro de la transacción
    de `servicios.cerrar_mes`: si falla, el mes no se da por cerrado y se
    reintenta en la siguiente petición."""
    from notificaciones.models import Notificacion

    from .servicios import MESES

    nombre_mes = MESES[mes_cerrado.mes - 1]
    referencia = {
        'tipo': Notificacion.Tipo.EVENTO,
        'estado': Notificacion.Estado.ACTIVA,
        'codigo_regla': CODIGO_AVISO,
        'content_type': ContentType.objects.get_for_model(mes_cerrado),
        'object_id': str(mes_cerrado.pk),
    }
    avisos = []
    for rol, filas in clasificaciones.items():
        participantes = sum(1 for f in filas if f['xp'] > 0)
        for fila in filas:
            mejorado = (mejorados or {}).get(fila['usuario'].pk)
            titulo, mensaje = texto_aviso(fila, rol, participantes, nombre_mes,
                                          subida=mejorado.subida if mejorado else None)
            avisos.append(Notificacion(titulo=titulo, mensaje=mensaje, destinatario=fila['usuario'],
                                       **referencia))

    titulo, mensaje = texto_resumen(clasificaciones, nombre_mes, mes_cerrado.anno, mejorados)
    for fila in clasificaciones.get(Rol.ADMINISTRADOR, []):
        avisos.append(Notificacion(titulo=titulo, mensaje=mensaje, destinatario=fila['usuario'],
                                   clave_extra=CLAVE_RESUMEN, **referencia))

    Notificacion.objects.bulk_create(avisos)
    return len(avisos)


def ideas_para_sumar(rol, cuantas=3):
    """Las actividades que más XP dan en `rol`, de la tabla de puntos real."""
    from .models import Actividad
    from .puntos import PUNTOS

    etiquetas = dict(Actividad.choices)
    mejores = sorted(PUNTOS.get(rol, {}).items(), key=lambda par: -par[1][0])[:cuantas]
    return [f'{etiquetas[actividad].lower()} ({xp} XP)' for actividad, (xp, _tope) in mejores]


def avisar_rezagados(anno, mes):
    """A mitad de mes, a quien aún no llegó al nivel Activo: cuántos XP le faltan y
    qué puede hacer para sumar (decisión de RRHH del 18-11-2026). Uno por persona y
    mes: la restricción única de `Notificacion` lo impide repetir."""
    from django.contrib.auth import get_user_model

    from notificaciones.avisos import _registrar_notificacion
    from notificaciones.models import Notificacion

    from .puntos import UMBRALES
    from .servicios import MESES, clasificacion

    tipo_ct = ContentType.objects.get_for_model(get_user_model())
    avisados = 0
    for rol in (Rol.MODERADOR, Rol.ADMINISTRADOR, Rol.OBSERVADOR):
        activo = UMBRALES[rol][1]
        ideas = ', '.join(ideas_para_sumar(rol))
        for fila in clasificacion(anno, mes, rol, incluir_sin_xp=True):
            if fila['xp'] >= activo:
                continue
            faltan = activo - fila['xp']
            _registrar_notificacion(
                tipo_ct=tipo_ct, object_id=str(fila['usuario'].pk), destinatario=fila['usuario'],
                codigo_regla=CODIGO_AVISO, clave_extra=CLAVE_ANIMO % (anno, mes),
                defaults={
                    'titulo': f'Te faltan {faltan} XP para el nivel Activo',
                    'mensaje': (f'Llevas {fila["xp"]} XP en {MESES[mes - 1].lower()}. '
                                f'Lo que más suma: {ideas}. ¡Aún queda medio mes!'),
                    'tipo': Notificacion.Tipo.EVENTO, 'estado': Notificacion.Estado.ACTIVA,
                })
            avisados += 1
    return avisados
