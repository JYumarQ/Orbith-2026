# -*- coding: utf-8 -*-
"""Movimientos de personal de un mes: las Altas y las Bajas.

Este informe reproduce el modelo que la UNE pide cada mes a la provincia, un
libro de cuatro hojas: resumen y detalle de las altas, resumen y detalle de las
bajas.

POR QUE NO USA `fuentes.FuenteDatos`
------------------------------------
Los otros seis informes son FOTOGRAFIAS: «cuántos trabajadores hay hoy», o
«cuántos había el 31 de agosto». Por eso `fuentes.py` construye una lista de
contratos vigentes en un instante, y por eso puede leerla de un cierre.

Este informe es de MOVIMIENTOS: no pregunta cuántos hay, sino quién entró y
quién salió ENTRE dos fechas. Un cierre mensual no sirve para responder eso —la
fotografía de febrero no distingue al que llevaba diez años del que entró el día
3—, así que aquí se consulta siempre la base viva, acotada por fecha.

EL DETALLE QUE HACE FALTA ENTENDER
----------------------------------
Al dar de baja a alguien, `contratos.views` BORRA su fila de `CAlta` y crea una
de `CBaja` que conserva la `fecha_alta`. Consecuencia: si las altas de febrero se
buscaran solo en `CAlta`, quien entró en febrero y se fue en marzo desaparecería
del informe de febrero, y el mismo informe daría cifras distintas según el día en
que se generara. Por eso las altas se buscan en las DOS tablas.
"""
import calendar
from dataclasses import dataclass
from datetime import date

from contratos.models import CAlta, CBaja
from nomencladores.models import sigla_de_nivel_educacional

from . import fuentes


# --------------------------------------------------------------------------
# Equivalencias con el modelo de la UNE
# --------------------------------------------------------------------------

# El modelo pide la categoría ocupacional como una sola letra. Los dos tipos de
# Cuadro (Directivo y Ejecutivo) comparten la C: la UNE no los separa.
LETRA_CATEGORIA = {
    'OPE': 'O',
    'TEC': 'T',
    'ADM': 'A',
    'SER': 'S',
    'CDI': 'C',
    'CEJ': 'C',
}

# Lo que se escribe cuando una unidad no tiene municipio declarado. Dice «esto se
# miró y no hay dato»; una celda en blanco no distingue eso de un olvido.
SIN_MUNICIPIO = '-----'

# «Graduado en» cuando el trabajador no tiene especialidad registrada. En el
# modelo esa columna mezcla títulos («Lic. Economía») con grados escolares
# («12 Grado»): lo primero para quien estudió una carrera, lo segundo para quien
# no. Aquí se deduce del nivel educacional.
GRADO_POR_NIVEL = {
    'NS': 'Nivel Superior',
    'MS': '12 Grado',
    'TM': '12 Grado',
    'NG': '9no Grado',
    'OC': 'Obrero Calificado',
    'PR': '6to Grado',
    'SA': '',
}


@dataclass(frozen=True)
class FilaMovimiento:
    """Una persona que entró o salió. Los cinco últimos campos, solo las bajas."""

    nombre: str
    cargo: str
    area: str
    puesto_clave: bool
    sexo: str
    edad: int
    # La letra que pide el modelo de la UNE (O, T, A, S, C) y el código completo
    # de Orbith. Hacen falta las dos: la letra es lo que se escribe en el papel,
    # y el código es lo que permite darle a la insignia el color global de su
    # categoría. Con la letra sola, Cuadro Directivo y Cuadro Ejecutivo serían
    # indistinguibles y ninguno de los dos tendría color.
    categoria: str
    cat_codigo: str
    nivel_escolar: str
    graduado_en: str
    fecha: date
    unidad: str
    # Municipio de la unidad en la que la persona entra o de la que sale, NO el
    # de su domicilio. Una unidad puede no tenerlo declarado, y entonces se
    # escribe la marca de hueco en vez de dejar la celda vacía: en un documento
    # que se archiva, un blanco no distingue «no lo tiene» de «se olvidó».
    municipio: str
    unidad_id: int
    ncargo_id: int

    actividad: str = ''
    causa: str = ''
    completar_cargo: bool = False
    antiguedad: str = ''
    cobro_sistema_pago: bool = False
    # Para la ventana de una cifra del resumen: el expediente y el trabajador
    # (doble clic, su histórico).
    expediente: str = ''
    aspirante_id: object = None

    @property
    def es_mujer(self):
        return self.sexo == 'F'


# --------------------------------------------------------------------------
# Cálculos sobre una persona
# --------------------------------------------------------------------------

def _nombre(aspirante):
    if aspirante is None:
        return ''
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido or '']
    return ' '.join(p for p in partes if p).strip()


def _edad(nacimiento, referencia):
    """Edad cumplida el día del movimiento, no la de hoy.

    Un informe de febrero que se reimprima en diciembre tiene que seguir diciendo
    la edad que la persona tenía en febrero; si no, el documento archivado y el
    reimpreso no coincidirían.
    """
    if not nacimiento or not referencia:
        return None
    anos = referencia.year - nacimiento.year
    if (referencia.month, referencia.day) < (nacimiento.month, nacimiento.day):
        anos -= 1
    return anos if anos >= 0 else None


def _graduado_en(aspirante):
    if aspirante is None:
        return ''
    if aspirante.especialidad_id:
        return aspirante.especialidad.nombre
    return GRADO_POR_NIVEL.get(aspirante.nivel_educ or '', '')


def _plural(cantidad, singular, plural):
    return '%d %s' % (cantidad, singular if cantidad == 1 else plural)


def _antiguedad(desde, hasta):
    """«2 años y 8 meses», con el mismo estilo que el modelo en papel.

    Por debajo del mes se cuenta en días: el modelo trae casos de «10 dias», y
    redondearlos a «0 meses» perdería la única información que aportan.
    """
    if not desde or not hasta or hasta < desde:
        return ''

    meses = (hasta.year - desde.year) * 12 + (hasta.month - desde.month)
    if hasta.day < desde.day:
        meses -= 1

    if meses < 1:
        return _plural((hasta - desde).days, 'día', 'días')

    anos, resto = divmod(meses, 12)
    if not anos:
        return _plural(resto, 'mes', 'meses')
    if not resto:
        return _plural(anos, 'año', 'años')
    return '%s y %s' % (_plural(anos, 'año', 'años'),
                        _plural(resto, 'mes', 'meses'))


def _fila(contrato, fecha, baja=None):
    """Traduce un contrato al lenguaje del modelo de la UNE.

    `contrato.cargo` puede ser nulo (el modelo lo permite), así que todo lo que
    cuelga de él se resuelve con cuidado: un contrato sin cargo tiene que salir
    en el informe con los huecos vacíos, no reventar la página entera.
    """
    aspirante = contrato.aspirante
    cargo = contrato.cargo
    ncargo = cargo.ncargo if cargo else None
    departamento = cargo.departamento if cargo else None
    unidad = departamento.unidad_organizativa if departamento else None

    extra = {}
    if baja is not None:
        # La antigüedad se mide desde la entrada REAL a la empresa. En las bajas
        # antiguas ese dato no se guardó (el campo es nuevo), y para ellas se cae
        # a la fecha del contrato: es lo único que hay.
        desde = baja.fecha_alta_entidad or baja.fecha_alta
        extra = {
            'actividad': baja.actividad_realizada or '',
            'causa': baja.causa_baja.descripcion if baja.causa_baja_id else '',
            'completar_cargo': baja.completar_cargo,
            'antiguedad': _antiguedad(desde, baja.fecha_baja),
            'cobro_sistema_pago': baja.cobro_sistema_pago,
        }

    return FilaMovimiento(
        nombre=_nombre(aspirante),
        cargo=ncargo.descripcion if ncargo else '',
        area=departamento.descripcion if departamento else '',
        puesto_clave=bool(ncargo and ncargo.puesto_clave),
        sexo=aspirante.sexo if aspirante else '',
        edad=_edad(aspirante.fecha_nacimiento if aspirante else None, fecha),
        categoria=LETRA_CATEGORIA.get(ncargo.cat_ocupacional if ncargo else '', ''),
        cat_codigo=(ncargo.cat_ocupacional or '') if ncargo else '',
        # La SIGLA, no el código guardado: MS(TM) y MS(DG) distinguen las
        # dos ramas de Medio Superior, y el Nivel Medio se escribe NM
        # aunque la base lo guarde como NG.
        nivel_escolar=(sigla_de_nivel_educacional(aspirante.nivel_educ)
                       if aspirante else ''),
        graduado_en=_graduado_en(aspirante),
        fecha=fecha,
        unidad=unidad.descripcion if unidad else 'Sin Unidad',
        municipio=(unidad.municipio.nombre
                   if unidad and unidad.municipio_id else SIN_MUNICIPIO),
        unidad_id=unidad.pk if unidad else None,
        ncargo_id=ncargo.pk if ncargo else None,
        expediente=contrato.no_expediente or '',
        aspirante_id=contrato.aspirante_id,
        **extra
    )


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------

RELACIONES = (
    'aspirante', 'aspirante__especialidad',
    'cargo__ncargo', 'cargo__departamento__unidad_organizativa',
    'cargo__departamento__unidad_organizativa__municipio',
)


def limites_del_mes(anno, mes):
    """Primer y último día del mes, ambos incluidos."""
    return (date(anno, mes, 1),
            date(anno, mes, calendar.monthrange(anno, mes)[1]))


def _acotar(consulta, unidades_ids):
    """`None` es «toda la empresa»; una lista vacía es «nada», y no es lo mismo.

    Una lista vacía la devuelve `unidades_pedidas` cuando el usuario es un
    Moderador sin unidades asignadas, o cuando pidió unidades que no tiene
    permitidas. Tratarla como «sin filtro» le enseñaría justo lo contrario de lo
    que debe ver, así que aquí se traduce a un `__in=[]`, que no devuelve nada.
    """
    if unidades_ids is None:
        return consulta
    return consulta.filter(
        cargo__departamento__unidad_organizativa_id__in=unidades_ids)


def altas_del_mes(anno, mes, unidades_ids=None):
    """Todo el que entró ese mes, siga en plantilla o ya no.

    La segunda consulta —la de `CBaja`— es la que recupera a quien entró y salió
    dentro del mismo período; sin ella el informe encogería con el tiempo.
    """
    inicio, fin = limites_del_mes(anno, mes)

    vigentes = _acotar(
        CAlta.objects.select_related(*RELACIONES)
        .filter(fecha_alta__gte=inicio, fecha_alta__lte=fin), unidades_ids)

    ya_de_baja = _acotar(
        CBaja.objects.select_related(*RELACIONES)
        .filter(fecha_alta__gte=inicio, fecha_alta__lte=fin), unidades_ids)

    filas = [_fila(c, c.fecha_alta) for c in vigentes]
    filas += [_fila(b, b.fecha_alta) for b in ya_de_baja]
    return _ordenar(filas)


def bajas_del_mes(anno, mes, unidades_ids=None):
    inicio, fin = limites_del_mes(anno, mes)

    consulta = _acotar(
        CBaja.objects.select_related(*RELACIONES, 'causa_baja')
        .filter(fecha_baja__gte=inicio, fecha_baja__lte=fin), unidades_ids)

    return _ordenar([_fila(b, b.fecha_baja, baja=b) for b in consulta])


def _ordenar(filas):
    """Por unidad y, dentro de ella, por fecha: así se lee el mes como sucedió."""
    return sorted(filas, key=lambda f: (
        (f.unidad or '').lower(),
        f.fecha or date.min,
        (f.nombre or '').lower(),
    ))


# --------------------------------------------------------------------------
# Las hojas de resumen
# --------------------------------------------------------------------------

def _por_cargo(filas):
    """Cuántos movimientos tuvo cada cargo, del más repetido al menos.

    A igual cantidad se ordena por nombre, para que dos meses con las mismas
    cifras produzcan exactamente la misma tabla y se puedan comparar.
    """
    cuenta = {}
    for fila in filas:
        cuenta[fila.cargo] = cuenta.get(fila.cargo, 0) + 1
    return sorted(cuenta.items(), key=lambda par: (-par[1], par[0]))


def _emparejar(izquierda, derecha):
    """Las dos listas del resumen, fila a fila, para pintarlas una al lado de otra.

    Los dos desgloses —puestos clave y puestos no clave— casi nunca tienen la
    misma longitud, y ninguna de las cuatro salidas sabe recorrer dos listas a la
    vez: la de Word son bucles de docxtpl, que iteran UNA colección. Así que el
    emparejado se hace aquí, en Python, y las cuatro se limitan a recorrer una
    sola lista de filas ya cuadradas. Las celdas sobrantes del bloque más corto
    van vacías.
    """
    total = max(len(izquierda), len(derecha))
    emparejadas = []
    for indice in range(total):
        cargo_c, cantidad_c = (izquierda[indice] if indice < len(izquierda)
                               else ('', ''))
        cargo_n, cantidad_n = (derecha[indice] if indice < len(derecha)
                               else ('', ''))
        emparejadas.append({
            'cargo_clave': cargo_c, 'cantidad_clave': cantidad_c,
            'cargo_no_clave': cargo_n, 'cantidad_no_clave': cantidad_n,
        })
    return emparejadas


def resumen(filas):
    """Las cifras de la hoja de resumen y los dos desgloses por cargo.

    Se desglosan por separado los puestos CLAVE y los NO CLAVE, y solo los
    cargos que tuvieron movimiento: una tabla donde todas las filas llevan
    número. Cada desglose suma, por construcción, su total correspondiente, y
    los dos juntos suman el total del mes.
    """
    claves = [f for f in filas if f.puesto_clave]
    no_claves = [f for f in filas if not f.puesto_clave]

    desglose = _por_cargo(claves)
    desglose_no_clave = _por_cargo(no_claves)

    return {
        'total': len(filas),
        'total_claves': len(claves),
        'total_no_claves': len(no_claves),
        'total_mujeres': sum(1 for f in filas if f.es_mujer),
        'desglose': desglose,
        'desglose_no_clave': desglose_no_clave,
        # Las dos listas ya cuadradas, que es lo que recorren las plantillas.
        'desglose_par': _emparejar(desglose, desglose_no_clave),
    }


def unidades_pedidas(request):
    """Lo que el usuario pidió, cruzado con lo que tiene permitido ver.

    El cruce con el alcance del rol es obligatorio y va aquí, en el servidor: es
    lo que impide que un Moderador amplíe su visibilidad escribiendo a mano
    `?ueb=` de otra unidad en la barra de direcciones. Sin él, este informe
    enseñaría los movimientos de toda la empresa a quien solo debe ver su UEB.

    Devuelve `None` cuando no hay nada que acotar (Administrador u Observador
    que no eligió unidad), o una lista de ids —posiblemente vacía—.
    """
    marcadas = [valor for valor in request.GET.getlist('ueb')
                if valor and str(valor).isdigit()]
    elegidas = fuentes.expandir_varias_unidades(marcadas) if marcadas else []
    return fuentes.acotar_al_alcance(
        elegidas, fuentes.unidades_visibles(request.user))


def meses_con_movimiento(unidades_ids=None):
    """Claves «AAAA-MM» de los meses que tuvieron alguna alta o alguna baja.

    Alimentan la rejilla del selector de período, que resalta los meses con
    contenido. En los otros seis informes esa marca significa «hay cierre
    declarado»; aquí significa «hubo movimiento», que es lo único que este
    informe sabe responder.

    Los meses SIN movimiento no se bloquean: siguen siendo consultables y dirán
    cero. La marca es una pista, no una puerta.
    """
    claves = set()
    consultas = (
        (_acotar(CAlta.objects.exclude(fecha_alta=None), unidades_ids),
         'fecha_alta'),
        (_acotar(CBaja.objects.exclude(fecha_alta=None), unidades_ids),
         'fecha_alta'),
        (_acotar(CBaja.objects.exclude(fecha_baja=None), unidades_ids),
         'fecha_baja'),
    )
    for consulta, campo in consultas:
        for fecha in consulta.values_list(campo, flat=True):
            claves.add('%04d-%02d' % (fecha.year, fecha.month))
    return sorted(claves)


def annos_con_movimiento(claves, anno_actual):
    """Los años entre los que se mueven las flechas del selector.

    Siempre incluye el año que se está viendo, aunque no tenga movimientos: si
    no, las flechas no podrían salir de él.
    """
    annos = {int(clave[:4]) for clave in claves}
    annos.add(anno_actual)
    return sorted(annos)
