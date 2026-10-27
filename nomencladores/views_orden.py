"""Orden por arrastre de los nomencladores (3.8.2, decisión del 27-10-2026).

El Administrador arrastra las filas de una tarjeta y, al soltar, la pantalla manda
aquí la lista completa de ids en su nuevo orden. Ese orden (`Ordenable.orden`) es
el de TODO Orbith porque cada modelo lo declara en su `Meta.ordering`.

Un solo evento de Auditoría por arrastre, con la lista antes y después: fila a fila
serían decenas de eventos para un único gesto.
"""
import json

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar

#: slug de la tarjeta → (modelo, filtro fijo de la lista, campo que delimita la lista)
ORDENABLES = {
    'rol': ('nomencladores.NRol', {}, None),
    'tipo-unidad': ('nomencladores.NTipoUnidadOrganizativa', {}, None),
    'tipo-familia': ('nomencladores.NTipoFamilia', {}, None),
    'familia': ('nomencladores.NFamiliaCargo', {}, 'tipo_familia_id'),
    'nocturnidad': ('nomencladores.NNocturnidad', {}, None),
    'condicion': ('nomencladores.NCondicionLaboralAnormal', {}, None),
    'provincia': ('nomencladores.NProvincia', {}, None),
    'municipio': ('nomencladores.NMunicipio', {}, 'provincia_id'),
    'causa': ('nomencladores.NCausaAltaBaja', {}, None),
    'especialidad': ('nomencladores.NEspecialidad', {}, None),
    'nivel-preparacion': ('nomencladores.NNivelPreparacion', {}, None),
    'tipo-contrato': ('nomencladores.NTipoContrato', {}, None),
    'motivo-contrato': ('nomencladores.NMotivoContrato', {}, None),
    'instructor': ('nomencladores.NPagoAdicional', {'tipo': 'INS'}, None),
    'cnci': ('nomencladores.NPagoAdicional', {'tipo': 'CNC'}, None),
    'pagos-horas': ('prenomina.NPagoHoras', {}, None),
    'pagos-importe': ('prenomina.NPagoImporte', {}, None),
    'claves-ausencia': ('prenomina.NClaveAusencia', {}, None),
}


@require_POST
def guardar_orden(request, slug):
    if slug not in ORDENABLES:
        raise Http404('Esta lista no se puede ordenar.')
    etiqueta, filtro, ambito = ORDENABLES[slug]
    Modelo = apps.get_model(etiqueta)

    try:
        ids = [int(i) for i in json.loads(request.body).get('ids', [])]
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'La lista recibida no es válida.'}, status=400)
    if not ids or len(ids) != len(set(ids)):
        return JsonResponse({'success': False, 'error': 'La lista recibida no es válida.'}, status=400)

    registros = {r.pk: r for r in Modelo.objects.filter(pk__in=ids, **filtro)}
    if len(registros) != len(ids):
        return JsonResponse({'success': False, 'error': (
            'La lista cambió mientras la ordenaba (alguien añadió o quitó un elemento). '
            'Recargue la página y vuelva a intentarlo.')}, status=409)
    lista = Modelo.objects.filter(**filtro)
    if ambito:
        valores = {getattr(r, ambito) for r in registros.values()}
        if len(valores) > 1:
            return JsonResponse({'success': False, 'error': 'Solo se ordena dentro de una misma lista.'}, status=400)
        lista = lista.filter(**{ambito: valores.pop()})
    # La lista tiene que venir COMPLETA: si faltara alguno, conservaría su número
    # viejo y chocaría con los nuevos.
    if lista.count() != len(ids):
        return JsonResponse({'success': False, 'error': (
            'La lista cambió mientras la ordenaba (alguien añadió o quitó un elemento). '
            'Recargue la página y vuelva a intentarlo.')}, status=409)

    antes = [str(r) for r in sorted(registros.values(), key=lambda r: (r.orden, r.pk))]
    with transaction.atomic():
        for posicion, pk in enumerate(ids, start=1):
            registros[pk].orden = posicion
        Modelo.objects.bulk_update(list(registros.values()), ['orden'])
    despues = [str(registros[pk]) for pk in ids]

    if antes != despues:
        registrar(
            usuario=request.user, accion=AccionAuditoria.MODIFICAR,
            content_type=ContentType.objects.get_for_model(Modelo), object_id='',
            descriptor=f'Orden de {Modelo._meta.verbose_name_plural}',
            datos_antes={'orden': antes}, datos_despues={'orden': despues},
            modulo='nomencladores')
    return JsonResponse({'success': True})
