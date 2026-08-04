"""Purga el histórico de hallazgos ya archivados y antiguos.

La reconciliación (`subsanacion/servicios.py::reconciliar_regla`) NUNCA borra un
hallazgo: cuando deja de detectarse, se archiva (`vigente=False`) y se conserva como
prueba de que el dato se corrigió. Con el tiempo eso acumula un histórico que crece
sin límite, y ese es exactamente el motivo de que este comando exista como una
operación EXPLÍCITA Y SEPARADA, que un administrador decide ejecutar, en vez de una
limpieza automática escondida dentro del análisis.

Solo toca hallazgos que ya están archivados (`vigente=False`) y cuya fecha de
resolución es más antigua que el umbral. Un hallazgo VIGENTE —abierto o silenciado—
nunca se toca aquí, tenga la antigüedad que tenga: solo se purga lo que ya dejó de ser
un problema activo.

Estilo calcado de los otros comandos del proyecto (`recalcular_salarios.py`,
`reenganchar_movimientos.py`): resumen con `self.style.SUCCESS`, `--dry-run` para ver
qué haría antes de escribir.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from subsanacion.models import Hallazgo

DIAS_POR_DEFECTO = 180


class Command(BaseCommand):
    help = (
        'Purga los hallazgos ya archivados (corregidos, o de reglas retiradas) con '
        f'más de {DIAS_POR_DEFECTO} días de antigüedad. Nunca toca un hallazgo '
        'vigente, esté abierto o silenciado.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias', type=int, default=DIAS_POR_DEFECTO, metavar='N',
            help=f'Antigüedad mínima en días para purgar (por defecto {DIAS_POR_DEFECTO}).')
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run',
            help='Muestra cuántos se purgarían sin borrar nada.')

    def handle(self, *args, **options):
        dias = options['dias']
        if dias < 1:
            self.stdout.write(self.style.ERROR('--dias debe ser un entero positivo.'))
            return

        limite = timezone.now() - timedelta(days=dias)

        candidatos = Hallazgo.objects.filter(
            vigente=False, fecha_resolucion__isnull=False, fecha_resolucion__lt=limite)

        total = candidatos.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS(
                f'No hay hallazgos archivados con más de {dias} días. Nada que purgar.'))
            return

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'SIMULACIÓN (--dry-run): se purgarían {total} hallazgo(s) archivados '
                f'antes del {limite:%d/%m/%Y}. No se ha borrado nada.'))
            return

        # `Hallazgo` es el padre de `RevisionHallazgo` con `on_delete=CASCADE`, así que
        # borrar el hallazgo borra su historial de revisiones con él. Es lo correcto:
        # ese historial no tiene sentido sin el hallazgo al que pertenece.
        borrados, _ = candidatos.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Purgados {total} hallazgo(s) archivados antes del {limite:%d/%m/%Y} '
            f'({borrados} fila(s) en total, incluido su historial de revisiones).'))
