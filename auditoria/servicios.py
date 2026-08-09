"""Único punto de escritura de EventoAuditoria. Mismo criterio que
`solicitudes/servicios.py`: nadie más crea filas de este modelo directamente.

`registrar()` es deliberadamente "tonto": no decide QUÉ auditar ni construye las
fotografías antes/después — eso lo sabe el módulo que llama (hoy,
`solicitudes/servicios.py`, que ya tiene `serializacion.capturar()` para eso). Aquí
solo se resuelve el `content_type`/`object_id` a partir de lo que llegue y se
persiste el hecho.
"""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from auditoria.models import EventoAuditoria


@transaction.atomic
def registrar(*, usuario, accion, content_type=None, object_id=None, instancia=None,
               datos_antes=None, datos_despues=None, solicitud=None, descriptor='',
               unidad=None, modulo='solicitudes'):
    """Registra un hecho de auditoría. Todo por keyword.

    Resolución de `content_type`/`object_id`, en orden de prioridad:
    1. Si se pasan explícitos, se usan tal cual (necesario para ELIMINAR: el objeto
       ya no tiene pk después de `.delete()`, así que el llamador pasa el id
       congelado).
    2. Si se pasa `instancia` con pk, se derivan de ella.
    3. Si hay `solicitud`, se heredan de `solicitud.content_type`/`solicitud.object_id`.
    """
    if content_type is None and instancia is not None and instancia.pk is not None:
        content_type = ContentType.objects.get_for_model(type(instancia))
        object_id = str(instancia.pk)
    if content_type is None and solicitud is not None:
        content_type = solicitud.content_type
        object_id = solicitud.object_id
    if unidad is None and solicitud is not None:
        unidad = solicitud.unidad
    if not descriptor and solicitud is not None:
        descriptor = solicitud.descriptor

    nombre_usuario = ''
    if usuario is not None:
        nombre_usuario = usuario.get_full_name() or usuario.username

    return EventoAuditoria.objects.create(
        usuario=usuario,
        usuario_nombre=nombre_usuario,
        accion=accion,
        modulo=modulo,
        content_type=content_type,
        object_id=str(object_id) if object_id not in (None, '') else None,
        descriptor=(descriptor or '')[:200],
        datos_antes=datos_antes or {},
        datos_despues=datos_despues or {},
        unidad=unidad,
        solicitud=solicitud,
    )
