"""
Motor de construcción de consultas para Informe Inteligente.

Traduce la configuración JSON de un informe (campos, filtros, orden) en un
QuerySet real de Django, usando el registro de informe_inteligente/metadata.py
como única fuente de verdad sobre qué es válido.
"""
from datetime import date, timedelta

from django.db.models import Q, F, Value, CharField, Count, Sum, Avg, OuterRef, Subquery
from django.db.models.functions import Concat, ExtractYear, ExtractMonth, ExtractDay
from django.db.models.expressions import Func
from django.apps import apps

from .metadata import (
    REGISTRO_MODELOS,
    LOOKUP_POR_OPERADOR,
    OPERADORES_MULTIVALOR,
    INDICADORES_POR_MODELO,
    mapa_valor_a_etiqueta,
    valores_db_de_etiqueta,
)


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
        raise ConfiguracionInformeInvalida(
            "El tipo de informe seleccionado ya no está disponible en el sistema."
        )
    return definicion


def _obtener_campo(definicion_modelo, key_campo):
    campo = definicion_modelo["campos"].get(key_campo)
    if not campo:
        raise ConfiguracionInformeInvalida(
            f"El campo «{key_campo}» ya no existe en el sistema. "
            "Es posible que este informe se guardara con una versión anterior."
        )
    return campo


def _aplicar_anotaciones_necesarias(queryset, definicion_modelo, keys_campos_usados):
    """
    Algunos campos (edad, nombre_completo, cumpleanos) no tienen ruta_orm
    directa: se resuelven con anotaciones. Aquí se añaden solo las que hagan
    falta.

    CAlta/CBaja llegan a los datos personales a través del FK 'aspirante';
    el modelo Aspirante ES esos datos directamente. 'ruta_aspirante' en el
    registro de metadata.py indica cuál de los dos casos aplica (None cuando
    el modelo raíz ya es Aspirante), para no duplicar esta lógica por modelo.
    """
    ruta_aspirante = definicion_modelo.get("ruta_aspirante")
    prefijo = f"{ruta_aspirante}__" if ruta_aspirante else ""

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
                edad=EdadExacta(F(f"{prefijo}fecha_nacimiento"), output_field=IntegerField())
            )
        elif key == "nombre_completo":
            queryset = queryset.annotate(
                nombre_completo=Concat(
                    F(f"{prefijo}nombre"), Value(" "),
                    F(f"{prefijo}papellido"), Value(" "),
                    F(f"{prefijo}sapellido"),
                    output_field=CharField()
                )
            )
        elif key == "cumpleanos":
            # Mes y día de nacimiento por separado: permiten mostrar "15 AGO"
            # (formateado en views.py) y ordenar cronológicamente sin depender
            # del año de nacimiento.
            queryset = queryset.annotate(
                mes_nacimiento=ExtractMonth(F(f"{prefijo}fecha_nacimiento")),
                dia_nacimiento=ExtractDay(F(f"{prefijo}fecha_nacimiento")),
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
        raise ConfiguracionInformeInvalida(
            f"El campo «{campo['label']}» no admite filtros."
        )

    # Usar ruta_orm si existe; si no, el campo se filtra por su propio 'key'
    # porque ya fue resuelto como anotación con ese mismo nombre.
    ruta = campo["ruta_orm"] or key

    if operador == "es_nulo":
        return Q(**{f"{ruta}__isnull": True})
    if operador == "no_es_nulo":
        return Q(**{f"{ruta}__isnull": False})
    if operador == "entre_fechas":
        return Q(**{f"{ruta}__range": (valor.get("desde"), valor.get("hasta"))})
    if operador == "mes":
        # El <select> de meses en el JS envía "1".."12" como string.
        return Q(**{f"{ruta}__month": int(valor)})
    if operador == "semana":
        # Semana de lunes a domingo, ignorando el año: se arma como un OR de
        # las 7 combinaciones (mes, día) de esa semana, para no depender de
        # aritmética de "día del año" (que se complica en fin de año y con
        # el 29 de febrero). `valor` trae {"offset_semanas": N} — N=0 semana
        # actual, N=-1 anterior, N=1 siguiente, cualquier entero para saltos
        # libres. Se calcula relativo a "hoy" en cada consulta (no se guarda
        # una fecha absoluta), para que un favorito "semana actual" siga
        # siendo la semana actual cada vez que se abre.
        offset = int((valor or {}).get("offset_semanas", 0))
        hoy = date.today()
        lunes_actual = hoy - timedelta(days=hoy.weekday())  # weekday(): lunes=0
        lunes_objetivo = lunes_actual + timedelta(weeks=offset)
        q_semana = Q()
        for i in range(7):
            dia = lunes_objetivo + timedelta(days=i)
            q_semana |= Q(**{f"{ruta}__month": dia.month, f"{ruta}__day": dia.day})
        return q_semana

    if campo["tipo"] == "booleano":
        # El JS envía el string "true"/"false" en minúsculas, que
        # BooleanField.to_python de Django NO reconoce (solo acepta
        # "True"/"1" o "False"/"0"): sin esta conversión, filtrar por un
        # campo booleano lanzaría un ValidationError en vez de un mensaje
        # controlado. Se normaliza aquí, sea cual sea la forma en que llegó.
        valor = str(valor).strip().lower() in ("true", "1", "t", "sí", "si")

    if operador in OPERADORES_MULTIVALOR:
        if not isinstance(valor, (list, tuple)) or not valor:
            raise ConfiguracionInformeInvalida(
                f"Seleccione al menos un valor para el filtro «{campo['label']}»."
            )

    # Campos con valores agrupados (Categoría Ocupacional: "Cuadro" son CDI y
    # CEJ a la vez). El usuario elige la etiqueta y aquí se traduce a los
    # códigos reales de la base de datos, siempre con un lookup 'in'.
    if campo.get("grupos_valores") and operador in ("igual", "diferente", "en_lista", "no_en_lista"):
        etiquetas = valor if isinstance(valor, (list, tuple)) else [valor]
        valores_db = []
        for etiqueta in etiquetas:
            equivalentes = valores_db_de_etiqueta(campo, etiqueta)
            if not equivalentes:
                raise ConfiguracionInformeInvalida(
                    f"El valor «{etiqueta}» no es válido para el filtro «{campo['label']}»."
                )
            valores_db.extend(equivalentes)

        q = Q(**{f"{ruta}__in": valores_db})
        return ~q if operador in ("diferente", "no_en_lista") else q

    lookup = LOOKUP_POR_OPERADOR[operador]
    q = Q(**{f"{ruta}__{lookup}": valor})

    if operador in ("diferente", "no_en_lista"):
        q = ~q  # negamos el Q en vez de usar .exclude(), para poder combinarlo con AND/OR

    return q


def _aplicar_alcance_por_rol(queryset, definicion_modelo, usuario):
    """
    Restringe el queryset según el rol del usuario. SIEMPRE se aplica,
    nunca es opcional desde la interfaz.

    'ruta_unidad_organizativa' en el registro de metadata.py admite 3 formas:
      - un string: se filtra por esa única ruta (caso normal: CAlta, CBaja,
        CargoPlantilla).
      - una lista de strings: el moderador ve el registro si CUALQUIERA de
        esas rutas cae en sus unidades asignadas (OR) — caso de TMovimiento,
        donde un movimiento puede afectar a la unidad de origen o de destino.
      - None: el modelo no tiene ningún concepto de Unidad Organizativa
        (decisión de negocio, ej. Aspirante — un aspirante no pertenece a
        ninguna unidad todavía). Sin nada que acotar, el moderador ve todo,
        igual que Admin/Observador.
    """
    if usuario.is_superuser or usuario.es_admin or usuario.es_observador:
        return queryset  # Ven todo, sin restricción

    if usuario.es_moderador:
        ruta_uo = definicion_modelo.get("ruta_unidad_organizativa")
        if ruta_uo is None:
            return queryset  # Sin concepto de Unidad Organizativa: ve todo.

        # UnidadOrganizativa usa 'codigo_interno' como PK (no 'id'); 'pk' es
        # portable ante cualquier nombre real de la clave primaria.
        unidades_ids = usuario.unidades.values_list("pk", flat=True)

        rutas = ruta_uo if isinstance(ruta_uo, (list, tuple)) else [ruta_uo]
        condicion = Q()
        for ruta in rutas:
            condicion |= Q(**{f"{ruta}__in": unidades_ids})
        return queryset.filter(condicion)

    # Cualquier otro caso (usuario sin rol reconocido): por seguridad, no ve nada.
    return queryset.none()


def _aplicar_filtro_bajas_vigentes(queryset):
    """
    El informe de Bajas debe reflejar el estado VIGENTE del trabajador, no el
    historial completo de CBaja: si alguien fue dado de baja y luego
    recontratado, sus bajas antiguas no deben aparecer (su Aspirante.estado
    ya no es 'BAJA'). Y si una persona actualmente de baja tiene más de un
    registro histórico (baja, alta, baja de nuevo), solo se muestra el más
    reciente — nunca ambos, para no duplicar al mismo trabajador.
    """
    ultima_baja_por_aspirante = queryset.filter(
        aspirante_id=OuterRef("aspirante_id")
    ).order_by("-fecha_baja", "-created_at").values("pk")[:1]

    return queryset.filter(
        aspirante__estado="BAJA",
        pk=Subquery(ultima_baja_por_aspirante),
    )


def _aplicar_filtro_aspirantes_vigentes(queryset):
    """
    El modelo Aspirante guarda a TODA persona que alguna vez pasó por el
    sistema (aspirante, activo o de baja) — 'estado' es lo único que
    distingue quién sigue genuinamente en la bolsa sin contrato. El informe
    de Aspirantes debe mostrar solo eso, no la plantilla completa.
    """
    return queryset.filter(estado="ASPIRANTE")


def _construir_queryset_filtrado(modelo_raiz, configuracion, usuario):
    """
    Parte común a todos los modos de informe: aplica el alcance por rol,
    las anotaciones necesarias y los filtros del usuario. NO ordena, porque
    cada modo necesita un orden distinto.

    Devuelve la tupla (queryset, definicion_modelo).
    """
    definicion_modelo = _obtener_definicion_modelo(modelo_raiz)
    app_label = definicion_modelo["app_label"]
    Modelo = apps.get_model(app_label, modelo_raiz)

    queryset = Modelo.objects.all()

    # El informe de Bajas/Aspirantes es sobre el estado vigente del
    # trabajador, no un historial de eventos: se aplica siempre, antes que
    # cualquier otra cosa.
    if modelo_raiz == "CBaja":
        queryset = _aplicar_filtro_bajas_vigentes(queryset)
    elif modelo_raiz == "Aspirante":
        queryset = _aplicar_filtro_aspirantes_vigentes(queryset)

    # 1. Alcance por rol — SIEMPRE primero, nunca condicionado por el usuario
    queryset = _aplicar_alcance_por_rol(queryset, definicion_modelo, usuario)

    # 2. Determinar qué campos están en juego (para saber qué anotar).
    #    Se validan de entrada: un informe guardado hace tiempo puede
    #    referenciar un campo que ya se eliminó del registro, y el usuario
    #    debe ver un mensaje claro en vez de un error del servidor.
    for key in configuracion.get("campos", []):
        _obtener_campo(definicion_modelo, key)

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

    return queryset, definicion_modelo


def construir_queryset(modelo_raiz, configuracion, usuario):
    """
    Modo LISTADO: devuelve un QuerySet de registros individuales, listo para
    paginar (sin evaluar todavía).
    """
    queryset, definicion_modelo = _construir_queryset_filtrado(modelo_raiz, configuracion, usuario)

    # Orden.
    # Siempre se termina ordenando por 'pk' además del campo elegido: sin un
    # orden total y estable, PostgreSQL puede devolver las filas en distinto
    # orden en cada consulta y la paginación repetiría o se saltaría registros.
    campos_orden = []
    campo_orden = configuracion.get("ordenar_por")
    if campo_orden:
        campo_meta = _obtener_campo(definicion_modelo, campo_orden)
        if campo_meta.get("ordenable"):
            signo = "-" if configuracion.get("orden_direccion") == "desc" else ""
            if campo_orden == "cumpleanos":
                # Campo compuesto: se muestra como "15 AGO" pero se ordena
                # cronológicamente por (mes, día), no alfabéticamente por el
                # texto ya formateado.
                campos_orden.append(f"{signo}mes_nacimiento")
                campos_orden.append(f"{signo}dia_nacimiento")
            else:
                ruta = campo_meta["ruta_orm"] or campo_orden
                campos_orden.append(f"{signo}{ruta}")

    campos_orden.append("pk")
    return queryset.order_by(*campos_orden)


def _expresion_de_campo(campo, key_campo, ruta_aspirante=None):
    """
    Devuelve la expresión ORM con la que agregar (sumar o promediar) un campo.
    La mayoría son una simple referencia a su columna; 'edad' es la excepción,
    porque se calcula a partir de la fecha de nacimiento (directa en
    Aspirante, o vía 'aspirante__' en CAlta/CBaja — ver 'ruta_aspirante').
    """
    if key_campo == "edad":
        from django.db.models import IntegerField
        prefijo = f"{ruta_aspirante}__" if ruta_aspirante else ""
        return EdadExacta(F(f"{prefijo}fecha_nacimiento"), output_field=IntegerField())
    return F(campo["ruta_orm"] or key_campo)


def calcular_indicadores(queryset, definicion_modelo, modelo_raiz):
    """
    Calcula las tarjetas del panel de resumen (total, % de mujeres, edad y
    salario promedio...) sobre el mismo conjunto de registros que se lista.

    TODAS se resuelven en UNA sola consulta de agregación: se acumulan en un
    diccionario y se envían juntas a .aggregate(). Con 50.000 trabajadores el
    coste es prácticamente el mismo que con 50.
    """
    especificaciones = INDICADORES_POR_MODELO.get(modelo_raiz, [])
    if not especificaciones:
        return [], 0

    ruta_aspirante = definicion_modelo.get("ruta_aspirante")
    agregaciones = {"_total": Count("id")}

    for spec in especificaciones:
        if spec["tipo"] == "conteo":
            continue

        key_campo = spec["campo"]
        campo = definicion_modelo["campos"].get(key_campo)
        if not campo:
            continue  # el campo se eliminó del registro: se omite el indicador

        if spec["tipo"] == "conteo_si":
            ruta = campo["ruta_orm"] or key_campo
            agregaciones[spec["key"]] = Count("id", filter=Q(**{ruta: spec["valor"]}))
        elif spec["tipo"] == "suma":
            agregaciones[spec["key"]] = Sum(_expresion_de_campo(campo, key_campo, ruta_aspirante))
        elif spec["tipo"] == "promedio":
            agregaciones[spec["key"]] = Avg(_expresion_de_campo(campo, key_campo, ruta_aspirante))

    crudos = queryset.aggregate(**agregaciones)
    total = crudos.get("_total") or 0

    indicadores = []
    for spec in especificaciones:
        valor = total if spec["tipo"] == "conteo" else crudos.get(spec["key"])

        indicador = {
            "label": spec["label"],
            "icono": spec["icono"],
            "color": spec["color"],
            "valor": _formatear_valor(valor, spec.get("formato", "entero"), spec.get("sufijo", "")),
        }
        if spec.get("con_porcentaje"):
            indicador["porcentaje"] = round((valor or 0) * 100 / total, 1) if total else 0
        indicadores.append(indicador)

    return indicadores, total


def _formatear_valor(valor, formato, sufijo=""):
    """Presenta un número con separadores de miles al estilo español."""
    if valor is None:
        return "—"

    if formato == "moneda":
        texto = f"{float(valor):,.2f}"
    elif formato == "decimal":
        texto = f"{float(valor):,.1f}"
    else:
        texto = f"{int(valor):,}"

    # Python formatea al estilo inglés (1,234.56) y en español es al revés
    # (1.234,56). Se separa la parte entera de la decimal para intercambiarlos
    # sin que un reemplazo pise al otro.
    entero, _, decimales = texto.partition(".")
    entero = entero.replace(",", ".")
    texto = f"{entero},{decimales}" if decimales else entero

    return texto + sufijo


def calcular_desglose(queryset, definicion_modelo, key_campo, total):
    """
    Cuenta cuántos registros hay en cada valor de un campo: el "cuántos hay de
    cada tipo" que acompaña a los indicadores.

    Se resuelve con values(...).annotate(Count(...)), es decir, un GROUP BY real
    en PostgreSQL: Django recibe una fila por grupo, no los registros completos.
    """
    campo = _obtener_campo(definicion_modelo, key_campo)
    if not campo.get("agrupable"):
        raise ConfiguracionInformeInvalida(
            f"El campo «{campo['label']}» no se puede usar para desglosar el resumen."
        )

    ruta_valor = campo["ruta_orm"] or key_campo
    # Algunos campos se guardan de una forma y se muestran de otra (grupo_escala
    # se ordena por su número pero se enseña en romano). Se piden ambas columnas
    # para poder ordenar por una y mostrar la otra.
    ruta_visual = campo.get("ruta_visual")
    columnas = [ruta_valor] + ([ruta_visual] if ruta_visual else [])

    grupos = (
        queryset
        .values(*columnas)
        .annotate(cantidad=Count("id"))
        .order_by("-cantidad", ruta_valor)
    )

    ruta_a_mostrar = ruta_visual or ruta_valor
    traduccion = mapa_valor_a_etiqueta(campo)

    # Varios valores de la base de datos pueden compartir etiqueta (CDI y CEJ
    # son ambos "Cuadro"), así que se acumulan bajo la misma fila.
    acumulado = {}
    for grupo in grupos:
        valor_crudo = grupo.get(ruta_a_mostrar)
        etiqueta = traduccion.get(valor_crudo, valor_crudo)
        acumulado[etiqueta] = acumulado.get(etiqueta, 0) + grupo["cantidad"]

    filas = [
        {
            "valor": etiqueta,
            "cantidad": cantidad,
            "porcentaje": round(cantidad * 100 / total, 1) if total else 0,
        }
        for etiqueta, cantidad in sorted(acumulado.items(), key=lambda par: -par[1])
    ]

    return filas, campo["label"]


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