from django.db import migrations

# Guía visual de exportar de Pre-Nómina (static/js/recorrido_prenomina.js).
CODIGO = 'exportar_prenomina'
ACCESOS = 'Ir a Pre-Nómina | /prenomina/ | exportar_prenomina:lista'
LINEA = (
    'En la lista de Reportes de Pago y dentro de cada reporte, "¿Cómo funciona?" → "Exportar un reporte a '
    'Excel" te acompaña paso a paso. El Excel se puede rellenar fuera y volver a subir con "Importar".'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if LINEA not in tarea.instrucciones:
        tarea.instrucciones = LINEA + '\n' + tarea.instrucciones
    tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ''
    tarea.instrucciones = tarea.instrucciones.replace(LINEA + '\n', '', 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0029_guia_exportar_anexos_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
