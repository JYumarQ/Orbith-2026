"""Repara el histórico de nómina que quedó desconectado de su contrato.

Cuando se da de baja a un trabajador se borra su CAlta, y como `TMovimiento.contrato`
es SET_NULL sus movimientos sobreviven con el enlace en blanco. Si más tarde se le
vuelve a contratar reutilizando el mismo número de expediente, el contrato nuevo es
otra fila: el histórico anterior sigue existiendo, pero ya no se llega a él al abrir
el histórico del trabajador desde su contrato.

Los contratos creados a partir de ahora se reenganchan solos (véase
`CAlta.save()`). Este comando es para los que ya estaban rotos.

Estilo calcado del otro comando de la app, `recalcular_salarios.py`.
"""

import json
from datetime import datetime

from django.core.management.base import BaseCommand

from contratos.models import TIPO_MOVIMIENTO_BAJA, CAlta, TMovimiento


class Command(BaseCommand):
    help = (
        "Reengancha a su contrato los movimientos del histórico que perdieron el "
        "enlace al borrarse el contrato anterior del trabajador. Solo toca aquello "
        "que es reconstruible sin ninguna duda: mismo trabajador y mismo número de "
        "expediente EXACTO. Los movimientos de tipo «Baja» no se tocan nunca (se "
        "crean sin contrato a propósito). Es idempotente: volver a ejecutarlo no "
        "hace nada. Use --dry-run para ver qué haría antes de escribir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Muestra lo que haría sin escribir nada en la base de datos.",
        )
        parser.add_argument(
            "--registro",
            metavar="RUTA",
            help=(
                "Guarda en un JSON el detalle de cada movimiento reenganchado. "
                "Sirve para deshacer la reparación: los movimientos que aparezcan "
                "en el fichero volvían a tener 'contrato' vacío."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Se parte de los movimientos rotos, no de los contratos: son muchos menos, y
        # así solo se consultan los contratos que de verdad tienen algo que reclamar.
        huerfanos = (TMovimiento.objects
                     .filter(contrato__isnull=True, aspirante__isnull=False)
                     .exclude(tipo_movimiento__iexact=TIPO_MOVIMIENTO_BAJA)
                     .exclude(no_expediente__isnull=True)
                     .exclude(no_expediente=""))

        total_huerfanos = huerfanos.count()
        if total_huerfanos == 0:
            self.stdout.write(self.style.SUCCESS(
                "No hay movimientos huérfanos que reenganchar."))
            return

        claves = set(huerfanos.values_list("aspirante_id", "no_expediente"))

        # El filtro por `no_expediente` lo resuelve la base de datos; la pareja completa
        # (aspirante + expediente) se comprueba aquí, porque un mismo número de
        # expediente reutilizado por OTRA persona no debe reenganchar nada.
        contratos = [
            contrato
            for contrato in (CAlta.objects
                             .filter(no_expediente__in={exp for _, exp in claves},
                                     aspirante__isnull=False)
                             .select_related("aspirante")
                             .order_by("no_expediente"))
            if (contrato.aspirante_id, contrato.no_expediente) in claves
        ]

        registro = []
        reenganchados = 0

        # Se procesa contrato por contrato, sin envolver todo en una única transacción,
        # igual que en `recalcular_salarios`: cada UPDATE ya es atómico por sí mismo, y
        # si el proceso se interrumpe lo ya reparado queda guardado. Volver a ejecutar
        # el comando solo recoge lo que siga pendiente.
        for contrato in contratos:
            pendientes = list(
                contrato.movimientos_huerfanos_reenganchables()
                .order_by("fecha_efectiva", "id")
                .values("id", "tipo_movimiento", "fecha_efectiva", "no_expediente")
            )
            if not pendientes:
                continue

            self.stdout.write(
                f"{self._nombre(contrato)} · expediente {contrato.no_expediente} · "
                f"contrato {contrato.pk} · {len(pendientes)} movimiento(s)"
            )
            for movimiento in pendientes:
                fecha = movimiento["fecha_efectiva"]
                self.stdout.write(
                    f"    mov {movimiento['id']:>6}  {fecha:%d/%m/%Y}  "
                    f"{movimiento['tipo_movimiento'] or '-'}"
                )
                registro.append({
                    "movimiento_id": movimiento["id"],
                    "tipo_movimiento": movimiento["tipo_movimiento"],
                    "fecha_efectiva": fecha.isoformat() if fecha else None,
                    "no_expediente": movimiento["no_expediente"],
                    "contrato_asignado": contrato.pk,
                    "aspirante_id": contrato.aspirante_id,
                })

            if not dry_run:
                reenganchados += contrato.reenganchar_movimientos_huerfanos()
            else:
                reenganchados += len(pendientes)

        irrecuperables = total_huerfanos - reenganchados

        if options["registro"]:
            self._guardar_registro(options["registro"], registro, aplicado=not dry_run)

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"SIMULACIÓN (--dry-run): no se ha escrito nada. "
                f"Se reengancharían {reenganchados} de {total_huerfanos} "
                f"movimiento(s) huérfano(s)."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Huérfanos revisados: {total_huerfanos}  |  "
                f"Reenganchados: {reenganchados}  |  "
                f"Contratos afectados: {len({r['contrato_asignado'] for r in registro})}"
            ))

        if irrecuperables:
            self.stdout.write(self.style.WARNING(
                f"Quedan {irrecuperables} movimiento(s) sin reenganchar: su trabajador "
                f"no tiene ningún contrato vivo con ese número de expediente (está de "
                f"baja y no se le ha vuelto a contratar). No hay contrato al que "
                f"asociarlos, así que no es un fallo de este comando: se resolverán "
                f"solos si se le vuelve a contratar con el mismo expediente."
            ))

    # ------------------------------------------------------------------
    @staticmethod
    def _nombre(contrato):
        aspirante = contrato.aspirante
        partes = [getattr(aspirante, campo, "") or ""
                  for campo in ("nombre", "papellido", "sapellido")]
        nombre = " ".join(parte for parte in partes if parte).strip()
        return nombre or f"Aspirante {contrato.aspirante_id}"

    def _guardar_registro(self, ruta, registro, aplicado):
        contenido = {
            "generado": datetime.now().isoformat(timespec="seconds"),
            "aplicado": aplicado,
            "total": len(registro),
            "movimientos": registro,
        }
        with open(ruta, "w", encoding="utf-8") as fichero:
            json.dump(contenido, fichero, ensure_ascii=False, indent=2, default=str)
        self.stdout.write(f"Registro guardado en {ruta}")
