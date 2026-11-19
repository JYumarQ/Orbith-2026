"""Los contratos sin F. de Contratación (regla CTR-004) toman la de su Alta Inicial
(decisión de RRHH del 18-11-2026).

La F. de Contratación es la fecha del Alta Inicial del histórico. Si el contrato no la
tiene pero su histórico tiene EXACTAMENTE un Alta Inicial de ese contrato, la fecha se
sabe con certeza y se copia. Con ninguna o con varias no se toca: lo corrige el
Administrador en el editor del histórico (el aviso de CTR-004 le lleva allí).

En la empresa había uno solo (expediente 70486): sin fecha, su histórico daba error.

Antes, el tipo «Alta inicial» (con minúscula) pasa a «Alta Inicial»: con la minúscula,
MOV-014 decía que al contrato le faltaba el Alta y el histórico la enseñaba como un
movimiento (expediente 76171). Solo cambia el nombre del tipo.

Cada cambio queda en Auditoría, firmado por «Sistema».
"""
from django.db import migrations


def normalizar_tipo_alta(apps):
    TMovimiento = apps.get_model('contratos', 'TMovimiento')
    EventoAuditoria = apps.get_model('auditoria', 'EventoAuditoria')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    tipo_movimiento = ContentType.objects.filter(app_label='contratos', model='tmovimiento').first()
    raros = (TMovimiento.objects.filter(tipo_movimiento__iexact='alta inicial')
             .exclude(tipo_movimiento='Alta Inicial'))
    for movimiento in raros:
        antes = movimiento.tipo_movimiento
        TMovimiento.objects.filter(pk=movimiento.pk).update(tipo_movimiento='Alta Inicial')
        EventoAuditoria.objects.create(
            usuario=None, usuario_nombre='Sistema', accion='UPD', modulo='contratos',
            content_type=tipo_movimiento, object_id=str(movimiento.pk),
            descriptor=(f'Tipo del movimiento del expediente {movimiento.no_expediente} escrito '
                        f'como «Alta Inicial» (estaba «{antes}»).')[:200],
            datos_antes={'Tipo de movimiento': antes},
            datos_despues={'Tipo de movimiento': 'Alta Inicial'},
        )


def rellenar(apps, schema_editor):
    normalizar_tipo_alta(apps)

    CAlta = apps.get_model('contratos', 'CAlta')
    TMovimiento = apps.get_model('contratos', 'TMovimiento')
    EventoAuditoria = apps.get_model('auditoria', 'EventoAuditoria')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    tipo_contrato = ContentType.objects.filter(app_label='contratos', model='calta').first()
    for contrato in CAlta.objects.filter(fecha_alta__isnull=True):
        fechas = list(TMovimiento.objects.filter(
            contrato_id=contrato.pk, tipo_movimiento='Alta Inicial',
        ).values_list('fecha_efectiva', flat=True))
        if len(fechas) != 1:
            continue
        CAlta.objects.filter(pk=contrato.pk).update(fecha_alta=fechas[0])
        EventoAuditoria.objects.create(
            usuario=None, usuario_nombre='Sistema', accion='UPD', modulo='contratos',
            content_type=tipo_contrato, object_id=str(contrato.pk),
            descriptor=(f'F. de Contratación del expediente {contrato.no_expediente} tomada '
                        f'de su Alta Inicial (el contrato no la tenía).')[:200],
            datos_antes={'F. de Contratación': '—'},
            datos_despues={'F. de Contratación': fechas[0].strftime('%d/%m/%Y')},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('contratos', '0030_escrito_a_mano_en_movimiento'),
        ('auditoria', '0006_alter_eventoauditoria_accion'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(rellenar, migrations.RunPython.noop),
    ]
