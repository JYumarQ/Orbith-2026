"""Reglas de integridad de la plantilla y la estructura organizativa."""

from django.db.models import Count, F, Q

from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_BAJA,
    CRITICIDAD_CRITICA,
    CRITICIDAD_MEDIA,
    MODULO_ESTRUCTURA,
    TAMANO_LOTE,
)
from .base import HallazgoDetectado, ReglaBase


class ConteoDePlazasDesincronizado(ReglaBase):
    """`CargoPlantilla.cant_cubierta` no coincide con las plazas realmente ocupadas.

    `cant_cubierta` es un campo denormalizado que solo se actualiza cuando alguien
    llama a `refrescar_conteo_plazas()`, es decir al guardar un contrato. Cualquier
    escritura con `.update()`, cualquier importación o cualquier borrado por SQL lo
    deja desfasado sin que nada avise.
    """

    codigo = 'EST-001'
    nombre = 'Conteo de plazas cubiertas desincronizado'
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_ALTA
    modelo = 'strorganizativa.CargoPlantilla'

    descripcion = (
        'Compara el número de plazas cubiertas que tiene guardado el cargo con las que '
        'están ocupadas de verdad por contratos activos que ocupan plaza.')
    causa_probable = (
        'El campo guardado solo se recalcula al guardar un contrato desde el '
        'formulario. Si se modificaron contratos por importación, si se borró un '
        'contrato directamente en la base de datos, o si el proceso se interrumpió a '
        'medias, el número se queda con el valor antiguo.')
    impacto = (
        'La plantilla informa mal de su ocupación: pueden aparecer plazas libres que en '
        'realidad están ocupadas (y permitir una contratación de más) o plazas '
        'ocupadas que están libres (y bloquear una contratación legítima). El Anexo 17 '
        'y los informes de plantilla arrastran el mismo error.')
    solucion = (
        'Abra el cargo y guárdelo: al guardar, Orbith recalcula el número de plazas '
        'cubiertas. Si son muchos cargos, revise primero por qué se desincronizaron, '
        'porque volverá a ocurrir.')

    def ejecutar(self, contexto):
        # Todo el trabajo lo hace PostgreSQL: el LEFT JOIN, el conteo condicional y la
        # comparación contra el campo guardado. A Python solo llegan las filas
        # DISCREPANTES, que en un sistema sano son cero.
        #
        # `calta` es el nombre inverso de consulta de `CAlta.cargo` (ese ForeignKey no
        # define related_name, así que Django usa el nombre del modelo en minúsculas).
        # `distinct=True` es obligatorio: el JOIN hacia `tipo` puede multiplicar filas.
        filas = (self.base_queryset()
                 .annotate(cubierta_real=Count(
                     'calta', distinct=True,
                     filter=Q(calta__aspirante__estado='ACTIVO',
                              calta__tipo__ocupa_plaza=True)))
                 .exclude(cubierta_real=F('cant_cubierta'))
                 .values(
                     'id', 'cant_cubierta', 'cubierta_real', 'cant_aprobada', 'activo',
                     'ncargo__descripcion', 'departamento__descripcion',
                     'departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            cargo = fila.get('ncargo__descripcion') or 'Cargo sin descripción'
            departamento = fila.get('departamento__descripcion') or '—'
            guardado = fila.get('cant_cubierta') or 0
            real = fila.get('cubierta_real') or 0
            diferencia = real - guardado

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=(f'{cargo} · {departamento} · plazas cubiertas '
                        f'{guardado} guardadas frente a {real} reales'),
                detalle=(
                    f'El cargo tiene guardadas {guardado} plazas cubiertas, pero hay '
                    f'{real} contratos activos que ocupan plaza. '
                    + ('El sistema cree que hay más plazas libres de las que hay.'
                       if diferencia > 0 else
                       'El sistema cree que hay menos plazas libres de las que hay.')),
                datos={
                    'cargo': cargo,
                    'departamento': departamento,
                    'plazas_aprobadas': fila.get('cant_aprobada') or 0,
                    'plazas_cubiertas_guardadas': guardado,
                    'plazas_cubiertas_reales': real,
                    'diferencia': diferencia,
                },
                unidad_organizativa_id=fila.get('departamento__unidad_organizativa_id'),
            )


class CargoFuncionarioYDesignado(ReglaBase):
    codigo = 'EST-002'
    nombre = 'Cargo marcado como funcionario y designado a la vez'
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_ALTA
    modelo = 'strorganizativa.CargoPlantilla'

    descripcion = (
        'Un cargo no puede ser funcionario y designado al mismo tiempo: son '
        'dos categorías excluyentes.')
    causa_probable = (
        'El formulario del cargo lo impide (`clean()` lo rechaza), así que '
        'solo puede ocurrir en una fila escrita sin pasar por él: una '
        'importación o una actualización masiva.')
    impacto = (
        'Los informes que clasifican la plantilla por este criterio cuentan '
        'el cargo en las dos categorías a la vez, y las reglas de negocio que '
        'dependen de una categoría excluyente (como los códigos de '
        'funcionario y designado del contrato) quedan indefinidas.')
    solucion = 'Abra el cargo y desmarque la casilla que no corresponde.'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(funcionario=True, designado=True)
                 .values('id', 'ncargo__descripcion', 'departamento__descripcion',
                         'departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            cargo = fila.get('ncargo__descripcion') or 'Cargo sin descripción'
            departamento = fila.get('departamento__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{cargo} · {departamento} · funcionario y designado a la vez',
                detalle=(
                    'El cargo tiene marcadas a la vez las casillas «Funcionario» '
                    'y «Designado», que deberían ser excluyentes.'),
                datos={'cargo': cargo, 'departamento': departamento,
                       'funcionario': 'Sí', 'designado': 'Sí'},
                unidad_organizativa_id=fila.get('departamento__unidad_organizativa_id'),
            )


class GrupoDeNominaDesincronizadoDelPadre(ReglaBase):
    codigo = 'EST-003'
    nombre = 'Grupo de nómina distinto al de la unidad principal'
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_MEDIA
    modelo = 'strorganizativa.UnidadOrganizativa'

    descripcion = (
        'Una subunidad debe compartir el grupo de nómina de la unidad '
        'principal de la que depende.')
    causa_probable = (
        '`UnidadOrganizativa.save()` propaga el grupo de nómina a sus '
        'subunidades cada vez que se guarda la unidad principal, pero solo en '
        'ese momento. Si el grupo de nómina de una subunidad se cambió '
        'directamente (fuera del formulario) después de la última vez que se '
        'guardó su unidad principal, queda desincronizado.')
    impacto = (
        'Los informes que agrupan la nómina por este campo mezclan '
        'trabajadores de la misma rama organizativa en grupos distintos.')
    solucion = (
        'Abra la unidad principal y guárdela: al guardar, Orbith propaga su '
        'grupo de nómina a todas sus subunidades.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(padre__isnull=False)
                 .exclude(grupo_nomina=F('padre__grupo_nomina'))
                 .values('codigo_interno', 'descripcion', 'grupo_nomina',
                         'padre__descripcion', 'padre__grupo_nomina')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            descripcion = fila.get('descripcion') or 'Unidad sin descripción'
            padre = fila.get('padre__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['codigo_interno']),
                titulo=(f'{descripcion} (código {fila["codigo_interno"]}) · grupo de '
                        f'nómina distinto al de «{padre}»'),
                detalle=(
                    f'Esta unidad tiene grupo de nómina '
                    f'«{fila.get("grupo_nomina") or "—"}», pero su unidad principal '
                    f'«{padre}» tiene «{fila.get("padre__grupo_nomina") or "—"}».'),
                datos={
                    'grupo_de_nomina_propio': fila.get('grupo_nomina') or '—',
                    'unidad_principal': padre,
                    'grupo_de_nomina_del_principal': fila.get('padre__grupo_nomina') or '—',
                },
                unidad_organizativa_id=fila['codigo_interno'],
            )


class ReglaOrdenDePrioridad(ReglaBase):
    """Base común de las tres reglas de orden de prioridad vacío.

    Es el mismo problema en tres modelos distintos de la jerarquía de plantilla, y
    comparten descripción, causa, impacto y solución palabra por palabra. Pero NO
    pueden ser una sola clase con `clave_extra`: `reconciliar_regla()` resuelve el
    `content_type` UNA vez por regla a partir de `self.modelo`, así que todos los
    hallazgos que produce una misma regla tienen que apuntar a instancias del MISMO
    modelo. Tres modelos distintos exigen tres reglas distintas (con el mismo texto),
    no una regla con tres `clave_extra`.
    """

    abstracta = True
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_BAJA

    descripcion = 'Busca registros de la plantilla sin su orden de prioridad asignado.'
    causa_probable = (
        'El campo es opcional a nivel de base de datos, así que puede quedar '
        'vacío al crear el registro.')
    impacto = (
        'El orden de prioridad decide en qué posición aparece el registro en '
        'el organigrama, en el Gestor de Plantilla y en el Anexo 17. Sin él, '
        'su posición en esos listados depende del orden en que la base de '
        'datos devuelva las filas, que no está garantizado.')
    solucion = 'Abra el registro y asigne su orden de prioridad dentro de su nivel.'


class UnidadSinOrdenDePrioridad(ReglaOrdenDePrioridad):
    codigo = 'EST-004'
    nombre = 'Unidad organizativa sin orden de prioridad'
    modelo = 'strorganizativa.UnidadOrganizativa'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(orden_informe__isnull=True)
                 .values('codigo_interno', 'descripcion')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            descripcion = fila.get('descripcion') or 'Unidad sin descripción'
            yield HallazgoDetectado(
                object_id=str(fila['codigo_interno']),
                titulo=(f'{descripcion} (código {fila["codigo_interno"]}) · sin '
                        f'orden de prioridad'),
                detalle='Esta unidad organizativa no tiene asignado su orden de prioridad.',
                datos={'tipo_de_registro': 'Unidad organizativa', 'nombre': descripcion},
                unidad_organizativa_id=fila['codigo_interno'],
            )


class DepartamentoSinOrdenDePrioridad(ReglaOrdenDePrioridad):
    codigo = 'EST-005'
    nombre = 'Departamento sin orden de prioridad'
    modelo = 'strorganizativa.Departamento'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(orden_informe__isnull=True)
                 .values('id', 'descripcion', 'unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            descripcion = fila.get('descripcion') or 'Departamento sin descripción'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{descripcion} · sin orden de prioridad',
                detalle='Este departamento no tiene asignado su orden de prioridad.',
                datos={'tipo_de_registro': 'Departamento', 'nombre': descripcion},
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class CargoSinOrdenDePrioridad(ReglaOrdenDePrioridad):
    codigo = 'EST-006'
    nombre = 'Cargo sin orden de prioridad'
    modelo = 'strorganizativa.CargoPlantilla'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(orden_informe__isnull=True)
                 .values('id', 'ncargo__descripcion', 'departamento__descripcion',
                         'departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))
        for fila in filas:
            cargo = fila.get('ncargo__descripcion') or 'Cargo sin descripción'
            departamento = fila.get('departamento__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{cargo} · {departamento} · sin orden de prioridad',
                detalle='Este cargo no tiene asignado su orden de prioridad.',
                datos={'tipo_de_registro': 'Cargo', 'nombre': cargo,
                       'departamento': departamento},
                unidad_organizativa_id=fila.get('departamento__unidad_organizativa_id'),
            )


class CargoSinNivelDePreparacion(ReglaBase):
    """El cargo no tiene asignado su nivel de preparación.

    El campo es opcional en la base de datos (`null=True, blank=True`) y el
    formulario no lo exige, así que la única forma de saber cuántos cargos lo tienen
    sin rellenar es preguntárselo a la plantilla entera — que es justo lo que hace
    esta regla.
    """

    codigo = 'EST-007'
    nombre = 'Cargo sin nivel de preparación'
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_BAJA
    modelo = 'strorganizativa.CargoPlantilla'

    descripcion = (
        'Busca los cargos de la plantilla que no tienen asignado su nivel de '
        'preparación.')
    causa_probable = (
        'El campo no es obligatorio ni en la base de datos ni en el formulario del '
        'cargo, así que puede quedarse vacío al crear el cargo y nada avisa después.')
    impacto = (
        'El nivel de preparación es el requisito de formación que exige el cargo. Sin '
        'él, el Anexo 17 y los informes de plantilla salen con la columna en blanco, y '
        'no se puede comparar lo que el cargo exige con la preparación real del '
        'trabajador que lo ocupa.')
    solucion = (
        'Abra el cargo y seleccione su nivel de preparación en el desplegable '
        '«Nivel de Preparación».')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(nivel_preparacion__isnull=True)
                 .values('id', 'ncargo__descripcion', 'departamento__descripcion',
                         'departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            cargo = fila.get('ncargo__descripcion') or 'Cargo sin descripción'
            departamento = fila.get('departamento__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{cargo} · {departamento} · sin nivel de preparación',
                detalle=(
                    'Este cargo no tiene asignado el nivel de preparación que exige '
                    'para desempeñarlo.'),
                datos={'cargo': cargo, 'departamento': departamento,
                       'nivel_de_preparacion': 'Vacío'},
                unidad_organizativa_id=fila.get('departamento__unidad_organizativa_id'),
                # Lleva el panel de advertencias directo al desplegable del formulario.
                campo_formulario='nivel_preparacion',
            )


class CargoSinRol(ReglaBase):
    """Un cargo que no es de Cuadro, con trabajadores, no tiene rol de pago.

    El rol es del cargo (decisión de RRHH del 23-10-2026): sin él, ninguno de sus
    trabajadores de salario dinámico tiene salario calculable. Pasa sobre todo cuando
    el nomenclador del cargo deja de ser Cuadro (un cuadro no lleva rol), o cuando el
    cargo se guardó sin rol desde fuera del formulario.
    """

    codigo = 'EST-008'
    nombre = 'Cargo que no es de Cuadro sin rol asignado'
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_CRITICA
    modelo = 'strorganizativa.CargoPlantilla'

    descripcion = (
        'Busca cargos con trabajadores cuya categoría ocupacional no es de Cuadro y '
        'que no tienen rol de pago (Decisorio, Fundamental o Apoyo).')
    causa_probable = (
        'El nomenclador del cargo dejó de ser de Cuadro (un cuadro no lleva rol), o '
        'el cargo se guardó sin rol desde el Admin o una importación.')
    impacto = (
        'Sus trabajadores de salario dinámico se quedan sin salario calculable en '
        'las pantallas, los informes, el Word del contrato y la Pre-Nómina.')
    solucion = (
        'Abra el cargo en el Gestor de Plantilla y elija su rol. Después, revise que '
        'sus contratos tengan tridente.')

    def ejecutar(self, contexto):
        from django.apps import apps

        NCargo = apps.get_model('nomencladores', 'NCargo')
        filas = (self.base_queryset()
                 .filter(rol__isnull=True, calta__isnull=False)
                 .exclude(ncargo__cat_ocupacional__in=NCargo.CATEGORIAS_CUADRO)
                 .annotate(trabajadores=Count('calta', distinct=True))
                 .values('id', 'ncargo__descripcion', 'departamento__descripcion',
                         'departamento__unidad_organizativa_id', 'trabajadores')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            cargo = fila.get('ncargo__descripcion') or 'Cargo sin descripción'
            departamento = fila.get('departamento__descripcion') or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{cargo} · {departamento} · sin rol de pago',
                detalle=(f'El cargo no es de Cuadro y no tiene rol: sus trabajadores de '
                         f'salario dinámico no tienen salario calculable.'),
                datos={'cargo': cargo, 'departamento': departamento},
                unidad_organizativa_id=fila.get('departamento__unidad_organizativa_id'),
                campo_formulario='rol',
            )


class GrupoDeNominaRepetido(ReglaBase):
    """EST-009 (24-10-2026): dos unidades que no son subunidades con el mismo grupo
    de nómina. Solo lo comparten una unidad principal y sus subunidades, que lo
    heredan (EST-003 vigila esa herencia). El formulario y el importador ya no lo
    dejan repetir; esta regla encuentra los repetidos que ya existían."""

    codigo = 'EST-009'
    nombre = 'Grupo de nómina repetido en dos unidades'
    modulo = MODULO_ESTRUCTURA
    criticidad = CRITICIDAD_MEDIA
    modelo = 'strorganizativa.UnidadOrganizativa'

    descripcion = (
        'Busca unidades principales o normales que comparten el mismo grupo de nómina. '
        'Solo debe repetirse entre una unidad principal y sus subunidades.')
    causa_probable = (
        'Hasta el 24-10-2026 el formulario de unidades no lo impedía, o el grupo se '
        'escribió por error al crear la unidad.')
    impacto = (
        'Los informes y la Pre-Nómina que agrupan por grupo de nómina juntarían a los '
        'trabajadores de unidades distintas en un mismo grupo.')
    solucion = (
        'Abra cada unidad del aviso y póngale su grupo de nómina correcto, distinto del '
        'de las demás unidades. También se puede corregir de una vez con «Exportar Excel» '
        'e «Importar Excel» en el admin (Unidades Organizativas).')

    def ejecutar(self, contexto):
        no_subunidades = self.base_queryset().filter(grupo_nomina__isnull=False).exclude(
            tipo__es_subunidad=True)
        repetidos = set(no_subunidades.values('grupo_nomina').annotate(n=Count('pk'))
                        .filter(n__gt=1).values_list('grupo_nomina', flat=True))
        if not repetidos:
            return
        filas = list(no_subunidades.filter(grupo_nomina__in=repetidos)
                     .values('codigo_interno', 'descripcion', 'grupo_nomina')
                     .order_by('grupo_nomina', 'descripcion'))
        por_grupo = {}
        for fila in filas:
            por_grupo.setdefault(fila['grupo_nomina'], []).append(fila['descripcion'])
        for fila in filas:
            otras = [n for n in por_grupo[fila['grupo_nomina']] if n != fila['descripcion']]
            yield HallazgoDetectado(
                object_id=str(fila['codigo_interno']),
                titulo=(f'{fila["descripcion"]} (código {fila["codigo_interno"]}) · grupo de nómina '
                        f'{fila["grupo_nomina"]} repetido'),
                detalle=(f'Tiene el grupo de nómina {fila["grupo_nomina"]}, igual que '
                         f'{", ".join("«%s»" % n for n in otras)}.'),
                datos={'grupo_de_nomina': fila['grupo_nomina'],
                       'tambien_lo_tienen': ', '.join(otras)},
                unidad_organizativa_id=fila['codigo_interno'],
            )
