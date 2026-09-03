from django.db import migrations

# 0011 no mencionaba la Fecha de Solicitud al describir el formulario de
# Movimiento de Nómina (movimiento_nomina.html), aunque el propio JS del
# template la trata como obligatoria junto con la Fecha Efectiva (ver
# `const obligatorios = ['tipo', 'tipo_salario', 'fecha_efectiva',
# 'fecha_solicitud']`). Afecta a 'primer_movimiento_interno' (el moderador
# hace las dos mitades) y a 'primer_movimiento_recibido' (el moderador de
# destino confirma): ambos pasan por el mismo formulario. 'primer_movimiento_cedido'
# no llega a ese formulario (solo marca "en proceso"), así que no aplica ahí.
TEXTOS_ANTERIORES = {
    'primer_movimiento_interno': (
        'Ve a Contrato → Lista de Contratos.\n'
        'Haz clic en la fila del trabajador para seleccionarlo.\n'
        'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
        'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir": la fila queda resaltada en amarillo.\n'
        'Ve a Contrato → Mov. Nómina.\n'
        'Dentro de "Solicitudes Pendientes", haz clic en esa misma fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Completa la Unidad Organizativa, el Departamento, el Cargo y la Fecha Efectiva del Movimiento (puedes repetir la misma unidad si solo cambias cargo o salario).\n'
        'Pulsa "Confirmar Movimiento" para guardar.'
    ),
    'primer_movimiento_recibido': (
        'Ve a Contrato → Mov. Nómina.\n'
        'En "Solicitudes Pendientes" verás los contratos que cualquier moderador haya marcado "en proceso" en todo el sistema: busca al trabajador que esperas recibir.\n'
        'Haz clic en su fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Elige tu Unidad Organizativa, Departamento y Cargo de destino (el desplegable de Unidad solo te mostrará las tuyas) y la Fecha Efectiva del Movimiento.\n'
        'Pulsa "Confirmar Movimiento" para guardar: el trabajador queda incorporado a tu unidad.'
    ),
}

TEXTOS_NUEVOS = {
    'primer_movimiento_interno': (
        'Ve a Contrato → Lista de Contratos.\n'
        'Haz clic en la fila del trabajador para seleccionarlo.\n'
        'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
        'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir": la fila queda resaltada en amarillo.\n'
        'Ve a Contrato → Mov. Nómina.\n'
        'Dentro de "Solicitudes Pendientes", haz clic en esa misma fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Completa la Unidad Organizativa, el Departamento, el Cargo, la Fecha Efectiva del Movimiento y la Fecha de Solicitud (puedes repetir la misma unidad si solo cambias cargo o salario): las dos fechas son obligatorias.\n'
        'Pulsa "Confirmar Movimiento" para guardar.'
    ),
    'primer_movimiento_recibido': (
        'Ve a Contrato → Mov. Nómina.\n'
        'En "Solicitudes Pendientes" verás los contratos que cualquier moderador haya marcado "en proceso" en todo el sistema: busca al trabajador que esperas recibir.\n'
        'Haz clic en su fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Elige tu Unidad Organizativa, Departamento y Cargo de destino (el desplegable de Unidad solo te mostrará las tuyas), y completa la Fecha Efectiva del Movimiento y la Fecha de Solicitud: las dos fechas son obligatorias.\n'
        'Pulsa "Confirmar Movimiento" para guardar: el trabajador queda incorporado a tu unidad.'
    ),
}


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, texto in TEXTOS_NUEVOS.items():
        TareaGuia.objects.filter(codigo=codigo).update(instrucciones=texto)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, texto in TEXTOS_ANTERIORES.items():
        TareaGuia.objects.filter(codigo=codigo).update(instrucciones=texto)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0011_split_movimiento_nomina'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
