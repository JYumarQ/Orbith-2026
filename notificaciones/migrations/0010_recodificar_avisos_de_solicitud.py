"""Migración de datos: recodifica y deduplica los avisos de Solicitudes.

`solicitudes/avisos.py` creaba estas filas con `bulk_create()` y `codigo_regla=''` (el
valor por defecto de un EVENTO) — sin ninguna clave natural que las protegiera de la
`UniqueConstraint` de `Notificacion.Meta` (que solo cubre `codigo_regla != ''`), así que
un doble envío, un reintento de red o varios workers concurrentes podían crear varias
filas para el MISMO aviso — el bug reportado en producción: una solicitud nueva le
aparecía repetida (hasta 8 veces) a cada administrador.

Ahora `_crear()` pasa un `codigo_regla` real (`SOL-NUEVA`/`SOL-DECISION`/
`SOL-REABIERTA`, ver `solicitudes/avisos.py`) y reutiliza
`notificaciones.avisos._registrar_notificacion`, con lo que las filas NUEVAS quedan
protegidas por esa restricción. Esta migración pone al día las filas que ya existían
antes de ese cambio:

1. Identifica su fase por el `titulo` (único emisor de esos textos exactos).
2. Colapsa los duplicados que la carrera de escritura ya haya podido crear (misma
   lógica de desempate que `0009_deduplicar_y_restringir_notificaciones`: se conserva
   la fila ACTIVA y leída más reciente).
3. Les asigna el `codigo_regla` que les corresponde, para que de aquí en adelante
   también estén protegidas por la restricción.

No usa imports en vivo (misma práctica que `0006_reclasificar_criticas`): resuelve los
modelos con `apps.get_model`.
"""

from django.db import migrations

#: Los únicos 4 textos que `solicitudes/avisos.py` ha usado como `titulo` para estos
#: avisos (ver `avisar_nueva_solicitud`/`avisar_decision`/`avisar_devuelta_a_espera`).
#: "aprobada" y "rechazada" comparten código porque son la MISMA fase (decisión) — un
#: aviso de decisión se reemplaza por el siguiente, nunca convive con el anterior.
MAPEO_CODIGO_POR_TITULO = {
    'Nueva Solicitud Pendiente': 'SOL-NUEVA',
    'Solicitud aprobada': 'SOL-DECISION',
    'Solicitud rechazada': 'SOL-DECISION',
    'Solicitud reabierta': 'SOL-REABIERTA',
}

ORDEN_ESTADO = {'ACT': 0, 'RES': 1, 'DES': 1}


def recodificar_y_deduplicar(apps, schema_editor):
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Solicitud = apps.get_model('solicitudes', 'Solicitud')

    tipo_solicitud = ContentType.objects.filter(
        app_label=Solicitud._meta.app_label, model=Solicitud._meta.model_name,
    ).first()
    if tipo_solicitud is None:
        return  # nunca se creó ninguna Solicitud: nada que recodificar.

    filas = (Notificacion.objects
             .filter(content_type=tipo_solicitud, codigo_regla='')
             .order_by('id')
             .values('id', 'object_id', 'destinatario_id', 'titulo', 'estado', 'leido'))

    grupos = {}
    for fila in filas:
        codigo = MAPEO_CODIGO_POR_TITULO.get(fila['titulo'])
        if codigo is None:
            continue  # título no reconocido (aviso de otro origen): no se toca.
        clave = (fila['object_id'], fila['destinatario_id'], codigo)
        grupos.setdefault(clave, []).append(fila)

    ids_a_borrar = []
    ids_por_codigo = {}  # codigo_regla -> [ids ganadores]
    for clave, filas_grupo in grupos.items():
        _object_id, _destinatario_id, codigo = clave
        ganadora = min(
            filas_grupo,
            key=lambda f: (ORDEN_ESTADO.get(f['estado'], 2), not f['leido'], -f['id']))
        ids_por_codigo.setdefault(codigo, []).append(ganadora['id'])
        ids_a_borrar.extend(f['id'] for f in filas_grupo if f['id'] != ganadora['id'])

    if ids_a_borrar:
        Notificacion.objects.filter(id__in=ids_a_borrar).delete()

    for codigo, ids in ids_por_codigo.items():
        Notificacion.objects.filter(id__in=ids).update(codigo_regla=codigo)


def sin_operacion(apps, schema_editor):
    # No hay un "deshacer" razonable: recodificar de vuelta a codigo_regla='' es
    # posible, pero las filas ya colapsadas por la deduplicación no vuelven.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0009_deduplicar_y_restringir_notificaciones'),
        ('solicitudes', '0004_solicitud_delete_solicitudcargo_and_more'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(recodificar_y_deduplicar, sin_operacion),
    ]
