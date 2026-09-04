"""Proveedor de datos de los informes: en tiempo real o desde un cierre mensual.

Las seis vistas de `informes/views.py` calculaban cada una su propio queryset y
recorrían los modelos directamente. Eso hacía imposible servirlas desde una
fotografía histórica sin duplicar los seis cálculos.

Aquí se interpone una capa muy fina: dos funciones que devuelven **las mismas
estructuras planas** vengan de donde vengan los datos. Las vistas dejan de saber
si están mirando la base de datos viva o el cierre de agosto.

Tres cosas que conviene entender antes de tocar esto:

* **Las filas son planas y ya traen los datos de nomenclador resueltos**
  (`cat_ocupacional`, `puesto_clave`, `ocupa_plaza`...). En modo histórico esos
  valores salen congelados de la fotografía; en modo actual se leen de los
  nomencladores vivos. Ese es justamente el punto: en agosto de verdad, no en el
  agosto que resultaría de aplicar los nomencladores de hoy.
* **No se filtra aquí por estado ni por tipo de contrato.** Los seis informes no
  coinciden entre sí (el Consolidado cuenta todos los contratos, Puestos Clave
  solo los de aspirantes ACTIVO, Motivos además exige `requiere_motivo`). La
  fuente entrega todo y cada informe filtra la lista como ya hacía.
* **`unidades_sin_cierre` no es decorativo.** En modo histórico el informe suma
  solo las unidades que cerraron ese mes; las que falten se avisan en pantalla.
  Mezclar fotografía y datos vivos daría un total que no cuadra con ninguna
  realidad.
"""

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Count, Q
from django.utils import timezone

from cierres import servicios as servicios_cierres
from cierres.models import CierreCargo, CierreContrato, CierreUnidad
from cierres.periodos import Periodo, desde_clave
from contratos.models import CAlta
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa

COLOR_POR_DEFECTO = '#697a8d'

FUENTE_ACTUAL = 'actual'
FUENTE_CIERRE = 'cierre'


# --------------------------------------------------------------------------
# Estructuras planas
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FilaUnidad:
    id: int
    descripcion: str
    orden: int
    es_principal: bool
    es_subunidad: bool
    padre_id: int
    color: str = COLOR_POR_DEFECTO


@dataclass(frozen=True)
class FilaCargo:
    unidad_id: int
    departamento_id: int
    departamento_descripcion: str
    departamento_orden: int
    ncargo_id: int
    ncargo_descripcion: str
    cat_ocupacional: str
    puesto_clave: bool
    grupo_escala_nivel: str
    familias_ids: tuple
    cant_aprobada: int
    cant_cubierta: int
    funcionario: bool
    designado: bool

    @property
    def activo(self):
        """`CargoPlantilla.save()` fuerza `activo = cant_aprobada > 0`, así que la
        condición es equivalente y no hace falta congelar la columna."""
        return self.cant_aprobada > 0

    @property
    def vacantes(self):
        return max(self.cant_aprobada - self.cant_cubierta, 0)


@dataclass(frozen=True)
class FilaContrato:
    unidad_id: int
    # `CargoPlantilla.ncargo` es obligatorio (RESTRICT, no nulo), así que
    # `ncargo_id is None` equivale exactamente a «el contrato no tiene cargo».
    # Es la comprobación que hacen hoy las vistas con `if not c.cargo`.
    no_expediente: str
    aspirante_nombre: str
    doc_identidad: str
    sexo: str
    aspirante_estado: str
    departamento_descripcion: str
    ncargo_id: int
    ncargo_descripcion: str
    cat_ocupacional: str
    puesto_clave: bool
    grupo_escala_nivel: str
    # Puestos Clave solo cuenta contratos cuyo cargo está activo (su consulta parte
    # de `CargoPlantilla.objects.filter(activo=True)`). Sin este dato habría que
    # volver a cruzar contra los cargos por cada fila.
    cargo_activo: bool
    tipo_descripcion: str
    ocupa_plaza: bool
    requiere_motivo: bool
    motivo_descripcion: str
    mision: bool
    pais: str
    fecha_alta: date
    duracion: int
    salario: object
    dias_restantes: int

    @property
    def es_mujer(self):
        return self.sexo == 'F'

    @property
    def fecha_vencimiento(self):
        """Réplica de `CAlta.fecha_vencimiento`, que la plantilla de Motivos usa."""
        if not self.fecha_alta or self.duracion is None:
            return None
        from datetime import timedelta
        return self.fecha_alta + timedelta(days=self.duracion)


@dataclass
class FuenteDatos:
    """Lo que una vista de informe necesita, sin saber de dónde salió."""

    es_historica: bool = False
    periodo: Periodo = None
    cargos: list = field(default_factory=list)
    contratos: list = field(default_factory=list)
    unidades: dict = field(default_factory=dict)
    unidades_sin_cierre: list = field(default_factory=list)

    def unidad(self, unidad_id):
        return self.unidades.get(unidad_id)

    def nombre_unidad(self, unidad_id, defecto='Sin Unidad'):
        fila = self.unidades.get(unidad_id)
        return fila.descripcion if fila else defecto

    @property
    def etiqueta(self):
        return self.periodo.etiqueta if self.periodo else 'Información actual'


# --------------------------------------------------------------------------
# Jerarquía
# --------------------------------------------------------------------------

def expandir_unidades(ueb_id, unidades=None):
    """Una unidad y, si es principal, sus subunidades.

    Esta cascada estaba copiada literalmente en cuatro vistas
    (`informes/views.py`). Aquí vive una sola vez.

    Devuelve `[]` cuando no hay filtro, que es lo que las vistas interpretan
    como «toda la empresa».
    """
    if not ueb_id:
        return []

    if unidades is not None:
        # Modo histórico. Las HIJAS declaran y congelan su propio padre en
        # `unidad_padre_id_original` (`u.padre_id` aquí): esa parte de la
        # jerarquía es fiel a como estaba en el momento de declarar, no a la
        # de hoy, y no se toca.
        #
        # El PADRE es otra historia: desde que las Direcciones Principales no
        # declaran (no tienen cargos propios), nunca tienen su propia fila en
        # `unidades` — por eso `unidades.get(clave)` daba `None` y esta
        # función devolvía `[]`, dejando un informe filtrado por el padre sin
        # ningún dato aunque sus hijas sí hubieran declarado. Para el padre no
        # hay nada que congelar (nunca se fotografía), así que su tipo se
        # resuelve contra la estructura viva — es la única fuente que existe.
        try:
            clave = int(ueb_id)
        except (TypeError, ValueError):
            return []

        fila = unidades.get(clave)
        if fila is not None:
            es_principal = fila.es_principal
        else:
            es_principal = (UnidadOrganizativa.objects
                            .filter(pk=clave, tipo__es_principal=True)
                            .exists())
            if not es_principal:
                # Ni tiene cierre propio ni es un padre reconocible: no hay
                # nada que mostrar para esta unidad en este período.
                return []

        ids = [clave]
        if es_principal:
            ids += [u.id for u in unidades.values() if u.padre_id == clave]
        return ids

    seleccionada = (UnidadOrganizativa.objects
                    .select_related('tipo')
                    .filter(pk=ueb_id)
                    .first())
    if seleccionada is None:
        return []
    ids = [seleccionada.pk]
    if seleccionada.tipo and seleccionada.tipo.es_principal:
        ids += list(UnidadOrganizativa.objects
                    .filter(padre=seleccionada)
                    .values_list('pk', flat=True))
    return ids


def expandir_varias_unidades(ueb_ids, unidades=None):
    """La cascada de varias unidades a la vez, sin repetidos.

    El filtro de los informes pasó de un desplegable de una sola unidad a un
    selector múltiple, así que hay que unir la cascada de cada una. Se conserva
    `expandir_unidades()` para un solo id porque Pre-Nómina la usa tal cual
    (`prenomina/captura.py`).

    Devuelve `[]` si no se pidió ninguna unidad.
    """
    ids = []
    for ueb_id in ueb_ids or []:
        for pk in expandir_unidades(ueb_id, unidades):
            if pk not in ids:
                ids.append(pk)
    return ids


def unidades_visibles(usuario):
    """Unidades que este usuario puede ver en los informes, o `None` si todas.

    Mismo reparto de roles que Informe Inteligente
    (`informe_inteligente.motor._aplicar_alcance_por_rol`): Administrador y
    Observador ven la empresa entera; el Moderador, solo lo suyo. Se replica aquí
    porque hasta ahora los informes de RRHH **no acotaban nada**: un Moderador de
    una sola UEB abría el consolidado y veía la plantilla de toda la empresa.

    Con UNA diferencia deliberada: aquí las unidades asignadas se expanden a sus
    subunidades. Informe Inteligente no lo hace, y por eso un Moderador que tenga
    asignada una unidad PRINCIPAL —una Dirección, que no tiene cargos propios—
    no vería ni una fila: todo cuelga de sus hijas. Además, en este módulo elegir
    una unidad principal en el filtro SIEMPRE ha arrastrado a sus subunidades
    (`expandir_unidades`), así que no expandir aquí el alcance dejaría al
    Moderador viendo menos con su unidad asignada que eligiéndola a mano.

    `None` significa «sin restricción» y NO es lo mismo que `[]`. Una lista
    vacía es un Moderador sin ninguna unidad asignada, que no debe ver ni una
    fila —la regla VIS-007 de Subsanación ya reclama esa situación—; devolver
    `[]` como «sin filtro» le enseñaría justo lo contrario, la empresa entera.
    """
    if usuario.is_superuser or usuario.es_admin or usuario.es_observador:
        return None
    if usuario.es_moderador:
        return expandir_varias_unidades(
            usuario.unidades.values_list('pk', flat=True))
    # Usuario sin rol reconocido: por seguridad, no ve nada.
    return []


def acotar_al_alcance(elegidas, permitidas):
    """Cruza lo que el usuario PIDIÓ con lo que tiene PERMITIDO ver.

    Es pública porque el informe de Altas y Bajas no pasa por `resolver_fuente`
    —consulta movimientos entre fechas, no una fotografía— y necesita aplicar
    exactamente este mismo cruce. Duplicarlo allí sería tener dos versiones de
    una regla de permisos, que es la manera clásica de que una de las dos se
    quede atrás.

    Que el alcance se aplique aquí, en el servidor, y no limitando el desplegable
    de la plantilla, es lo que impide que un Moderador amplíe su visibilidad
    escribiendo a mano `?ueb=` de otra unidad en la barra de direcciones.

    Devuelve `None` cuando no hay nada que acotar, que es lo que las fuentes
    entienden como «toda la empresa».
    """
    if permitidas is None:
        # Administrador u Observador: manda su elección, o todo si no eligió.
        return elegidas or None
    if not elegidas:
        # Sin elección explícita, el filtro es su alcance completo.
        return permitidas
    return [pk for pk in elegidas if pk in permitidas]


def _unidades_vivas():
    filas = {}
    for unidad in UnidadOrganizativa.objects.select_related('tipo'):
        tipo = unidad.tipo
        filas[unidad.pk] = FilaUnidad(
            id=unidad.pk,
            descripcion=unidad.descripcion,
            orden=unidad.orden_informe or 999,
            es_principal=bool(tipo.es_principal) if tipo else False,
            es_subunidad=bool(tipo.es_subunidad) if tipo else False,
            padre_id=unidad.padre_id,
            color=(tipo.color if tipo and tipo.color else COLOR_POR_DEFECTO),
        )
    return filas


# --------------------------------------------------------------------------
# Fuente en tiempo real
# --------------------------------------------------------------------------

def fuente_actual(unidades_ids=None):
    """Los datos vivos, con el mismo `select_related` que ya usaban las vistas."""
    # `count_cubiertas` es la anotación que reconoce la property
    # `CargoPlantilla.cant_cubierta_real`, que si no lanza un COUNT (con dos joins)
    # POR CADA CARGO dentro del bucle de abajo.
    # Con la plantilla real de la empresa eso eran cientos de consultas por informe:
    # es lo que hacía que «Informes RRHH» tardara segundos en producción y nada en
    # local, donde la plantilla de prueba es diminuta. Anotado aquí, el mismo cálculo
    # se resuelve en la ÚNICA consulta que ya se hacía.
    #
    # Los filtros son exactamente los de la property (contrato de aspirante ACTIVO
    # cuyo tipo ocupa plaza oficial). No hace falta `distinct=True`: todo lo que se
    # cruza son claves foráneas 1:1, así que ninguna fila se duplica.
    cargos_qs = (CargoPlantilla.objects
                 .select_related('departamento', 'ncargo', 'ncargo__grupo_escala')
                 .prefetch_related('ncargo__familias')
                 .annotate(count_cubiertas=Count(
                     'calta',
                     filter=Q(calta__aspirante__estado='ACTIVO',
                              calta__tipo__ocupa_plaza=True),
                 )))
    contratos_qs = (CAlta.objects
                    .select_related('aspirante', 'cargo', 'cargo__departamento',
                                    'cargo__ncargo', 'cargo__ncargo__grupo_escala',
                                    'tipo', 'motivo'))
    # `is not None` y no la comprobación de verdad a secas: desde que el alcance
    # por rol acota los informes, una lista VACÍA es un caso real y significativo
    # —un Moderador sin unidades asignadas— que no debe ver ninguna fila. Con
    # `if unidades_ids:` esa lista caía en «sin filtro» y le enseñaba la empresa
    # entera. `__in=[]` no devuelve nada, que es justo lo correcto.
    if unidades_ids is not None:
        cargos_qs = cargos_qs.filter(
            departamento__unidad_organizativa_id__in=unidades_ids)
        contratos_qs = contratos_qs.filter(
            cargo__departamento__unidad_organizativa_id__in=unidades_ids)

    cargos = []
    for cargo in cargos_qs:
        ncargo = cargo.ncargo
        grupo = ncargo.grupo_escala if ncargo else None
        cargos.append(FilaCargo(
            unidad_id=cargo.departamento.unidad_organizativa_id if cargo.departamento else None,
            departamento_id=cargo.departamento_id,
            departamento_descripcion=cargo.departamento.descripcion if cargo.departamento else '',
            departamento_orden=cargo.departamento.orden_informe if cargo.departamento else None,
            ncargo_id=cargo.ncargo_id,
            ncargo_descripcion=ncargo.descripcion if ncargo else '',
            cat_ocupacional=ncargo.cat_ocupacional if ncargo else '',
            puesto_clave=bool(ncargo.puesto_clave) if ncargo else False,
            grupo_escala_nivel=grupo.nivel if grupo else '',
            # `.all()` y no `.values_list()`: values_list NO usa la caché que deja
            # `prefetch_related('ncargo__familias')` y volvía a consultar la base de
            # datos una vez por cargo, desperdiciando el prefetch que ya se pedía
            # tres líneas más arriba.
            familias_ids=tuple(f.id for f in ncargo.familias.all()) if ncargo else (),
            cant_aprobada=cargo.cant_aprobada or 0,
            # La property, no la columna `cant_cubierta` (que puede estar
            # desfasada). Gracias al `annotate(count_cubiertas=...)` de arriba, la
            # property la lee de ahí y no lanza ninguna consulta.
            cant_cubierta=cargo.cant_cubierta_real,
            funcionario=bool(cargo.funcionario),
            designado=bool(cargo.designado),
        ))

    hoy = timezone.localdate()
    contratos = []
    for contrato in contratos_qs:
        cargo = contrato.cargo
        ncargo = cargo.ncargo if cargo else None
        grupo = ncargo.grupo_escala if ncargo else None
        aspirante = contrato.aspirante
        tipo = contrato.tipo
        contratos.append(FilaContrato(
            unidad_id=(cargo.departamento.unidad_organizativa_id
                       if cargo and cargo.departamento else None),
            no_expediente=contrato.no_expediente or '',
            aspirante_nombre=_nombre(aspirante),
            doc_identidad=aspirante.doc_identidad if aspirante else '',
            sexo=aspirante.sexo if aspirante else '',
            aspirante_estado=aspirante.estado if aspirante else '',
            departamento_descripcion=(cargo.departamento.descripcion
                                      if cargo and cargo.departamento else ''),
            ncargo_id=cargo.ncargo_id if cargo else None,
            ncargo_descripcion=ncargo.descripcion if ncargo else '',
            cat_ocupacional=ncargo.cat_ocupacional if ncargo else '',
            puesto_clave=bool(ncargo.puesto_clave) if ncargo else False,
            grupo_escala_nivel=grupo.nivel if grupo else '',
            cargo_activo=bool(cargo and (cargo.cant_aprobada or 0) > 0),
            tipo_descripcion=tipo.descripcion if tipo else '',
            ocupa_plaza=bool(tipo.ocupa_plaza) if tipo else False,
            requiere_motivo=bool(tipo.requiere_motivo) if tipo else False,
            motivo_descripcion=contrato.motivo.descripcion if contrato.motivo else '',
            mision=bool(contrato.mision),
            pais=contrato.pais or '',
            fecha_alta=contrato.fecha_alta,
            duracion=contrato.duracion,
            salario=contrato.salario_actual,
            dias_restantes=_dias_restantes(contrato.fecha_alta, contrato.duracion, hoy),
        ))

    return FuenteDatos(
        es_historica=False,
        periodo=None,
        cargos=_ordenar_cargos(cargos),
        contratos=_ordenar_contratos(contratos),
        unidades=_unidades_vivas(),
    )


# --------------------------------------------------------------------------
# Fuente histórica
# --------------------------------------------------------------------------

def fuente_de_cierre(periodo, unidades_ids=None):
    """Los datos congelados de un cierre mensual.

    El color de cada unidad se resuelve contra los datos vivos a propósito: es
    puramente estético y no forma parte del hecho económico. Todo lo demás sale
    de la fotografía.
    """
    cierres = (CierreUnidad.objects
               .filter(anno=periodo.anno, mes=periodo.mes)
               .order_by('unidad_orden_informe'))
    # `is not None`: ver la nota de `fuente_actual()`. Una lista vacía es un
    # alcance vacío de verdad, no la ausencia de filtro.
    if unidades_ids is not None:
        cierres = cierres.filter(unidad_id__in=unidades_ids)
    cierres = list(cierres)

    colores = dict(
        UnidadOrganizativa.objects
        .select_related('tipo')
        .values_list('pk', 'tipo__color'))

    unidades = {}
    for cierre in cierres:
        unidades[cierre.unidad_id] = FilaUnidad(
            id=cierre.unidad_id,
            descripcion=cierre.unidad_descripcion,
            orden=cierre.unidad_orden_informe or 999,
            es_principal=cierre.unidad_es_principal,
            es_subunidad=cierre.unidad_es_subunidad,
            padre_id=cierre.unidad_padre_id_original,
            color=colores.get(cierre.unidad_id) or COLOR_POR_DEFECTO,
        )

    ids = [c.pk for c in cierres]
    unidad_de_cierre = {c.pk: c.unidad_id for c in cierres}
    # La referencia temporal de cada cierre es su propia fecha de declaración: es
    # la única forma de que «días restantes» signifique algo en un histórico.
    fecha_de_cierre = {
        c.pk: (c.fecha_declaracion.date() if c.fecha_declaracion else None)
        for c in cierres
    }

    cargos = [
        FilaCargo(
            unidad_id=unidad_de_cierre[fila.cierre_id],
            departamento_id=fila.departamento_id_original,
            departamento_descripcion=fila.departamento_descripcion,
            departamento_orden=fila.departamento_orden,
            ncargo_id=fila.ncargo_id_original,
            ncargo_descripcion=fila.ncargo_descripcion,
            cat_ocupacional=fila.cat_ocupacional,
            puesto_clave=fila.puesto_clave,
            grupo_escala_nivel=fila.grupo_escala_nivel,
            familias_ids=tuple(fila.familias_ids or ()),
            cant_aprobada=fila.cant_aprobada,
            cant_cubierta=fila.cant_cubierta,
            funcionario=fila.funcionario,
            designado=fila.designado,
        )
        for fila in CierreCargo.objects.filter(cierre_id__in=ids)
    ]

    aprobadas_por_cargo = dict(
        CierreCargo.objects.filter(cierre_id__in=ids).values_list('pk', 'cant_aprobada'))

    contratos = [
        FilaContrato(
            unidad_id=unidad_de_cierre[fila.cierre_id],
            no_expediente=fila.no_expediente,
            aspirante_nombre=fila.aspirante_nombre,
            doc_identidad=fila.doc_identidad,
            sexo=fila.sexo,
            aspirante_estado=fila.aspirante_estado,
            departamento_descripcion=fila.departamento_descripcion,
            ncargo_id=fila.ncargo_id_original,
            ncargo_descripcion=fila.ncargo_descripcion,
            cat_ocupacional=fila.cat_ocupacional,
            puesto_clave=fila.puesto_clave,
            grupo_escala_nivel=fila.grupo_escala_nivel,
            cargo_activo=aprobadas_por_cargo.get(fila.cierre_cargo_id, 0) > 0,
            tipo_descripcion=fila.tipo_descripcion,
            ocupa_plaza=fila.ocupa_plaza,
            requiere_motivo=fila.requiere_motivo,
            motivo_descripcion=fila.motivo_descripcion,
            mision=fila.mision,
            pais=fila.pais,
            fecha_alta=fila.fecha_alta,
            duracion=fila.duracion,
            salario=fila.salario,
            dias_restantes=_dias_restantes(
                fila.fecha_alta, fila.duracion, fecha_de_cierre.get(fila.cierre_id)),
        )
        for fila in CierreContrato.objects.filter(cierre_id__in=ids)
    ]

    return FuenteDatos(
        es_historica=True,
        periodo=periodo,
        cargos=_ordenar_cargos(cargos),
        contratos=_ordenar_contratos(contratos),
        unidades=unidades,
        unidades_sin_cierre=servicios_cierres.unidades_sin_cierre(periodo, unidades_ids),
    )


# --------------------------------------------------------------------------
# Punto de entrada de las vistas
# --------------------------------------------------------------------------

def resolver_fuente(request):
    """Lee `fuente`, `periodo` y `ueb` de la URL y devuelve `(fuente, contexto)`.

    Ante cualquier valor inválido cae en modo actual: un informe que se abre con
    los datos de hoy es un mal menor frente a una pantalla de error.

    El parámetro `ueb` es ahora **múltiple** (`?ueb=3&ueb=7`), porque el filtro
    de unidad pasó a ser un selector de varias. Desapareció el antiguo
    `usar_filtro_ueb=False`, que apagaba el filtro en Trabajadores x UEB y en
    Misiones: con selección múltiple esos dos informes siguen teniendo sentido
    acotados —«compara estas tres unidades», «quién de mi UEB está en misión»— y
    sin nada elegido se comportan exactamente igual que antes.

    Sobre todo, el filtro ya no es solo del usuario: se cruza con su alcance por
    rol (`unidades_visibles`), así que un Moderador no puede ver otras unidades
    ni escribiendo el `?ueb=` a mano.
    """
    modo = request.GET.get('fuente') or FUENTE_ACTUAL
    clave = request.GET.get('periodo') or ''
    # Solo ids: la querystring la escribe cualquiera —y hasta la propia
    # aplicacion la escribia mal, con `?ueb=[]`, en los botones de exportar de
    # Puestos Clave— y un valor que no sea un numero reventaba la pagina entera
    # con un ValueError. Se ignora y se muestra el alcance completo.
    seleccionadas = [valor for valor in request.GET.getlist('ueb')
                     if valor and str(valor).isdigit()]
    permitidas = unidades_visibles(request.user)

    periodo = desde_clave(clave) if modo == FUENTE_CIERRE else None
    disponibles = servicios_cierres.periodos_disponibles()

    if periodo is not None and periodo not in disponibles:
        periodo = None

    if periodo is None:
        elegidas = expandir_varias_unidades(seleccionadas)
        unidades_ids = acotar_al_alcance(elegidas, permitidas)
        fuente = fuente_actual(unidades_ids)
        modo = FUENTE_ACTUAL
    else:
        # La cascada se calcula sobre la jerarquía congelada, así que hace falta
        # cargar antes las unidades de ese cierre.
        unidades_del_cierre = fuente_de_cierre(periodo).unidades
        elegidas = expandir_varias_unidades(seleccionadas, unidades_del_cierre)
        unidades_ids = acotar_al_alcance(elegidas, permitidas)
        fuente = fuente_de_cierre(periodo, unidades_ids)

    contexto = {
        'fuente_datos': fuente,
        'fuente_modo': modo,
        'fuente_periodo': periodo.clave if periodo else '',
        'fuente_etiqueta': fuente.etiqueta,
        'es_historico': fuente.es_historica,
        'periodos_disponibles': disponibles,
        'unidades_sin_cierre': fuente.unidades_sin_cierre,
        # Las que el usuario tiene marcadas, en texto, para que la plantilla del
        # filtro pueda comprobarlas con `{% if u.pk|stringformat:"s" in ueb_actual %}`.
        'ueb_actual': seleccionadas,
        # Las unidades que el informe REALMENTE abarca, ya cruzadas con el
        # alcance del rol; `None` significa la empresa entera. Lo necesita quien
        # agrupe por unidad: una cabecera de unidad principal solo puede sumar
        # sus subunidades si todas ellas entran en el informe.
        'unidades_alcance': unidades_ids,
        # Lo que necesita la rejilla de meses del selector de período: qué meses
        # tienen cierre, entre qué años se mueven las flechas, y cuál está puesto.
        # Se calcula aquí y no en la plantilla porque `Periodo` es un objeto y las
        # plantillas de Django no pueden desmontarlo en año y mes.
        'periodos_claves': [p.clave for p in disponibles],
        'periodos_annos': sorted({p.anno for p in disponibles}),
        'periodo_anno': periodo.anno if periodo else '',
        'periodo_mes': periodo.mes if periodo else '',
    }
    return fuente, contexto


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------

def _ordenar_cargos(filas):
    return sorted(filas, key=lambda c: (
        c.departamento_orden if c.departamento_orden is not None else 9999,
        (c.departamento_descripcion or '').lower(),
        (c.ncargo_descripcion or '').lower(),
    ))


def _ordenar_contratos(filas):
    """Orden estable de los contratos.

    Las consultas originales no llevaban `ORDER BY`, así que el orden de las
    listas que se pintan (Misiones, Motivos) lo decidía PostgreSQL y podía
    cambiar entre dos ejecuciones sobre los mismos datos. Un informe que se
    firma no puede salir en distinto orden cada vez que se imprime, y menos aún
    uno histórico, cuyo sentido es ser siempre idéntico.

    Los informes que necesitan otro orden lo aplican después (ver
    `InformeMotivosContratoView`).
    """
    return sorted(filas, key=lambda c: (
        (c.aspirante_nombre or '').lower(),
        c.no_expediente or '',
    ))


def _nombre(aspirante):
    if aspirante is None:
        return ''
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido or '']
    return ' '.join(p for p in partes if p).strip()


def _dias_restantes(fecha_alta, duracion, referencia):
    """Réplica de `CAlta.dias_restantes`, pero contra una fecha elegible.

    En tiempo real la referencia es hoy; en un histórico, el día en que se
    declaró el cierre. Preguntar «cuántos días le quedaban» a un contrato de
    agosto usando la fecha de hoy no significaría nada.
    """
    if not fecha_alta or duracion is None or referencia is None:
        return None
    from datetime import timedelta
    return ((fecha_alta + timedelta(days=duracion)) - referencia).days
