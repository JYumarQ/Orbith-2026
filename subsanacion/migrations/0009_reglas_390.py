"""Subsanación 3.9.0 (decisiones de RRHH del 09-11-2026), aplicadas a los datos ya guardados.

1. Las reglas de Pre-Nómina quedan DESACTIVADAS (todavía no se usa): CAL-101, CAL-102 y
   PNM-002. Sus avisos se ocultan sin borrarse (ver `subsanacion.ocultar`).
2. Los hallazgos y advertencias ya guardados toman la gravedad nueva de su regla; si no,
   conservarían la antigua hasta el siguiente análisis.
3. Las advertencias Informativas desaparecen de la campana: desde la 3.9.0 una regla
   Informativa solo se ve en Subsanación.

Solo cambia avisos: ningún dato de contratos, personas ni plantilla.
"""
from django.db import migrations

PRENOMINA = ('CAL-101', 'CAL-102', 'PNM-002')

CRITICA, ALTA, MEDIA, INFORMATIVA = 10, 20, 30, 50
GRAVEDADES = {
    'ASP-006': INFORMATIVA, 'ASP-008': INFORMATIVA, 'ASP-009': INFORMATIVA,
    'CAL-003': INFORMATIVA, 'CAL-004': INFORMATIVA,
    'EST-004': INFORMATIVA, 'EST-005': INFORMATIVA, 'EST-006': INFORMATIVA, 'EST-007': INFORMATIVA,
    'CTR-012': INFORMATIVA, 'CTR-015': INFORMATIVA, 'USR-002': INFORMATIVA,
    'CTR-002': CRITICA, 'CTR-005': ALTA, 'CTR-009': MEDIA,
    'SAL-001': CRITICA, 'CTR-008': CRITICA,
    'VIS-007': MEDIA, 'VIS-008': MEDIA, 'CIE-001': MEDIA,
}


def aplicar(apps, schema_editor):
    EstadoRegla = apps.get_model('subsanacion', 'EstadoRegla')
    Hallazgo = apps.get_model('subsanacion', 'Hallazgo')
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    alerta = 'ALE'

    for codigo in PRENOMINA:
        estado, _ = EstadoRegla.objects.get_or_create(codigo=codigo)
        if estado.activa:
            estado.activa = False
            estado.motivo = 'Pre-Nómina todavía no se usa (versión 3.9.0).'
            estado.save(update_fields=['activa', 'motivo'])
        Hallazgo.objects.filter(codigo_regla=codigo, vigente=True).update(vigente=False)
        Notificacion.objects.filter(codigo_regla=codigo, tipo=alerta).delete()

    for codigo, criticidad in GRAVEDADES.items():
        Hallazgo.objects.filter(codigo_regla=codigo).update(criticidad=criticidad)
        Notificacion.objects.filter(codigo_regla=codigo, tipo=alerta).update(severidad=criticidad)

    Notificacion.objects.filter(tipo=alerta, severidad=INFORMATIVA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subsanacion', '0008_estado_de_reglas'),
        ('notificaciones', '0014_borrar_alertas_de_fichas_de_baja'),
    ]

    operations = [
        migrations.RunPython(aplicar, migrations.RunPython.noop),
    ]
