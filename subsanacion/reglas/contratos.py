"""Reglas de integridad de los contratos de alta."""

from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
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
        'categoría ocupacional o unidad organizativa (incluido el Anexo 17).')
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
    criticidad = CRITICIDAD_CRITICA

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
    criticidad = CRITICIDAD_CRITICA

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


def _tridente_indebido(tipo_salario, es_cuadro):
    """Pura: recibe valores escalares, no un dict ni una instancia.

    La usan `ejecutar()` (con valores de `.values()`) y, si en el futuro se activa
    `evaluable_en_caliente` para esta regla, también `evaluar_instancia()` — mismo
    patrón que `_grado_cientifico_sin_reflejar` (CTR-007) — para que el criterio
    nunca pueda divergir de la "REGLA DE ORO" de `contratos/forms.py::CAltaForm.clean()`
    ni de `contratos/salarios.py::calcular_salario()`: un salario Fijo, o un cargo de
    categoría Cuadro, no usan tridente.

    Devuelve la `clave_extra` del problema, o `''` si el tridente es correcto.
    """
    if tipo_salario == 'FIJ':
        return 'fijo_con_tridente'
    if es_cuadro:
        return 'cuadro_con_tridente'
    return ''


class TridenteIndebido(ReglaContratos):
    """Un mismo problema con dos variantes: fijo con tridente y cuadro con tridente.

    Se agrupan en una sola clase porque comparten causa, impacto y solución (el
    tridente solo aplica al salario dinámico en un cargo que no es de categoría
    Cuadro); se distinguen con `clave_extra` para poder revisar cada variante por
    separado, igual que `MotivoIncoherenteConTipo` (CTR-002) y
    `GradoCientificoSinReflejar` (CTR-007).
    """

    codigo = 'CTR-009'
    nombre = 'Contrato con tridente asignado indebidamente'
    criticidad = CRITICIDAD_BAJA
    # Evaluable en caliente: O(1) — un único campo propio (`tipo_salario`) más un
    # salto de FK ya resuelto por `calcular_salario_escala()` momentos antes en el
    # mismo `save()` (`self.cargo.ncargo`), así que no añade una consulta nueva. Es
    # lo que permite que `subsanacion.servicios.reconciliar_hallazgos_en_caliente()`
    # cierre el hallazgo en el momento en que se corrige, sin esperar al barrido
    # periódico (ver esa función para el porqué no todas las reglas hacen esto).
    evaluable_en_caliente = True

    descripcion = (
        'El tridente solo aplica a un contrato de salario dinámico cuyo cargo NO '
        'es de categoría Cuadro (Directivo o Ejecutivo). Busca contratos que '
        'tengan tridente asignado a pesar de no cumplir esa condición: salario '
        'fijo, o cargo de Cuadro con salario dinámico.')
    causa_probable = (
        'El contrato cambió de salario dinámico a fijo, o el cargo del contrato '
        'cambió a una categoría ocupacional de Cuadro, después de que el '
        'tridente ya estuviera asignado. CAlta.save() limpia el tridente al '
        'guardar en ambos casos, así que este dato solo puede quedar así si la '
        'fila se escribió sin pasar por el formulario (por ejemplo, desde el '
        'admin de Django o un script).')
    impacto = (
        'Es una inconsistencia menor: el tridente no se usa para el cálculo '
        'en ninguno de los dos casos (el salario fijo toma el básico del cargo, '
        'y un Cuadro cobra por su escala sin tridente), pero indica que el '
        'registro se escribió por una vía que no respeta las reglas del '
        'formulario.')
    solucion = (
        'Abra el contrato y guárdelo: al guardar, Orbith limpia el tridente '
        'automáticamente cuando el salario es fijo o el cargo es de Cuadro.')

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'tipo_salario', 'tridente__tipo', 'cargo__ncargo__cat_ocupacional')

        filas = (self.base_queryset()
                 .filter(tridente__isnull=False)
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        NCargo = apps.get_model('nomencladores', 'NCargo')

        for fila in filas:
            categoria = fila.get('cargo__ncargo__cat_ocupacional')
            es_cuadro = categoria in NCargo.CATEGORIAS_CUADRO
            clave_extra = _tridente_indebido(fila.get('tipo_salario'), es_cuadro)
            if not clave_extra:
                continue

            tridente = fila.get('tridente__tipo') or '—'
            if clave_extra == 'fijo_con_tridente':
                sufijo = f'salario fijo con tridente «{tridente}»'
                detalle = (
                    f'El contrato es de salario fijo pero tiene el tridente '
                    f'«{tridente}» asignado, cuando el salario fijo no usa tridente.')
                tipo_de_salario = 'Fijo'
            else:
                sufijo = f'cargo de Cuadro con tridente «{tridente}»'
                detalle = (
                    f'El contrato es de salario dinámico en un cargo de categoría '
                    f'Cuadro, pero tiene el tridente «{tridente}» asignado, cuando '
                    f'un Cuadro no usa tridente.')
                tipo_de_salario = 'Dinámico (Cuadro)'

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra=clave_extra,
                titulo=self.titulo_de(fila, sufijo),
                detalle=detalle,
                datos={'tipo_de_salario': tipo_de_salario, 'tridente_asignado': tridente},
                unidad_organizativa_id=self.unidad_de(fila),
            )

    def evaluar_instancia(self, contrato):
        # Mismo filtro que `ejecutar()`: sin tridente asignado no hay nada indebido
        # que reportar, sea cual sea el tipo de salario o el cargo.
        if not contrato.tridente_id:
            return None

        ncargo = contrato.cargo.ncargo if contrato.cargo_id else None
        es_cuadro = bool(ncargo.es_cuadro) if ncargo else False
        clave_extra = _tridente_indebido(contrato.tipo_salario, es_cuadro)
        if not clave_extra:
            return None

        tridente = contrato.tridente.tipo
        if clave_extra == 'fijo_con_tridente':
            detalle = (
                f'El contrato es de salario fijo pero tiene el tridente '
                f'«{tridente}» asignado, cuando el salario fijo no usa tridente.')
            tipo_de_salario = 'Fijo'
        else:
            detalle = (
                f'El contrato es de salario dinámico en un cargo de categoría '
                f'Cuadro, pero tiene el tridente «{tridente}» asignado, cuando '
                f'un Cuadro no usa tridente.')
            tipo_de_salario = 'Dinámico (Cuadro)'

        return [HallazgoDetectado(
            object_id=str(contrato.pk),
            clave_extra=clave_extra,
            titulo=f'Tridente «{tridente}» asignado indebidamente',
            detalle=detalle,
            datos={'tipo_de_salario': tipo_de_salario, 'tridente_asignado': tridente},
        )]


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


def _funcionario_o_designado_sin_codigo(es_funcionario, es_designado, funcionario_res, designado_res,
                                        es_de_confianza=False, confianza_res=None):
    """Pura: la usan `ejecutar()` y `evaluar_instancia()` sin repetir la condición.

    Devuelve una lista de `(clave_extra, etiqueta, campo)` — vacía si no hay problema.
    De Confianza se añadió el 24-10-2026 (decisión de RRHH).
    """
    problemas = []
    if es_funcionario and not (funcionario_res or '').strip():
        problemas.append(('funcionario_sin_codigo', 'Funcionario', 'funcionario_res'))
    if es_designado and not (designado_res or '').strip():
        problemas.append(('designado_sin_codigo', 'Designado', 'designado_res'))
    if es_de_confianza and not (confianza_res or '').strip():
        problemas.append(('confianza_sin_codigo', 'De Confianza', 'confianza_res'))
    return problemas


class FuncionarioODesignadoSinCodigo(ReglaContratos):
    """Dos variantes del mismo problema: funcionario y designado sin su código.

    CRITICIDAD_BAJA a propósito: el propio usuario calificó este campo como
    «importante pero no obligatorio» — el código de la resolución puede tardar en
    emitirse, así que su ausencia no es una violación de una regla de negocio, es una
    tarea pendiente de completar cuando llegue el documento.
    """

    codigo = 'CTR-012'
    nombre = 'Funcionario, designado o de confianza sin código de resolución'
    criticidad = CRITICIDAD_BAJA
    # Evaluable en caliente: O(1) — un único salto de FK (`instancia.cargo`, ya
    # resuelto por las @property `funcionario`/`designado` de CAlta) más dos campos
    # propios de la instancia.
    evaluable_en_caliente = True

    descripcion = (
        'Cuando el cargo del contrato es Funcionario, Designado o De Confianza, el '
        'contrato debe tener registrado el código de la resolución correspondiente.')
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
        'correspondiente (Funcionario, Designado o De Confianza, según el cargo). '
        'El Moderador puede hacerlo sin solicitud, también desde el movimiento de nómina.')

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
            campo_formulario=campo,
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'cargo__funcionario', 'cargo__designado', 'funcionario_res', 'designado_res',
            'cargo__de_confianza', 'confianza_res')

        filas = (self.base_queryset()
                 .filter(Q(cargo__funcionario=True) | Q(cargo__designado=True)
                         | Q(cargo__de_confianza=True))
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            problemas = _funcionario_o_designado_sin_codigo(
                fila.get('cargo__funcionario'), fila.get('cargo__designado'),
                fila.get('funcionario_res'), fila.get('designado_res'),
                fila.get('cargo__de_confianza'), fila.get('confianza_res'))

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
            contrato.funcionario_res, contrato.designado_res,
            getattr(contrato, 'de_confianza', False), getattr(contrato, 'confianza_res', None))
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
            # Puede faltar más de una fecha a la vez: se apunta a la primera, que
            # basta para llevar al usuario a la zona correcta del formulario.
            campo_formulario=faltantes[0][0],
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


def _mision_sin_pais(mision, pais):
    """Pura: la usan ejecutar() y evaluar_instancia() sin repetir la condición."""
    return bool(mision) and not (pais or '').strip()


class MisionSinPais(ReglaContratos):
    codigo = 'CTR-014'
    nombre = 'Contrato de misión sin país registrado'
    criticidad = CRITICIDAD_MEDIA
    # Evaluable en caliente: O(1) — solo campos propios de la instancia, sin FK.
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que un contrato marcado como misión tenga registrado el país '
        'donde se cumple.')
    causa_probable = (
        'Se marcó «Misión» al crear el contrato pero el país todavía no estaba '
        'confirmado, o se registró en el expediente físico sin trasladarlo al '
        'sistema.')
    impacto = (
        'Sin el país, el contrato no documenta dónde se cumple la misión, un dato '
        'que afecta a la trazabilidad administrativa del trabajador en el '
        'exterior. No es obligatorio a nivel de formulario porque el dato puede '
        'llegar después del alta.')
    solucion = 'Abra el contrato y complete el país de la misión.'

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle='El contrato es de misión, pero no tiene registrado el país.',
            datos={'mision': 'Sí', 'pais': 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='pais',
        )

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(mision=True)
                 .filter(Q(pais__isnull=True) | Q(pais=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield self._hallazgo(
                str(fila['id']), self.titulo_de(fila, 'misión sin país'),
                self.unidad_de(fila))

    def evaluar_instancia(self, contrato):
        if not _mision_sin_pais(contrato.mision, contrato.pais):
            return None
        return [self._hallazgo(str(contrato.pk), 'Misión sin país')]


def _datos_de_mision_faltantes(mision, dias, importe):
    """Pura: `[(campo, nombre)]` de los datos de la misión que faltan.

    El 0 cuenta como falta: es un valor válido para el modelo, pero nadie cumple
    una misión de 0 días cobrando 0. Vacío y 0 se reclaman igual.
    """
    if not mision:
        return []
    faltantes = []
    if not dias:
        faltantes.append(('mision_dias', 'días'))
    if not importe:
        faltantes.append(('mision_importe', 'importe'))
    return faltantes


class MisionSinDiasOImporte(ReglaContratos):
    codigo = 'CTR-021'
    nombre = 'Contrato de misión sin días o importe'
    criticidad = CRITICIDAD_MEDIA
    # Evaluable en caliente: O(1) — solo campos propios de la instancia, sin FK.
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que un contrato marcado como misión tenga registrados los días '
        'que dura y su importe. Un valor en 0 también se reclama.')
    causa_probable = (
        'Se marcó «Misión» al crear el contrato pero la duración o el importe '
        'todavía no estaban confirmados, o se registraron en el expediente físico '
        'sin trasladarlos al sistema.')
    impacto = (
        'Sin los días y el importe, el informe de Misiones Internacionales sale '
        'incompleto y su total no refleja lo que realmente se paga. No es '
        'obligatorio a nivel de formulario porque el dato puede llegar después del '
        'alta.')
    solucion = 'Abra el contrato y complete los días y el importe de la misión.'

    def _hallazgo(self, object_id, faltantes, titulo, unidad_organizativa_id=None):
        nombres = ' ni '.join(nombre for _, nombre in faltantes)
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle=f'El contrato es de misión, pero no tiene registrado {nombres}.',
            datos={'faltantes': [campo for campo, _ in faltantes]},
            unidad_organizativa_id=unidad_organizativa_id,
            # Si faltan los dos, se apunta al primero: basta para llevar al
            # usuario a la fila de la misión en el formulario.
            campo_formulario=faltantes[0][0],
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + ('mision_dias', 'mision_importe')
        filas = (self.base_queryset()
                 .filter(mision=True)
                 .filter(Q(mision_dias__isnull=True) | Q(mision_dias=0)
                         | Q(mision_importe__isnull=True) | Q(mision_importe=0))
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            faltantes = _datos_de_mision_faltantes(
                True, fila['mision_dias'], fila['mision_importe'])
            nombres = ' ni '.join(nombre for _, nombre in faltantes)
            yield self._hallazgo(
                str(fila['id']), faltantes,
                self.titulo_de(fila, f'misión sin {nombres}'),
                self.unidad_de(fila))

    def evaluar_instancia(self, contrato):
        faltantes = _datos_de_mision_faltantes(
            contrato.mision, contrato.mision_dias, contrato.mision_importe)
        if not faltantes:
            return None
        nombres = ' ni '.join(nombre for _, nombre in faltantes)
        return [self._hallazgo(str(contrato.pk), faltantes, f'Misión sin {nombres}')]


def _c_formal_sin_res(c_formal, c_formal_res):
    """Pura: la usan ejecutar() y evaluar_instancia() sin repetir la condición."""
    return bool(c_formal) and not (c_formal_res or '').strip()


class ConformidadFormalSinCodigo(ReglaContratos):
    """Contrato marcado como «C. Formal» sin su código de resolución.

    A diferencia de `funcionario`/`designado` (CTR-012), que son `@property` que
    delegan en `self.cargo`, `c_formal` es un campo propio de `CAlta` — no depende
    de la Plantilla, se marca directamente en el contrato.
    """

    codigo = 'CTR-015'
    nombre = 'Conformidad formal sin código de resolución'
    criticidad = CRITICIDAD_BAJA
    evaluable_en_caliente = True

    descripcion = (
        'Cuando el contrato marca «C. Formal», debe tener registrado el código de '
        'la resolución correspondiente.')
    causa_probable = (
        'Se marcó «C. Formal» al crear el contrato antes de que llegara la '
        'resolución administrativa que la respalda.')
    impacto = (
        'El contrato no tiene trazabilidad del acto administrativo que respalda '
        'la conformidad formal. No es obligatorio a nivel de sistema porque el '
        'código puede tardar en emitirse.')
    solucion = (
        'Cuando llegue la resolución, abra el contrato y registre el código '
        'correspondiente en «C. Formal».')

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle=(
                'El contrato está marcado como C. Formal, pero no tiene '
                'registrado el código de resolución correspondiente.'),
            datos={'c_formal': 'Sí', 'c_formal_res': 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='c_formal_res',
        )

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + ('c_formal', 'c_formal_res')

        filas = (self.base_queryset()
                 .filter(c_formal=True)
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            if not _c_formal_sin_res(fila.get('c_formal'), fila.get('c_formal_res')):
                continue
            yield self._hallazgo(
                str(fila['id']),
                self.titulo_de(fila, 'C. Formal sin código de resolución'),
                self.unidad_de(fila))

    def evaluar_instancia(self, contrato):
        if not _c_formal_sin_res(contrato.c_formal, contrato.c_formal_res):
            return None
        return [self._hallazgo(str(contrato.pk), 'C. Formal sin código de resolución')]


class ContratoSinFechaAltaEntidad(ReglaContratos):
    codigo = 'CTR-016'
    nombre = 'Contrato sin F. Alta Entidad'
    criticidad = CRITICIDAD_ALTA

    descripcion = 'Busca contratos sin la fecha de alta inicial en la entidad registrada.'
    causa_probable = (
        'El campo se incorporó después de que estos contratos ya existieran en '
        'producción, así que quedó vacío para todo el histórico previo a su '
        'creación.')
    impacto = (
        'La F. Alta Entidad es la base para calcular en el futuro los años de '
        'servicio ininterrumpido del trabajador dentro de la Unión Eléctrica. '
        'Sin ella, ese cálculo no puede hacerse correctamente para este contrato.')
    solucion = (
        'Abra el contrato y registre la fecha en que el trabajador fue dado de '
        'alta por primera vez en la entidad (puede coincidir con la F. de '
        'Contratación).')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(fecha_alta_entidad__isnull=True)
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'sin F. Alta Entidad'),
                detalle='El contrato no tiene registrada la fecha de alta inicial en la entidad.',
                datos={'expediente': fila.get('no_expediente') or '—'},
                unidad_organizativa_id=self.unidad_de(fila),
                campo_formulario='fecha_alta_entidad',
            )


class ContratoFechaAltaEntidadImposible(ReglaContratos):
    """CTR-017: la F. Alta Entidad existe, pero con un año que no puede ser real.

    Regla aparte de CTR-016 y no un filtro más dentro de ella: el problema es distinto
    (allí falta el dato, aquí está mal escrito), la causa y la solución que se le explican
    al usuario también, y los hallazgos se identifican por `codigo_regla`. Mezclarlas
    haría que un contrato pasara de «sin fecha» a «con fecha imposible» sin que el panel
    reflejara ningún cambio.
    """

    codigo = 'CTR-017'
    nombre = 'Contrato con F. Alta Entidad imposible'
    criticidad = CRITICIDAD_ALTA

    #: Mismo corte que `contratos.forms.ANO_MINIMO_FECHAS`. Se repite en vez de
    #: importarse para que el motor de Subsanación no dependa del módulo de formularios.
    ANO_MINIMO = 1900

    descripcion = (
        'Busca contratos cuya fecha de alta en la entidad tiene un año anterior a 1900.')
    causa_probable = (
        'Un campo de fecha del navegador guarda lo que tenga escrito en cuanto se sale '
        'de él, aunque el año esté a medio teclear: al escribir "2022" y pasar al '
        'siguiente campo demasiado pronto quedaba registrado el año 0002. Hasta que se '
        'añadió la validación de año mínimo, ni el formulario ni la base de datos lo '
        'rechazaban.')
    impacto = (
        'La F. Alta Entidad es la base para calcular los años de servicio '
        'ininterrumpido del trabajador en la Unión Eléctrica. Con un año imposible ese '
        'cálculo da un resultado absurdo, y además la fecha aparece mal en cualquier '
        'informe o documento que la muestre.')
    solucion = (
        'Abra el contrato y escriba de nuevo la fecha en que el trabajador fue dado de '
        'alta por primera vez en la entidad, comprobando que el año tenga cuatro '
        'cifras. El formulario ya no admite años anteriores a 1900.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(fecha_alta_entidad__isnull=False,
                         fecha_alta_entidad__lt=date(self.ANO_MINIMO, 1, 1))
                 .values(*self.COLUMNAS_BASE, 'fecha_alta_entidad')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            # Formateo a mano y no con `strftime('%d/%m/%Y')`: para un año de una sola
            # cifra —justo el caso que esta regla persigue— el relleno con ceros de
            # `%Y` depende de la plataforma, y en Windows sale «2» en vez de «0002».
            fecha = fila.get('fecha_alta_entidad')
            texto_fecha = f'{fecha.day:02d}/{fecha.month:02d}/{fecha.year:04d}'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, 'con F. Alta Entidad imposible'),
                detalle=(
                    f'La fecha de alta en la entidad registrada es {texto_fecha}, '
                    f'con un año anterior a {self.ANO_MINIMO}.'),
                datos={
                    'expediente': fila.get('no_expediente') or '—',
                    'fecha_registrada': texto_fecha,
                },
                unidad_organizativa_id=self.unidad_de(fila),
                campo_formulario='fecha_alta_entidad',
            )


class ContratoFechaAltaImposible(ReglaContratos):
    """CTR-022: la fecha de alta del CONTRATO tiene un año que no puede ser real.

    Regla aparte de CTR-017 (F. Alta Entidad) por el mismo motivo que CTR-017 está
    aparte de CTR-016: otro dato, otra causa y otra solución. La fecha de alta no
    se edita en el formulario del contrato (sale de solo lectura), así que la
    solución pasa por el panel de administración."""

    codigo = 'CTR-022'
    nombre = 'Contrato con fecha de alta imposible'
    criticidad = CRITICIDAD_ALTA
    ANO_MINIMO = 1900

    descripcion = 'Busca contratos cuya fecha de alta tiene un año anterior a 1900.'
    causa_probable = (
        'Se escribió el año incompleto (0026 en vez de 2026) en la fecha efectiva del '
        'asistente de contratación, que hasta el 13-10-2026 lo aceptaba.')
    impacto = (
        'El contrato aparece como el más antiguo de la empresa, la fecha mínima para '
        'bajas y movimientos queda en un año absurdo, y las cifras de altas por mes de '
        'la Dashboard y los informes no lo cuentan en el mes real.')
    solucion = (
        'Corrija la fecha de alta del contrato desde el panel de administración, '
        'escribiendo el año con cuatro cifras, y revise su movimiento «Alta Inicial» '
        '(regla MOV-011). El asistente ya no admite años anteriores a 1900.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(fecha_alta__isnull=False, fecha_alta__lt=date(self.ANO_MINIMO, 1, 1))
                 .values(*self.COLUMNAS_BASE, 'fecha_alta')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            fecha = fila['fecha_alta']
            texto_fecha = f'{fecha.day:02d}/{fecha.month:02d}/{fecha.year:04d}'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'con fecha de alta imposible ({texto_fecha})'),
                detalle=f'La fecha de alta del contrato es {texto_fecha}, con un año anterior a {self.ANO_MINIMO}.',
                datos={'expediente': fila.get('no_expediente') or '—', 'fecha_registrada': texto_fecha},
                unidad_organizativa_id=self.unidad_de(fila),
            )


def _vencimiento_de(fecha_alta, duracion):
    """Fecha en la que se acaba un contrato determinado, o `None` si no se sabe.

    La duración de un contrato es SIEMPRE en días (confirmado por RRHH el
    23-10-2026): es lo que escribe el Word («N días»), lo que usa
    `CAlta.fecha_vencimiento` y el Recordatorio de vencimiento. Hasta entonces esta
    regla la sumaba como meses, así que un contrato de 90 días no se daba por
    vencido hasta pasados 90 meses.
    """
    if not fecha_alta or not duracion:
        return None
    return fecha_alta + timedelta(days=int(duracion))


class ContratoDeterminadoVencido(ReglaContratos):
    """El contrato determinado ya expiró y el trabajador sigue activo.

    Es el hallazgo más caro de los que faltaban: un trabajador sin contrato
    vigente sigue cobrando en nómina, y jurídicamente la relación laboral está
    sin amparo. El informe «Contratos Determinados» ya calcula los vencimientos
    para pintarlos de colores, pero nadie los RECLAMA: hay que acordarse de
    abrir ese informe.
    """

    codigo = 'CTR-018'
    nombre = 'Contrato determinado vencido con el trabajador todavía activo'
    criticidad = CRITICIDAD_CRITICA

    descripcion = (
        'Busca los contratos de duración determinada cuya fecha de vencimiento ya '
        'pasó y cuyo trabajador sigue en estado Activo.')
    causa_probable = (
        'El contrato se firmó por un número de meses y nadie lo renovó ni tramitó '
        'la baja al llegar la fecha. Nada en el sistema avisaba del vencimiento.')
    impacto = (
        'El trabajador sigue cobrando en la nómina sin un contrato vigente que lo '
        'ampare, y ocupa una plaza de la plantilla que consta como cubierta.')
    solucion = (
        'Renueve el contrato con una fecha y una duración nuevas, o tramite la baja '
        'del trabajador si ya no presta servicios.')

    def ejecutar(self, contexto):
        hoy = date.today()
        columnas = self.COLUMNAS_BASE + (
            'fecha_alta', 'duracion', 'tipo__descripcion')

        filas = (self.base_queryset()
                 .filter(aspirante__estado='ACTIVO',
                         duracion__isnull=False, duracion__gt=0,
                         fecha_alta__isnull=False)
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            vence = _vencimiento_de(fila.get('fecha_alta'), fila.get('duracion'))
            # Crítica desde el mismo día del vencimiento (antes de vencer avisa el
            # Recordatorio de 60 días; decisión de RRHH del 23-10-2026).
            if vence is None or vence > hoy:
                continue

            dias = (hoy - vence).days
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila, 'contrato que vence hoy' if vence == hoy
                    else f'contrato vencido el {vence:%d/%m/%Y}'),
                detalle=(
                    f'El contrato es de {fila["duracion"]} días desde el '
                    f'{fila["fecha_alta"]:%d/%m/%Y}, así que '
                    f'{"vence hoy" if vence == hoy else f"venció el {vence:%d/%m/%Y}"}, '
                    f'y el trabajador sigue activo.'),
                # `dias` NO entra en `datos`: cambia cada día que pasa y movería la
                # huella del hallazgo, devolviendo a Pendiente uno ya silenciado.
                datos={
                    'tipo_de_contrato': fila.get('tipo__descripcion') or '—',
                    'fecha_de_contratacion': f'{fila["fecha_alta"]:%d/%m/%Y}',
                    'duracion_en_meses': fila['duracion'],
                    'venció_el': f'{vence:%d/%m/%Y}',
                },
                unidad_organizativa_id=self.unidad_de(fila),
                campo_formulario='duracion',
            )


class ImporteAntiguoSinNomenclador(ReglaContratos):
    """Importe que el contrato tenía tecleado a mano y no encajaba con el nomenclador.

    Desde el 23-10-2026 los importes de Maestría, Doctorado, CNCI e Instructor ya no
    se guardan en el contrato: el nomenclador manda. La migración que quitó las
    columnas dejó anotados (`contratos.ImporteSinNomenclador`) los importes antiguos
    que no encajaban. Es un problema transitorio, heredado de antes de que existieran
    los nomencladores: criticidad Media, sin rojo.
    """

    codigo = 'CTR-023'
    nombre = 'Importe antiguo del contrato que no coincide con el nomenclador'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Muestra los importes de Maestría, Doctorado, CNCI o Instructor que el '
        'contrato tenía escritos a mano y que no coincidían con el nomenclador '
        'cuando el importe pasó a leerse siempre del nomenclador.')
    causa_probable = (
        'El importe se tecleó a mano antes de que existieran los nomencladores, o '
        'el nomenclador cambió después y el contrato conservaba el importe viejo.')
    impacto = (
        'El trabajador cobra ahora lo que dice el nomenclador. Si el importe antiguo '
        'era el correcto, falta elegir en el contrato la entrada que le corresponde '
        '(o crearla en el nomenclador).')
    solucion = (
        'Abra el contrato y elija la entrada de CNCI o Instructor que le corresponde: '
        'el pendiente se cierra solo. Si el importe del nomenclador es el bueno, un '
        'Administrador puede pulsar «Dar por revisado».')

    correccion_etiqueta = 'Dar por revisado'
    correccion_aviso = (
        'El contrato se queda con el importe del nomenclador y este pendiente se '
        'borra. Queda registrado en Auditoría.')

    def corregir(self, hallazgo):
        from contratos.correcciones import dar_por_revisado_importe_antiguo
        return dar_por_revisado_importe_antiguo(hallazgo.object_id, hallazgo.clave_extra)

    def ejecutar(self, contexto):
        ImporteSinNomenclador = apps.get_model('contratos', 'ImporteSinNomenclador')
        prefijo = {c: f'contrato__{c}' for c in self.COLUMNAS_BASE}
        filas = (ImporteSinNomenclador.objects
                 .values('concepto', 'importe_antiguo', 'importe_nomenclador',
                         *prefijo.values())
                 .iterator(chunk_size=TAMANO_LOTE))
        etiquetas = dict(ImporteSinNomenclador.CONCEPTOS)

        for pendiente in filas:
            fila = {c: pendiente[ruta] for c, ruta in prefijo.items()}
            etiqueta = etiquetas.get(pendiente['concepto'], pendiente['concepto'])
            antiguo = pendiente['importe_antiguo']
            nomenclador = pendiente['importe_nomenclador']
            if nomenclador is None:
                detalle = (f'El contrato tenía {antiguo} de {etiqueta} escrito a mano y '
                           f'ninguna entrada del nomenclador con ese importe. Ahora cobra 0 '
                           f'por ese concepto hasta que se le elija una entrada.')
            else:
                detalle = (f'El contrato tenía {antiguo} de {etiqueta}, pero el '
                           f'nomenclador dice {nomenclador}. Ahora cobra {nomenclador}.')
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra=pendiente['concepto'],
                titulo=self.titulo_de(fila, f'{etiqueta}: importe antiguo distinto del nomenclador'),
                detalle=detalle,
                datos={
                    'concepto': etiqueta,
                    'importe_antiguo': str(antiguo),
                    'segun_el_nomenclador': str(nomenclador) if nomenclador is not None else 'Sin entrada',
                },
                unidad_organizativa_id=self.unidad_de(fila),
                campo_formulario=f'{pendiente["concepto"]}_nomenclador'
                if pendiente['concepto'] in ('cnci', 'instructor') else '',
            )


class ContratoFijoEnCargoFueraDePlantilla(ReglaContratos):
    """Un contrato que ocupa plaza sobre un cargo que no está en la plantilla.

    No debería poder existir: lo rechazan el JavaScript de los tres modales,
    `CAltaForm.clean()` y, desde ahora, `CAlta.clean()`. Esta regla existe por lo
    que entró ANTES de esos cierres, y por lo que pueda entrar por una puerta que
    no pase por el modelo —una carga masiva con `bulk_create`, una migración de
    datos, un `update()` sobre `cargo` o `tipo`—.

    Es Crítica por el mismo motivo que un contrato vencido: alguien cobra
    ocupando una plaza que el organismo no aprobó, y eso descuadra el Anexo 17 y
    el 17.1 contra la plantilla real que se entrega.
    """

    codigo = 'CTR-020'
    nombre = 'Contrato que ocupa plaza sobre un cargo fuera de la plantilla aprobada'
    criticidad = CRITICIDAD_CRITICA

    descripcion = (
        'Busca los contratos cuyo tipo ocupa plaza —hoy, Indeterminado— asignados a '
        'un cargo marcado como fuera de la plantilla aprobada.')
    causa_probable = (
        'El contrato se creó antes de que la comprobación existiera, o se cargó por '
        'una vía que no pasa por el formulario (el admin, una importación o un '
        'script). También ocurre si el cargo se sacó de la plantilla DESPUÉS de '
        'contratar a alguien en él.')
    impacto = (
        'El trabajador ocupa una plaza que el organismo no aprobó. El Anexo 17 y el '
        '17.1 cuentan esa plaza fuera de la plantilla oficial mientras la nómina la '
        'paga como si estuviera dentro, así que los dos documentos dejan de cuadrar '
        'con la realidad.')
    solucion = (
        'Hay dos salidas y la correcta depende del caso, así que la decide Capital '
        'Humano: si la plaza NO debía existir, cambie el tipo de contrato a uno que '
        'no ocupe plaza (Determinado o Adiestrado). Si la plaza SÍ hace falta, '
        'apruebe el cargo en la plantilla desde el Gestor de Plantilla. Aprobar un '
        'cargo solo para silenciar el aviso es la salida equivocada.')

    def ejecutar(self, contexto):
        columnas = self.COLUMNAS_BASE + (
            'tipo__descripcion', 'cargo__ncargo__descripcion',
            'cargo__departamento__descripcion')

        filas = (self.base_queryset()
                 .filter(tipo__ocupa_plaza=True, cargo__en_plantilla=False)
                 .values(*columnas)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            cargo = fila.get('cargo__ncargo__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'contrato fijo en «{cargo}», fuera de plantilla'),
                detalle=(
                    f'El contrato es de tipo «{fila.get("tipo__descripcion") or "—"}», '
                    f'que ocupa plaza, pero el cargo «{cargo}» está marcado como fuera '
                    f'de la plantilla aprobada.'),
                datos={
                    'tipo_de_contrato': fila.get('tipo__descripcion') or '—',
                    'cargo': cargo,
                    'departamento': fila.get('cargo__departamento__descripcion') or '—',
                },
                unidad_organizativa_id=self.unidad_de(fila),
                campo_formulario='tipo',
            )


class ContratoConFechaFutura(ReglaContratos):
    """CTR-024: F. de Contratación o F. Alta Entidad posterior a hoy.

    Desde el 23-10-2026 (decisión de RRHH) ninguna de las dos puede ser futura; los
    formularios ya lo impiden. Las fechas de vencimiento quedan fuera: son futuras
    por naturaleza.
    """

    codigo = 'CTR-024'
    nombre = 'Contrato con fecha futura'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Busca contratos con la F. de Contratación o la F. Alta Entidad posterior al '
        'día de hoy.')
    causa_probable = (
        'Se escribió mal el año o el mes, o se registró por adelantado un contrato que '
        'todavía no ha empezado. Hasta el 23-10-2026 Orbith lo aceptaba.')
    impacto = (
        'El trabajador figura contratado antes de tiempo, los años de servicio y el '
        'vencimiento salen mal, y el contrato se cuenta en un mes que aún no ha llegado.')
    solucion = (
        'Corrija la fecha desde el panel de administración (la F. de Contratación no se '
        'edita desde el formulario) junto con la de su movimiento de Alta Inicial.')

    def ejecutar(self, contexto):
        from django.utils import timezone

        hoy = timezone.localdate()
        filas = (self.base_queryset()
                 .filter(Q(fecha_alta__gt=hoy) | Q(fecha_alta_entidad__gt=hoy))
                 .values(*self.COLUMNAS_BASE, 'fecha_alta', 'fecha_alta_entidad')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            if fila.get('fecha_alta') and fila['fecha_alta'] > hoy:
                cual, fecha = 'F. de Contratación', fila['fecha_alta']
            else:
                cual, fecha = 'F. Alta Entidad', fila['fecha_alta_entidad']
            texto = f'{fecha.day:02d}/{fecha.month:02d}/{fecha.year:04d}'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'{cual} futura ({texto})'),
                detalle=f'El contrato tiene la {cual} {texto}, posterior a hoy.',
                datos={'campo': cual, 'fecha': texto},
                unidad_organizativa_id=self.unidad_de(fila),
            )
