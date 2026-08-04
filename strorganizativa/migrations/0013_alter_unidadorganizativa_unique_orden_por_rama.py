from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Corrige unique_orden_por_rama (UnidadOrganizativa): la restricción original
    (migración 0011) incluía nulls_distinct=False, distinto de sus dos
    restricciones hermanas (Departamento, CargoPlantilla), que nunca lo usaron.
    Eso hace que varias unidades sin orden_informe asignado bajo el mismo padre
    choquen entre sí como si fueran duplicados, y Postgres rechaza crear la
    restricción.

    Se usa RunSQL en vez de un ALTER normal porque en producción esta
    restricción fue editada a mano directamente en el servidor (sin pasar por
    git) para poder aplicar la migración 0011: no se puede asumir con certeza
    qué forma exacta quedó. DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT
    funciona sin importar cuál de las variantes esté actualmente en la base de
    datos.
    """

    dependencies = [
        ('strorganizativa', '0012_unidadorganizativa_municipio'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE strorganizativa_unidadorganizativa "
                "DROP CONSTRAINT IF EXISTS unique_orden_por_rama;"
                "ALTER TABLE strorganizativa_unidadorganizativa "
                "ADD CONSTRAINT unique_orden_por_rama "
                "UNIQUE (padre_id, orden_informe) DEFERRABLE INITIALLY DEFERRED;"
            ),
            reverse_sql=(
                "ALTER TABLE strorganizativa_unidadorganizativa "
                "DROP CONSTRAINT IF EXISTS unique_orden_por_rama;"
                "ALTER TABLE strorganizativa_unidadorganizativa "
                "ADD CONSTRAINT unique_orden_por_rama "
                "UNIQUE NULLS NOT DISTINCT (padre_id, orden_informe) "
                "DEFERRABLE INITIALLY DEFERRED;"
            ),
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='unidadorganizativa',
                    name='unique_orden_por_rama',
                ),
                migrations.AddConstraint(
                    model_name='unidadorganizativa',
                    constraint=models.UniqueConstraint(
                        fields=('padre', 'orden_informe'),
                        name='unique_orden_por_rama',
                        deferrable=models.Deferrable.DEFERRED,
                    ),
                ),
            ],
        ),
    ]
