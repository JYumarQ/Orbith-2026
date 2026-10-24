"""Corrige el «salario anterior» de los movimientos de nómina ya registrados.

Se calculaba con la copia del rol que tenía el contrato (eliminada en la 0022), que un
movimiento anterior podía haber dejado con el rol de otro cargo. Decisión de RRHH del
23-10-2026: recalcularlo con la escala salarial de HOY, porque la escala no ha variado
desde que se usa Orbith, así que la de hoy es la que había en cada movimiento.

* Usa el grupo, el rol y el tridente que el propio movimiento guardó como «anteriores»
  (el rol ya se guardaba del cargo, era correcto).
* Solo movimientos de salario dinámico: en los de salario fijo el rol no influye.
* Si la combinación no está en la escala, el movimiento se deja como estaba.
* Protección: si Auditoría registra algún cambio real en la escala de un grupo, los
  movimientos de ese grupo NO se tocan (la escala de hoy ya no sería la de entonces).
"""

from decimal import Decimal

from django.db import migrations


def _grupos_con_escala_modificada(apps):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    EventoAuditoria = apps.get_model('auditoria', 'EventoAuditoria')
    tipo = ContentType.objects.filter(app_label='nomencladores', model='ngrupoescala').first()
    if tipo is None:
        return set()
    return {
        str(object_id)
        for object_id, antes, despues in EventoAuditoria.objects.filter(
            content_type=tipo, accion__in=('UPD', 'DEL')).values_list(
            'object_id', 'datos_antes', 'datos_despues')
        if antes != despues
    }


def recalcular_salario_anterior_de_movimientos(apps, schema_editor):
    TMovimiento = apps.get_model('contratos', 'TMovimiento')
    NGrupoEscala = apps.get_model('nomencladores', 'NGrupoEscala')
    NRol = apps.get_model('nomencladores', 'NRol')
    NTridente = apps.get_model('nomencladores', 'NTridente')
    NSalario = apps.get_model('nomencladores', 'NSalario')

    escala = {(g, r, t): m for g, r, t, m in NSalario.objects.values_list(
        'grupo_escala_id', 'rol_id', 'tridente_id', 'monto')}
    modificados = _grupos_con_escala_modificada(apps)
    grupos = {nivel: pk for nivel, pk in NGrupoEscala.objects.values_list('nivel', 'pk')
              if str(pk) not in modificados}
    roles = {tipo: pk for pk, tipo in NRol.objects.values_list('pk', 'tipo')}
    # El movimiento guarda el tridente como texto «Tridente I» (`str(NTridente)`).
    tridentes = {f'Tridente {tipo}': pk for pk, tipo in NTridente.objects.values_list('pk', 'tipo')}

    movimientos = (TMovimiento.objects
                   .filter(tipo_movimiento='Movimiento de Nómina', tipo_salario_anterior='Dinámico')
                   .values('pk', 'salario_anterior', 'grupo_escala_anterior', 'rol_anterior',
                           'tridente_anterior', 'cat_ocupacional_anterior'))
    for mov in movimientos:
        grupo = grupos.get((mov['grupo_escala_anterior'] or '').strip())
        if grupo is None:
            continue
        if (mov['cat_ocupacional_anterior'] or '').startswith('Cuadro'):
            # Un cuadro cobra sin tridente; respaldo: la escala del grupo sin rol.
            monto = (escala.get((grupo, roles.get(mov['rol_anterior']), None))
                     or escala.get((grupo, None, None)))
        else:
            rol = roles.get(mov['rol_anterior'])
            tridente = tridentes.get(mov['tridente_anterior'])
            if rol is None or tridente is None:
                continue
            monto = escala.get((grupo, rol, tridente))
        if not monto:
            continue
        monto = round(Decimal(monto), 2)
        if monto != mov['salario_anterior']:
            TMovimiento.objects.filter(pk=mov['pk']).update(salario_anterior=monto)


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contratos', '0022_quitar_rol_del_contrato'),
        ('auditoria', '0004_alter_eventoauditoria_accion'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(recalcular_salario_anterior_de_movimientos, sin_operacion),
    ]
