"""Recordatorios automáticos: vencimientos y eventos previsibles que ya pueden
calcularse con la información existente (cumpleaños, contrato por vencer, documentos
de chófer, jubilación próxima).

No pasan por la maquinaria de reglas de Subsanación (no hay `Hallazgo`/
`EjecucionAnalisis` para un Recordatorio: no es una auditoría de integridad, es un
aviso de que algo está por ocurrir). Cada detector es una función pura que produce
`RecordatorioDetectado`; `generar_recordatorios()` los reparte por unidad reutilizando
`destinatarios_de_unidad()` y el mismo mecanismo de deduplicación/resolución que
`notificaciones/avisos.py` ya usa para las Advertencias.

Horizonte de detección: `HORIZONTE_DIAS` (60, coincide con el primer tramo de color,
🟢 ≥60 días — más allá de eso el recordatorio no se crea todavía). Un recordatorio ya
vencido (`fecha_objetivo` en el pasado) NO desaparece por antigüedad aquí: sigue activo
hasta que la condición que lo originó deje de cumplirse (se resuelve exactamente igual
que una Advertencia) o hasta la purga automática a 60 días de RESUELTA
(`notificaciones/limpieza.py`).

Fuera de esta ronda (decisión ya tomada): "Fin de misión" — no existe ningún campo de
fecha que lo respalde hoy; se añadirá un detector más cuando exista.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from django.contrib.contenttypes.models import ContentType

from bolsa.models import Aspirante
from contratos.models import CAlta

from .avisos import _registrar_recordatorio, _resolver_notificaciones_obsoletas
from .destinatarios import destinatarios_de_unidad
from .models import Notificacion

HORIZONTE_DIAS = 60


@dataclass(frozen=True)
class RecordatorioDetectado:
    object_id: str
    titulo: str
    mensaje: str
    fecha_objetivo: date
    clave_extra: str = ''
    unidad_organizativa_id: Optional[int] = None


def _unidad_del_contrato(contrato):
    """Mismo criterio de respaldo que `notificaciones/avisos.py::_unidad_del_contrato`
    (la del cargo si tiene, si no la del aspirante)."""
    if contrato.cargo_id and contrato.cargo.departamento_id:
        return contrato.cargo.departamento.unidad_organizativa_id
    if contrato.aspirante_id:
        return contrato.aspirante.unidad_organizativa_id
    return None


def detectar_cumpleanos():
    """Cumpleaños dentro del horizonte, de trabajadores activos."""
    hoy = date.today()
    aspirantes = (Aspirante.objects.filter(estado='ACTIVO', fecha_nacimiento__isnull=False)
                  .only('id', 'nombre', 'papellido', 'sapellido', 'fecha_nacimiento',
                        'unidad_organizativa_id'))
    for aspirante in aspirantes:
        dias = aspirante.dias_hasta_cumpleanos
        if dias is None or dias > HORIZONTE_DIAS:
            continue
        fecha_objetivo = hoy + timedelta(days=dias)
        yield RecordatorioDetectado(
            object_id=str(aspirante.pk),
            titulo=f'Cumpleaños de {aspirante}',
            mensaje=f'{aspirante} cumple años el {fecha_objetivo.strftime("%d/%m/%Y")}.',
            fecha_objetivo=fecha_objetivo,
            unidad_organizativa_id=aspirante.unidad_organizativa_id,
        )


def detectar_contratos_por_vencer():
    """Contratos de alta (no indeterminados) próximos a vencer, de trabajadores activos."""
    contratos = (CAlta.objects.filter(aspirante__estado='ACTIVO')
                 .select_related('aspirante', 'tipo', 'cargo__departamento__unidad_organizativa'))
    for contrato in contratos:
        if contrato.tipo and 'INDETERMINADO' in (contrato.tipo.descripcion or '').upper():
            continue
        dias = contrato.dias_restantes
        if dias is None or dias > HORIZONTE_DIAS:
            continue
        yield RecordatorioDetectado(
            object_id=str(contrato.pk),
            titulo=f'Contrato de {contrato.aspirante} próximo a vencer',
            mensaje=(
                f'El contrato {contrato.no_expediente} de {contrato.aspirante} vence el '
                f'{contrato.fecha_vencimiento.strftime("%d/%m/%Y")}.'),
            fecha_objetivo=contrato.fecha_vencimiento,
            unidad_organizativa_id=_unidad_del_contrato(contrato),
        )


_CAMPOS_VENCIMIENTO_CHOFER = (
    ('fecha_vence_lic', 'licencia'),
    ('fecha_vence_recal', 'recalificación'),
    ('fecha_vence_seg', 'seguro'),
)


def detectar_documentos_chofer():
    """Fechas de vencimiento de licencia/recalificación/seguro de chóferes, cuando ya
    están registradas y próximas. Complementa a CTR-013 de Subsanación, que cubre el
    caso de fecha SIN registrar."""
    contratos = (CAlta.objects.filter(aspirante__estado='ACTIVO', profesional=True)
                 .select_related('aspirante', 'cargo__departamento__unidad_organizativa'))
    for contrato in contratos:
        unidad_id = _unidad_del_contrato(contrato)
        for campo, nombre in _CAMPOS_VENCIMIENTO_CHOFER:
            fecha = getattr(contrato, campo)
            if not fecha:
                continue
            dias = (fecha - date.today()).days
            if dias > HORIZONTE_DIAS:
                continue
            yield RecordatorioDetectado(
                object_id=str(contrato.pk), clave_extra=campo,
                titulo=f'Vence {nombre} de chófer: {contrato.aspirante}',
                mensaje=(
                    f'La {nombre} de {contrato.aspirante} vence el '
                    f'{fecha.strftime("%d/%m/%Y")}.'),
                fecha_objetivo=fecha,
                unidad_organizativa_id=unidad_id,
            )


def detectar_jubilacion_proxima():
    """Trabajadores activos que entran (o ya están) en la ventana de pre-jubilación."""
    hoy = date.today()
    aspirantes = Aspirante.objects.filter(estado='ACTIVO', fecha_nacimiento__isnull=False)
    for aspirante in aspirantes:
        dias = aspirante.dias_hasta_jubilacion
        if dias is None or dias > HORIZONTE_DIAS:
            continue
        fecha_objetivo = hoy + timedelta(days=dias)
        if dias >= 0:
            mensaje = f'{aspirante} alcanza la edad de pre-jubilación el {fecha_objetivo.strftime("%d/%m/%Y")}.'
        else:
            mensaje = f'{aspirante} ya está en edad de pre-jubilación.'
        yield RecordatorioDetectado(
            object_id=str(aspirante.pk),
            titulo=f'Jubilación próxima: {aspirante}',
            mensaje=mensaje,
            fecha_objetivo=fecha_objetivo,
            unidad_organizativa_id=aspirante.unidad_organizativa_id,
        )


# `(modelo, codigo, detector)`. `codigo` ocupa `Notificacion.codigo_regla` — identifica
# el TIPO de recordatorio igual que una regla de Subsanación identifica un tipo de
# alerta; es también la clave que usa `_resolver_notificaciones_obsoletas()` para saber
# qué filas ACTIVA de un destinatario hay que revisar en cada pasada.
DETECTORES = (
    (Aspirante, 'REC-CUMPLE', detectar_cumpleanos),
    (CAlta, 'REC-CONTRATO', detectar_contratos_por_vencer),
    (CAlta, 'REC-CHOFER', detectar_documentos_chofer),
    (Aspirante, 'REC-JUBILACION', detectar_jubilacion_proxima),
)


def generar_recordatorios():
    """Corre los 4 detectores, reparte cada recordatorio a los destinatarios de la
    unidad correspondiente (moderador(es) + administradores, vía
    `destinatarios_de_unidad()`; sin unidad -> todos los administradores activos,
    mismo criterio que `notificaciones/escaneo.py`) y resuelve los que ya no aplican.

    La resolución se comprueba contra CUALQUIER destinatario que tenga hoy una fila
    ACTIVA de ese código (no solo los notificados en esta misma pasada): así, si un
    recordatorio deja de detectarse para todo el mundo, se resuelve igual aunque su
    antiguo destinatario ya no sea moderador de la unidad que lo originó.

    Devuelve `{'generados': N, 'sin_unidad': M}`.
    """
    from usuarios.models import CustomUser

    generados = 0
    sin_unidad = 0

    for modelo, codigo, detector in DETECTORES:
        tipo_ct = ContentType.objects.get_for_model(modelo)
        detectados = list(detector())

        claves_vigentes = set()
        destinatarios_notificados = set()

        for detectado in detectados:
            if detectado.unidad_organizativa_id is not None:
                destinatarios = list(destinatarios_de_unidad(detectado.unidad_organizativa_id))
            else:
                destinatarios = list(CustomUser.objects.filter(es_admin=True, is_active=True))
                sin_unidad += 1

            for destinatario in destinatarios:
                _registrar_recordatorio(
                    tipo_ct=tipo_ct, object_id=detectado.object_id, destinatario=destinatario,
                    codigo=codigo, clave_extra=detectado.clave_extra,
                    titulo=detectado.titulo, mensaje=detectado.mensaje,
                    fecha_objetivo=detectado.fecha_objetivo,
                    unidad_id=detectado.unidad_organizativa_id)
                destinatarios_notificados.add(destinatario)
                generados += 1

            claves_vigentes.add(
                (tipo_ct.id, detectado.object_id, codigo, detectado.clave_extra))

        destinatarios_con_activas = CustomUser.objects.filter(
            notificaciones_personales__tipo=Notificacion.Tipo.RECORDATORIO,
            notificaciones_personales__estado=Notificacion.Estado.ACTIVA,
            notificaciones_personales__codigo_regla=codigo,
        ).distinct()

        for destinatario in set(destinatarios_con_activas) | destinatarios_notificados:
            _resolver_notificaciones_obsoletas(
                destinatario=destinatario, codigos_relevantes={codigo},
                claves_vigentes=claves_vigentes)

    return {'generados': generados, 'sin_unidad': sin_unidad}
