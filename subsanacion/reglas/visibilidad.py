"""Reglas de visibilidad: registros que están en la base de datos y no se ven.

Orbith no tiene ningún campo «oculto». Estos registros son invisibles por una razón
distinta y más difícil de detectar: los listados filtran por estado, y hay
combinaciones de datos que no encajan en ningún filtro y por tanto no aparecen en
ninguna pantalla. Nadie los ve, nadie los corrige, y siguen contando para la
plantilla y los informes.
"""

from django.apps import apps
from django.db.models import Count, Exists, F, OuterRef, Q

from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_CRITICA,
    CRITICIDAD_MEDIA,
    MODULO_OCULTOS,
    TAMANO_LOTE,
)
from ..formato import referencia_trabajador
from .base import HallazgoDetectado, ReglaBase


class ReglaTrabajadorOculto(ReglaBase):
    """Base de las reglas que cruzan el estado del trabajador con sus contratos.

    Se comprueban las combinaciones de `Aspirante.estado` y existencia de `CAlta` que
    dejan al trabajador fuera de todas las pantallas, o en la pantalla equivocada.
    """

    abstracta = True
    modulo = MODULO_OCULTOS
    modelo = 'bolsa.Aspirante'

    COLUMNAS = (
        'id', 'nombre', 'papellido', 'sapellido', 'doc_identidad', 'estado',
        'unidad_organizativa_id', 'unidad_organizativa__descripcion',
    )

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_trabajador(
            fila.get('nombre'), fila.get('papellido'),
            fila.get('sapellido'), fila.get('doc_identidad'))
        return f'{referencia} · {sufijo}'

    def con_contrato(self, valor=True):
        """Trabajadores que tienen (o no) al menos un contrato de alta.

        `~Exists()` en lugar de un LEFT JOIN con IS NULL: PostgreSQL corta la subconsulta
        en cuanto encuentra la primera fila, y no hay riesgo de duplicar filas si un
        trabajador tuviera varios contratos.
        """
        CAlta = apps.get_model('contratos', 'CAlta')
        return (self.base_queryset()
                .annotate(tiene_contrato=Exists(
                    CAlta.objects.filter(aspirante_id=OuterRef('pk'))))
                .filter(tiene_contrato=valor))


class BajaConContratoActivo(ReglaTrabajadorOculto):
    codigo = 'VIS-002'
    nombre = 'Trabajador dado de baja con contrato activo'
    criticidad = CRITICIDAD_CRITICA

    descripcion = (
        'Busca trabajadores marcados como BAJA que siguen teniendo un contrato de alta.')
    causa_probable = (
        'Se cambió el estado del trabajador a BAJA sin eliminar su contrato de alta, o el '
        'proceso de baja se interrumpió a medias.')
    impacto = (
        'La persona aparece a la vez en Bajas y en Contratos, y sigue ocupando plaza en la '
        'plantilla. Los informes de trabajadores activos la incluyen o la excluyen según el '
        'criterio de cada uno, así que las cifras dejan de cuadrar entre sí.')
    solucion = (
        'Decida cuál es la situación real. Si la persona ya no trabaja en la entidad, '
        'complete su baja desde el contrato, para que el contrato de alta desaparezca y la '
        'plaza quede libre. Si sigue trabajando, cambie su estado a ACTIVO.')

    def ejecutar(self, contexto):
        filas = (self.con_contrato(True)
                 .filter(estado='BAJA')
                 .values(*self.COLUMNAS)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'está de baja y conserva contrato activo'),
                detalle=(
                    'Su estado es BAJA pero tiene un contrato de alta vigente, así que '
                    'aparece a la vez en Bajas y en Contratos, y sigue ocupando plaza.'),
                datos={
                    'estado_registrado': 'BAJA',
                    'tiene_contrato_de_alta': 'Sí',
                    'unidad_organizativa': (
                        fila.get('unidad_organizativa__descripcion') or 'Sin asignar'),
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class AspiranteYaContratado(ReglaTrabajadorOculto):
    codigo = 'VIS-003'
    nombre = 'Aspirante que ya tiene contrato y sigue en la bolsa'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Busca personas en estado ASPIRANTE que ya tienen un contrato de alta.')
    causa_probable = (
        'Orbith pone el estado en ACTIVO al crear un contrato. Si sigue en ASPIRANTE es '
        'porque el estado se revirtió a mano después, o porque el contrato se creó sin '
        'pasar por el formulario.')
    impacto = (
        'La persona sigue apareciendo en la bolsa de aspirantes como si estuviera '
        'disponible, con el riesgo de que se la proponga para otra plaza estando ya '
        'contratada. Y los informes que cuentan trabajadores por estado no la cuentan.')
    solucion = (
        'Abra el trabajador y cambie su estado a ACTIVO, que es lo que corresponde a quien '
        'tiene un contrato de alta vigente.')

    def ejecutar(self, contexto):
        filas = (self.con_contrato(True)
                 .filter(estado='ASPIRANTE')
                 .values(*self.COLUMNAS)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'sigue como aspirante teniendo contrato'),
                detalle=(
                    'Tiene un contrato de alta vigente pero su estado sigue siendo '
                    'ASPIRANTE, así que continúa apareciendo en la bolsa como disponible.'),
                datos={
                    'estado_registrado': 'ASPIRANTE',
                    'estado_que_corresponde': 'ACTIVO',
                    'tiene_contrato_de_alta': 'Sí',
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class TrabajadorActivoSinContrato(ReglaBase):
    """Aspirante en estado ACTIVO que no tiene ningún contrato de alta.

    Por qué es invisible, verificado en el código:

      * `bolsa/views.py` — `AspiranteListView` filtra `estado='ASPIRANTE'`, así que no
        sale en Aspirantes.
      * `bolsa/views.py` — `BajaListView` filtra `estado='BAJA'`, así que no sale en Bajas.
      * `contratos/views.py` — `ContratoListView` lista filas de `CAlta`, y este
        trabajador no tiene ninguna, así que no sale en Contratos.

    Resultado: la persona existe en la base de datos y no aparece en ninguna pantalla
    del sistema.
    """

    codigo = 'VIS-001'
    nombre = 'Trabajador activo sin contrato (invisible en el sistema)'
    modulo = MODULO_OCULTOS
    criticidad = CRITICIDAD_CRITICA
    modelo = 'bolsa.Aspirante'

    descripcion = (
        'Busca personas marcadas como ACTIVO que no tienen ningún contrato de alta. '
        'No aparecen en Aspirantes (solo lista los que están en estado ASPIRANTE), ni '
        'en Bajas (solo los que están en BAJA), ni en Contratos (no tienen contrato).')
    causa_probable = (
        'Lo más habitual es que el contrato se borrara sin que el estado del trabajador '
        'volviera a BAJA, o que el estado se cambiara a mano o por importación sin '
        'crear el contrato. El estado ACTIVO lo pone Orbith al crear un contrato, así '
        'que ACTIVO sin contrato siempre indica que algo se quedó a medias.')
    impacto = (
        'La persona es inalcanzable desde la interfaz: no se puede consultar, corregir '
        'ni dar de baja porque no aparece en ninguna lista. Además su carnet de '
        'identidad sigue ocupado (es único), así que no se puede volver a registrar, y '
        'los informes que cuentan trabajadores por estado la incluyen sin que haya '
        'forma de ver quién es.')
    solucion = (
        'Decida cuál de las dos situaciones es la real y arréglela desde el formulario '
        'del trabajador, al que puede llegar con el botón de abajo: si la persona '
        'trabaja en la entidad, créele el contrato de alta que le falta; si ya no '
        'trabaja, cambie su estado a BAJA y registre la baja correspondiente.')

    def ejecutar(self, contexto):
        # apps.get_model dentro de ejecutar(), no a nivel de módulo: evita imports
        # circulares y respeta que en AppConfig.ready() los modelos aún no están listos.
        CAlta = apps.get_model('contratos', 'CAlta')

        # `~Exists()` en lugar de un LEFT JOIN con IS NULL: PostgreSQL corta la
        # subconsulta en cuanto encuentra la primera fila, y no hay riesgo de duplicar
        # filas si un trabajador tuviera varios contratos.
        filas = (self.base_queryset()
                 .filter(estado='ACTIVO')
                 .annotate(tiene_contrato=Exists(
                     CAlta.objects.filter(aspirante_id=OuterRef('pk'))))
                 .filter(tiene_contrato=False)
                 .values('id', 'nombre', 'papellido', 'sapellido', 'doc_identidad',
                         'unidad_organizativa_id',
                         'unidad_organizativa__descripcion')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            referencia = referencia_trabajador(
                fila.get('nombre'), fila.get('papellido'),
                fila.get('sapellido'), fila.get('doc_identidad'))

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · activo sin contrato, no aparece en ninguna pantalla',
                detalle=(
                    'Está marcado como ACTIVO pero no tiene ningún contrato de alta. '
                    'Por eso no aparece en Aspirantes, ni en Bajas, ni en Contratos: '
                    'hoy no hay forma de llegar a esta persona desde la interfaz.'),
                datos={
                    'estado_registrado': 'ACTIVO',
                    'contratos_de_alta': 0,
                    'unidad_organizativa': (
                        fila.get('unidad_organizativa__descripcion') or 'Sin asignar'),
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )
