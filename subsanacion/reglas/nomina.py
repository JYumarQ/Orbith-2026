"""Reglas de nómina e históricos: salario cacheado y cadena de movimientos."""

from decimal import Decimal

from django.apps import apps
from django.db.models import F, Window
from django.db.models.functions import Lag

from ..calculos import COLUMNAS_SALARIO, construir_indice_salarios, salario_esperado
from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_INFORMATIVA,
    CRITICIDAD_MEDIA,
    MODULO_NOMINA,
    TAMANO_LOTE,
)
from ..formato import referencia_contrato, referencia_trabajador
from .base import HallazgoDetectado, ReglaBase


def _evaluar_salarios(contexto):
    """Recorre los contratos UNA vez y clasifica los problemas de salario.

    Se guarda en el memo del contexto para que las dos reglas de salario compartan el
    recorrido: cada una filtra la lista que le toca en lugar de volver a recorrer la
    tabla entera.
    """
    def calcular():
        CAlta = apps.get_model('contratos', 'CAlta')
        indice = contexto.memo('indice_salarios', construir_indice_salarios)

        discrepantes = []
        incalculables = []

        filas = (CAlta.objects
                 .values(*COLUMNAS_SALARIO)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            esperado = salario_esperado(fila, indice)

            if esperado is None:
                # No se puede calcular: es un problema distinto, no una discrepancia.
                incalculables.append(fila)
                continue

            # `esperado` es float y `salario_actual` es Decimal. Comparar directamente
            # daría falsos positivos por la representación binaria del float, así que
            # se normaliza a dos decimales antes de comparar.
            esperado_decimal = Decimal(str(esperado)).quantize(Decimal('0.01'))
            guardado = fila.get('salario_actual')

            if guardado is None or guardado.quantize(Decimal('0.01')) != esperado_decimal:
                fila = dict(fila)
                fila['_esperado'] = esperado_decimal
                discrepantes.append(fila)

        return {'discrepantes': discrepantes, 'incalculables': incalculables}

    return contexto.memo('evaluacion_salarios', calcular)


class ReglaSalario(ReglaBase):
    abstracta = True
    modulo = MODULO_NOMINA
    modelo = 'contratos.CAlta'

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_contrato(
            fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
            fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'),
            fila.get('no_expediente'))
        return f'{referencia} · {sufijo}'


class SalarioDesincronizado(ReglaSalario):
    codigo = 'SAL-001'
    nombre = 'Salario guardado distinto al de la escala'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Compara el salario que tiene guardado el contrato con el que le corresponde '
        'según la escala salarial, el grupo del cargo, el rol de pago y el tridente.')
    causa_probable = (
        'El salario guardado solo se recalcula al guardar el contrato desde el '
        'formulario. Si se modificó la escala salarial, el cargo o el rol sin volver a '
        'guardar los contratos afectados, el valor guardado se queda con el anterior. '
        'También ocurre con importaciones y con cambios hechos directamente en la base '
        'de datos.')
    impacto = (
        'Informe Inteligente y todos los informes económicos leen el salario guardado, '
        'no lo recalculan, así que arrastran la cifra equivocada. Con salarios es un '
        'problema que puede llegar a tener consecuencias legales.')
    solucion = (
        'Abra el contrato y púlselo Guardar: Orbith recalcula el salario al guardar. '
        'Compruebe antes que el cargo, el rol de pago y el tridente son los correctos, '
        'porque si el error está en ellos el salario volverá a salir mal.')

    def ejecutar(self, contexto):
        evaluacion = _evaluar_salarios(contexto)

        for fila in evaluacion['discrepantes']:
            guardado = fila.get('salario_actual')
            esperado = fila['_esperado']
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila,
                    f'salario {guardado if guardado is not None else "vacío"} '
                    f'frente a {esperado} según la escala'),
                detalle=(
                    'El salario guardado en el contrato no coincide con el que le '
                    'corresponde según la escala salarial vigente.'),
                datos={
                    'cargo': fila.get('cargo__ncargo__descripcion') or 'Sin cargo',
                    'tipo_de_salario': (
                        'Dinámico (por escala)' if fila.get('tipo_salario') == 'DIN'
                        else 'Fijo (básico del cargo)'),
                    'salario_guardado': (
                        str(guardado) if guardado is not None else 'Vacío'),
                    'salario_segun_la_escala': str(esperado),
                    'diferencia': (
                        str(esperado - guardado) if guardado is not None
                        else 'No se puede calcular'),
                },
                unidad_organizativa_id=fila.get('cargo__departamento__unidad_organizativa_id'),
            )


class SalarioNoCalculable(ReglaSalario):
    codigo = 'SAL-002'
    nombre = 'Contrato sin datos suficientes para calcular el salario'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Busca contratos en los que Orbith no puede determinar el salario porque falta '
        'algún dato de la cadena cargo → grupo de escala → rol → tridente.')
    causa_probable = (
        'Lo más habitual es un contrato de salario dinámico sin tridente asignado, o un '
        'contrato sin cargo. También ocurre cuando la escala salarial no tiene una fila '
        'para la combinación de grupo, rol y tridente del contrato.')
    impacto = (
        'El trabajador aparece sin salario en todos los informes económicos. No es que '
        'cobre cero: es que Orbith no sabe cuánto le corresponde, así que cualquier '
        'total que lo incluya está incompleto.')
    solucion = (
        'Abra el contrato y complete lo que falte según la lista de abajo: normalmente '
        'el cargo o el tridente. Si están completos, el problema está en la escala '
        'salarial: revise en Parámetros Generales que exista la combinación de grupo de '
        'escala, rol y tridente que usa este contrato.')

    def ejecutar(self, contexto):
        evaluacion = _evaluar_salarios(contexto)

        for fila in evaluacion['incalculables']:
            dinamico = fila.get('tipo_salario') == 'DIN'
            sin_cargo = fila.get('cargo_id') is None
            sin_tridente = fila.get('tridente_id') is None

            if sin_cargo:
                falta = 'No tiene cargo asignado'
            elif dinamico and sin_tridente:
                falta = 'Es de salario dinámico y no tiene tridente'
            elif dinamico:
                falta = 'No existe esa combinación en la escala salarial'
            else:
                falta = 'El cargo no tiene salario básico'

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'sin salario calculable — {falta.lower()}'),
                detalle=f'Orbith no puede determinar el salario de este contrato. {falta}.',
                datos={
                    'motivo': falta,
                    'cargo': fila.get('cargo__ncargo__descripcion') or 'Sin cargo',
                    'tipo_de_salario': (
                        'Dinámico (por escala)' if dinamico else 'Fijo (básico del cargo)'),
                    'tridente': 'Sin asignar' if sin_tridente else 'Asignado',
                    'salario_guardado': (
                        str(fila.get('salario_actual'))
                        if fila.get('salario_actual') is not None else 'Vacío'),
                },
                unidad_organizativa_id=fila.get('cargo__departamento__unidad_organizativa_id'),
            )


class ReglaMovimientos(ReglaBase):
    abstracta = True
    modulo = MODULO_NOMINA
    modelo = 'contratos.TMovimiento'

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_trabajador(
            fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
            fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'))
        expediente = fila.get('no_expediente')
        if expediente:
            referencia = f'{referencia} · Expediente {expediente}'
        return f'{referencia} · {sufijo}'


class CadenaDeSalariosRota(ReglaMovimientos):
    """El salario anterior de un movimiento no coincide con el nuevo del anterior."""

    codigo = 'MOV-001'
    nombre = 'Cadena de salarios del histórico rota'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Recorre el histórico de cada trabajador en orden y comprueba que el salario '
        'anterior de cada movimiento coincida con el salario nuevo del movimiento que '
        'lo precede.')
    causa_probable = (
        'Se creó un movimiento a mano sin partir del último, se borró un movimiento '
        'intermedio de la cadena, o se modificó el salario del contrato sin generar el '
        'movimiento correspondiente.')
    impacto = (
        'El histórico deja de ser una secuencia coherente, así que no sirve como prueba '
        'de la evolución salarial del trabajador. Cualquier certificación o reclamación '
        'basada en él sería contradictoria.')
    solucion = (
        'Revise el histórico del trabajador desde su contrato y localice el salto. '
        'Corrija el contrato de alta y genere el movimiento que falte. Los movimientos '
        'no se editan directamente: son el registro de lo que ocurrió.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(aspirante__isnull=False)
                 .annotate(salario_previo=Window(
                     expression=Lag('salario_nuevo'),
                     partition_by=[F('aspirante_id')],
                     # El desempate por `id` NO es opcional. `Meta.ordering` de
                     # TMovimiento es solo por fecha_efectiva, que no es un orden total
                     # (dos movimientos pueden ser del mismo día). Sin desempate, Lag()
                     # sería no determinista y esta regla reportaría hallazgos distintos
                     # en cada análisis, moviendo la huella y reabriendo hallazgos ya
                     # revisados sin motivo.
                     order_by=[F('fecha_efectiva').asc(), F('id').asc()],
                 ))
                 # Filtrar sobre una función de ventana requiere Django 4.2 o superior;
                 # el proyecto está en 5.2 y el ORM envuelve la consulta en una
                 # subconsulta automáticamente. No lo "simplifique" moviendo el filtro
                 # antes del annotate: dejaría de funcionar.
                 .exclude(salario_previo__isnull=True)
                 .exclude(salario_anterior=F('salario_previo'))
                 .values('id', 'no_expediente', 'fecha_efectiva', 'tipo_movimiento',
                         'salario_anterior', 'salario_nuevo', 'salario_previo',
                         'cargo_anterior', 'cargo_nuevo',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'unidad_nueva_fk_id', 'unidad_anterior_fk_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            declarado = fila.get('salario_anterior')
            real = fila.get('salario_previo')
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila,
                    f'movimiento del {fila["fecha_efectiva"]:%d/%m/%Y} parte de '
                    f'{declarado} y el anterior terminó en {real}'),
                detalle=(
                    f'El movimiento declara que el salario anterior era {declarado}, '
                    f'pero el movimiento que le precede dejó el salario en {real}. '
                    f'La cadena del histórico está rota en este punto.'),
                datos={
                    'fecha_efectiva': fila['fecha_efectiva'].strftime('%d/%m/%Y'),
                    'tipo_de_movimiento': fila.get('tipo_movimiento') or '—',
                    'salario_anterior_declarado': str(declarado),
                    'salario_real_del_movimiento_previo': str(real),
                    'salario_nuevo': str(fila.get('salario_nuevo')),
                    'cargo_nuevo': fila.get('cargo_nuevo') or '—',
                },
                unidad_organizativa_id=(
                    fila.get('unidad_nueva_fk_id') or fila.get('unidad_anterior_fk_id')),
            )


# Los movimientos de baja se crean DELIBERADAMENTE sin contrato: véase
# `contratos/views.py`, donde la creación del movimiento de baja pasa `contrato=None`
# porque el contrato se borra inmediatamente después. Es el diseño del histórico
# inmutable, no un defecto, así que estas reglas los excluyen.
#
# Se compara por el texto porque `TMovimiento.tipo_movimiento` es un CharField libre,
# sin `choices`. Si algún día ese literal cambia en views.py, hay que cambiarlo aquí.
TIPO_MOVIMIENTO_BAJA = 'Baja'


class MovimientoDesconectadoDeSuContrato(ReglaMovimientos):
    """Movimiento sin contrato cuando el contrato SÍ existe.

    Esta regla se redefinió tras analizar los datos. La versión anterior reportaba todo
    movimiento con `contrato` en blanco, y eso incluía los 21 movimientos de baja, que
    están así a propósito: el 100 % de los movimientos de tipo «Baja» se crean sin
    contrato porque el contrato se borra justo después. Eran falsos positivos por
    construcción.

    Lo que sí es un problema real, y lo que detecta ahora, son los movimientos que NO son
    de baja y han perdido el enlace: el código que los crea sí asigna el contrato, así
    que si está en blanco es porque el contrato al que apuntaban se borró y se volvió a
    contratar reutilizando el mismo número de expediente.
    """

    codigo = 'MOV-002'
    nombre = 'Movimiento del histórico desconectado de su contrato'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Busca movimientos que no son de baja y han perdido el enlace con su contrato, o '
        'que no tienen trabajador asociado. Los movimientos de baja se excluyen: Orbith '
        'los crea sin contrato a propósito, porque el contrato desaparece al darse la '
        'baja.')
    causa_probable = (
        'El trabajador fue dado de baja —lo que borra su contrato— y después se volvió a '
        'contratar reutilizando el mismo número de expediente. El contrato nuevo es otra '
        'fila, así que los movimientos anteriores se quedaron apuntando al que ya no '
        'existe.')
    impacto = (
        'Esos movimientos no aparecen al abrir el histórico del trabajador desde su '
        'contrato, aunque sigan contando en el listado de movimientos de nómina. Es '
        'información que existe y a la que ya no se llega por el camino normal, así que '
        'el histórico que se consulta parece más corto de lo que realmente es.')
    solucion = (
        'Estos movimientos no se editan desde ningún formulario: son el registro de lo '
        'que ocurrió. Compruebe en el listado de movimientos de nómina, buscando por el '
        'número de expediente, que el histórico completo del trabajador está ahí. Si '
        'necesita que vuelva a aparecer desde el contrato, un administrador tiene que '
        'reasociarlo, y conviene revisar el proceso de recontratación para que no se '
        'repita.')

    def ejecutar(self, contexto):
        from django.db.models import Q

        filas = (self.base_queryset()
                 # Se excluyen las bajas: están sin contrato por diseño.
                 .exclude(tipo_movimiento__iexact=TIPO_MOVIMIENTO_BAJA)
                 .filter(Q(contrato__isnull=True) | Q(aspirante__isnull=True))
                 .values('id', 'no_expediente', 'fecha_efectiva', 'tipo_movimiento',
                         'contrato_id', 'aspirante_id',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'unidad_nueva_fk_id', 'unidad_anterior_fk_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            sin_aspirante = fila.get('aspirante_id') is None

            if sin_aspirante:
                # Sin trabajador el movimiento es irrecuperable: no hay forma de saber a
                # quién pertenece. Hoy no ocurre en la base, pero se deja como red de
                # seguridad porque el campo admite nulos.
                clave = 'sin_aspirante'
                que_falta = 'No tiene trabajador asociado'
                expediente = fila.get('no_expediente')
                titulo = 'Movimiento sin trabajador'
                if expediente:
                    titulo = f'{titulo} · Expediente {expediente}'
                titulo = f'{titulo} · no se puede saber a quién pertenece'
            else:
                clave = 'sin_contrato'
                que_falta = 'Perdió el enlace con su contrato'
                titulo = self.titulo_de(
                    fila, 'movimiento desconectado de su contrato')

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra=clave,
                titulo=titulo,
                detalle=(
                    f'{que_falta}. Por eso no aparece al abrir el histórico del '
                    f'trabajador desde su contrato.'),
                datos={
                    'fecha_efectiva': (
                        fila['fecha_efectiva'].strftime('%d/%m/%Y')
                        if fila.get('fecha_efectiva') else '—'),
                    'tipo_de_movimiento': fila.get('tipo_movimiento') or '—',
                    'expediente': fila.get('no_expediente') or '—',
                    'que_falta': que_falta,
                },
                unidad_organizativa_id=(
                    fila.get('unidad_nueva_fk_id') or fila.get('unidad_anterior_fk_id')),
            )


class MovimientoAnteriorAlAlta(ReglaMovimientos):
    codigo = 'MOV-003'
    nombre = 'Movimiento con fecha anterior al alta del contrato'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Un movimiento no puede tener efecto antes de que el contrato al que '
        'pertenece haya empezado.')
    causa_probable = (
        'Se registró el movimiento con una fecha efectiva equivocada, o se '
        'corrigió después la fecha de alta del contrato sin revisar los '
        'movimientos que ya se habían generado.')
    impacto = (
        'El histórico del trabajador queda con un movimiento que, según las '
        'fechas, ocurrió antes de que empezara el contrato al que pertenece. '
        'Cualquier informe que ordene por fecha efectiva presenta una secuencia '
        'que no pudo haber ocurrido así.')
    solucion = (
        'Verifique la fecha efectiva del movimiento y la fecha de alta del '
        'contrato; corrija la que esté equivocada. Los movimientos no se editan '
        'desde ningún formulario, así que si la fecha del movimiento es la '
        'incorrecta, contacte al administrador de la base de datos.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(contrato__isnull=False,
                         contrato__fecha_alta__isnull=False,
                         fecha_efectiva__lt=F('contrato__fecha_alta'))
                 .values('id', 'no_expediente', 'fecha_efectiva', 'tipo_movimiento',
                         'contrato__fecha_alta',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'unidad_nueva_fk_id', 'unidad_anterior_fk_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            efectiva = fila['fecha_efectiva']
            alta = fila['contrato__fecha_alta']
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila, f'movimiento del {efectiva:%d/%m/%Y} es anterior al alta '
                          f'del {alta:%d/%m/%Y}'),
                detalle=(
                    f'El movimiento tiene fecha efectiva {efectiva:%d/%m/%Y}, pero '
                    f'el contrato al que pertenece empezó el {alta:%d/%m/%Y}: el '
                    f'movimiento no pudo ocurrir antes de que existiera el contrato.'),
                datos={
                    'fecha_efectiva_del_movimiento': efectiva.strftime('%d/%m/%Y'),
                    'fecha_de_alta_del_contrato': alta.strftime('%d/%m/%Y'),
                    'tipo_de_movimiento': fila.get('tipo_movimiento') or '—',
                },
                unidad_organizativa_id=(
                    fila.get('unidad_nueva_fk_id') or fila.get('unidad_anterior_fk_id')),
            )


# MOV-004 («solicitud posterior a la fecha efectiva») estaba en el catálogo original
# y se llegó a implementar, pero se retiró tras medir los datos reales: los 47 casos
# candidatos mostraban `fecha_solicitud > fecha_efectiva` en el 100 % de las filas, sin
# una sola excepción en sentido contrario. Un patrón tan uniforme no es ruido de
# captura, es la semántica real del dato: el propio código de creación del movimiento
# de baja (`contratos/views.py`, comentario «Corrigiendo el error de fechas») deja
# constancia de que estos dos campos ya se confundieron una vez en el pasado, y para
# «Alta Inicial» y «Movimiento de Nómina» todo indica que `fecha_solicitud` registra
# cuándo se formalizó en papel un cambio que ya estaba en vigor, no una solicitud
# previa. Implementar la regla con la dirección que yo había asumido habría repetido
# el error de VIS-004: 47 falsos positivos por dar por buena una lectura no verificada
# del esquema. Se documenta como pendiente hasta que alguien que conozca el proceso
# administrativo real confirme qué dirección es la correcta.


class BajaAnteriorAlAlta(ReglaBase):
    codigo = 'MOV-005'
    nombre = 'Baja con fecha anterior a la del alta'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_ALTA
    modelo = 'contratos.CBaja'

    descripcion = (
        'La fecha de baja de un trabajador no puede ser anterior a la fecha en '
        'que fue dado de alta en ese mismo contrato.')
    causa_probable = (
        'Se intercambiaron las fechas de alta y baja al registrar la baja, o se '
        'copió por error la fecha de un contrato anterior del mismo trabajador.')
    impacto = (
        'El histórico de bajas queda con una secuencia imposible: el trabajador '
        'aparece dado de baja antes de haber sido contratado. Los informes que '
        'calculan la antigüedad o la duración real del vínculo laboral quedan '
        'mal calculados.')
    solucion = (
        'Revise el expediente de baja y corrija la fecha que esté equivocada, '
        'la de alta o la de baja, según corresponda.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(fecha_alta__isnull=False, fecha_baja__isnull=False,
                         fecha_baja__lt=F('fecha_alta'))
                 .values('id', 'no_expediente', 'fecha_alta', 'fecha_baja',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'cargo__departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            referencia = referencia_contrato(
                fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
                fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'),
                fila.get('no_expediente'))
            alta = fila['fecha_alta']
            baja = fila['fecha_baja']
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=(f'{referencia} · baja del {baja:%d/%m/%Y} anterior al alta '
                        f'del {alta:%d/%m/%Y}'),
                detalle=(
                    f'La baja está fechada el {baja:%d/%m/%Y}, antes de que el '
                    f'alta ({alta:%d/%m/%Y}) hubiera ocurrido.'),
                datos={
                    'fecha_de_alta': alta.strftime('%d/%m/%Y'),
                    'fecha_de_baja': baja.strftime('%d/%m/%Y'),
                },
                unidad_organizativa_id=fila.get(
                    'cargo__departamento__unidad_organizativa_id'),
            )


class ContratoSinMovimientos(ReglaBase):
    codigo = 'MOV-006'
    nombre = 'Contrato sin ningún movimiento registrado'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_INFORMATIVA
    modelo = 'contratos.CAlta'

    descripcion = (
        'Señala los contratos que todavía no tienen ningún movimiento en su '
        'histórico de nómina. No es necesariamente un error: un contrato recién '
        'creado es normal que aún no tenga movimientos.')
    causa_probable = (
        'El contrato es reciente y no ha tenido cambios de cargo, salario o '
        'unidad desde que se creó, o los movimientos que debieron generarse no '
        'se registraron.')
    impacto = (
        'Es informativo: sirve para localizar contratos cuyo histórico está '
        'vacío y decidir si corresponde a que son nuevos o a que se olvidó '
        'registrar algún movimiento.')
    solucion = (
        'Si el contrato ha tenido cambios que no se ven aquí, revíselo y genere '
        'el movimiento correspondiente desde el formulario de movimiento de '
        'nómina. Si es un contrato reciente sin cambios, no requiere ninguna '
        'acción.')

    def ejecutar(self, contexto):
        # `trazabilidad` es el related_name de TMovimiento.contrato.
        filas = (self.base_queryset()
                 .filter(trazabilidad__isnull=True)
                 .values('id', 'no_expediente', 'fecha_alta',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'cargo__departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            referencia = referencia_contrato(
                fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
                fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'),
                fila.get('no_expediente'))
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · sin ningún movimiento en el histórico',
                detalle=(
                    'El contrato no tiene ningún movimiento registrado en su '
                    'histórico de nómina.'),
                datos={
                    'fecha_de_alta': (
                        fila['fecha_alta'].strftime('%d/%m/%Y')
                        if fila.get('fecha_alta') else '—'),
                    'movimientos_registrados': 0,
                },
                unidad_organizativa_id=fila.get(
                    'cargo__departamento__unidad_organizativa_id'),
            )
