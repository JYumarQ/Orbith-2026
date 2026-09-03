from django.db import migrations

# 'primer_movimiento_nomina' trataba como un solo caso tres flujos de negocio
# distintos (contratos/views.py: MovimientoUpdateView, solicitar_movimiento_nomina):
#   1. Movimiento interno: el mismo moderador marca "en proceso" un contrato
#      y también lo confirma, dentro de sus propias Unidades Organizativas.
#   2. Ceder un contrato: un moderador lo marca "en proceso" para que OTRO
#      moderador, dueño de la unidad de destino, lo reciba.
#   3. Recibir un contrato: el moderador de destino confirma el movimiento de
#      un contrato que no era originalmente suyo.
# Se reutiliza la fila existente (mismo id, conserva las TareaGuiaUsuario ya
# completadas por quienes ya hicieron un movimiento) para el caso 1, y se
# agregan dos filas nuevas para los otros dos.
TAREAS = [
    ('primer_movimiento_interno', 'Realiza tu primer movimiento de nómina',
     'Completaste un movimiento de nómina dentro de tus propias Unidades Organizativas.',
     'PRI', 'Contratos', 30,
     '/contrato/list_contrato/',
     'Ve a Contrato → Lista de Contratos.\n'
     'Haz clic en la fila del trabajador para seleccionarlo.\n'
     'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
     'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir": la fila queda resaltada en amarillo.\n'
     'Ve a Contrato → Mov. Nómina.\n'
     'Dentro de "Solicitudes Pendientes", haz clic en esa misma fila para seleccionarla.\n'
     'Pulsa "Confirmar Movimiento".\n'
     'Completa la Unidad Organizativa, el Departamento, el Cargo y la Fecha Efectiva del Movimiento (puedes repetir la misma unidad si solo cambias cargo o salario).\n'
     'Pulsa "Confirmar Movimiento" para guardar.'),

    ('primer_movimiento_cedido', 'Cede tu primer contrato a otro moderador',
     'Marcaste un contrato "en proceso" para que otro moderador lo incorpore a su unidad.',
     'PRI', 'Contratos', 31,
     '/contrato/list_contrato/',
     'Ve a Contrato → Lista de Contratos.\n'
     'Haz clic en la fila del trabajador que va a cambiar de unidad.\n'
     'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
     'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir".\n'
     'Listo: el contrato queda marcado "en proceso" (fila en amarillo) y disponible en la bandeja de movimientos pendientes para que el moderador que lo recibe lo complete desde su propia sesión.\n'
     'Si necesitas anular la solicitud, vuelve a esa fila (ahora en rojo) y pulsa "Cancelar Movimiento".'),

    ('primer_movimiento_recibido', 'Recibe tu primer contrato de otro moderador',
     'Confirmaste un movimiento de nómina de un contrato que otro moderador te cedió.',
     'PRI', 'Contratos', 32,
     '/contrato/movimientos/nomina/',
     'Ve a Contrato → Mov. Nómina.\n'
     'En "Solicitudes Pendientes" verás los contratos que cualquier moderador haya marcado "en proceso" en todo el sistema: busca al trabajador que esperas recibir.\n'
     'Haz clic en su fila para seleccionarla.\n'
     'Pulsa "Confirmar Movimiento".\n'
     'Elige tu Unidad Organizativa, Departamento y Cargo de destino (el desplegable de Unidad solo te mostrará las tuyas) y la Fecha Efectiva del Movimiento.\n'
     'Pulsa "Confirmar Movimiento" para guardar: el trabajador queda incorporado a tu unidad.'),
]

INSTRUCCIONES_ORIGINALES = (
    'Ve a Contrato → Mov. Nómina.\n'
    'Selecciona el trabajador al que vas a aplicar el movimiento.\n'
    'Ajusta los datos que cambian (cargo, salario, unidad u otros) y la fecha efectiva.\n'
    'Guarda el movimiento.'
)


def migrar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')

    codigo, titulo, descripcion, categoria, modulo, orden, url, instrucciones = TAREAS[0]
    TareaGuia.objects.filter(codigo='primer_movimiento_nomina').update(
        codigo=codigo, titulo=titulo, descripcion=descripcion,
        categoria=categoria, modulo=modulo, orden=orden,
        url_relacionada=url, instrucciones=instrucciones,
    )

    for codigo, titulo, descripcion, categoria, modulo, orden, url, instrucciones in TAREAS[1:]:
        TareaGuia.objects.update_or_create(
            codigo=codigo,
            defaults={
                'titulo': titulo, 'descripcion': descripcion,
                'categoria': categoria, 'modulo': modulo, 'orden': orden,
                'url_relacionada': url, 'instrucciones': instrucciones,
            },
        )


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo__in=['primer_movimiento_cedido', 'primer_movimiento_recibido']).delete()
    TareaGuia.objects.filter(codigo='primer_movimiento_interno').update(
        codigo='primer_movimiento_nomina',
        titulo='Registra tu primer movimiento de nómina',
        descripcion='Registraste un movimiento de nómina para un trabajador.',
        orden=30,
        url_relacionada='/contrato/movimientos/nomina/',
        instrucciones=INSTRUCCIONES_ORIGINALES,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0010_fix_campos_primera_contratacion'),
    ]

    operations = [
        migrations.RunPython(migrar, revertir),
    ]
