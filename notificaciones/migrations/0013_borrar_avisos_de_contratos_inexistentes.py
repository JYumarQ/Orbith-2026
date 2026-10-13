"""Migración de datos: borra los avisos que apuntan a un contrato vivo (`CAlta`)
que ya no existe. Se quedaban activos al causar baja el trabajador (su contrato se
borra) y su enlace daba un error 404. A partir de ahora los borra
`notificaciones.receptores.borrar_avisos_del_contrato` en el momento de la baja;
esto limpia los que ya había (decisión de RRHH del 13-10-2026).
"""

from django.db import migrations


def borrar(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    CAlta = apps.get_model('contratos', 'CAlta')

    tipo = ContentType.objects.filter(app_label='contratos', model='calta').first()
    if tipo is None:
        return
    vivos = {str(pk) for pk in CAlta.objects.values_list('pk', flat=True)}
    huerfanas = [n.pk for n in Notificacion.objects.filter(content_type=tipo).only('pk', 'object_id')
                 if n.object_id not in vivos]
    Notificacion.objects.filter(pk__in=huerfanas).delete()


def sin_operacion(apps, schema_editor):
    # No hay forma de recuperar lo borrado.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0012_resolver_cumpleanos_y_jubilacion_existentes'),
        ('contratos', '0021_mision_solo_en_calta_dias_importe'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(borrar, sin_operacion)]
