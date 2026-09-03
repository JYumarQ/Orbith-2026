"""Alcance y filtros del listado de reportes de pago.

`reportes_visibles()` es el **único punto** donde se decide qué ve cada usuario,
igual que `cierres/filtros.py::unidades_visibles()` o
`contratos/filtros.py::contratos_visibles()`. Si mañana cambia la regla de
alcance, se cambia aquí y en ningún otro sitio.

El alcance se aplica siempre **en el queryset**, nunca con un `if` en la vista.
La diferencia es de seguridad, no de estilo: con `get_object_or_404(reportes_visibles(...))`
un Moderador que fuerce la URL de otra unidad recibe un 404 y no llega a saber
que ese reporte existe.
"""

from cierres.constantes import MESES
from strorganizativa.models import UnidadOrganizativa

from .models import EstadoReporte, ReportePago
from .permisos import es_administrador, es_moderador

ESTADOS_VALIDOS = {estado.value for estado in EstadoReporte}


def reportes_visibles(usuario):
    """Reportes que el usuario puede consultar.

    El Observador no tiene acceso al módulo (`permisos.tiene_acceso`): cae
    directo en `base.none()`. No hace falta comprobarlo aquí aparte porque las
    vistas de lectura ya están cerradas con `@acceso_prenomina` antes de llegar
    a este queryset; se mantiene igualmente en el queryset por si algún día se
    consulta desde fuera de esas vistas.
    """
    base = ReportePago.objects.select_related('unidad__tipo', 'cerrado_por')
    if es_administrador(usuario):
        return base
    if es_moderador(usuario):
        return base.filter(unidad__in=usuario.unidades.values_list('pk', flat=True))
    return base.none()


def unidades_gestionables(usuario):
    """Unidades en las que el usuario puede CREAR un reporte.

    Es más estrecho que `reportes_visibles`: el Observador queda fuera.

    **Sí se ofrecen las unidades principales**, a diferencia de Cierres. Allí no
    tiene sentido declararlas porque no tienen cargos propios; aquí el reporte
    expande a las subunidades (`captura.unidades_del_reporte`), así que el de una
    Dirección Principal recoge la nómina de toda su rama. Lo que impide el doble
    pago no es esconder el padre, sino `servicios._exigir_sin_solape()`.
    """
    base = (UnidadOrganizativa.objects
            .select_related('tipo')
            .order_by('orden_informe', 'descripcion'))
    if es_administrador(usuario):
        return base
    if es_moderador(usuario):
        return base.filter(pk__in=usuario.unidades.values_list('pk', flat=True))
    return base.none()


def filtrar_reportes(request):
    """Devuelve `(queryset, contexto)`, mismo contrato que el resto del proyecto.

    `q` dejó de ser texto libre: ahora es el `pk` de la Unidad Organizativa
    elegida en el `&lt;select&gt;` con autocompletado (mismo patrón Select2 que
    `contrato/add_contrato.html`), y el desplegable solo ofrece las unidades que
    el usuario tiene asignadas (`unidades_gestionables`) — no tiene sentido
    dejarlo buscar por una unidad que ni siquiera puede gestionar.
    """
    reportes = reportes_visibles(request.user)

    q = (request.GET.get('q') or '').strip()
    if q.isdigit():
        reportes = reportes.filter(unidad_id=int(q))

    estado = (request.GET.get('estado') or '').strip()
    if estado in ESTADOS_VALIDOS:
        reportes = reportes.filter(estado=estado)

    anno = (request.GET.get('anno') or '').strip()
    if anno.isdigit():
        reportes = reportes.filter(anno=int(anno))

    # El mes solo acota junto al año: filtrar «septiembre» de todos los años a la
    # vez mezclaría períodos de nóminas distintas y no responde a ninguna
    # pregunta real.
    mes = (request.GET.get('mes') or '').strip()
    if mes.isdigit() and 1 <= int(mes) <= 12 and anno.isdigit():
        reportes = reportes.filter(mes=int(mes))

    contexto = {
        'q': q,
        'unidades': unidades_gestionables(request.user),
        'estado_actual': estado,
        'anno_actual': anno,
        'mes_actual': mes,
        'opciones_estado': list(EstadoReporte.choices),
        'meses': list(enumerate(MESES, start=1)),
        # Los años que realmente existen, para no ofrecer un desplegable con
        # décadas vacías.
        'annos_disponibles': list(
            reportes_visibles(request.user)
            .values_list('anno', flat=True).order_by('-anno').distinct()),
        # Los meses que tienen algún reporte, para que la rejilla del selector de
        # período los resalte y no haga buscar a ciegas.
        'periodos_existentes': [
            f'{a}-{m:02d}' for a, m in reportes_visibles(request.user)
            .values_list('anno', 'mes').order_by('-anno', '-mes').distinct()],
        'hay_filtros': bool(q or estado or anno or mes),
    }
    contexto.update(estado_del_periodo(request.user, anno, mes))
    return reportes, contexto


def estado_del_periodo(usuario, anno, mes):
    """Qué se puede hacer con el período elegido, para la barra de la pantalla.

    Une las dos mitades del módulo: dice si el Calendario de Pago de ese año+mes
    está cerrado y cuántos reportes siguen en Borrador, que es lo que decide si
    tiene sentido ofrecer «Cerrar mes».

    Devuelve un diccionario vacío de claves útiles cuando no hay un período
    concreto seleccionado: sin año y mes no hay mes que cerrar.
    """
    from .models import CalendarioPago

    if not (anno.isdigit() and mes.isdigit() and 1 <= int(mes) <= 12):
        return {'periodo_calendario': None, 'borradores_del_periodo': 0,
                'hay_periodo': False}

    anno, mes = int(anno), int(mes)
    return {
        'periodo_calendario': CalendarioPago.objects.filter(
            usuario=usuario, anno=anno, mes=mes).first(),
        'borradores_del_periodo': (
            reportes_visibles(usuario)
            .filter(anno=anno, mes=mes, estado=EstadoReporte.BORRADOR).count()),
        'hay_periodo': True,
    }
