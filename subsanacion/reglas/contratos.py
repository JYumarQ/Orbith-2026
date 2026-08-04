"""Reglas de integridad de los contratos de alta."""

from django.db.models import Count, F, Q

from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_BAJA,
    CRITICIDAD_CRITICA,
    CRITICIDAD_MEDIA,
    MODULO_CONTRATOS,
    TAMANO_LOTE,
)
from ..formato import referencia_contrato, referencia_trabajador
from .base import HallazgoDetectado, ReglaBase


class ReglaContratos(ReglaBase):
    """Base común de las reglas de contratos. No se registra."""

    abstracta = True
    modulo = MODULO_CONTRATOS
    modelo = 'contratos.CAlta'

    # Columnas que necesita cualquier regla de contratos para redactar el título de
    # forma buscable y para denormalizar la unidad organizativa. Se piden con
    # `.values()` en lugar de hidratar instancias: una fila es un diccionario de unas
    # pocas claves, no tres objetos relacionados construidos en memoria.
    COLUMNAS_BASE = (
        'id',
        'no_expediente',
        'aspirante__nombre',
        'aspirante__papellido',
        'aspirante__sapellido',
        'aspirante__doc_identidad',
        'aspirante__unidad_organizativa_id',
        'cargo__departamento__unidad_organizativa_id',
    )

    @staticmethod
    def unidad_de(fila):
        """Unidad organizativa del contrato.

        Se toma primero la del cargo, que es la real; si el contrato no tiene cargo
        (justo el caso de CTR-001) se usa la del trabajador para que el hallazgo no
        quede sin unidad y siga siendo visible para el moderador de esa unidad.
        """
        return (fila.get('cargo__departamento__unidad_organizativa_id')
                or fila.get('aspirante__unidad_organizativa_id'))

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_contrato(
            fila.get('aspirante__nombre'),
            fila.get('aspirante__papellido'),
            fila.get('aspirante__sapellido'),
            fila.get('aspirante__doc_identidad'),
            fila.get('no_expediente'),
        )
        return f'{referencia} · {sufijo}'


class ContratoSinCargo(ReglaContratos):
    codigo = 'CTR-001'
    nombre = 'Contrato sin cargo asignado'
    criticidad = CRITICIDAD_CRITICA

    descripcion = (
        'Busca contratos de alta que no tienen ningún cargo de plantilla asignado.')
    causa_probable = (
        'El contrato se creó antes de que existiera el cargo en la plantilla, o el '
        'cargo se reasignó y quedó vacío. También ocurre cuando el contrato se '
        'importó desde otra fuente sin completar todos los datos.')
    impacto = (
        'Sin cargo no se puede calcular el salario por escala, el trabajador no ocupa '
        'plaza en la plantilla y no aparece en los informes que agrupan por cargo, '
        'categoría ocupacional o unidad organizativa (incluido el Anexo 14).')
    solucion = (
        'Abra el contrato y asigne el cargo de plantilla que corresponde. Si el cargo '
        'todavía no existe, créelo primero en el Gestor de Plantilla. Al guardar el '
        'contrato, Orbith recalcula el salario y el conteo de plazas.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(cargo__isnull=True)
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'sin cargo asignado'),
                detalle=(
                    'El contrato no tiene ningún cargo de plantilla asignado, así que '
                    'Orbith no puede determinar su salario ni la plaza que ocupa.'),
                datos={
                    'expediente': fila.get('no_expediente') or '—',
                    'cargo_asignado': 'Ninguno',
                },
                unidad_organizativa_id=self.unidad_de(fila),
            )


class MotivoIncoherenteConTipo(ReglaContratos):
    """Dos problemas distintos sobre la misma pareja de campos.

    Se resuelven en una sola regla porque comparten causa, impacto y solución, y se
    distinguen con `clave_extra`: así el usuario puede ignorar uno y atender el otro
    sobre el mismo contrato sin que se pisen en la base de datos.
    """

    codigo = 'CTR-002'
    nombre = 'Motivo de contrato incoherente con el tipo'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Comprueba dos cosas: que un tipo de contrato que exige motivo lo tenga, y '
        'que el motivo indicado pertenezca de verdad a ese tipo de contrato.')
    causa_probable = (
        'El tipo de contrato se cambió después de haber elegido el motivo, y el '
        'motivo anterior se quedó. También ocurre si se marcó «Requiere motivo» en un '
        'tipo de contrato que ya tenía contratos creados sin él.')
    impacto = (
        'El contrato queda con una combinación que la aplicación no habría permitido '
        'crear hoy. Los informes que agrupan por motivo de contratación cuentan mal, y '
        'el modelo impreso del contrato puede citar una base legal que no corresponde.')
    solucion = (
        'Abra el contrato y elija un motivo de la lista del tipo de contrato actual. '
        'Si el tipo es el equivocado, corrija primero el tipo y después el motivo.')

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'tipo__descripcion',
            'motivo__descripcion',
            'motivo__tipo_contrato__descripcion',
        )

        # (a) El tipo exige motivo y no lo hay.
        faltantes = (self.base_queryset()
                     .filter(tipo__requiere_motivo=True, motivo__isnull=True)
                     .values(*columnas)
                     .iterator(chunk_size=TAMANO_LOTE))

        for fila in faltantes:
            tipo = fila.get('tipo__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra='motivo_ausente',
                titulo=self.titulo_de(fila, f'sin motivo, y el tipo «{tipo}» lo exige'),
                detalle=(
                    f'El tipo de contrato «{tipo}» está configurado como «Requiere '
                    f'motivo», pero este contrato no tiene ninguno.'),
                datos={
                    'tipo_de_contrato': tipo,
                    'motivo_registrado': 'Ninguno',
                    'problema': 'El tipo de contrato exige un motivo',
                },
                unidad_organizativa_id=self.unidad_de(fila),
            )

        # (b) Hay motivo, pero pertenece a otro tipo de contrato.
        # Se exige `tipo__isnull=False` a propósito: si el contrato no tiene tipo, la
        # comparación en SQL daría NULL (desconocido) y el resultado del `.exclude()`
        # sería confuso. Ese caso es otro problema distinto («contrato sin tipo»), que
        # tendrá su propia regla.
        incoherentes = (self.base_queryset()
                        .filter(tipo__isnull=False, motivo__isnull=False)
                        .exclude(motivo__tipo_contrato=F('tipo'))
                        .values(*columnas)
                        .iterator(chunk_size=TAMANO_LOTE))

        for fila in incoherentes:
            tipo = fila.get('tipo__descripcion') or '—'
            motivo = fila.get('motivo__descripcion') or '—'
            tipo_del_motivo = fila.get('motivo__tipo_contrato__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra='motivo_incoherente',
                titulo=self.titulo_de(
                    fila, f'motivo «{motivo}» no pertenece al tipo «{tipo}»'),
                detalle=(
                    f'El contrato es de tipo «{tipo}», pero su motivo «{motivo}» '
                    f'pertenece al tipo «{tipo_del_motivo}».'),
                datos={
                    'tipo_de_contrato': tipo,
                    'motivo_registrado': motivo,
                    'tipo_al_que_pertenece_el_motivo': tipo_del_motivo,
                },
                unidad_organizativa_id=self.unidad_de(fila),
            )


class ContratoSinTipo(ReglaContratos):
    codigo = 'CTR-003'
    nombre = 'Contrato sin tipo de contrato'
    criticidad = CRITICIDAD_ALTA

    descripcion = 'Busca contratos que no tienen asignado ningún tipo de contrato.'
    causa_probable = (
        'El campo es opcional a nivel de base de datos (se dejó así para no romper '
        'la migración inicial del sistema), así que una importación o un contrato '
        'creado en los primeros tiempos de Orbith puede haberlo dejado vacío.')
    impacto = (
        'El tipo de contrato determina si exige motivo, si ocupa plaza en la '
        'plantilla y si es un adiestramiento. Sin él, esas comprobaciones no se '
        'pueden hacer y el contrato queda fuera de los informes que agrupan por '
        'tipo de contratación.')
    solucion = 'Abra el contrato y asigne el tipo de contrato que corresponde.'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(tipo__isnull=True)
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'sin tipo de contrato'),
                detalle='El contrato no tiene ningún tipo de contrato asignado.',
                datos={'expediente': fila.get('no_expediente') or '—'},
                unidad_organizativa_id=self.unidad_de(fila),
            )


class ContratoSinFechaAlta(ReglaContratos):
    codigo = 'CTR-004'
    nombre = 'Contrato sin fecha de contratación'
    criticidad = CRITICIDAD_ALTA

    descripcion = 'Busca contratos sin fecha de alta registrada.'
    causa_probable = (
        'El campo es opcional a nivel de base de datos, así que quedó vacío en una '
        'importación o al crear el contrato fuera del formulario habitual.')
    impacto = (
        'La fecha de alta es la base para calcular el vencimiento del contrato '
        '(fecha_alta + duracion) y para ordenar el histórico del trabajador. '
        'Sin ella, Orbith no puede avisar de contratos por vencer ni situar '
        'correctamente el contrato en la línea de tiempo del trabajador.')
    solucion = 'Abra el contrato y registre la fecha en que el trabajador fue contratado.'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(fecha_alta__isnull=True)
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'sin fecha de contratación'),
                detalle='El contrato no tiene registrada la fecha en que se firmó el alta.',
                datos={'expediente': fila.get('no_expediente') or '—'},
                unidad_organizativa_id=self.unidad_de(fila),
            )


class MotivoSinDuracion(ReglaContratos):
    codigo = 'CTR-005'
    nombre = 'Contrato con motivo pero sin duración'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Cuando un contrato tiene un motivo de contratación registrado, debe tener '
        'también su duración en meses.')
    causa_probable = (
        'Se completó el motivo del contrato pero no se rellenó la duración, o la '
        'duración se borró después sin quitar el motivo.')
    impacto = (
        'Sin duración, Orbith no puede calcular la fecha de vencimiento del '
        'contrato (fecha_alta + duracion), así que este contrato no aparecerá '
        'en los avisos de contratos próximos a vencer aunque tenga un motivo que '
        'normalmente implica un plazo definido.')
    solucion = 'Abra el contrato y complete la duración en meses.'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(motivo__isnull=False, duracion__isnull=True)
                 .values(*self.COLUMNAS_BASE, 'motivo__descripcion')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            motivo = fila.get('motivo__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'motivo «{motivo}» sin duración'),
                detalle=(
                    f'El contrato tiene el motivo «{motivo}» registrado, pero no '
                    f'tiene duración, así que no se puede calcular cuándo vence.'),
                datos={'motivo_registrado': motivo, 'duracion': 'Vacía'},
                unidad_organizativa_id=self.unidad_de(fila),
            )


class ContratoSinRegistroMilitar(ReglaContratos):
    codigo = 'CTR-006'
    nombre = 'Contrato sin registro militar'
    criticidad = CRITICIDAD_MEDIA

    descripcion = 'Busca contratos sin el campo de registro militar completado.'
    causa_probable = (
        'El campo es opcional a nivel de base de datos, así que puede quedar vacío '
        'si no se completó al crear el contrato.')
    impacto = (
        'El registro militar (MTT, Imprescindible, BPD o No Incorporado) es un '
        'dato que se exige en el modelo impreso del contrato y en los informes '
        'que lo agrupan por esta condición.')
    solucion = (
        'Abra el contrato y seleccione la condición militar que corresponde al '
        'trabajador.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(Q(reg_militar__isnull=True) | Q(reg_militar=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'sin registro militar'),
                detalle='El contrato no tiene completado el campo de registro militar.',
                datos={'expediente': fila.get('no_expediente') or '—'},
                unidad_organizativa_id=self.unidad_de(fila),
            )


def _grado_cientifico_sin_reflejar(grado, maestria, doctorado):
    """Pura: recibe valores escalares, no un dict ni una instancia.

    La usan `ejecutar()` (con valores de `.values()`) y `evaluar_instancia()` (con
    atributos de la instancia real) para que la condición nunca pueda divergir entre
    el barrido periódico y la alerta en caliente. Devuelve una lista de
    `(clave_extra, etiqueta, campo)` — vacía si no hay problema.
    """
    problemas = []
    if grado == 'MC' and not (maestria or 0):
        problemas.append(('maestria_vacia', 'Máster', 'campo_maestria'))
    if grado == 'DC' and not (doctorado or 0):
        problemas.append(('doctorado_vacio', 'Doctor', 'campo_doctorado'))
    return problemas


class GradoCientificoSinReflejar(ReglaContratos):
    """Un mismo problema con dos variantes: máster y doctor.

    Se agrupan en una sola clase porque comparten causa, impacto y solución; se
    distinguen con `clave_extra` para poder revisar cada variante por separado.
    """

    codigo = 'CTR-007'
    nombre = 'Grado científico no reflejado en el contrato'
    criticidad = CRITICIDAD_MEDIA
    # Evaluable en caliente: es O(1) — un único salto de FK ya accesible
    # (`instancia.aspirante`) más dos campos propios de la instancia.
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el contrato refleje en el campo correspondiente (máster o '
        'doctorado) el grado científico que tiene registrado el trabajador.')
    causa_probable = (
        'El trabajador obtuvo el grado científico después de crear el contrato, o '
        'se registró su grado científico en la ficha personal sin actualizar el '
        'contrato con el porcentaje o los datos correspondientes.')
    impacto = (
        'El contrato no refleja un dato que afecta al cálculo salarial y a los '
        'informes de calificación del personal.')
    solucion = (
        'Abra el contrato y complete el campo correspondiente al grado científico '
        'que tiene registrado el trabajador.')

    def _hallazgo(self, object_id, clave_extra, etiqueta, campo, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            clave_extra=clave_extra,
            titulo=titulo,
            detalle=(
                f'El trabajador tiene registrado el grado científico de {etiqueta}, '
                f'pero el campo correspondiente del contrato está vacío.'),
            datos={'grado_cientifico': etiqueta, campo: 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'maestria', 'doctorado', 'aspirante__grado_cientifico')

        filas = (self.base_queryset()
                 .filter(aspirante__grado_cientifico__in=['MC', 'DC'])
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            grado = fila.get('aspirante__grado_cientifico')
            problemas = _grado_cientifico_sin_reflejar(
                grado, fila.get('maestria'), fila.get('doctorado'))

            for clave_extra, etiqueta, campo in problemas:
                sufijo = ('es máster y el contrato no lo refleja' if etiqueta == 'Máster'
                          else 'es doctor y el contrato no lo refleja')
                yield self._hallazgo(
                    str(fila['id']), clave_extra, etiqueta, campo,
                    self.titulo_de(fila, sufijo), self.unidad_de(fila))

    def evaluar_instancia(self, contrato):
        aspirante = contrato.aspirante
        problemas = _grado_cientifico_sin_reflejar(
            aspirante.grado_cientifico if aspirante else None,
            contrato.maestria, contrato.doctorado)
        if not problemas:
            return None

        return [
            self._hallazgo(
                str(contrato.pk), clave_extra, etiqueta, campo,
                f'{etiqueta} y el contrato no lo refleja')
            for clave_extra, etiqueta, campo in problemas
        ]


class AspiranteConMultiplesContratos(ReglaContratos):
    codigo = 'CTR-008'
    nombre = 'Trabajador con más de un contrato de alta'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Un trabajador solo debería tener un contrato de alta vigente a la vez. '
        'Busca a quienes tienen más de uno.')
    causa_probable = (
        'Se creó un contrato nuevo sin dar de baja el anterior, o una importación '
        'insertó varias filas para la misma persona.')
    impacto = (
        'El trabajador ocupa dos plazas de plantilla a la vez y tiene dos salarios '
        'calculándose en paralelo. Los informes de nómina cuentan a esta persona '
        'dos veces.')
    solucion = (
        'Revise cuál de los contratos es el vigente y dé de baja el que ya no '
        'corresponde desde su propio formulario.')

    # Este hallazgo apunta al ASPIRANTE, no al contrato, aunque la regla viva en el
    # módulo de Contratos por afinidad temática con el resto de reglas de esta
    # familia. `object_id` es el pk del aspirante, así que `modelo` TIENE que ser
    # `bolsa.Aspirante` y no el `contratos.CAlta` que hereda `ReglaContratos`: el
    # `content_type` que guarda el hallazgo sale de este atributo, y tiene que
    # coincidir con lo que `object_id` de verdad identifica, o el enlace y cualquier
    # resolución futura del objeto quedarían apuntando al modelo equivocado.
    modelo = 'bolsa.Aspirante'

    def ejecutar(self, contexto):
        Aspirante = self.obtener_modelo()

        duplicados = (Aspirante.objects
                      .annotate(total=Count('calta_contratos'))
                      .filter(total__gt=1)
                      .values('id', 'nombre', 'papellido', 'sapellido',
                              'doc_identidad', 'unidad_organizativa_id', 'total')
                      .iterator(chunk_size=TAMANO_LOTE))

        for fila in duplicados:
            referencia = referencia_trabajador(
                fila.get('nombre'), fila.get('papellido'),
                fila.get('sapellido'), fila.get('doc_identidad'))
            total = fila['total']
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · tiene {total} contratos de alta a la vez',
                detalle=(
                    f'Este trabajador tiene {total} contratos de alta vigentes '
                    f'simultáneamente. Solo debería tener uno.'),
                datos={'contratos_de_alta_vigentes': total},
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class SalarioFijoConTridente(ReglaContratos):
    codigo = 'CTR-009'
    nombre = 'Contrato de salario fijo con tridente asignado'
    criticidad = CRITICIDAD_BAJA

    descripcion = (
        'Un contrato de salario fijo no debería tener tridente: el tridente solo '
        'aplica al salario dinámico por escala.')
    causa_probable = (
        'El contrato cambió de salario dinámico a fijo. CAlta.save() limpia el '
        'tridente al guardar en ese caso, así que este dato solo puede quedar '
        'así si la fila se escribió sin pasar por el formulario.')
    impacto = (
        'Es una inconsistencia menor: el tridente no se usa para el cálculo '
        '(el salario fijo toma el básico del cargo), pero indica que el registro '
        'se escribió por una vía que no respeta las reglas del formulario.')
    solucion = (
        'Abra el contrato y guárdelo: al guardar con salario fijo, Orbith limpia '
        'el tridente automáticamente.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(tipo_salario='FIJ', tridente__isnull=False)
                 .values(*self.COLUMNAS_BASE, 'tridente__tipo')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            tridente = fila.get('tridente__tipo') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'salario fijo con tridente «{tridente}»'),
                detalle=(
                    f'El contrato es de salario fijo pero tiene el tridente '
                    f'«{tridente}» asignado, cuando el salario fijo no usa tridente.'),
                datos={'tipo_de_salario': 'Fijo', 'tridente_asignado': tridente},
                unidad_organizativa_id=self.unidad_de(fila),
            )


class NocturnidadesDuplicadas(ReglaContratos):
    codigo = 'CTR-010'
    nombre = 'Las dos nocturnidades del contrato son la misma'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Un contrato no puede tener la misma condición de nocturnidad marcada '
        'dos veces.')
    causa_probable = (
        'El formulario lo impide (clean() lo rechaza), así que solo puede '
        'ocurrir en una fila escrita sin pasar por él: una importación o una '
        'actualización masiva.')
    impacto = (
        'El cálculo del pago por nocturnidad puede duplicarse o quedar '
        'indefinido, según cómo lo interprete el informe de nómina que lo use.')
    solucion = (
        'Abra el contrato y corrija una de las dos nocturnidades para que sean '
        'distintas.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(nocturnidad_1__isnull=False)
                 .filter(nocturnidad_1=F('nocturnidad_2'))
                 .values(*self.COLUMNAS_BASE, 'nocturnidad_1__nombre')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            condicion = fila.get('nocturnidad_1__nombre') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'nocturnidad «{condicion}» duplicada'),
                detalle=(
                    f'Las dos nocturnidades del contrato son la misma condición '
                    f'«{condicion}».'),
                datos={'nocturnidad_1': condicion, 'nocturnidad_2': condicion},
                unidad_organizativa_id=self.unidad_de(fila),
            )


class NocturnidadSinConfigurar(ReglaContratos):
    codigo = 'CTR-011'
    nombre = 'Nocturnidad del contrato sin horario configurado'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Cada nocturnidad del contrato debe apuntar a una condición laboral que '
        'tenga un horario de nocturnidad configurado en el nomenclador.')
    causa_probable = (
        'La condición laboral anormal se creó sin asignarle su nocturnidad, o '
        'esa nocturnidad se desvinculó después de que el contrato ya la '
        'estuviera usando.')
    impacto = (
        'Sin el horario de nocturnidad configurado, Orbith no puede calcular '
        'cuántas horas nocturnas corresponde pagar en este contrato.')
    solucion = (
        'Vaya al nomenclador de Condiciones Laborales Anormales y asigne el '
        'horario de nocturnidad que falta. No hace falta tocar el contrato: en '
        'cuanto se configure el nomenclador, el cálculo queda correcto.')

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'nocturnidad_1__nombre', 'nocturnidad_1__nocturnidad_id',
            'nocturnidad_2__nombre', 'nocturnidad_2__nocturnidad_id',
        )
        filas = (self.base_queryset()
                 .filter(Q(nocturnidad_1__isnull=False, nocturnidad_1__nocturnidad__isnull=True)
                         | Q(nocturnidad_2__isnull=False, nocturnidad_2__nocturnidad__isnull=True))
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            sin_horario = []
            if (fila.get('nocturnidad_1__nombre')
                    and fila.get('nocturnidad_1__nocturnidad_id') is None):
                sin_horario.append(('Nocturnidad 1', fila['nocturnidad_1__nombre']))
            if (fila.get('nocturnidad_2__nombre')
                    and fila.get('nocturnidad_2__nocturnidad_id') is None):
                sin_horario.append(('Nocturnidad 2', fila['nocturnidad_2__nombre']))

            for campo, condicion in sin_horario:
                yield HallazgoDetectado(
                    object_id=str(fila['id']),
                    clave_extra=campo.lower().replace(' ', '_'),
                    titulo=self.titulo_de(
                        fila, f'{campo} «{condicion}» sin horario configurado'),
                    detalle=(
                        f'{campo} usa la condición «{condicion}», que no tiene un '
                        f'horario de nocturnidad configurado en el nomenclador.'),
                    datos={'campo': campo, 'condicion': condicion},
                    unidad_organizativa_id=self.unidad_de(fila),
                )


def _funcionario_o_designado_sin_codigo(es_funcionario, es_designado, funcionario_res, designado_res):
    """Pura: la usan `ejecutar()` y `evaluar_instancia()` sin repetir la condición.

    Devuelve una lista de `(clave_extra, etiqueta, campo)` — vacía si no hay problema.
    """
    problemas = []
    if es_funcionario and not (funcionario_res or '').strip():
        problemas.append(('funcionario_sin_codigo', 'Funcionario', 'funcionario_res'))
    if es_designado and not (designado_res or '').strip():
        problemas.append(('designado_sin_codigo', 'Designado', 'designado_res'))
    return problemas


class FuncionarioODesignadoSinCodigo(ReglaContratos):
    """Dos variantes del mismo problema: funcionario y designado sin su código.

    CRITICIDAD_BAJA a propósito: el propio usuario calificó este campo como
    «importante pero no obligatorio» — el código de la resolución puede tardar en
    emitirse, así que su ausencia no es una violación de una regla de negocio, es una
    tarea pendiente de completar cuando llegue el documento.
    """

    codigo = 'CTR-012'
    nombre = 'Funcionario o designado sin código de resolución'
    criticidad = CRITICIDAD_BAJA
    # Evaluable en caliente: O(1) — un único salto de FK (`instancia.cargo`, ya
    # resuelto por las @property `funcionario`/`designado` de CAlta) más dos campos
    # propios de la instancia.
    evaluable_en_caliente = True

    descripcion = (
        'Cuando el cargo del contrato es Funcionario o Designado, el contrato debe '
        'tener registrado el código de la resolución correspondiente.')
    causa_probable = (
        'El cargo se marcó como Funcionario o Designado en la Plantilla después de '
        'crear el contrato, o el contrato se guardó antes de que llegara la '
        'resolución administrativa que respalda esa condición.')
    impacto = (
        'El contrato no tiene trazabilidad del acto administrativo que respalda la '
        'condición de Funcionario o Designado del trabajador. No es obligatorio a '
        'nivel de sistema porque el código puede tardar en emitirse, pero su '
        'ausencia prolongada deja el expediente incompleto.')
    solucion = (
        'Cuando llegue la resolución, abra el contrato y registre el código '
        'correspondiente (funcionario_res o designado_res, según el tipo de cargo).')

    def _hallazgo(self, object_id, clave_extra, etiqueta, campo, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            clave_extra=clave_extra,
            titulo=titulo,
            detalle=(
                f'El cargo es {etiqueta}, pero el contrato no tiene registrado el '
                f'código de resolución correspondiente.'),
            datos={'condicion': etiqueta, 'campo': campo},
            unidad_organizativa_id=unidad_organizativa_id,
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'cargo__funcionario', 'cargo__designado', 'funcionario_res', 'designado_res')

        filas = (self.base_queryset()
                 .filter(Q(cargo__funcionario=True) | Q(cargo__designado=True))
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            problemas = _funcionario_o_designado_sin_codigo(
                fila.get('cargo__funcionario'), fila.get('cargo__designado'),
                fila.get('funcionario_res'), fila.get('designado_res'))

            for clave_extra, etiqueta, campo in problemas:
                yield self._hallazgo(
                    str(fila['id']), clave_extra, etiqueta, campo,
                    self.titulo_de(fila, f'{etiqueta.lower()} sin código de resolución'),
                    self.unidad_de(fila))

    def evaluar_instancia(self, contrato):
        # `funcionario`/`designado` son @property de CAlta que delegan en `self.cargo`
        # (un único salto de FK, ya cargado por Django al acceder a `contrato.cargo`).
        problemas = _funcionario_o_designado_sin_codigo(
            contrato.funcionario, contrato.designado,
            contrato.funcionario_res, contrato.designado_res)
        if not problemas:
            return None

        return [
            self._hallazgo(
                str(contrato.pk), clave_extra, etiqueta, campo,
                f'{etiqueta} sin código de resolución')
            for clave_extra, etiqueta, campo in problemas
        ]


def _fechas_de_vencimiento_faltantes(lic, recal, seg):
    """Pura: la usan `ejecutar()` y `evaluar_instancia()` sin repetir la condición.

    Devuelve una lista de `(campo, nombre)` — vacía si no falta ninguna fecha.
    """
    faltantes = []
    if lic is None:
        faltantes.append(('fecha_vence_lic', 'licencia'))
    if recal is None:
        faltantes.append(('fecha_vence_recal', 'recalificación'))
    if seg is None:
        faltantes.append(('fecha_vence_seg', 'seguro'))
    return faltantes


class ChoferSinFechasDeVencimiento(ReglaContratos):
    """Chófer (profesional) sin las fechas de vencimiento de sus documentos.

    CRITICIDAD_MEDIA: más grave que CTR-012 porque aquí hay un riesgo operativo real
    (un chófer puede seguir conduciendo con documentación caducada sin que nadie lo
    detecte), no solo una trazabilidad administrativa pendiente. Sigue sin ser
    obligatoria a nivel de formulario, por la misma razón que CTR-012: el dato puede
    llegar después del alta.
    """

    codigo = 'CTR-013'
    nombre = 'Chófer sin fechas de vencimiento de licencia, recalificación o seguro'
    criticidad = CRITICIDAD_MEDIA
    # Evaluable en caliente: O(1) — solo campos propios de la instancia, sin FK.
    evaluable_en_caliente = True

    descripcion = (
        'Cuando el contrato marca al trabajador como profesional (chófer), debe '
        'tener registradas las fechas de vencimiento de licencia, recalificación y '
        'seguro.')
    causa_probable = (
        'Se marcó «profesional» al crear el contrato pero las fechas de los '
        'documentos del chófer todavía no estaban disponibles, o se registraron en '
        'el expediente físico sin trasladarlas al sistema.')
    impacto = (
        'Sin estas fechas, Orbith no puede avisar cuándo vence la licencia, la '
        'recalificación o el seguro de este chófer, lo que puede dejarlo conduciendo '
        'con documentación caducada sin que nadie lo detecte a tiempo. No es '
        'obligatorio a nivel de formulario porque el dato puede llegar después del '
        'alta.')
    solucion = (
        'Abra el contrato y complete las fechas de vencimiento que falten: '
        'licencia, recalificación y/o seguro.')

    def _hallazgo(self, object_id, faltantes, titulo):
        nombres = ', '.join(nombre for _, nombre in faltantes)
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle=f'El trabajador es chófer y le faltan estas fechas de vencimiento: {nombres}.',
            datos={'faltantes': [campo for campo, _ in faltantes]},
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'fecha_vence_lic', 'fecha_vence_recal', 'fecha_vence_seg')

        filas = (self.base_queryset()
                 .filter(profesional=True)
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            faltantes = _fechas_de_vencimiento_faltantes(
                fila.get('fecha_vence_lic'), fila.get('fecha_vence_recal'),
                fila.get('fecha_vence_seg'))
            if not faltantes:
                continue

            nombres = ', '.join(nombre for _, nombre in faltantes)
            hallazgo = self._hallazgo(
                str(fila['id']), faltantes,
                self.titulo_de(fila, f'chófer sin fecha de {nombres}'))
            # `_hallazgo` no fija `unidad_organizativa_id` (evaluar_instancia no la
            # necesita); en el barrido sí hace falta para el alcance por rol.
            yield HallazgoDetectado(
                object_id=hallazgo.object_id, titulo=hallazgo.titulo,
                detalle=hallazgo.detalle, datos=hallazgo.datos,
                unidad_organizativa_id=self.unidad_de(fila))

    def evaluar_instancia(self, contrato):
        if not contrato.profesional:
            return None

        faltantes = _fechas_de_vencimiento_faltantes(
            contrato.fecha_vence_lic, contrato.fecha_vence_recal, contrato.fecha_vence_seg)
        if not faltantes:
            return None

        nombres = ', '.join(nombre for _, nombre in faltantes)
        return [self._hallazgo(str(contrato.pk), faltantes, f'Chófer sin fecha de {nombres}')]
