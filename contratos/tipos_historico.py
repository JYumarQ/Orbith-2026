"""Tipo de contrato y motivo que faltan en el histórico (25-10-2026).

Las Altas Iniciales hechas con el asistente antes de la versión 3.6.0 y los
movimientos antiguos no guardaban el tipo de contrato ni el motivo. Desde entonces
se guardan siempre; esto rellena los que faltan cuando se pueden SABER con certeza:

1. El evento siguiente del mismo contrato dice de qué venía (su «antes»).
2. El último evento de un contrato que terminó: lo que guarda su baja.
3. El último evento del contrato vigente: lo que dice el contrato.

El motivo solo se busca si el tipo lo pide (Determinado, Adiestrado…). Lo que no se
puede saber se deja vacío: lo completa un Administrador en el editor del histórico
(que no deja guardar sin ello) y lo avisa Subsanación (MOV-016).
"""

from dataclasses import dataclass

from django.db.models import Q

SIN_DATO = '---'

#: dato del estado del editor -> (columna «antes», columna «después») de TMovimiento
DATOS = {
    'tipo_contrato': ('tipo_contrato_anterior', 'tipo_contrato_nuevo'),
    'motivo': ('motivo_anterior', 'motivo_nuevo'),
}


def tipos_con_motivo():
    from nomencladores.models import NTipoContrato
    return list(NTipoContrato.objects.filter(requiere_motivo=True).values_list('descripcion', flat=True))


def _vacio_q(campo):
    return Q(**{campo + '__isnull': True}) | Q(**{campo + '__in': ['', SIN_DATO]})


def incompletos_q(prefijo=''):
    """Movimientos (no bajas) sin tipo de contrato, o sin motivo cuando su tipo lo pide."""
    sin_tipo = _vacio_q(prefijo + 'tipo_contrato_nuevo')
    sin_motivo = Q(**{prefijo + 'tipo_contrato_nuevo__in': tipos_con_motivo()}) & _vacio_q(prefijo + 'motivo_nuevo')
    return (sin_tipo | sin_motivo) & ~Q(**{prefijo + 'tipo_movimiento__icontains': 'baja'})


#: Nombre antiguo, por compatibilidad.
sin_tipo_q = incompletos_q


@dataclass
class Relleno:
    mov_pk: int
    campo: str          # columna de TMovimiento
    valor: str
    fuente: str
    evento: str         # «Movimiento de Nómina del 30/05/2026»


def _vacio(valor):
    return (valor or '').strip() in ('', SIN_DATO)


def rellenos_de(aspirante_id):
    """Lo que se puede rellenar con certeza en el histórico de una persona."""
    from .editor_historico import BAJA, cargar, ciclos
    from .models import CAlta, CBaja

    con_motivo = set(tipos_con_motivo())
    historico = cargar(aspirante_id)
    grupos = ciclos(historico)
    contrato = (CAlta.objects.filter(pk=historico.contrato_pk).select_related('tipo', 'motivo').first()
                if historico.contrato_pk else None)
    rellenos = []
    for n, grupo in enumerate(grupos):
        eventos = [e for e in grupo if e.tipo != BAJA]
        baja = grupo[-1] if grupo and grupo[-1].tipo == BAJA else None
        cbaja = (CBaja.objects.filter(pk=baja.baja_pk).select_related('tipo', 'motivo').first()
                 if baja is not None and baja.baja_pk else None)
        vigente = n == len(grupos) - 1 and baja is None and contrato is not None

        def de_origen(dato):
            """Lo que dice la baja o el contrato vigente del último evento del ciclo."""
            origen, fuente = (cbaja, 'la baja') if cbaja is not None else \
                (contrato, 'el contrato vigente') if vigente else (None, None)
            if origen is None:
                return None, None
            objeto = origen.tipo if dato == 'tipo_contrato' else origen.motivo
            return (objeto.descripcion if objeto is not None else None), \
                ('el tipo que guarda ' if dato == 'tipo_contrato' else 'el motivo que guarda ') + fuente

        for i, evento in enumerate(eventos):
            if evento.mov_pk is None:
                continue
            siguiente = eventos[i + 1] if i + 1 < len(eventos) else None
            tipo_final = evento.estado.get('tipo_contrato')
            for dato in ('tipo_contrato', 'motivo'):
                if not _vacio(evento.estado.get(dato)):
                    continue
                if dato == 'motivo' and (tipo_final or '').strip() not in con_motivo:
                    continue      # este tipo no lleva motivo
                valor = fuente = None
                if siguiente is not None:
                    if not _vacio(siguiente.antes.get(dato)):
                        valor = siguiente.antes[dato].strip()
                        fuente = 'el movimiento siguiente dice de qué venía'
                else:
                    valor, fuente = de_origen(dato)
                if not valor:
                    continue
                if dato == 'tipo_contrato':
                    tipo_final = valor
                rellenos.append(Relleno(evento.mov_pk, DATOS[dato][1], valor, fuente, evento.nombre))
                # El «antes» del siguiente es lo que deja este: si tampoco lo tenía, se completa.
                if siguiente is not None and siguiente.mov_pk and _vacio(siguiente.antes.get(dato)):
                    rellenos.append(Relleno(siguiente.mov_pk, DATOS[dato][0], valor, fuente, siguiente.nombre))
    return rellenos


def personas_incompletas():
    """Ids de las personas con algún Alta o Movimiento sin tipo de contrato o sin motivo."""
    from .models import TMovimiento

    filas = TMovimiento.objects.filter(incompletos_q()).values_list('aspirante_id', 'contrato__aspirante_id')
    return sorted({a or b for a, b in filas if (a or b)})


#: Nombre antiguo, por compatibilidad.
personas_sin_tipo = personas_incompletas
