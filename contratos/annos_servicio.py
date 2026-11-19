"""Años de servicio de un contrato y el dinero que le corresponde.

Une dos piezas que ya existían por separado:

* **Cuántos años** lleva el trabajador en la entidad — se derivan de
  `CAlta.fecha_alta_entidad` con `prenomina.captura.annos_de_servicio()`, la
  misma función que congela la Pre-Nómina y la misma semántica de «años
  completos» que la tarjeta Antigüedad del Dashboard.
* **Cuánto dinero** corresponde a esos años — sale del nomenclador
  `NEscalaAnnosServicio` (Configuración → Nomencladores → Tiempo de Trabajo →
  Escala de Años de Servicio), a través de su propio `cuantia_de()`, que ya
  aplica el techo de la escala (quien pasa del último tramo cobra el último).

**No se almacena en el contrato a propósito.** Es un valor derivado de dos
fuentes que se mueven solas: los años aumentan cada aniversario sin que nadie
guarde el contrato, y la escala cambia con cada resolución salarial. Un campo en
`CAlta` se quedaría desactualizado en silencio al día siguiente de guardarlo. El
sitio donde este importe SÍ se congela es el reporte de pago
(`ReporteTrabajador.anos_servicio` + `escala_congelada`), porque allí congelarlo
es justamente lo correcto: un documento de pago debe poder recalcularse igual
dentro de años.
"""

from prenomina.captura import annos_de_servicio
from prenomina.models import NEscalaAnnosServicio


def annos_y_pago(fecha_alta_entidad, referencia=None):
    """Devuelve `(años completos, cuantía)` a la fecha de referencia (hoy si no se da).

    Sin `fecha_alta_entidad` no hay antigüedad que calcular y se devuelve
    `(0, None)`. `None` significa «no se puede calcular», que es distinto de un
    cero: un trabajador que aún no cumple el primer tramo de la escala sí cobra
    `Decimal('0.00')`, y esa diferencia es la que permite mostrar el campo vacío
    en vez de un 0.00 inventado.
    """
    if not fecha_alta_entidad:
        return 0, None

    annos = annos_de_servicio(fecha_alta_entidad, referencia)
    escala = NEscalaAnnosServicio.como_diccionario()
    return annos, NEscalaAnnosServicio.cuantia_de(escala, annos)


# --------------------------------------------------------------------------
# Cambio de años de servicio (decisión de RRHH del 19-11-2026)
# --------------------------------------------------------------------------
# Cuando un aniversario de la F. Alta Entidad hace cambiar el importe de la escala,
# hay que registrarlo con un movimiento de nómina con fecha efectiva ese día o
# posterior. Orbith avisa 10 días antes (recordatorio REC-ANTIGUEDAD) y, si llega
# el día sin movimiento, Subsanación lo marca (regla CTR-025) hasta que se haga.
# Cualquier movimiento con fecha efectiva igual o posterior al aniversario cumple:
# el movimiento congela «Otros» con los años de su fecha efectiva.


def aniversario(fecha_alta_entidad, annos):
    """El día en que se cumplen `annos` años completos. Un 29 de febrero, en un año
    no bisiesto, se cumple el 1 de marzo (mismo criterio que `annos_de_servicio`)."""
    from datetime import date
    try:
        return fecha_alta_entidad.replace(year=fecha_alta_entidad.year + annos)
    except ValueError:
        return date(fecha_alta_entidad.year + annos, 3, 1)


def importe_a(fecha_alta_entidad, fecha, escala=None):
    """Importe de años de servicio a una fecha (None sin F. Alta Entidad)."""
    if not fecha_alta_entidad:
        return None
    escala = escala if escala is not None else NEscalaAnnosServicio.como_diccionario()
    return NEscalaAnnosServicio.cuantia_de(escala, annos_de_servicio(fecha_alta_entidad, fecha))


def cambios_de_importe(fecha_alta_entidad, desde, hasta, escala=None):
    """Aniversarios entre `desde` y `hasta` (ambos incluidos) que cambian el importe:
    `[(fecha, años, importe_antes, importe_después)]`, en orden."""
    if not fecha_alta_entidad or not desde or not hasta or desde > hasta:
        return []
    escala = escala if escala is not None else NEscalaAnnosServicio.como_diccionario()
    cambios = []
    for annos in range(max(desde.year - fecha_alta_entidad.year - 1, 1),
                       hasta.year - fecha_alta_entidad.year + 1):
        dia = aniversario(fecha_alta_entidad, annos)
        if not (desde <= dia <= hasta):
            continue
        antes = NEscalaAnnosServicio.cuantia_de(escala, annos - 1)
        despues = NEscalaAnnosServicio.cuantia_de(escala, annos)
        if antes != despues:
            cambios.append((dia, annos, antes, despues))
    return cambios


def avisos_desde():
    """Desde qué día se reclaman los cambios (decisión del 19-11-2026: solo los
    aniversarios a partir de la actualización; los anteriores no). Lo guarda
    Parámetros Generales al aplicar la migración; sin dato, hoy."""
    from datetime import date

    from configuracion.models import Configuracion
    config = Configuracion.objects.only('annos_servicio_avisos_desde').first()
    return (config.annos_servicio_avisos_desde if config else None) or date.today()
