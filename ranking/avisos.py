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

MEDALLAS = {1: ('🥇', 'oro'), 2: ('🥈', 'plata'), 3: ('🥉', 'bronce')}

ROLES_PLURAL = {
    Rol.ADMINISTRADOR: 'Administradores',
    Rol.MODERADOR: 'Moderadores',
    Rol.OBSERVADOR: 'Observadores',
}


def texto_aviso(fila, rol, total_participantes, nombre_mes):
    """(título, mensaje) del aviso personal de una fila de `clasificacion()`."""
    xp, puesto = fila['xp'], fila['puesto']
    grupo = ROLES_PLURAL[rol]
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


def texto_resumen(clasificaciones, nombre_mes, anno):
    """(título, mensaje) del resumen para los Administradores."""
    from .servicios import PUESTOS_PREMIADOS, nombre_publico

    partes = []
    for rol in (Rol.ADMINISTRADOR, Rol.MODERADOR, Rol.OBSERVADOR):
        ganadores = [f for f in clasificaciones.get(rol, [])
                     if f['xp'] > 0 and f['puesto'] <= PUESTOS_PREMIADOS]
        if ganadores:
            nombres = ', '.join(f'{MEDALLAS[f["puesto"]][0]} {nombre_publico(f["usuario"])} ({f["xp"]} XP)'
                                for f in ganadores)
        else:
            nombres = 'nadie sumó XP'
        partes.append(f'{ROLES_PLURAL[rol]}: {nombres}.')
    return f'Ranking de {nombre_mes} {anno}: ganadores', ' '.join(partes)


def avisar_cierre(mes_cerrado, clasificaciones):
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
            titulo, mensaje = texto_aviso(fila, rol, participantes, nombre_mes)
            avisos.append(Notificacion(titulo=titulo, mensaje=mensaje, destinatario=fila['usuario'],
                                       **referencia))

    titulo, mensaje = texto_resumen(clasificaciones, nombre_mes, mes_cerrado.anno)
    for fila in clasificaciones.get(Rol.ADMINISTRADOR, []):
        avisos.append(Notificacion(titulo=titulo, mensaje=mensaje, destinatario=fila['usuario'],
                                   clave_extra=CLAVE_RESUMEN, **referencia))

    Notificacion.objects.bulk_create(avisos)
    return len(avisos)
