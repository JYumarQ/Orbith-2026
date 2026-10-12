"""Tabla de puntos del Ranking Mensual Orbith (aprobada el 07-10-2026).

Para cada rol: {actividad: (XP por acción, tope diario de acciones que dan XP)}.
Un tope `None` es "sin tope". Lo que pasa del tope se guarda igual (cuenta en
el uso) pero con 0 XP. Una actividad que no está en la tabla de un rol no se
registra para ese rol.
"""
from .models import Actividad, Rol

# XP del "Día con actividad": se da una sola vez al día, con la primera
# actividad registrada.
XP_DIA_ACTIVO = 2

_COMUNES = {
    Actividad.INFORME: (1, 10),
    Actividad.DESCARGA: (1, 10),
}

PUNTOS = {
    Rol.MODERADOR: {
        Actividad.ASPIRANTE: (3, 20),
        Actividad.ALTA: (10, 15),
        Actividad.MOVIMIENTO: (8, 15),
        Actividad.ENVIO_MOVIMIENTO: (4, 10),
        Actividad.BAJA: (8, 15),
        Actividad.SOLICITUD_APROBADA: (6, 10),
        Actividad.CIERRE_EN_PLAZO: (20, None),
        Actividad.HALLAZGO_REVISADO: (3, 20),
        Actividad.RECORDATORIO_COMPLETADO: (5, 10),
        **_COMUNES,
    },
    Rol.ADMINISTRADOR: {
        Actividad.SOLICITUD_DECIDIDA: (4, 20),
        Actividad.ANALISIS_SUBSANACION: (5, 1),
        Actividad.RECORDATORIO_CREADO: (2, 5),
        **_COMUNES,
    },
    Rol.OBSERVADOR: dict(_COMUNES),
}

# Umbrales de XP de cada nivel del mes (Inicial, Activo, Destacado, Experto).
NIVELES = ('Inicial', 'Activo', 'Destacado', 'Experto')
UMBRALES = {
    Rol.MODERADOR: (0, 50, 150, 300),
    Rol.ADMINISTRADOR: (0, 40, 120, 250),
    Rol.OBSERVADOR: (0, 15, 40, 80),
}


def nivel_de(rol, xp):
    """Nombre del nivel que alcanza `xp` en `rol`."""
    nivel = NIVELES[0]
    for nombre, minimo in zip(NIVELES, UMBRALES.get(rol, UMBRALES[Rol.MODERADOR])):
        if xp >= minimo:
            nivel = nombre
    return nivel
