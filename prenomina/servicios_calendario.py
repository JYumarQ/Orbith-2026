"""Reglas de negocio del Calendario de Pre-Nómina.

Misma doctrina que `servicios.py`, del que este módulo es hermano: **las vistas
no escriben estado, solo llaman aquí**; toda transición es `@transaction.atomic`
y bloquea con `select_for_update()` lo que vaya a modificar. Los errores son
`ErrorDePreNomina` (reutilizado desde `servicios.py`, para que las vistas no
tengan que capturar dos excepciones distintas) y su mensaje en español va
directo a la interfaz.

Tres reglas sostienen todo lo demás:

1. **Los catálogos son personales.** Cada `Calendario` y cada `CalendarioPago`
   pertenece a un usuario. Ninguna función de aquí acepta un objeto sin
   comprobar antes que es de quien dice ser (`_exigir_propietario`): con datos
   personales, el alcance no puede quedar solo en el queryset de la vista.

2. **Lo cerrado no se toca.** Un `CalendarioPago` cerrado es histórico: ni sus
   horas, ni sus líneas, ni él mismo admiten cambios. Se comprueba aquí y no en
   la plantilla, porque ocultar un botón no es la protección.

3. **Este módulo no cierra períodos por su cuenta.** `cerrar_periodo()` existe
   para que la acción «Cerrar mes» de Gestión de Reportes de Pagos la invoque;
   no hay ningún botón de cierre en la pantalla del calendario. Una sola fuente
   de verdad para el cierre, como pide la especificación.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar as registrar_auditoria

from .constantes import MODULO
from .models import (AsignacionCalendario, Calendario, CalendarioPago,
                     CalendarioPagoDetalle)
from .servicios import ErrorDePreNomina, _nombre_de

logger = logging.getLogger(__name__)

CERO = Decimal('0')
DOS_DECIMALES = Decimal('0.01')

MENSAJE_CERRADO = ('{periodo} está cerrado. Los Calendarios de Pago cerrados no '
                   'pueden editarse ni eliminarse.')


# --------------------------------------------------------------------------- #
# Comprobaciones compartidas
# --------------------------------------------------------------------------- #

def _exigir_propietario(objeto, usuario):
    """El calendario o el período tienen que ser de quien los toca.

    Se compara el `usuario_id` guardado, nunca el rol: que alguien sea
    Administrador no le da permiso para editar el catálogo personal de otro. Lo
    que sí puede el Administrador es **consultarlos** desde el panel de Django.
    """
    if objeto.usuario_id != usuario.pk:
        raise ErrorDePreNomina(
            'Este calendario pertenece a otro usuario, no puede modificarlo.')


def _exigir_abierto(periodo):
    if periodo.cerrado:
        raise ErrorDePreNomina(MENSAJE_CERRADO.format(periodo=periodo.etiqueta))


def _auditar(usuario, accion, instancia, descripcion):
    """Copia literal del `_auditar` de `servicios.py`, con su mismo criterio.

    Va en `try/except` porque **la auditoría nunca debe tumbar la operación
    real**: si falla el registro, se pierde la traza pero el calendario queda
    guardado. Mismo criterio que `auditoria/admin_mixins.py`.

    En los borrados se pasa `instancia=None` a propósito: tras `.delete()` el
    objeto ya no tiene pk, así que no hay de qué derivar el `content_type`; el
    descriptor conserva de qué se trataba.
    """
    try:
        registrar_auditoria(
            usuario=usuario, accion=accion, instancia=instancia,
            descriptor=descripcion[:200], modulo=MODULO)
    except Exception:
        logger.exception('No se pudo auditar la acción %s del calendario.', accion)


def normalizar_horas(valor, etiqueta='Las horas'):
    """Texto de la interfaz → Decimal de dos decimales, o error en español.

    Se acepta la coma como separador decimal porque es lo que teclea quien
    trabaja en español, pero se guarda siempre en el formato canónico. Un valor
    vacío es cero, no un error: dejar una quincena en blanco significa que no
    tiene horas.
    """
    if valor is None:
        return CERO
    texto = str(valor).strip().replace(',', '.')
    if not texto:
        return CERO
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError):
        raise ErrorDePreNomina(
            f'{etiqueta} deben ser un número. Se admiten decimales, por '
            f'ejemplo 80, 80.5 o 88.25.')
    if numero < CERO:
        raise ErrorDePreNomina(
            f'{etiqueta} no pueden ser negativas. Introduzca un número mayor o '
            f'igual a 0.')
    if numero >= Decimal('100000'):
        raise ErrorDePreNomina(f'{etiqueta} superan el máximo admitido.')
    return numero.quantize(DOS_DECIMALES)


def normalizar_codigo(valor):
    """El código solo admite números enteros. Mensaje propio para cada fallo."""
    texto = str(valor or '').strip()
    if not texto:
        raise ErrorDePreNomina('El código es obligatorio.')
    if not texto.isdigit():
        raise ErrorDePreNomina('El código solo admite números enteros.')
    numero = int(texto)
    if numero <= 0:
        raise ErrorDePreNomina('El código debe ser mayor que cero.')
    return numero


def normalizar_descripcion(valor):
    texto = str(valor or '').strip()
    if not texto:
        raise ErrorDePreNomina('La descripción es obligatoria.')
    if len(texto) > 20:
        raise ErrorDePreNomina('La descripción no puede superar los 20 caracteres.')
    return texto


# --------------------------------------------------------------------------- #
# Tarjeta 1: el calendario maestro
# --------------------------------------------------------------------------- #

@transaction.atomic
def crear_calendario(usuario, *, codigo, descripcion, activo=True):
    """Alta de un tipo de jornada en el catálogo personal del usuario."""
    codigo = normalizar_codigo(codigo)
    descripcion = normalizar_descripcion(descripcion)

    if Calendario.objects.filter(usuario=usuario, codigo=codigo).exists():
        raise ErrorDePreNomina(f'Ya existe un calendario con el código {codigo:02d}.')

    calendario = Calendario.objects.create(
        usuario=usuario, codigo=codigo, descripcion=descripcion,
        activo=bool(activo))

    _auditar(usuario, AccionAuditoria.CREAR, calendario,
             f'Creado el calendario {calendario.etiqueta}')
    return calendario


@transaction.atomic
def editar_calendario(calendario, usuario, *, codigo, descripcion, activo,
                      actualizar_historico=False):
    """Modifica un calendario y decide qué hacer con los períodos que ya lo usan.

    `actualizar_historico` solo entra en juego cuando **cambia la descripción** y
    el calendario ya tiene líneas en algún período:

    * `True` → se reescribe `descripcion_historica` en todas sus líneas, incluidas
      las de períodos cerrados. Es una corrección de nombre, no un dato nuevo.
    * `False` → las líneas existentes se quedan como están y el nombre nuevo solo
      se copiará en las que se creen a partir de ahora.

    En ningún caso se tocan el código histórico ni las horas: son el
    identificador y el dato económico del período, y esta decisión es solo sobre
    el nombre.
    """
    calendario = Calendario.objects.select_for_update().get(pk=calendario.pk)
    _exigir_propietario(calendario, usuario)

    codigo = normalizar_codigo(codigo)
    descripcion = normalizar_descripcion(descripcion)

    if (Calendario.objects.filter(usuario=usuario, codigo=codigo)
            .exclude(pk=calendario.pk).exists()):
        raise ErrorDePreNomina(f'Ya existe un calendario con el código {codigo:02d}.')

    cambia_descripcion = descripcion != calendario.descripcion
    anterior = calendario.descripcion

    calendario.codigo = codigo
    calendario.descripcion = descripcion
    calendario.activo = bool(activo)
    calendario.save(update_fields=['codigo', 'descripcion', 'activo'])

    detalle = f'Editado el calendario {calendario.etiqueta}'
    if cambia_descripcion and actualizar_historico:
        actualizadas = calendario.detalles.update(descripcion_historica=descripcion)
        if actualizadas:
            detalle += (f' — descripción propagada a {actualizadas} '
                        f'línea{"s" if actualizadas != 1 else ""} histórica'
                        f'{"s" if actualizadas != 1 else ""} '
                        f'(«{anterior}» → «{descripcion}»)')

    _auditar(usuario, AccionAuditoria.MODIFICAR, calendario, detalle)
    return calendario


@transaction.atomic
def eliminar_calendario(calendario, usuario):
    """Borra un calendario que nunca se haya usado.

    En cuanto tiene una línea en cualquier período —abierto o cerrado— pasa a
    ser histórico y deja de poder borrarse. La alternativa que se le ofrece al
    usuario es marcarlo Inactivo, que lo retira del modal de selección sin
    romper lo ya registrado.
    """
    calendario = Calendario.objects.select_for_update().get(pk=calendario.pk)
    _exigir_propietario(calendario, usuario)

    # Los trabajadores asignados bloquean igual que los períodos: la FK es
    # PROTECT, así que sin esta comprobación el borrado reventaría con un
    # `ProtectedError` crudo —un error 500— en vez de con una explicación.
    asignados = calendario.asignaciones.count()
    if asignados:
        raise ErrorDePreNomina(
            f'No se puede eliminar este calendario: lo tienen asignado '
            f'{asignados} trabajador{"es" if asignados != 1 else ""}. Reasígnelos '
            f'a otra jornada en Pre-Nómina → Asignar Calendario, o márquelo como '
            f'Inactivo en lugar de eliminarlo.')

    periodos = list(calendario.periodos_donde_se_usa)
    if periodos:
        listado = ' · '.join(
            f'{p.etiqueta}{" (cerrado)" if p.cerrado else ""}' for p in periodos[:6])
        if len(periodos) > 6:
            listado += f' y {len(periodos) - 6} más'
        raise ErrorDePreNomina(
            f'No se puede eliminar este calendario: ya ha sido utilizado en '
            f'{len(periodos)} Calendario{"s" if len(periodos) != 1 else ""} de '
            f'Pago ({listado}). Si ya no debe usarse, márquelo como Inactivo en '
            f'lugar de eliminarlo.')

    etiqueta = calendario.etiqueta
    calendario.delete()
    _auditar(usuario, AccionAuditoria.ELIMINAR, None,
             f'Eliminado el calendario {etiqueta}')


@transaction.atomic
def marcar_inactivo(calendario, usuario):
    """Atajo del bloqueo de borrado: la alternativa que se ofrece en el aviso."""
    calendario = Calendario.objects.select_for_update().get(pk=calendario.pk)
    _exigir_propietario(calendario, usuario)

    calendario.activo = False
    calendario.save(update_fields=['activo'])
    _auditar(usuario, AccionAuditoria.MODIFICAR, calendario,
             f'Marcado como Inactivo el calendario {calendario.etiqueta}')
    return calendario


# --------------------------------------------------------------------------- #
# Tarjeta 2: el período
# --------------------------------------------------------------------------- #

def ultimo_periodo(usuario):
    """El período más reciente del usuario, o None si aún no tiene ninguno."""
    return (CalendarioPago.objects.filter(usuario=usuario)
            .order_by('-anno', '-mes').first())


@transaction.atomic
def crear_periodo(usuario, *, anno, mes):
    """Crea el Calendario de Pago de un año+mes.

    Dos reglas, en este orden porque el mensaje de la primera es más concreto:

    1. No puede haber dos períodos para el mismo año+mes.
    2. Salvo el primero de todos, un período nuevo tiene que ser **estrictamente
       posterior** al último existente. La comparación es cronológica sobre
       (año, mes), no sobre la fecha de creación.
    """
    from cierres.periodos import Periodo

    try:
        periodo = Periodo(int(anno), int(mes))
    except (TypeError, ValueError):
        raise ErrorDePreNomina('El año y el mes indicados no son válidos.')

    if CalendarioPago.objects.filter(usuario=usuario, anno=periodo.anno,
                                     mes=periodo.mes).exists():
        raise ErrorDePreNomina(
            f'Ya existe un Calendario de Pago para {periodo.etiqueta}.')

    ultimo = ultimo_periodo(usuario)
    if ultimo is not None and periodo <= ultimo.periodo:
        raise ErrorDePreNomina(
            f'No se puede crear un período anterior a {ultimo.etiqueta}. '
            f'Es el último período registrado; solo se admiten fechas '
            f'posteriores que aún no existan.')

    calendario_pago = CalendarioPago.objects.create(
        usuario=usuario, anno=periodo.anno, mes=periodo.mes)

    _auditar(usuario, AccionAuditoria.CREAR, calendario_pago,
             f'Creado el Calendario de Pago de {periodo.etiqueta}')
    return calendario_pago


@transaction.atomic
def eliminar_periodo(calendario_pago, usuario):
    """Borra un período abierto y sus líneas. Los cerrados son intocables."""
    calendario_pago = CalendarioPago.objects.select_for_update().get(
        pk=calendario_pago.pk)
    _exigir_propietario(calendario_pago, usuario)
    _exigir_abierto(calendario_pago)

    etiqueta = calendario_pago.etiqueta
    calendario_pago.delete()   # las líneas van en cascada
    _auditar(usuario, AccionAuditoria.ELIMINAR, None,
             f'Eliminado el Calendario de Pago de {etiqueta}')


@transaction.atomic
def seleccionar_calendarios(calendario_pago, usuario, codigos_pk):
    """Añade al período las líneas de los calendarios elegidos en el modal.

    Solo entran los **activos**: un calendario inactivo está retirado de
    circulación y no debe poder incorporarse a un período nuevo, aunque siga
    apareciendo en los antiguos. Los que ya estaban en el período se ignoran en
    silencio, para que reabrir el modal y confirmar no duplique ni falle.

    Cada línea copia el código y la descripción **vigentes en este momento**:
    es la fotografía que después permite renombrar el maestro sin reescribir el
    histórico.
    """
    calendario_pago = CalendarioPago.objects.select_for_update().get(
        pk=calendario_pago.pk)
    _exigir_propietario(calendario_pago, usuario)
    _exigir_abierto(calendario_pago)

    elegidos = list(Calendario.objects.filter(
        pk__in=codigos_pk, usuario=usuario, activo=True))
    if not elegidos:
        raise ErrorDePreNomina(
            'Seleccione al menos un calendario activo para añadirlo al período.')

    ya_estan = set(calendario_pago.detalles.values_list('calendario_id', flat=True))
    nuevas = [
        CalendarioPagoDetalle(
            calendario_pago=calendario_pago,
            calendario=calendario,
            codigo_historico=calendario.codigo,
            descripcion_historica=calendario.descripcion)
        for calendario in elegidos if calendario.pk not in ya_estan
    ]
    if nuevas:
        CalendarioPagoDetalle.objects.bulk_create(nuevas)
        _auditar(usuario, AccionAuditoria.MODIFICAR, calendario_pago,
                 f'Añadido{"s" if len(nuevas) != 1 else ""} {len(nuevas)} '
                 f'calendario{"s" if len(nuevas) != 1 else ""} al Calendario de '
                 f'Pago de {calendario_pago.etiqueta}')
    return nuevas


@transaction.atomic
def quitar_detalle(detalle, usuario):
    """Retira una línea de un período abierto."""
    detalle = (CalendarioPagoDetalle.objects
               .select_related('calendario_pago')
               .select_for_update().get(pk=detalle.pk))
    _exigir_propietario(detalle.calendario_pago, usuario)
    _exigir_abierto(detalle.calendario_pago)

    etiqueta = detalle.calendario_pago.etiqueta
    descripcion = detalle.descripcion_historica
    detalle.delete()
    _auditar(usuario, AccionAuditoria.MODIFICAR, None,
             f'Retirado «{descripcion}» del Calendario de Pago de {etiqueta}')


@transaction.atomic
def guardar_horas(detalle, usuario, *, horas_q1=None, horas_q2=None):
    """Guarda la edición en línea de una quincena.

    Se pasa solo la quincena que se editó; la otra llega como `None` y se
    conserva. `horas_mes` no se guarda: es una propiedad calculada, así que no
    hay forma de que quede desincronizada de sus dos sumandos.
    """
    detalle = (CalendarioPagoDetalle.objects
               .select_related('calendario_pago')
               .select_for_update().get(pk=detalle.pk))
    _exigir_propietario(detalle.calendario_pago, usuario)
    _exigir_abierto(detalle.calendario_pago)

    campos = []
    if horas_q1 is not None:
        detalle.horas_q1 = normalizar_horas(horas_q1, 'Las horas de la 1ra quincena')
        campos.append('horas_q1')
    if horas_q2 is not None:
        detalle.horas_q2 = normalizar_horas(horas_q2, 'Las horas de la 2da quincena')
        campos.append('horas_q2')

    if campos:
        detalle.save(update_fields=campos)
    return detalle


# --------------------------------------------------------------------------- #
# Cierre: lo invoca «Cerrar mes» de Gestión de Reportes de Pagos
# --------------------------------------------------------------------------- #

@transaction.atomic
def cerrar_periodo(usuario, *, anno, mes, cerrado_por=None):
    """Marca como cerrado el Calendario de Pago de ese año+mes del usuario.

    **No la llama ninguna pantalla del calendario**: es el enganche que usa el
    cierre de Gestión de Reportes de Pagos para que ambos módulos queden
    sincronizados sin duplicar la lógica de cierre.

    Es idempotente y silenciosa si no hay período: cerrar el reporte de un mes
    para el que nunca se creó un calendario no es un error, simplemente no hay
    nada que cerrar.
    """
    periodo = (CalendarioPago.objects.select_for_update()
               .filter(usuario=usuario, anno=anno, mes=mes).first())
    if periodo is None or periodo.cerrado:
        return periodo

    periodo.cerrado = True
    periodo.fecha_cierre = timezone.now()
    periodo.cerrado_por_nombre = _nombre_de(cerrado_por or usuario)
    periodo.save(update_fields=['cerrado', 'fecha_cierre', 'cerrado_por_nombre'])

    _auditar(cerrado_por or usuario, AccionAuditoria.MODIFICAR, periodo,
             f'Cerrado el Calendario de Pago de {periodo.etiqueta}')
    return periodo


@transaction.atomic
def reabrir_periodo(usuario, *, anno, mes, reabierto_por=None):
    """Devuelve a Activo un período cerrado.

    Contrapartida de `cerrar_periodo()`, para cuando se reabre el reporte del
    mes: si el mes vuelve a admitir correcciones, sus horas también deben
    hacerlo. Igual que aquélla, es idempotente y no falla si no hay período.
    """
    periodo = (CalendarioPago.objects.select_for_update()
               .filter(usuario=usuario, anno=anno, mes=mes).first())
    if periodo is None or not periodo.cerrado:
        return periodo

    periodo.cerrado = False
    periodo.fecha_cierre = None
    periodo.cerrado_por_nombre = ''
    periodo.save(update_fields=['cerrado', 'fecha_cierre', 'cerrado_por_nombre'])

    _auditar(reabierto_por or usuario, AccionAuditoria.MODIFICAR, periodo,
             f'Reabierto el Calendario de Pago de {periodo.etiqueta}')
    return periodo


# --------------------------------------------------------------------------- #
# Tarjeta 3: asignación de calendarios a los trabajadores
# --------------------------------------------------------------------------- #

@transaction.atomic
def asignar_calendario(contratos_pk, calendario, usuario):
    """Asigna un calendario a varios trabajadores de una vez.

    La asignación es **permanente**: se guarda una sola por trabajador y se
    conserva hasta que alguien la cambie. Los reportes congelan sus horas al
    crearse, así que reasignar más adelante no reescribe ningún período pasado.

    `contratos_pk` ya viene acotado por la vista al alcance del usuario (sus
    unidades, o todas si es Administrador); aquí se vuelve a filtrar contra ese
    mismo alcance porque una lista de identificadores que llega por POST no es
    de fiar.
    """
    from contratos.models import CAlta

    _exigir_propietario(calendario, usuario)
    if not calendario.activo:
        raise ErrorDePreNomina(
            f'El calendario {calendario.etiqueta} está Inactivo: actívelo antes '
            f'de asignarlo a trabajadores.')

    from .filtros import unidades_gestionables
    permitidos = (CAlta.objects
                  .filter(pk__in=contratos_pk,
                          cargo__departamento__unidad_organizativa__in=
                          unidades_gestionables(usuario))
                  .values_list('pk', flat=True))
    permitidos = list(permitidos)
    if not permitidos:
        raise ErrorDePreNomina(
            'Seleccione al menos un trabajador de sus Unidades Organizativas.')

    for contrato_pk in permitidos:
        AsignacionCalendario.objects.update_or_create(
            contrato_id=contrato_pk,
            defaults={'calendario': calendario, 'asignado_por': usuario})

    _auditar(usuario, AccionAuditoria.MODIFICAR, calendario,
             f'Asignado el calendario {calendario.etiqueta} a {len(permitidos)} '
             f'trabajador{"es" if len(permitidos) != 1 else ""}')
    return len(permitidos)


@transaction.atomic
def quitar_asignacion(contratos_pk, usuario):
    """Deja sin calendario a los trabajadores indicados."""
    from contratos.models import CAlta
    from .filtros import unidades_gestionables

    permitidos = (CAlta.objects
                  .filter(pk__in=contratos_pk,
                          cargo__departamento__unidad_organizativa__in=
                          unidades_gestionables(usuario))
                  .values_list('pk', flat=True))
    borradas, _ = AsignacionCalendario.objects.filter(
        contrato_id__in=list(permitidos)).delete()

    if borradas:
        _auditar(usuario, AccionAuditoria.MODIFICAR, None,
                 f'Retirada la asignación de calendario a {borradas} '
                 f'trabajador{"es" if borradas != 1 else ""}')
    return borradas
