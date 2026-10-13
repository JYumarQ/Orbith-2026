"""Migración de datos: borra las ALERTAS de la ficha de las personas que hoy están
de baja («Sin dirección», «Tallas incompletas»…). Desde el 13-10-2026 se borran al
causar baja (`notificaciones.receptores.borrar_avisos_del_contrato`) y el análisis
ya no las crea para ellas; esto limpia las que ya había. Los avisos de tipo Evento,
como «Baja de contrato», se conservan.
"""

from django.db import migrations


def borrar(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    Aspirante = apps.get_model('bolsa', 'Aspirante')

    tipo = ContentType.objects.filter(app_label='bolsa', model='aspirante').first()
    if tipo is None:
        return
    de_baja = [str(pk) for pk in Aspirante.objects.filter(estado='BAJA').values_list('pk', flat=True)]
    Notificacion.objects.filter(content_type=tipo, object_id__in=de_baja, tipo='ALE').delete()


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0013_borrar_avisos_de_contratos_inexistentes'),
        ('bolsa', '0009_nivel_educ_obligatorio'),
    ]

    operations = [migrations.RunPython(borrar, sin_operacion)]
