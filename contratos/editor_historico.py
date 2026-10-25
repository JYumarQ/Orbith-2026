"""Motor del editor del histórico (fase 1, 24-10-2026). Solo LEE: no escribe nada.

El editor del histórico deja al Administrador corregir todo el histórico de una
persona. Este módulo es lo que garantiza que una corrección no rompe nada, y lo
hace sin tocar la base de datos:

1. `cargar(aspirante)` lee el histórico y lo ordena en eventos (Alta Inicial o
   Recontratación, Movimiento de Nómina, Baja) agrupados en ciclos de contrato.
2. `aplicar(historico, cambios)` aplica el BORRADOR del Administrador (editar,
   borrar, insertar) sobre una copia.
3. `comprobar(historico)` vuelve a encadenar los «antes» y comprueba las reglas
   de la cronología. Devuelve los errores en español.
4. `resumen(original, propuesto)` lista lo que cambia: lo que tocó el
   Administrador y lo que se ajustó solo.

El guardado (fase 2, `guardar`) y los meses cerrados (fase 3,
`cierres/correcciones.py`) se apoyan en esto.

QUÉ ES CADA COSA EN LA BASE DE DATOS
------------------------------------
* Cada evento es un `TMovimiento`. Guarda una «foto» de antes y de después con
  TEXTOS (cargo, unidad, tipo…) y no claves: así el histórico se lee igual aunque
  el nomenclador cambie después. Por eso aquí el estado es texto, y solo cuando el
  Administrador elige algo del nomenclador se guarda además su id (`ids`), que es
  lo que hace falta para actualizar el contrato vigente.
* Una recontratación se guarda como otra «Alta Inicial»: es la primera de su
  ciclo, no la de la persona.
* Una baja es un `TMovimiento` «Baja» MÁS su registro `CBaja` (causa, fecha del
  documento). Se enlazan por la fecha.
* Al causar baja, los movimientos pierden el enlace a su contrato (SET_NULL), así
  que los ciclos se reconstruyen por ORDEN: cada «Alta Inicial» abre uno y cada
  «Baja» lo cierra.
"""

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils import timezone

ALTA = 'ALTA'
MOV = 'MOV'
BAJA = 'BAJA'

NOMBRE_TIPO = {ALTA: 'Alta Inicial', MOV: 'Movimiento de Nómina', BAJA: 'Baja'}

#: Año mínimo de cualquier fecha (mismo corte que `contratos.cronologia`).
ANO_MINIMO = 1900

#: El estado que deja cada evento: dato -> (columna «antes», columna «después»)
#: de `TMovimiento`. Es lo que encadena un movimiento con el siguiente.
COLUMNAS_ESTADO = {
    'cargo': ('cargo_anterior', 'cargo_nuevo'),
    'departamento': ('departamento_anterior', 'departamento_nuevo'),
    'unidad': ('unidad_anterior', 'unidad_nueva'),
    'grupo_escala': ('grupo_escala_anterior', 'grupo_escala_nuevo'),
    'cat_ocupacional': ('cat_ocupacional_anterior', 'cat_ocupacional_nuevo'),
    'rol': ('rol_anterior', 'rol_nuevo'),
    'tipo_contrato': ('tipo_contrato_anterior', 'tipo_contrato_nuevo'),
    'motivo': ('motivo_anterior', 'motivo_nuevo'),
    'tipo_salario': ('tipo_salario_anterior', 'tipo_salario_nuevo'),
    'tridente': ('tridente_anterior', 'tridente_nuevo'),
    'salario': ('salario_anterior', 'salario_nuevo'),
    'otros': ('otros_anterior', 'otros_nuevo'),
}

#: Cómo se llama cada dato en el resumen.
ETIQUETAS = {
    'fecha': 'Fecha', 'fecha_solicitud': 'Fecha de solicitud', 'observaciones': 'Observaciones',
    'duracion': 'Duración', 'cargo': 'Cargo', 'departamento': 'Departamento', 'unidad': 'Unidad',
    'grupo_escala': 'Grupo escala', 'cat_ocupacional': 'Categoría', 'rol': 'Rol',
    'tipo_contrato': 'Tipo de contrato', 'motivo': 'Motivo', 'tipo_salario': 'Tipo de salario',
    'tridente': 'Tridente', 'salario': 'Salario', 'otros': 'Otros',
    'causa_baja': 'Causa de la baja', 'fecha_documento': 'Fecha del documento',
}

SIN_DATO = '---'

#: Lo que el borrador puede cambiar en un evento.
CAMPOS_EDITABLES = {
    'fecha', 'fecha_solicitud', 'observaciones', 'duracion', 'cargo_id', 'tipo_id',
    'motivo_id', 'tipo_salario', 'tridente_id', 'salario', 'otros', 'causa_baja_id',
    'fecha_documento',
}


class ErrorDeBorrador(Exception):
    """El borrador pide algo imposible (un evento que no existe, un dato que no se
    puede cambiar). El mensaje va al Administrador, en español."""


def estado_vacio():
    """El estado antes de un Alta Inicial: no había nada."""
    estado = {clave: SIN_DATO for clave in COLUMNAS_ESTADO}
    estado['salario'] = Decimal('0.00')
    estado['otros'] = Decimal('0.00')
    return estado


@dataclass
class Evento:
    clave: str                      # 'mov:<pk>', 'baja:<pk>' (baja sin movimiento) o 'nuevo:<n>'
    tipo: str                       # ALTA, MOV o BAJA
    fecha: date
    estado: dict                    # lo que quedó DESPUÉS (vacío en una baja)
    antes: dict
    fecha_solicitud: date = None
    observaciones: str = ''
    duracion: int = None
    causa_baja_id: int = None       # solo bajas
    causa_baja: str = ''
    fecha_documento: date = None
    mov_pk: int = None
    baja_pk: int = None
    ids: dict = field(default_factory=dict)   # ids del nomenclador elegidos en el borrador
    borrado: bool = False
    nuevo: bool = False
    editado: set = field(default_factory=set)  # datos que tocó el Administrador

    @property
    def nombre(self):
        return '%s del %s' % (NOMBRE_TIPO[self.tipo], self.fecha.strftime('%d/%m/%Y'))


@dataclass
class Historico:
    aspirante_id: int
    eventos: list                   # en orden cronológico (incluidos los borrados del borrador)
    contrato_pk: int = None         # contrato vigente, si lo hay
    version: str = ''
    anomalias: list = field(default_factory=list)  # datos viejos que no cumplen las reglas

    def vivos(self):
        return [e for e in self.eventos if not e.borrado]

    def evento(self, clave):
        for e in self.eventos:
            if e.clave == clave:
                return e
        raise ErrorDeBorrador('El evento «%s» ya no existe en el histórico. Recargue el editor.' % clave)


# --------------------------------------------------------------------------
# 1. Leer
# --------------------------------------------------------------------------

def _tipo_de(movimiento):
    texto = (movimiento.tipo_movimiento or '').upper()
    if 'BAJA' in texto:
        return BAJA
    if 'ALTA' in texto or 'RECONTRAT' in texto:
        return ALTA
    return MOV


def _decimal(valor):
    if valor is None:
        return Decimal('0.00')
    try:
        return Decimal(str(valor)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


def _estado_de(movimiento, lado):
    """El estado de un `TMovimiento` antes (lado 0) o después (lado 1)."""
    estado = {}
    for clave, columnas in COLUMNAS_ESTADO.items():
        valor = getattr(movimiento, columnas[lado])
        if clave in ('salario', 'otros'):
            estado[clave] = _decimal(valor)
        else:
            estado[clave] = (valor or SIN_DATO).strip() or SIN_DATO
    return estado


def cargar(aspirante):
    """El histórico de la persona, ordenado y agrupable en ciclos."""
    from django.db.models import Q

    from .models import CAlta, CBaja, TMovimiento

    aspirante_id = getattr(aspirante, 'pk', aspirante)
    movimientos = list(
        TMovimiento.objects.filter(Q(aspirante_id=aspirante_id) | Q(contrato__aspirante_id=aspirante_id))
        .order_by('fecha_efectiva', 'pk'))
    bajas = list(CBaja.objects.filter(aspirante_id=aspirante_id).select_related('causa_baja'))
    bajas_por_fecha = {b.fecha_baja: b for b in bajas if b.fecha_baja}
    usadas = set()

    eventos = []
    for m in movimientos:
        tipo = _tipo_de(m)
        evento = Evento(
            clave='mov:%d' % m.pk, tipo=tipo, fecha=m.fecha_efectiva,
            estado={} if tipo == BAJA else _estado_de(m, 1), antes=_estado_de(m, 0),
            fecha_solicitud=m.fecha_solicitud, observaciones=m.observaciones or '',
            duracion=m.duracion_nueva, mov_pk=m.pk)
        if tipo == BAJA:
            baja = bajas_por_fecha.get(m.fecha_efectiva)
            if baja is not None:
                usadas.add(baja.pk)
                evento.baja_pk = baja.pk
                evento.causa_baja_id = baja.causa_baja_id
                evento.causa_baja = baja.causa_baja.descripcion if baja.causa_baja_id else ''
                evento.fecha_documento = baja.fecha_documento
        eventos.append(evento)

    anomalias = []
    # Bajas antiguas sin su movimiento: se muestran para que el histórico esté
    # completo, aunque no tengan «foto».
    for baja in bajas:
        if baja.pk in usadas or not baja.fecha_baja:
            continue
        eventos.append(Evento(
            clave='baja:%d' % baja.pk, tipo=BAJA, fecha=baja.fecha_baja, estado={},
            antes=estado_vacio(), baja_pk=baja.pk, causa_baja_id=baja.causa_baja_id,
            causa_baja=baja.causa_baja.descripcion if baja.causa_baja_id else '',
            fecha_documento=baja.fecha_documento))
        anomalias.append('La baja del %s no tiene su movimiento en el histórico.'
                         % baja.fecha_baja.strftime('%d/%m/%Y'))

    eventos.sort(key=lambda e: (e.fecha, {ALTA: 0, MOV: 1, BAJA: 2}[e.tipo]))
    contrato = CAlta.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_alta').first()
    historico = Historico(aspirante_id=aspirante_id, eventos=eventos,
                          contrato_pk=contrato.pk if contrato else None)
    historico.anomalias = anomalias + [e for e in _errores_de_orden(historico)]
    historico.version = huella(historico)
    return historico


def huella(historico):
    """Resumen de lo leído. Si al guardar no coincide con el de la base, otro
    Administrador cambió el histórico mientras tanto."""
    partes = []
    for e in historico.eventos:
        partes.append(repr((e.clave, e.tipo, e.fecha, sorted(e.estado.items()), sorted(e.antes.items()),
                            e.fecha_solicitud, e.observaciones, e.duracion, e.causa_baja_id,
                            e.fecha_documento)))
    partes.append(repr(historico.contrato_pk))
    return hashlib.sha1('\n'.join(partes).encode('utf-8')).hexdigest()


def ciclos(historico, incluir_borrados=False):
    """Los eventos agrupados por contrato: cada Alta abre un ciclo y cada Baja lo
    cierra. Un ciclo abierto al final es el contrato vigente."""
    grupos, actual = [], []
    for e in historico.eventos:
        if e.borrado and not incluir_borrados:
            continue
        if e.tipo == ALTA and actual and not e.borrado:
            grupos.append(actual)
            actual = []
        actual.append(e)
        if e.tipo == BAJA and not e.borrado:
            grupos.append(actual)
            actual = []
    if actual:
        grupos.append(actual)
    return grupos


# --------------------------------------------------------------------------
# 2. Aplicar el borrador
# --------------------------------------------------------------------------

def _fecha(valor, etiqueta):
    if valor in (None, ''):
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ErrorDeBorrador('%s no es una fecha válida.' % etiqueta)


def _aplicar_campos(evento, campos):
    from nomencladores.models import NCausaAltaBaja, NMotivoContrato, NTipoContrato, NTridente
    from strorganizativa.models import CargoPlantilla

    desconocidos = set(campos) - CAMPOS_EDITABLES
    if desconocidos:
        raise ErrorDeBorrador('No se puede cambiar: %s.' % ', '.join(sorted(desconocidos)))
    if evento.tipo == BAJA and set(campos) - {'fecha', 'causa_baja_id', 'fecha_documento', 'observaciones'}:
        raise ErrorDeBorrador('De una baja solo se corrigen la fecha, la causa y la fecha del documento.')

    def marcar(clave, valor):
        evento.editado.add(clave)
        return valor

    if 'fecha' in campos:
        evento.fecha = marcar('fecha', _fecha(campos['fecha'], 'La fecha'))
    if 'fecha_solicitud' in campos:
        evento.fecha_solicitud = marcar('fecha_solicitud', _fecha(campos['fecha_solicitud'], 'La fecha de solicitud'))
    if 'fecha_documento' in campos:
        evento.fecha_documento = marcar('fecha_documento', _fecha(campos['fecha_documento'], 'La fecha del documento'))
    if 'observaciones' in campos:
        evento.observaciones = marcar('observaciones', (campos['observaciones'] or '').strip())
    if 'duracion' in campos:
        valor = campos['duracion']
        evento.duracion = marcar('duracion', int(valor) if valor not in (None, '') else None)
    if 'causa_baja_id' in campos:
        causa = NCausaAltaBaja.objects.filter(pk=campos['causa_baja_id']).first()
        if causa is None:
            raise ErrorDeBorrador('La causa de baja elegida no existe.')
        evento.causa_baja_id = causa.pk
        evento.causa_baja = marcar('causa_baja', causa.descripcion)

    estado = evento.estado
    if 'cargo_id' in campos:
        cargo = (CargoPlantilla.objects.select_related(
            'ncargo__grupo_escala', 'departamento__unidad_organizativa', 'rol')
            .filter(pk=campos['cargo_id']).first())
        if cargo is None:
            raise ErrorDeBorrador('El cargo elegido no existe.')
        evento.ids['cargo_id'] = cargo.pk
        departamento = cargo.departamento
        unidad = departamento.unidad_organizativa if departamento else None
        evento.ids['unidad_id'] = unidad.pk if unidad else None
        nuevos = {
            'cargo': cargo.ncargo.descripcion,
            'departamento': departamento.descripcion if departamento else SIN_DATO,
            'unidad': unidad.descripcion if unidad else SIN_DATO,
            'grupo_escala': cargo.ncargo.grupo_escala.nivel if cargo.ncargo.grupo_escala_id else SIN_DATO,
            'cat_ocupacional': cargo.ncargo.get_cat_ocupacional_display() or SIN_DATO,
            'rol': cargo.rol.tipo if cargo.rol_id else SIN_DATO,
        }
        for clave, valor in nuevos.items():
            if estado.get(clave) != valor:
                estado[clave] = marcar(clave, valor)
    if 'tipo_id' in campos:
        tipo = NTipoContrato.objects.filter(pk=campos['tipo_id']).first()
        if tipo is None:
            raise ErrorDeBorrador('El tipo de contrato elegido no existe.')
        evento.ids['tipo_id'] = tipo.pk
        estado['tipo_contrato'] = marcar('tipo_contrato', tipo.descripcion)
        if not tipo.requiere_motivo and 'motivo_id' not in campos:
            # Un tipo que no lleva motivo no conserva el del tipo anterior.
            evento.ids['motivo_id'] = None
            if estado.get('motivo') != SIN_DATO:
                estado['motivo'] = marcar('motivo', SIN_DATO)
    if 'motivo_id' in campos:
        if campos['motivo_id'] in (None, ''):
            evento.ids['motivo_id'] = None
            estado['motivo'] = marcar('motivo', SIN_DATO)
        else:
            motivo = NMotivoContrato.objects.filter(pk=campos['motivo_id']).first()
            if motivo is None:
                raise ErrorDeBorrador('El motivo elegido no existe.')
            evento.ids['motivo_id'] = motivo.pk
            estado['motivo'] = marcar('motivo', motivo.descripcion)
    if 'tipo_salario' in campos:
        codigo = campos['tipo_salario']
        if codigo not in ('FIJ', 'DIN'):
            raise ErrorDeBorrador('El tipo de salario tiene que ser Fijo o Dinámico.')
        evento.ids['tipo_salario'] = codigo
        estado['tipo_salario'] = marcar('tipo_salario', 'Fijo' if codigo == 'FIJ' else 'Dinámico')
        if codigo == 'FIJ' and 'tridente_id' not in campos:
            evento.ids['tridente_id'] = None
            if estado.get('tridente') != SIN_DATO:
                estado['tridente'] = marcar('tridente', SIN_DATO)
    if 'tridente_id' in campos:
        if campos['tridente_id'] in (None, ''):
            evento.ids['tridente_id'] = None
            estado['tridente'] = marcar('tridente', SIN_DATO)
        else:
            tridente = NTridente.objects.filter(pk=campos['tridente_id']).first()
            if tridente is None:
                raise ErrorDeBorrador('El tridente elegido no existe.')
            evento.ids['tridente_id'] = tridente.pk
            estado['tridente'] = marcar('tridente', str(tridente))
    for clave in ('salario', 'otros'):
        if clave in campos:
            try:
                valor = Decimal(str(campos[clave])).quantize(Decimal('0.01'))
            except (InvalidOperation, ValueError):
                raise ErrorDeBorrador('%s tiene que ser una cifra.' % ETIQUETAS[clave])
            if valor < 0:
                raise ErrorDeBorrador('%s no puede ser negativo.' % ETIQUETAS[clave])
            estado[clave] = marcar(clave, valor)


def aplicar(historico, cambios):
    """Copia del histórico con el borrador aplicado. `cambios` es una lista de:

    * `{'op': 'editar', 'evento': clave, 'campos': {...}}`
    * `{'op': 'borrar', 'evento': clave}`
    * `{'op': 'insertar', 'tras': clave, 'campos': {'fecha': ..., ...}}` — un
      Movimiento de Nómina nuevo detrás de ese evento, que parte de lo que había.

    No comprueba las reglas: eso lo hace `comprobar()`, para poder enseñarlas todas
    juntas.
    """
    propuesto = copy.deepcopy(historico)
    nuevos = 0
    for cambio in cambios:
        op = cambio.get('op')
        if op == 'editar':
            evento = propuesto.evento(cambio.get('evento'))
            if evento.borrado:
                raise ErrorDeBorrador('No se puede corregir %s: está marcado para borrar.' % evento.nombre)
            _aplicar_campos(evento, cambio.get('campos') or {})
        elif op == 'borrar':
            propuesto.evento(cambio.get('evento')).borrado = True
        elif op == 'insertar':
            anterior = propuesto.evento(cambio.get('tras'))
            if anterior.tipo == BAJA:
                raise ErrorDeBorrador('Después de una baja solo puede venir una recontratación, '
                                      'no un movimiento de nómina.')
            nuevos += 1
            campos = dict(cambio.get('campos') or {})
            if not campos.get('fecha'):
                raise ErrorDeBorrador('Indique la fecha del movimiento que va a insertar.')
            evento = Evento(clave='nuevo:%d' % nuevos, tipo=MOV,
                            fecha=_fecha(campos.pop('fecha'), 'La fecha'),
                            estado=dict(anterior.estado), antes=dict(anterior.estado), nuevo=True)
            evento.ids = dict(anterior.ids)
            _aplicar_campos(evento, campos)
            propuesto.eventos.insert(propuesto.eventos.index(anterior) + 1, evento)
        else:
            raise ErrorDeBorrador('Operación desconocida: %s.' % op)
    propuesto.eventos.sort(key=lambda e: (e.fecha, {ALTA: 0, MOV: 1, BAJA: 2}[e.tipo]))
    return propuesto


# --------------------------------------------------------------------------
# 3. Comprobar y encadenar
# --------------------------------------------------------------------------

def _errores_de_orden(historico):
    """Las reglas de la cronología sobre los eventos vivos (sin encadenar)."""
    errores = []
    hoy = timezone.localdate()
    vivos = historico.vivos()
    anterior = None
    for e in vivos:
        if e.fecha.year < ANO_MINIMO:
            errores.append('%s: el año debe ser %d o posterior.' % (e.nombre, ANO_MINIMO))
        if e.fecha > hoy:
            errores.append('%s: no puede tener fecha futura.' % e.nombre)
        if anterior is not None:
            if e.fecha == anterior.fecha:
                errores.append('%s y %s caen el mismo día: cada evento tiene que ser '
                               'posterior al anterior.' % (anterior.nombre, e.nombre))
            if anterior.tipo == BAJA and e.tipo != ALTA:
                errores.append('%s va después de una baja: tras una baja solo puede venir una '
                               'recontratación.' % e.nombre)
            if anterior.tipo != BAJA and e.tipo == ALTA:
                errores.append('%s: para recontratar, antes tiene que haber una baja.' % e.nombre)
        elif e.tipo != ALTA:
            errores.append('El histórico tiene que empezar por el Alta Inicial; empieza por %s.' % e.nombre)
        anterior = e
    return errores


def _errores_de_borrado(historico):
    """Un Alta solo se borra si es lo único que queda de su contrato. Una baja no se
    borra: se corrige (fecha, causa, documento)."""
    errores = []
    for grupo in ciclos(historico, incluir_borrados=True):
        alta = grupo[0] if grupo and grupo[0].tipo == ALTA else None
        if alta is not None and alta.borrado and any(not e.borrado for e in grupo[1:]):
            errores.append('El %s no se puede borrar mientras su contrato tenga otros eventos: '
                           'borre antes los demás.' % alta.nombre.replace('Alta Inicial', 'alta'))
        for e in grupo:
            if e.tipo == BAJA and e.borrado:
                errores.append('La %s no se puede borrar: corrija su fecha o su causa. Si nunca '
                               'debió causar baja, consulte con el desarrollador.' % e.nombre.lower())
    return errores


def encadenar(historico):
    """Rehace los «antes»: el de cada evento es el estado que dejó el anterior de su
    ciclo (y el vacío para un Alta). Devuelve los eventos cuyo «antes» cambió."""
    ajustados = []
    previo = None
    for e in historico.vivos():
        if e.tipo == ALTA:
            nuevo_antes = estado_vacio()
        elif previo is not None:
            nuevo_antes = dict(previo.estado) if previo.tipo != BAJA else estado_vacio()
        else:
            nuevo_antes = dict(e.antes)
        if nuevo_antes != e.antes:
            ajustados.append(e)
            e.antes = nuevo_antes
        previo = e
    return ajustados


def _errores_de_tipo(historico):
    """Todo Alta y Movimiento tiene un tipo de contrato del nomenclador (25-10-2026).
    Antes el editor ofrecía «Sin tipo» como si fuera uno más y dejaba guardar así."""
    from nomencladores.models import NTipoContrato

    from nomencladores.models import NMotivoContrato

    tipos = {t.descripcion: t for t in NTipoContrato.objects.all()}
    motivos = set(NMotivoContrato.objects.values_list('tipo_contrato__descripcion', 'descripcion'))
    errores = []
    for e in historico.vivos():
        if e.tipo == BAJA:
            continue
        tipo = (e.estado.get('tipo_contrato') or SIN_DATO).strip()
        if tipo == SIN_DATO:
            errores.append('%s: falta el tipo de contrato. Elíjalo en el evento.' % e.nombre)
        elif tipo not in tipos:
            errores.append('%s: el tipo de contrato «%s» ya no existe en el nomenclador. Elija otro.'
                           % (e.nombre, tipo))
        elif tipos[tipo].requiere_motivo:
            # Mismo criterio para el motivo cuando el tipo lo pide (25-10-2026).
            motivo = (e.estado.get('motivo') or SIN_DATO).strip()
            if motivo == SIN_DATO:
                errores.append('%s: el tipo «%s» pide motivo y no lo tiene. Elíjalo en el evento.'
                               % (e.nombre, tipo))
            elif (tipo, motivo) not in motivos:
                errores.append('%s: el motivo «%s» no existe para el tipo «%s». Elija otro.'
                               % (e.nombre, motivo, tipo))
    return errores


def comprobar(historico):
    """Errores del histórico propuesto (lista vacía si todo está bien)."""
    return _errores_de_borrado(historico) + _errores_de_orden(historico) + _errores_de_tipo(historico)


# --------------------------------------------------------------------------
# 4. Resumen de cambios
# --------------------------------------------------------------------------

def _texto(valor):
    if valor is None or valor == '':
        return SIN_DATO
    if isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')
    if isinstance(valor, Decimal):
        return '{:,.2f}'.format(valor).replace(',', ' ').replace('.', ',')
    return str(valor)


def estado_final(historico):
    """Cómo queda la persona: 'ACTIVO' (último ciclo abierto), 'BAJA' (todos
    cerrados) o 'ASPIRANTE' (sin ningún evento)."""
    vivos = historico.vivos()
    if not vivos:
        return 'ASPIRANTE'
    return 'BAJA' if vivos[-1].tipo == BAJA else 'ACTIVO'


def resumen(original, propuesto):
    """Lo que cambia, para la ventana «Revisar los cambios»:

    * `cambios`: `[(evento, dato, antes, después)]` de lo que tocó el Administrador,
      incluidos los eventos nuevos y los borrados.
    * `ajustes`: los «antes» que se rehicieron solos al encadenar.
    * `estado_persona`: `(antes, después)` si la ficha cambia de estado.
    * `ultimo`: el estado que deja el último evento vivo (lo que pasará al
      contrato vigente si se corrigió).

    `preparar` y `guardar` añaden `meses`: los cierres ya declarados que cambian
    (ver `cierres/correcciones.py`).
    """
    originales = {e.clave: e for e in original.eventos}
    cambios = []
    for e in propuesto.eventos:
        if e.nuevo:
            cambios.append((e.nombre, 'Nuevo movimiento', SIN_DATO,
                            '%s · %s' % (e.estado.get('cargo', SIN_DATO), _texto(e.estado.get('salario')))))
            continue
        if e.borrado:
            cambios.append((originales[e.clave].nombre, 'Borrado', 'existía', 'se borra'))
            continue
        antes_ev = originales.get(e.clave)
        if antes_ev is None:
            continue
        for dato in sorted(e.editado):
            if dato == 'fecha':
                viejo, nuevo = antes_ev.fecha, e.fecha
            elif dato in COLUMNAS_ESTADO:
                viejo, nuevo = antes_ev.estado.get(dato), e.estado.get(dato)
            elif dato == 'causa_baja':
                viejo, nuevo = antes_ev.causa_baja, e.causa_baja
            else:
                viejo, nuevo = getattr(antes_ev, dato), getattr(e, dato)
            if viejo != nuevo:
                cambios.append((antes_ev.nombre, ETIQUETAS.get(dato, dato), _texto(viejo), _texto(nuevo)))

    ajustes = []
    for e in propuesto.vivos():
        antes_ev = originales.get(e.clave)
        if antes_ev is None or e.tipo == ALTA:
            continue
        diferencias = [ETIQUETAS[d] for d in COLUMNAS_ESTADO if antes_ev.antes.get(d) != e.antes.get(d)]
        if diferencias:
            ajustes.append('%s: su «antes» se ajusta (%s).' % (e.nombre, ', '.join(diferencias).lower()))

    antes_persona, despues_persona = estado_final(original), estado_final(propuesto)
    vivos = propuesto.vivos()
    return {
        'cambios': cambios,
        'ajustes': ajustes,
        'estado_persona': (antes_persona, despues_persona) if antes_persona != despues_persona else None,
        'ultimo': vivos[-1] if vivos else None,
    }


def preparar(aspirante, cambios):
    """Todo de una vez: lee, aplica el borrador, encadena y comprueba.
    Devuelve `(original, propuesto, errores, resumen)`."""
    original = cargar(aspirante)
    propuesto = aplicar(original, cambios)
    encadenar(propuesto)
    errores = comprobar(propuesto)
    res = resumen(original, propuesto)
    if not errores:
        from cierres.correcciones import cierres_afectados, describir
        res['meses'] = describir(cierres_afectados(original, propuesto))
    return original, propuesto, errores, res


# --------------------------------------------------------------------------
# 5. Guardar (fase 2): todo o nada
# --------------------------------------------------------------------------

def _texto_de(estado, clave):
    """Valor de una columna de texto de TMovimiento (nunca vacío)."""
    valor = estado.get(clave)
    return SIN_DATO if valor in (None, '') else valor


def _volcar_estado(movimiento, antes, despues):
    """Escribe el «antes» y, si se da, el «después» en las columnas del movimiento."""
    for clave, (col_antes, col_despues) in COLUMNAS_ESTADO.items():
        if clave in ('salario', 'otros'):
            setattr(movimiento, col_antes, antes.get(clave, Decimal('0.00')))
            if despues:
                setattr(movimiento, col_despues, despues.get(clave, Decimal('0.00')))
        else:
            setattr(movimiento, col_antes, _texto_de(antes, clave))
            if despues:
                setattr(movimiento, col_despues, _texto_de(despues, clave))


def _ids_para_el_contrato(evento):
    """Las claves del nomenclador que necesita el contrato vigente para quedar como
    el último evento. Las elegidas en el borrador se usan tal cual; las demás se
    deducen del texto guardado en el histórico, que tiene que ser inequívoco."""
    from nomencladores.models import NMotivoContrato, NTipoContrato, NTridente
    from strorganizativa.models import CargoPlantilla

    ids, estado = dict(evento.ids), evento.estado
    if 'cargo_id' not in ids:
        cargos = list(CargoPlantilla.objects.filter(
            ncargo__descripcion=estado.get('cargo'), departamento__descripcion=estado.get('departamento'),
            departamento__unidad_organizativa__descripcion=estado.get('unidad'),
        ).values_list('pk', flat=True)[:2])
        if len(cargos) != 1:
            raise ErrorDeBorrador(
                'No se puede saber qué cargo de la plantilla es «%s» (%s, %s): elija el cargo en '
                'el %s para que el contrato vigente quede bien.'
                % (estado.get('cargo'), estado.get('departamento'), estado.get('unidad'),
                   evento.nombre.lower()))
        ids['cargo_id'] = cargos[0]
    if 'tipo_id' not in ids:
        tipos = list(NTipoContrato.objects.filter(
            descripcion=estado.get('tipo_contrato')).values_list('pk', flat=True)[:2])
        if len(tipos) != 1:
            raise ErrorDeBorrador('Elija el tipo de contrato en el %s: «%s» no está en el nomenclador.'
                                  % (evento.nombre.lower(), estado.get('tipo_contrato')))
        ids['tipo_id'] = tipos[0]
    if 'motivo_id' not in ids:
        texto = estado.get('motivo')
        ids['motivo_id'] = None if texto in (None, '', SIN_DATO) else (
            NMotivoContrato.objects.filter(descripcion=texto, tipo_contrato_id=ids['tipo_id'])
            .values_list('pk', flat=True).first())
    if 'tridente_id' not in ids:
        texto = estado.get('tridente')
        ids['tridente_id'] = None if texto in (None, '', SIN_DATO) else next(
            (t.pk for t in NTridente.objects.all() if str(t) == texto), None)
    if 'tipo_salario' not in ids:
        ids['tipo_salario'] = 'FIJ' if estado.get('tipo_salario') == 'Fijo' else 'DIN'
    return ids


def _expediente_de(historico):
    """El expediente de la persona (es uno solo, aunque tenga varios contratos)."""
    from .models import CAlta, CBaja, TMovimiento
    aspirante_id = historico.aspirante_id
    return (CAlta.objects.filter(aspirante_id=aspirante_id).values_list('no_expediente', flat=True).first()
            or CBaja.objects.filter(aspirante_id=aspirante_id).values_list('no_expediente', flat=True).first()
            or TMovimiento.objects.filter(aspirante_id=aspirante_id).exclude(no_expediente='')
            .values_list('no_expediente', flat=True).first()
            or '')


def guardar(aspirante, cambios, motivo, version=None, usuario=None):
    """Aplica el borrador a la base de datos. Todo o nada.

    * `version` es la `huella` con la que se abrió el editor: si el histórico
      cambió desde entonces, no se guarda nada y hay que recargar.
    * `motivo` es obligatorio: queda en Auditoría y en los cambios externos.

    Devuelve el resumen de lo guardado. Lanza `ErrorDeBorrador` (sin escribir nada)
    si falta el motivo, si las reglas no se cumplen o si el histórico cambió.
    """
    import uuid

    from django.contrib.contenttypes.models import ContentType
    from django.db import transaction

    from auditoria import registro_automatico
    from auditoria.models import AccionAuditoria
    from bolsa.models import Aspirante

    from .models import CAlta, CBaja, CambioExterno, TMovimiento, correccion_de_historico

    motivo = (motivo or '').strip()
    if not motivo:
        raise ErrorDeBorrador('Escriba el motivo de la corrección.')
    aspirante_id = getattr(aspirante, 'pk', aspirante)

    with transaction.atomic():
        persona = Aspirante.objects.select_for_update().get(pk=aspirante_id)
        original = cargar(persona)
        if version and original.version != version:
            raise ErrorDeBorrador(
                'El histórico de esta persona cambió mientras lo editaba (otro administrador o '
                'una operación nueva). Recargue el editor y vuelva a hacer los cambios.')
        propuesto = aplicar(original, cambios)
        encadenar(propuesto)
        errores = comprobar(propuesto)
        if errores:
            raise ErrorDeBorrador(' '.join(errores))
        res = resumen(original, propuesto)
        if not res['cambios'] and not res['ajustes']:
            raise ErrorDeBorrador('No hay ningún cambio que guardar.')

        originales = {e.clave: e for e in original.eventos}
        expediente = _expediente_de(original)
        nombre_usuario = (getattr(usuario, 'username', '') or '')[:100]
        descripcion = 'Corrección del histórico (%s)' % motivo[:120]
        contrato = CAlta.objects.filter(pk=original.contrato_pk).first()
        grupos = ciclos(propuesto, incluir_borrados=True)
        ciclo_abierto = grupos[-1] if grupos and grupos[-1][-1].tipo != BAJA else []
        en_ciclo_abierto = {e.clave for e in ciclo_abierto}
        grupos_originales = ciclos(original)
        ultimo_original_clave = (grupos_originales[-1][-1].clave if grupos_originales
                                 and grupos_originales[-1][-1].tipo != BAJA else None)

        def auditar(objeto, accion, antes=None, despues=None, object_id=None):
            registro_automatico.registrar(objeto, accion, antes=antes, despues=despues,
                                          descripcion=descripcion, object_id=object_id)

        with registro_automatico.sin_auditoria_automatica(), correccion_de_historico():
            # --- Movimientos y bajas ---
            for e in propuesto.eventos:
                previo = originales.get(e.clave)
                if e.nuevo:
                    mov = TMovimiento(
                        aspirante_id=aspirante_id, no_expediente=expediente,
                        contrato=contrato if e.clave in en_ciclo_abierto else None,
                        fecha_efectiva=e.fecha, fecha_solicitud=e.fecha_solicitud,
                        observaciones=e.observaciones, duracion_nueva=e.duracion,
                        tipo_movimiento=NOMBRE_TIPO[MOV], usuario=nombre_usuario,
                        unidad_nueva_fk_id=e.ids.get('unidad_id'))
                    _volcar_estado(mov, e.antes, e.estado)
                    mov.save()
                    auditar(mov, AccionAuditoria.CREAR, despues=registro_automatico.fotografia(mov))
                    continue
                if e.borrado:
                    if e.mov_pk:
                        mov = TMovimiento.objects.get(pk=e.mov_pk)
                        antes_foto = registro_automatico.fotografia(mov)
                        mov.delete()
                        auditar(mov, AccionAuditoria.ELIMINAR, antes=antes_foto, object_id=e.mov_pk)
                    continue
                if not (e.editado or (previo is not None and previo.antes != e.antes)):
                    continue
                if e.mov_pk:
                    mov = TMovimiento.objects.get(pk=e.mov_pk)
                    antes_foto = registro_automatico.fotografia(mov)
                    mov.fecha_efectiva = e.fecha
                    mov.observaciones = e.observaciones
                    if e.tipo == BAJA:
                        # En una baja, la «fecha de solicitud» del movimiento es la del documento.
                        mov.fecha_solicitud = e.fecha_documento
                    else:
                        mov.fecha_solicitud = e.fecha_solicitud
                        mov.duracion_nueva = e.duracion
                        if 'unidad_id' in e.ids:
                            mov.unidad_nueva_fk_id = e.ids['unidad_id']
                    _volcar_estado(mov, e.antes, e.estado if e.tipo != BAJA else None)
                    mov.save()
                    auditar(mov, AccionAuditoria.MODIFICAR, antes_foto, registro_automatico.fotografia(mov))
                if e.tipo == BAJA and e.baja_pk and e.editado:
                    baja = CBaja.objects.get(pk=e.baja_pk)
                    antes_foto = registro_automatico.fotografia(baja)
                    baja.fecha_baja = e.fecha
                    baja.fecha_documento = e.fecha_documento
                    baja.causa_baja_id = e.causa_baja_id
                    baja.save()
                    auditar(baja, AccionAuditoria.MODIFICAR, antes_foto, registro_automatico.fotografia(baja))

            # --- La fecha de alta de un contrato cerrado vive en su CBaja ---
            for grupo in grupos:
                alta = grupo[0] if grupo[0].tipo == ALTA else None
                cierre = grupo[-1] if grupo[-1].tipo == BAJA else None
                if alta and cierre and cierre.baja_pk and 'fecha' in alta.editado:
                    CBaja.objects.filter(pk=cierre.baja_pk).update(fecha_alta=alta.fecha)

            # --- Contrato vigente ---
            vivos_abiertos = [e for e in ciclo_abierto if not e.borrado]
            if contrato is not None and ciclo_abierto and not vivos_abiertos:
                # Se borró el contrato entero: nunca debió existir.
                antes_foto = registro_automatico.fotografia(contrato)
                pk_contrato = contrato.pk
                contrato.delete()
                auditar(contrato, AccionAuditoria.ELIMINAR, antes=antes_foto, object_id=pk_contrato)
                contrato = None
            elif contrato is not None and vivos_abiertos:
                ultimo = vivos_abiertos[-1]
                ultimo_original = originales.get(ultimo.clave)
                # Cambia el contrato si cambia CUÁL es el último movimiento (se borró o
                # se insertó uno) o lo que ese último dice.
                cambia_ultimo = (
                    ultimo.clave != ultimo_original_clave or ultimo_original is None
                    or ultimo.estado != ultimo_original.estado
                    or ultimo.duracion != ultimo_original.duracion)
                alta = vivos_abiertos[0]
                cambia_alta = alta.tipo == ALTA and 'fecha' in alta.editado
                if cambia_ultimo or cambia_alta:
                    antes_foto = registro_automatico.fotografia(contrato)
                    if cambia_ultimo:
                        ids = _ids_para_el_contrato(ultimo)
                        contrato.cargo_id = ids['cargo_id']
                        contrato.tipo_id = ids['tipo_id']
                        contrato.motivo_id = ids['motivo_id']
                        contrato.tridente_id = ids['tridente_id']
                        contrato.tipo_salario = ids['tipo_salario']
                        if ultimo.duracion is not None:
                            contrato.duracion = ultimo.duracion
                    if cambia_alta:
                        contrato.fecha_alta = alta.fecha
                    contrato.save()
                    auditar(contrato, AccionAuditoria.MODIFICAR, antes_foto,
                            registro_automatico.fotografia(contrato))

            # --- Estado de la ficha ---
            final = estado_final(propuesto)
            if persona.estado != final:
                Aspirante.objects.filter(pk=persona.pk).update(estado=final)

            # --- Meses cerrados (fase 3): sus fotografías, plazas y totales ---
            from cierres.correcciones import corregir_cierres
            res['meses'] = corregir_cierres(original, propuesto, motivo, usuario=usuario,
                                            expediente=expediente)

        # --- Cambios externos: lo que se ve en el histórico, con su motivo ---
        lote = uuid.uuid4().hex
        tipo_ct = ContentType.objects.get_for_model(Aspirante)
        CambioExterno.objects.bulk_create([
            CambioExterno(
                contrato=contrato, aspirante_id=aspirante_id, no_expediente=expediente,
                origen=CambioExterno.Origen.HISTORICO, origen_content_type=tipo_ct,
                origen_object_id=str(aspirante_id), lote=lote,
                descripcion='%s · %s' % (evento, dato), valor_anterior=str(antes)[:150],
                valor_nuevo=str(despues)[:150], motivo=motivo, usuario=usuario,
                usuario_nombre=(usuario.get_full_name() or usuario.username) if usuario else 'Sistema')
            for evento, dato, antes, despues in res['cambios']])

    # Subsanación revisa a la persona (y su contrato, si lo tiene): así el aviso de
    # MOV-015 se cierra en cuanto el histórico queda bien, también si está de baja.
    from subsanacion.por_registro import revisar_registros
    revisar_registros(contratos=[contrato.pk] if contrato is not None else [],
                      aspirantes=[aspirante_id])
    return res
