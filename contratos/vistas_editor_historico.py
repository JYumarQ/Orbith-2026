"""Pantalla del editor del histórico (fase 4, 24-10-2026). Solo el Administrador.

La pantalla trabaja en BORRADOR: el navegador guarda la lista de cambios y, cada
vez que el Administrador toca algo, la manda a `previa`, que la aplica sobre una
copia con el motor (`contratos/editor_historico.py`) y devuelve cómo quedaría el
histórico, los errores y el resumen. Nada se escribe hasta `guardar`.

    página   GET  /contrato/editor-historico/<id>/
    previa   POST /contrato/editor-historico/<id>/previa/    {"cambios": [...]}
    guardar  POST /contrato/editor-historico/<id>/guardar/   {"cambios", "motivo", "version"}
    calcular GET  /contrato/editor-historico/<id>/calcular/?cargo=&tipo_salario=&tridente=
"""

import json
import logging
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from bolsa.models import Aspirante
from usuarios.permisos_especiales import permiso_required

# Administrador, o Moderador con el permiso especial «Editor del histórico»
# (25-10-2026, ver `usuarios/permisos_especiales.py`).
admin_required = permiso_required('editor_historico')

from . import editor_historico as eh

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Datos para el navegador
# --------------------------------------------------------------------------

def _iso(fecha):
    return fecha.isoformat() if fecha else ''


def _estado_json(estado):
    return {clave: (str(valor) if isinstance(valor, Decimal) else valor) for clave, valor in estado.items()}


def _eventos_json(historico, meses=None):
    """Los eventos con su contrato (C1, C2…) para pintar la línea de tiempo."""
    meses = meses or {}
    grupos = eh.ciclos(historico, incluir_borrados=True)
    ultimo = eh.ultimo_del_vigente(historico)
    salida = []
    for numero, grupo in enumerate(grupos, start=1):
        abierto = grupo[-1].tipo != eh.BAJA or grupo[-1].borrado
        for e in grupo:
            salida.append({
                'clave': e.clave, 'tipo': e.tipo, 'nombre': e.nombre, 'contrato': numero,
                'contrato_abierto': abierto and numero == len(grupos),
                'recontratacion': e.tipo == eh.ALTA and numero > 1,
                'fecha': _iso(e.fecha), 'fecha_solicitud': _iso(e.fecha_solicitud),
                'fecha_documento': _iso(e.fecha_documento), 'observaciones': e.observaciones,
                'duracion': e.duracion, 'causa_baja_id': e.causa_baja_id, 'causa_baja': e.causa_baja,
                'estado': _estado_json(e.estado), 'antes': _estado_json(e.antes),
                'ids': e.ids, 'borrado': e.borrado, 'nuevo': e.nuevo, 'editado': sorted(e.editado),
                'meses_cerrados': meses.get(e.clave, []),
                'a_mano': e.a_mano, 'unidad_fk_id': e.unidad_fk_id, 'unidad_fk': e.unidad_fk,
                'plaza_reconocida': e.plaza_reconocida,
                'ultimo_vigente': ultimo is not None and e.clave == ultimo.clave,
            })
    return salida


def _catalogos():
    """Lo que se puede elegir en la mesa. Los cargos inactivos también: un movimiento
    antiguo pudo ser a un cargo que ya no existe en la plantilla de hoy."""
    from nomencladores.models import (NCargo, NCausaAltaBaja, NGrupoEscala, NMotivoContrato, NRol,
                                      NTipoContrato, NTridente)
    from strorganizativa.models import CargoPlantilla, UnidadOrganizativa

    from .views import nivel_romano_a_int

    cargos = []
    for c in (CargoPlantilla.objects
              .select_related('ncargo__grupo_escala', 'departamento__unidad_organizativa', 'rol')
              .order_by('departamento__unidad_organizativa__orden_informe',
                        'departamento__unidad_organizativa__descripcion',
                        'departamento__orden_informe', 'orden_informe', 'pk')):
        departamento = c.departamento
        unidad = departamento.unidad_organizativa if departamento else None
        cargos.append({
            'id': c.pk, 'cargo': c.ncargo.descripcion if c.ncargo_id else eh.SIN_DATO,
            'departamento': departamento.descripcion if departamento else eh.SIN_DATO,
            'unidad': unidad.descripcion if unidad else eh.SIN_DATO,
            'grupo': c.ncargo.grupo_escala.nivel if c.ncargo_id and c.ncargo.grupo_escala_id else eh.SIN_DATO,
            'rol': c.rol.tipo if c.rol_id else eh.SIN_DATO,
            'activo': bool(c.activo),
            # Para la cascada Unidad → Departamento → Cargo y las reglas del contrato.
            'departamento_id': departamento.pk if departamento else None,
            'unidad_id': unidad.pk if unidad else None,
            'cat': c.ncargo.get_cat_ocupacional_display() if c.ncargo_id else eh.SIN_DATO,
            'es_cuadro': bool(c.ncargo_id and c.ncargo.es_cuadro),
        })
    return {
        'cargos': cargos,
        'tipos': list(NTipoContrato.objects.order_by('descripcion').values('id', 'descripcion', 'requiere_motivo')),
        'motivos': list(NMotivoContrato.objects.order_by('descripcion').values('id', 'descripcion', 'tipo_contrato_id')),
        'tridentes': [{'id': t.pk, 'texto': str(t)} for t in NTridente.objects.order_by('pk')],
        'causas': list(NCausaAltaBaja.objects.order_by('descripcion').values('id', 'descripcion', 'alta')),
        # «Escribir a mano»: la unidad de hoy a la que corresponde y las listas.
        'unidades': [{'id': u.pk, 'descripcion': u.descripcion}
                     for u in UnidadOrganizativa.objects.order_by('orden_informe', 'descripcion')],
        'grupos': sorted(NGrupoEscala.objects.values_list('nivel', flat=True), key=nivel_romano_a_int),
        'categorias': [etiqueta for _, etiqueta in NCargo._meta.get_field('cat_ocupacional').choices],
        'roles': list(NRol.objects.order_by('tipo').values_list('tipo', flat=True)),
    }


def _resumen_json(res):
    estado = res.get('estado_persona')
    return {
        'cambios': [list(fila) for fila in res['cambios']],
        'ajustes': res['ajustes'],
        'estado_persona': list(estado) if estado else None,
        'meses': res.get('meses', []),
    }


def _leer_peticion(request):
    try:
        datos = json.loads(request.body or b'{}')
    except ValueError:
        raise eh.ErrorDeBorrador('La petición no es válida. Recargue el editor.')
    cambios = datos.get('cambios') or []
    if not isinstance(cambios, list):
        raise eh.ErrorDeBorrador('La petición no es válida. Recargue el editor.')
    return datos, cambios


# --------------------------------------------------------------------------
# Vistas
# --------------------------------------------------------------------------

@admin_required
@require_GET
def editor_historico(request, aspirante_id):
    from cierres.correcciones import meses_por_evento

    from .models import CAlta, CBaja

    persona = get_object_or_404(Aspirante, pk=aspirante_id)
    historico = eh.cargar(persona)
    contrato = CAlta.objects.filter(aspirante=persona).select_related('cargo__departamento__unidad_organizativa').first()
    expediente = eh._expediente_de(historico)
    unidad = ''
    if contrato and contrato.cargo_id and contrato.cargo.departamento_id:
        unidad = contrato.cargo.departamento.unidad_organizativa.descripcion
    datos = {
        'aspirante_id': persona.pk,
        'version': historico.version,
        'eventos': _eventos_json(historico, meses_por_evento(historico)),
        'anomalias': historico.anomalias,
        'catalogos': _catalogos(),
        'tiene_contrato': contrato is not None,
    }
    return render(request, 'pages/contrato/editor_historico.html', {
        'persona': persona,
        'expediente': expediente or '---',
        'unidad': unidad,
        'contratos': len(eh.ciclos(historico)),
        'eventos': len(historico.vivos()),
        'bajas_sueltas': CBaja.objects.filter(aspirante=persona).count(),
        'datos_editor': datos,
    })


@admin_required
@require_POST
def editor_historico_previa(request, aspirante_id):
    persona = get_object_or_404(Aspirante, pk=aspirante_id)
    try:
        _, cambios = _leer_peticion(request)
        original, propuesto, errores, res = eh.preparar(persona, cambios)
    except eh.ErrorDeBorrador as error:
        return JsonResponse({'ok': False, 'errores': [str(error)]})
    from cierres.correcciones import meses_por_evento
    return JsonResponse({
        'ok': not errores,
        'errores': errores,
        'eventos': _eventos_json(propuesto, meses_por_evento(original)),
        'resumen': _resumen_json(res),
        'version_actual': original.version,
    })


@admin_required
@require_POST
def editor_historico_guardar(request, aspirante_id):
    persona = get_object_or_404(Aspirante, pk=aspirante_id)
    try:
        datos, cambios = _leer_peticion(request)
        res = eh.guardar(persona, cambios, datos.get('motivo'), version=datos.get('version'),
                         usuario=request.user)
    except eh.ErrorDeBorrador as error:
        return JsonResponse({'ok': False, 'errores': [str(error)]})
    except Exception:
        logger.exception('Fallo al guardar el editor del histórico de la persona %s', aspirante_id)
        return JsonResponse({'ok': False, 'errores': [
            'No se pudo guardar por un error inesperado. No se ha cambiado nada; '
            'el error quedó registrado para el desarrollador.']}, status=500)
    return JsonResponse({'ok': True, 'resumen': _resumen_json(res)})


@admin_required
@require_GET
def editor_historico_calcular(request, aspirante_id):
    """«Usar escala actual» (salario de hoy para ese cargo, tipo de salario y
    tridente) y «Recalcular a hoy» (los Otros que el contrato vigente tiene hoy)."""
    from strorganizativa.models import CargoPlantilla

    from .models import CAlta, salario_de_escala_para

    texto_cargo = request.GET.get('cargo') or ''
    cargo = (CargoPlantilla.objects.select_related('ncargo').filter(pk=texto_cargo).first()
             if texto_cargo.isdigit() else None)
    tridente = request.GET.get('tridente') or ''
    salario = salario_de_escala_para(cargo, request.GET.get('tipo_salario'),
                                     int(tridente) if tridente.isdigit() else None)
    contrato = CAlta.objects.filter(aspirante_id=aspirante_id).first()
    otros = contrato.importe_otros if contrato is not None else None
    return JsonResponse({
        'salario': '%.2f' % salario if salario is not None else None,
        'otros': '%.2f' % otros if otros is not None else None,
    })
