"""Mantiene al día quién lleva cada subunidad.

Una subunidad no se asigna por separado: se asigna su Unidad Principal y las
subunidades entran con ella (ver el bloque de `usuarios/forms.py`). Esa
expansión ocurre al guardar el USUARIO, así que por sí sola solo cubre las
subunidades que ya existían en ese momento.

Aquí se cubre el otro lado: cuando nace una subunidad —o cuando se muda a otro
padre— hay que repartirla igual que su padre, sin esperar a que alguien recuerde
reabrir la ficha del moderador y volver a guardarla. Sin esto, una subunidad
recién creada se quedaría sin moderador y **nadie podría declarar su cierre**,
porque `cierres.permisos.puede_declarar` exige tenerla asignada y niega declarar
directamente la Unidad Principal.

La regla que se aplica es exactamente el invariante que valida el formulario:
    *quien lleva la subunidad = quien lleva a su padre*

Se recalcula entero con `set()` en vez de solo añadir, porque así el mismo
código resuelve los tres casos —alta, cambio de padre y corrección de datos
incoherentes— y el resultado no depende de cuántas veces se ejecute.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UnidadOrganizativa


@receiver(post_save, sender=UnidadOrganizativa)
def sincronizar_titulares_de_subunidad(sender, instance, raw=False, **kwargs):
    """Reparte la subunidad entre quienes tengan asignado a su padre."""
    # `raw=True` es una carga de fixtures (`loaddata`): la base todavía está a
    # medio poblar y tocar relaciones aquí puede fallar o dejar datos raros.
    if raw:
        return

    # Solo las subunidades tienen padre. Una principal o una independiente se
    # asignan a mano y no hay nada que propagar.
    if not instance.padre_id:
        return

    from usuarios.models import CustomUser

    titulares = CustomUser.objects.filter(unidades=instance.padre_id)
    # Reverse del ManyToMany `CustomUser.unidades`, que no declara `related_name`.
    instance.customuser_set.set(titulares)
