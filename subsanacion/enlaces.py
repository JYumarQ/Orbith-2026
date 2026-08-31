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
from urllib.parse import quote

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
    # `solo_admin`: el destino está protegido con `admin_required` (ver
    # usuarios/urls.py). Sin esta marca, un Moderador con un hallazgo sobre una
    # cuenta de usuario veía el botón «Abrir usuario» y se comía un 403 al
    # pulsarlo. Ahora el hallazgo se muestra igual, solo sin botón — la misma
    # degradación que ya se aplica a los modelos sin formulario de edición.
    'usuarios.CustomUser': {
        'url': 'updt_usuario', 'etiqueta': 'Abrir usuario', 'editable': True,
        'solo_admin': True},
    'configuracion.Configuracion': {
        'url': 'parametros', 'etiqueta': 'Abrir parámetros generales',
        'editable': True, 'sin_argumento': True},

    # Las notificaciones de Solicitudes apuntan a la propia solicitud, no al registro
    # afectado: la solicitud sobrevive a la operación —incluso cuando lo aprobado fue
    # eliminar ese registro—, así que el enlace nunca queda roto. `editable=False` porque
    # el destino es la pantalla de consulta: una solicitud ya decidida solo se mira, y una
    # pendiente se modifica desde su propia pantalla, no desde aquí.
    'solicitudes.Solicitud': {
        'url': 'ver_solicitud', 'etiqueta': 'Abrir solicitud', 'editable': False},

    # Sin formulario de edición: se degrada al listado.
    'contratos.CBaja': {
        'url': 'list_baja', 'etiqueta': 'Ver listado de bajas',
        'editable': False, 'sin_argumento': True},
    'contratos.TMovimiento': {
        'url': 'list_movimientos', 'etiqueta': 'Ver movimientos de nómina',
        'editable': False, 'sin_argumento': True},

    # El Calendario de Pago no tiene formulario propio: se monta en la pantalla
    # de Pre-Nómina → Calendario, eligiendo su año y mes en los desplegables. Por
    # eso `sin_argumento`: el enlace lleva a la pantalla, y el texto `solucion` de
    # la regla CAL-102 explica que hay que situarse en ese período.
    'prenomina.CalendarioPago': {
        'url': 'prenomina:calendario', 'etiqueta': 'Abrir Calendario de Pago',
        'editable': False, 'sin_argumento': True},
}


def construir_enlace(etiqueta_modelo, object_id, forzar_url=None, next_url=None,
                     origen_label=None, usuario=None):
    """Devuelve `{'href', 'etiqueta', 'editable'}` o None si no se puede construir.

    `etiqueta_modelo` es «app.Modelo». `object_id` es el valor guardado en el
    hallazgo, que es el pk real del registro — importante para
    `UnidadOrganizativa`, cuyo pk es `codigo_interno` y no `id`.

    `usuario` (opcional): quien va a ver el enlace. Solo se usa para las entradas
    marcadas con `solo_admin`; si no se pasa, esas entradas no devuelven enlace.

    `next_url`/`origen_label` (opcionales): si se pasan, se anexan como
    `?next=...&origen=...` al `href`. Es el ÚNICO punto que genera estos enlaces
    (tanto desde Subsanación como desde Notificaciones), así que añadirlos aquí basta
    para que el destino sepa a dónde volver tras guardar (`core.mixins.VolverAlOrigenMixin`)
    y pueda mostrar de dónde vino el usuario, sin duplicar esa lógica en cada llamador.
    """
    definicion = ENLACES_POR_MODELO.get(etiqueta_modelo)
    if definicion is None:
        return None

    # Si el destino es una pantalla exclusiva del Administrador, no se ofrece el
    # botón a quien no lo es: mejor no enseñar una puerta que va a dar 403.
    if definicion.get('solo_admin') and not getattr(usuario, 'es_admin', False):
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

    if next_url:
        href = f'{href}?next={quote(next_url)}'
        if origen_label:
            href = f'{href}&origen={quote(origen_label)}'

    return {
        'href': href,
        'etiqueta': definicion['etiqueta'],
        'editable': definicion.get('editable', False),
    }


def enlace_de_hallazgo(hallazgo, forzar_url=None, next_url=None, origen_label=None,
                       usuario=None):
    """Igual que `construir_enlace`, partiendo de un `Hallazgo`.

    Usa `content_type` sin resolver la GenericForeignKey, así que no dispara una
    consulta por fila ni falla si el registro apuntado fue borrado.
    """
    ct = hallazgo.content_type
    etiqueta_modelo = f'{ct.app_label}.{ct.model_class().__name__}' if ct.model_class() else None
    if etiqueta_modelo is None:
        return None
    return construir_enlace(
        etiqueta_modelo, hallazgo.object_id, forzar_url=forzar_url,
        next_url=next_url, origen_label=origen_label, usuario=usuario)
