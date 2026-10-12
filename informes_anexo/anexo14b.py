# -*- coding: utf-8 -*-
"""Anexo 14-B: la plantilla de cargos CON el registro de trabajadores.

QUÉ ES, Y EN QUÉ SE DIFERENCIA DE LOS OTROS DOS
-----------------------------------------------
El Anexo 14 dice qué plazas hay. El 14-A las cuenta. El 14-B dice **quién ocupa
cada una y cuánto cobra**: nombre, carné, formación y el salario desglosado en
siete conceptos.

LA UNIDAD DE LA FILA ES LA PLAZA, NO LA PERSONA
-----------------------------------------------
Un cargo con tres plazas aprobadas y dos cubiertas ocupa TRES filas: dos con su
ocupante y una con las columnas de trabajador vacías. Así el documento cuadra con
el Anexo 14 —las mismas plazas— y enseña las vacantes, que es media razón de ser
de un registro de plantilla. Está comprobado contra el fichero real de Capital
Humano, donde las vacantes salen con su cargo, su grupo escala y su rol, y el
salario en cero.

LAS DOS HOJAS QUE NO SON UN DEPARTAMENTO
----------------------------------------
Hay gente que cobra y no ocupa plaza aprobada, y va en hojas aparte para no
falsear el conteo del departamento. Cada persona sale UNA sola vez en el libro:

* `Adiestrados` — contratos con `NTipoContrato.es_adiestrado`.
* `Contratados` — el resto de los que no ocupan plaza (hoy, Determinado).

Hubo una tercera, `Fuera de plantilla`, y se retiró: no contenía a nadie. Sus
trabajadores ya caían en las dos anteriores —se enrutan por TIPO DE CONTRATO, no
por si la plaza está aprobada—, así que lo único que quedaba dentro eran plazas
vacantes de cargos no aprobados. Una plaza que ni está aprobada ni tiene a nadie
no es un registro de trabajadores: se cuenta en el Anexo 14 y en el 14-A, que son
los que cuentan plazas, y aquí no sale.

EL SALARIO NO PASA POR PRE-NÓMINA
---------------------------------
Los Anexos y Pre-Nómina son cosas independientes y no se tocan. El CLA y la
nocturnidad salen de las TARJETAS DEL CONTRATO —los tres selectores del
formulario, cada uno con su `tarifa_hora`—, y no de un reporte cerrado. Son
CUP/hora y no importes del mes, y por eso no se suman al Total: el Total es
Escala + Maestría/Doctorado + Años de servicio + Otros.
"""
from collections import defaultdict
from datetime import date

from bolsa.models import Aspirante  # noqa: F401  (documenta el origen de la persona)
# El pago por años de servicio no se calcula aquí: lo resuelve el mismo módulo
# que alimenta el campo «Pago Años de Servicio» de la pestaña Salarios del
# formulario de contrato. Así el Anexo 14-B y ese campo no pueden discrepar, y de
# paso `informes_anexo` no importa NADA de Pre-Nómina.
from contratos.annos_servicio import annos_y_pago
from contratos.models import CAlta
from informes.altas_bajas import LETRA_CATEGORIA
from nomencladores.models import sigla_de_nivel_educacional
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa

#: Las dos hojas que no se corresponden con un departamento. El orden es el que
#: tendrán al final del libro.
HOJA_ADIESTRADOS = 'Adiestrados'
HOJA_CONTRATADOS = 'Contratados'


def _nombre_completo(aspirante):
    if aspirante is None:
        return ''
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido or '']
    return ' '.join(p for p in partes if p).strip()


def _formacion(aspirante):
    """La columna 7: la formación REAL de la persona, no la que pide el puesto.

    Sale como «N.S Ingeniero Eléctrico» — la sigla del nivel educacional y, si la
    tiene, su especialidad. Es lo que trae el fichero de Capital Humano, y por eso
    no se usa aquí `CargoPlantilla.nivel_preparacion`, que es el requisito del
    cargo y es lo que imprime el Anexo 14.
    """
    if aspirante is None:
        return ''
    sigla = sigla_de_nivel_educacional(aspirante.nivel_educ)
    especialidad = aspirante.especialidad.nombre if aspirante.especialidad_id else ''
    return ' '.join(p for p in (sigla, especialidad) if p).strip()


def _tarifas_de_nocturnidad(contrato):
    """Las DOS tarjetas de nocturnidad del contrato, tal como se enseñan.

    El modelo pide las dos en una sola casilla, así que se escriben separadas por
    una barra: «1.2/2.30». Con una sola tarjeta va solo esa, y sin ninguna la
    celda queda vacía. No se suman: son dos condiciones distintas y sumarlas
    perdería cuál es cuál.
    """
    if contrato is None:
        return ''
    tarifas = []
    for campo in ('nocturnidad_1', 'nocturnidad_2'):
        condicion = getattr(contrato, campo, None)
        if condicion is not None:
            tarifas.append('%g' % condicion.tarifa_hora)
    return '/'.join(tarifas)


def _fila(cargo, contrato, referencia):
    """Una plaza: los datos del cargo siempre, los del trabajador si lo hay.

    `contrato` a `None` es una vacante. Las columnas de persona y de dinero se
    quedan vacías, pero el cargo, la categoría, el grupo escala y el rol sí se
    escriben: la plaza existe aunque nadie la ocupe, y es justo lo que un registro
    de plantilla tiene que enseñar.
    """
    ncargo = cargo.ncargo
    aspirante = contrato.aspirante if contrato else None

    maestria_doctorado = (
        (contrato.maestria or 0) + (contrato.doctorado or 0)) if contrato else 0
    otros = ((contrato.cnci or 0) + (contrato.instructor or 0)) if contrato else 0
    escala = (contrato.salario_actual or 0) if contrato else 0

    # `annos_y_pago` devuelve `(años, cuantía)`; la cuantía es `None` cuando no
    # hay fecha de alta en la entidad, que es distinto de cobrar cero.
    _, pago_annos = annos_y_pago(
        contrato.fecha_alta_entidad, referencia) if contrato else (0, None)
    annos_servicio = pago_annos or 0

    # El TOTAL no incluye el CLA ni la nocturnidad: esas dos columnas llevan la
    # tarifa POR HORA de las tarjetas del contrato, no un importe del mes, y
    # sumar CUP/hora con CUP/mes daría una cifra que no significa nada.
    total = escala + maestria_doctorado + annos_servicio + otros

    return {
        'expediente': contrato.no_expediente if contrato else '',
        'cargo': ncargo.descripcion,
        # La inicial, no el código: «C» para los dos tipos de Cuadro, «T», «A»,
        # «S», «O». Es lo que pide el modelo oficial, y el mapa es el mismo que ya
        # usa «Altas y Bajas del Mes» — importado, no copiado.
        'categoria': LETRA_CATEGORIA.get(ncargo.cat_ocupacional, ''),
        'cat_codigo': ncargo.cat_ocupacional,
        'nombre': _nombre_completo(aspirante),
        'sexo': aspirante.sexo if aspirante else '',
        'carne': aspirante.doc_identidad if aspirante else '',
        'formacion': _formacion(aspirante),
        'grupo_escala': ncargo.grupo_escala.nivel if ncargo.grupo_escala_id else '',
        'total': total,
        'escala': escala,
        # Tarifa por hora de la tarjeta CLA, y las dos de nocturnidad en texto.
        'cla': (contrato.cla.tarifa_hora
                if contrato and contrato.cla_id else None),
        'nocturnos': _tarifas_de_nocturnidad(contrato),
        'maestria_doctorado': maestria_doctorado,
        'annos_servicio': annos_servicio,
        'otros': otros,
        # El Rol es el del CARGO, así que la vacante también lo lleva. El
        # Tridente, en cambio, se pacta en el contrato: sin contrato no hay.
        'rol': cargo.rol.tipo if cargo.rol_id else '',
        'tridente': (contrato.tridente.tipo
                     if contrato and contrato.tridente_id else ''),
        'vacante': contrato is None,
    }


def _unidades_de(raiz, permitidas):
    """La unidad y sus subunidades: de ahí cuelgan todos sus departamentos.

    Una UEB no tiene subunidades y sus departamentos cuelgan de ella misma; una
    Unidad Principal los tiene repartidos entre sus Direcciones. El 14-B no
    distingue: sus hojas son departamentos, vengan de donde vengan.
    """
    ids = [raiz.pk]
    subunidades = UnidadOrganizativa.objects.filter(
        padre=raiz, tipo__es_subunidad=True).values_list('pk', flat=True)
    ids.extend(subunidades)
    if permitidas is not None:
        ids = [i for i in ids if i in permitidas]
    return ids


def hojas_de_unidad(raiz, permitidas):
    """Todas las hojas del 14-B de una unidad, en el orden del libro.

    Devuelve una lista de dicts `{nombre, departamento, filas}`: primero una hoja
    por departamento con plazas, y detrás las dos especiales, que solo se crean si
    tienen a alguien.

    Los cargos NO aprobados (`en_plantilla=False`) no generan plaza aquí: sus
    ocupantes salen en Adiestrados o en Contratados según su tipo de contrato, y
    sus vacantes no salen en ningún sitio. Un registro de trabajadores no es el
    lugar de una plaza que ni está aprobada ni tiene a nadie.
    """
    referencia = date.today()
    unidades_ids = _unidades_de(raiz, permitidas)

    departamentos = list(
        Departamento.objects.filter(unidad_organizativa_id__in=unidades_ids)
        .select_related('unidad_organizativa')
        .order_by('orden_informe', 'id')
    )

    cargos = list(
        CargoPlantilla.objects.filter(
            activo=True, departamento_id__in=[d.pk for d in departamentos])
        .select_related('ncargo', 'ncargo__grupo_escala', 'rol')
        .order_by('orden_informe', 'ncargo__descripcion')
    )

    # Los contratos de todos esos cargos, de una vez: sin esto, cada plaza
    # dispararía su propia consulta y una unidad grande haría cientos.
    contratos = defaultdict(list)
    consulta = (
        CAlta.objects.filter(
            cargo_id__in=[c.pk for c in cargos], aspirante__estado='ACTIVO')
        .select_related('aspirante', 'aspirante__especialidad', 'tipo',
                        'tridente', 'cla', 'nocturnidad_1', 'nocturnidad_2')
        .order_by('aspirante__papellido', 'aspirante__nombre')
    )
    for contrato in consulta:
        contratos[contrato.cargo_id].append(contrato)

    por_departamento = defaultdict(list)
    adiestrados, contratados = [], []

    for cargo in cargos:
        ocupantes, aparte = [], []
        for contrato in contratos.get(cargo.pk, []):
            if contrato.tipo and contrato.tipo.ocupa_plaza:
                ocupantes.append(contrato)
            else:
                aparte.append(contrato)

        # Una fila por plaza aprobada: las primeras con ocupante y el resto
        # vacantes. `max()` protege del dato inconsistente —más contratos que
        # plazas—, que existe y no debe hacer desaparecer a nadie del registro.
        #
        # Solo para los cargos APROBADOS: los de fuera de plantilla no generan
        # plaza. Un contrato Indeterminado sobre uno de ellos no debería existir
        # —se impide al guardar y Subsanación lo reclama—, pero si lo hubiera se
        # lista igual, porque desaparecer del registro sería peor que salir.
        if cargo.en_plantilla:
            plazas = max(cargo.cant_aprobada or 0, len(ocupantes))
            destino = por_departamento[cargo.departamento_id]
        else:
            plazas = len(ocupantes)
            destino = por_departamento[cargo.departamento_id]

        for indice in range(plazas):
            contrato = ocupantes[indice] if indice < len(ocupantes) else None
            destino.append(_fila(cargo, contrato, referencia))

        # Los que no ocupan plaza no generan plaza: una fila por persona.
        for contrato in aparte:
            fila = _fila(cargo, contrato, referencia)
            if contrato.tipo and contrato.tipo.es_adiestrado:
                adiestrados.append(fila)
            else:
                contratados.append(fila)

    hojas = [
        {'nombre': depto.descripcion, 'departamento': depto,
         'filas': por_departamento.get(depto.pk, [])}
        for depto in departamentos
        if por_departamento.get(depto.pk)
    ]

    for nombre, filas in ((HOJA_ADIESTRADOS, adiestrados),
                          (HOJA_CONTRATADOS, contratados)):
        if filas:
            hojas.append({'nombre': nombre, 'departamento': None, 'filas': filas})

    return hojas
