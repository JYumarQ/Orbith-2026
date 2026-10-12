"""Puente entre Cierres y el Gestor de Plantilla.

Mismo papel que `solicitudes/integracion.py`: el módulo que *presta* la
funcionalidad expone funciones, y el que la consume las llama. El Gestor de
Plantilla no sabe nada de períodos ni de ventanas; solo pregunta «¿qué puede
hacer este usuario con estas unidades, y de qué color pinto cada una?» y
pinta la fila.

La razón de que esto no sea simplemente llamar a `servicios.calcular_estado()`
por cada fila es el rendimiento: el gestor pinta la lista completa de unidades
más sus subunidades, y `calcular_estado` cuesta una consulta por unidad. Aquí se
resuelve todo con **dos consultas**, sean 5 unidades o 200.
"""

from datetime import date

from .constantes import (COLOR_AZUL, COLOR_NARANJA, COLOR_ROJO, COLOR_SIN_HIJAS,
                         COLOR_VERDE)
from .models import CierreUnidad
from .periodos import Periodo, color_por_calendario, en_ventana, periodo_de, periodo_declarable
from .permisos import es_principal, puede_declarar

# Para agregar el color de un padre a partir de sus hijas: el peor gana.
# Rojo (incumplimiento) pesa más que naranja (ventana corriendo), que pesa
# más que azul (esperando su turno), que pesa más que verde (todo en orden).
_PRIORIDAD_COLOR = {COLOR_ROJO: 0, COLOR_NARANJA: 1, COLOR_AZUL: 2, COLOR_VERDE: 3}

# Clase de la insignia lista para pintar, mismo criterio y la misma paleta que
# `EstadoCierreUnidad.color_badge`: la plantilla no decide colores, solo pinta la
# clase que ya viene resuelta. Son las `inf-estado--*` de `informes-rrhh.css`.
_CLASE_POR_COLOR = {
    COLOR_VERDE: 'inf-estado inf-estado--ok',
    COLOR_AZUL: 'inf-estado inf-estado--espera',
    COLOR_NARANJA: 'inf-estado inf-estado--aviso',
    COLOR_ROJO: 'inf-estado inf-estado--critico',
    COLOR_SIN_HIJAS: 'inf-estado inf-estado--neutro',
}

# Para el `title`/tooltip del badge. En un padre no se refiere a SU propia
# declaración (nunca la tiene) sino a la de sus hijas — la redacción lo deja
# explícito para no sugerir que el padre mismo declaró algo.
_ETIQUETA_POR_COLOR = {
    COLOR_VERDE: 'Actualizada para el cierre actual',
    COLOR_AZUL: 'Al día — el período de actualización aún no ha comenzado',
    COLOR_NARANJA: 'Período de actualización abierto — pendiente de declarar',
    COLOR_ROJO: 'Desactualizada o nunca declarada',
    COLOR_SIN_HIJAS: 'Sin subunidades todavía',
}
_ETIQUETA_PADRE_POR_COLOR = {
    COLOR_VERDE: 'Todas sus subunidades están actualizadas',
    COLOR_AZUL: 'Sus subunidades están al día, ninguna ha entrado en período de actualización',
    COLOR_NARANJA: 'Alguna subunidad tiene el período de actualización abierto sin declarar',
    COLOR_ROJO: 'Alguna subunidad está desactualizada o nunca ha declarado',
    COLOR_SIN_HIJAS: 'Sin subunidades todavía',
}


def _ultimos_periodos(unidades_ids):
    """El período más reciente cerrado por cada unidad, en una sola consulta."""
    ultimos = {}
    filas = (CierreUnidad.objects
             .filter(unidad_id__in=unidades_ids)
             .values_list('unidad_id', 'anno', 'mes'))
    for unidad_id, anno, mes in filas:
        periodo = Periodo(anno, mes)
        if unidad_id not in ultimos or periodo > ultimos[unidad_id]:
            ultimos[unidad_id] = periodo
    return ultimos


def _color_de_padre(unidad, unidades, acciones):
    """El color de una Dirección Principal: el peor entre sus hijas directas.

    Sin hijas todavía (unidad recién creada) no es un incumplimiento — no hay
    nada que declarar — así que se pinta en gris, no en rojo.
    """
    hijos_ids = [u.pk for u in unidades if u.padre_id == unidad.pk]
    colores = [acciones[hid]['color'] for hid in hijos_ids if hid in acciones]
    if not colores:
        return COLOR_SIN_HIJAS
    return min(colores, key=lambda c: _PRIORIDAD_COLOR.get(c, 99))


def acciones_por_unidad(unidades, usuario, hoy=None):
    """Qué puede hacer `usuario` con cada unidad, y de qué color pintarla.

    Devuelve `{unidad_id: dict}` con `puede_declarar`, `puede_reabrir`, el
    período que se cerraría, y `color` — uno de los cinco valores de
    `constantes.py` (verde/azul/naranja/rojo/gris).

    Las Direcciones Principales nunca declaran (`puede_declarar` siempre
    `False`, ver `permisos.puede_declarar`) y su `color` no sale de su propio
    historial — que no existe — sino de agregar el de sus hijas **directas**
    presentes en `unidades`. Por eso hace falta que quien llame pase padre e
    hijas juntos en la misma lista (`anotar_acciones` ya lo hace vía
    `_aplanar`); si solo se pasa el padre sin sus hijas, no hay con qué
    agregar y se pinta gris (mismo resultado que "sin hijas").
    """
    hoy = hoy or date.today()
    unidades = list(unidades)
    ids = [u.pk for u in unidades]
    if not ids:
        return {}

    ultimos = _ultimos_periodos(ids)
    actual = periodo_de(hoy)
    con_cierre_actual = set(
        CierreUnidad.objects
        .filter(unidad_id__in=ids, anno=actual.anno, mes=actual.mes)
        .values_list('unidad_id', flat=True))

    ventana_abierta = en_ventana(hoy)
    acciones = {}
    padres_pendientes = []

    for unidad in unidades:
        if es_principal(unidad):
            # Se completa en una segunda pasada: hace falta que TODAS las
            # hijas (que pueden aparecer después en la lista) ya tengan su
            # color calculado antes de poder agregar el del padre.
            padres_pendientes.append(unidad)
            acciones[unidad.pk] = {
                'autorizado': False,
                'puede_declarar': False,
                'puede_reabrir': False,
                'periodo_declarable': None,
                'etiqueta_declarable': '',
                'ultimo_cerrado': None,
                'color': None,          # placeholder, se resuelve abajo
                'color_badge': None,
                'color_titulo': None,
            }
            continue

        autorizado = puede_declarar(usuario, unidad)
        ultimo_cerrado = ultimos.get(unidad.pk)
        declarable = periodo_declarable(ultimo_cerrado, hoy)
        tiene_cierre_actual = unidad.pk in con_cierre_actual
        color = color_por_calendario(ultimo_cerrado, hoy)

        acciones[unidad.pk] = {
            'autorizado': autorizado,
            'puede_declarar': autorizado and declarable is not None,
            'puede_reabrir': autorizado and tiene_cierre_actual and ventana_abierta,
            'periodo_declarable': declarable,
            'etiqueta_declarable': declarable.etiqueta if declarable else '',
            'ultimo_cerrado': ultimo_cerrado,
            'color': color,
            'color_badge': _CLASE_POR_COLOR[color],
            'color_titulo': _ETIQUETA_POR_COLOR[color],
        }

    # Asume una sola jerarquía de profundidad (padre -> hijas), igual que el
    # resto del proyecto (`expandir_unidades` en informes, `direcciones_hijas`
    # en el gestor): si una hija fuera a su vez principal, su color quedaría
    # sin resolver al agregarlo aquí. No es un caso que la aplicación soporte
    # hoy en ningún otro sitio, así que no se contempla.
    for padre in padres_pendientes:
        color = _color_de_padre(padre, unidades, acciones)
        acciones[padre.pk]['color'] = color
        acciones[padre.pk]['color_badge'] = _CLASE_POR_COLOR[color]
        acciones[padre.pk]['color_titulo'] = _ETIQUETA_PADRE_POR_COLOR[color]

    return acciones


def _aplanar(unidades):
    """El listado del gestor: unidades de primer nivel y sus subunidades.

    El gestor pinta las subunidades dentro del desplegable de su padre, y también
    tienen que poder declararse. Se recorre el `prefetch_related` ya cargado, así
    que no dispara consultas nuevas.
    """
    completas = []
    for unidad in unidades:
        completas.append(unidad)
        completas.extend(unidad.direcciones_hijas.all())
    return completas


def anotar_acciones(unidades, usuario, hoy=None):
    """Cuelga `acciones_cierre` de cada unidad y de cada subunidad.

    Se anota sobre la instancia en vez de devolver un diccionario porque la
    plantilla del gestor recorre las unidades y sus hijas por separado, y Django
    no permite indexar un dict por clave variable sin un filtro a medida. El
    proyecto no tiene ninguno, y no merece inventarlo para esto.
    """
    completas = _aplanar(unidades)
    acciones = acciones_por_unidad(completas, usuario, hoy)
    for unidad in completas:
        unidad.acciones_cierre = acciones.get(unidad.pk, {})
    return unidades
