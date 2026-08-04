"""Resolución de a quién dirigir una notificación ligada a una unidad organizativa.

Hoy la relación real es 1 moderador por unidad (además de los administradores, que
tienen control absoluto sobre toda la app, incluidas todas las unidades) — así que
"destinatarios de una unidad" es, en el caso normal, un conjunto pequeño y estable.
"""

from django.db.models import Q


def destinatarios_de_unidad(unidad):
    """Moderador(es) de `unidad` + todos los administradores activos, sin duplicados.

    Devuelve un queryset de `CustomUser`. Puede estar vacío si la unidad no tiene
    moderador y no hay ningún administrador activo (caso límite); quien llame a esta
    función debe decidir qué hacer si el resultado está vacío (típicamente, registrar
    un aviso en el log en vez de fallar).
    """
    from usuarios.models import CustomUser

    if unidad is None:
        return CustomUser.objects.none()

    return CustomUser.objects.filter(
        Q(es_moderador=True, unidades=unidad) | Q(es_admin=True),
        is_active=True,
    ).distinct()
