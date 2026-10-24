"""Cambios externos: lo que un cambio MÁS ARRIBA del contrato le hace a cada
trabajador afectado (decisión de RRHH del 23-10-2026). Ver `CambioExterno`.

Cómo se usa
-----------
Las pantallas que editan algo de lo que dependen los contratos (escala salarial,
cargo, nomenclador de cargo, departamento, unidad, importes, ficha) envuelven el
guardado en::

    with transaction.atomic(), motivo_de_cambio(motivo, error_humano, exigir=True):
        objeto.save()

El `save()` del modelo (o la vista de la escala) calcula qué contratos cambian de
verdad y llama a `registrar_cambio()`. Si alguno cambia y la pantalla no trajo
motivo ni marcó «Error humano», se lanza `MotivoRequerido`: la vista deshace la
transacción y vuelve a pedirlo diciendo a cuántos contratos afecta.

Fuera de una pantalla (Admin de Django, un script, una migración) no se exige: el
cambio se registra igual, con el motivo vacío.
"""

import logging
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_local = threading.local()


class MotivoRequerido(Exception):
    """El cambio afecta a contratos y no trae motivo ni «Error humano»."""

    def __init__(self, afectados):
        self.afectados = afectados
        contratos = 'contrato' if afectados == 1 else 'contratos'
        super().__init__(
            f'Este cambio afecta a {afectados} {contratos}. Indique el motivo del cambio '
            f'o marque «Error humano» si corrige un error de tecleo.')


@dataclass
class _Contexto:
    motivo: str = ''
    error_humano: bool = False
    exigir: bool = False
    lotes: list = field(default_factory=list)


@contextmanager
def motivo_de_cambio(motivo='', error_humano=False, exigir=True):
    """Hace llegar el motivo de la pantalla hasta los `save()` de los modelos."""
    anterior = getattr(_local, 'contexto', None)
    _local.contexto = _Contexto(motivo=(motivo or '').strip(), error_humano=bool(error_humano),
                                exigir=exigir)
    try:
        yield _local.contexto
    finally:
        _local.contexto = anterior


def contexto_actual():
    return getattr(_local, 'contexto', None) or _Contexto()


@dataclass
class Afectado:
    """Lo que el cambio le hizo a UN contrato."""
    contrato: object
    descripcion: str
    valor_anterior: str = ''
    valor_nuevo: str = ''


def registrar_cambio(origen, objeto_origen, afectados):
    """Escribe una fila de `CambioExterno` por contrato afectado y devuelve el lote.

    `afectados` solo debe traer contratos a los que el cambio les cambió algo de
    verdad. Sin afectados no se escribe nada (ni se exige motivo).
    """
    from django.contrib.contenttypes.models import ContentType

    from auditoria.middleware import get_current_user

    from .models import CambioExterno

    afectados = [a for a in afectados if a.contrato is not None and a.contrato.aspirante_id]
    if not afectados:
        return None

    contexto = contexto_actual()
    if contexto.exigir and not contexto.motivo and not contexto.error_humano:
        raise MotivoRequerido(len(afectados))

    usuario = get_current_user()
    if usuario is not None and not getattr(usuario, 'is_authenticated', False):
        usuario = None
    tipo = ContentType.objects.get_for_model(type(objeto_origen))
    lote = uuid.uuid4().hex

    if contexto.error_humano:
        # Corrige un error: anula el último cambio REAL del mismo origen, que deja
        # de verse en el histórico igual que esta corrección.
        ultimo = (CambioExterno.objects
                  .filter(origen_content_type=tipo, origen_object_id=str(objeto_origen.pk),
                          error_humano=False, anulado=False)
                  .order_by('-fecha').values_list('lote', flat=True).first())
        if ultimo:
            CambioExterno.objects.filter(lote=ultimo).update(anulado=True)

    CambioExterno.objects.bulk_create([
        CambioExterno(
            contrato=a.contrato, aspirante_id=a.contrato.aspirante_id,
            no_expediente=a.contrato.no_expediente or '',
            origen=origen, origen_content_type=tipo, origen_object_id=str(objeto_origen.pk),
            lote=lote, descripcion=a.descripcion,
            valor_anterior=str(a.valor_anterior or '')[:150],
            valor_nuevo=str(a.valor_nuevo or '')[:150],
            motivo=contexto.motivo, error_humano=contexto.error_humano,
            usuario=usuario,
            usuario_nombre=(usuario.get_full_name() or usuario.username) if usuario else 'Sistema',
        )
        for a in afectados
    ])
    contexto.lotes.append(lote)
    reevaluar_advertencias([a.contrato for a in afectados])
    return lote


def reevaluar_advertencias(contratos):
    """Vuelve a evaluar las advertencias de los contratos afectados: el cambio de
    arriba no guarda el contrato, así que sin esto un problema nuevo (sin salario
    calculable, sin tridente…) no aparecería hasta que alguien lo guardara."""
    from notificaciones.avisos import avisar_hallazgos_en_caliente
    from subsanacion.por_registro import revisar_contratos

    for contrato in contratos:
        try:
            avisar_hallazgos_en_caliente(contrato)
        except Exception:
            logger.exception('No se pudieron reevaluar las advertencias del contrato %s.',
                             getattr(contrato, 'pk', None))
    revisar_contratos(contratos)


def texto_del_motivo():
    """Para los avisos de la campana: «Motivo: …» o «Corrección de error humano»."""
    contexto = contexto_actual()
    if contexto.error_humano:
        return 'Corrección de un error humano.'
    if contexto.motivo:
        return f'Motivo: {contexto.motivo}'
    return ''


def motivo_del_post(request):
    """`(motivo, error_humano)` del bloque común `base/partials/motivo_cambio.html`."""
    return (request.POST.get('motivo_cambio', '').strip(),
            request.POST.get('error_humano') in ('1', 'true', 'on'))


def registrar_renombre(origen, objeto, descripcion, anterior, nuevo, unidad=None,
                       **filtro_contratos):
    """Cambio que no toca dinero (un nombre, una ubicación) pero sí cómo aparece el
    trabajador en sus documentos: se anota para todos los contratos afectados y se
    avisa en la campana con un solo aviso resumido."""
    from .models import CAlta

    contratos = list(CAlta.objects.filter(**filtro_contratos).select_related('aspirante'))
    if not contratos:
        return None
    lote = registrar_cambio(origen, objeto, [
        Afectado(c, descripcion, anterior, nuevo) for c in contratos])
    try:
        from notificaciones.avisos import CODIGO_CAMBIO_ESTRUCTURA, avisar_cambio_salarial
        total = len(contratos)
        avisar_cambio_salarial(
            objeto, codigo=CODIGO_CAMBIO_ESTRUCTURA, titulo='Cambio en la estructura',
            unidad=unidad,
            mensaje=' '.join(p for p in (
                descripcion, 'Afecta a %s %s.' % (total, 'contrato' if total == 1 else 'contratos'),
                texto_del_motivo()) if p))
    except Exception:
        logger.exception('No se pudo avisar del cambio de %s.', objeto)
    return lote


def registrar_cambio_de_importe(objeto, concepto, anterior, nuevo, **filtro_contratos):
    """El importe de un nomenclador (CNCI, Instructor, Maestría, Doctorado) cambió:
    los contratos que lo usan cobran el nuevo desde hoy (el contrato no guarda el
    importe). Se anota en su histórico y se avisa en la campana."""
    from .models import CAlta, CambioExterno

    contratos = list(CAlta.objects.filter(**filtro_contratos).select_related('aspirante'))
    if not contratos:
        return None
    descripcion = f'El importe de {concepto} cambió de {anterior} a {nuevo}.'
    lote = registrar_cambio(CambioExterno.Origen.IMPORTE, objeto, [
        Afectado(c, descripcion, f'{concepto}: {anterior}', f'{concepto}: {nuevo}')
        for c in contratos])
    try:
        from notificaciones.avisos import CODIGO_CAMBIO_IMPORTE, avisar_cambio_salarial
        total = len(contratos)
        avisar_cambio_salarial(
            objeto, codigo=CODIGO_CAMBIO_IMPORTE, titulo='Cambio en un importe',
            mensaje=' '.join(p for p in (
                descripcion,
                'Se aplica a %s %s.' % (total, 'contrato' if total == 1 else 'contratos'),
                texto_del_motivo()) if p))
    except Exception:
        logger.exception('No se pudo avisar del cambio de importe de %s.', objeto)
    return lote
