"""Repara las unidades asignadas a los moderadores.

EL INVARIANTE
-------------
Una subunidad no se asigna por separado: se asigna su Unidad Principal y las
subunidades entran con ella. Dicho al revés, que es como se comprueba aquí:

    quien lleva la subunidad = quien lleva a su padre

Ese invariante lo imponen dos piezas del sistema: `usuarios/forms.py`
(`expandir_a_subunidades`) al guardar un usuario, y `strorganizativa/signals.py`
cuando nace una subunidad o cambia de padre. Vale para los dos roles que usan
unidades: el Moderador y el Observador acotado (ver `usuarios/alcance.py`).

POR QUÉ HACE FALTA ESTE COMANDO IGUALMENTE
------------------------------------------
Ninguna de esas dos piezas cubre lo que ya estaba escrito antes de existir, ni
lo que entre por fuera del formulario: una importación, el shell, el admin de
Django o un `set()` directo. Y cuando los datos se descuadran, el fallo es
SILENCIOSO y caro:

  * el usuario deja de ver a los trabajadores de esa subunidad en Contratos,
    Informes, Dashboard, Anexo 17, Pre-Nómina y Notificaciones;
  * y el moderador no puede declarar su cierre mensual, porque
    `cierres.permisos.puede_declarar` exige tener la unidad asignada y NIEGA
    declarar directamente la principal.

Nada avisa de ninguna de las dos cosas: simplemente no ve nada.

Se ejecuta así:

    python manage.py sincronizar_unidades --simular    # solo informa
    python manage.py sincronizar_unidades              # aplica los cambios

Es idempetente: ejecutarlo dos veces seguidas no cambia nada la segunda vez.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from strorganizativa.models import UnidadOrganizativa
from usuarios.models import CustomUser


class Command(BaseCommand):
    help = (
        "Aplica el invariante «quien lleva una Unidad Principal lleva también sus "
        "subunidades» a los usuarios ya guardados (Moderadores y Observadores "
        "acotados). Use --simular para ver qué cambiaría sin tocar nada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--simular",
            action="store_true",
            help="Muestra lo que cambiaría y NO escribe nada en la base de datos.",
        )
        parser.add_argument(
            "--solo-moderadores",
            action="store_true",
            help=(
                "Revisa únicamente a los Moderadores. Por defecto se revisan también "
                "los Observadores que tengan unidades asignadas, porque desde que el "
                "alcance del Observador se puede acotar (ver usuarios/alcance.py) sus "
                "unidades deciden lo mismo que las de un Moderador."
            ),
        )

    def handle(self, *args, **opciones):
        simular = opciones["simular"]

        # Un solo mapa padre -> hijas para todo el recorrido, en vez de una
        # consulta por usuario y unidad.
        hijas_de = {}
        for pk, padre_id in UnidadOrganizativa.objects.values_list("pk", "padre_id"):
            if padre_id:
                hijas_de.setdefault(padre_id, []).append(pk)

        nombre_de = dict(UnidadOrganizativa.objects.values_list("pk", "descripcion"))

        usuarios = list(
            CustomUser.objects.filter(es_moderador=True).prefetch_related("unidades"))
        if not opciones["solo_moderadores"]:
            # Solo los Observadores CON unidades: el que no tiene ninguna ve toda
            # la empresa por su rol, y añadirle subunidades no cambiaría nada
            # salvo convertirlo por sorpresa en un observador acotado.
            usuarios += list(
                CustomUser.objects.filter(es_observador=True, unidades__isnull=False)
                .distinct()
                .prefetch_related("unidades")
            )

        if not usuarios:
            self.stdout.write(self.style.WARNING("No hay usuarios que revisar."))
            return

        pendientes = []
        for usuario in usuarios:
            actuales = {u.pk for u in usuario.unidades.all()}
            # Solo se AÑADEN las hijas que falten. No se quita nada: una unidad
            # asignada de más puede responder a una decisión que este comando no
            # conoce, y retirarla dejaría a alguien sin acceso por sorpresa.
            faltantes = set()
            for pk in actuales:
                faltantes.update(h for h in hijas_de.get(pk, ()) if h not in actuales)
            if faltantes:
                pendientes.append((usuario, sorted(faltantes)))

        if not pendientes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Revisados {len(usuarios)} usuario(s): todas las asignaciones "
                    f"cumplen el invariante. No hay nada que corregir."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"{len(pendientes)} usuario(s) con subunidades sin asignar:"
            )
        )
        for usuario, faltantes in pendientes:
            nombres = ", ".join(nombre_de.get(pk, str(pk)) for pk in faltantes)
            self.stdout.write(f"  · {usuario.username}: le faltan {nombres}")

        if simular:
            self.stdout.write(
                self.style.NOTICE(
                    "\n--simular: no se ha escrito nada. Vuelva a ejecutarlo sin "
                    "--simular para aplicar los cambios."
                )
            )
            return

        # En una sola transacción: o se corrigen todos o no se corrige ninguno.
        # Una corrección a medias dejaría los datos igual de incoherentes que
        # antes, pero además sin saber por dónde se quedó.
        with transaction.atomic():
            for usuario, faltantes in pendientes:
                usuario.unidades.add(*faltantes)

        total = sum(len(f) for _, f in pendientes)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nHecho: {total} asignación(es) añadida(s) a "
                f"{len(pendientes)} usuario(s)."
            )
        )
