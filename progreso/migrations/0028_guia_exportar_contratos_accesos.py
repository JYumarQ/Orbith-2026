from django.db import migrations

# Guías visuales de exportar de Contratos (static/js/recorrido_exportar_contratos.js).
# Se añaden los accesos y una línea al principio de los pasos escritos.
CAMBIOS = {
    'exportar_lista_contratos': {
        'accesos': 'Ir a Contratos | /contrato/list_contrato/ | exportar_lista_contratos:contratos',
        'linea': 'En Contratos, "¿Cómo funciona?" → "Lista de contratos a Excel" te acompaña paso a paso.',
    },
    'exportar_contrato_modificacion': {
        'accesos': (
            'Desde Contratos | /contrato/list_contrato/ | exportar_contrato_modificacion:contratos\n'
            'Desde el Gestor | /estructuras/gestor/ | exportar_contrato_modificacion:gestor'
        ),
        'linea': (
            'En Contratos o en el Gestor de Plantilla, "¿Cómo funciona?" → "Contrato de Trabajo y Modificación" te '
            'acompaña hasta el Asistente de Exportación Legal, que tiene su propio "¿Cómo funciona?" para '
            'rellenarlo campo a campo.'
        ),
    },
    'exportar_movimiento_nomina': {
        'accesos': (
            'Desde Contratos | /contrato/list_contrato/ | exportar_movimiento_nomina:contratos\n'
            'Desde el Gestor | /estructuras/gestor/ | exportar_movimiento_nomina:gestor'
        ),
        'linea': (
            'En Contratos o en el Gestor de Plantilla, "¿Cómo funciona?" → "Movimiento de nómina (Word)" te acompaña '
            'paso a paso. El histórico también se abre con doble clic en Mov. Nómina, Aspirantes y Bajas.'
        ),
    },
    'exportar_historico_trabajador': {
        'accesos': (
            'Desde Contratos | /contrato/list_contrato/ | exportar_historico_trabajador:contratos\n'
            'Desde el Gestor | /estructuras/gestor/ | exportar_historico_trabajador:gestor'
        ),
        'linea': (
            'En Contratos o en el Gestor de Plantilla, "¿Cómo funciona?" → "Histórico del trabajador (PDF)" te '
            'acompaña paso a paso. El histórico también se abre con doble clic en Mov. Nómina, Aspirantes y Bajas.'
        ),
    },
}


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, cambio in CAMBIOS.items():
        tarea = TareaGuia.objects.filter(codigo=codigo).first()
        if not tarea:
            continue
        tarea.accesos = cambio['accesos']
        if cambio['linea'] not in tarea.instrucciones:
            tarea.instrucciones = cambio['linea'] + '\n' + tarea.instrucciones
        tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, cambio in CAMBIOS.items():
        tarea = TareaGuia.objects.filter(codigo=codigo).first()
        if not tarea:
            continue
        tarea.accesos = ''
        tarea.instrucciones = tarea.instrucciones.replace(cambio['linea'] + '\n', '', 1)
        tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0027_guia_tareas_exportar'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
