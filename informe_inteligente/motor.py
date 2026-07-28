"""
Motor de construcción de consultas para Informe Inteligente.

Traduce la configuración JSON de un informe (campos, filtros, orden) en un
QuerySet real de Django, usando el registro de informe_inteligente/metadata.py
como única fuente de verdad sobre qué es válido.
"""
from django.db.models import Q, F, Value, CharField
from django.db.models.functions import Concat, ExtractYear
from django.db.models.expressions import Func
from django.apps import apps

from .metadata import REGISTRO_MODELOS, LOOKUP_POR_OPERADOR


class EdadExacta(Func):
    """
    Calcula la edad exacta en años completos usando la función nativa
    age() de PostgreSQL, que sí contempla si el cumpleaños ya pasó este
    año. Equivalente exacto a la lógica de Aspirante.get_edad, pero
    resuelto en la base de datos para poder filtrar y ordenar por él.
    """
    function = "DATE_PART"
    template = "%(function)s('year', AGE(%(expressions)s))"
    arity = 1
    output_field = None  # se define al usarla, ver más abajo


class ConfiguracionInformeInvalida(Exception):
    """Se lanza cuando el JSON del informe referencia un campo que no existe
    en el registro (por ejemplo, un informe guardado hace tiempo cuyo campo
    fue eliminado del sistema)."""
    pass


def _obtener_definicion_modelo(modelo_raiz):
    definicion = REGISTRO_MODELOS.get(modelo_raiz)
    if not definicion:
        raise ConfiguracionInformeInvalida(f"Modelo raíz desconocido: {modelo_raiz}")
    return definicion


def _obtener_campo(definicion_modelo, key_campo):
    campo = definicion_modelo["campos"].get(key_campo)
    if not campo:
        raise ConfiguracionInformeInvalida(f"Campo desconocido: {key_campo}")
    return campo


def _aplicar_anotaciones_necesarias(queryset, definicion_modelo, keys_campos_usados):
    """
    Algunos campos (edad, nombre_completo) no tienen ruta_orm directa:
    se resuelven con anotaciones. Aquí se añaden solo las que hagan falta.
    """
    for key in keys_campos_usados:
        campo = definicion_modelo["campos"].get(key)
        if not campo or campo["ruta_orm"] is not None:
            continue  # Este campo ya tiene ruta directa, no necesita anotación

        if key == "edad":
            # Edad EXACTA (contempla si el cumpleaños ya ocurrió este año),
            # usando la función nativa AGE() de PostgreSQL — mismo resultado
            # que Aspirante.get_edad, calculado en la base de datos.
            from django.db.models import IntegerField
            queryset = queryset.annotate(
                edad=EdadExacta(F("aspirante__fecha_nacimiento"), output_field=IntegerField())
            )
        elif key == "nombre_completo":
            queryset = queryset.annotate(
                nombre_completo=Concat(
                    F("aspirante__nombre"), Value(" "),
                    F("aspirante__papellido"), Value(" "),
                    F("aspirante__sapellido"),
                    output_field=CharField()
                )
            )
        # Si en el futuro se añade otro campo calculado, su anotación va aquí.

    return queryset


def _construir_q_de_filtro(definicion_modelo, filtro):
    """Convierte un filtro del JSON en un objeto Q de Django."""
    key = filtro["campo"]
    operador = filtro["operador"]
    valor = filtro.get("valor")

    campo = _obtener_campo(definicion_modelo, key)
    if not campo.get("filtrable"):
        raise ConfiguracionInformeInvalida(f"El campo '{key}' no es filtrable.")

    # Usar ruta_orm si existe; si no, el campo se filtra por su propio 'key'
    # porque ya fue resuelto como anotación con ese mismo nombre.
    ruta = campo["ruta_orm"] or key

    if operador == "es_nulo":
        return Q(**{f"{ruta}__isnull": True})
    if operador == "no_es_nulo":
        return Q(**{f"{ruta}__isnull": False})
    if operador == "entre_fechas":
        return Q(**{f"{ruta}__range": (valor.get("desde"), valor.get("hasta"))})

    lookup = LOOKUP_POR_OPERADOR[operador]
    q = Q(**{f"{ruta}__{lookup}": valor})

    if operador == "diferente":
        q = ~q  # negamos el Q en vez de usar .exclude(), para poder combinarlo con AND/OR

    return q


def _aplicar_alcance_por_rol(queryset, definicion_modelo, usuario):
    """
    Restringe el queryset según el rol del usuario. SIEMPRE se aplica,
    nunca es opcional desde la interfaz.
    """
    if usuario.is_superuser or usuario.es_admin or usuario.es_observador:
        return queryset  # Ven todo, sin restricción

    if usuario.es_moderador:
        ruta_uo = definicion_modelo.get("ruta_unidad_organizativa")
        if ruta_uo is None:
            # Este modelo no tiene concepto de Unidad Organizativa (ej. Aspirante):
            # el moderador no ve nada de este modelo raíz.
            return queryset.none()
        unidades_ids = usuario.unidades.values_list("id", flat=True)
        return queryset.filter(**{f"{ruta_uo}__in": unidades_ids})

    # Cualquier otro caso (usuario sin rol reconocido): por seguridad, no ve nada.
    return queryset.none()


def construir_queryset(modelo_raiz, configuracion, usuario):
    """
    Punto de entrada principal. Recibe el nombre del modelo raíz, la
    configuración JSON del informe, y el usuario que ejecuta la consulta.
    Devuelve un QuerySet listo para paginar (sin evaluar todavía).
    """
    definicion_modelo = _obtener_definicion_modelo(modelo_raiz)
    app_label = definicion_modelo["app_label"]
    Modelo = apps.get_model(app_label, modelo_raiz)

    queryset = Modelo.objects.all()

    # 1. Alcance por rol — SIEMPRE primero, nunca condicionado por el usuario
    queryset = _aplicar_alcance_por_rol(queryset, definicion_modelo, usuario)

    # 2. Determinar qué campos están en juego (para saber qué anotar)
    keys_campos = set(configuracion.get("campos", []))
    for filtro in configuracion.get("filtros", []):
        keys_campos.add(filtro["campo"])
    if configuracion.get("ordenar_por"):
        keys_campos.add(configuracion["ordenar_por"])
    if configuracion.get("agrupar_por"):
        keys_campos.add(configuracion["agrupar_por"])

    queryset = _aplicar_anotaciones_necesarias(queryset, definicion_modelo, keys_campos)

    # 3. Filtros del usuario, combinados con AND
    for filtro in configuracion.get("filtros", []):
        queryset = queryset.filter(_construir_q_de_filtro(definicion_modelo, filtro))

    # 4. Orden
    campo_orden = configuracion.get("ordenar_por")
    if campo_orden:
        campo_meta = _obtener_campo(definicion_modelo, campo_orden)
        if campo_meta.get("ordenable"):
            ruta = campo_meta["ruta_orm"] or campo_orden
            if configuracion.get("orden_direccion") == "desc":
                ruta = f"-{ruta}"
            queryset = queryset.order_by(ruta)

    return queryset


def obtener_rutas_select_related(definicion_modelo, keys_campos):
    """
    Calcula qué relaciones hay que precargar con select_related() para
    evitar el problema N+1 al mostrar los campos elegidos.
    """
    rutas = set()
    for key in keys_campos:
        campo = definicion_modelo["campos"].get(key)
        if not campo or not campo.get("ruta_orm"):
            continue
        partes = campo["ruta_orm"].split("__")
        if len(partes) > 1:
            rutas.add("__".join(partes[:-1]))
    return list(rutas)