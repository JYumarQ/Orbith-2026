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
