"""Meses cerrados y editor del histórico (fase 3, 24-10-2026).

Cuando el Administrador corrige el histórico de una persona, los meses que ya
se cerraron guardan una fotografía con los datos de entonces, que eran los
equivocados. Las reglas acordadas con RRHH:

* **11a** — lo corregido se corrige también en la fotografía de cada cierre en
  el que estaba vigente, pero SOLO en los datos que vienen del histórico (cargo,
  departamento, tipo, motivo, salario, fecha de alta, duración…). Misión, CLA,
  CNCI y el resto no se tocan: no están en el histórico.
* **11b** — si la corrección hace que la persona entre en un mes en el que no
  estaba (o salga de uno en el que estaba), se añade (o se quita) su fila.
* **11c** — si cambia de unidad, su fila pasa al cierre de la otra unidad (si esa
  unidad declaró ese mes; si no, simplemente sale).
* Se recalculan las plazas cubiertas y los totales, se apunta en el cierre
  «Corregido el dd/mm/aaaa por X: motivo» y se avisa al moderador de la unidad.

CÓMO SE DECIDE
--------------
Cada cierre se mira por separado. El «corte» es el día en que se declaró: lo que
la persona tenía ese día es lo que debería salir en la fotografía. Se calcula con
el histórico de antes y con el corregido; si salen iguales, ese cierre no se toca
(así un mes que nada tiene que ver con la corrección queda exactamente como se
declaró, aunque tuviera otras diferencias).
"""

import copy

from django.db.models import Q
from django.utils import timezone

from contratos.editor_historico import ALTA, BAJA, SIN_DATO

from .models import CierreCargo, CierreContrato, CierreUnidad

CODIGO_CIERRE_CORREGIDO = 'CIE-CORREGIDO'

ENTRA, SALE, CORRIGE = 'entra', 'sale', 'corrige'
TEXTO_ACCION = {ENTRA: 'se añade la persona', SALE: 'se quita la persona',
                CORRIGE: 'se corrigen sus datos'}


# --------------------------------------------------------------------------
# 1. Qué tenía la persona un día dado
# --------------------------------------------------------------------------

def situacion_en(historico, dia):
    """Lo que la persona tenía el día `dia` según `historico`, o None si ese día
    no tenía contrato. Es un dict con `estado` (el del último evento), `fecha_alta`
    (la del alta de ese contrato), `duracion` e `ids` (los del nomenclador, si el
    Administrador eligió algo en el último evento)."""
    vivos = [e for e in historico.vivos() if e.fecha <= dia]
    if not vivos or vivos[-1].tipo == BAJA:
        return None
    # El contrato de ese día empieza tras la última baja.
    inicio = 0
    for i, e in enumerate(vivos):
        if e.tipo == BAJA:
            inicio = i + 1
    ciclo = vivos[inicio:]
    alta = next((e for e in ciclo if e.tipo == ALTA), ciclo[0])
    duracion = next((e.duracion for e in reversed(ciclo) if e.duracion is not None), None)
    ultimo = ciclo[-1]
    return {'estado': dict(ultimo.estado), 'fecha_alta': alta.fecha, 'duracion': duracion,
            'ids': dict(ultimo.ids), 'clave': ultimo.clave}


def _iguales(a, b):
    if a is None or b is None:
        return a is b
    return (a['estado'], a['fecha_alta'], a['duracion']) == (b['estado'], b['fecha_alta'], b['duracion'])


def _es_de_la_unidad(situacion, cierre):
    if situacion is None:
        return False
    unidad_id = situacion['ids'].get('unidad_id')
    if unidad_id:
        return cierre.unidad_id == unidad_id
    texto = situacion['estado'].get('unidad')
    return texto not in (None, '', SIN_DATO) and texto in (
        cierre.unidad_descripcion, cierre.unidad.descripcion)


def _corte(cierre):
    return timezone.localdate(cierre.fecha_declaracion)


# --------------------------------------------------------------------------
# 2. Qué cierres cambian
# --------------------------------------------------------------------------

def _cierres_candidatos(original, propuesto, aspirante_id):
    """Los cierres que PUEDEN verse afectados: los de las unidades por las que pasó
    la persona (antes o después de corregir) y aquellos en los que ya sale."""
    textos, ids = set(), set()
    for historico in (original, propuesto):
        for e in historico.eventos:
            for estado in (e.estado, e.antes):
                texto = estado.get('unidad')
                if texto not in (None, '', SIN_DATO):
                    textos.add(texto)
            if e.ids.get('unidad_id'):
                ids.add(e.ids['unidad_id'])
    con_la_persona = CierreContrato.objects.filter(
        aspirante_id_original=aspirante_id).values('cierre_id')
    return list(
        CierreUnidad.objects
        .filter(Q(unidad_descripcion__in=textos) | Q(unidad__descripcion__in=textos)
                | Q(unidad_id__in=ids) | Q(pk__in=con_la_persona))
        .select_related('unidad').order_by('anno', 'mes', 'unidad_orden_informe', 'pk'))


def cierres_afectados(original, propuesto):
    """`[(cierre, accion, situacion)]`: los cierres que la corrección cambia y qué
    les pasa (ENTRA, SALE o CORRIGE). `situacion` es la que debe quedar (None si la
    persona sale). Solo lee."""
    aspirante_id = propuesto.aspirante_id
    filas = set(CierreContrato.objects.filter(aspirante_id_original=aspirante_id)
                .values_list('cierre_id', flat=True))
    afectados = []
    for cierre in _cierres_candidatos(original, propuesto, aspirante_id):
        dia = _corte(cierre)
        antes = situacion_en(original, dia)
        despues = situacion_en(propuesto, dia)
        antes = antes if _es_de_la_unidad(antes, cierre) else None
        despues = despues if _es_de_la_unidad(despues, cierre) else None
        if _iguales(antes, despues):
            continue
        if despues is None:
            if cierre.pk in filas:
                afectados.append((cierre, SALE, None))
        else:
            afectados.append((cierre, CORRIGE if cierre.pk in filas else ENTRA, despues))
    return afectados


def meses_por_evento(historico):
    """`{clave del evento: [«Agosto 2026», …]}`: en qué meses cerrados sale la
    persona con lo que dejó cada evento. Es la nota «Vigente en N meses cerrados»
    del editor. Solo lee."""
    cierres = (CierreUnidad.objects
               .filter(contratos__aspirante_id_original=historico.aspirante_id)
               .distinct().order_by('anno', 'mes'))
    por_evento = {}
    for cierre in cierres:
        situacion = situacion_en(historico, _corte(cierre))
        if situacion is not None:
            etiquetas = por_evento.setdefault(situacion['clave'], [])
            if cierre.periodo.etiqueta not in etiquetas:
                etiquetas.append(cierre.periodo.etiqueta)
    return por_evento


def describir(afectados):
    """Las líneas para el resumen: «Cierre de Agosto 2026 (UEB Central): …»."""
    return ['Cierre de %s (%s): %s.' % (c.periodo.etiqueta, c.unidad_descripcion, TEXTO_ACCION[accion])
            for c, accion, _ in afectados]


# --------------------------------------------------------------------------
# 3. Escribir
# --------------------------------------------------------------------------

def _codigo_categoria(texto):
    """El histórico guarda la categoría con su nombre («Técnico»); la fotografía,
    con su código («TEC»)."""
    from nomencladores.models import NCargo
    if texto in (None, '', SIN_DATO):
        return ''
    for codigo, nombre in NCargo._meta.get_field('cat_ocupacional').choices:
        if nombre == texto:
            return codigo
    return texto[:20]


def _sin_dato(texto):
    return '' if texto in (None, SIN_DATO) else texto


def _volcar_historia(fila, situacion, cierre):
    """Escribe en la fila de la fotografía SOLO los datos que vienen del histórico.
    Si algo no se encuentra en el nomenclador, se conserva lo que la fila ya tenía
    cuando el texto coincide (no se inventa nada)."""
    from nomencladores.models import NCargo, NMotivoContrato, NTipoContrato

    estado, ids = situacion['estado'], situacion['ids']
    cargo = _sin_dato(estado.get('cargo'))
    if cargo != fila.ncargo_descripcion:
        ncargo = list(NCargo.objects.filter(descripcion=cargo)[:2])
        ncargo = ncargo[0] if len(ncargo) == 1 else None
        fila.ncargo_id_original = ncargo.pk if ncargo else None
        fila.puesto_clave = bool(ncargo.puesto_clave) if ncargo else False
    fila.ncargo_descripcion = cargo[:150]
    fila.departamento_descripcion = _sin_dato(estado.get('departamento'))[:150]
    fila.cat_ocupacional = _codigo_categoria(estado.get('cat_ocupacional'))
    fila.grupo_escala_nivel = _sin_dato(estado.get('grupo_escala'))[:8]
    fila.rol_tipo = _sin_dato(estado.get('rol'))[:50]

    tipo_texto = _sin_dato(estado.get('tipo_contrato'))
    tipo = (NTipoContrato.objects.filter(pk=ids['tipo_id']).first() if ids.get('tipo_id')
            else NTipoContrato.objects.filter(descripcion=tipo_texto).first())
    if tipo is not None:
        fila.tipo_id_original = tipo.pk
        fila.ocupa_plaza = bool(tipo.ocupa_plaza)
        fila.requiere_motivo = bool(tipo.requiere_motivo)
    elif tipo_texto != fila.tipo_descripcion:
        fila.tipo_id_original, fila.ocupa_plaza, fila.requiere_motivo = None, False, False
    fila.tipo_descripcion = tipo_texto[:150]

    motivo_texto = _sin_dato(estado.get('motivo'))
    if motivo_texto != fila.motivo_descripcion:
        fila.motivo_id_original = (NMotivoContrato.objects.filter(
            descripcion=motivo_texto, tipo_contrato_id=fila.tipo_id_original)
            .values_list('pk', flat=True).first() if motivo_texto else None)
    fila.motivo_descripcion = motivo_texto[:150]

    tridente = _sin_dato(estado.get('tridente'))
    fila.tridente_tipo = tridente.replace('Tridente', '').strip()[:50]
    fila.tipo_salario = {'Fijo': 'FIJ', 'Dinámico': 'DIN'}.get(estado.get('tipo_salario'), '')
    fila.salario = estado.get('salario')
    fila.fecha_alta = situacion['fecha_alta']
    if situacion['duracion'] is not None:
        fila.duracion = situacion['duracion']
    fila.cierre_cargo = (CierreCargo.objects.filter(
        cierre=cierre, ncargo_descripcion=fila.ncargo_descripcion,
        departamento_descripcion=fila.departamento_descripcion).order_by('pk').first())


def _fila_nueva(cierre, aspirante_id, modelo, expediente):
    """Una fila para alguien que no salía en el cierre. Lo que no es historia (nombre,
    formación, misión…) se copia de otra fotografía suya; si no tiene ninguna, de su
    contrato vigente o, al menos, de su ficha."""
    from bolsa.models import Aspirante
    from contratos.models import CAlta

    from .captura import _fila_de_contrato, _nombre_completo

    if modelo is not None:
        fila = copy.copy(modelo)
        fila._state = copy.copy(modelo._state)
        fila._state.adding = True
        fila._state.fields_cache = {}
        fila.pk = fila.id = None
        fila.cierre = cierre
    else:
        contrato = (CAlta.objects.filter(aspirante_id=aspirante_id)
                    .select_related('aspirante', 'aspirante__especialidad', 'cargo',
                                    'cargo__ncargo', 'tipo', 'motivo', 'tridente').first())
        if contrato is not None:
            fila = _fila_de_contrato(cierre, contrato, None)
        else:
            persona = Aspirante.objects.select_related('especialidad').get(pk=aspirante_id)
            fila = CierreContrato(
                cierre=cierre, aspirante_id_original=persona.pk, aspirante_vivo=persona,
                aspirante_nombre=_nombre_completo(persona), doc_identidad=persona.doc_identidad or '',
                sexo=persona.sexo or '', nivel_educ=persona.nivel_educ or '',
                especialidad_nombre=persona.especialidad.nombre if persona.especialidad else '',
                grado_cientifico=persona.grado_cientifico or '', titulo_oro=bool(persona.titulo_oro),
                fecha_nacimiento=persona.fecha_nacimiento)
    fila.no_expediente = expediente or fila.no_expediente
    # Si salía en la fotografía de ese mes, estaba activo.
    fila.aspirante_estado = 'ACTIVO'
    return fila


def _cuenta_plaza(fila):
    """Lo mismo que `cant_cubierta_real`: activo y en un tipo que ocupa plaza."""
    return fila is not None and fila.ocupa_plaza and fila.aspirante_estado == 'ACTIVO'


def _ajustar_plaza(cierre_cargo_id, delta):
    if not cierre_cargo_id or not delta:
        return
    cargo = CierreCargo.objects.get(pk=cierre_cargo_id)
    cargo.cant_cubierta = max(cargo.cant_cubierta + delta, 0)
    cargo.save(update_fields=['cant_cubierta'])


def _recalcular_totales(cierre):
    """Mismas cuentas que `captura.construir_fotografia`."""
    cargos = list(cierre.cargos.all())
    cierre.total_cargos = len(cargos)
    cierre.total_plazas_aprobadas = sum(c.cant_aprobada for c in cargos if c.en_plantilla)
    cierre.total_plazas_cubiertas = sum(c.cant_cubierta for c in cargos if c.en_plantilla)
    cierre.total_contratos = cierre.contratos.count()


def corregir_cierres(original, propuesto, motivo, usuario=None, expediente=''):
    """Aplica la corrección a los meses cerrados. Va DENTRO de la transacción del
    guardado del editor: si algo falla, no se guarda nada. Devuelve las líneas para
    el resumen y deja preparados los avisos (se envían al confirmar la transacción)."""
    from django.db import transaction

    afectados = cierres_afectados(original, propuesto)
    if not afectados:
        return []

    aspirante_id = propuesto.aspirante_id
    filas = list(CierreContrato.objects.filter(aspirante_id_original=aspirante_id)
                 .order_by('-cierre__anno', '-cierre__mes', '-pk'))
    por_cierre = {}
    for fila in filas:
        por_cierre.setdefault(fila.cierre_id, []).append(fila)
    modelo = filas[0] if filas else None   # la fotografía más reciente de la persona

    hoy = timezone.localdate().strftime('%d/%m/%Y')
    quien = (usuario.get_full_name() or usuario.username) if usuario else 'Sistema'
    nota = 'Corregido el %s por %s: %s' % (hoy, quien, motivo)

    for cierre, accion, situacion in afectados:
        suyas = por_cierre.get(cierre.pk, [])
        if accion == SALE:
            for fila in suyas:
                _ajustar_plaza(fila.cierre_cargo_id, -int(_cuenta_plaza(fila)))
                fila.delete()
        else:
            fila = suyas[0] if suyas else _fila_nueva(cierre, aspirante_id, modelo, expediente)
            antes_cargo = fila.cierre_cargo_id if fila.pk else None
            antes_cuenta = int(_cuenta_plaza(fila)) if fila.pk else 0
            _volcar_historia(fila, situacion, cierre)
            fila.save()
            _ajustar_plaza(antes_cargo, -antes_cuenta)
            _ajustar_plaza(fila.cierre_cargo_id, int(_cuenta_plaza(fila)))
            for sobrante in suyas[1:]:   # nunca debería haber dos; por si acaso
                _ajustar_plaza(sobrante.cierre_cargo_id, -int(_cuenta_plaza(sobrante)))
                sobrante.delete()
        _recalcular_totales(cierre)
        cierre.correcciones = (cierre.correcciones + '\n' + nota).strip()
        cierre.save(update_fields=['total_cargos', 'total_plazas_aprobadas', 'total_plazas_cubiertas',
                                   'total_contratos', 'correcciones'])

    cierres = [c for c, _, _ in afectados]
    transaction.on_commit(lambda: avisar_moderadores(cierres, nota))
    return describir(afectados)


def avisar_moderadores(cierres, nota):
    """Un aviso por cierre corregido a los moderadores de su unidad."""
    from django.contrib.contenttypes.models import ContentType

    from notificaciones.avisos import _registrar_notificacion
    from notificaciones.models import Notificacion
    from usuarios.models import CustomUser

    if not cierres:
        return
    tipo_ct = ContentType.objects.get_for_model(CierreUnidad)
    marca = timezone.now().strftime('%Y%m%d%H%M%S')
    for cierre in cierres:
        moderadores = CustomUser.objects.filter(es_moderador=True, unidades=cierre.unidad_id,
                                                is_active=True).distinct()
        for moderador in moderadores:
            _registrar_notificacion(
                tipo_ct=tipo_ct, object_id=str(cierre.pk), destinatario=moderador,
                codigo_regla=CODIGO_CIERRE_CORREGIDO, clave_extra=marca,
                defaults={
                    'titulo': 'Cierre de %s corregido' % cierre.periodo.etiqueta,
                    'mensaje': '%s (%s). %s' % (cierre.periodo.etiqueta, cierre.unidad_descripcion, nota),
                    'tipo': Notificacion.Tipo.EVENTO, 'estado': Notificacion.Estado.ACTIVA,
                    'unidad': cierre.unidad,
                })
