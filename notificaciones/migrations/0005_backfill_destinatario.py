"""Migración de datos: reparte las notificaciones históricas "por unidad" a personas.

Solo toca filas con `destinatario` vacío y `unidad` poblada (las creadas por las dos
vías anteriores a este cambio: alta de cargo y nueva solicitud). Política, decidida
con el usuario dado que hoy hay pocos moderadores y la app aún no está desplegada del
todo (se acepta perder trazabilidad fina en estos históricos en vez de dejarlos
pendientes de revisión manual):

  * Si la unidad tiene EXACTAMENTE un destinatario resoluble (su moderador, o un
    administrador si no hay moderador), se le asigna directo.
  * Si hay cero o varios (varios administradores, o ningún moderador y ningún
    administrador), se asigna a TODOS los administradores activos como respaldo
    simple, para no dejar ninguna alerta histórica sin que nadie la vea.

No usa imports en vivo de `notificaciones`/`usuarios` (la app puede cambiar después de
esta migración): resuelve los modelos con `apps.get_model`, siguiendo la práctica
estándar de Django para migraciones de datos.
"""

from django.db import migrations


def repartir_destinatarios(apps, schema_editor):
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    CustomUser = apps.get_model('usuarios', 'CustomUser')

    admins_activos = list(CustomUser.objects.filter(es_admin=True, is_active=True))

    huerfanas = Notificacion.objects.filter(
        destinatario__isnull=True, unidad__isnull=False)

    for notificacion in huerfanas:
        moderadores = list(CustomUser.objects.filter(
            es_moderador=True, is_active=True, unidades=notificacion.unidad_id))

        if len(moderadores) == 1:
            notificacion.destinatario = moderadores[0]
            notificacion.save(update_fields=['destinatario'])
            continue

        # Cero o varios moderadores: respaldo simple, todos los administradores.
        # Se actualiza la fila original con el primer admin y se clonan copias para
        # el resto, para no perder a nadie sin multiplicar filas más de lo necesario.
        destinatarios = moderadores + admins_activos
        if not destinatarios:
            continue  # no hay a quién asignarla; se deja huérfana, se pierde en la práctica.

        primero, *resto = destinatarios
        notificacion.destinatario = primero
        notificacion.save(update_fields=['destinatario'])

        for destinatario in resto:
            Notificacion.objects.create(
                titulo=notificacion.titulo,
                mensaje=notificacion.mensaje,
                fecha_creado=notificacion.fecha_creado,
                leido=notificacion.leido,
                tipo=notificacion.tipo,
                estado=notificacion.estado,
                fecha_resolucion=notificacion.fecha_resolucion,
                severidad=notificacion.severidad,
                codigo_regla=notificacion.codigo_regla,
                clave_extra=notificacion.clave_extra,
                content_type=notificacion.content_type,
                object_id=notificacion.object_id,
                unidad=notificacion.unidad,
                destinatario=destinatario,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0004_notificacion_tipo_severidad_estado'),
        ('usuarios', '0003_customuser_avatar_preferenciasusuario'),
    ]

    operations = [
        migrations.RunPython(repartir_destinatarios, migrations.RunPython.noop),
    ]
