"""Construcción de la fotografía de una Unidad Organizativa.

Equivalente de `solicitudes/serializacion.py`, pero a otra escala: allí se
congela un registro, aquí toda la plantilla y los contratos de una unidad.

Dos criterios que conviene tener presentes al leer esto:

* **Se releen los datos de la base**, nunca se usan instancias que vengan del
  llamador. Mismo motivo que `solicitudes/servicios.py::_releer()`: una
  instancia en memoria puede traer valores a medio validar.
* **Se capturan TODOS los cargos y TODOS los contratos** de la unidad, no solo
  los activos. Los informes no coinciden entre sí (el Consolidado filtra cargos
  por `activo=True` pero cuenta todos los contratos; Puestos Clave filtra además
  por `aspirante__estado='ACTIVO'`). Guardando todo y congelando los campos que
  usan para filtrar, la fotografía puede reproducir cualquiera de los dos
  comportamientos. Filtrar aquí obligaría a elegir uno y romper el otro.
"""

from contratos.models import CAlta
from strorganizativa.models import CargoPlantilla

from .models import CierreCargo, CierreContrato


def _nombre_completo(aspirante):
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido]
    return ' '.join(p for p in partes if p).strip()[:100]


def _cargos_de(unidad):
    """Cargos de la unidad con todo lo que hay que congelar ya precargado.

    `prefetch_related('ncargo__familias')` evita una consulta por cargo al
    aplanar la M2M; sin él, capturar una unidad de 200 cargos lanzaría 200
    consultas sueltas.
    """
    return (CargoPlantilla.objects
            .filter(departamento__unidad_organizativa=unidad)
            .select_related('departamento', 'ncargo', 'ncargo__grupo_escala',
                            'rol', 'nivel_preparacion')
            .prefetch_related('ncargo__familias')
            .order_by('departamento__orden_informe', 'orden_informe', 'id'))


def _contratos_de(unidad):
    return (CAlta.objects
            .filter(cargo__departamento__unidad_organizativa=unidad)
            .select_related('aspirante', 'aspirante__especialidad',
                            'cargo', 'cargo__departamento',
                            'cargo__ncargo', 'cargo__ncargo__grupo_escala',
                            'tipo', 'motivo', 'rol', 'tridente')
            .order_by('id'))


def _fila_de_cargo(cierre, cargo):
    ncargo = cargo.ncargo
    grupo = ncargo.grupo_escala if ncargo else None
    return CierreCargo(
        cierre=cierre,
        cargo_id_original=cargo.pk,
        departamento_id_original=cargo.departamento_id,
        departamento_descripcion=cargo.departamento.descripcion if cargo.departamento else '',
        departamento_orden=cargo.departamento.orden_informe if cargo.departamento else None,
        ncargo_id_original=cargo.ncargo_id,
        ncargo_descripcion=ncargo.descripcion if ncargo else '',
        cat_ocupacional=ncargo.cat_ocupacional if ncargo else '',
        puesto_clave=bool(ncargo.puesto_clave) if ncargo else False,
        grupo_escala_nivel=grupo.nivel if grupo else '',
        salario_basico=ncargo.salario_basico if ncargo else None,
        familias_ids=list(ncargo.familias.values_list('id', flat=True)) if ncargo else [],
        cant_aprobada=cargo.cant_aprobada or 0,
        # `cant_cubierta_real` y no la columna `cant_cubierta`: esta última es un
        # contador denormalizado que puede quedar desfasado, y una fotografía con
        # cifras desfasadas no vale para nada.
        cant_cubierta=cargo.cant_cubierta_real,
        en_plantilla=bool(cargo.en_plantilla),
        funcionario=bool(cargo.funcionario),
        designado=bool(cargo.designado),
        orden_informe=cargo.orden_informe,
        rol_tipo=cargo.rol.tipo if cargo.rol else '',
        nivel_preparacion_nombre=(
            cargo.nivel_preparacion.nombre if cargo.nivel_preparacion else ''),
        activo=bool(cargo.activo),
    )


def _fila_de_contrato(cierre, contrato, cierre_cargo):
    aspirante = contrato.aspirante
    cargo = contrato.cargo
    ncargo = cargo.ncargo if cargo else None
    grupo = ncargo.grupo_escala if ncargo else None
    tipo = contrato.tipo
    motivo = contrato.motivo
    return CierreContrato(
        cierre=cierre,
        cierre_cargo=cierre_cargo,
        contrato_id_original=contrato.pk,
        no_expediente=contrato.no_expediente or '',
        aspirante_id_original=contrato.aspirante_id,
        aspirante_nombre=_nombre_completo(aspirante) if aspirante else '',
        doc_identidad=aspirante.doc_identidad if aspirante else '',
        sexo=aspirante.sexo if aspirante else '',
        aspirante_estado=aspirante.estado if aspirante else '',

        # Formación: se congela porque evoluciona (ver el modelo).
        nivel_educ=(aspirante.nivel_educ or '') if aspirante else '',
        especialidad_nombre=(
            aspirante.especialidad.nombre if aspirante and aspirante.especialidad else ''),
        grado_cientifico=(aspirante.grado_cientifico or '') if aspirante else '',
        titulo_oro=bool(aspirante.titulo_oro) if aspirante else False,
        fecha_nacimiento=aspirante.fecha_nacimiento if aspirante else None,

        # Enlace vivo, solo para los datos que no son historia (contacto,
        # ubicación, tallas). Ver el comentario de `aspirante_vivo` en models.py.
        aspirante_vivo=aspirante,
        ncargo_id_original=cargo.ncargo_id if cargo else None,
        ncargo_descripcion=ncargo.descripcion if ncargo else '',
        cat_ocupacional=ncargo.cat_ocupacional if ncargo else '',
        puesto_clave=bool(ncargo.puesto_clave) if ncargo else False,
        grupo_escala_nivel=grupo.nivel if grupo else '',
        departamento_descripcion=(
            cargo.departamento.descripcion if cargo and cargo.departamento else ''),
        tipo_id_original=contrato.tipo_id,
        tipo_descripcion=tipo.descripcion if tipo else '',
        ocupa_plaza=bool(tipo.ocupa_plaza) if tipo else False,
        requiere_motivo=bool(tipo.requiere_motivo) if tipo else False,
        motivo_id_original=contrato.motivo_id,
        motivo_descripcion=motivo.descripcion if motivo else '',
        mision=bool(contrato.mision),
        pais=contrato.pais or '',
        fecha_alta=contrato.fecha_alta,
        duracion=contrato.duracion,
        salario=contrato.salario_actual,

        # Resto del contrato, para que el informe histórico ofrezca las mismas
        # columnas que el informe en tiempo real.
        reg_militar=contrato.reg_militar or '',
        profesional=bool(contrato.profesional),
        jubilado_recontratado=bool(contrato.jubilado_recontratado),
        fecha_alta_entidad=contrato.fecha_alta_entidad,
        c_formal=bool(contrato.c_formal),
        funcionario_res=contrato.funcionario_res or '',
        designado_res=contrato.designado_res or '',
        c_formal_res=contrato.c_formal_res or '',
        fecha_vence_lic=contrato.fecha_vence_lic,
        fecha_vence_recal=contrato.fecha_vence_recal,
        fecha_vence_seg=contrato.fecha_vence_seg,
        rol_tipo=contrato.rol.tipo if contrato.rol else '',
        tridente_tipo=contrato.tridente.tipo if contrato.tridente else '',
        tipo_salario=contrato.tipo_salario or '',
        maestria=contrato.maestria,
        doctorado=contrato.doctorado,
        cnci=contrato.cnci,
        instructor=contrato.instructor,
    )


def construir_fotografia(cierre):
    """Crea las filas de la fotografía y devuelve los totales para la cabecera.

    Asume que el `CierreUnidad` ya existe y que no tiene filas (el llamador las
    borra antes al redeclarar). Va en la misma transacción que la declaración,
    en `servicios.py`.
    """
    unidad = cierre.unidad

    filas_cargo = [_fila_de_cargo(cierre, c) for c in _cargos_de(unidad)]
    CierreCargo.objects.bulk_create(filas_cargo)

    # `bulk_create` en PostgreSQL rellena las pk, así que se puede indexar por el
    # cargo original para enlazar cada contrato con su fila sin volver a consultar.
    por_cargo_original = {f.cargo_id_original: f for f in filas_cargo}

    filas_contrato = [
        _fila_de_contrato(cierre, contrato, por_cargo_original.get(contrato.cargo_id))
        for contrato in _contratos_de(unidad)
    ]
    CierreContrato.objects.bulk_create(filas_contrato)

    return {
        'total_cargos': len(filas_cargo),
        # Los cargos fuera de la plantilla aprobada se congelan (su gente cobró
        # ese mes), pero sus plazas no son plantilla: no suman en los totales.
        'total_plazas_aprobadas': sum(
            f.cant_aprobada for f in filas_cargo if f.en_plantilla),
        'total_plazas_cubiertas': sum(
            f.cant_cubierta for f in filas_cargo if f.en_plantilla),
        'total_contratos': len(filas_contrato),
    }


def datos_de_unidad(unidad):
    """Campos de la propia Unidad Organizativa que se congelan en la cabecera."""
    tipo = unidad.tipo
    return {
        'unidad_descripcion': unidad.descripcion,
        'unidad_padre_id_original': unidad.padre_id,
        'unidad_es_principal': bool(tipo.es_principal) if tipo else False,
        'unidad_es_subunidad': bool(tipo.es_subunidad) if tipo else False,
        'unidad_orden_informe': unidad.orden_informe,
        'unidad_grupo_nomina': unidad.grupo_nomina,
    }
