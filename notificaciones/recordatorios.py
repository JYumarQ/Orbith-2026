"""Recordatorios automáticos: vencimientos y eventos previsibles que ya pueden
calcularse con la información existente (contrato por vencer, documentos de chófer).

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

Cumpleaños (`REC-CUMPLE`) y jubilación próxima (`REC-JUBILACION`) dejaron de
calcularse por decisión de RRHH (no eran una de las categorías que querían conservar):
sus detectores se retiraron de `DETECTORES`. Las filas `ACTIVA` que ya existían se
resolvieron en la migración `0012_resolver_cumpleanos_y_jubilacion_existentes`. La
tarjeta de Cumpleaños del Dashboard es independiente de todo esto: calcula la fecha
directamente desde `Aspirante`, nunca dependió de este módulo.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.contrib.contenttypes.models import ContentType

from contratos.models import CAlta, con_inicio_del_periodo

from .avisos import _registrar_recordatorio, _resolver_notificaciones_obsoletas
from .destinatarios import destinatarios_de_unidad
from .models import Notificacion

HORIZONTE_DIAS = 60

# Ventana propia y más corta para REC-ANTIGUEDAD: a diferencia de un vencimiento de
# contrato (donde avisar con 60 días de margen tiene sentido para gestionar el
# trámite), sumar un año de antigüedad no requiere ninguna acción salvo dejar
# constancia en un Movimiento de Nómina — 10 días de aviso es lo que RRHH pidió.
HORIZONTE_ANTIGUEDAD_DIAS = 10


@dataclass(frozen=True)
class RecordatorioDetectado:
    object_id: str
    titulo: str
    mensaje: str
    fecha_objetivo: date
    clave_extra: str = ''
    unidad_organizativa_id: Optional[int] = None


def _unidad_del_contrato(contrato):
    """Mismo criterio que `notificaciones/avisos.py::_unidad_del_contrato`: la del cargo."""
    if contrato.cargo_id and contrato.cargo.departamento_id:
        return contrato.cargo.departamento.unidad_organizativa_id
    return None


def detectar_contratos_por_vencer(queryset=None):
    """Contratos de alta (no indeterminados) próximos a vencer, de trabajadores activos.

    `queryset`: permite reutilizar este mismo criterio (horizonte, exclusión de
    "INDETERMINADO", cálculo de días) sobre un queryset ya acotado por otro
    llamador — p.ej. el Dashboard, que ya filtra `CAlta` por Unidad
    Organizativa antes de pasarlo aquí, para no tener una segunda fuente de
    verdad sobre cuándo un contrato "está por vencer". Por defecto (sin
    argumento) construye el mismo queryset de siempre.
    """
    contratos = queryset if queryset is not None else (
        CAlta.objects.filter(aspirante__estado='ACTIVO')
        .select_related('aspirante', 'tipo', 'cargo__departamento__unidad_organizativa'))
    # El vencimiento cuenta desde el último movimiento (renovación, 18-11-2026).
    contratos = con_inicio_del_periodo(contratos)
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


_ARTICULO_DOCUMENTO = {'licencia': 'la', 'recalificación': 'la', 'seguro': 'el'}


def _enumerar(partes):
    """['a'] -> 'a'; ['a', 'b', 'c'] -> 'a, b y c'."""
    return partes[0] if len(partes) == 1 else f'{", ".join(partes[:-1])} y {partes[-1]}'


def detectar_documentos_chofer():
    """Fechas de vencimiento de licencia/recalificación/seguro de chóferes, cuando ya
    están registradas y próximas. Complementa a CTR-013 de Subsanación, que cubre el
    caso de fecha SIN registrar."""
    contratos = (CAlta.objects.filter(aspirante__estado='ACTIVO', profesional=True)
                 .select_related('aspirante', 'cargo__departamento__unidad_organizativa'))
    for contrato in contratos:
        unidad_id = _unidad_del_contrato(contrato)
        # Los documentos que vencen el MISMO día van en un solo aviso (18-11-2026):
        # antes llegaban dos o tres avisos con la misma fecha para el mismo chófer.
        por_fecha = {}
        for campo, nombre in _CAMPOS_VENCIMIENTO_CHOFER:
            fecha = getattr(contrato, campo)
            if not fecha:
                continue
            dias = (fecha - date.today()).days
            if dias > HORIZONTE_DIAS:
                continue
            por_fecha.setdefault(fecha, []).append((campo, nombre))
        for fecha, documentos in por_fecha.items():
            nombres = [nombre for _campo, nombre in documentos]
            con_articulo = [f'{_ARTICULO_DOCUMENTO[nombre]} {nombre}' for nombre in nombres]
            verbo = 'vence' if len(nombres) == 1 else 'vencen'
            yield RecordatorioDetectado(
                object_id=str(contrato.pk),
                clave_extra='+'.join(campo for campo, _nombre in documentos),
                titulo=f'Vence {_enumerar(nombres)} de chófer: {contrato.aspirante}',
                mensaje=(
                    f'{_enumerar(con_articulo).capitalize()} de {contrato.aspirante} '
                    f'{verbo} el {fecha.strftime("%d/%m/%Y")}.'),
                fecha_objetivo=fecha,
                unidad_organizativa_id=unidad_id,
            )


def detectar_proximo_aniversario_antiguedad(queryset=None):
    """Cambios de años de servicio que hay que registrar con un movimiento de nómina
    (decisión de RRHH del 19-11-2026; antes avisaba de cada aniversario y el aviso
    se iba solo al pasar el día).

    * Solo los aniversarios (desde la F. Alta Entidad) que CAMBIAN el importe de la
      Escala de Años de Servicio.
    * Avisa `HORIZONTE_ANTIGUEDAD_DIAS` (10) días antes y, si llega el día sin
      movimiento, el aviso se queda hasta que se haga (además, Subsanación CTR-025).
    * Lo cierra CUALQUIER movimiento del contrato con fecha efectiva igual o
      posterior al aniversario.
    * Solo los aniversarios desde la actualización (`annos_servicio.avisos_desde`):
      los anteriores no se reclaman.

    Uno por aniversario (`clave_extra` = su fecha): el del año siguiente es otro aviso.
    """
    from datetime import timedelta

    from contratos.annos_servicio import avisos_desde, cambios_de_importe
    from prenomina.models import NEscalaAnnosServicio

    contratos = queryset if queryset is not None else (
        CAlta.objects.filter(aspirante__estado='ACTIVO')
        .select_related('aspirante', 'cargo__departamento__unidad_organizativa'))
    contratos = con_inicio_del_periodo(contratos)
    hoy = date.today()
    desde = avisos_desde()
    hasta = hoy + timedelta(days=HORIZONTE_ANTIGUEDAD_DIAS)
    escala = NEscalaAnnosServicio.como_diccionario()
    for contrato in contratos:
        ultimo = contrato.ultimo_movimiento
        for dia, annos, antes, despues in cambios_de_importe(
                contrato.fecha_alta_entidad, desde, hasta, escala):
            if ultimo and ultimo >= dia:
                continue  # ya hay un movimiento con fecha efectiva ese día o después
            cuando = 'cumplirá' if dia > hoy else 'cumplió'
            yield RecordatorioDetectado(
                object_id=str(contrato.pk),
                titulo=f'{contrato.aspirante}: cambio de años de servicio ({annos} años)',
                mensaje=(
                    f'{contrato.aspirante} {cuando} {annos} años de servicio el '
                    f'{dia:%d/%m/%Y}: el pago por años de servicio pasa de {antes:.2f} a '
                    f'{despues:.2f}. Registre el movimiento de nómina con fecha efectiva '
                    f'ese día o posterior.'),
                fecha_objetivo=dia,
                clave_extra=dia.isoformat(),
                unidad_organizativa_id=_unidad_del_contrato(contrato),
            )


# `(modelo, codigo, detector)`. `codigo` ocupa `Notificacion.codigo_regla` — identifica
# el TIPO de recordatorio igual que una regla de Subsanación identifica un tipo de
# alerta; es también la clave que usa `_resolver_notificaciones_obsoletas()` para saber
# qué filas ACTIVA de un destinatario hay que revisar en cada pasada.
DETECTORES = (
    (CAlta, 'REC-CONTRATO', detectar_contratos_por_vencer),
    (CAlta, 'REC-CHOFER', detectar_documentos_chofer),
    (CAlta, 'REC-ANTIGUEDAD', detectar_proximo_aniversario_antiguedad),
)


def generar_recordatorios():
    """Corre los detectores, reparte cada recordatorio a los destinatarios de la
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
