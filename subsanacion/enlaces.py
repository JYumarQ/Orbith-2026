"""Enlace desde un hallazgo al formulario donde el usuario lo corrige.

Ningún modelo de Orbith define `get_absolute_url()` y las urls de negocio no usan
namespace, así que el problema se resuelve en un solo archivo en lugar de repetirse
en cada regla.

Dos decisiones importantes:

* La URL NO se guarda en la base de datos: se reconstruye al renderizar. Una url
  guardada quedaría obsoleta el día que alguien reordene `urls.py`, y ese es
  justamente el tipo de fallo silencioso que este módulo existe para evitar.
* `construir_enlace()` nunca lanza. Si una url se renombra, el hallazgo se sigue
  mostrando; solo pierde el botón.
"""

import logging

from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)


# `editable=False` significa que ese modelo NO tiene formulario de edición y el
# enlace lleva al listado. Verificado en los urls.py del proyecto: no existe
# `updt_baja`, y TMovimiento solo tiene `movimiento_detalle_readonly`, que es un
# modal HTMX y no una página. En esos casos, el texto `solucion` de la regla TIENE
# que decir dónde se arregla el problema de verdad.
ENLACES_POR_MODELO = {
    'contratos.CAlta': {
        'url': 'updt_contrato', 'etiqueta': 'Abrir contrato', 'editable': True},
    'bolsa.Aspirante': {
        'url': 'updt_aspir', 'etiqueta': 'Abrir trabajador', 'editable': True},
    'strorganizativa.CargoPlantilla': {
        'url': 'updt_cargo', 'etiqueta': 'Abrir cargo', 'editable': True},
    'strorganizativa.Departamento': {
        'url': 'updt_dpto', 'etiqueta': 'Abrir departamento', 'editable': True},
    'strorganizativa.UnidadOrganizativa': {
        'url': 'updt_uniorg', 'etiqueta': 'Abrir unidad', 'editable': True},
    'usuarios.CustomUser': {
        'url': 'updt_usuario', 'etiqueta': 'Abrir usuario', 'editable': True},
    'configuracion.Configuracion': {
        'url': 'parametros', 'etiqueta': 'Abrir parámetros generales',
        'editable': True, 'sin_argumento': True},

    # Sin formulario de edición: se degrada al listado.
    'contratos.CBaja': {
        'url': 'list_baja', 'etiqueta': 'Ver listado de bajas',
        'editable': False, 'sin_argumento': True},
    'contratos.TMovimiento': {
        'url': 'list_movimientos', 'etiqueta': 'Ver movimientos de nómina',
        'editable': False, 'sin_argumento': True},
}


def construir_enlace(etiqueta_modelo, object_id, forzar_url=None):
    """Devuelve `{'href', 'etiqueta', 'editable'}` o None si no se puede construir.

    `etiqueta_modelo` es «app.Modelo». `object_id` es el valor guardado en el
    hallazgo, que es el pk real del registro — importante para
    `UnidadOrganizativa`, cuyo pk es `codigo_interno` y no `id`.
    """
    definicion = ENLACES_POR_MODELO.get(etiqueta_modelo)
    if definicion is None:
        return None

    nombre_url = forzar_url or definicion['url']
    sin_argumento = definicion.get('sin_argumento', False)

    # Un hallazgo global (object_id vacío) no puede llevar argumento aunque la url
    # normalmente lo lleve.
    if not object_id:
        sin_argumento = True

    try:
        if sin_argumento:
            href = reverse(nombre_url)
        else:
            href = reverse(nombre_url, args=[object_id])
    except NoReverseMatch:
        logger.warning(
            'Subsanación: no se pudo construir el enlace «%s» para %s (id=%r). '
            '¿Se renombró la url?', nombre_url, etiqueta_modelo, object_id)
        return None

    return {
        'href': href,
        'etiqueta': definicion['etiqueta'],
        'editable': definicion.get('editable', False),
    }


def enlace_de_hallazgo(hallazgo, forzar_url=None):
    """Igual que `construir_enlace`, partiendo de un `Hallazgo`.

    Usa `content_type` sin resolver la GenericForeignKey, así que no dispara una
    consulta por fila ni falla si el registro apuntado fue borrado.
    """
    ct = hallazgo.content_type
    etiqueta_modelo = f'{ct.app_label}.{ct.model_class().__name__}' if ct.model_class() else None
    if etiqueta_modelo is None:
        return None
    return construir_enlace(etiqueta_modelo, hallazgo.object_id, forzar_url=forzar_url)
