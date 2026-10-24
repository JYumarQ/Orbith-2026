"""Reglas de nómina e históricos: salario cacheado y cadena de movimientos."""

from decimal import Decimal

from django.apps import apps
from datetime import date

from django.db.models import Exists, F, OuterRef, Q, Subquery, Window
from django.db.models.functions import Lag

from ..calculos import COLUMNAS_SALARIO, construir_indice_salarios, salario_esperado
from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_CRITICA,
    CRITICIDAD_INFORMATIVA,
    CRITICIDAD_MEDIA,
    MODULO_NOMINA,
    TAMANO_LOTE,
)
from ..formato import referencia_contrato, referencia_trabajador
from .base import HallazgoDetectado, ReglaBase, restringir


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

        filas = (restringir(CAlta.objects.all(), 'contratos.calta')
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
    criticidad = CRITICIDAD_CRITICA

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
    """Movimiento que DEBERÍA tener contrato y no lo tiene.

    La pregunta que responde esta regla no es «¿este movimiento tiene `contrato` en
    blanco?», sino «¿existe un contrato vivo al que este movimiento debería estar
    asociado y no lo está?». Son preguntas distintas:

      * Un movimiento de baja sin contrato es normal: se crea así a propósito porque el
        contrato se borra justo después (véase `TIPO_MOVIMIENTO_BAJA` más arriba).
      * Un movimiento sin contrato de un trabajador que sigue de baja HOY —sin ningún
        `CAlta` vivo con su mismo número de expediente— tampoco es un defecto: es el
        estado normal de alguien que no está recontratado. No hay ningún contrato al
        que asociarlo, así que no hay nada que un usuario pueda corregir. Si se le
        recontrata reutilizando el expediente, `CAlta.save()` lo reengancha solo (véase
        `contratos/models.py`) y el caso nunca llega a producir hallazgo.
      * Un movimiento sin contrato mientras SÍ existe un `CAlta` vivo del mismo
        aspirante con el mismo expediente —el reenganche automático no llegó a
        ocurrir, por ejemplo por una importación, una edición masiva o datos
        heredados de antes de que existiera ese mecanismo— es el único caso realmente
        accionable, y es el único que se reporta.

    El criterio de «contrato vivo al que correspondería» tiene que coincidir exactamente
    con `CAlta.movimientos_huerfanos_reenganchables()` en `contratos/models.py`: mismo
    aspirante y mismo `no_expediente`. Subsanación no puede importar modelos de negocio
    directamente (por eso usa `apps.get_model`), así que la condición está reimplementada
    aquí; si ese criterio cambia en el modelo, hay que cambiarlo también aquí.
    """

    codigo = 'MOV-002'
    nombre = 'Movimiento del histórico desconectado de su contrato'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Busca movimientos que no son de baja y deberían estar asociados a un contrato '
        'vivo del mismo trabajador y no lo están, o que no tienen trabajador asociado. '
        'Se excluyen los movimientos de baja (sin contrato por diseño) y los casos en '
        'los que el trabajador no tiene ningún contrato vivo con ese expediente: eso no '
        'es un dato incorrecto, es el estado normal de alguien dado de baja.')
    causa_probable = (
        'El trabajador fue dado de baja —lo que borra su contrato— y después se volvió a '
        'contratar reutilizando el mismo número de expediente, pero el movimiento no se '
        'reenganchó al contrato nuevo (por ejemplo, por una importación o una edición '
        'hecha directamente en la base de datos, sin pasar por el guardado normal).')
    impacto = (
        'Esos movimientos no aparecen al abrir el histórico del trabajador desde su '
        'contrato actual, aunque sigan contando en el listado de movimientos de nómina. '
        'Es información que existe y a la que ya no se llega por el camino normal, así '
        'que el histórico que se consulta parece más corto de lo que realmente es.')
    solucion = (
        'Un Administrador puede pulsar «Reenganchar al contrato» en este hallazgo: '
        'enlaza el movimiento al contrato vivo del mismo trabajador con el mismo número '
        'de expediente, y queda en Auditoría. Para muchos casos a la vez existe el '
        'comando de gestión «reenganchar_movimientos» (use --dry-run primero). Estos '
        'movimientos no se editan desde ningún formulario: son el registro de lo que '
        'ocurrió.')

    correccion_etiqueta = 'Reenganchar al contrato'
    correccion_aviso = (
        'Se enlazará este movimiento al contrato vivo del mismo trabajador con el mismo '
        'número de expediente. El cambio queda registrado en Auditoría.')

    def corregir(self, hallazgo):
        from contratos.correcciones import reenganchar_movimiento
        return reenganchar_movimiento(hallazgo.object_id)

    def ejecutar(self, contexto):
        from django.apps import apps
        from django.db.models import Exists, OuterRef, Q

        CAlta = apps.get_model('contratos', 'CAlta')

        # Mismo criterio que `CAlta.movimientos_huerfanos_reenganchables()`: mismo
        # aspirante y mismo `no_expediente` exacto. `no_expediente` es único entre los
        # contratos vivos, así que esta subconsulta nunca puede encontrar más de una fila.
        contrato_vivo_correspondiente = CAlta.objects.filter(
            aspirante_id=OuterRef('aspirante_id'),
            no_expediente=OuterRef('no_expediente'),
        )

        filas = (self.base_queryset()
                 # Se excluyen las bajas: están sin contrato por diseño.
                 .exclude(tipo_movimiento__iexact=TIPO_MOVIMIENTO_BAJA)
                 .filter(
                     # Sin trabajador: problema estructural, se reporta siempre.
                     Q(aspirante__isnull=True)
                     # Con trabajador: solo se reporta si de verdad existe un contrato
                     # vivo al que debería estar enlazado y no lo está. Si el trabajador
                     # no tiene ningún contrato vivo con ese expediente, no es un
                     # defecto: es el estado normal de alguien dado de baja.
                     | Q(contrato__isnull=True, aspirante__isnull=False)
                     & ~Q(no_expediente__isnull=True) & ~Q(no_expediente='')
                     & Exists(contrato_vivo_correspondiente)
                 )
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


class MovimientoConOtroExpediente(ReglaMovimientos):
    """Movimiento enlazado a su contrato, pero con otro número de expediente.

    Pasaba al corregir el expediente de un contrato: sus movimientos se quedaban con
    el número viejo. Desde el 12-10-2026 `CAlta.save()` les lleva el nuevo, así que
    esta regla encuentra los casos de antes (y los que lleguen por otra vía, como el
    panel de administración o una importación).
    """

    codigo = 'MOV-008'
    nombre = 'Movimiento con un expediente distinto al de su contrato'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Busca movimientos enlazados a un contrato cuyo número de expediente no '
        'coincide con el del contrato.')
    causa_probable = (
        'Se corrigió el número de expediente del contrato después de crear el '
        'movimiento, y el movimiento conservó el número anterior.')
    impacto = (
        'El movimiento no aparece al buscar por el expediente del trabajador '
        '(«E:» en los buscadores), y el documento del movimiento de nómina sale con '
        'un número de expediente que ya no es el suyo.')
    solucion = (
        'Un Administrador puede pulsar «Corregir expediente» en este hallazgo: el '
        'movimiento toma el número de expediente de su contrato, y queda en Auditoría. '
        'Antes, compruebe en el contrato que su número de expediente es el correcto.')

    correccion_etiqueta = 'Corregir expediente'
    correccion_aviso = (
        'El movimiento tomará el número de expediente de su contrato. El cambio queda '
        'registrado en Auditoría.')

    def corregir(self, hallazgo):
        from contratos.correcciones import alinear_expediente_movimiento
        return alinear_expediente_movimiento(hallazgo.object_id)

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(contrato__isnull=False)
                 # `exclude` y no `filter(~Q)`: así entran también los movimientos
                 # con el expediente vacío, que tampoco coinciden.
                 .exclude(no_expediente=F('contrato__no_expediente'))
                 .values('id', 'no_expediente', 'fecha_efectiva', 'tipo_movimiento',
                         'contrato__no_expediente',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'unidad_nueva_fk_id', 'unidad_anterior_fk_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            del_movimiento = fila.get('no_expediente') or '—'
            del_contrato = fila['contrato__no_expediente']
            efectiva = fila.get('fecha_efectiva')
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila, f'el movimiento tiene el expediente {del_movimiento} y su '
                          f'contrato el {del_contrato}'),
                detalle=(
                    f'El movimiento está enlazado a un contrato con el expediente '
                    f'{del_contrato}, pero él tiene guardado el {del_movimiento}.'),
                datos={
                    'fecha_efectiva': efectiva.strftime('%d/%m/%Y') if efectiva else '—',
                    'tipo_de_movimiento': fila.get('tipo_movimiento') or '—',
                    'expediente_del_movimiento': del_movimiento,
                    'expediente_del_contrato': del_contrato,
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


class BajaSinMovimientosNiCargo(ReglaBase):
    """Caso real reportado: se eliminó desde el Admin de Django TODO el histórico de
    movimientos (`TMovimiento`) de un trabajador. `contratos.models._al_eliminar_movimiento`
    reacciona a eso cerrando el ciclo (si tenía `CAlta` vigente, la cierra; si no,
    marca al aspirante 'BAJA' directamente) y crea un `CBaja` SIN `cargo`, porque ya
    no queda ningún rastro documental de en qué cargo o Unidad Organizativa trabajó.
    Esta regla es la que hace visible esa pérdida de información en Subsanación."""

    codigo = 'MOV-007'
    nombre = 'Contrato en Bajas sin movimientos ni registro de cargo'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_ALTA
    modelo = 'contratos.CBaja'

    descripcion = (
        'Busca registros de Baja que no tienen cargo asignado NI ningún movimiento '
        'de nómina (TMovimiento) en el histórico del trabajador: no pertenecen a '
        'ninguna Unidad Organizativa ni Departamento.')
    causa_probable = (
        'Se eliminó por completo, desde el Admin de Django, el histórico de '
        'movimientos de nómina del trabajador (uno, varios o todos los TMovimiento), '
        'dejando la baja sin cargo, UO ni Departamento asociado.')
    impacto = (
        'El trabajador aparece en el listado de Bajas sin ninguna trazabilidad: no '
        'se puede saber qué cargo tuvo ni en qué Unidad Organizativa o Departamento '
        'trabajó. Cualquier certificación laboral o informe histórico sobre esta '
        'persona queda sin base documental.')
    solucion = (
        'Si el borrado del histórico fue un error, restáurelo desde una copia de '
        'seguridad. Si fue intencional, no hay más acción posible sobre el dato: '
        'considere documentar el motivo en las Observaciones de la Baja.')

    def ejecutar(self, contexto):
        from django.apps import apps

        TMovimiento = apps.get_model('contratos', 'TMovimiento')

        filas = (self.base_queryset()
                 .filter(cargo__isnull=True)
                 .values('id', 'no_expediente', 'aspirante_id',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            aspirante_id = fila.get('aspirante_id')
            if aspirante_id and TMovimiento.objects.filter(aspirante_id=aspirante_id).exists():
                # Sin cargo pero con histórico intacto: no es este caso (por ejemplo,
                # una baja antigua cuyo cargo se dejó sin completar a propósito).
                continue

            referencia = referencia_contrato(
                fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
                fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'),
                fila.get('no_expediente'))
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · baja sin movimientos ni cargo asociado',
                detalle=(
                    'Este registro de Baja no tiene cargo asignado ni ningún '
                    'movimiento de nómina en su histórico: no pertenece a ninguna '
                    'Unidad Organizativa.'),
                datos={
                    'expediente': fila.get('no_expediente') or '—',
                    'cargo': 'Sin cargo',
                    'movimientos_registrados': 0,
                },
                unidad_organizativa_id=None,
            )



def _fecha_texto(fecha):
    """dd/mm/aaaa a mano: con años de una cifra (0026) `strftime('%Y')` depende de
    la plataforma y en Windows sale «26» en vez de «0026»."""
    return f'{fecha.day:02d}/{fecha.month:02d}/{fecha.year:04d}'


class BajaPosteriorAlContratoVivo(ReglaBase):
    """MOV-009: una persona ACTIVA tiene una baja posterior al inicio del contrato
    que sigue teniendo (o una baja cuyo propio alta es posterior). Es imposible:
    para causar baja hay que dejar de tener el contrato vivo. Desde los
    formularios no puede ocurrir; llega por el panel de administración, una
    importación o datos de prueba (caso de «Pinga», 13-10-2026).

    Se compara con «>» y no con «>=»: causar baja y volver el MISMO día es
    legítimo (la baja del día 10 y el contrato nuevo del día 10)."""

    codigo = 'MOV-009'
    nombre = 'Baja posterior al contrato vigente del trabajador'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_ALTA
    modelo = 'contratos.CBaja'

    descripcion = (
        'Busca trabajadores activos con una baja fechada después del inicio de su '
        'contrato vigente.')
    causa_probable = (
        'La baja o el contrato se registraron o se corrigieron fuera de los formularios '
        'de Orbith (panel de administración, importación de datos), que no comprueban '
        'el orden de las fechas.')
    impacto = (
        'El histórico del trabajador queda en un orden imposible: aparece dándose de '
        'baja mientras tiene un contrato vivo. Las cifras de altas y bajas de la '
        'Dashboard y de los informes cuentan esa baja en un mes en que no ocurrió.')
    solucion = (
        'Abra el histórico del trabajador y decida qué está mal: la fecha de la baja, '
        'la del contrato vigente, o si esa baja sobra. Corríjalo desde el panel de '
        'administración. Esta regla no lo arregla sola porque hace falta decidir cuál '
        'de los datos es el bueno.')

    def ejecutar(self, contexto):
        CAlta = apps.get_model('contratos', 'CAlta')
        vivo = CAlta.objects.filter(aspirante_id=OuterRef('aspirante_id'),
                                    aspirante__estado='ACTIVO')
        filas = (self.base_queryset()
                 .filter(aspirante__estado='ACTIVO')
                 .annotate(alta_vigente=Subquery(vivo.order_by('-fecha_alta').values('fecha_alta')[:1]))
                 .filter(Q(fecha_baja__gt=F('alta_vigente')) | Q(fecha_alta__gt=F('alta_vigente')))
                 .values('id', 'no_expediente', 'fecha_alta', 'fecha_baja', 'alta_vigente',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'cargo__departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            referencia = referencia_contrato(
                fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
                fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'),
                fila.get('no_expediente'))
            vigente = _fecha_texto(fila['alta_vigente'])
            baja = _fecha_texto(fila['fecha_baja']) if fila.get('fecha_baja') else '—'
            alta = _fecha_texto(fila['fecha_alta']) if fila.get('fecha_alta') else '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · baja del {baja} posterior a su contrato vigente del {vigente}',
                detalle=(
                    f'El trabajador sigue activo con un contrato que empezó el {vigente}, '
                    f'pero tiene registrada una baja (alta {alta}, baja {baja}) posterior a esa fecha.'),
                datos={
                    'contrato_vigente_desde': vigente,
                    'alta_de_la_baja': alta,
                    'fecha_de_baja': baja,
                },
                unidad_organizativa_id=fila.get('cargo__departamento__unidad_organizativa_id'),
            )


class BajaConFechaFutura(ReglaBase):
    """MOV-010: una baja fechada después de hoy."""

    codigo = 'MOV-010'
    nombre = 'Baja con fecha futura'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_ALTA
    modelo = 'contratos.CBaja'

    descripcion = 'Busca bajas con fecha de baja posterior al día de hoy.'
    causa_probable = (
        'Se escribió mal el año o el mes de la fecha de baja, o se registró por '
        'adelantado una baja que todavía no ha ocurrido.')
    impacto = (
        'El trabajador figura como baja antes de tiempo, y la baja se cuenta en un mes '
        'que aún no ha llegado en la Dashboard, los informes y los cierres.')
    solucion = (
        'Compruebe la fecha de la baja en el histórico del trabajador. Si está mal '
        'escrita, corríjala desde el panel de administración; si la baja todavía no '
        'ha ocurrido, regístrela el día en que ocurra.')

    def ejecutar(self, contexto):
        from django.utils import timezone

        hoy = timezone.localdate()
        filas = (self.base_queryset()
                 .filter(fecha_baja__gt=hoy)
                 .values('id', 'no_expediente', 'fecha_baja',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'cargo__departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            referencia = referencia_contrato(
                fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
                fila.get('aspirante__sapellido'), fila.get('aspirante__doc_identidad'),
                fila.get('no_expediente'))
            baja = _fecha_texto(fila['fecha_baja'])
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · baja con fecha futura ({baja})',
                detalle=f'La baja está fechada el {baja}, después de hoy.',
                datos={'fecha_de_baja': baja},
                unidad_organizativa_id=fila.get('cargo__departamento__unidad_organizativa_id'),
            )


class MovimientoConAnoImposible(ReglaMovimientos):
    """MOV-011: movimiento con fecha efectiva anterior a 1900 (un «0026» tecleado
    en vez de «2026»). Complementa a CTR-017 / CTR-022, que miran el contrato."""

    codigo = 'MOV-011'
    nombre = 'Movimiento con fecha efectiva imposible'
    criticidad = CRITICIDAD_ALTA

    #: Mismo corte que `contratos.forms.ANO_MINIMO_FECHAS` (ver CTR-017).
    ANO_MINIMO = 1900

    descripcion = 'Busca movimientos de nómina con fecha efectiva de un año anterior a 1900.'
    causa_probable = (
        'Se escribió el año incompleto (0026 en vez de 2026). Hasta el 13-10-2026 el '
        'asistente de contratación lo aceptaba al crear el movimiento de alta.')
    impacto = (
        'El movimiento se ordena antes que todo el histórico del trabajador y sale con '
        'una fecha absurda en informes, documentos y en el cálculo de fechas mínimas.')
    solucion = (
        'Corrija la fecha efectiva del movimiento desde el panel de administración, '
        'escribiendo el año con cuatro cifras. Revise también el contrato: si nació del '
        'mismo asistente, su fecha de alta tendrá el mismo error (regla CTR-022).')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(fecha_efectiva__lt=date(self.ANO_MINIMO, 1, 1))
                 .values('id', 'no_expediente', 'fecha_efectiva', 'tipo_movimiento',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'unidad_nueva_fk_id', 'unidad_anterior_fk_id')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            fecha = _fecha_texto(fila['fecha_efectiva'])
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'movimiento con fecha imposible ({fecha})'),
                detalle=f'El movimiento tiene la fecha efectiva {fecha}, con un año anterior a {self.ANO_MINIMO}.',
                datos={'fecha_efectiva': fecha, 'tipo_de_movimiento': fila.get('tipo_movimiento') or '—'},
                unidad_organizativa_id=fila.get('unidad_nueva_fk_id') or fila.get('unidad_anterior_fk_id'),
            )
