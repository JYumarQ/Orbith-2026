"""Orquestación del análisis y reconciliación de hallazgos.

=============================================================================
AVISO IMPORTANTE PARA QUIEN CONOZCA `informe_inteligente/motor.py`
=============================================================================
Allí, `_aplicar_alcance_por_rol()` filtra por las unidades del moderador DENTRO del
motor. Aquí eso sería un ERROR DE CORRECCIÓN, no una mejora de seguridad.

Motivo: la reconciliación marca como «corregido» todo hallazgo de una regla que ya no
se detecta. Si el barrido leyera solo una parte de la empresa, los hallazgos de las
unidades no leídas desaparecerían de la vista y el módulo los daría por resueltos
siendo falso.

Por tanto:
  * El barrido lee SIEMPRE toda la empresa y solo lo puede lanzar un administrador.
  * El alcance por rol se aplica al LEER el listado (en las vistas), usando el campo
    denormalizado `Hallazgo.unidad_organizativa`.

No mueva el filtro de rol a este archivo.
=============================================================================

Este módulo es el único que escribe en las tablas de Subsanación. Nunca escribe en un
modelo de negocio.
"""

import hashlib
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from .constantes import (
    CLAVES_MODULOS,
    ETIQUETA_MODULO,
    color_de_indice,
    LIMITE_HALLAZGOS_POR_REGLA,
    MINIMO_REGISTROS_PARA_PORCENTAJE,
    MINUTOS_EJECUCION_ABANDONADA,
    MODULOS,
    TAMANO_LOTE,
    VERSION_INDICE_SALUD,
)
from .contexto import ContextoAnalisis
from .models import EjecucionAnalisis, Hallazgo, RevisionHallazgo
from .reglas import obtener_reglas, reglas_por_modulo, total_reglas
from .signals import analisis_finalizado, hallazgo_revisado

logger = logging.getLogger(__name__)


class AnalisisEnCurso(Exception):
    """Ya hay un barrido en marcha. Lleva la ejecución para poder informar de cuándo empezó."""

    def __init__(self, ejecucion):
        self.ejecucion = ejecucion
        super().__init__('Ya hay un análisis en curso.')


# Campos que se refrescan cuando un hallazgo vuelve a detectarse.
_CAMPOS_REFRESCO = [
    'modulo', 'criticidad', 'titulo', 'detalle', 'datos', 'huella',
    'unidad_organizativa', 'ultima_deteccion', 'veces_detectado', 'ejecucion',
    'vigente', 'fecha_resolucion', 'resuelto_automaticamente',
    'estado', 'revisado_por', 'fecha_revision',
]

# Campos que se tocan cuando un hallazgo deja de detectarse.
_CAMPOS_RESOLUCION = ['vigente', 'fecha_resolucion', 'resuelto_automaticamente', 'estado']


# ---------------------------------------------------------------------------
# Huella
# ---------------------------------------------------------------------------

def calcular_huella(datos):
    """md5 de `datos`, para saber si un hallazgo sigue siendo *el mismo* hallazgo.

    Caso real que esto resuelve: el usuario marca «Falso positivo» en «salario
    guardado 4.560 / esperado 5.060» porque conoce una excepción. Meses después la
    escala cambia y el esperado pasa a 6.200. Ya NO es el mismo caso, y seguir
    silenciándolo sería peligroso: la huella distinta lo devuelve a Pendiente.

    Por eso `datos` no debe contener valores volátiles (fechas de ejecución,
    contadores): moverían la huella sin que el problema haya cambiado.
    """
    if not datos:
        return ''
    canonico = json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.md5(canonico.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Ciclo de vida de una ejecución
# ---------------------------------------------------------------------------

def cerrar_ejecuciones_abandonadas():
    """Marca como FALLIDA las ejecuciones que llevan demasiado tiempo «En curso».

    Ocurre cuando el usuario cierra el navegador a mitad de la cadena HTMX: no hay
    worker de fondo que las termine, así que se limpian aquí, de forma perezosa.
    """
    limite = timezone.now() - timedelta(minutes=MINUTOS_EJECUCION_ABANDONADA)
    abandonadas = EjecucionAnalisis.objects.filter(
        estado=EjecucionAnalisis.EN_CURSO, iniciada_en__lt=limite)
    cerradas = 0
    for ejecucion in abandonadas:
        ejecucion.estado = EjecucionAnalisis.FALLIDA
        ejecucion.terminada_en = timezone.now()
        ejecucion.errores = dict(ejecucion.errores or {})
        ejecucion.errores['_abandonada'] = (
            'El análisis se interrumpió antes de terminar (probablemente se cerró la '
            'página). No se marcó ningún hallazgo como corregido.')
        ejecucion.save(update_fields=['estado', 'terminada_en', 'errores'])
        cerradas += 1
    return cerradas


def obtener_ejecucion_en_curso():
    """Devuelve la ejecución en curso, o None. Antes limpia las abandonadas."""
    cerrar_ejecuciones_abandonadas()
    return EjecucionAnalisis.objects.filter(estado=EjecucionAnalisis.EN_CURSO).first()


def ultima_ejecucion_terminada():
    """La última ejecución con resultado. Es lo que lee el dashboard."""
    return (EjecucionAnalisis.objects
            .filter(estado__in=EjecucionAnalisis.ESTADOS_TERMINADOS)
            .first())


def iniciar_ejecucion(usuario=None, origen=EjecucionAnalisis.MANUAL, modulos=None):
    """Crea una ejecución nueva.

    Lanza `AnalisisEnCurso` si ya hay una en marcha. La comprobación se hace dos
    veces —consultando y capturando el IntegrityError— porque dos administradores
    pueden pulsar el botón a la vez: la UniqueConstraint de la base de datos es la
    que decide de verdad.
    """
    en_curso = obtener_ejecucion_en_curso()
    if en_curso is not None:
        raise AnalisisEnCurso(en_curso)

    solicitados = list(modulos) if modulos else list(CLAVES_MODULOS)
    try:
        return EjecucionAnalisis.objects.create(
            estado=EjecucionAnalisis.EN_CURSO,
            origen=origen,
            lanzada_por=usuario if (usuario and usuario.is_authenticated) else None,
            modulos_solicitados=solicitados,
            version_indice=VERSION_INDICE_SALUD,
        )
    except IntegrityError:
        # Otro proceso ganó la carrera contra la UniqueConstraint.
        en_curso = EjecucionAnalisis.objects.filter(
            estado=EjecucionAnalisis.EN_CURSO).first()
        raise AnalisisEnCurso(en_curso)


# ---------------------------------------------------------------------------
# Reconciliación (el corazón del módulo)
# ---------------------------------------------------------------------------

def reconciliar_regla(regla, ejecucion, contexto):
    """Ejecuta una regla y sincroniza sus hallazgos con la base de datos.

    Devuelve un diccionario con los contadores de lo que hizo.

    El paso de «desaparecidos» se acota SIEMPRE por `codigo_regla`. Es lo que hace
    correcto ejecutar el análisis por partes: si un módulo no corre, sus hallazgos no
    se tocan, porque la consulta nunca los alcanza.
    """
    modelo = regla.obtener_modelo()
    tipo = ContentType.objects.get_for_model(modelo, for_concrete_model=True)
    ahora = timezone.now()
    contexto.registrar_modelo(regla.modelo)

    # Todos los hallazgos que esta regla generó alguna vez (servido por
    # subs_hall_regla_vig). Se cargan de golpe: es una consulta, no N.
    existentes = {
        (hallazgo.object_id, hallazgo.clave_extra): hallazgo
        for hallazgo in Hallazgo.objects.filter(codigo_regla=regla.codigo)
    }

    detectadas = set()
    nuevos = []
    a_refrescar = []
    revisiones_pendientes = []   # (hallazgo, estado_anterior, estado_nuevo, nota)
    truncada = False
    contados = 0

    for detectado in regla.ejecutar(contexto):
        contados += 1
        if contados > LIMITE_HALLAZGOS_POR_REGLA:
            truncada = True
            break

        clave = (str(detectado.object_id or ''), detectado.clave_extra or '')
        detectadas.add(clave)
        huella = calcular_huella(detectado.datos)
        existente = existentes.get(clave)

        if existente is None:
            nuevos.append(Hallazgo(
                codigo_regla=regla.codigo,
                content_type=tipo,
                object_id=clave[0],
                clave_extra=clave[1],
                modulo=regla.modulo,
                criticidad=regla.criticidad,
                titulo=detectado.titulo[:255],
                detalle=detectado.detalle or '',
                datos=detectado.datos or {},
                huella=huella,
                unidad_organizativa_id=detectado.unidad_organizativa_id,
                vigente=True,
                ultima_deteccion=ahora,
                veces_detectado=1,
                ejecucion=ejecucion,
                estado=Hallazgo.PENDIENTE,
            ))
            continue

        # Persiste o reaparece: se refresca la instantánea.
        estado_anterior = existente.estado
        huella_cambio = bool(existente.huella) and existente.huella != huella

        existente.modulo = regla.modulo
        existente.criticidad = regla.criticidad
        existente.titulo = detectado.titulo[:255]
        existente.detalle = detectado.detalle or ''
        existente.datos = detectado.datos or {}
        existente.huella = huella
        existente.unidad_organizativa_id = detectado.unidad_organizativa_id
        existente.ultima_deteccion = ahora
        existente.veces_detectado = (existente.veces_detectado or 0) + 1
        existente.ejecucion = ejecucion
        existente.vigente = True
        existente.fecha_resolucion = None
        existente.resuelto_automaticamente = False

        # Política de estados al reaparecer, según lo acordado:
        nuevo_estado = None
        nota_automatica = ''
        if estado_anterior == Hallazgo.CORREGIDO:
            nuevo_estado = Hallazgo.PENDIENTE
            nota_automatica = (
                'El hallazgo volvió a detectarse, así que no estaba corregido de '
                'verdad. Se reabre automáticamente.')
        elif estado_anterior in Hallazgo.ESTADOS_SILENCIADOS and huella_cambio:
            nuevo_estado = Hallazgo.PENDIENTE
            nota_automatica = (
                'Los datos del hallazgo cambiaron respecto a cuando se silenció, así '
                'que ya no es el mismo caso. Se reabre automáticamente para que se '
                'revise de nuevo.')
        # Pendiente, En revisión, Ignorado y Falso positivo (con la misma huella)
        # conservan su estado: el usuario ya decidió sobre ellos.

        if nuevo_estado is not None:
            existente.estado = nuevo_estado
            existente.revisado_por = None
            existente.fecha_revision = None
            revisiones_pendientes.append(
                (existente, estado_anterior, nuevo_estado, nota_automatica))

        a_refrescar.append(existente)

    # --- Desaparecidos ---------------------------------------------------
    desaparecidos = []
    if not truncada:
        # Si la regla se truncó por el límite NO se puede saber si los que faltan
        # desaparecieron o simplemente no se llegó a ellos. Marcarlos como corregidos
        # sería mentir, así que se dejan intactos.
        for clave, existente in existentes.items():
            if clave in detectadas or not existente.vigente:
                continue
            estado_anterior = existente.estado
            existente.vigente = False
            existente.fecha_resolucion = ahora
            existente.resuelto_automaticamente = True
            if estado_anterior in Hallazgo.ESTADOS_ABIERTOS:
                existente.estado = Hallazgo.CORREGIDO
                revisiones_pendientes.append((
                    existente, estado_anterior, Hallazgo.CORREGIDO,
                    'Ya no se detecta. El dato fue corregido desde el formulario '
                    'correspondiente.'))
            # Un Ignorado / Falso positivo que desaparece conserva su estado: si el
            # problema vuelve, el usuario ya dictaminó y su historial lo explica.
            desaparecidos.append(existente)

    # --- Escritura en lotes ---------------------------------------------
    if nuevos:
        Hallazgo.objects.bulk_create(nuevos, batch_size=TAMANO_LOTE)
    if a_refrescar:
        Hallazgo.objects.bulk_update(a_refrescar, _CAMPOS_REFRESCO, batch_size=TAMANO_LOTE)
    if desaparecidos:
        Hallazgo.objects.bulk_update(desaparecidos, _CAMPOS_RESOLUCION, batch_size=TAMANO_LOTE)

    if revisiones_pendientes:
        RevisionHallazgo.objects.bulk_create([
            RevisionHallazgo(
                hallazgo=hallazgo, estado_anterior=anterior, estado_nuevo=nuevo,
                usuario=None, nota=nota, automatica=True)
            for hallazgo, anterior, nuevo, nota in revisiones_pendientes
        ], batch_size=TAMANO_LOTE)

        for hallazgo, anterior, nuevo, nota in revisiones_pendientes:
            hallazgo_revisado.send(
                sender=Hallazgo, hallazgo=hallazgo, estado_anterior=anterior,
                estado_nuevo=nuevo, usuario=None, nota=nota, automatica=True)

    return {
        'codigo': regla.codigo,
        'nuevos': len(nuevos),
        'persistentes': len(a_refrescar),
        'resueltos': len(desaparecidos),
        'truncada': truncada,
    }


def ejecutar_modulo(ejecucion, clave_modulo, contexto=None):
    """Ejecuta todas las reglas de una categoría. Es la unidad de trabajo del barrido.

    Cada regla va en su propia transacción: si una falla, se anota el error y el
    barrido CONTINÚA. Un fallo en la regla 27 no puede invalidar las 26 anteriores.
    Nunca se abre una transacción que envuelva el módulo entero: una transacción
    larga en PostgreSQL bloquea el VACUUM y mantiene locks mientras el resto de la
    plantilla sigue trabajando.
    """
    if clave_modulo not in CLAVES_MODULOS:
        raise ValueError(f'La categoría «{clave_modulo}» no existe.')

    contexto = contexto or ContextoAnalisis(ejecucion)
    reglas = obtener_reglas(modulo=clave_modulo)

    resumen = {
        'modulo': clave_modulo,
        'etiqueta': ETIQUETA_MODULO[clave_modulo],
        'reglas': 0,
        'nuevos': 0,
        'persistentes': 0,
        'resueltos': 0,
        'errores': {},
        'truncadas': [],
    }

    errores = dict(ejecucion.errores or {})

    for regla in reglas:
        try:
            with transaction.atomic():
                contadores = reconciliar_regla(regla, ejecucion, contexto)
        except Exception as exc:                        # noqa: BLE001
            logger.exception('Subsanación: falló la regla %s', regla.codigo)
            mensaje = f'{type(exc).__name__}: {exc}'[:500]
            errores[regla.codigo] = mensaje
            resumen['errores'][regla.codigo] = mensaje
            continue

        resumen['reglas'] += 1
        resumen['nuevos'] += contadores['nuevos']
        resumen['persistentes'] += contadores['persistentes']
        resumen['resueltos'] += contadores['resueltos']
        if contadores['truncada']:
            aviso = (f'La regla superó el límite de {LIMITE_HALLAZGOS_POR_REGLA:,} '
                     f'hallazgos; se guardaron los primeros.')
            errores[regla.codigo] = aviso
            resumen['truncadas'].append(regla.codigo)

    completados = list(ejecucion.modulos_completados or [])
    if clave_modulo not in completados:
        completados.append(clave_modulo)

    modelos = set(ejecucion.modelos_analizados or []) | contexto.modelos_analizados

    ejecucion.modulos_completados = completados
    ejecucion.modelos_analizados = sorted(modelos)
    ejecucion.reglas_ejecutadas = (ejecucion.reglas_ejecutadas or 0) + resumen['reglas']
    ejecucion.hallazgos_nuevos = (ejecucion.hallazgos_nuevos or 0) + resumen['nuevos']
    ejecucion.hallazgos_persistentes = (
        (ejecucion.hallazgos_persistentes or 0) + resumen['persistentes'])
    ejecucion.hallazgos_resueltos = (ejecucion.hallazgos_resueltos or 0) + resumen['resueltos']
    ejecucion.errores = errores
    ejecucion.save(update_fields=[
        'modulos_completados', 'modelos_analizados', 'reglas_ejecutadas',
        'hallazgos_nuevos', 'hallazgos_persistentes', 'hallazgos_resueltos', 'errores'])

    return resumen


def contar_registros(etiquetas_modelos):
    """Cuenta las filas de los modelos revisados, cada modelo UNA sola vez.

    Devuelve `(total, {clave_modulo: filas})`.

    Contar cada modelo una vez y no una vez por regla es importante: si se contara
    por regla, añadir reglas nuevas inflaría el denominador y el índice de salud
    subiría sin que la base de datos hubiera mejorado en nada.

    Es un COUNT(*) por modelo distinto, y se hace UNA vez al cerrar el análisis. El
    resultado se guarda en la ejecución para que el dashboard no tenga que repetirlo
    en cada carga de la página.
    """
    conteo_por_modelo = {}
    for etiqueta in etiquetas_modelos or []:
        try:
            app_label, nombre = etiqueta.split('.')
            modelo = apps.get_model(app_label, nombre)
        except (ValueError, LookupError):
            logger.warning('Subsanación: modelo «%s» no reconocido al contar filas.', etiqueta)
            continue
        conteo_por_modelo[etiqueta] = modelo._default_manager.count()

    por_modulo = {}
    for clave, reglas in reglas_por_modulo().items():
        etiquetas = {regla.modelo for regla in reglas}
        por_modulo[clave] = sum(conteo_por_modelo.get(e, 0) for e in etiquetas)

    return sum(conteo_por_modelo.values()), por_modulo


def contar_registros_afectados(modulo=None):
    """Cuántos REGISTROS DISTINTOS tienen algún hallazgo abierto.

    Se cuentan registros y no hallazgos, porque un mismo registro puede producir varios
    (un trabajador con diez movimientos genera diez hallazgos, y sigue siendo un
    trabajador). Los «Ignorado» y «Falso positivo» no cuentan: el usuario ya dictaminó.
    """
    consulta = Hallazgo.objects.filter(
        vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
    if modulo:
        consulta = consulta.filter(modulo=modulo)
    return consulta.values('content_type', 'object_id').distinct().count()


def indice_desde_afectados(afectados, registros):
    """La fórmula del índice, aislada para que el global y el de cada módulo usen la MISMA.

        indice = 100 × (1 − registros afectados / registros analizados)

    Es un porcentaje de registros limpios.

    Se llegó a esta fórmula tras comprobar sobre datos reales que la anterior
    —penalización por gravedad dividida entre el número de registros— se desbordaba:
    como un mismo registro puede generar varios hallazgos, la penalización superaba el
    número de registros y el índice quedaba pegado a cero, con lo que dejaba de servir
    para saber si la base mejora o empeora.

    Este índice no se satura nunca y no se desvirtúa al añadir reglas nuevas. La
    GRAVEDAD no entra en el porcentaje a propósito: se muestra aparte, en los contadores
    de Crítico, Alto, Medio y Bajo del dashboard, donde se lee mejor.
    """
    base = max(int(registros or 0), 1)
    limpios = max(base - int(afectados or 0), 0)
    return (Decimal(limpios * 100) / Decimal(base)).quantize(Decimal('0.01'))


def calcular_indice_salud(registros_analizados):
    """Índice de salud global, de 0 a 100."""
    return indice_desde_afectados(
        contar_registros_afectados(), registros_analizados)


def archivar_hallazgos_de_reglas_retiradas(ejecucion):
    """Archiva los hallazgos de reglas que ya no se ejecutan.

    Hace falta porque la reconciliación se acota SIEMPRE por `codigo_regla`: si una regla
    se retira del código (o se desactiva), su consulta no vuelve a ejecutarse nunca, así
    que sus hallazgos se quedarían vigentes para siempre, penalizando el índice de salud
    sin que nada pueda volver a comprobarlos.

    Solo se hace en un análisis COMPLETO. En uno parcial no hay forma de distinguir «la
    regla se retiró» de «la regla no se ejecutó esta vez», y archivar por error los
    hallazgos de las reglas que no corrieron sería justo el fallo que la reconciliación
    acotada por regla evita.

    No se marcan como «Corregido»: nadie corrigió nada. Se dejan con su estado y se
    archivan con una nota que explica que la regla dejó de existir.
    """
    solicitados = set(ejecucion.modulos_solicitados or [])
    completados = set(ejecucion.modulos_completados or [])
    if not solicitados >= set(CLAVES_MODULOS) or solicitados != completados:
        return 0

    codigos_vigentes = {regla.codigo for regla in obtener_reglas()}
    huerfanos = list(Hallazgo.objects
                     .filter(vigente=True)
                     .exclude(codigo_regla__in=codigos_vigentes))
    if not huerfanos:
        return 0

    ahora = timezone.now()
    for hallazgo in huerfanos:
        hallazgo.vigente = False
        hallazgo.fecha_resolucion = ahora
        # `resuelto_automaticamente` se queda en False a propósito: el hallazgo no se
        # resolvió, simplemente dejó de comprobarse.
        hallazgo.resuelto_automaticamente = False

    Hallazgo.objects.bulk_update(
        huerfanos, ['vigente', 'fecha_resolucion', 'resuelto_automaticamente'],
        batch_size=TAMANO_LOTE)

    RevisionHallazgo.objects.bulk_create([
        RevisionHallazgo(
            hallazgo=hallazgo, estado_anterior=hallazgo.estado,
            estado_nuevo=hallazgo.estado, usuario=None, automatica=True,
            nota=('La regla que lo detectaba se retiró del sistema, así que este '
                  'hallazgo ya no se comprueba. Se archiva sin darlo por corregido.'))
        for hallazgo in huerfanos
    ], batch_size=TAMANO_LOTE)

    logger.info('Subsanación: archivados %s hallazgos de reglas retiradas.', len(huerfanos))
    return len(huerfanos)


def finalizar_ejecucion(ejecucion):
    """Cierra la ejecución, calcula el índice de salud y emite la señal."""
    archivar_hallazgos_de_reglas_retiradas(ejecucion)
    ahora = timezone.now()

    total, por_modulo = contar_registros(ejecucion.modelos_analizados)
    ejecucion.registros_analizados = total
    ejecucion.registros_por_modulo = por_modulo
    ejecucion.hallazgos_vigentes = Hallazgo.objects.filter(vigente=True).count()
    ejecucion.indice_salud = calcular_indice_salud(total)
    ejecucion.terminada_en = ahora
    ejecucion.duracion_ms = max(
        0, int((ahora - ejecucion.iniciada_en).total_seconds() * 1000))

    completados = set(ejecucion.modulos_completados or [])
    solicitados = set(ejecucion.modulos_solicitados or [])
    if not completados:
        ejecucion.estado = EjecucionAnalisis.FALLIDA
    elif ejecucion.errores or (solicitados - completados):
        ejecucion.estado = EjecucionAnalisis.PARCIAL
    else:
        ejecucion.estado = EjecucionAnalisis.COMPLETA

    ejecucion.save(update_fields=[
        'registros_analizados', 'registros_por_modulo', 'hallazgos_vigentes',
        'indice_salud', 'terminada_en', 'duracion_ms', 'estado'])

    analisis_finalizado.send(sender=EjecucionAnalisis, ejecucion=ejecucion)
    return ejecucion


def ejecutar_analisis_completo(usuario=None, origen=EjecucionAnalisis.COMANDO, modulos=None):
    """Barrido completo en una sola llamada. La usa el comando de consola.

    Las vistas NO la usan: allí el barrido se trocea en una petición por categoría
    para no acercarse al timeout de Gunicorn.
    """
    ejecucion = iniciar_ejecucion(usuario=usuario, origen=origen, modulos=modulos)
    contexto = ContextoAnalisis(ejecucion)
    resumenes = []
    for clave in (ejecucion.modulos_solicitados or CLAVES_MODULOS):
        resumenes.append(ejecutar_modulo(ejecucion, clave, contexto=contexto))
    finalizar_ejecucion(ejecucion)
    return ejecucion, resumenes


# ---------------------------------------------------------------------------
# Estado de un hallazgo (lo único que el usuario escribe)
# ---------------------------------------------------------------------------

def cambiar_estado_hallazgo(hallazgo, nuevo_estado, usuario=None, nota=''):
    """Cambia el estado de un hallazgo y lo registra en el historial.

    Es la ÚNICA escritura que puede originar el usuario en este módulo, y solo toca
    tablas de Subsanación. Ningún dato de negocio se modifica aquí ni en ningún otro
    punto del módulo.

    Marcar un hallazgo como Ignorado o Falso positivo exige una nota. Sin ella, ese
    estado no dice nada: dentro de seis meses, ni el propio administrador que lo marcó
    recordaría por qué decidió silenciarlo, y un hallazgo silenciado sin motivo escrito
    es indistinguible de uno que nadie llegó a revisar.
    """
    nota = (nota or '').strip()

    estados_validos = dict(Hallazgo.ESTADOS)
    if nuevo_estado not in estados_validos:
        raise ValueError(f'El estado «{nuevo_estado}» no es válido.')

    if nuevo_estado in Hallazgo.ESTADOS_SILENCIADOS and not nota:
        raise ValueError(
            f'Para marcar un hallazgo como «{estados_validos[nuevo_estado]}» hace '
            f'falta explicar por qué en la observación.')

    estado_anterior = hallazgo.estado
    if estado_anterior == nuevo_estado and not nota:
        return hallazgo

    hallazgo.estado = nuevo_estado
    hallazgo.revisado_por = usuario if (usuario and usuario.is_authenticated) else None
    hallazgo.fecha_revision = timezone.now()
    if nota:
        hallazgo.nota = nota
    hallazgo.save(update_fields=['estado', 'revisado_por', 'fecha_revision', 'nota'])

    RevisionHallazgo.objects.create(
        hallazgo=hallazgo,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        usuario=hallazgo.revisado_por,
        nota=nota,
        automatica=False,
    )

    hallazgo_revisado.send(
        sender=Hallazgo, hallazgo=hallazgo, estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado, usuario=hallazgo.revisado_por, nota=nota,
        automatica=False)

    return hallazgo


# ---------------------------------------------------------------------------
# Datos para el dashboard (siempre de lectura, nunca dispara un análisis)
# ---------------------------------------------------------------------------

def resumen_por_criticidad():
    """{criticidad: nº de hallazgos vigentes y abiertos}."""
    conteos = (Hallazgo.objects
               .filter(vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
               .values('criticidad')
               .annotate(total=Count('id')))
    return {fila['criticidad']: fila['total'] for fila in conteos}


def resumen_por_modulo(ejecucion=None):
    """Estado de cada categoría, incluidas las que están limpias o sin reglas todavía.

    El porcentaje se calcula EN VIVO con la MISMA fórmula que el índice global, usando
    como denominador el recuento de filas que guardó la última ejecución. Así el
    dashboard no lanza un COUNT(*) por modelo en cada carga, y a la vez el porcentaje
    reacciona en el momento en que el usuario marca un hallazgo como ignorado o
    corregido, sin tener que volver a analizar.

    Una categoría sin hallazgos aparece al 100 %; una que aún no tiene reglas aparece
    marcada como tal en vez de desaparecer, para que no parezca que está sana cuando
    en realidad no se ha comprobado.
    """
    # Nº de hallazgos abiertos por categoría (para el contador) …
    conteos = (Hallazgo.objects
               .filter(vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
               .values('modulo')
               .annotate(total=Count('id')))
    hallazgos_por_modulo = {fila['modulo']: fila['total'] for fila in conteos}

    # … y nº de REGISTROS DISTINTOS afectados (para el porcentaje). Son dos cifras
    # distintas a propósito: un trabajador con diez movimientos da diez hallazgos y un
    # solo registro afectado.
    afectados = (Hallazgo.objects
                 .filter(vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
                 .values('modulo', 'content_type', 'object_id')
                 .distinct())
    afectados_por_modulo = {}
    for fila in afectados:
        afectados_por_modulo[fila['modulo']] = afectados_por_modulo.get(fila['modulo'], 0) + 1

    denominadores = (ejecucion.registros_por_modulo or {}) if ejecucion else {}
    reglas = reglas_por_modulo()

    filas = []
    for clave, etiqueta, icono in MODULOS:
        total_hallazgos = hallazgos_por_modulo.get(clave, 0)
        registros_afectados = afectados_por_modulo.get(clave, 0)
        registros = denominadores.get(clave, 0)
        numero_reglas = len(reglas.get(clave, []))

        # Tres situaciones distintas, y cada una se dice de forma distinta en el
        # dashboard en lugar de forzar todas a un número:
        #   * sin reglas      -> todavía no se comprueba nada (un 100 % sería falso)
        #   * pocas filas     -> el porcentaje no significa nada (ver la constante)
        #   * caso normal     -> porcentaje
        if not numero_reglas:
            situacion = 'sin_reglas'
            indice = None
        elif registros < MINIMO_REGISTROS_PARA_PORCENTAJE:
            situacion = 'sin_porcentaje'
            indice = None
        else:
            situacion = 'normal'
            indice = indice_desde_afectados(registros_afectados, registros)

        filas.append({
            'clave': clave,
            'etiqueta': etiqueta,
            'icono': icono,
            'total': total_hallazgos,
            'afectados': registros_afectados,
            'reglas': numero_reglas,
            'registros': registros,
            'situacion': situacion,
            'indice': indice,
            'color': color_de_indice(indice) if indice is not None else 'gris',
        })
    return filas


def tendencia_indice(limite=12):
    """Evolución del índice de salud, de la más antigua a la más reciente.

    Solo se devuelven ejecuciones de la MISMA versión de fórmula que la actual. Mezclar
    versiones en una gráfica compararía valores que no son comparables: para eso existe
    `EjecucionAnalisis.version_indice`.
    """
    ejecuciones = list(EjecucionAnalisis.objects
                       .filter(estado__in=EjecucionAnalisis.ESTADOS_TERMINADOS,
                               indice_salud__isnull=False,
                               version_indice=VERSION_INDICE_SALUD)
                       .order_by('-iniciada_en')[:limite])
    ejecuciones.reverse()

    return [{
        'fecha': ejecucion.iniciada_en,
        'indice': float(ejecucion.indice_salud),
        'hallazgos': ejecucion.hallazgos_vigentes,
        'registros': ejecucion.registros_analizados,
    } for ejecucion in ejecuciones]


def estadisticas_por_regla():
    """Cuántos hallazgos abiertos tiene cada regla, con sus metadatos.

    Se listan TODAS las reglas del catálogo, también las que no han encontrado nada: una
    regla con cero hallazgos es información útil (se comprobó y está limpio), no una
    fila que deba desaparecer.
    """
    conteos = dict(Hallazgo.objects
                   .filter(vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
                   .values_list('codigo_regla')
                   .annotate(total=Count('id'))
                   .values_list('codigo_regla', 'total'))

    filas = []
    for regla in obtener_reglas():
        filas.append({
            'codigo': regla.codigo,
            'nombre': regla.nombre,
            'modulo': regla.modulo,
            'etiqueta_modulo': ETIQUETA_MODULO.get(regla.modulo, regla.modulo),
            'criticidad': regla.criticidad,
            'etiqueta_criticidad': regla.etiqueta_criticidad,
            'color': regla.color,
            'total': conteos.get(regla.codigo, 0),
        })

    # De más hallazgos a menos, y a igualdad, lo más grave primero.
    filas.sort(key=lambda fila: (-fila['total'], fila['criticidad'], fila['codigo']))
    return filas


def estadisticas_por_estado():
    """Reparto de los hallazgos vigentes por estado, incluidos los que el usuario cerró."""
    conteos = dict(Hallazgo.objects
                   .filter(vigente=True)
                   .values_list('estado')
                   .annotate(total=Count('id'))
                   .values_list('estado', 'total'))

    return [{
        'estado': valor,
        'etiqueta': etiqueta,
        'total': conteos.get(valor, 0),
        'color': Hallazgo.COLOR_POR_ESTADO.get(valor, 'secondary'),
    } for valor, etiqueta in Hallazgo.ESTADOS]


def historial_revisiones(limite=None):
    """Historial de revisiones, lo más reciente primero.

    Es el historial PROPIO del módulo, no la Auditoría del sistema: aquí solo se
    registra lo que pasa con los hallazgos, nunca cambios en datos de negocio.
    """
    consulta = (RevisionHallazgo.objects
                .select_related('usuario', 'hallazgo')
                .order_by('-fecha'))
    if limite:
        consulta = consulta[:limite]
    return consulta


def hay_reglas_disponibles():
    return total_reglas() > 0
