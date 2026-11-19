"""Salud de los datos sin las reglas Informativas (19-11-2026, decisiones del usuario).

* Fórmula del índice, versión 3: no cuentan las Informativas (ni, como antes, Extras).
* Se recalcula con ella la nota del último análisis terminado, para que la nota
  general y las de cada categoría (que se calculan al vuelo) digan lo mismo hasta el
  próximo análisis. Se marca como versión 3: la gráfica de evolución empieza aquí,
  porque no se pueden comparar notas calculadas de dos formas.
* Se ocultan los avisos de las reglas desactivadas que seguían vivos: se desactivaron
  antes de la 3.9.0, que es la que empezó a ocultarlos al desactivar
  (`subsanacion.ocultar.ocultar_avisos_de`). Igual que allí: `vigente=False` sin
  tocar su estado ni `fecha_resolucion`, así que si se reactiva la regla vuelven los
  que sigan siendo ciertos.
"""

from decimal import Decimal

from django.db import migrations, models

#: Reglas Informativas y de Extras a fecha de esta migración (las mismas que en
#: `notificaciones/0016`, más las de Extras). Las que cambien después las calcula el
#: código de cada momento (`servicios.codigos_que_no_cuentan`).
NO_CUENTAN = (
    'ASP-005', 'ASP-006', 'ASP-008', 'ASP-009', 'CAL-003', 'CAL-004', 'CTR-012',
    'CTR-015', 'EST-004', 'EST-005', 'EST-006', 'EST-007', 'EXT-001', 'EXT-002',
    'MOV-006', 'USR-002', 'USR-003')
ABIERTOS = ('PEN', 'REV')
TERMINADAS = ('COM', 'PAR', 'FAL')


def adelante(apps, schema_editor):
    Hallazgo = apps.get_model('subsanacion', 'Hallazgo')
    EjecucionAnalisis = apps.get_model('subsanacion', 'EjecucionAnalisis')
    EstadoRegla = apps.get_model('subsanacion', 'EstadoRegla')

    desactivadas = list(EstadoRegla.objects.filter(activa=False).values_list('codigo', flat=True))
    Hallazgo.objects.filter(vigente=True, codigo_regla__in=desactivadas).update(vigente=False)

    ultima = (EjecucionAnalisis.objects.filter(estado__in=TERMINADAS, indice_salud__isnull=False)
              .order_by('-iniciada_en').first())
    if ultima is None or not ultima.codigos_regla_ejecutados:
        return
    codigos = [c for c in ultima.codigos_regla_ejecutados if c not in NO_CUENTAN]
    afectados = (Hallazgo.objects
                 .filter(vigente=True, estado__in=ABIERTOS, codigo_regla__in=codigos)
                 .order_by().values('content_type', 'object_id').distinct().count())
    base = max(int(ultima.registros_analizados or 0), 1)
    limpios = max(base - afectados, 0)
    ultima.indice_salud = (Decimal(limpios * 100) / Decimal(base)).quantize(Decimal('0.01'))
    ultima.version_indice = 3
    ultima.save(update_fields=['indice_salud', 'version_indice'])


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subsanacion', '0009_reglas_390'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ejecucionanalisis',
            name='version_indice',
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.RunPython(adelante, sin_operacion),
    ]
