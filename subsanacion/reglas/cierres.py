"""Reglas del módulo de Cierres.

El estado de cada unidad ya está calculado y materializado en
`cierres.EstadoCierreUnidad`, así que esta regla no recalcula nada: lee esa
tabla, que es exactamente para lo que existe.

POR QUÉ NO ES UNA DUPLICIDAD DEL AVISO QUE YA HAY
--------------------------------------------------
`cierres.servicios.procesar_barrido()` ya envía notificaciones a las unidades
desactualizadas. Pero es una **acción manual** del Administrador —hay que
acordarse de pulsar el botón— y una notificación se lee y desaparece.

Un hallazgo de Subsanación es otra cosa: persiste hasta que se resuelve, sale en
el panel sin que nadie lo lance, se puede silenciar con motivo y queda en el
histórico. Son dos superficies distintas para el mismo hecho, igual que CTR-016
convive con la validación del formulario de contrato.
"""

from ..constantes import CRITICIDAD_ALTA, MODULO_CONFIGURACION, TAMANO_LOTE
from .base import HallazgoDetectado, ReglaBase


class UnidadSinDeclararElCierre(ReglaBase):
    """Unidades que se pasaron de plazo sin declarar su cierre mensual.

    DOS EXCLUSIONES, las mismas que aplica el barrido de avisos:

    * Las Direcciones Principales no declaran: su estado se deriva del de sus
      hijas, así que reclamarles un cierre sería pedirles algo que
      estructuralmente no pueden hacer.
    * Las unidades que nunca declararon no tienen obligación todavía. Una unidad
      recién creada aparecería como incumplidora desde el primer día.
    """

    codigo = 'CIE-001'
    nombre = 'Unidad que no declaró su cierre mensual'
    modulo = MODULO_CONFIGURACION
    criticidad = CRITICIDAD_ALTA
    modelo = 'strorganizativa.UnidadOrganizativa'

    descripcion = (
        'Busca las unidades organizativas cuyo plazo para declarar el cierre del '
        'mes ya venció sin que lo declararan.')
    causa_probable = (
        'Nadie de esa unidad entró a declarar dentro de la ventana mensual. El '
        'aviso del módulo de Cierres solo se envía cuando un Administrador lanza '
        'el barrido a mano, así que puede pasar desapercibido.')
    impacto = (
        'Sin cierre no hay fotografía de ese mes: la unidad queda FUERA de todos '
        'los informes históricos de ese período, y sus cifras no se pueden '
        'reconstruir después. El total de la empresa sale incompleto.')
    solucion = (
        'Abra el módulo de Cierres y declare la información al día de esa unidad. '
        'Si el mes ya pasó, declárelo igualmente: es la única forma de que la '
        'unidad aparezca en los informes de ese período.')

    def ejecutar(self, contexto):
        from cierres.models import EstadoUnidad

        estados = (self.obtener_modelo()._default_manager
                   .select_related('estado_cierre', 'tipo')
                   .filter(estado_cierre__estado=EstadoUnidad.DESACTUALIZADA)
                   .exclude(estado_cierre__primer_cierre__isnull=True)
                   .exclude(tipo__es_principal=True)
                   .iterator(chunk_size=TAMANO_LOTE))

        for unidad in estados:
            estado = unidad.estado_cierre
            periodo = estado.periodo_pendiente
            if periodo is None:
                continue

            yield HallazgoDetectado(
                object_id=str(unidad.pk),
                # El período forma parte de la clave: si la unidad se pone al día
                # con agosto pero sigue debiendo septiembre, es otro hallazgo.
                clave_extra=periodo.clave,
                titulo=f'{unidad.descripcion} · sin declarar el cierre de {periodo.etiqueta}',
                detalle=(
                    f'La unidad no declaró su cierre de {periodo.etiqueta} y el '
                    f'plazo ya venció, así que queda fuera de los informes '
                    f'históricos de ese mes.'),
                # `meses_pendientes` NO entra en `datos`: crece cada mes que pasa y
                # movería la huella del hallazgo, devolviendo a Pendiente uno ya
                # silenciado sin que el problema haya cambiado.
                datos={
                    'unidad': unidad.descripcion,
                    'periodo_sin_declarar': periodo.etiqueta,
                    'estado': 'Desactualizada',
                },
                unidad_organizativa_id=unidad.pk,
            )
