"""Reglas del Calendario de Pre-Nómina: jornadas asignadas y horas del período.

Desde que las horas del mes salen del Calendario de Pago
(`prenomina/servicios.py::crear_reporte`), hay dos huecos que no se notan hasta
el momento de montar la nómina, que es el peor momento posible para descubrirlos:

* un trabajador activo al que nadie le asignó jornada;
* un período creado pero sin horas, ya sea porque no se le añadió ningún
  calendario o porque las quincenas se quedaron en cero.

Ambos casos los rechaza `crear_reporte()`, pero solo cuando el usuario ya está
intentando crear el reporte. Estas reglas los sacan antes, con su causa y su
solución, que es exactamente para lo que existe Subsanación.

**Son reglas por usuario, no globales.** Los calendarios de Pre-Nómina son
personales, así que un período «vacío» solo lo es para su dueño. Los hallazgos
llevan el nombre del usuario en el título para que se entienda de quién es el
período, y no se apuntan a ninguna Unidad Organizativa porque no pertenecen a
ninguna.
"""

from django.apps import apps

from ..constantes import (CRITICIDAD_ALTA, CRITICIDAD_MEDIA, MODULO_NOMINA,
                          TAMANO_LOTE)
from ..formato import referencia_contrato
from .base import HallazgoDetectado, ReglaBase


class TrabajadorSinJornada(ReglaBase):
    """Trabajadores activos sin calendario asignado.

    Se restringe a los que tienen contrato **activo**: un trabajador de baja no
    entra en ninguna nómina, así que exigirle jornada sería ruido.
    """

    codigo = 'CAL-101'
    nombre = 'Trabajador activo sin jornada asignada'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_ALTA
    modelo = 'contratos.CAlta'

    descripcion = (
        'Busca trabajadores con contrato activo a los que no se les ha asignado '
        'ninguna jornada en Pre-Nómina → Asignar Calendario.')
    causa_probable = (
        'El trabajador se dio de alta después de la última asignación masiva de '
        'calendarios, o cambió de unidad organizativa y quedó fuera del listado '
        'que se asignó en su momento. También ocurre con las altas importadas, '
        'que no pasan por esa pantalla.')
    impacto = (
        'Sin jornada no hay horas del mes, y sin horas del mes no se puede '
        'calcular lo que le corresponde cobrar. Orbith se niega a crear el '
        'reporte de pago de toda su unidad mientras quede un solo trabajador '
        'así, de modo que uno sin asignar bloquea la nómina de sus compañeros.')
    solucion = (
        'Abra Pre-Nómina → Asignar Calendario, elija la Unidad Organizativa del '
        'trabajador, márquelo en la lista y pulse «Asignar calendario». Puede '
        'seleccionar varios a la vez con la casilla «Todos» si le falta la '
        'asignación a toda la unidad.')

    def ejecutar(self, contexto):
        CAlta = apps.get_model('contratos', 'CAlta')
        Calendario = apps.get_model('prenomina', 'Calendario')

        # Si no existe ni un solo calendario en todo el sistema, el módulo aún no
        # se ha empezado a usar: marcar entonces a toda la plantilla sería un
        # muro de hallazgos que no dice nada útil —nadie ha podido asignar nada
        # todavía—. La regla entra en juego en cuanto alguien crea su primera
        # jornada, que es cuando la asignación pasa a ser exigible.
        if not Calendario.objects.exists():
            return

        filas = (CAlta.objects
                 .filter(aspirante__estado='ACTIVO',
                         asignacion_calendario__isnull=True)
                 .values('id', 'no_expediente',
                         'aspirante__nombre', 'aspirante__papellido',
                         'aspirante__sapellido', 'aspirante__doc_identidad',
                         'cargo__ncargo__descripcion',
                         'cargo__departamento__descripcion',
                         'cargo__departamento__unidad_organizativa_id',
                         'cargo__departamento__unidad_organizativa__descripcion')
                 .iterator())

        for fila in filas:
            referencia = referencia_contrato(
                fila.get('aspirante__nombre'), fila.get('aspirante__papellido'),
                fila.get('aspirante__sapellido'),
                fila.get('aspirante__doc_identidad'),
                fila.get('no_expediente'))
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{referencia} · sin jornada asignada',
                detalle=(
                    'El trabajador tiene contrato activo pero no se le ha '
                    'asignado ningún calendario de jornada, así que Orbith no '
                    'sabe cuántas horas al mes le corresponden.'),
                datos={
                    'cargo': fila.get('cargo__ncargo__descripcion') or 'Sin cargo',
                    'departamento': (
                        fila.get('cargo__departamento__descripcion') or 'Sin departamento'),
                    'unidad_organizativa': (
                        fila.get('cargo__departamento__unidad_organizativa__descripcion')
                        or 'Sin unidad'),
                    'jornada_asignada': 'Ninguna',
                },
                unidad_organizativa_id=fila.get(
                    'cargo__departamento__unidad_organizativa_id'),
            )


class PeriodoSinHoras(ReglaBase):
    """Calendarios de Pago abiertos que no definen horas utilizables.

    Dos formas del mismo problema, separadas por `clave_extra` para que cada una
    tenga su propio hallazgo y se puedan resolver por separado:

    * `sin-lineas`: el período existe pero no se le añadió ningún calendario.
    * `en-cero`: tiene calendarios, pero todas sus quincenas están a cero.

    **Solo se miran los períodos abiertos.** Uno cerrado es histórico: puede
    tener ceros legítimos y ya no se puede corregir, así que señalarlo sería
    pedir algo imposible.
    """

    codigo = 'CAL-102'
    nombre = 'Calendario de Pago sin horas definidas'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_MEDIA
    modelo = 'prenomina.CalendarioPago'

    descripcion = (
        'Comprueba que cada Calendario de Pago abierto tenga al menos una '
        'jornada con horas mayores que cero.')
    causa_probable = (
        'El período se creó y se dejó a medias: falta pulsar «Seleccionar '
        'Calendario» para añadirle las jornadas, o se añadieron pero nadie llegó '
        'a escribir las horas de las quincenas.')
    impacto = (
        'Un período así parece montado pero no sirve: los reportes de pago de '
        'ese mes no se pueden crear, o saldrían con todos los trabajadores a '
        'cero horas. Un cero no se nota al revisar, y el error aparecería en la '
        'nómina ya cerrada.')
    solucion = (
        'Abra Pre-Nómina → Calendario, sitúese en ese año y mes y use '
        '«Seleccionar Calendario» para añadir las jornadas que se paguen ese '
        'mes. Después escriba las horas de cada quincena con doble clic sobre '
        'la celda correspondiente.')

    def ejecutar(self, contexto):
        CalendarioPago = apps.get_model('prenomina', 'CalendarioPago')

        # `chunk_size` es obligatorio al combinar `iterator()` con
        # `prefetch_related()`: sin él Django no sabe de cuántas filas resolver
        # las relaciones de golpe y se niega.
        periodos = (CalendarioPago.objects
                    .filter(cerrado=False)
                    .select_related('usuario')
                    .prefetch_related('detalles')
                    .iterator(chunk_size=TAMANO_LOTE))

        for periodo in periodos:
            detalles = list(periodo.detalles.all())
            duenno = periodo.usuario.get_full_name() or periodo.usuario.get_username()

            if not detalles:
                yield HallazgoDetectado(
                    object_id=str(periodo.pk),
                    clave_extra='sin-lineas',
                    titulo=(f'{periodo.etiqueta} de {duenno} · sin ninguna '
                            f'jornada añadida'),
                    detalle=(
                        'El Calendario de Pago existe pero no tiene ninguna '
                        'jornada, así que no define horas para ningún trabajador.'),
                    datos={
                        'usuario': duenno,
                        'periodo': periodo.etiqueta,
                        'jornadas_incluidas': '0',
                    },
                )
                continue

            con_horas = [d for d in detalles if d.horas_mes > 0]
            if not con_horas:
                yield HallazgoDetectado(
                    object_id=str(periodo.pk),
                    clave_extra='en-cero',
                    titulo=(f'{periodo.etiqueta} de {duenno} · todas las '
                            f'jornadas están en cero horas'),
                    detalle=(
                        f'El período tiene {len(detalles)} jornada'
                        f'{"s" if len(detalles) != 1 else ""}, pero ninguna '
                        f'tiene horas: las dos quincenas están a cero en todas.'),
                    datos={
                        'usuario': duenno,
                        'periodo': periodo.etiqueta,
                        'jornadas_incluidas': str(len(detalles)),
                        'jornadas_con_horas': '0',
                    },
                )
