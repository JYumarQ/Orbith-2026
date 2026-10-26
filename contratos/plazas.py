"""Plazas sobregiradas (25-10-2026).

Un cargo está SOBREGIRADO cuando tiene más contratos que ocupan plaza (tipo con
«Ocupa plaza», persona activa) que plazas aprobadas. Mientras siga así, ningún
contrato que ocupe plaza en él se guarda desde «Editar contrato»: hay que
resolverlo antes con un Movimiento de Nómina, corrigiendo el histórico de quien
ocupa la plaza por error o subiendo las plazas aprobadas del cargo.

El Movimiento de Nómina NO se bloquea: es una de las soluciones.
"""


def ocupantes(cargo, excluir=None):
    """Contratos que ocupan plaza en el cargo, del más antiguo al más reciente."""
    from .models import CAlta

    qs = (CAlta.objects.filter(cargo=cargo, aspirante__estado='ACTIVO', tipo__ocupa_plaza=True)
          .select_related('aspirante').order_by('fecha_alta', 'pk'))
    if excluir is not None:
        qs = qs.exclude(pk=excluir)
    return qs


def sobregiro_de(contrato):
    """`None` si el contrato no ocupa plaza o su cargo no está sobregirado; si lo
    está, lo necesario para explicarlo en pantalla."""
    if not (contrato and contrato.cargo_id and contrato.tipo_id and contrato.tipo.ocupa_plaza):
        return None
    cargo = contrato.cargo
    lista = list(ocupantes(cargo))
    if len(lista) <= cargo.cant_aprobada:
        return None
    return {
        'cargo': cargo,
        'aprobadas': cargo.cant_aprobada,
        'ocupadas': len(lista),
        'ocupantes': lista,
    }
