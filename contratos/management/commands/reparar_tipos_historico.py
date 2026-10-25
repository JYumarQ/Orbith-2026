from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from contratos.models import TMovimiento
from contratos.tipos_historico import incompletos_q, personas_incompletas, rellenos_de


class Command(BaseCommand):
    help = (
        "Rellena el tipo de contrato y el motivo que faltan en el histórico cuando se "
        "pueden saber con certeza (el movimiento siguiente, la baja o el contrato vigente). Por defecto "
        "solo SIMULA: dice qué haría. Con --aplicar lo guarda. Al terminar lista las "
        "personas que siguen con eventos incompletos, para completarlas en el editor del "
        "histórico."
    )

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Guarda los cambios (sin esto, solo simula).')

    def handle(self, *args, **options):
        from bolsa.models import Aspirante
        from subsanacion.por_registro import sin_revision_por_registro

        aplicar = options['aplicar']
        personas = personas_incompletas()
        rellenos = {a: rellenos_de(a) for a in personas}

        if aplicar:
            # Uno a uno con `save(update_fields=…)`: así cada cambio queda en Auditoría.
            with transaction.atomic(), sin_revision_por_registro():
                for lista in rellenos.values():
                    for r in lista:
                        movimiento = TMovimiento.objects.get(pk=r.mov_pk)
                        setattr(movimiento, r.campo, r.valor)
                        movimiento.save(update_fields=[r.campo])

        por_fuente = {}
        quedan = []
        for aspirante_id, lista in rellenos.items():
            nuevos = [r for r in lista if r.campo.endswith('_nuevo')]
            for r in nuevos:
                por_fuente[r.fuente] = por_fuente.get(r.fuente, 0) + 1
            pendientes = (TMovimiento.objects.filter(incompletos_q())
                          .filter(Q(aspirante_id=aspirante_id) | Q(contrato__aspirante_id=aspirante_id))
                          .exclude(pk__in={r.mov_pk for r in nuevos}))
            if not aplicar and pendientes.exists() or aplicar and TMovimiento.objects.filter(incompletos_q()).filter(
                    Q(aspirante_id=aspirante_id) | Q(contrato__aspirante_id=aspirante_id)).exists():
                quedan.append(aspirante_id)

        self.stdout.write(self.style.MIGRATE_HEADING(
            'GUARDADO' if aplicar else 'SIMULACIÓN: no se ha guardado nada (use --aplicar)'))
        self.stdout.write('Personas con eventos sin tipo de contrato o sin motivo: %d' % len(personas))
        self.stdout.write('Datos deducidos con certeza: %d' % sum(por_fuente.values()))
        for fuente, cuantos in sorted(por_fuente.items(), key=lambda x: -x[1]):
            self.stdout.write('  · %d por %s' % (cuantos, fuente))
        self.stdout.write('')
        if not quedan:
            self.stdout.write(self.style.SUCCESS('No queda ninguna persona con eventos incompletos.'))
            return
        self.stdout.write(self.style.WARNING(
            'Quedan %d personas con eventos cuyo tipo o motivo no se puede saber. Complételas en el '
            'editor del histórico (Subsanación las avisa con la regla MOV-016):' % len(quedan)))
        for aspirante in Aspirante.objects.filter(pk__in=quedan).order_by('papellido', 'sapellido', 'nombre'):
            self.stdout.write('  · %s %s %s (CI %s): /contrato/editor-historico/%d/' % (
                aspirante.nombre, aspirante.papellido, aspirante.sapellido,
                aspirante.doc_identidad, aspirante.pk))
