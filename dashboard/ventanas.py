"""Ventanas de la Dashboard (decisión de RRHH del 24-10-2026).

Toda interacción con la Dashboard abre primero una VENTANA con lo que hay detrás
de la cifra pulsada. Desde ella:

* «Ver más» lleva a la lista (Contratos, Bajas, Gestor de Plantilla) con los
  mismos filtros, cuando esa lista existe y puede mostrar lo mismo;
* «Excel» descarga exactamente lo que se ve: las unidades elegidas en «Filtros
  Organizativos», el filtro de la ventana y lo buscado, con portada y logo.

Cada ventana se describe UNA vez aquí (`VENTANAS`): la pantalla y el Excel salen
de la misma descripción, así nunca dicen cosas distintas. Las cinco ventanas que
ya existían (pirámide, mes, años de servicio, salario y plazas) conservan su
pantalla propia; aquí solo se describen sus datos para el Excel y su pie.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from contratos.models import CAlta, CBaja
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa

from .filtros import _filtrar_por_uo, resolver_filtros, unidades_visibles

#: Filas por página en las listas largas (decisión del 24-10-2026). El Excel
#: saca SIEMPRE todas.
FILAS_POR_PAGINA = 50


@dataclass
class Tabla:
    """Una tabla de la ventana y una hoja del Excel.

    `columnas`: `[(rótulo, clave, tipo)]`, con tipo '' (texto), 'num', 'fecha' o
    'dinero'. `filas`: diccionarios; si traen `aspirante_id`, el doble clic abre
    el histórico de esa persona.
    """
    nombre: str
    columnas: list
    filas: list


@dataclass
class Ventana:
    titulo: str
    tablas: list
    ver_mas: list = field(default_factory=list)   # [(texto, url)]
    cifras: list = field(default_factory=list)    # [(rótulo, valor)]
    buscable: bool = True
    pista: str = 'Buscar por nombre, expediente o CI…'
    nota: str = ''          # aclaración bajo el título (p. ej. por qué la lista sale distinta)


# --------------------------------------------------------------------------
# Piezas comunes
# --------------------------------------------------------------------------

def _nombre(aspirante):
    return ' '.join(p for p in (aspirante.nombre, aspirante.papellido, aspirante.sapellido) if p)


def _cargo_y_unidad(registro):
    cargo = registro.cargo
    if not cargo:
        return '—', '—'
    departamento = cargo.departamento
    unidad = departamento.unidad_organizativa if departamento else None
    return (cargo.ncargo.descripcion if cargo.ncargo else '—',
            unidad.descripcion if unidad else '—')


def _persona(registro, **extra):
    """La fila de una persona (de un contrato o de una baja)."""
    cargo, unidad = _cargo_y_unidad(registro)
    aspirante = registro.aspirante
    return {'expediente': registro.no_expediente or '—', 'nombre': _nombre(aspirante),
            'ci': aspirante.doc_identidad or '', 'aspirante_id': registro.aspirante_id,
            'cargo': cargo, 'unidad': unidad, **extra}


RELACIONES = ('aspirante', 'cargo__ncargo', 'cargo__departamento__unidad_organizativa', 'tipo')


def _unidades_para_listas(request):
    """Las unidades elegidas en «Filtros Organizativos», como `unidad=..` de las
    listas (que se llaman así, y no `uo`). Sin elegir ninguna, la lista aplica
    sola el alcance del rol."""
    _uo_ids, contexto = resolver_filtros(request)
    return [('unidad', v) for v in contexto.get('filtro_uo_seleccionadas_txt') or []]


def _url(nombre, parametros):
    from urllib.parse import urlencode
    consulta = urlencode([(k, v) for k, v in parametros if v not in (None, '')])
    return reverse(nombre) + ('?' + consulta if consulta else '')


def _hoy_y_hace_30():
    hoy = date.today()
    return hoy, hoy - timedelta(days=30)


# --------------------------------------------------------------------------
# Empleados activos (con los filtros de la lista de Contratos)
# --------------------------------------------------------------------------

#: Los filtros de la lista de Contratos que la Dashboard puede pedir (género y
#: gráficos de distribución). La ventana los aplica con `aplicar_filtros`, la
#: misma función de la lista, así «Ver más» enseña lo mismo.
FILTROS_DE_CONTRATOS = ('sexo', 'nivel_educ', 'cat_ocupacional', 'tipo', 'raza',
                        'especialidad', 'municipio', 'grado_cientifico')


def _describir_filtro(campo, valor):
    from bolsa.models import Aspirante
    from nomencladores.models import NCargo

    if campo == 'sexo':
        return {'M': 'Hombres', 'F': 'Mujeres'}.get(valor, valor)
    if campo == 'cat_ocupacional':
        if valor == 'CUA':
            return 'Cuadros'
        return dict(NCargo._meta.get_field('cat_ocupacional').choices).get(valor, valor)
    if campo in ('nivel_educ', 'raza'):
        return dict(Aspirante._meta.get_field(campo).choices).get(valor, valor)
    if campo == 'grado_cientifico':
        return {'MC': 'Máster', 'DC': 'Doctor', 'NINGUNO': 'Sin grado científico'}.get(valor, valor)
    if campo == 'especialidad':
        from nomencladores.models import NEspecialidad
        return NEspecialidad.objects.filter(pk=valor).values_list('nombre', flat=True).first() or valor
    if campo == 'municipio':
        from nomencladores.models import NMunicipio
        return NMunicipio.objects.filter(pk=valor).values_list('nombre', flat=True).first() or valor
    return valor


def ventana_activos(request):
    from contratos.filtros import aplicar_filtros

    uo_ids, _ = resolver_filtros(request)
    pedidos = [(c, request.GET.get(c)) for c in FILTROS_DE_CONTRATOS if request.GET.get(c)]
    filtros = SimpleNamespace(GET=_SoloEstos(request.GET, FILTROS_DE_CONTRATOS))
    activos = _filtrar_por_uo(CAlta.objects.filter(aspirante__estado='ACTIVO'),
                              'cargo__departamento', uo_ids)
    activos = aplicar_filtros(filtros, activos, solo_comunes=True).select_related(*RELACIONES)
    filas = sorted((_persona(c, tipo=c.tipo.descripcion if c.tipo else '—', fecha_alta=c.fecha_alta)
                    for c in activos), key=lambda f: f['nombre'])
    titulo = 'Empleados activos'
    if pedidos:
        titulo += ' · ' + ' · '.join(_describir_filtro(c, v) for c, v in pedidos)
    return Ventana(
        titulo=titulo,
        tablas=[Tabla('Empleados', [('Exp.', 'expediente', ''), ('Nombre', 'nombre', ''),
                                    ('CI', 'ci', ''), ('Cargo', 'cargo', ''), ('Unidad', 'unidad', ''),
                                    ('Tipo de contrato', 'tipo', ''), ('F. alta', 'fecha_alta', 'fecha')],
                      filas)],
        ver_mas=[('Ver en Contratos', _url('list_contrato', pedidos + _unidades_para_listas(request)))],
        cifras=[('Personas', len(filas))])


class _SoloEstos:
    """`request.GET` reducido a unas claves: así `aplicar_filtros` no recoge por
    accidente otro parámetro de la Dashboard (`uo`, `cortes`, `q`…)."""

    def __init__(self, consulta, claves):
        self._datos = {c: consulta.get(c) for c in claves if consulta.get(c)}

    def get(self, clave, defecto=None):
        return self._datos.get(clave, defecto)

    def getlist(self, clave):
        return [self._datos[clave]] if clave in self._datos else []


# --------------------------------------------------------------------------
# Nuevas altas y nuevas bajas (últimos 30 días)
# --------------------------------------------------------------------------

def ventana_altas(request):
    """Mismo criterio que la tarjeta: PERSONAS con alta en los últimos 30 días, sigan
    o no contratadas (`CAlta.fecha_alta` + `CBaja.fecha_alta`)."""
    uo_ids, _ = resolver_filtros(request)
    hoy, hace_30 = _hoy_y_hace_30()
    personas = {}
    for baja in _filtrar_por_uo(CBaja.objects.filter(fecha_alta__range=(hace_30, hoy)),
                                'cargo__departamento', uo_ids).select_related(*RELACIONES):
        personas[baja.aspirante_id] = _persona(
            baja, fecha_alta=baja.fecha_alta,
            situacion='Causó baja el %s' % baja.fecha_baja.strftime('%d/%m/%Y') if baja.fecha_baja else 'Baja')
    # El contrato vigente manda sobre una baja anterior de la misma persona.
    for contrato in _filtrar_por_uo(CAlta.objects.filter(fecha_alta__range=(hace_30, hoy)),
                                    'cargo__departamento', uo_ids).select_related(*RELACIONES):
        personas[contrato.aspirante_id] = _persona(contrato, fecha_alta=contrato.fecha_alta,
                                                   situacion='Vigente')
    filas = sorted(personas.values(), key=lambda f: (f['fecha_alta'], f['nombre']))
    return Ventana(
        titulo='Nuevas altas · últimos 30 días',
        tablas=[Tabla('Altas', [('F. alta', 'fecha_alta', 'fecha'), ('Exp.', 'expediente', ''),
                                ('Nombre', 'nombre', ''), ('Cargo', 'cargo', ''), ('Unidad', 'unidad', ''),
                                ('Situación', 'situacion', '')], filas)],
        ver_mas=[('Ver en Contratos', _url('list_contrato', [
            ('alta_desde', hace_30.isoformat()), ('alta_hasta', hoy.isoformat())]
            + _unidades_para_listas(request)))],
        cifras=[('Personas', len(filas)), ('Desde', hace_30.strftime('%d/%m/%Y')),
                ('Hasta', hoy.strftime('%d/%m/%Y'))])


def ventana_bajas(request):
    """Mismo criterio que la tarjeta: PERSONAS con baja en los últimos 30 días."""
    uo_ids, _ = resolver_filtros(request)
    hoy, hace_30 = _hoy_y_hace_30()
    personas = {}
    for baja in (_filtrar_por_uo(CBaja.objects.filter(fecha_baja__range=(hace_30, hoy)),
                                 'cargo__departamento', uo_ids)
                 .select_related('causa_baja', *RELACIONES).order_by('fecha_baja', 'pk')):
        personas[baja.aspirante_id] = _persona(
            baja, fecha_baja=baja.fecha_baja,
            causa=baja.causa_baja.descripcion if baja.causa_baja_id else 'Sin causa')
    filas = sorted(personas.values(), key=lambda f: (f['fecha_baja'], f['nombre']))
    return Ventana(
        titulo='Nuevas bajas · últimos 30 días',
        tablas=[Tabla('Bajas', [('F. baja', 'fecha_baja', 'fecha'), ('Exp.', 'expediente', ''),
                                ('Nombre', 'nombre', ''), ('Cargo', 'cargo', ''), ('Unidad', 'unidad', ''),
                                ('Causa', 'causa', '')], filas)],
        ver_mas=[('Ver en Bajas', _url('list_baja', [
            ('baja_desde', hace_30.isoformat()), ('baja_hasta', hoy.isoformat())]
            + _unidades_para_listas(request)))],
        cifras=[('Personas', len(filas)), ('Desde', hace_30.strftime('%d/%m/%Y')),
                ('Hasta', hoy.strftime('%d/%m/%Y'))])


# --------------------------------------------------------------------------
# Top causas de baja
# --------------------------------------------------------------------------

#: Valor de `?causa=` para las bajas sin causa (en la ventana y en la lista).
SIN_CAUSA = 'ninguna'


def ventana_causa(request):
    """Las bajas de una causa, con el mismo criterio que el gráfico: todas las
    bajas registradas (no personas), en el alcance de unidades."""
    from nomencladores.models import NCausaAltaBaja

    uo_ids, _ = resolver_filtros(request)
    causa = (request.GET.get('causa') or '').strip()
    bajas = _filtrar_por_uo(CBaja.objects.all(), 'cargo__departamento', uo_ids)
    if causa == SIN_CAUSA:
        bajas, nombre = bajas.filter(causa_baja__isnull=True), 'Sin causa'
    elif causa.isdigit():
        bajas = bajas.filter(causa_baja_id=causa)
        nombre = (NCausaAltaBaja.objects.filter(pk=causa).values_list('descripcion', flat=True).first()
                  or 'Causa desconocida')
    else:
        raise Http404('Causa no válida.')
    bajas = list(bajas.select_related(*RELACIONES).order_by('-fecha_baja', 'pk'))
    filas = [_persona(b, fecha_alta=b.fecha_alta, fecha_baja=b.fecha_baja) for b in bajas]
    # El gráfico cuenta BAJAS; la lista de Bajas, PERSONAS que siguen de baja hoy.
    personas = {b.aspirante_id: b.aspirante for b in bajas}
    siguen = sum(1 for a in personas.values() if a.estado == 'BAJA')
    nota = ''
    if len(filas) != siguen:
        nota = ('%d baja%s de %d persona%s; %d sigue%s de baja hoy y %s las que verá en la lista de '
                'Bajas (las demás fueron recontratadas o tienen más de una baja).' % (
                    len(filas), '' if len(filas) == 1 else 's', len(personas),
                    '' if len(personas) == 1 else 's', siguen, '' if siguen == 1 else 'n',
                    'esa es' if siguen == 1 else 'esas son'))
    return Ventana(
        titulo='Bajas por «%s»' % nombre,
        tablas=[Tabla('Bajas', [('F. baja', 'fecha_baja', 'fecha'), ('F. alta', 'fecha_alta', 'fecha'),
                                ('Exp.', 'expediente', ''), ('Nombre', 'nombre', ''),
                                ('Cargo', 'cargo', ''), ('Unidad', 'unidad', '')], filas)],
        ver_mas=[('Ver en Bajas', _url('list_baja', [('causa', causa)] + _unidades_para_listas(request)))],
        cifras=[('Bajas', len(filas)), ('Personas', len(personas)), ('Siguen de baja', siguen)],
        nota=nota)


# --------------------------------------------------------------------------
# Unidades organizativas y departamentos
# --------------------------------------------------------------------------

def _unidades_de(request):
    """Las unidades que cuenta la tarjeta: las elegidas o, sin elegir, todas las que
    el usuario puede ver (mismo criterio que `uo_count`)."""
    uo_ids, _ = resolver_filtros(request)
    visibles = unidades_visibles(request.user)
    if uo_ids:
        visibles = visibles.filter(pk__in=uo_ids)
    return visibles


def _cifras_de_plazas(cargos):
    """(cargos, aprobadas, ocupadas, vacantes) de la plantilla aprobada, con el mismo
    criterio que las tarjetas de plazas: cargos activos y EN plantilla."""
    en_plantilla = [c for c in cargos if c.activo and c.en_plantilla]
    aprobadas = sum(c.cant_aprobada or 0 for c in en_plantilla)
    ocupadas = sum(c.cant_cubierta or 0 for c in en_plantilla)
    return len(en_plantilla), aprobadas, ocupadas, max(aprobadas - ocupadas, 0)


def _gestor(request):
    from .views import _contexto_enlaces
    _uo_ids, contexto = resolver_filtros(request)
    unica = _contexto_enlaces(request, contexto)['unidad_unica']
    return [('Abrir el Gestor de Plantilla', _url('gestor_plantilla', [('unidad', unica)]))]


COLUMNAS_PLAZAS = [('Cargos', 'cargos', 'num'), ('Aprobadas', 'aprobadas', 'num'),
                   ('Ocupadas', 'ocupadas', 'num'), ('Vacantes', 'vacantes', 'num'),
                   ('Trabajadores', 'trabajadores', 'num')]


def _trabajadores_por(campo):
    return dict(CAlta.objects.filter(aspirante__estado='ACTIVO')
                .values_list(campo).annotate(n=Count('pk')).values_list(campo, 'n'))


def ventana_unidades(request):
    unidades = list(_unidades_de(request).order_by('orden_informe', 'descripcion'))
    cargos = {}
    for cargo in CargoPlantilla.objects.filter(
            departamento__unidad_organizativa__in=unidades).select_related('departamento'):
        cargos.setdefault(cargo.departamento.unidad_organizativa_id, []).append(cargo)
    trabajadores = _trabajadores_por('cargo__departamento__unidad_organizativa_id')
    filas = []
    for unidad in unidades:
        n, aprobadas, ocupadas, vacantes = _cifras_de_plazas(cargos.get(unidad.pk, []))
        filas.append({'nombre': unidad.descripcion, 'cargos': n, 'aprobadas': aprobadas,
                      'ocupadas': ocupadas, 'vacantes': vacantes,
                      'trabajadores': trabajadores.get(unidad.pk, 0)})
    return Ventana(
        titulo='Unidades organizativas',
        tablas=[Tabla('Unidades', [('Unidad', 'nombre', '')] + COLUMNAS_PLAZAS, filas)],
        ver_mas=_gestor(request), cifras=[('Unidades', len(filas))], pista='Buscar unidad…')


def ventana_departamentos(request):
    unidades = _unidades_de(request)
    departamentos = list(Departamento.objects.filter(unidad_organizativa__in=unidades)
                         .select_related('unidad_organizativa')
                         .order_by('unidad_organizativa__orden_informe', 'unidad_organizativa__descripcion',
                                   'orden_informe', 'descripcion'))
    cargos = {}
    for cargo in CargoPlantilla.objects.filter(departamento__in=departamentos):
        cargos.setdefault(cargo.departamento_id, []).append(cargo)
    trabajadores = _trabajadores_por('cargo__departamento_id')
    filas = []
    for dpto in departamentos:
        n, aprobadas, ocupadas, vacantes = _cifras_de_plazas(cargos.get(dpto.pk, []))
        filas.append({'unidad': dpto.unidad_organizativa.descripcion, 'nombre': dpto.descripcion,
                      'cargos': n, 'aprobadas': aprobadas, 'ocupadas': ocupadas,
                      'vacantes': vacantes, 'trabajadores': trabajadores.get(dpto.pk, 0)})
    return Ventana(
        titulo='Departamentos',
        tablas=[Tabla('Departamentos', [('Unidad', 'unidad', ''), ('Departamento', 'nombre', '')]
                      + COLUMNAS_PLAZAS, filas)],
        ver_mas=_gestor(request), cifras=[('Departamentos', len(filas))],
        pista='Buscar unidad o departamento…')


# --------------------------------------------------------------------------
# Las ventanas que ya existían: solo sus datos para el Excel y su pie
# --------------------------------------------------------------------------

def ventana_piramide(request):
    from .views import datos_piramide
    datos = datos_piramide(request)
    if datos is None:
        raise Http404('Tramo no válido.')
    titulo, filas = datos
    return Ventana(
        titulo='Pirámide de edades · ' + titulo,
        tablas=[Tabla('Personas', [('Exp.', 'expediente', ''), ('Nombre', 'nombre', ''),
                                   ('Edad', 'edad', 'num'), ('Cargo', 'cargo', ''),
                                   ('Unidad', 'unidad', '')], filas)],
        cifras=[('Personas', len(filas))])


def _ver_mas_mes(request):
    """Las altas del mes en Contratos y sus bajas en Bajas (mismo mes y unidades)."""
    try:
        anno, mes = int(request.GET.get('anno')), int(request.GET.get('mes'))
        inicio = date(anno, mes, 1)
    except (TypeError, ValueError):
        return []
    ultimo = (date(anno + 1, 1, 1) if mes == 12 else date(anno, mes + 1, 1)) - timedelta(days=1)
    unidades = _unidades_para_listas(request)
    return [
        ('Ver las altas en Contratos', _url('list_contrato', [
            ('alta_desde', inicio.isoformat()), ('alta_hasta', ultimo.isoformat())] + unidades)),
        ('Ver las bajas en Bajas', _url('list_baja', [
            ('baja_desde', inicio.isoformat()), ('baja_hasta', ultimo.isoformat())] + unidades)),
    ]


def ventana_mes(request):
    from .views import datos_mes
    datos = datos_mes(request)
    if datos is None:
        raise Http404('Mes no válido.')
    titulo, filas, _inicio, _fin = datos
    for fila in filas:
        fila['movimiento'] = 'Alta' if fila['tipo'] == 'alta' else 'Baja'
    return Ventana(
        titulo='Altas y bajas · ' + titulo,
        tablas=[Tabla('Altas y bajas', [('Fecha', 'fecha', 'fecha'), ('Movimiento', 'movimiento', ''),
                                        ('Exp.', 'expediente', ''), ('Nombre', 'nombre', ''),
                                        ('Cargo', 'cargo', ''), ('Unidad', 'unidad', '')], filas)],
        ver_mas=_ver_mas_mes(request),
        cifras=[('Altas', sum(f['tipo'] == 'alta' for f in filas)),
                ('Bajas', sum(f['tipo'] == 'baja' for f in filas))])


def ventana_antiguedad(request):
    from .views import datos_antiguedad
    contratos, rango = datos_antiguedad(request)
    filas = []
    for c in contratos:
        cargo, unidad = _cargo_y_unidad(c)
        filas.append({'expediente': c.no_expediente, 'nombre': _nombre(c.aspirante),
                      'aspirante_id': c.aspirante_id, 'unidad': unidad, 'cargo': cargo,
                      'fecha_alta_entidad': c.fecha_alta_entidad, 'annos': c.antiguedad,
                      'importe': c.importe_annos})
    return Ventana(
        titulo='Años de servicio' + (' · ' + rango if rango else ''),
        tablas=[Tabla('Años de servicio', [
            ('Exp.', 'expediente', ''), ('Nombre', 'nombre', ''), ('Unidad', 'unidad', ''),
            ('Cargo', 'cargo', ''), ('F. alta entidad', 'fecha_alta_entidad', 'fecha'),
            ('Años', 'annos', 'num'), ('Importe', 'importe', 'dinero')], filas)],
        cifras=[('Personas', len(filas))])


def ventana_salario(request):
    from .views import datos_salario
    datos = datos_salario(request)
    tablas = [Tabla(titulo, [(columna, 'nombre', ''), ('Personas', 'personas', 'num'),
                             ('Promedio', 'promedio', 'dinero')], filas)
              for titulo, columna, filas in datos['tablas']]
    return Ventana(titulo='Salario escala promedio', tablas=tablas, buscable=False,
                   cifras=[('Promedio', datos['promedio']), ('Trabajadores activos', datos['personas'])])


def ventana_plazas(request):
    """Dos hojas (decisión del 24-10-2026): las plazas y quién ocupa cada cargo."""
    from .views import VISTAS_PLAZAS, datos_plazas
    cargos, vista, _q = datos_plazas(request)
    plazas, ocupantes = [], []
    por_cargo = {}
    for contrato in (CAlta.objects.filter(cargo__in=cargos).select_related('aspirante', 'tipo')
                     .order_by('aspirante__nombre', 'aspirante__papellido')):
        por_cargo.setdefault(contrato.cargo_id, []).append(contrato)
    for cargo in cargos:
        unidad = cargo.departamento.unidad_organizativa.descripcion if cargo.departamento else '—'
        departamento = cargo.departamento.descripcion if cargo.departamento else '—'
        nombre = cargo.ncargo.descripcion if cargo.ncargo else '—'
        plazas.append({'unidad': unidad, 'departamento': departamento, 'cargo': nombre,
                       'aprobadas': cargo.cant_aprobada or 0, 'ocupadas': cargo.cant_cubierta or 0,
                       'vacantes': cargo.vacantes})
        for contrato in por_cargo.get(cargo.pk, []):
            ocupantes.append({'unidad': unidad, 'departamento': departamento, 'cargo': nombre,
                              'expediente': contrato.no_expediente, 'nombre': _nombre(contrato.aspirante),
                              'aspirante_id': contrato.aspirante_id,
                              'tipo': contrato.tipo.descripcion if contrato.tipo else '—'})
    estructura = [('Unidad', 'unidad', ''), ('Departamento', 'departamento', ''), ('Cargo', 'cargo', '')]
    return Ventana(
        titulo='Plazas · ' + dict(VISTAS_PLAZAS)[vista],
        tablas=[Tabla('Plazas', estructura + [('Aprobadas', 'aprobadas', 'num'),
                                              ('Ocupadas', 'ocupadas', 'num'),
                                              ('Vacantes', 'vacantes', 'num')], plazas),
                Tabla('Ocupantes', estructura + [('Exp.', 'expediente', ''), ('Nombre', 'nombre', ''),
                                                 ('Tipo de contrato', 'tipo', '')], ocupantes)],
        ver_mas=_gestor(request), buscable=False,
        cifras=[('Cargos', len(plazas)), ('Vacantes', sum(p['vacantes'] for p in plazas))])


VENTANAS = {
    'activos': ventana_activos,
    'altas': ventana_altas,
    'bajas': ventana_bajas,
    'causa': ventana_causa,
    'unidades': ventana_unidades,
    'departamentos': ventana_departamentos,
    'piramide': ventana_piramide,
    'mes': ventana_mes,
    'antiguedad': ventana_antiguedad,
    'salario': ventana_salario,
    'plazas': ventana_plazas,
}


# --------------------------------------------------------------------------
# Pantalla, pie y Excel
# --------------------------------------------------------------------------

def _construir(request, clave):
    funcion = VENTANAS.get(clave)
    if funcion is None:
        raise Http404('Ventana desconocida.')
    return funcion(request)


def _buscar(ventana, texto):
    """Lo buscado filtra las filas por nombre, expediente o CI (y por el nombre en
    las tablas de unidades y departamentos)."""
    texto = _sin_tildes(texto)
    if not texto or not ventana.buscable:
        return
    for tabla in ventana.tablas:
        tabla.filas = [f for f in tabla.filas
                       if any(texto in _sin_tildes(f.get(c))
                              for c in ('nombre', 'expediente', 'ci', 'unidad'))]


def _sin_tildes(valor):
    """«García» y «garcia» se encuentran igual."""
    import unicodedata
    texto = unicodedata.normalize('NFD', str(valor or '').strip().lower())
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def _sin(request, *claves):
    consulta = request.GET.copy()
    for clave in claves:
        consulta.pop(clave, None)
    return consulta.urlencode()


def pie_de_ventana(request, clave, ventana=None):
    """`excel_url` y `ver_mas` para el pie común de una ventana
    (`partials/ventana_pie.html`). Las ventanas que ya existían lo añaden a su
    contexto; la genérica lo calcula de la ventana ya construida."""
    if ventana is not None:
        ver_mas = ventana.ver_mas
    else:
        # Sin volver a calcular la ventana entera: solo sus enlaces.
        ver_mas = {'mes': _ver_mas_mes, 'plazas': _gestor}.get(clave, lambda _r: [])(request)
    consulta = _sin(request, 'page', 'solo_tabla', 'solo_filas')
    return {
        'excel_url': reverse('dashboard_ventana_excel', args=[clave]) + ('?' + consulta if consulta else ''),
        'ver_mas': ver_mas,
    }


def ventana_html(request, clave):
    """La ventana genérica: título, buscador, tabla paginada (50 filas) y el pie con
    «Ver más» y «Excel». Con `?solo_tabla=1` devuelve solo la tabla (buscar y
    cambiar de página sin perder el foco del buscador)."""
    ventana = _construir(request, clave)
    q = (request.GET.get('q') or '').strip()
    _buscar(ventana, q)
    tablas = []
    for tabla in ventana.tablas:
        pagina = Paginator(tabla.filas, FILAS_POR_PAGINA).get_page(request.GET.get('page'))
        tablas.append({'tabla': tabla, 'pagina': pagina, 'total': len(tabla.filas)})
    contexto = {
        'clave': clave, 'ventana': ventana, 'tablas': tablas, 'q': q,
        'url_tabla': reverse('dashboard_ventana', args=[clave]) + '?' + _sin(request, 'page', 'q', 'solo_tabla'),
        **pie_de_ventana(request, clave, ventana),
    }
    plantilla = ('pages/dashboard/partials/ventana_tabla.html' if request.GET.get('solo_tabla')
                 else 'pages/dashboard/partials/ventana.html')
    return render(request, plantilla, contexto)


def ventana_excel(request, clave):
    """El Excel de una ventana: portada con logo y una hoja por tabla, con TODAS las
    filas (sin paginar) y lo mismo que se ve (unidades, filtro y búsqueda)."""
    from core.nombres_descarga import nombre_de_informe
    from informes.excel import LibroDeInforme, respuesta
    from informes.views import _cabecera_documento

    ventana = _construir(request, clave)
    _buscar(ventana, request.GET.get('q'))

    contexto = _cabecera_documento(request)
    _uo_ids, filtro = resolver_filtros(request)
    elegidas = filtro.get('filtro_uo_seleccionadas_txt') or []
    contexto['cab_unidades'] = list(UnidadOrganizativa.objects.filter(pk__in=elegidas)
                                    .order_by('orden_informe', 'descripcion')
                                    .values_list('descripcion', flat=True))
    contexto['cab_unidades_resumen'] = ', '.join(contexto['cab_unidades']) or 'Todas las unidades'
    contexto['periodo_texto'] = 'al %s' % date.today().strftime('%d/%m/%Y')

    libro = LibroDeInforme(contexto, ventana.titulo)
    cifras = list(ventana.cifras)
    if request.GET.get('q'):
        cifras.append(('Búsqueda', request.GET.get('q').strip()))
    libro.portada(cifras=cifras)
    for tabla in ventana.tablas:
        filas = [[_valor_excel(fila.get(clave_col), tipo) for _r, clave_col, tipo in tabla.columnas]
                 for fila in tabla.filas]
        centradas = [i for i, (_r, _c, tipo) in enumerate(tabla.columnas, start=1)
                     if tipo in ('num', 'fecha')]
        anchos = [min(45, max([len(rotulo) + 4] + [len(str(f[i] or '')) + 2 for f in filas[:300]]))
                  for i, (rotulo, _c, _t) in enumerate(tabla.columnas)]
        libro.datos(tabla.nombre, [r for r, _c, _t in tabla.columnas], filas,
                    anchos=anchos, centradas=centradas)
    nombre = nombre_de_informe('Dashboard', ventana.titulo.split(' · ')[0], extension='xlsx')
    return respuesta(libro.libro, nombre)


def _valor_excel(valor, tipo):
    if valor is None:
        return ''
    if tipo == 'fecha' and isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')
    if tipo == 'dinero':
        try:
            return round(float(valor), 2)
        except (TypeError, ValueError):
            return valor
    return valor
