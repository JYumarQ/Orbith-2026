# -*- coding: utf-8 -*-
"""Anexo 17.1: el resumen cuantitativo de la Plantilla de Cargos.

QUÉ ES
------
Si el Anexo 17 es el detalle —una fila por cargo, con su rol, su nivel de
preparación y su grupo escala—, el 17.1 es el CONTEO: cuántas plazas hay por
categoría ocupacional, sin nombrar ni un solo cargo. Es el modelo que se
acompaña al organismo junto al 17.

Viene en dos niveles, y los dos se sirven desde aquí:

* RESUMEN DE EMPRESA (sin unidad elegida): una fila por unidad raíz —Oficina
  Central, las UEB, el Despacho— y la fila de total general.
* RESUMEN POR UNIDAD (con una unidad elegida): dentro de ella, cada subunidad
  («Dirección») rotula un bloque, sus Departamentos («Grupos») llevan las
  cifras, y cada bloque cierra con su `Subtotal`.

Una unidad raíz sin subunidades —una UEB— no tiene el nivel intermedio: sus
Departamentos cuelgan directos y no se rotula bloque alguno.

LAS COLUMNAS
------------
El modelo en papel parte los Cuadros en tres columnas (Dirección Superior,
Directivo y Ejecutivo). Orbith solo distingue dos categorías de Cuadro
(`CDI`/`CEJ`) y ya las presenta juntas en todo el módulo Anexo 17
(`views.ETIQUETAS_CATEGORIA`), así que aquí se escribe UNA columna «Cuadros» con
la suma de ambas. Se prefiere una columna honrada a tres de las que una saldría
siempre en cero: este documento se archiva, y una columna vacía en un modelo
oficial se lee como un dato que falta, no como un dato que no existe.

POR QUÉ NO REUTILIZA `_construir_hijas()`
-----------------------------------------
El Anexo 17 necesita cada `CargoPlantilla` en memoria porque los imprime uno a
uno. El 17.1 solo necesita SUMAS. Cargar el árbol entero para contarlo sería
traerse miles de filas a Python para reducirlas a seis números por unidad. Aquí
se suma en PostgreSQL con `Sum()` y una consulta agregada por nivel, así que el
coste no crece con el tamaño de la plantilla.
"""
from django.db.models import Sum

from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa

# Las columnas del modelo, en el orden del papel: C | T | A | S | O.
#
# Cada una declara (clave, rótulo, nombre, categorías de `NCargo` que agrupa).
# El RÓTULO es la LETRA del modelo oficial y es lo que va en la cabecera de la
# tabla y del Excel; el NOMBRE es la palabra entera, para el pie de las tarjetas
# de KPI. Una «S» suelta identifica la columna en un documento que ya tiene su
# leyenda, pero no dice nada en una tarjeta que se lee de un vistazo.
#
# Cuadros es «C» y no «Cuadros»: las cinco columnas son una fila de siglas y
# escribir una de ellas entera la hacía parecer de otra clase que las demás.
COLUMNAS_17_1 = [
    ("cuadros", "C", "Cuadros (C)", ("CDI", "CEJ")),
    ("tecnicos", "T", "Técnicos (T)", ("TEC",)),
    ("administrativos", "A", "Administrativos (A)", ("ADM",)),
    ("servicio", "S", "Servicio (S)", ("SER",)),
    ("obreros", "O", "Obreros (O)", ("OPE",)),
]

# Índice inverso, para no recorrer la lista por cada fila agregada.
_CLAVE_POR_CATEGORIA = {
    categoria: clave
    for clave, _, _, categorias in COLUMNAS_17_1
    for categoria in categorias
}

# Los tres tipos de fila que puede devolver `filas_de_unidad()`. La plantilla y
# el Excel deciden con esto cómo pintar cada una.
NIVEL_BLOQUE = "bloque"          # rótulo de la subunidad («Dirección»), sin cifras
NIVEL_DETALLE = "detalle"        # el Departamento («Grupo»), con sus cifras
NIVEL_SUBTOTAL = "subtotal"      # cierre del bloque


def _fila(denominacion, nivel=NIVEL_DETALLE):
    """Una fila del 17.1 con todas sus columnas a cero."""
    fila = {"denominacion": denominacion, "nivel": nivel, "total": 0}
    fila.update({clave: 0 for clave, _, _, _ in COLUMNAS_17_1})
    return fila


def _sumar(fila, categoria, cantidad):
    """Acumula `cantidad` en la columna que le toca a `categoria`.

    Una categoría que no esté en ninguna columna se ignora en vez de romper: las
    opciones de `NCargo.cat_ocupacional` están cerradas y todas tienen columna,
    pero si mañana se añadiera una sin actualizar `COLUMNAS_17_1`, es preferible
    que el informe salga (y no cuadre) a que reviente con un KeyError.
    """
    clave = _CLAVE_POR_CATEGORIA.get(categoria)
    if clave is None:
        return
    fila[clave] += cantidad
    fila["total"] += cantidad


def _acumular_en(destino, origen):
    """Suma `origen` sobre `destino`, columna a columna. Para los subtotales."""
    for clave, _, _, _ in COLUMNAS_17_1:
        destino[clave] += origen[clave]
    destino["total"] += origen["total"]


def _cargos_agregados(en_plantilla, permitidas, unidades_ids=None, filtros=None):
    """Plazas aprobadas agrupadas por unidad, departamento y categoría.

    UNA sola consulta, con la suma hecha en la base. `unidades_ids` acota a un
    conjunto concreto de unidades; `permitidas` es el alcance del usuario, con el
    mismo contrato que en `views._unidades_del_alcance()`: `None` no acota nada y
    un conjunto vacío no deja pasar ni una fila.

    `filtros` son los del Anexo 17 (búsqueda, categoría y rol). Se aplican aquí
    con los mismos criterios que en `views._construir_hijas()` para que las dos
    pantallas no puedan discrepar: si el Anexo 17 está filtrado por «Obrero», la
    cifra que el 17.1 pone en la pestaña de una unidad tiene que ser la de los
    obreros de esa unidad, no su total de siempre.
    """
    consulta = CargoPlantilla.objects.filter(activo=True, en_plantilla=en_plantilla)

    if permitidas is not None:
        consulta = consulta.filter(departamento__unidad_organizativa_id__in=permitidas)
    if unidades_ids is not None:
        consulta = consulta.filter(departamento__unidad_organizativa_id__in=unidades_ids)

    if filtros:
        busqueda = filtros.get("busqueda")
        categoria = filtros.get("categoria")
        rol = filtros.get("rol")
        if busqueda:
            consulta = consulta.filter(ncargo__descripcion__icontains=busqueda)
        if categoria and categoria != "ALL":
            if categoria == "CUADRO":
                consulta = consulta.filter(ncargo__cat_ocupacional__in=("CDI", "CEJ"))
            else:
                consulta = consulta.filter(ncargo__cat_ocupacional=categoria)
        if rol and rol != "ALL":
            consulta = consulta.filter(rol__tipo=rol)

    return (
        consulta
        .values(
            "departamento_id",
            "departamento__unidad_organizativa_id",
            "departamento__unidad_organizativa__padre_id",
            "ncargo__cat_ocupacional",
        )
        .annotate(cantidad=Sum("cant_aprobada"))
    )


def filas_de_empresa(raices, permitidas, en_plantilla=True, filtros=None):
    """El Resumen: una fila por unidad raíz, más la fila de total general.

    `raices` son las unidades que el usuario puede ver, ya ordenadas y en
    memoria (las mismas que alimentan el selector del Anexo 17). Se respeta ese
    orden y se listan TODAS, también las que no tienen ni una plaza: en un
    resumen oficial, una unidad que no aparece se confunde con una unidad que se
    olvidó.
    """
    indice = {}
    for raiz in raices:
        fila = _fila(raiz.descripcion)
        # La fila lleva su `pk` para que quien la reciba pueda cruzarla con la
        # unidad sin depender del orden de la lista.
        fila["pk"] = raiz.pk
        indice[raiz.pk] = fila
    total = _fila("Total", nivel=NIVEL_SUBTOTAL)

    for grupo in _cargos_agregados(en_plantilla, permitidas, filtros=filtros):
        # Un cargo cuelga de un Departamento, que cuelga de una unidad. Si esa
        # unidad es una subunidad, la fila del resumen es la de su padre.
        raiz_id = (grupo["departamento__unidad_organizativa__padre_id"]
                   or grupo["departamento__unidad_organizativa_id"])
        fila = indice.get(raiz_id)
        if fila is None:
            # La unidad existe pero no está en el selector (fuera del alcance del
            # usuario, o colgada de una raíz que él no ve). No se suma a nada.
            continue
        _sumar(fila, grupo["ncargo__cat_ocupacional"], grupo["cantidad"] or 0)

    filas = list(indice.values())
    for fila in filas:
        _acumular_en(total, fila)

    return {"filas": filas, "total": total}


def filas_de_unidad(raiz, permitidas, en_plantilla=True, filtros=None):
    """El 17.1 de UNA unidad: sus bloques, sus departamentos y sus subtotales.

    Devuelve una lista plana de filas, cada una con su `nivel`, porque es lo que
    recorren igual la pantalla y el Excel. Los bloques se ordenan por
    `orden_informe` —el organigrama que definió Capital Humano—, no por nombre.
    """
    if raiz is None:
        return {"filas": [], "total": _fila("Total", nivel=NIVEL_SUBTOTAL)}

    subunidades = list(
        UnidadOrganizativa.objects.filter(padre=raiz, tipo__es_subunidad=True)
        .order_by("orden_informe", "descripcion")
    )
    if permitidas is not None:
        subunidades = [u for u in subunidades if u.pk in permitidas]

    # Una unidad hoja (una UEB) no tiene subunidades: sus departamentos cuelgan
    # de ella misma. Es el mismo rescate que hace `views._construir_hijas()`.
    unidades = subunidades or [raiz]
    unidades_ids = [u.pk for u in unidades]

    departamentos = list(
        Departamento.objects.filter(unidad_organizativa_id__in=unidades_ids)
        .order_by("orden_informe", "id")
    )

    conteos = {depto.pk: _fila(depto.descripcion) for depto in departamentos}
    for grupo in _cargos_agregados(en_plantilla, permitidas, unidades_ids, filtros):
        fila = conteos.get(grupo["departamento_id"])
        if fila is not None:
            _sumar(fila, grupo["ncargo__cat_ocupacional"], grupo["cantidad"] or 0)

    por_unidad = {}
    for depto in departamentos:
        por_unidad.setdefault(depto.unidad_organizativa_id, []).append(conteos[depto.pk])

    filas = []
    total = _fila("Total", nivel=NIVEL_SUBTOTAL)

    for unidad in unidades:
        deptos = por_unidad.get(unidad.pk, [])

        # Los bloques sin departamentos SÍ se listan, con su subtotal en cero.
        # Misma razón que en `filas_de_empresa()`: una Dirección que existe en el
        # organigrama y no aparece en el informe no se distingue de una que se
        # quedó fuera por error.
        if not deptos and not subunidades:
            continue

        # El rótulo del bloque solo tiene sentido cuando hay un nivel intermedio
        # que rotular. En una unidad hoja la «Dirección» sería la propia unidad,
        # y repetir su nombre encima de sus departamentos no informa de nada.
        if subunidades:
            filas.append(_fila(unidad.descripcion, nivel=NIVEL_BLOQUE))

        subtotal = _fila("Subtotal", nivel=NIVEL_SUBTOTAL)
        for fila_depto in deptos:
            filas.append(fila_depto)
            _acumular_en(subtotal, fila_depto)

        if subunidades:
            filas.append(subtotal)
        _acumular_en(total, subtotal)

    return {"filas": filas, "total": total}


def libro_completo(raices, permitidas):
    """Todas las hojas del Anexo 17.1, en el orden del modelo oficial.

    Devuelve una lista de bloques —el Resumen primero y detrás una hoja por
    unidad raíz—, cada uno con sus dos conteos: la plantilla aprobada y los
    cargos que quedaron fuera de ella.

    Es lo que se exporta SIEMPRE, mire lo que mire el usuario en pantalla: el
    selector de la vista elige qué se enseña, no qué se entrega. El documento
    que va al organismo es el libro entero, y armarlo a mano exportando unidad
    por unidad es justo lo que esta función evita.

    El alcance por rol se respeta en los dos sentidos: `raices` llega ya acotada
    por `views._unidades_del_alcance()`, así que un Moderador se descarga el
    libro de SUS unidades, no el de la empresa.
    """
    bloques = [{
        'nombre': 'Resumen',
        'unidad': None,
        'aprobada': filas_de_empresa(raices, permitidas),
        'fuera': filas_de_empresa(raices, permitidas, en_plantilla=False),
    }]

    for raiz in raices:
        bloques.append({
            'nombre': raiz.descripcion,
            'unidad': raiz,
            'aprobada': filas_de_unidad(raiz, permitidas),
            'fuera': filas_de_unidad(raiz, permitidas, en_plantilla=False),
        })

    return bloques
