"""Reglas de visibilidad sobre la estructura, la plantilla y los usuarios.

Continuación de `visibilidad.py`, que se ocupa de los trabajadores. Están en archivos
separados porque son familias distintas de registros invisibles, y así cada archivo
sigue siendo corto: añadir una regla es añadir una clase, no navegar un archivo enorme.
"""

from django.db.models import Count, Q

from ..constantes import CRITICIDAD_ALTA, MODULO_OCULTOS, TAMANO_LOTE
from .base import HallazgoDetectado, ReglaBase


class SubunidadSinPadre(ReglaBase):
    codigo = 'VIS-005'
    nombre = 'Subunidad sin unidad superior'
    modulo = MODULO_OCULTOS
    criticidad = CRITICIDAD_ALTA
    modelo = 'strorganizativa.UnidadOrganizativa'

    descripcion = (
        'Busca unidades cuyo tipo está marcado como subunidad pero que no tienen ninguna '
        'unidad superior asignada.')
    causa_probable = (
        'El formulario exige la unidad superior cuando el tipo es una subunidad, así que '
        'la fila se escribió sin pasar por él, o el tipo de unidad se cambió a subunidad '
        'después de haberla creado como principal.')
    impacto = (
        'El Gestor de Plantilla muestra en el primer nivel solo las unidades sin superior, '
        'así que esta subunidad aparece ahí como si fuera principal, fuera de su rama '
        'real. El organigrama y el Anexo 14 la sitúan en el lugar equivocado.')
    solucion = (
        'Abra la unidad y asígnele la unidad superior a la que pertenece. Si en realidad '
        'es una unidad principal, cambie su tipo de unidad.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(tipo__es_subunidad=True, padre__isnull=True)
                 .values('codigo_interno', 'descripcion', 'grupo_nomina',
                         'tipo__descripcion', 'orden_informe')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            descripcion = fila.get('descripcion') or 'Unidad sin descripción'
            tipo = fila.get('tipo__descripcion') or '—'
            yield HallazgoDetectado(
                # El pk de UnidadOrganizativa es `codigo_interno`, no `id`.
                object_id=str(fila['codigo_interno']),
                titulo=(f'{descripcion} (código {fila["codigo_interno"]}) · '
                        f'es subunidad y no tiene unidad superior'),
                detalle=(
                    f'Su tipo es «{tipo}», que está marcado como subunidad, pero no tiene '
                    f'ninguna unidad superior. Por eso aparece en el primer nivel del '
                    f'Gestor de Plantilla, como si fuera una unidad principal.'),
                datos={
                    'codigo_interno': fila['codigo_interno'],
                    'tipo_de_unidad': tipo,
                    'unidad_superior': 'Ninguna',
                    'grupo_de_nomina': fila.get('grupo_nomina') or 'Sin asignar',
                },
                unidad_organizativa_id=fila['codigo_interno'],
            )


class CargoCerradoConTrabajadores(ReglaBase):
    codigo = 'VIS-006'
    nombre = 'Cargo cerrado que sigue teniendo trabajadores'
    modulo = MODULO_OCULTOS
    criticidad = CRITICIDAD_ALTA
    modelo = 'strorganizativa.CargoPlantilla'

    descripcion = (
        'Busca cargos de plantilla sin plazas aprobadas (y por tanto inactivos) que sin '
        'embargo tienen contratos activos ocupando plaza.')
    causa_probable = (
        'Se pusieron a cero las plazas aprobadas del cargo sin mover antes a los '
        'trabajadores que lo ocupaban. Orbith marca el cargo como inactivo en cuanto las '
        'plazas aprobadas llegan a cero, pero no toca los contratos.')
    impacto = (
        'Hay trabajadores asignados a un cargo que la plantilla considera cerrado. Su '
        'plaza no está aprobada, así que la plantilla informa de una ocupación que no está '
        'respaldada, y eso es justo lo que se revisa en una auditoría de plantilla.')
    solucion = (
        'Decida cuál es la situación real. Si el cargo debe seguir existiendo, abra el '
        'cargo y ponga las plazas aprobadas que le corresponden. Si se cierra de verdad, '
        'mueva a esos trabajadores a otro cargo desde sus contratos antes de dejarlo a '
        'cero.')

    def ejecutar(self, contexto):
        # Todo en una consulta: el conteo condicional y el filtro los hace PostgreSQL.
        # `calta` es el nombre inverso de CAlta.cargo (ese FK no define related_name).
        filas = (self.base_queryset()
                 .filter(cant_aprobada=0)
                 .annotate(ocupadas=Count(
                     'calta', distinct=True,
                     filter=Q(calta__aspirante__estado='ACTIVO',
                              calta__tipo__ocupa_plaza=True)))
                 .filter(ocupadas__gt=0)
                 .values('id', 'ocupadas', 'cant_aprobada', 'cant_cubierta', 'activo',
                         'ncargo__descripcion', 'departamento__descripcion',
                         'departamento__unidad_organizativa_id')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            cargo = fila.get('ncargo__descripcion') or 'Cargo sin descripción'
            departamento = fila.get('departamento__descripcion') or '—'
            ocupadas = fila['ocupadas']
            plural = ocupadas != 1

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=(f'{cargo} · {departamento} · sin plazas aprobadas y con '
                        f'{ocupadas} trabajador{"es" if plural else ""}'),
                detalle=(
                    f'El cargo no tiene plazas aprobadas, así que está inactivo, pero '
                    f'{ocupadas} contrato{"s" if plural else ""} activo'
                    f'{"s" if plural else ""} lo ocupa{"n" if plural else ""} en la '
                    f'plantilla.'),
                datos={
                    'cargo': cargo,
                    'departamento': departamento,
                    'plazas_aprobadas': 0,
                    'trabajadores_que_lo_ocupan': ocupadas,
                    'cargo_activo': 'Sí' if fila.get('activo') else 'No',
                },
                unidad_organizativa_id=fila.get('departamento__unidad_organizativa_id'),
            )


class ModeradorSinUnidades(ReglaBase):
    codigo = 'VIS-007'
    nombre = 'Moderador sin unidades organizativas asignadas'
    modulo = MODULO_OCULTOS
    criticidad = CRITICIDAD_ALTA
    modelo = 'usuarios.CustomUser'

    descripcion = (
        'Busca usuarios activos con rol de moderador que no tienen ninguna unidad '
        'organizativa asignada.')
    causa_probable = (
        'El usuario se creó con rol de moderador y quedó pendiente asignarle sus unidades, '
        'o las que tenía se quitaron de su ficha.')
    impacto = (
        'Un moderador solo ve los datos de las unidades que tiene asignadas. Sin ninguna, '
        'este usuario entra en Orbith y no ve NADA: ni contratos, ni plantilla, ni '
        'informes. No aparece ningún mensaje de error, así que lo normal es que crea que '
        'la aplicación está vacía o averiada.')
    solucion = (
        'Abra el usuario y asígnele las unidades organizativas cuyos datos debe gestionar. '
        'Si no debe gestionar ninguna en concreto, cámbiele el rol a Observador, que ve '
        'todo en modo de solo consulta.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(es_moderador=True, is_active=True)
                 .annotate(total_unidades=Count('unidades'))
                 .filter(total_unidades=0)
                 .values('id', 'username', 'last_login')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            usuario = fila.get('username') or f'Usuario {fila["id"]}'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{usuario} · moderador sin unidades: no ve nada en el sistema',
                detalle=(
                    'Es moderador y no tiene ninguna unidad organizativa asignada, así '
                    'que al entrar en Orbith no verá ningún dato.'),
                datos={
                    'usuario': usuario,
                    'rol': 'Moderador',
                    'unidades_asignadas': 0,
                    'ultimo_acceso': (
                        fila['last_login'].strftime('%d/%m/%Y %H:%M')
                        if fila.get('last_login') else 'Nunca ha entrado'),
                },
            )
