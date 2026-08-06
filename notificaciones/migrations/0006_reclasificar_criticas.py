"""Migración de datos: reclasifica a ALERTA las notificaciones de «críticas nuevas».

`notificaciones/receptores.py::avisar_criticas_nuevas` no fijaba `tipo` explícito antes
de esta ronda, así que las filas ya creadas cayeron en el default `EVENTO` aunque son
alertas de integridad (avisan de hallazgos críticos de Subsanación, no de un evento
informativo como un alta o un cargo nuevo). Se identifican por su `content_type`: es
el ÚNICO emisor que apunta a `subsanacion.EjecucionAnalisis` (el resto de notificaciones
apuntan al registro afectado — contrato, aspirante, cargo — nunca a una ejecución de
análisis).

No usa imports en vivo (misma práctica que `0005_backfill_destinatario.py`): resuelve
los modelos con `apps.get_model`.
"""

from django.db import migrations


def reclasificar_a_alerta(apps, schema_editor):
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    EjecucionAnalisis = apps.get_model('subsanacion', 'EjecucionAnalisis')

    tipo_ejecucion = ContentType.objects.filter(
        app_label=EjecucionAnalisis._meta.app_label,
        model=EjecucionAnalisis._meta.model_name,
    ).first()
    if tipo_ejecucion is None:
        return  # nunca se creó ninguna: nada que reclasificar.

    Notificacion.objects.filter(content_type=tipo_ejecucion, tipo='EVE').update(tipo='ALE')


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0005_backfill_destinatario'),
        ('subsanacion', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(reclasificar_a_alerta, migrations.RunPython.noop),
    ]
