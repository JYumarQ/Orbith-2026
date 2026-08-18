"""Reglas de datos complementarios: útiles tenerlos completos, pero su ausencia NO
es un problema de calidad de datos que deba considerarse importante.

Por eso viven en su propio módulo, `MODULO_EXTRAS`, con `criticidad =
CRITICIDAD_INFORMATIVA` (la más baja): se siguen detectando y mostrando en Subsanación
—así RRHH puede completarlos si quiere—, pero `servicios.finalizar_ejecucion()` excluye
los códigos de este módulo del índice de salud general, para que la ausencia de un dato
"agradable pero no importante" nunca baje la nota de salud de los datos de la empresa.

Historial: `ASP-005` (móvil sin completar) vivía antes en `aspirantes.py` como regla de
criticidad Baja — RRHH decidió que el móvil ya no es un dato importante para la
empresa, así que se movió aquí en vez de retirarse: sigue detectando exactamente
igual, solo que ya no cuenta como un problema de calidad de datos. Su `codigo` NO
cambió al moverla: es la clave natural del hallazgo (ver `subsanacion/reglas/base.py`),
así que su historial sigue intacto.

`CAL-001` (móvil con formato inválido, exigía el prefijo «+53») y `CAL-002` (teléfono
fijo con formato inválido) SÍ se retiraron por completo — a diferencia del móvil, RRHH
no quiere ninguna validación de formato para estos campos, ni siquiera informativa. Sus
hallazgos históricos los archiva solo el próximo análisis completo
(`servicios.archivar_hallazgos_de_reglas_retiradas()`, ver el aviso en `servicios.py`).
Lo único que interesa de estos dos campos es que estén completos: el fijo tiene ahora
`EXT-002`, la misma comprobación de «vacío» que ya usa el móvil.
"""

from django.db.models import Q

from ..constantes import CRITICIDAD_INFORMATIVA, MODULO_EXTRAS, TAMANO_LOTE
from ..formato import referencia_trabajador
from .aspirantes import _campo_de_texto_vacio
from .base import HallazgoDetectado, ReglaBase


class ReglaExtras(ReglaBase):
    abstracta = True
    modulo = MODULO_EXTRAS
    modelo = 'bolsa.Aspirante'
    criticidad = CRITICIDAD_INFORMATIVA

    COLUMNAS_BASE = (
        'id', 'nombre', 'papellido', 'sapellido', 'doc_identidad', 'estado',
        'unidad_organizativa_id',
    )

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_trabajador(
            fila.get('nombre'), fila.get('papellido'),
            fila.get('sapellido'), fila.get('doc_identidad'))
        return f'{referencia} · {sufijo}'


class MovilPersonalVacio(ReglaExtras):
    codigo = 'ASP-005'
    nombre = 'Móvil personal sin completar'
    # Evaluable en caliente: O(1), solo un campo propio de la instancia.
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el trabajador tenga registrado un número de móvil personal. '
        'Es un dato útil de contacto, pero RRHH determinó que no es un dato '
        'importante para la empresa, así que no penaliza la salud de los datos.')
    causa_probable = (
        'El trabajador no facilitó un móvil al registrarse, o el dato llegará más '
        'adelante.')
    impacto = (
        'Sin un móvil registrado, Orbith no tiene ninguna vía rápida de contacto '
        'directo con el trabajador. No es obligatorio a nivel de formulario, y '
        'completarlo es opcional: RRHH ya no lo considera un dato importante.')
    solucion = 'Abra el trabajador y complete el móvil personal, si lo desea.'

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle='El trabajador no tiene registrado ningún móvil personal.',
            datos={'movil_personal': 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='movil_personal',
        )

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(Q(movil_personal__isnull=True) | Q(movil_personal=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield self._hallazgo(
                str(fila['id']), self.titulo_de(fila, 'sin móvil personal'),
                fila.get('unidad_organizativa_id'))

    def evaluar_instancia(self, aspirante):
        if not _campo_de_texto_vacio(aspirante.movil_personal):
            return None
        return [self._hallazgo(str(aspirante.pk), 'Sin móvil personal')]


class TelefonoFijoSinCompletar(ReglaExtras):
    codigo = 'EXT-002'
    nombre = 'Teléfono fijo sin completar'
    # Evaluable en caliente: O(1), solo un campo propio de la instancia. Mismo
    # criterio que ASP-005 (móvil): solo importa si está vacío, no su formato.
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el trabajador tenga registrado un número de teléfono fijo.')
    causa_probable = (
        'El trabajador no facilitó un teléfono fijo al registrarse, no tiene, o el '
        'dato llegará más adelante.')
    impacto = (
        'Sin un teléfono fijo registrado, Orbith tiene una vía de contacto menos '
        'con el trabajador. No es un dato importante para la empresa, así que no '
        'penaliza la salud de los datos.')
    solucion = 'Abra el trabajador y complete el teléfono fijo, si lo desea.'

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle='El trabajador no tiene registrado ningún teléfono fijo.',
            datos={'fijo_personal': 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='fijo_personal',
        )

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(Q(fijo_personal__isnull=True) | Q(fijo_personal=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield self._hallazgo(
                str(fila['id']), self.titulo_de(fila, 'sin teléfono fijo'),
                fila.get('unidad_organizativa_id'))

    def evaluar_instancia(self, aspirante):
        if not _campo_de_texto_vacio(aspirante.fijo_personal):
            return None
        return [self._hallazgo(str(aspirante.pk), 'Sin teléfono fijo')]


def _tallas_incompletas(tpantalon, tcamisa, tzapatos):
    """Pura: la usan `ejecutar()` y `evaluar_instancia()` sin repetir el criterio.

    `tzapatos` es un `IntegerField` (no texto), así que su vacío se comprueba con
    `is None` en vez de `_campo_de_texto_vacio()`. Devuelve la lista de etiquetas de
    las tallas que faltan — vacía si las tres están completas. Es una lista y no un
    booleano porque el detalle del hallazgo dice exactamente cuáles faltan.
    """
    faltantes = []
    if _campo_de_texto_vacio(tpantalon):
        faltantes.append('pantalón')
    if _campo_de_texto_vacio(tcamisa):
        faltantes.append('camisa/blusa')
    if tzapatos is None:
        faltantes.append('zapatos')
    return faltantes


class TallasSinCompletar(ReglaExtras):
    """Pantalón, camisa/blusa y zapatos cuentan como UN solo problema por trabajador
    (a diferencia de CTR-002/CTR-007, que usan `clave_extra` para separar sus
    variantes): aquí un único hallazgo basta para decir «faltan tallas», y su detalle
    enumera cuáles. Menos ruido en el listado que tres hallazgos por la misma persona.
    """

    codigo = 'EXT-001'
    nombre = 'Tallas incompletas'
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el trabajador tenga registradas sus tallas de pantalón, '
        'camisa/blusa y zapatos, para la gestión de la dotación de ropa y calzado.')
    causa_probable = (
        'El trabajador no facilitó sus tallas al registrarse, o el dato llegará '
        'más adelante.')
    impacto = (
        'Sin las tallas registradas, la gestión de dotación de ropa y calzado no '
        'puede planificarse para este trabajador. No es un dato importante para '
        'la empresa, así que no penaliza la salud de los datos.')
    solucion = 'Abra el trabajador y complete la talla o tallas que falten, si lo desea.'

    def _hallazgo(self, object_id, faltantes, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle=f'Al trabajador le falta(n) registrar: {", ".join(faltantes)}.',
            datos={'tallas_incompletas': ', '.join(faltantes)},
            unidad_organizativa_id=unidad_organizativa_id,
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + ('tpantalon', 'tcamisa', 'tzapatos')
        filas = (self.base_queryset()
                 .filter(Q(tpantalon__isnull=True) | Q(tpantalon='')
                         | Q(tcamisa__isnull=True) | Q(tcamisa='')
                         | Q(tzapatos__isnull=True))
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            faltantes = _tallas_incompletas(
                fila.get('tpantalon'), fila.get('tcamisa'), fila.get('tzapatos'))
            if not faltantes:
                continue
            yield self._hallazgo(
                str(fila['id']), faltantes,
                self.titulo_de(fila, f'tallas incompletas ({", ".join(faltantes)})'),
                fila.get('unidad_organizativa_id'))

    def evaluar_instancia(self, aspirante):
        faltantes = _tallas_incompletas(
            aspirante.tpantalon, aspirante.tcamisa, aspirante.tzapatos)
        if not faltantes:
            return None
        return [self._hallazgo(
            str(aspirante.pk), faltantes, f'Tallas incompletas ({", ".join(faltantes)})')]
