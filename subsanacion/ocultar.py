"""Ocultar y volver a mostrar los avisos de una regla desactivada (3.9.0, 09-11-2026).

Decisión de RRHH: al desactivar una regla, sus avisos dejan de verse en todas partes
(Hallazgos, triángulos, campana, Dashboard), pero NO se borran: al reactivarla vuelven
los que sigan siendo ciertos, con su estado y su historial de revisiones.

Cómo: sus hallazgos pasan a `vigente=False` SIN tocar `estado` ni `fecha_resolucion`.
Todo lo que muestra avisos ya mira solo los vigentes. Un hallazgo archivado de verdad
(corregido o retirado) tiene `fecha_resolucion`; uno oculto por la desactivación, no:
así se distinguen al reactivar. Las advertencias de la campana sí se borran: son una
copia por usuario que la búsqueda vuelve a crear en cuanto la regla está activa.
"""


def ocultar_avisos_de(codigo):
    from notificaciones.models import Notificacion

    from .models import Hallazgo

    ocultos = Hallazgo.objects.filter(codigo_regla=codigo, vigente=True).update(vigente=False)
    Notificacion.objects.filter(codigo_regla=codigo, tipo=Notificacion.Tipo.ALERTA).delete()
    return ocultos


def mostrar_avisos_de(regla):
    """Devuelve a la vista los ocultos y ejecuta la regla en el momento: los que ya no
    se detectan se cierran como Corregidos y aparecen los nuevos."""
    from .contexto import ContextoAnalisis
    from .models import Hallazgo
    from .servicios import reconciliar_regla

    Hallazgo.objects.filter(codigo_regla=regla.codigo, vigente=False,
                            fecha_resolucion__isnull=True).update(vigente=True)
    return reconciliar_regla(regla, None, ContextoAnalisis())
