"""
Motor de construcción de consultas para Informe Inteligente.

Traduce la configuración JSON de un informe (campos, filtros, orden) en un
QuerySet real de Django, usando el registro de informe_inteligente/metadata.py
como única fuente de verdad sobre qué es válido.
"""
from datetime import date, timedelta

from django.db.models import Q, F, Value, CharField, Count, Sum, Avg, OuterRef, Subquery
from django.db.models.functions import Coalesce, Concat, ExtractYear, ExtractMonth, ExtractDay
from django.db.models.expressions import Func
from django.apps import apps

# La paleta de las categorías ocupacionales vive en `nomencladores`, que es su
# fuente única: la misma que pintan las insignias de los listados, las barras
# del Dashboard y las columnas de los Excel de RRHH.
from nomencladores.models import (COLORES_CAT_OCUPACIONAL, COLORES_SEXO,
                                  color_de_categoria, color_de_sexo,
                                  sigla_de_nivel_educacional)
from usuarios.alcance import tiene_alcance_acotado, ve_toda_la_empresa

from .metadata import (
    REGISTRO_MODELOS,
    PREFIJO_CONTRATOS_POR_TIPO,
    definicion_viva,
    LOOKUP_POR_OPERADOR,
    OPERADORES_MULTIVALOR,
    INDICADORES_POR_MODELO,
    FUENTES_HISTORICAS,
    definicion_historica,
    DESGLOSES_ESPECIALES_POR_MODELO,
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
    definicion = definicion_viva(modelo_raiz)
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
        elif key == "antiguedad":
            # Años cumplidos en la entidad, misma lógica que "edad" pero sobre
            # fecha_alta_entidad, que vive directo en CAlta (sin pasar por
            # aspirante__): un contrato puede tener antigüedad distinta a la
            # de otro del mismo trabajador si fue recontratado.
            from django.db.models import IntegerField
            queryset = queryset.annotate(
                antiguedad=EdadExacta(F("fecha_alta_entidad"), output_field=IntegerField())
            )
        elif key == "cumpleanos":
            # Mes y día de nacimiento por separado: permiten mostrar "15 AGO"
            # (formateado en views.py) y ordenar cronológicamente sin depender
            # del año de nacimiento.
            queryset = queryset.annotate(
                mes_nacimiento=ExtractMonth(F(f"{prefijo}fecha_nacimiento")),
                dia_nacimiento=ExtractDay(F(f"{prefijo}fecha_nacimiento")),
            )
        elif key == "vacantes":
            # Plazas aprobadas menos cubiertas. No se guarda en ninguna tabla
            # —sería un tercer número que se puede desincronizar de los otros
            # dos— y sale igual de la fuente viva que de la fotografía mensual,
            # porque el cierre congela las dos cantidades.
            from django.db.models import IntegerField
            queryset = queryset.annotate(
                vacantes=F("cant_aprobada") - F("cant_cubierta"),
            )
        elif key in CONTEOS_DE_CONTRATOS or key.startswith(PREFIJO_CONTRATOS_POR_TIPO):
            queryset = queryset.annotate(**{key: _conteo_de_contratos(queryset.model, key)})
        elif key in ("maestria", "doctorado"):
            # El importe ya no vive en el contrato (23-10-2026): el del grado
            # científico del trabajador según el nomenclador, o 0 si no lo tiene.
            from django.db.models import Case, DecimalField, OuterRef, Subquery, When
            from nomencladores.models import NImporteGradoCientifico
            grado = "MC" if key == "maestria" else "DC"
            importe = Subquery(NImporteGradoCientifico.objects.filter(grado=grado)
                               .values("importe")[:1])
            queryset = queryset.annotate(**{key: Case(
                When(**{f"{prefijo}grado_cientifico": grado}, then=Coalesce(importe, Value(0))),
                default=Value(0), output_field=DecimalField(max_digits=10, decimal_places=2))})
        elif key in ("cnci", "instructor"):
            from django.db.models import DecimalField
            queryset = queryset.annotate(**{key: Coalesce(
                F(f"{key}_nomenclador__importe"), Value(0),
                output_field=DecimalField(max_digits=10, decimal_places=2))})
        # Si en el futuro se añade otro campo calculado, su anotación va aquí.

    return queryset


def _q_rango_dia_mes(ruta, mes_desde, dia_desde, mes_hasta, dia_hasta):
    """
    Q de "día+mes entre A y B" ignorando el año, sin enumerar cada día (a
    diferencia del operador 'semana', que sí enumera 7 combinaciones porque
    ahí el rango nunca crece). Se arma con comparaciones puras de mes/día:

      no cruza fin de año (A <= B): mes,día debe caer DESPUÉS de A Y ANTES de B
      cruza fin de año (A > B, ej. 20/12 a 05/01): DESPUÉS de A O ANTES de B
    """
    desde_o_despues = (
        Q(**{f"{ruta}__month__gt": mes_desde}) |
        Q(**{f"{ruta}__month": mes_desde, f"{ruta}__day__gte": dia_desde})
    )
    hasta_o_antes = (
        Q(**{f"{ruta}__month__lt": mes_hasta}) |
        Q(**{f"{ruta}__month": mes_hasta, f"{ruta}__day__lte": dia_hasta})
    )
    if (mes_desde, dia_desde) <= (mes_hasta, dia_hasta):
        return desde_o_despues & hasta_o_antes
    return desde_o_despues | hasta_o_antes


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
        if campo.get("recurrente_anual"):
            # Cumpleaños y campos similares: el rango solo compara día+mes,
            # el año de nacimiento es irrelevante. 'valor' trae
            # {"desde": "MM-DD", "hasta": "MM-DD"}, ver informe_inteligente.js.
            try:
                mes_desde, dia_desde = (int(parte) for parte in valor.get("desde", "").split("-"))
                mes_hasta, dia_hasta = (int(parte) for parte in valor.get("hasta", "").split("-"))
            except (ValueError, AttributeError):
                raise ConfiguracionInformeInvalida(
                    f"El rango de fechas del filtro «{campo['label']}» no es válido."
                )
            return _q_rango_dia_mes(ruta, mes_desde, dia_desde, mes_hasta, dia_hasta)
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

    # Campos JERÁRQUICOS: el valor elegido representa también a los que cuelgan
    # de él. Es el caso de la Unidad Organizativa, donde elegir una Dirección
    # Principal debe traer también a sus subunidades — sin esto, filtrar por una
    # principal no devolvía nada, porque no tiene cargos propios: todo cuelga de
    # sus hijas.
    #
    # Se resuelve AQUÍ, en la construcción del filtro, y no con `grupos_valores`,
    # que es el mecanismo vecino: aquel colapsa también la PRESENTACIÓN, y un
    # trabajador de una subunidad acabaría mostrándose en la tabla y en el
    # desglose con el nombre de su principal. Aquí cada valor se sigue viendo con
    # su propio nombre y solo cambia a qué filas alcanza el filtro.
    if campo.get("expansion_filtro") and operador in ("igual", "diferente", "en_lista", "no_en_lista"):
        etiquetas = valor if isinstance(valor, (list, tuple)) else [valor]
        # Se le pasa la lista ENTERA y no una etiqueta cada vez: así resuelve la
        # expansión con una sola consulta aunque el usuario haya marcado varias
        # unidades en un «Es alguno de».
        q = Q(**{f"{ruta}__in": campo["expansion_filtro"](list(etiquetas))})
        return ~q if operador in ("diferente", "no_en_lista") else q

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

    El reparto lo decide `usuarios.alcance`: el Administrador ve todo; el
    Moderador solo sus unidades; y el Observador ve todo SOLO mientras no tenga
    unidades asignadas — si el Administrador le asignó alguna, se filtra igual
    que un Moderador.

    'ruta_unidad_organizativa' en el registro de metadata.py admite 3 formas:
      - un string: se filtra por esa única ruta (caso normal: CAlta, CBaja,
        CargoPlantilla).
      - una lista de strings: el moderador ve el registro si CUALQUIERA de
        esas rutas cae en sus unidades asignadas (OR) — caso de TMovimiento,
        donde un movimiento puede afectar a la unidad de origen o de destino.
      - None: el modelo no tiene ningún concepto de Unidad Organizativa
        (decisión de negocio, ej. Aspirante — un aspirante no pertenece a
        ninguna unidad todavía). Sin nada que acotar, quien tiene el alcance
        acotado ve todo, igual que el Administrador.
    """
    if ve_toda_la_empresa(usuario):
        return queryset  # Ven todo, sin restricción

    if tiene_alcance_acotado(usuario):
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


def resolver_definicion(modelo_raiz, periodo=None):
    """Definición a usar: la viva, o su gemela histórica si se pidió un período.

    Es el único punto donde se decide si el informe mira los datos de ahora
    mismo o la fotografía de un mes cerrado. Devuelve
    `(definicion, nombre_del_modelo)`.
    """
    if not periodo:
        return _obtener_definicion_modelo(modelo_raiz), modelo_raiz

    historica = definicion_historica(modelo_raiz)
    if historica is None:
        raise ConfiguracionInformeInvalida(
            "Este informe solo existe en tiempo real: no se guarda una "
            "fotografía mensual de estos datos, así que no se puede consultar "
            "un mes pasado.")
    return historica, historica["modelo_historico"]


def _construir_queryset_filtrado(modelo_raiz, configuracion, usuario, periodo=None):
    """
    Parte común a todos los modos de informe: aplica el alcance por rol,
    las anotaciones necesarias y los filtros del usuario. NO ordena, porque
    cada modo necesita un orden distinto.

    Con `periodo` ('AAAA-MM') el informe se construye sobre la fotografía de
    ese cierre en vez de sobre los datos vivos.

    Devuelve la tupla (queryset, definicion_modelo).
    """
    definicion_modelo, nombre_modelo = resolver_definicion(modelo_raiz, periodo)
    app_label = definicion_modelo["app_label"]
    Modelo = apps.get_model(app_label, nombre_modelo)

    queryset = Modelo.objects.all()

    if periodo:
        # Acotar al mes pedido es lo primero: todo lo demás (alcance, filtros,
        # indicadores) debe calcularse ya dentro de ese período.
        queryset = queryset.filter(cierre__periodo_clave=periodo)
    # El informe de Bajas/Aspirantes es sobre el estado vigente del
    # trabajador, no un historial de eventos: se aplica siempre, antes que
    # cualquier otra cosa.
    elif modelo_raiz == "CBaja":
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
    usa_relacion_m2m = False
    for filtro in configuracion.get("filtros", []):
        campo_filtro = _obtener_campo(definicion_modelo, filtro["campo"])
        if campo_filtro.get("es_m2m"):
            usa_relacion_m2m = True
        queryset = queryset.filter(_construir_q_de_filtro(definicion_modelo, filtro))

    if usa_relacion_m2m:
        # Filtrar por una relación ManyToMany (ej. familias de un cargo) hace
        # JOIN y puede duplicar filas (un cargo con 2 familias duplicaría al
        # trabajador). distinct() se aplica aquí, antes de paginar/agregar,
        # para que tanto el listado como los indicadores usen el mismo total.
        queryset = queryset.distinct()

    return queryset, definicion_modelo


def construir_queryset(modelo_raiz, configuracion, usuario, periodo=None):
    """
    Modo LISTADO: devuelve un QuerySet de registros individuales, listo para
    paginar (sin evaluar todavía).

    Con `periodo` ('AAAA-MM') el informe se construye sobre la fotografía de
    ese cierre mensual en vez de sobre los datos vivos.
    """
    queryset, definicion_modelo = _construir_queryset_filtrado(
        modelo_raiz, configuracion, usuario, periodo)

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
    from django.db.models import IntegerField

    if key_campo == "edad":
        prefijo = f"{ruta_aspirante}__" if ruta_aspirante else ""
        return EdadExacta(F(f"{prefijo}fecha_nacimiento"), output_field=IntegerField())

    # La antigüedad se calcula aquí, y NO se lee de la anotación del mismo
    # nombre: las anotaciones solo se ponen para los campos que el usuario ha
    # elegido, y el indicador de antigüedad promedio se calcula siempre, elija
    # o no esa columna. Leer `F("antiguedad")` reventaría con FieldError en
    # cuanto el informe no la incluyera.
    if key_campo == "antiguedad":
        return EdadExacta(F("fecha_alta_entidad"), output_field=IntegerField())

    # Mismo motivo que la antigüedad: el indicador de plazas vacantes se calcula
    # aunque el usuario no haya elegido esa columna, así que no puede depender
    # de la anotación.
    if key_campo == "vacantes":
        return F("cant_aprobada") - F("cant_cubierta")

    return F(campo["ruta_orm"] or key_campo)


#: Conteos de contratos por cargo («Estructura y Plantilla Aprobada»,
#: 24-10-2026): clave -> filtro sobre el contrato. Valen igual en la fuente viva
#: (CAlta, solo trabajadores activos) que en la fotografía del cierre
#: (CierreContrato), porque las dos guardan `ocupa_plaza` y `requiere_motivo`.
CONTEOS_DE_CONTRATOS = {
    'contratos_activos': {},
    'contratos_ocupan_plaza': {'ocupa_plaza': True},
    'contratos_no_ocupan_plaza': {'ocupa_plaza': False},
}


def _conteo_de_contratos(modelo, key):
    """Subconsulta con el número de contratos del cargo de cada fila."""
    from django.db.models import Count, IntegerField, OuterRef, Subquery

    historico = modelo._meta.model_name == 'cierrecargo'
    if key.startswith(PREFIJO_CONTRATOS_POR_TIPO):
        # Una columna por tipo de contrato: la fotografía guarda el id original.
        tipo_id = int(key[len(PREFIJO_CONTRATOS_POR_TIPO):])
        filtro_vivo = {'tipo_id': tipo_id}
        filtro_historico = {'tipo_id_original': tipo_id}
    else:
        filtro_historico = CONTEOS_DE_CONTRATOS[key]
        filtro_vivo = {'tipo__' + campo: valor for campo, valor in filtro_historico.items()}
    if historico:
        from cierres.models import CierreContrato
        contratos = CierreContrato.objects.filter(cierre_cargo=OuterRef('pk'), **filtro_historico)
        agrupar = 'cierre_cargo'
    else:
        from contratos.models import CAlta
        contratos = CAlta.objects.filter(cargo=OuterRef('pk'), aspirante__estado='ACTIVO', **filtro_vivo)
        agrupar = 'cargo'
    total = (contratos.order_by().values(agrupar).annotate(n=Count('pk')).values('n')[:1])
    return Coalesce(Subquery(total, output_field=IntegerField()), Value(0))


def _condiciones_de(spec):
    """Las condiciones de un indicador `conteo_si`, siempre como lista.

    Un indicador puede pedir una sola condición —la forma corta `campo`/`valor`,
    que es la de casi todos— o varias a la vez, con `condiciones`. «Mujeres en
    puestos clave» es de las segundas: cruza sexo con puesto clave, y sin esto
    habría que inventar un campo calculado en la base de datos para cada cruce
    que a alguien se le ocurra.
    """
    if spec.get("condiciones"):
        return spec["condiciones"]
    return [{"campo": spec["campo"], "valor": spec["valor"]}]


def _q_de_condiciones(definicion_modelo, condiciones):
    """Traduce las condiciones de un indicador a un Q, o None si algún campo ya
    no existe en este catálogo (la gemela historica puede no tenerlo todo).

    Un valor de tipo lista se resuelve con `__in`: es lo que permite contar los
    Cuadros —Directivos y Ejecutivos son dos códigos distintos— o a quien tiene
    grado científico, sea Máster o Doctor, sin escribir dos indicadores.
    """
    filtro = Q()
    for condicion in condiciones:
        campo = definicion_modelo["campos"].get(condicion["campo"])
        if not campo:
            return None
        ruta = campo["ruta_orm"] or condicion["campo"]
        valor = condicion["valor"]
        if isinstance(valor, (list, tuple, set)):
            filtro &= Q(**{f"{ruta}__in": list(valor)})
        else:
            filtro &= Q(**{ruta: valor})
    return filtro


def indicadores_disponibles(modelo_raiz):
    """Las tarjetas de resumen que este modelo sabe calcular: clave y rótulo.

    Alimenta el selector múltiple del panel: el usuario elige cuáles quiere ver
    en vez de recibir las dieciséis de golpe.
    """
    return [{"key": spec["key"], "label": spec["label"]}
            for spec in INDICADORES_POR_MODELO.get(modelo_raiz, [])]


def calcular_indicadores(queryset, definicion_modelo, modelo_raiz, keys=None):
    """
    Calcula las tarjetas del panel de resumen (total, % de mujeres, edad y
    salario promedio...) sobre el mismo conjunto de registros que se lista.

    `keys` son las tarjetas que el usuario ha pedido. Sin ellas no se calcula
    ninguna: el resumen aparece cuando se pide, igual que el desglose. Antes se
    calculaban y se pintaban las dieciséis siempre, y no había forma de quitar
    las que no interesaban.

    El total de registros se devuelve SIEMPRE, aunque no se pida ninguna
    tarjeta: lo necesitan la paginación, los porcentajes del desglose y el aviso
    de tamaño al exportar.

    Las pedidas se resuelven en UNA sola consulta de agregación: se acumulan en
    un diccionario y se envían juntas a .aggregate(). Con 50.000 trabajadores el
    coste es prácticamente el mismo que con 50.
    """
    todas = INDICADORES_POR_MODELO.get(modelo_raiz, [])
    pedidas = set(keys or [])
    especificaciones = [spec for spec in todas if spec["key"] in pedidas]

    if not especificaciones:
        return [], queryset.count()

    ruta_aspirante = definicion_modelo.get("ruta_aspirante")
    agregaciones = {"_total": Count("id")}

    # Las tarjetas de la plantilla IGNORAN los cargos fuera de la plantilla
    # aprobada: existen y pueden tener gente, pero no son plantilla y no deben
    # inflar «Plazas aprobadas», «Cobertura» ni ninguna otra cifra oficial.
    # `_total` se queda sin este filtro a propósito: es el que pagina el listado,
    # y el listado sí los muestra. Para lo que miden las tarjetas se usa
    # `_total_indicadores`. En la gemela histórica el campo se llama igual, así
    # que la misma condición sirve para el informe vivo y para un mes cerrado.
    filtro_plantilla = Q(en_plantilla=True) if modelo_raiz == "CargoPlantilla" else None
    if filtro_plantilla is not None:
        agregaciones["_total_indicadores"] = Count("id", filter=filtro_plantilla)

    for spec in especificaciones:
        if spec["tipo"] == "conteo":
            continue

        if spec["tipo"] == "conteo_si":
            filtro = _q_de_condiciones(definicion_modelo, _condiciones_de(spec))
            if filtro is None:
                continue  # algún campo ya no está en el registro
            if filtro_plantilla is not None:
                filtro = filtro & filtro_plantilla
            agregaciones[spec["key"]] = Count("id", filter=filtro)
            continue

        key_campo = spec["campo"]
        campo = definicion_modelo["campos"].get(key_campo)
        if not campo:
            continue  # el campo se eliminó del registro: se omite el indicador

        if spec["tipo"] == "razon":
            # Dos sumas que luego se dividen. La división se hace en Python y no
            # en SQL para poder decidir qué hacer cuando el divisor es cero, que
            # en la base de datos sería un error y aquí es sencillamente «—».
            divisor = definicion_modelo["campos"].get(spec["campo_divisor"])
            if not divisor:
                continue
            ruta_aspirante_local = ruta_aspirante
            agregaciones[spec["key"] + "__num"] = Sum(
                _expresion_de_campo(campo, key_campo, ruta_aspirante_local),
                filter=filtro_plantilla)
            agregaciones[spec["key"] + "__den"] = Sum(
                _expresion_de_campo(divisor, spec["campo_divisor"], ruta_aspirante_local),
                filter=filtro_plantilla)
        elif spec["tipo"] == "suma":
            agregaciones[spec["key"]] = Sum(
                _expresion_de_campo(campo, key_campo, ruta_aspirante),
                filter=filtro_plantilla)
        elif spec["tipo"] == "promedio":
            agregaciones[spec["key"]] = Avg(
                _expresion_de_campo(campo, key_campo, ruta_aspirante),
                filter=filtro_plantilla)

    crudos = queryset.aggregate(**agregaciones)
    total = crudos.get("_total") or 0
    # Base de las tarjetas: sin los cargos fuera de plantilla cuando aplica.
    total_indicadores = (crudos.get("_total_indicadores") or 0
                         if filtro_plantilla is not None else total)

    indicadores = []
    for spec in especificaciones:
        if spec["tipo"] == "conteo":
            valor = total_indicadores
        elif spec["tipo"] == "razon":
            valor = _razon(crudos.get(spec["key"] + "__num"),
                           crudos.get(spec["key"] + "__den"))
        else:
            valor = crudos.get(spec["key"])

        indicador = {
            # La clave viaja hasta la plantilla porque los exportables la usan
            # para respetar el orden en que el usuario eligió las tarjetas.
            "key": spec["key"],
            "label": spec["label"],
            "icono": spec["icono"],
            "color": spec["color"],
            "valor": _formatear_valor(valor, spec.get("formato", "entero"), spec.get("sufijo", "")),
        }
        if spec.get("con_porcentaje"):
            indicador["porcentaje"] = (round((valor or 0) * 100 / total_indicadores, 1)
                                       if total_indicadores else 0)
        indicadores.append(indicador)


    return indicadores, total


def indicadores_graficables(modelo_raiz):
    """Indicadores que tienen sentido dibujar en una línea de evolución.

    Se devuelven TODOS, incluidos los que en la tarjeta del resumen llevan
    porcentaje. Antes se excluían por miedo a confundir, y el efecto era el
    contrario: «Mujeres» no se podía graficar en absoluto, cuando lo que se
    dibuja es su CANTIDAD —el número entero del que sale ese porcentaje—, que
    es justo lo que hace falta para ver si sube o baja mes a mes.

    Se devuelven como pares (clave, etiqueta) para el desplegable del panel.
    """
    if modelo_raiz not in FUENTES_HISTORICAS:
        return []
    return [
        (spec["key"] if spec["tipo"] != "conteo" else "_total", spec["label"])
        for spec in INDICADORES_POR_MODELO.get(modelo_raiz, [])
    ]


def annos_con_cierre():
    """Años que tienen al menos un cierre declarado, de menor a mayor.

    El `order_by()` vacío es imprescindible: `CierreUnidad` ordena por defecto
    por (-anno, -mes, unidad), y PostgreSQL añade esas columnas al SELECT del
    DISTINCT, con lo que un año con tres cierres saldría tres veces.
    """
    from cierres.models import CierreUnidad
    return sorted(
        CierreUnidad.objects.order_by().values_list("anno", flat=True).distinct())


def calcular_evolucion(modelo_raiz, configuracion, usuario, key_indicador, anno):
    """Valor de un indicador en los DOCE meses de un año, para el gráfico.

    Es la única lectura del módulo que atraviesa varios períodos a la vez: el
    resto del informe siempre mira un momento concreto (ahora, o un cierre). Se
    resuelve con una agregación por mes en vez de una consulta gigante agrupada,
    porque cada período aplica por su cuenta el alcance del usuario y sus
    filtros, y como mucho son doce.

    Los meses sin cierre declarado devuelven `None`, NO cero: cero significaría
    que ese mes no había nadie, cuando lo que ocurre es que nadie lo declaró.
    El gráfico dibuja un hueco, que es lo único que no miente.

    Los filtros que el usuario tenga puestos se respetan: si está mirando solo
    Cuadros, la línea es la evolución de los Cuadros, no de toda la plantilla.
    """
    if modelo_raiz not in FUENTES_HISTORICAS:
        raise ConfiguracionInformeInvalida(
            "De este informe no se guarda una fotografía mensual, así que no "
            "se puede dibujar su evolución.")

    specs = {
        (spec["key"] if spec["tipo"] != "conteo" else "_total"): spec
        for spec in INDICADORES_POR_MODELO.get(modelo_raiz, [])
    }
    spec = specs.get(key_indicador)
    if spec is None:
        raise ConfiguracionInformeInvalida("La medida elegida no está disponible.")

    # Los nombres de mes ya viven en el módulo de Cierres: una sola fuente.
    from cierres.constantes import MESES

    # Una sola consulta para saber qué meses de este año existen, en vez de
    # doce agregaciones a ciegas de las que la mayoría no devolvería nada.
    declarados = set(_opciones_periodos_cerrados_de(anno))

    puntos = []
    for mes in range(1, 13):
        periodo = f"{anno}-{mes:02d}"
        etiqueta = MESES[mes - 1]

        if periodo not in declarados:
            puntos.append({"periodo": periodo, "etiqueta": etiqueta, "valor": None})
            continue

        queryset, definicion = _construir_queryset_filtrado(
            modelo_raiz, configuracion, usuario, periodo)

        # Mismo criterio que las tarjetas del resumen: la evolución de la
        # plantilla no cuenta los cargos que quedaron fuera de ella.
        if modelo_raiz == "CargoPlantilla":
            queryset = queryset.filter(en_plantilla=True)

        if spec["tipo"] == "conteo":
            valor = queryset.count()
        elif spec["tipo"] == "conteo_si":
            # Mismo criterio que la tarjeta del resumen: se cuentan los registros
            # que cumplen la condición. Es lo que permite dibujar la línea de
            # Mujeres, de Cuadros o de quienes están en misión.
            filtro = _q_de_condiciones(definicion, _condiciones_de(spec))
            valor = None if filtro is None else queryset.filter(filtro).count()
        elif spec["tipo"] == "razon":
            campo = definicion["campos"].get(spec["campo"])
            divisor = definicion["campos"].get(spec["campo_divisor"])
            if not campo or not divisor:
                valor = None
            else:
                ruta_aspirante = definicion.get("ruta_aspirante")
                crudos = queryset.aggregate(
                    num=Sum(_expresion_de_campo(campo, spec["campo"], ruta_aspirante)),
                    den=Sum(_expresion_de_campo(
                        divisor, spec["campo_divisor"], ruta_aspirante)))
                valor = _razon(crudos["num"], crudos["den"])
        else:
            campo = definicion["campos"].get(spec["campo"])
            if not campo:
                valor = None
            else:
                expresion = _expresion_de_campo(
                    campo, spec["campo"], definicion.get("ruta_aspirante"))
                funcion = Sum if spec["tipo"] == "suma" else Avg
                valor = queryset.aggregate(v=funcion(expresion))["v"]

        puntos.append({
            "periodo": periodo,
            "etiqueta": etiqueta,
            "valor": float(valor) if valor is not None else None,
        })

    return puntos, spec["label"], spec.get("formato", "entero")


def _opciones_periodos_cerrados_de(anno):
    """Claves 'AAAA-MM' con cierre declarado dentro de un año concreto."""
    from cierres.models import CierreUnidad
    return (CierreUnidad.objects
            .filter(anno=anno)
            .exclude(periodo_clave="")
            .values_list("periodo_clave", flat=True)
            .distinct())


def _razon(numerador, divisor):
    """Porcentaje de `numerador` sobre `divisor`, o None si no se puede.

    Divisor cero o vacío devuelve None y la tarjeta muestra «—»: una plantilla
    sin plazas aprobadas no tiene un 0 % de cobertura, no tiene cobertura
    ninguna, y pintar un cero rotundo diría algo que no es.
    """
    if not divisor:
        return None
    return round(float(numerador or 0) * 100 / float(divisor), 1)


def _formatear_valor(valor, formato, sufijo=""):
    """Presenta un número con separadores de miles al estilo español."""
    if valor is None:
        return "—"

    if formato == "moneda":
        texto = f"{float(valor):,.2f}"
    elif formato == "porcentaje":
        texto = f"{float(valor):,.1f}"
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


def _buscar_desglose_especial(modelo_raiz, key_campo):
    """Busca `key_campo` entre los desgloses especiales (por suma) del
    modelo raíz. Devuelve su especificación o None si no es uno de ellos."""
    for spec in DESGLOSES_ESPECIALES_POR_MODELO.get(modelo_raiz, []):
        if spec["key"] == key_campo:
            return spec
    return None


def _calcular_desglose_por_suma(queryset, spec):
    """
    Suma un campo numérico agrupado por otro campo (ej. plazas aprobadas por
    Unidad Organizativa), en vez de contar registros. El porcentaje de cada
    fila se calcula sobre el total de la SUMA, no sobre la cantidad de
    registros del queryset.
    """
    ruta_agrupacion = spec["ruta_agrupacion"]
    ruta_suma = spec["ruta_suma"]

    # Un desglose puede acotar su propio conjunto (`filtro` en su definición).
    # Se aplica aquí, sobre el queryset ya filtrado por el usuario, para que el
    # desglose y la tarjeta que mide lo mismo cuenten siempre lo mismo.
    filtro = spec.get("filtro")
    if filtro:
        queryset = queryset.filter(**filtro)

    grupos = (
        queryset
        .values(ruta_agrupacion)
        .annotate(cantidad=Sum(ruta_suma))
        .order_by("-cantidad", ruta_agrupacion)
    )

    total = queryset.aggregate(total=Sum(ruta_suma))["total"] or 0

    filas = [
        {
            "valor": grupo[ruta_agrupacion] or "Sin especificar",
            "cantidad": grupo["cantidad"] or 0,
            "porcentaje": round((grupo["cantidad"] or 0) * 100 / total, 1) if total else 0,
        }
        for grupo in grupos
    ]

    return filas, spec["label"]


def calcular_desglose(queryset, definicion_modelo, key_campo, total, modelo_raiz=None):
    """
    Cuenta cuántos registros hay en cada valor de un campo: el "cuántos hay de
    cada tipo" que acompaña a los indicadores.

    Se resuelve con values(...).annotate(Count(...)), es decir, un GROUP BY real
    en PostgreSQL: Django recibe una fila por grupo, no los registros completos.

    Si `key_campo` es uno de los desgloses especiales del modelo raíz (ver
    DESGLOSES_ESPECIALES_POR_MODELO), se suma un campo en vez de contar.
    """
    especial = _buscar_desglose_especial(modelo_raiz, key_campo)
    if especial:
        return _calcular_desglose_por_suma(queryset, especial)

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
    traduccion = _traduccion_del_desglose(key_campo, campo)

    # Varios valores de la base de datos pueden compartir etiqueta (CDI y CEJ
    # son ambos "Cuadro"), así que se acumulan bajo la misma fila.
    #
    # Se guarda además UN código crudo por etiqueta. Sirve para darle a la barra
    # el color global de su categoría ocupacional: la etiqueta sola no basta
    # porque es texto traducido, y el color está definido por código. Que CDI y
    # CEJ compartan fila no estorba: comparten también color.
    acumulado = {}
    codigos = {}
    for grupo in grupos:
        valor_crudo = grupo.get(ruta_a_mostrar)
        etiqueta = traduccion.get(valor_crudo, valor_crudo)
        acumulado[etiqueta] = acumulado.get(etiqueta, 0) + grupo["cantidad"]
        codigos.setdefault(etiqueta, valor_crudo)

    filas = [
        {
            "valor": etiqueta,
            "cantidad": cantidad,
            "porcentaje": round(cantidad * 100 / total, 1) if total else 0,
            "color": _color_de_grupo(codigos.get(etiqueta)),
        }
        for etiqueta, cantidad in sorted(acumulado.items(), key=lambda par: -par[1])
    ]

    return filas, campo["label"]


def _traduccion_del_desglose(key_campo, campo):
    """Cómo se escribe cada valor en las barras del desglose.

    Dos campos no usan su etiqueta larga sino la forma corta que usa la empresa,
    la misma que muestran la tabla y los tres exportables: el SEXO se escribe
    «F» y «M», y el NIVEL EDUCACIONAL en siglas. Un desglose que dijera
    «Femenino» junto a una tabla que dice «F» serían dos formas de nombrar lo
    mismo en la misma pantalla.
    """
    if key_campo == 'sexo':
        # El código guardado ya ES la sigla: basta con no traducir.
        return {}
    if key_campo == 'nivel_educ':
        return {codigo: sigla_de_nivel_educacional(codigo)
                for codigo, _ in (campo.get('choices') or [])}
    return mapa_valor_a_etiqueta(campo)


def _color_de_grupo(codigo):
    """El color global del grupo, o None si el valor no tiene uno asignado.

    Se decide por el CÓDIGO y no por el nombre del campo, así que cualquier
    desglose cuyos valores sean categorías ocupacionales o sexos sale coloreado
    sin tener que enumerar los campos aquí. El resto devuelven None y la
    plantilla los pinta con su color de siempre.
    """
    if codigo in COLORES_CAT_OCUPACIONAL:
        return color_de_categoria(codigo)
    if codigo in COLORES_SEXO:
        return color_de_sexo(codigo)
    return None


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
        if campo.get("es_m2m"):
            # select_related() no admite relaciones ManyToMany (Django lanza
            # FieldError). Estos campos se precargan implícitamente por el
            # propio filtro/columna vía JOIN; no necesitan select_related.
            continue
        partes = campo["ruta_orm"].split("__")
        if len(partes) > 1:
            rutas.add("__".join(partes[:-1]))
    return list(rutas)