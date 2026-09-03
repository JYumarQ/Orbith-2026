"""Jerarquía de Unidades Organizativas: ordenarlas y expandirlas.

Las tres pantallas que filtran por unidad —Dashboard, Informes RRHH e Informe
Inteligente— necesitan lo mismo:

  * pintar el desplegable con cada padre seguido de sus hijas, para que se vea
    de quién cuelga cada subunidad;
  * y entender que elegir una Unidad Principal significa también sus
    subunidades, porque una principal no tiene cargos propios: todo cuelga de
    sus hijas, así que sin la expansión el informe sale VACÍO.

Antes cada módulo lo resolvía a su manera (o no lo resolvía), y de ahí venía que
el mismo filtro diera resultados distintos según la pantalla. Aquí vive una sola
vez.

Es deliberadamente independiente de `informes.fuentes.expandir_unidades`: aquella
trabaja también sobre la jerarquía CONGELADA de un cierre mensual, que puede no
coincidir con la de hoy. Esta solo mira los datos vivos, que es lo que necesitan
un desplegable y el Dashboard.
"""

from .models import UnidadOrganizativa


def ordenar_con_jerarquia(unidades):
    """Devuelve las unidades ordenadas padre → hijas, con el atributo `nivel`.

    `nivel` vale 0 para las raíces y 1 para las subunidades; es lo que usa la
    plantilla para indentarlas.

    Se ordena en Python y no con un `order_by`, porque el orden que hace falta
    es jerárquico —cada padre seguido de los suyos— y eso no se expresa en SQL
    sin una consulta recursiva. Son decenas de unidades: el coste es irrelevante
    frente a la complejidad que ahorraría.
    """
    todas = list(unidades)
    por_padre = {}
    for unidad in todas:
        por_padre.setdefault(unidad.padre_id, []).append(unidad)

    def por_orden(lista):
        return sorted(lista, key=lambda u: (u.orden_informe or 999, u.descripcion or ''))

    presentes = {u.pk for u in todas}
    # Son raíces las que no tienen padre y también aquellas cuyo padre no está en
    # la lista: le pasa a un Moderador cuyo alcance empieza en una subunidad. Sin
    # esta segunda mitad, esas unidades desaparecerían del desplegable.
    raices = [u for u in todas if u.padre_id is None or u.padre_id not in presentes]

    ordenadas = []
    for raiz in por_orden(raices):
        raiz.nivel = 0
        ordenadas.append(raiz)
        for hija in por_orden(por_padre.get(raiz.pk, [])):
            hija.nivel = 1
            ordenadas.append(hija)
    return ordenadas


def expandir(unidades_ids):
    """Los ids recibidos MÁS los de sus subunidades directas.

    Una unidad sin hijas se expande a sí misma, así que elegir una subunidad
    concreta la sigue mostrando sola: se puede ver el total del padre o el
    detalle de una hija.

    Una sola consulta, sea cual sea el número de unidades elegidas.
    """
    ids = [pk for pk in (unidades_ids or []) if pk not in (None, '')]
    if not ids:
        return []

    completos = set()
    for pk in ids:
        try:
            completos.add(int(pk))
        except (TypeError, ValueError):
            continue
    if not completos:
        return []

    completos.update(
        UnidadOrganizativa.objects
        .filter(padre_id__in=completos)
        .values_list('pk', flat=True)
    )
    return sorted(completos)
