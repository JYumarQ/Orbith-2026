"""Migración de datos: recodifica las notificaciones de alta/baja de contrato, cargo
nuevo y críticas de Subsanación creadas antes de que estos 3 productores empezaran a
pasar un `codigo_regla` real.

Los tres seguían escribiendo con `Notificacion.objects.bulk_create()` directo y
`codigo_regla=''` (el valor por defecto de un EVENTO), sin ninguna clave natural que
las protegiera de la `UniqueConstraint` de `Notificacion.Meta` (que solo cubre
`codigo_regla != ''`) — el mismo hueco que causó los avisos de Solicitud duplicados en
producción, corregido para ese módulo en la migración 0010. Ahora
`notificaciones/avisos.py::avisar_alta_contrato/avisar_baja_contrato/avisar_nuevo_cargo`
y `notificaciones/receptores.py::avisar_criticas_nuevas` pasan un `codigo_regla` real
y reutilizan `_registrar_notificacion`. Esta migración pone al día las filas que ya
existían antes de ese cambio.

Deduplicación por productor:

* `EVT-ALTA` y `EVT-CARGO`: `object_id` (pk del contrato / del cargo) ya es único por
  evento — se agrupan por `(object_id, destinatario)` y se colapsan los duplicados que
  la carrera de escritura haya podido crear, igual que hizo 0009/0010.
* `ALE-CRITICAS`: `object_id` (pk de la `EjecucionAnalisis`) también es único por
  ejecución — mismo criterio.
* `EVT-BAJA`: **no se colapsa nada.** `object_id` es el `Aspirante`, que puede tener
  varias bajas reales a lo largo del tiempo (recontratación) con el mismo destinatario
  — agrupar solo por `(object_id, destinatario)` fusionaría bajas distintas de la misma
  persona, perdiendo historial real. Sin una forma fiable de reconstruir a qué `CAlta`
  concreta pertenecía cada fila histórica, la opción segura es darle a cada una su
  propio `clave_extra` (el id de la propia fila): nunca colisiona con otra, así que
  queda protegida hacia adelante sin arriesgar fusionar nada hacia atrás.
"""

from django.db import migrations

ORDEN_ESTADO = {'ACT': 0, 'RES': 1, 'DES': 1}


def _content_type(ContentType, modelo):
    return ContentType.objects.filter(
        app_label=modelo._meta.app_label, model=modelo._meta.model_name).first()


def _recodificar_con_dedup(Notificacion, tipo_ct, titulo, codigo):
    """Para EVT-ALTA / EVT-CARGO / ALE-CRITICAS: `object_id` ya es único por evento,
    así que agrupar y colapsar por `(object_id, destinatario)` es seguro."""
    filas = (Notificacion.objects
             .filter(content_type=tipo_ct, codigo_regla='', titulo=titulo)
             .order_by('id')
             .values('id', 'object_id', 'destinatario_id', 'estado', 'leido'))

    grupos = {}
    for fila in filas:
        clave = (fila['object_id'], fila['destinatario_id'])
        grupos.setdefault(clave, []).append(fila)

    ids_a_borrar = []
    ids_ganadores = []
    for filas_grupo in grupos.values():
        ganadora = min(
            filas_grupo,
            key=lambda f: (ORDEN_ESTADO.get(f['estado'], 2), not f['leido'], -f['id']))
        ids_ganadores.append(ganadora['id'])
        ids_a_borrar.extend(f['id'] for f in filas_grupo if f['id'] != ganadora['id'])

    if ids_a_borrar:
        Notificacion.objects.filter(id__in=ids_a_borrar).delete()
    if ids_ganadores:
        Notificacion.objects.filter(id__in=ids_ganadores).update(codigo_regla=codigo)


def _recodificar_sin_dedup(Notificacion, tipo_ct, titulo, codigo):
    """Para EVT-BAJA: cada fila conserva su propio `clave_extra` (su propio id), sin
    intentar colapsar nada — ver docstring del módulo."""
    for fila_id in (Notificacion.objects
                     .filter(content_type=tipo_ct, codigo_regla='', titulo=titulo)
                     .values_list('id', flat=True)):
        Notificacion.objects.filter(id=fila_id).update(
            codigo_regla=codigo, clave_extra=str(fila_id))


def recodificar(apps, schema_editor):
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    CAlta = apps.get_model('contratos', 'CAlta')
    Aspirante = apps.get_model('bolsa', 'Aspirante')
    CargoPlantilla = apps.get_model('strorganizativa', 'CargoPlantilla')
    EjecucionAnalisis = apps.get_model('subsanacion', 'EjecucionAnalisis')

    tipo_calta = _content_type(ContentType, CAlta)
    if tipo_calta is not None:
        _recodificar_con_dedup(
            Notificacion, tipo_calta, 'Nuevo contrato de alta', 'EVT-ALTA')

    tipo_aspirante = _content_type(ContentType, Aspirante)
    if tipo_aspirante is not None:
        _recodificar_sin_dedup(
            Notificacion, tipo_aspirante, 'Baja de contrato', 'EVT-BAJA')

    tipo_cargo = _content_type(ContentType, CargoPlantilla)
    if tipo_cargo is not None:
        _recodificar_con_dedup(
            Notificacion, tipo_cargo, 'Nuevo Cargo creado', 'EVT-CARGO')

    tipo_ejecucion = _content_type(ContentType, EjecucionAnalisis)
    if tipo_ejecucion is not None:
        # El título trae un conteo dinámico ("3 hallazgos críticos nuevos"), así que no
        # se puede filtrar por texto exacto — se agrupan todas las filas EVENTO sin
        # codigo_regla de este content_type, sean cuales sean sus títulos.
        filas = (Notificacion.objects
                 .filter(content_type=tipo_ejecucion, codigo_regla='')
                 .order_by('id')
                 .values('id', 'object_id', 'destinatario_id', 'estado', 'leido'))
        grupos = {}
        for fila in filas:
            clave = (fila['object_id'], fila['destinatario_id'])
            grupos.setdefault(clave, []).append(fila)
        ids_a_borrar = []
        ids_ganadores = []
        for filas_grupo in grupos.values():
            ganadora = min(
                filas_grupo,
                key=lambda f: (ORDEN_ESTADO.get(f['estado'], 2), not f['leido'], -f['id']))
            ids_ganadores.append(ganadora['id'])
            ids_a_borrar.extend(f['id'] for f in filas_grupo if f['id'] != ganadora['id'])
        if ids_a_borrar:
            Notificacion.objects.filter(id__in=ids_a_borrar).delete()
        if ids_ganadores:
            Notificacion.objects.filter(id__in=ids_ganadores).update(codigo_regla='ALE-CRITICAS')


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0010_recodificar_avisos_de_solicitud'),
        ('contratos', '0016_calta_calta_fijo_sin_tridente'),
        ('bolsa', '0007_remove_aspirante_contratado'),
        ('strorganizativa', '0013_alter_unidadorganizativa_unique_orden_por_rama'),
        ('subsanacion', '0004_ejecucionanalisis_codigos_regla_ejecutados'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(recodificar, sin_operacion),
    ]
