"""Rellena el «Otros» congelado de los movimientos que ya existían (24-10-2026).

Hasta hoy el documento del movimiento calculaba «Otros» al imprimirlo, con los
importes ACTUALES del contrato (Maestría + Doctorado + Instructor + CNCI). Desde
ahora se congela al crear el movimiento (`TMovimiento.otros_anterior` y
`otros_nuevo`) y suma también los Años de servicio.

Para que ningún documento ya emitido cambie de aspecto, aquí se guarda
EXACTAMENTE lo que mostraba hoy, con la fórmula antigua:

* movimientos y altas: el mismo importe en «De» y en «A», sacado del contrato
  enlazado (sin contrato, 0);
* bajas: «De» en 0 (el registro de baja no tiene esos importes) y «A» vacío (la
  baja no lleva fila «A»).

Solo rellena lo que está vacío, así que volver a ejecutarla no pisa nada.
"""

from decimal import Decimal

from django.db import migrations

CERO = Decimal('0.00')


def rellenar(apps, schema_editor):
    TMovimiento = apps.get_model('contratos', 'TMovimiento')
    CAlta = apps.get_model('contratos', 'CAlta')
    NImporteGradoCientifico = apps.get_model('nomencladores', 'NImporteGradoCientifico')

    grados = dict(NImporteGradoCientifico.objects.values_list('grado', 'importe'))
    otros_por_contrato = {}
    for contrato in CAlta.objects.select_related(
            'aspirante', 'instructor_nomenclador', 'cnci_nomenclador'):
        grado = contrato.aspirante.grado_cientifico if contrato.aspirante_id else None
        otros_por_contrato[contrato.pk] = (
            (grados.get(grado) or CERO)
            + (contrato.instructor_nomenclador.importe if contrato.instructor_nomenclador_id else CERO)
            + (contrato.cnci_nomenclador.importe if contrato.cnci_nomenclador_id else CERO))

    pendientes = TMovimiento.objects.filter(otros_anterior__isnull=True, otros_nuevo__isnull=True)
    for movimiento in pendientes.only('pk', 'tipo_movimiento', 'contrato_id'):
        if 'BAJA' in (movimiento.tipo_movimiento or '').upper():
            TMovimiento.objects.filter(pk=movimiento.pk).update(otros_anterior=CERO)
        else:
            valor = otros_por_contrato.get(movimiento.contrato_id, CERO)
            TMovimiento.objects.filter(pk=movimiento.pk).update(
                otros_anterior=valor, otros_nuevo=valor)


class Migration(migrations.Migration):

    dependencies = [
        ('contratos', '0026_confianza_modalidad_otros'),
        ('nomencladores', '0013_nimportegradocientifico_npagoadicional'),
    ]

    operations = [
        migrations.RunPython(rellenar, migrations.RunPython.noop),
    ]
