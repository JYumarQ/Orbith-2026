"""Reglas de negocio de las Plantillas de reporte de pago.

Misma doctrina que `servicios.py` y `servicios_calendario.py`: **las vistas no
escriben estado, solo llaman aquí**, toda transición es `@transaction.atomic` y
los errores son `ErrorDePreNomina` con su mensaje en español listo para pantalla.

Cuatro reglas sostienen el módulo:

1. **Las plantillas son personales.** Cada una pertenece a un usuario y la
   descripción es única dentro de su catálogo, no en toda la tabla.

2. **La coherencia se valida al guardar la plantilla, no al aplicarla.** Se
   reutiliza `validar_seleccion()`, que es la misma comprobación que hace
   `servicios.configurar_conceptos()` sobre el reporte. Así no se puede guardar
   una plantilla que después sería imposible de aplicar.

3. **Editar una plantilla no toca ningún reporte.** Los conceptos del reporte
   son copias congeladas (`ReporteConcepto*`) hechas al aplicarla; la plantilla
   apunta a los nomencladores vivos. Son dos cosas distintas a propósito.

4. **Una plantilla usada no se borra.** Ni siquiera si el reporte que la usó
   está cerrado o es histórico: se protege la trazabilidad de por qué ese
   reporte tiene esas columnas.
"""

import logging

from django.db import transaction

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar as registrar_auditoria

from .constantes import MODULO
from .models import (NClaveAusencia, NPagoHoras, NPagoImporte, PlantillaReporte)
from .servicios import ErrorDePreNomina

logger = logging.getLogger(__name__)

LONGITUD_DESCRIPCION = 30

MENSAJE_SIN_CONCEPTOS = 'Debe seleccionar al menos un concepto.'
MENSAJE_DUPLICAR_TODO = ('Debe cambiar la descripción de esta plantilla y agregar '
                         'o eliminar, al menos, uno de los conceptos seleccionables.')
MENSAJE_DUPLICAR_CONCEPTOS = ('Debe agregar o eliminar, al menos, uno de los '
                              'conceptos seleccionables.')
MENSAJE_DUPLICAR_DESCRIPCION = 'Debe cambiar la descripción de esta plantilla.'


def _auditar(usuario, accion, instancia, descripcion):
    """Igual que en `servicios.py`: la auditoría nunca tumba la operación real."""
    try:
        registrar_auditoria(
            usuario=usuario, accion=accion, instancia=instancia,
            descriptor=descripcion[:200], modulo=MODULO)
    except Exception:
        logger.exception('No se pudo auditar la acción %s de la plantilla.', accion)


def _exigir_propietario(plantilla, usuario):
    """La plantilla tiene que ser de quien la toca.

    Se compara el `usuario_id`, nunca el rol: que alguien sea Administrador no
    le da permiso para editar el catálogo personal de otro.
    """
    if plantilla.usuario_id != usuario.pk:
        raise ErrorDePreNomina(
            'Esta plantilla pertenece a otro usuario, no puede modificarla.')


# --------------------------------------------------------------------------- #
# Normalización y validación de la selección
# --------------------------------------------------------------------------- #

def normalizar_descripcion(valor):
    texto = str(valor or '').strip()
    if not texto:
        raise ErrorDePreNomina('La descripción es obligatoria.')
    if len(texto) > LONGITUD_DESCRIPCION:
        raise ErrorDePreNomina(
            f'La descripción no puede superar los {LONGITUD_DESCRIPCION} caracteres.')
    return texto


def _a_codigos(valores, etiqueta):
    """Lista de cadenas del POST → conjunto de enteros, rechazando basura."""
    codigos = set()
    for bruto in valores or ():
        try:
            codigos.add(int(bruto))
        except (TypeError, ValueError):
            raise ErrorDePreNomina(
                f'«{bruto}» no es un código válido de {etiqueta}.')
    return codigos


def normalizar_seleccion(codigos_ausencia=(), codigos_horas=(), codigos_importe=()):
    return (_a_codigos(codigos_ausencia, 'clave de ausencia'),
            _a_codigos(codigos_horas, 'pago asociado por horas'),
            _a_codigos(codigos_importe, 'pago asociado por importe'))


def validar_seleccion(codigos_ausencia, codigos_horas, codigos_importe):
    """Las mismas reglas de coherencia que impone el reporte, aplicadas antes.

    Devuelve `(claves, pagos_horas, importes_manuales)` ya resueltos, para no
    volver a consultarlos en el llamador.

    Es una copia deliberada de lo que comprueba
    `servicios.configurar_conceptos()`, y no una llamada a esa función, porque
    aquélla necesita un reporte con trabajadores y aquí todavía no hay ninguno.
    Si alguna de estas reglas cambia, hay que cambiarla en los dos sitios: el
    precio de poder validar la plantilla antes de que exista el reporte.
    """
    if not (codigos_ausencia or codigos_horas or codigos_importe):
        raise ErrorDePreNomina(MENSAJE_SIN_CONCEPTOS)

    claves = {c.codigo: c for c in
              NClaveAusencia.objects.filter(codigo__in=codigos_ausencia)
              .select_related('relacionado_con')}
    pagos_horas = {p.codigo: p for p in
                   NPagoHoras.objects.filter(codigo__in=codigos_horas)}

    faltan = codigos_ausencia - set(claves)
    if faltan:
        raise ErrorDePreNomina(
            f'No existe la clave de ausencia con código {sorted(faltan)[0]}.')
    faltan = codigos_horas - set(pagos_horas)
    if faltan:
        raise ErrorDePreNomina(
            f'No existe el pago por horas con código {sorted(faltan)[0]}.')

    # Una ausencia que alimenta un concepto por horas exige que ese concepto
    # esté también seleccionado: si no, esas horas no tendrían dónde reflejarse.
    for clave in claves.values():
        destino = clave.relacionado_con
        if destino and destino.codigo not in pagos_horas:
            raise ErrorDePreNomina(
                f'La clave «{clave.etiqueta}» alimenta el concepto '
                f'«{destino.etiqueta}», así que ese concepto por horas también '
                f'debe estar seleccionado.')

    # Los importes relacionados con un pago por horas seleccionado entran solos
    # al aplicar la plantilla; aquí solo se guardan los elegidos a mano.
    automaticos = set(NPagoImporte.objects
                      .filter(relacionado_con__codigo__in=codigos_horas)
                      .values_list('codigo', flat=True))
    manuales = {p.codigo: p for p in
                NPagoImporte.objects.filter(codigo__in=codigos_importe)
                .exclude(codigo__in=automaticos)
                .select_related('relacionado_con')}

    faltan = codigos_importe - automaticos - set(manuales)
    if faltan:
        raise ErrorDePreNomina(
            f'No existe el pago por importe con código {sorted(faltan)[0]}.')

    # Un importe manual cuya fórmula use {{horas}} necesita su concepto por
    # horas, o la fórmula se evaluaría siempre con cero.
    for pago in manuales.values():
        if pago.relacionado_con and pago.relacionado_con.codigo not in pagos_horas:
            raise ErrorDePreNomina(
                f'El importe «{pago.etiqueta}» toma las horas de '
                f'«{pago.relacionado_con.etiqueta}», que no está seleccionado.')

    return claves, pagos_horas, manuales


def _exigir_descripcion_libre(usuario, descripcion, excluir=None):
    existentes = PlantillaReporte.objects.filter(
        usuario=usuario, descripcion__iexact=descripcion)
    if excluir is not None:
        existentes = existentes.exclude(pk=excluir)
    if existentes.exists():
        raise ErrorDePreNomina(
            f'Ya tiene una plantilla llamada «{descripcion}».')


def comprobar_duplicado(original, descripcion, seleccion):
    """Mensaje que corresponde al estado actual de una duplicación, o `None`.

    Se usa **dos veces**: en la validación en vivo por HTMX mientras el usuario
    marca casillas, y al guardar en el servidor. Que sea la misma función es lo
    que garantiza que el mensaje de la pantalla y el del backend nunca se
    contradigan.

    El orden importa: quedarse sin conceptos manda sobre todo lo demás, porque
    una plantilla vacía no se puede guardar de ninguna forma.
    """
    if not any(seleccion):
        return MENSAJE_SIN_CONCEPTOS

    cambia_descripcion = (descripcion or '').strip().casefold() != \
        original.descripcion.casefold()
    cambian_conceptos = tuple(seleccion) != tuple(original.codigos())

    if not cambia_descripcion and not cambian_conceptos:
        return MENSAJE_DUPLICAR_TODO
    if not cambian_conceptos:
        return MENSAJE_DUPLICAR_CONCEPTOS
    if not cambia_descripcion:
        return MENSAJE_DUPLICAR_DESCRIPCION
    return None


# --------------------------------------------------------------------------- #
# Alta, edición, duplicado y borrado
# --------------------------------------------------------------------------- #

def _guardar_seleccion(plantilla, claves, pagos_horas, manuales):
    plantilla.claves_ausencia.set(claves.values())
    plantilla.pagos_horas.set(pagos_horas.values())
    plantilla.pagos_importe.set(manuales.values())


@transaction.atomic
def crear_plantilla(usuario, *, descripcion, codigos_ausencia=(),
                    codigos_horas=(), codigos_importe=()):
    descripcion = normalizar_descripcion(descripcion)
    seleccion = normalizar_seleccion(codigos_ausencia, codigos_horas, codigos_importe)
    claves, pagos_horas, manuales = validar_seleccion(*seleccion)
    _exigir_descripcion_libre(usuario, descripcion)

    plantilla = PlantillaReporte.objects.create(
        usuario=usuario, descripcion=descripcion)
    _guardar_seleccion(plantilla, claves, pagos_horas, manuales)

    _auditar(usuario, AccionAuditoria.CREAR, plantilla,
             f'Creada la plantilla «{plantilla.descripcion}» con '
             f'{plantilla.total_conceptos} conceptos')
    return plantilla


@transaction.atomic
def editar_plantilla(plantilla, usuario, *, descripcion, codigos_ausencia=(),
                     codigos_horas=(), codigos_importe=()):
    """Modifica una plantilla existente.

    **No se exige que cambie nada**: se puede guardar habiendo tocado solo la
    descripción, solo los conceptos, o ambas cosas. La regla de «cambiar las dos»
    es exclusiva de duplicar, donde su razón de ser es no acabar con dos
    plantillas funcionalmente idénticas.

    Editar aquí no altera ningún reporte ya creado: los suyos son copias
    congeladas.
    """
    plantilla = PlantillaReporte.objects.select_for_update().get(pk=plantilla.pk)
    _exigir_propietario(plantilla, usuario)

    descripcion = normalizar_descripcion(descripcion)
    seleccion = normalizar_seleccion(codigos_ausencia, codigos_horas, codigos_importe)
    claves, pagos_horas, manuales = validar_seleccion(*seleccion)
    _exigir_descripcion_libre(usuario, descripcion, excluir=plantilla.pk)

    plantilla.descripcion = descripcion
    plantilla.save(update_fields=['descripcion', 'fecha_actualizado'])
    _guardar_seleccion(plantilla, claves, pagos_horas, manuales)

    _auditar(usuario, AccionAuditoria.MODIFICAR, plantilla,
             f'Editada la plantilla «{plantilla.descripcion}» '
             f'({plantilla.total_conceptos} conceptos)')
    return plantilla


@transaction.atomic
def duplicar_plantilla(original, usuario, *, descripcion, codigos_ausencia=(),
                       codigos_horas=(), codigos_importe=()):
    """Crea una plantilla nueva a partir de otra, exigiendo que sea distinta.

    Las dos condiciones —descripción distinta y al menos un concepto distinto—
    no protegen ninguna clave primaria: la plantilla nueva tendría la suya de
    todos modos. Lo que evitan es llenar el catálogo de copias funcionalmente
    idénticas que después nadie sabe distinguir.
    """
    _exigir_propietario(original, usuario)

    descripcion_limpia = normalizar_descripcion(descripcion)
    seleccion = normalizar_seleccion(codigos_ausencia, codigos_horas, codigos_importe)

    problema = comprobar_duplicado(original, descripcion_limpia, seleccion)
    if problema:
        raise ErrorDePreNomina(problema)

    claves, pagos_horas, manuales = validar_seleccion(*seleccion)
    _exigir_descripcion_libre(usuario, descripcion_limpia)

    copia = PlantillaReporte.objects.create(
        usuario=usuario, descripcion=descripcion_limpia)
    _guardar_seleccion(copia, claves, pagos_horas, manuales)

    _auditar(usuario, AccionAuditoria.CREAR, copia,
             f'Duplicada «{original.descripcion}» como «{copia.descripcion}»')
    return copia


@transaction.atomic
def eliminar_plantilla(plantilla, usuario):
    """Borra una plantilla que no haya usado ningún reporte.

    Cuenta cualquier reporte, en cualquier estado. Se comprueba aquí además de
    con el `PROTECT` de la clave foránea porque `PROTECT` solo sabe negarse: no
    puede decir cuántos reportes la usan ni por qué importa.
    """
    plantilla = PlantillaReporte.objects.select_for_update().get(pk=plantilla.pk)
    _exigir_propietario(plantilla, usuario)

    usos = plantilla.reportes.count()
    if usos:
        ejemplos = ' · '.join(
            f'{r.unidad_descripcion} {r.periodo.etiqueta}'
            for r in plantilla.reportes.all()[:4])
        raise ErrorDePreNomina(
            f'No se puede eliminar «{plantilla.descripcion}»: ya se ha utilizado '
            f'en {usos} reporte{"s" if usos != 1 else ""} de pago ({ejemplos}). '
            f'Una plantilla usada queda protegida para conservar la trazabilidad '
            f'de esos reportes.')

    nombre = plantilla.descripcion
    plantilla.delete()
    _auditar(usuario, AccionAuditoria.ELIMINAR, None,
             f'Eliminada la plantilla «{nombre}»')


# --------------------------------------------------------------------------- #
# Aplicación a un reporte
# --------------------------------------------------------------------------- #

def aplicar_a_reporte(reporte, plantilla, usuario):
    """Congela en el reporte los conceptos de la plantilla.

    Es una fachada sobre `servicios.configurar_conceptos()`: se le pasan los
    códigos de la plantilla y él hace lo de siempre —validar, copiar los
    conceptos y crear las celdas de valor—. Reutilizarlo, en lugar de escribir
    un congelado nuevo, es lo que garantiza que un reporte creado desde una
    plantilla sea indistinguible de los que ya existían.
    """
    from . import servicios

    ausencias, horas, importes = plantilla.codigos()
    resumen = servicios.configurar_conceptos(
        reporte, usuario,
        codigos_ausencia=ausencias,
        codigos_horas=horas,
        codigos_importe=importes)

    if reporte.plantilla_id != plantilla.pk:
        reporte.plantilla = plantilla
        reporte.save(update_fields=['plantilla'])
    return resumen
