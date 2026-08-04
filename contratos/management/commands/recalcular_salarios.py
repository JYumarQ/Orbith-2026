from decimal import Decimal

from django.core.management.base import BaseCommand

from contratos.models import CAlta


class Command(BaseCommand):
    help = (
        "Recalcula y guarda 'salario_actual' (el campo cacheado que usa Informe "
        "Inteligente) para los contratos que lo tengan vacío. No repite el resto "
        "de la lógica de CAlta.save() (reasignar plazas, etc.) — solo actualiza "
        "esa columna, igual que hace save() en cada guardado normal desde el "
        "formulario."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--todos",
            action="store_true",
            help="Recalcula TODOS los contratos, no solo los que tienen salario_actual vacío.",
        )

    def handle(self, *args, **options):
        queryset = CAlta.objects.select_related(
            "cargo__ncargo__grupo_escala", "cargo__rol", "rol", "tridente"
        )
        if not options["todos"]:
            queryset = queryset.filter(salario_actual__isnull=True)

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No hay contratos pendientes de recalcular."))
            return

        actualizados = 0
        sin_calculo = 0

        # Se actualiza fila por fila (sin envolver todo en una única transacción)
        # a propósito: si el proceso se interrumpe a mitad de un lote grande, lo
        # ya actualizado queda guardado y se puede volver a ejecutar el comando
        # sin repetir trabajo (el filtro salario_actual__isnull=True solo recoge
        # lo que sigue pendiente).
        for contrato in queryset.iterator(chunk_size=200):
            nuevo_salario = contrato.calcular_salario_escala()
            if nuevo_salario is None:
                sin_calculo += 1
                continue
            CAlta.objects.filter(pk=contrato.pk).update(
                salario_actual=Decimal(str(nuevo_salario))
            )
            actualizados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Revisados: {total}  |  Actualizados: {actualizados}  |  "
            f"Sin datos suficientes para calcular: {sin_calculo}"
        ))
