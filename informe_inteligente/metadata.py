"""
Registro declarativo de campos reportables para el módulo Informe Inteligente.

Este archivo es la ÚNICA fuente de verdad sobre qué se puede mostrar, filtrar,
ordenar o agrupar en un informe. Si un campo no está aquí, el módulo no sabe
que existe — por diseño, para evitar exponer datos sin control.

Para añadir un campo nuevo: copia un bloque existente parecido y ajusta sus
valores. No hace falta tocar ninguna otra parte del código para que aparezca
en el selector de campos.
"""

# ---------------------------------------------------------------------------
# TIPOS DE CAMPO Y SUS OPERADORES VÁLIDOS
# ---------------------------------------------------------------------------
# Cada tipo determina qué operadores tienen sentido y qué widget usa el filtro.

OPERADORES_POR_TIPO = {
    "texto":   ["igual", "diferente", "contiene", "es_nulo", "no_es_nulo"],
    "numero":  ["igual", "diferente", "mayor", "menor", "es_nulo", "no_es_nulo"],
    "fecha":   ["entre_fechas", "mes", "semana", "mayor", "menor", "es_nulo", "no_es_nulo"],
    "opcion":  ["igual", "diferente", "en_lista", "no_en_lista", "es_nulo", "no_es_nulo"],
    "booleano": ["igual"],
}

# Operadores cuyo valor es una LISTA de opciones en vez de un dato suelto.
# Permiten expresar "es CDI o CEJ" sin que el motor tenga que soportar OR
# genérico entre filtros distintos, que complicaría mucho la construcción
# de la consulta a cambio de muy poco uso real.
OPERADORES_MULTIVALOR = ["en_lista", "no_en_lista"]

# Traducción de cada operador a su lookup real de Django ORM.
# '{campo}' se sustituye por la ruta ORM del campo en tiempo de ejecución.
LOOKUP_POR_OPERADOR = {
    "igual":        "exact",
    "diferente":    "exact",       # se niega con .exclude() en vez de .filter()
    "mayor":        "gt",
    "menor":        "lt",
    "contiene":     "icontains",
    "entre_fechas": "range",
    "mes":          "month",       # Django soporta __month nativo, sin anotación especial
    # 'semana' no tiene lookup directo: se resuelve como caso especial en
    # motor.py (7 condiciones OR de mes+día), igual que 'entre_fechas'.
    "en_lista":     "in",
    "no_en_lista":  "in",          # se niega igual que 'diferente'
    "es_nulo":      "isnull",
    "no_es_nulo":   "isnull",      # se usa con valor=False
}


# ---------------------------------------------------------------------------
# OPCIONES CARGADAS DINÁMICAMENTE DESDE LA BASE DE DATOS
# ---------------------------------------------------------------------------
# A diferencia de 'choices' (lista fija hardcodeada abajo), estas funciones se
# usan en campos cuyo catálogo de valores lo administra el usuario en
# Configuración/Nomencladores y puede crecer. Se evalúan en el momento de
# construir el panel de filtros (una consulta fresca por request), nunca al
# importar este módulo — por eso el import de los modelos va local a cada
# función, para no acoplar la carga de metadata.py a que la BD ya exista.

def _opciones_tipos_familia():
    from nomencladores.models import NTipoFamilia
    return list(NTipoFamilia.objects.order_by("nombre").values_list("nombre", "nombre"))


def _opciones_familias_cargo():
    from nomencladores.models import NFamiliaCargo
    return list(NFamiliaCargo.objects.order_by("nombre").values_list("nombre", "nombre"))


def _opciones_departamentos():
    from strorganizativa.models import Departamento
    return list(Departamento.objects.order_by("descripcion").values_list("descripcion", "descripcion").distinct())


def _opciones_unidades_organizativas():
    from strorganizativa.models import UnidadOrganizativa
    return list(UnidadOrganizativa.objects.order_by("descripcion").values_list("descripcion", "descripcion").distinct())


def _expansion_jerarquica_unidades(etiquetas):
    """Una Unidad Principal representa también a sus subunidades AL FILTRAR.

    EL PROBLEMA QUE RESUELVE
    ------------------------
    Este filtro compara la descripción de la unidad con un `=` exacto, así que
    filtrar por «Oficina Central» no devolvía NADA de sus subunidades — y una
    Dirección Principal no tiene cargos propios: todo cuelga de sus hijas. El
    resultado era un informe vacío para la unidad más grande de la empresa.

    Recibe la LISTA de unidades elegidas y devuelve sus descripciones más las de
    sus subunidades directas. Recibe la lista entera, y no una etiqueta cada vez,
    para resolverlo con UNA sola consulta: con «Es alguno de» y cinco unidades
    marcadas, una consulta por etiqueta serían cinco viajes a la base de datos
    para construir un único filtro.

    Una unidad sin hijas se expande a sí misma, así que elegir una subunidad
    concreta la sigue mostrando SOLA: se puede ver el total del padre o el
    detalle de una hija, que es la razón de tener jerarquía.

    SOLO AFECTA AL FILTRO. No se usa `grupos_valores` —el mecanismo que ya
    existía para agrupar valores— precisamente porque ese SÍ afecta a la
    presentación: colapsaría la etiqueta, y un trabajador de Camagüey aparecería
    en la tabla y en el desglose como «Oficina Central». Aquí cada unidad se
    sigue mostrando con su propio nombre.

    Limitación heredada: la comparación es por texto, así que dos unidades
    distintas con la misma descripción se confundirían. Ya era así antes de esta
    expansión —el filtro siempre ha comparado descripciones— y `descripcion` no
    es un campo único en el modelo.
    """
    from strorganizativa.models import UnidadOrganizativa

    if isinstance(etiquetas, str):
        etiquetas = [etiquetas]

    descripciones = set(etiquetas)
    descripciones.update(
        UnidadOrganizativa.objects
        .filter(padre__descripcion__in=etiquetas)
        .values_list("descripcion", flat=True)
    )
    # Ordenado y sin repetidos, para que dos informes iguales generen exactamente
    # la misma consulta.
    return sorted(descripciones)


def _opciones_cargos():
    from nomencladores.models import NCargo
    return list(NCargo.objects.order_by("descripcion").values_list("descripcion", "descripcion").distinct())


def _opciones_especialidades():
    from nomencladores.models import NEspecialidad
    return list(NEspecialidad.objects.order_by("nombre").values_list("nombre", "nombre").distinct())


def _opciones_niveles_preparacion():
    from nomencladores.models import NNivelPreparacion
    return list(NNivelPreparacion.objects.order_by("nombre").values_list("nombre", "nombre").distinct())


def _opciones_tipos_contrato():
    from nomencladores.models import NTipoContrato
    return list(NTipoContrato.objects.order_by("descripcion").values_list("descripcion", "descripcion").distinct())


def _opciones_motivos_contrato():
    from nomencladores.models import NMotivoContrato
    return list(NMotivoContrato.objects.order_by("descripcion").values_list("descripcion", "descripcion").distinct())


def _opciones_roles():
    from nomencladores.models import NRol
    return list(NRol.objects.order_by("tipo").values_list("tipo", "tipo").distinct())


def _opciones_tridentes():
    from nomencladores.models import NTridente
    return list(NTridente.objects.order_by("tipo").values_list("tipo", "tipo").distinct())


def _opciones_causas_alta_baja():
    from nomencladores.models import NCausaAltaBaja
    return list(NCausaAltaBaja.objects.order_by("descripcion").values_list("descripcion", "descripcion").distinct())


def _opciones_municipios():
    from nomencladores.models import NMunicipio
    return list(NMunicipio.objects.order_by("nombre").values_list("nombre", "nombre").distinct())


def _opciones_provincias():
    from nomencladores.models import NProvincia
    return list(NProvincia.objects.order_by("nombre").values_list("nombre", "nombre").distinct())


# ---------------------------------------------------------------------------
# CATEGORÍAS PARA AGRUPAR LOS CAMPOS EN LA INTERFAZ
# ---------------------------------------------------------------------------
# Solo afectan a cómo se presentan los checkboxes al usuario, no a la consulta.
# El orden de este diccionario (y el de cada diccionario _campos_*() dentro de
# cada categoría) es el orden en que aparecen los checkboxes en el panel, y
# por lo tanto el orden por defecto de las columnas. Pero si el usuario marca
# los checkboxes en otro orden, las columnas del informe (tabla y documentos
# exportables) respetan ESE orden de selección, no este — ver
# camposSeleccionados() en informe_inteligente.js.

CATEGORIAS_CAMPOS = {
    "periodo":    {"label": "Período del Cierre",   "icono": "bi-calendar-check-fill", "color": "azul"},
    "trabajador": {"label": "Datos del Trabajador", "icono": "bi-person-badge-fill", "color": "violeta"},
    "cargo":      {"label": "Datos del Cargo",      "icono": "bi-briefcase-fill",    "color": "indigo"},
    "contrato":   {"label": "Datos del Contrato",   "icono": "bi-file-earmark-text-fill", "color": "esmeralda"},
    "salariales": {"label": "Datos Salariales",     "icono": "bi-cash-stack",        "color": "naranja"},
    "baja":       {"label": "Datos de la Baja",     "icono": "bi-person-dash-fill",  "color": "rosa"},
    "movimiento": {"label": "Antes / Después del Movimiento", "icono": "bi-arrow-left-right", "color": "azul"},
}


# ---------------------------------------------------------------------------
# REGISTRO DE MODELOS RAÍZ
# ---------------------------------------------------------------------------
# Cada modelo raíz define:
#   - el modelo Django real
#   - la ruta ORM para llegar a la Unidad Organizativa (para el filtro de alcance
#     del Moderador). None si el modelo no tiene ese alcance (ej. Aspirante).
#   - el diccionario de campos reportables de ese modelo

def _campos_calta():
    return {
        # ---------------- DATOS DEL TRABAJADOR (vía Aspirante) ----------------
        "nombre_completo": {
            "label": "Nombre y Apellidos",
            "ruta_orm": None,  # se construye por anotación (concat de 3 campos)
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
        "carne_identidad": {
            "label": "Carné de Identidad",
            "ruta_orm": "aspirante__doc_identidad",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "serie_ci": {
            "label": "Serie del Carnet",
            "ruta_orm": "aspirante__serie_ci",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "sexo": {
            "label": "Sexo",
            "ruta_orm": "aspirante__sexo",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("M", "Masculino"), ("F", "Femenino")],
        },
        "edad": {
            "label": "Edad",
            "ruta_orm": None,  # se resuelve por anotación sobre fecha_nacimiento
            "tipo": "numero",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_nacimiento": {
            "label": "Fecha de Nacimiento",
            "ruta_orm": "aspirante__fecha_nacimiento",
            "tipo": "fecha",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
            # "Entre fechas" sobre este campo compara solo día+mes, ignorando
            # el año (para buscar cumpleaños en un rango sin importar en qué
            # año nació cada quien). Ver motor.py::_construir_q_de_filtro.
            "recurrente_anual": True,
        },
        "cumpleanos": {
            "label": "Cumpleaños",
            "ruta_orm": None,  # anotado: mes_nacimiento + dia_nacimiento (ver motor.py)
            "tipo": "texto",   # se muestra ya formateado, ej. "15 AGO"
            "categoria": "trabajador",
            # El filtrado por mes/semana de cumpleaños ya se hace sobre el campo
            # 'fecha_nacimiento' (operadores Mes/Semana); este campo es solo para
            # MOSTRAR la columna "15 AGO" en la tabla de resultados.
            "filtrable": False, "ordenable": True, "agrupable": False,
            "sensible": False,  # día+mes sin año no identifica tanto como la fecha completa
        },
        "raza": {
            "label": "Raza",
            "ruta_orm": "aspirante__raza",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": True,
            "choices": [("BL", "Blanca"), ("NE", "Negra"), ("ME", "Mestiza")],
        },
        "nivel_educ": {
            "label": "Nivel Educacional",
            "ruta_orm": "aspirante__nivel_educ",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [
                ("SA", "Sin Acreditar"), ("PR", "Primaria"), ("NG", "Medio"),
                ("OC", "Obrero Calificado"), ("TM", "Medio Superior (TM)"),
                ("MS", "Medio Superior (DG)"), ("NS", "Nivel Superior"),
            ],
        },
        "grado_cientifico": {
            "label": "Grado Científico",
            "ruta_orm": "aspirante__grado_cientifico",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("MC", "Master"), ("DC", "Doctor")],
        },
        "titulo_oro": {
            "label": "Título de Oro",
            "ruta_orm": "aspirante__titulo_oro",
            "tipo": "booleano",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "especialidad": {
            "label": "Especialidad",
            "ruta_orm": "aspirante__especialidad__nombre",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_especialidades,
        },
        "reg_militar": {
            "label": "Registro Militar",
            "ruta_orm": "reg_militar",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [
                ("MTT", "MTT"), ("IMP", "Imprescindible"),
                ("BPD", "BPD"), ("NIN", "No Incorporado"),
            ],
        },
        "profesional": {
            "label": "Chofer Profesional",
            "ruta_orm": "profesional",
            "tipo": "booleano",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "jubilado_recontratado": {
            "label": "Jubilado Recontratado",
            "ruta_orm": "jubilado_recontratado",
            "tipo": "booleano",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },

        # ---------------- DATOS DEL CARGO ----------------
        "cargo": {
            "label": "Cargo",
            "ruta_orm": "cargo__ncargo__descripcion",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_cargos,
        },
        "categoria_ocupacional": {
            "label": "Categoría Ocupacional",
            "ruta_orm": "cargo__ncargo__cat_ocupacional",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            # En Orbith, Cuadro Directivo (CDI) y Cuadro Ejecutivo (CEJ) no se
            # distinguen: ambos son "Cuadro". Por eso este campo usa
            # 'grupos_valores' en vez de 'choices': varios valores de la base de
            # datos se presentan, se filtran y se cuentan como uno solo.
            "grupos_valores": [
                ("Técnico", ["TEC"]),
                ("Administrativo", ["ADM"]),
                ("Servicio", ["SER"]),
                ("Obrero", ["OPE"]),
                ("Cuadro", ["CDI", "CEJ"]),
            ],
        },
        "grupo_escala": {
            "label": "Grupo Escala",
            "ruta_orm": "cargo__ncargo__grupo_escala__valor_numerico_db",
            "ruta_visual": "cargo__ncargo__grupo_escala__nivel",  # lo que se MUESTRA
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "departamento": {
            "label": "Departamento",
            "ruta_orm": "cargo__departamento__descripcion",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_departamentos,
        },
        "unidad_organizativa": {
            "label": "Unidad Organizativa",
            "ruta_orm": "cargo__departamento__unidad_organizativa__descripcion",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_unidades_organizativas,
            # Elegir una Unidad Principal suma también sus subunidades. Solo al
            # FILTRAR: en la tabla y en el desglose cada unidad conserva su
            # propio nombre. Ver `_expansion_jerarquica_unidades`.
            "expansion_filtro": _expansion_jerarquica_unidades,
        },
        "nivel_preparacion": {
            "label": "Nivel de Preparación",
            "ruta_orm": "cargo__nivel_preparacion__nombre",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_niveles_preparacion,
        },
        "funcionario": {
            "label": "Funcionario",
            "ruta_orm": "cargo__funcionario",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "designado": {
            "label": "Designado",
            "ruta_orm": "cargo__designado",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "cant_aprobada": {
            "label": "Cantidad de Plazas Aprobadas",
            "ruta_orm": "cargo__cant_aprobada",
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "cant_cubierta": {
            "label": "Cantidad de Plazas Cubiertas",
            "ruta_orm": "cargo__cant_cubierta",
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "tipo_familia_cargo": {
            "label": "Tipo de Familia de Cargos",
            "ruta_orm": "cargo__ncargo__familias__tipo_familia__nombre",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_tipos_familia,
            # NCargo.familias es ManyToMany: esta ruta atraviesa esa relación.
            # Ver motor.py (select_related/distinct) y views.py (_resolver_valor_por_ruta).
            "es_m2m": True,
        },
        "familia_cargo": {
            "label": "Familia de Cargos",
            "ruta_orm": "cargo__ncargo__familias__nombre",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_familias_cargo,
            "es_m2m": True,
        },

        # ---------------- DATOS DEL CONTRATO ----------------
        "no_expediente": {
            "label": "No. Expediente",
            "ruta_orm": "no_expediente",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "tipo_contrato": {
            "label": "Tipo de Contrato",
            "ruta_orm": "tipo__descripcion",
            "tipo": "opcion",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_tipos_contrato,
        },
        "fecha_alta": {
            "label": "Fecha de Alta",
            "ruta_orm": "fecha_alta",
            "tipo": "fecha",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_alta_entidad": {
            "label": "F. Alta Entidad",
            "ruta_orm": "fecha_alta_entidad",
            "tipo": "fecha",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "antiguedad": {
            "label": "Antigüedad (años)",
            "ruta_orm": None,  # se resuelve por anotación sobre fecha_alta_entidad
            "tipo": "numero",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "motivo": {
            "label": "Motivo de Contrato",
            "ruta_orm": "motivo__descripcion",
            "tipo": "opcion",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_motivos_contrato,
        },
        "duracion": {
            "label": "Duración",
            "ruta_orm": "duracion",
            "tipo": "numero",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "contrato_determinado": {
            "label": "Contrato Determinado",
            # Se deduce del nomenclador de tipo de contrato: los que exigen
            # motivo son los determinados. Mismo criterio que el informe
            # «Contratos Determinados (Motivos)», para que las dos pantallas no
            # puedan dar cifras distintas.
            "ruta_orm": "tipo__requiere_motivo",
            "tipo": "booleano",
            "categoria": "contrato",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "puesto_clave": {
            "label": "Puesto Clave",
            "ruta_orm": "cargo__ncargo__puesto_clave",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "mision": {
            "label": "Misión",
            "ruta_orm": "mision",
            "tipo": "booleano",
            "categoria": "contrato",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "pais": {
            "label": "País de Misión",
            "ruta_orm": "pais",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "funcionario_res": {
            "label": "No. Res. Funcionario",
            "ruta_orm": "funcionario_res",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "designado_res": {
            "label": "No. Res. Designado",
            "ruta_orm": "designado_res",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "c_formal_res": {
            "label": "No. Res. Calif. Formal",
            "ruta_orm": "c_formal_res",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_vence_lic": {
            "label": "Vencimiento de Licencia",
            "ruta_orm": "fecha_vence_lic",
            "tipo": "fecha",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_vence_recal": {
            "label": "Vencimiento de Recalificación",
            "ruta_orm": "fecha_vence_recal",
            "tipo": "fecha",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_vence_seg": {
            "label": "Vencimiento de Seguro",
            "ruta_orm": "fecha_vence_seg",
            "tipo": "fecha",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },

        # ---------------- DATOS SALARIALES ----------------
        "salario": {
            "label": "Salario",
            "ruta_orm": "salario_actual",
            "tipo": "numero",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "rol": {
            "label": "Rol de Pago",
            "ruta_orm": "rol__tipo",
            "tipo": "opcion",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_roles,
        },
        "tridente": {
            "label": "Tridente",
            "ruta_orm": "tridente__tipo",
            "tipo": "opcion",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_tridentes,
        },
        "tipo_salario": {
            "label": "Tipo de Salario",
            "ruta_orm": "tipo_salario",
            "tipo": "opcion",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("FIJ", "Fijo"), ("DIN", "Dinámico")],
        },
        "maestria": {
            "label": "Maestrías",
            "ruta_orm": "maestria",
            "tipo": "numero",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "doctorado": {
            "label": "Doctorados",
            "ruta_orm": "doctorado",
            "tipo": "numero",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "cnci": {
            "label": "CNCI",
            "ruta_orm": "cnci",
            "tipo": "numero",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "instructor": {
            "label": "Instructor",
            "ruta_orm": "instructor",
            "tipo": "numero",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
    }


def _campos_cbaja():
    """
    CBaja comparte con CAlta los mismos FKs 'aspirante' y 'cargo' (ambos
    heredan de ContratoBase), así que reutiliza casi todo el catálogo de
    CAlta. Se excluyen los campos que solo existen en CAlta (rol de pago,
    salario, vencimientos, maestrías...) y se agregan los propios del
    proceso de baja.
    """
    base = _campos_calta()
    solo_calta = {
        "duracion", "tipo_salario", "rol", "tridente", "maestria", "doctorado",
        "cnci", "instructor",
        "fecha_vence_lic", "fecha_vence_recal", "fecha_vence_seg",
        "jubilado_recontratado", "salario",
    }
    campos = {key: valor for key, valor in base.items() if key not in solo_calta}

    campos.update({
        "causa_baja": {
            "label": "Causa de Baja",
            "ruta_orm": "causa_baja__descripcion",
            "tipo": "opcion",
            "categoria": "baja",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_causas_alta_baja,
        },
        "fecha_baja": {
            "label": "Fecha de Baja",
            "ruta_orm": "fecha_baja",
            "tipo": "fecha",
            "categoria": "baja",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_documento": {
            "label": "Fecha del Documento",
            "ruta_orm": "fecha_documento",
            "tipo": "fecha",
            "categoria": "baja",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "cobro_sistema_pago": {
            "label": "Cobró Sistema de Pago",
            "ruta_orm": "cobro_sistema_pago",
            "tipo": "booleano",
            "categoria": "baja",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "completar_cargo": {
            "label": "Completar Cargo",
            "ruta_orm": "completar_cargo",
            "tipo": "booleano",
            "categoria": "baja",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "actividad_realizada": {
            "label": "Actividad que Realizaba",
            "ruta_orm": "actividad_realizada",
            "tipo": "texto",
            "categoria": "baja",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
        "observaciones_baja": {
            "label": "Observaciones de la Baja",
            "ruta_orm": "observaciones",
            "tipo": "texto",
            "categoria": "baja",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
    })
    return campos


def _campos_cargoplantilla():
    """
    Catálogo de CargoPlantilla (la plaza/estructura, sin importar quién la
    ocupa). Mismos campos de estructura ya usados en el módulo Anexo 14:
    categoría ocupacional, rol, nivel de preparación y grupo escala.
    """
    return {
        "cargo": {
            "label": "Cargo",
            "ruta_orm": "ncargo__descripcion",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_cargos,
        },
        "categoria_ocupacional": {
            "label": "Categoría Ocupacional",
            "ruta_orm": "ncargo__cat_ocupacional",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "grupos_valores": [
                ("Técnico", ["TEC"]),
                ("Administrativo", ["ADM"]),
                ("Servicio", ["SER"]),
                ("Obrero", ["OPE"]),
                ("Cuadro", ["CDI", "CEJ"]),
            ],
        },
        "grupo_escala": {
            "label": "Grupo Escala",
            "ruta_orm": "ncargo__grupo_escala__valor_numerico_db",
            "ruta_visual": "ncargo__grupo_escala__nivel",
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "rol": {
            "label": "Rol",
            "ruta_orm": "rol__tipo",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_roles,
        },
        "nivel_preparacion": {
            "label": "Nivel de Preparación",
            "ruta_orm": "nivel_preparacion__nombre",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_niveles_preparacion,
        },
        "departamento": {
            "label": "Departamento",
            "ruta_orm": "departamento__descripcion",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_departamentos,
        },
        "unidad_organizativa": {
            "label": "Unidad Organizativa",
            "ruta_orm": "departamento__unidad_organizativa__descripcion",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_unidades_organizativas,
            # Elegir una Unidad Principal suma también sus subunidades. Solo al
            # FILTRAR: en la tabla y en el desglose cada unidad conserva su
            # propio nombre. Ver `_expansion_jerarquica_unidades`.
            "expansion_filtro": _expansion_jerarquica_unidades,
        },
        "funcionario": {
            "label": "Funcionario",
            "ruta_orm": "funcionario",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "designado": {
            "label": "Designado",
            "ruta_orm": "designado",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "activo": {
            "label": "Activo",
            "ruta_orm": "activo",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "cant_aprobada": {
            "label": "Cantidad Aprobada",
            "ruta_orm": "cant_aprobada",
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "cant_cubierta": {
            "label": "Cantidad Cubierta",
            "ruta_orm": "cant_cubierta",
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "puesto_clave": {
            "label": "Puesto Clave",
            "ruta_orm": "ncargo__puesto_clave",
            "tipo": "booleano",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "vacantes": {
            "label": "Plazas Vacantes",
            # Sin columna propia: es la resta de aprobadas menos cubiertas, y la
            # calcula el motor por anotación. Guardarla sería un dato duplicado
            # que se puede desincronizar de los otros dos.
            "ruta_orm": None,
            "tipo": "numero",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "tipo_familia_cargo": {
            "label": "Tipo de Familia de Cargos",
            "ruta_orm": "ncargo__familias__tipo_familia__nombre",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_tipos_familia,
            "es_m2m": True,
        },
        "familia_cargo": {
            "label": "Familia de Cargos",
            "ruta_orm": "ncargo__familias__nombre",
            "tipo": "opcion",
            "categoria": "cargo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_familias_cargo,
            "es_m2m": True,
        },
    }


def _campos_aspirante():
    """
    A diferencia de CAlta/CBaja, Aspirante ES el dato personal directamente
    (no hay FK 'aspirante' de por medio): las rutas ORM no llevan prefijo.
    Cubre tanto aspirantes en bolsa como activos o de baja (campo 'estado').
    """
    return {
        "nombre_completo": {
            "label": "Nombre y Apellidos",
            "ruta_orm": None,  # anotado (concat de 3 campos), ver motor.py
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
        "carne_identidad": {
            "label": "Carné de Identidad",
            "ruta_orm": "doc_identidad",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "serie_ci": {
            "label": "Serie del Carnet",
            "ruta_orm": "serie_ci",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "sexo": {
            "label": "Sexo",
            "ruta_orm": "sexo",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("M", "Masculino"), ("F", "Femenino")],
        },
        "edad": {
            "label": "Edad",
            "ruta_orm": None,  # anotado sobre fecha_nacimiento, ver motor.py
            "tipo": "numero",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "estado": {
            "label": "Estado",
            "ruta_orm": "estado",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("ASPIRANTE", "Aspirante"), ("ACTIVO", "Activo"), ("BAJA", "Baja")],
        },
        "fecha_nacimiento": {
            "label": "Fecha de Nacimiento",
            "ruta_orm": "fecha_nacimiento",
            "tipo": "fecha",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
            "recurrente_anual": True,
        },
        "cumpleanos": {
            "label": "Cumpleaños",
            "ruta_orm": None,
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": False, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "raza": {
            "label": "Raza",
            "ruta_orm": "raza",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": True,
            "choices": [("BL", "Blanca"), ("NE", "Negra"), ("ME", "Mestiza")],
        },
        "nivel_educ": {
            "label": "Nivel Educacional",
            "ruta_orm": "nivel_educ",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [
                ("SA", "Sin Acreditar"), ("PR", "Primaria"), ("NG", "Medio"),
                ("OC", "Obrero Calificado"), ("TM", "Medio Superior (TM)"),
                ("MS", "Medio Superior (DG)"), ("NS", "Nivel Superior"),
            ],
        },
        "grado_cientifico": {
            "label": "Grado Científico",
            "ruta_orm": "grado_cientifico",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("MC", "Master"), ("DC", "Doctor")],
        },
        "titulo_oro": {
            "label": "Título de Oro",
            "ruta_orm": "titulo_oro",
            "tipo": "booleano",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "especialidad": {
            "label": "Especialidad",
            "ruta_orm": "especialidad__nombre",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_especialidades,
        },
        "movil_personal": {
            "label": "Móvil",
            "ruta_orm": "movil_personal",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": True,
        },
        "fijo_personal": {
            "label": "Teléfono Fijo",
            "ruta_orm": "fijo_personal",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": True,
        },
        "direccion": {
            "label": "Dirección",
            "ruta_orm": "direccion",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": True,
        },
        "municipio": {
            "label": "Municipio",
            "ruta_orm": "municipio__nombre",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_municipios,
        },
        "provincia": {
            "label": "Provincia",
            "ruta_orm": "provincia__nombre",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_provincias,
        },
    }


def _campos_tmovimiento():
    """
    TMovimiento guarda una "foto" de antes/después de cada movimiento de
    nómina (promoción, traslado, cambio de cargo...). Los campos de texto
    (unidad_anterior, unidad_nueva, etc.) son el histórico inmutable que se
    muestra en el informe; las nuevas columnas FK (unidad_anterior_fk/
    unidad_nueva_fk) NO se exponen aquí — solo existen para acotar el
    alcance de Moderador (ver REGISTRO_MODELOS y motor.py).
    """
    return {
        "nombre_completo": {
            "label": "Nombre y Apellidos",
            "ruta_orm": None,  # anotado vía 'aspirante', ver motor.py
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
        "no_expediente": {
            "label": "No. Expediente",
            "ruta_orm": "no_expediente",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "tipo_movimiento": {
            "label": "Tipo de Movimiento",
            "ruta_orm": "tipo_movimiento",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "fecha_efectiva": {
            "label": "Fecha Efectiva",
            "ruta_orm": "fecha_efectiva",
            "tipo": "fecha",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "fecha_solicitud": {
            "label": "Fecha de Solicitud",
            "ruta_orm": "fecha_solicitud",
            "tipo": "fecha",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "cargo_anterior": {
            "label": "Cargo Anterior",
            "ruta_orm": "cargo_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "cargo_nuevo": {
            "label": "Cargo Nuevo",
            "ruta_orm": "cargo_nuevo",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "unidad_anterior": {
            "label": "Unidad Anterior",
            "ruta_orm": "unidad_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "unidad_nueva": {
            "label": "Unidad Nueva",
            "ruta_orm": "unidad_nueva",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "departamento_anterior": {
            "label": "Departamento Anterior",
            "ruta_orm": "departamento_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "departamento_nuevo": {
            "label": "Departamento Nuevo",
            "ruta_orm": "departamento_nuevo",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "cat_ocupacional_anterior": {
            "label": "Categoría Ocupacional Anterior",
            "ruta_orm": "cat_ocupacional_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "cat_ocupacional_nuevo": {
            "label": "Categoría Ocupacional Nueva",
            "ruta_orm": "cat_ocupacional_nuevo",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "rol_anterior": {
            "label": "Rol Anterior",
            "ruta_orm": "rol_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "rol_nuevo": {
            "label": "Rol Nuevo",
            "ruta_orm": "rol_nuevo",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "salario_anterior": {
            "label": "Salario Anterior",
            "ruta_orm": "salario_anterior",
            "tipo": "numero",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "salario_nuevo": {
            "label": "Salario Nuevo",
            "ruta_orm": "salario_nuevo",
            "tipo": "numero",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "tipo_contrato_anterior": {
            "label": "Tipo de Contrato Anterior",
            "ruta_orm": "tipo_contrato_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "tipo_contrato_nuevo": {
            "label": "Tipo de Contrato Nuevo",
            "ruta_orm": "tipo_contrato_nuevo",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "motivo_anterior": {
            "label": "Motivo Anterior",
            "ruta_orm": "motivo_anterior",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "motivo_nuevo": {
            "label": "Motivo Nuevo",
            "ruta_orm": "motivo_nuevo",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "observaciones": {
            "label": "Observaciones",
            "ruta_orm": "observaciones",
            "tipo": "texto",
            "categoria": "movimiento",
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
    }


DESGLOSES_ESPECIALES_POR_MODELO = {
    # Desgloses del panel de resumen que NO cuentan registros sino que suman
    # un campo numérico agrupado (ej. plazas aprobadas por Unidad
    # Organizativa). No corresponden a ningún campo del catálogo de columnas:
    # solo aparecen como opción extra en el select "Desglosar Resumen Por".
    # Ver motor.py::calcular_desglose_por_suma y views.py::_preparar_datos_informe.
    "CargoPlantilla": [
        {
            "key": "plazas_por_unidad_organizativa",
            "label": "Plazas Aprob. por Unid. Org.",
            "ruta_agrupacion": "departamento__unidad_organizativa__descripcion",
            "ruta_suma": "cant_aprobada",
        },
    ],
}


def _opciones_periodos_cerrados():
    """Períodos que REALMENTE tienen un cierre declarado, del más reciente al más
    antiguo.

    Es la lista que alimenta el desplegable de «Período» en las fuentes
    históricas. Se construye desde los datos y no desde un rango de fechas a
    propósito: así el usuario no puede pedir un mes que nadie cerró y recibir un
    informe vacío sin entender por qué. Un mes sin cierre sencillamente no
    aparece como opción.
    """
    from cierres.models import CierreUnidad
    from cierres.periodos import Periodo

    claves = (CierreUnidad.objects
              .exclude(periodo_clave='')
              .order_by('-anno', '-mes')
              .values_list('periodo_clave', 'anno', 'mes')
              .distinct())
    vistos, opciones = set(), []
    for clave, anno, mes in claves:
        if clave in vistos:
            continue
        vistos.add(clave)
        opciones.append((clave, Periodo(anno, mes).etiqueta))
    return opciones


def _campos_comunes_del_cierre():
    """Campos de la cabecera del cierre, comunes a las dos gemelas.

    `periodo` no es un campo más: es lo que el selector superior fija. Se
    incluye igualmente como columna marcable porque al comparar varios meses
    en un mismo informe hay que poder ver a qué mes pertenece cada fila.
    """
    return {
        "periodo": {
            "label": "Período del cierre",
            "ruta_orm": "cierre__periodo_clave",
            "tipo": "opcion",
            "categoria": "periodo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices_dinamicas": _opciones_periodos_cerrados,
        },
        "declarado_por": {
            "label": "Declarado por",
            "ruta_orm": "cierre__declarado_por_nombre",
            "tipo": "texto",
            "categoria": "periodo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "en_plazo": {
            "label": "Cierre declarado en plazo",
            "ruta_orm": "cierre__en_plazo",
            "tipo": "booleano",
            "categoria": "periodo",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
    }


def _clonar_campo(campo_vivo, ruta_orm, **cambios):
    """Copia la definición de un campo vivo cambiándole la ruta ORM.

    Así la gemela histórica hereda etiqueta, tipo, `choices`, si es sensible y
    demás sin repetirlo: lo único que cambia de verdad es de dónde sale el
    dato. Repetir las definiciones a mano garantizaría que un día divergieran.
    """
    campo = dict(campo_vivo)
    campo["ruta_orm"] = ruta_orm
    campo.pop("ruta_visual", None)
    campo.update(cambios)
    return campo


# Cada entrada es `clave_de_campo -> ruta_orm dentro de la fotografía`. La
# clave es la MISMA que usa la fuente viva a propósito: así un informe favorito
# guardado en tiempo real se puede ejecutar en un mes pasado sin traducir nada.
_RUTAS_HISTORICAS_CONTRATO = {
    "nombre_completo": "aspirante_nombre",
    "carne_identidad": "doc_identidad",
    "sexo": "sexo",
    "fecha_nacimiento": "fecha_nacimiento",
    "nivel_educ": "nivel_educ",
    "grado_cientifico": "grado_cientifico",
    "titulo_oro": "titulo_oro",
    "especialidad": "especialidad_nombre",
    "reg_militar": "reg_militar",
    "profesional": "profesional",
    "jubilado_recontratado": "jubilado_recontratado",
    "cargo": "ncargo_descripcion",
    "categoria_ocupacional": "cat_ocupacional",
    "departamento": "departamento_descripcion",
    "unidad_organizativa": "cierre__unidad_descripcion",
    "no_expediente": "no_expediente",
    "tipo_contrato": "tipo_descripcion",
    "fecha_alta": "fecha_alta",
    "fecha_alta_entidad": "fecha_alta_entidad",
    "motivo": "motivo_descripcion",
    "duracion": "duracion",
    "puesto_clave": "puesto_clave",
    "contrato_determinado": "requiere_motivo",
    "mision": "mision",
    "pais": "pais",
    "funcionario_res": "funcionario_res",
    "designado_res": "designado_res",
    "c_formal_res": "c_formal_res",
    "fecha_vence_lic": "fecha_vence_lic",
    "fecha_vence_recal": "fecha_vence_recal",
    "fecha_vence_seg": "fecha_vence_seg",
    "salario": "salario",
    "rol": "rol_tipo",
    "tridente": "tridente_tipo",
    "tipo_salario": "tipo_salario",
    "maestria": "maestria",
    "doctorado": "doctorado",
    "cnci": "cnci",
    "instructor": "instructor",
    # Vienen de la fila de cargo de la MISMA fotografía, no de la plantilla
    # viva: un cargo al que hoy le aprobaron plazas nuevas no debe cambiar el
    # informe de agosto.
    "nivel_preparacion": "cierre_cargo__nivel_preparacion_nombre",
    "funcionario": "cierre_cargo__funcionario",
    "designado": "cierre_cargo__designado",
    "cant_aprobada": "cierre_cargo__cant_aprobada",
    "cant_cubierta": "cierre_cargo__cant_cubierta",
    # Datos personales que no son historia: se leen del registro vivo, para que
    # corregir hoy un dato mal cargado arregle también los meses ya cerrados.
    "serie_ci": "aspirante_vivo__serie_ci",
    "raza": "aspirante_vivo__raza",
}

_RUTAS_HISTORICAS_CARGO = {
    "cargo": "ncargo_descripcion",
    "categoria_ocupacional": "cat_ocupacional",
    "rol": "rol_tipo",
    "nivel_preparacion": "nivel_preparacion_nombre",
    "departamento": "departamento_descripcion",
    "unidad_organizativa": "cierre__unidad_descripcion",
    "funcionario": "funcionario",
    "designado": "designado",
    "activo": "activo",
    "cant_aprobada": "cant_aprobada",
    "cant_cubierta": "cant_cubierta",
    "puesto_clave": "puesto_clave",
}


def _campos_historico(campos_vivos, rutas):
    """Construye el catálogo de una gemela clonando el de su fuente viva."""
    campos = _campos_comunes_del_cierre()
    for clave, ruta in rutas.items():
        campos[clave] = _clonar_campo(campos_vivos[clave], ruta)
    return campos


def _campos_historico_contrato():
    campos_vivos = _campos_calta()
    campos = _campos_historico(campos_vivos, _RUTAS_HISTORICAS_CONTRATO)

    # `grupo_escala` se filtra por número en la fuente viva (para poder ordenar
    # I < II < X); la fotografía solo congeló el nivel en romano, así que aquí
    # es texto. Es el mismo dato, con menos capacidades de orden.
    campos["grupo_escala"] = _clonar_campo(
        campos_vivos["grupo_escala"], "grupo_escala_nivel", tipo="texto")

    # Derivados: no tienen columna, los calcula el motor con una anotación a
    # partir de fechas que SÍ están congeladas.
    for clave in ("edad", "cumpleanos", "antiguedad"):
        campos[clave] = _clonar_campo(campos_vivos[clave], None)

    # Congelado pero renombrado: en el histórico se muestra el estado que tenía
    # la persona en ese cierre, no el de hoy.
    campos["estado_trabajador"] = {
        "label": "Estado del trabajador (en ese cierre)",
        "ruta_orm": "aspirante_estado",
        "tipo": "opcion",
        "categoria": "trabajador",
        "filtrable": True, "ordenable": True, "agrupable": True,
        "sensible": False,
        "choices": [("ASPIRANTE", "Aspirante"), ("ACTIVO", "Activo"), ("BAJA", "Baja")],
    }
    return campos


def _campos_historico_cargo():
    campos_vivos = _campos_cargoplantilla()
    campos = _campos_historico(campos_vivos, _RUTAS_HISTORICAS_CARGO)
    # Derivado: la fotografía congela aprobadas y cubiertas, y la resta la hace
    # el motor con una anotación, igual que en la fuente viva.
    campos["vacantes"] = _clonar_campo(campos_vivos["vacantes"], None)
    # Mismo caso que en el histórico de contratos: la fotografía congeló el
    # nivel en romano, no el número con el que la fuente viva ordena.
    campos["grupo_escala"] = _clonar_campo(
        campos_vivos["grupo_escala"], "grupo_escala_nivel", tipo="texto")
    return campos


REGISTRO_MODELOS = {
    "CAlta": {
        "app_label": "contratos",
        "label": "Contratos / Trabajadores Activos",
        "ruta_unidad_organizativa": "cargo__departamento__unidad_organizativa",
        # Los datos personales (nombre, edad, fecha de nacimiento...) se
        # llegan a través del FK 'aspirante'. Ver motor.py::_aplicar_anotaciones_necesarias.
        "ruta_aspirante": "aspirante",
        "campos": _campos_calta(),
        # Por qué campo se desglosa el resumen si el usuario no elige otro.
        "desglose_por_defecto": "categoria_ocupacional",
    },
    "CBaja": {
        "app_label": "contratos",
        "label": "Bajas",
        "ruta_unidad_organizativa": "cargo__departamento__unidad_organizativa",
        "ruta_aspirante": "aspirante",
        "campos": _campos_cbaja(),
        "desglose_por_defecto": "causa_baja",
    },
    "CargoPlantilla": {
        "app_label": "strorganizativa",
        "label": "Estructura y Plantilla Aprobada",
        "ruta_unidad_organizativa": "departamento__unidad_organizativa",
        "campos": _campos_cargoplantilla(),
        "desglose_por_defecto": "categoria_ocupacional",
    },
    "Aspirante": {
        "app_label": "bolsa",
        "label": "Aspirantes (Bolsa de Empleo)",
        # Decisión funcional: un aspirante no tiene Unidad Organizativa
        # asignada (solo la adquiere al ser contratado). Sin nada que
        # acotar, un Moderador ve la bolsa completa, igual que Admin/Observador.
        "ruta_unidad_organizativa": None,
        # Aspirante ES el dato personal (sin FK intermedio): ruta_aspirante
        # queda sin definir a propósito, así el prefijo de anotación es vacío.
        "campos": _campos_aspirante(),
        "desglose_por_defecto": "estado",
    },
    "TMovimiento": {
        "app_label": "contratos",
        "label": "Movimientos de Nómina",
        # Un movimiento puede afectar la unidad de origen o la de destino:
        # el Moderador lo ve si CUALQUIERA de las dos es suya (lista = OR,
        # ver motor.py::_aplicar_alcance_por_rol). Estas son las 2 FK reales
        # (unidad_anterior_fk/unidad_nueva_fk), no los campos de texto — que
        # siguen siendo lo único que se muestra en el informe.
        "ruta_unidad_organizativa": ["unidad_anterior_fk", "unidad_nueva_fk"],
        "ruta_aspirante": "aspirante",
        "campos": _campos_tmovimiento(),
        "desglose_por_defecto": "tipo_movimiento",
    },

}


# ---------------------------------------------------------------------------
# GEMELAS HISTÓRICAS
# ---------------------------------------------------------------------------
# NO son fuentes que el usuario elija: no aparecen en «¿Sobre qué desea
# informar?». Son el mismo informe de arriba, pero leído de la fotografía que
# el módulo de Cierres congela cada mes.
#
# El usuario elige su informe de siempre y, si quiere, un período cerrado en el
# selector de la parte superior. Cuando hay período, el motor cambia por debajo
# el modelo raíz por su gemela y usa este catálogo — que usa DELIBERADAMENTE
# las mismas claves de campo que la fuente viva, para que la configuración del
# usuario (y sus informes favoritos) valga igual en tiempo real que en un mes
# pasado.
#
# Solo existe gemela donde existe fotografía. Bajas, Aspirantes y Movimientos
# de Nómina no se congelan, así que en esas tres el selector de período se
# deshabilita en vez de prometer algo que no se puede cumplir.
FUENTES_HISTORICAS = {
    "CAlta": {
        "modelo_historico": "CierreContrato",
        "app_label": "cierres",
        "ruta_unidad_organizativa": "cierre__unidad",
        "campos": _campos_historico_contrato(),
    },
    "CargoPlantilla": {
        "modelo_historico": "CierreCargo",
        "app_label": "cierres",
        "ruta_unidad_organizativa": "cierre__unidad",
        "campos": _campos_historico_cargo(),
    },
}


def definicion_historica(modelo_raiz):
    """Gemela histórica de un modelo raíz, o None si no tiene fotografía."""
    return FUENTES_HISTORICAS.get(modelo_raiz)


def campos_sin_historico(modelo_raiz):
    """Campos del informe vivo que la fotografía no puede reproducir.

    La interfaz los deshabilita al elegir un período, para que el usuario sepa
    POR QUÉ no puede pedirlos en vez de recibir una columna vacía.
    """
    historica = FUENTES_HISTORICAS.get(modelo_raiz)
    if not historica:
        return set()
    vivos = set(REGISTRO_MODELOS[modelo_raiz]["campos"])
    return vivos - set(historica["campos"])


# ---------------------------------------------------------------------------
# INDICADORES DEL PANEL DE RESUMEN
# ---------------------------------------------------------------------------
# Tarjetas que aparecen SIEMPRE encima de la tabla de resultados, calculadas
# sobre el mismo conjunto de registros que se está listando (con sus filtros
# aplicados). Todas se resuelven en UNA sola consulta de agregación.
#
# Cada indicador declara:
#   tipo      -> 'conteo' (cuántos registros hay)
#                'conteo_si' (cuántos cumplen una condición)
#                'suma' / 'promedio' (sobre un campo numérico)
#   campo     -> clave del registro de campos de arriba (no una ruta ORM suelta,
#                así nunca se desincroniza)
#   formato   -> 'entero' (por defecto), 'moneda' o 'decimal'
#   color     -> nombre de color de la paleta, ver el CSS del módulo

INDICADORES_POR_MODELO = {
    "CAlta": [
        {
            "key": "total",
            "label": "Total de trabajadores",
            "tipo": "conteo",
            "icono": "bi-people-fill",
            "color": "indigo",
        },
        {
            "key": "mujeres",
            "label": "Mujeres",
            "tipo": "conteo_si",
            "campo": "sexo",
            "valor": "F",
            "con_porcentaje": True,
            "icono": "bi-gender-female",
            "color": "violeta",
        },
        {
            "key": "edad_promedio",
            "label": "Edad promedio",
            "tipo": "promedio",
            "campo": "edad",
            "formato": "decimal",
            "sufijo": " años",
            "icono": "bi-hourglass-split",
            "color": "esmeralda",
        },
        {
            "key": "salario_total",
            "label": "Salario total",
            "tipo": "suma",
            "campo": "salario",
            "formato": "moneda",
            "icono": "bi-cash-stack",
            "color": "naranja",
        },
        {
            "key": "salario_promedio",
            "label": "Salario promedio",
            "tipo": "promedio",
            "campo": "salario",
            "formato": "moneda",
            "icono": "bi-graph-up-arrow",
            "color": "azul",
        },
        {
            "key": "puestos_clave",
            "label": "En puestos clave",
            "tipo": "conteo_si",
            "campo": "puesto_clave",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-star-fill",
            "color": "naranja",
        },
        {
            "key": "en_mision",
            "label": "En misión internacional",
            "tipo": "conteo_si",
            "campo": "mision",
            "valor": True,
            "icono": "bi-airplane-fill",
            "color": "azul",
        },
        {
            "key": "antiguedad_promedio",
            "label": "Antigüedad promedio",
            "tipo": "promedio",
            "campo": "antiguedad",
            "formato": "decimal",
            "sufijo": " años",
            "icono": "bi-award-fill",
            "color": "violeta",
        },
        {
            "key": "cuadros",
            "label": "Cuadros",
            "tipo": "conteo_si",
            "campo": "categoria_ocupacional",
            # Directivos y Ejecutivos son dos códigos distintos y una sola idea.
            "valor": ["CDI", "CEJ"],
            "con_porcentaje": True,
            "icono": "bi-person-badge-fill",
            "color": "indigo",
        },
        {
            "key": "mujeres_puestos_clave",
            "label": "Mujeres en puestos clave",
            "tipo": "conteo_si",
            "condiciones": [
                {"campo": "sexo", "valor": "F"},
                {"campo": "puesto_clave", "valor": True},
            ],
            "icono": "bi-star-half",
            "color": "violeta",
        },
        {
            "key": "con_grado_cientifico",
            "label": "Con grado científico",
            "tipo": "conteo_si",
            "campo": "grado_cientifico",
            "valor": ["MC", "DC"],
            "con_porcentaje": True,
            "icono": "bi-mortarboard-fill",
            "color": "esmeralda",
        },
        {
            "key": "nivel_superior",
            "label": "De nivel superior",
            "tipo": "conteo_si",
            "campo": "nivel_educ",
            "valor": "NS",
            "con_porcentaje": True,
            "icono": "bi-book-fill",
            "color": "azul",
        },
        {
            "key": "titulo_oro",
            "label": "Título de Oro",
            "tipo": "conteo_si",
            "campo": "titulo_oro",
            "valor": True,
            "icono": "bi-trophy-fill",
            "color": "naranja",
        },
        {
            "key": "profesionales",
            "label": "Profesionales",
            "tipo": "conteo_si",
            "campo": "profesional",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-briefcase-fill",
            "color": "indigo",
        },
        {
            "key": "jubilados_recontratados",
            "label": "Jubilados recontratados",
            "tipo": "conteo_si",
            "campo": "jubilado_recontratado",
            "valor": True,
            "icono": "bi-person-heart",
            "color": "esmeralda",
        },
        {
            "key": "determinados",
            "label": "Contratos determinados",
            "tipo": "conteo_si",
            "campo": "contrato_determinado",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-hourglass-split",
            "color": "naranja",
        },
    ],
    "CBaja": [
        {
            "key": "total",
            "label": "Total de bajas",
            "tipo": "conteo",
            "icono": "bi-person-dash-fill",
            "color": "naranja",
        },
        {
            "key": "mujeres",
            "label": "Mujeres",
            "tipo": "conteo_si",
            "campo": "sexo",
            "valor": "F",
            "con_porcentaje": True,
            "icono": "bi-gender-female",
            "color": "violeta",
        },
        {
            "key": "edad_promedio",
            "label": "Edad promedio",
            "tipo": "promedio",
            "campo": "edad",
            "formato": "decimal",
            "sufijo": " años",
            "icono": "bi-hourglass-split",
            "color": "esmeralda",
        },
    ],
    "CargoPlantilla": [
        {
            "key": "total",
            "label": "Total de cargos",
            "tipo": "conteo",
            "icono": "bi-briefcase-fill",
            "color": "indigo",
        },
        {
            "key": "plazas_aprobadas",
            "label": "Plazas aprobadas",
            "tipo": "suma",
            "campo": "cant_aprobada",
            "icono": "bi-people-fill",
            "color": "esmeralda",
        },
        {
            "key": "plazas_cubiertas",
            "label": "Plazas cubiertas",
            "tipo": "suma",
            "campo": "cant_cubierta",
            "icono": "bi-person-check-fill",
            "color": "azul",
        },
        {
            "key": "plazas_vacantes",
            "label": "Plazas vacantes",
            "tipo": "suma",
            "campo": "vacantes",
            "icono": "bi-person-dash",
            "color": "naranja",
        },
        {
            "key": "cobertura",
            "label": "Cobertura de la plantilla",
            "tipo": "razon",
            "campo": "cant_cubierta",
            "campo_divisor": "cant_aprobada",
            "formato": "porcentaje",
            "sufijo": " %",
            "icono": "bi-pie-chart-fill",
            "color": "violeta",
        },
        {
            "key": "cargos_sin_cubrir",
            "label": "Cargos sin cubrir",
            "tipo": "conteo_si",
            "campo": "cant_cubierta",
            "valor": 0,
            "con_porcentaje": True,
            "icono": "bi-slash-circle",
            "color": "naranja",
        },
        {
            "key": "cargos_puesto_clave",
            "label": "Cargos de puesto clave",
            "tipo": "conteo_si",
            "campo": "puesto_clave",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-star-fill",
            "color": "azul",
        },
        {
            "key": "cargos_inactivos",
            "label": "Cargos inactivos",
            "tipo": "conteo_si",
            "campo": "activo",
            "valor": False,
            "icono": "bi-dash-circle",
            "color": "esmeralda",
        },
    ],
    "Aspirante": [
        {
            "key": "total",
            "label": "Total de aspirantes",
            "tipo": "conteo",
            "icono": "bi-person-lines-fill",
            "color": "indigo",
        },
        {
            "key": "mujeres",
            "label": "Mujeres",
            "tipo": "conteo_si",
            "campo": "sexo",
            "valor": "F",
            "con_porcentaje": True,
            "icono": "bi-gender-female",
            "color": "violeta",
        },
        {
            "key": "edad_promedio",
            "label": "Edad promedio",
            "tipo": "promedio",
            "campo": "edad",
            "formato": "decimal",
            "sufijo": " años",
            "icono": "bi-hourglass-split",
            "color": "esmeralda",
        },
    ],
    "TMovimiento": [
        {
            "key": "total",
            "label": "Total de movimientos",
            "tipo": "conteo",
            "icono": "bi-arrow-left-right",
            "color": "azul",
        },
    ],
    "CierreContrato": [
        {
            # Cuidado al leerlo: si el informe abarca varios períodos, cada
            # trabajador cuenta una vez POR MES cerrado. Por eso la fuente
            # desglosa por período de entrada.
            "key": "total",
            "label": "Filas del histórico",
            "tipo": "conteo",
            "icono": "bi-calendar-check-fill",
            "color": "azul",
        },
        {
            "key": "mujeres",
            "label": "Mujeres",
            "tipo": "conteo_si",
            "campo": "sexo",
            "valor": "F",
            "con_porcentaje": True,
            "icono": "bi-gender-female",
            "color": "violeta",
        },
        {
            "key": "salario_total",
            "label": "Salario total",
            "tipo": "suma",
            "campo": "salario",
            "formato": "moneda",
            "icono": "bi-cash-stack",
            "color": "naranja",
        },
        # Las mismas medidas que la fuente viva: mirar un mes cerrado no tiene
        # por qué ofrecer menos tarjetas que mirar hoy. Todos estos datos los
        # congela `CierreContrato`.
        {
            "key": "edad_promedio",
            "label": "Edad promedio",
            "tipo": "promedio",
            "campo": "edad",
            "formato": "decimal",
            "sufijo": " años",
            "icono": "bi-hourglass-split",
            "color": "esmeralda",
        },
        {
            "key": "puestos_clave",
            "label": "En puestos clave",
            "tipo": "conteo_si",
            "campo": "puesto_clave",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-star-fill",
            "color": "naranja",
        },
        {
            "key": "en_mision",
            "label": "En misión internacional",
            "tipo": "conteo_si",
            "campo": "mision",
            "valor": True,
            "icono": "bi-airplane-fill",
            "color": "azul",
        },
        {
            "key": "antiguedad_promedio",
            "label": "Antigüedad promedio",
            "tipo": "promedio",
            "campo": "antiguedad",
            "formato": "decimal",
            "sufijo": " años",
            "icono": "bi-award-fill",
            "color": "violeta",
        },
        {
            "key": "cuadros",
            "label": "Cuadros",
            "tipo": "conteo_si",
            "campo": "categoria_ocupacional",
            # Directivos y Ejecutivos son dos códigos distintos y una sola idea.
            "valor": ["CDI", "CEJ"],
            "con_porcentaje": True,
            "icono": "bi-person-badge-fill",
            "color": "indigo",
        },
        {
            "key": "mujeres_puestos_clave",
            "label": "Mujeres en puestos clave",
            "tipo": "conteo_si",
            "condiciones": [
                {"campo": "sexo", "valor": "F"},
                {"campo": "puesto_clave", "valor": True},
            ],
            "icono": "bi-star-half",
            "color": "violeta",
        },
        {
            "key": "con_grado_cientifico",
            "label": "Con grado científico",
            "tipo": "conteo_si",
            "campo": "grado_cientifico",
            "valor": ["MC", "DC"],
            "con_porcentaje": True,
            "icono": "bi-mortarboard-fill",
            "color": "esmeralda",
        },
        {
            "key": "nivel_superior",
            "label": "De nivel superior",
            "tipo": "conteo_si",
            "campo": "nivel_educ",
            "valor": "NS",
            "con_porcentaje": True,
            "icono": "bi-book-fill",
            "color": "azul",
        },
        {
            "key": "titulo_oro",
            "label": "Título de Oro",
            "tipo": "conteo_si",
            "campo": "titulo_oro",
            "valor": True,
            "icono": "bi-trophy-fill",
            "color": "naranja",
        },
        {
            "key": "profesionales",
            "label": "Profesionales",
            "tipo": "conteo_si",
            "campo": "profesional",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-briefcase-fill",
            "color": "indigo",
        },
        {
            "key": "jubilados_recontratados",
            "label": "Jubilados recontratados",
            "tipo": "conteo_si",
            "campo": "jubilado_recontratado",
            "valor": True,
            "icono": "bi-person-heart",
            "color": "esmeralda",
        },
        {
            "key": "determinados",
            "label": "Contratos determinados",
            "tipo": "conteo_si",
            "campo": "contrato_determinado",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-hourglass-split",
            "color": "naranja",
        },
    ],
    "CierreCargo": [
        {
            "key": "total",
            "label": "Filas del histórico",
            "tipo": "conteo",
            "icono": "bi-calendar-check-fill",
            "color": "azul",
        },
        {
            "key": "plazas_aprobadas",
            "label": "Plazas aprobadas",
            "tipo": "suma",
            "campo": "cant_aprobada",
            "icono": "bi-people-fill",
            "color": "esmeralda",
        },
        {
            "key": "plazas_cubiertas",
            "label": "Plazas cubiertas",
            "tipo": "suma",
            "campo": "cant_cubierta",
            "icono": "bi-person-check-fill",
            "color": "indigo",
        },
        {
            "key": "plazas_vacantes",
            "label": "Plazas vacantes",
            "tipo": "suma",
            "campo": "vacantes",
            "icono": "bi-person-dash",
            "color": "naranja",
        },
        {
            "key": "cobertura",
            "label": "Cobertura de la plantilla",
            "tipo": "razon",
            "campo": "cant_cubierta",
            "campo_divisor": "cant_aprobada",
            "formato": "porcentaje",
            "sufijo": " %",
            "icono": "bi-pie-chart-fill",
            "color": "violeta",
        },
        {
            "key": "cargos_sin_cubrir",
            "label": "Cargos sin cubrir",
            "tipo": "conteo_si",
            "campo": "cant_cubierta",
            "valor": 0,
            "con_porcentaje": True,
            "icono": "bi-slash-circle",
            "color": "naranja",
        },
        {
            "key": "cargos_puesto_clave",
            "label": "Cargos de puesto clave",
            "tipo": "conteo_si",
            "campo": "puesto_clave",
            "valor": True,
            "con_porcentaje": True,
            "icono": "bi-star-fill",
            "color": "azul",
        },
        {
            "key": "cargos_inactivos",
            "label": "Cargos inactivos",
            "tipo": "conteo_si",
            "campo": "activo",
            "valor": False,
            "icono": "bi-dash-circle",
            "color": "esmeralda",
        },
    ],
}


# ---------------------------------------------------------------------------
# AYUDAS PARA TRABAJAR CON VALORES DE OPCIÓN
# ---------------------------------------------------------------------------
# Un campo de opción puede presentar sus valores de dos formas:
#   - 'choices': cada valor de la base de datos tiene su propia etiqueta.
#   - 'grupos_valores': varios valores de la base de datos comparten etiqueta
#     (caso de Categoría Ocupacional, donde CDI y CEJ son ambos "Cuadro").
# Estas tres funciones evitan que el resto del código tenga que saber cuál de
# las dos usa cada campo.

def opciones_visibles(campo):
    """
    Opciones que se ofrecen al usuario en los filtros, como lista de
    pares (valor_a_guardar, etiqueta_a_mostrar).

    Con 'grupos_valores' el valor guardado es la propia etiqueta ("Cuadro"),
    porque los códigos internos (CDI, CEJ) no deben salir a la interfaz.
    """
    if campo.get("grupos_valores"):
        return [(etiqueta, etiqueta) for etiqueta, _ in campo["grupos_valores"]]
    if campo.get("choices_dinamicas"):
        return list(campo["choices_dinamicas"]())
    return list(campo.get("choices") or [])


def mapa_valor_a_etiqueta(campo):
    """Traduce el valor guardado en la base de datos a lo que ve el usuario."""
    if campo.get("grupos_valores"):
        mapa = {}
        for etiqueta, valores_db in campo["grupos_valores"]:
            for valor in valores_db:
                mapa[valor] = etiqueta
        return mapa
    if campo.get("choices_dinamicas"):
        # Hasta ahora esta rama no existía y los campos dinámicos salían con su
        # valor crudo en la tabla. No se notaba porque todos los que había
        # (cargos, departamentos, provincias...) usan el nombre como valor Y
        # como etiqueta, así que la traducción era la identidad. Deja de serlo
        # en cuanto un campo dinámico guarda un código distinto de lo que se
        # muestra — el caso del Período de los cierres, que guarda '2026-09' y
        # debe leerse 'Septiembre 2026'.
        #
        # El coste es una consulta por campo y por informe: quien llama
        # (`views._construir_filas`, `motor._calcular_desglose`) construye este
        # mapa una sola vez, no por fila.
        return dict(campo["choices_dinamicas"]())
    return dict(campo.get("choices") or [])


def valores_db_de_etiqueta(campo, etiqueta):
    """
    Camino inverso: dada una etiqueta elegida en un filtro, devuelve los
    valores reales de la base de datos que representa. Devuelve None si el
    campo no agrupa valores (entonces la etiqueta ya es el valor).
    """
    if not campo.get("grupos_valores"):
        return None
    for etiqueta_grupo, valores_db in campo["grupos_valores"]:
        if etiqueta_grupo == etiqueta:
            return list(valores_db)
    return []


# ---------------------------------------------------------------------------
# PLANTILLAS RÁPIDAS
# ---------------------------------------------------------------------------
# Configuraciones predefinidas que el usuario aplica con un clic. Viven aquí,
# junto al registro de campos, para que sea imposible que una plantilla acabe
# apuntando a un campo que ya no existe: si se elimina o renombra un campo
# arriba, se ve de inmediato qué plantillas hay que ajustar.
#
# No confundir con los informes favoritos: esos sí son datos del usuario y se
# guardan en la base de datos (modelo InformePersonalizado).

PLANTILLAS_RAPIDAS = {
    "CAlta": [
        {
            "key": "listado_general",
            "nombre": "Listado General",
            "descripcion": "Datos básicos de toda la plantilla, ordenados por departamento.",
            "icono": "bi-people-fill",
            "color": "indigo",
            "configuracion": {
                "campos": [
                    "nombre_completo", "carne_identidad", "sexo", "edad",
                    "cargo", "departamento", "tipo_contrato", "fecha_alta",
                ],
                "filtros": [],
                "desglosar_por": "departamento",
                "ordenar_por": "departamento",
                "orden_direccion": "asc",
            },
        },
        {
            "key": "cuadros",
            "nombre": "Cuadros",
            "descripcion": "Personal que ocupa cargos de cuadro, con su desglose por sexo.",
            "icono": "bi-briefcase-fill",
            "color": "azul",
            "configuracion": {
                "campos": [
                    "nombre_completo", "sexo", "edad", "cargo",
                    "departamento", "unidad_organizativa",
                ],
                "filtros": [
                    {"campo": "categoria_ocupacional", "operador": "igual", "valor": "Cuadro"},
                ],
                "desglosar_por": "sexo",
                "ordenar_por": "departamento",
                "orden_direccion": "asc",
            },
        },
        {
            "key": "personal_mayor_60",
            "nombre": "Personal de 60 años o más",
            "descripcion": "Útil para prever jubilaciones y relevo de cargos.",
            "icono": "bi-person-dash-fill",
            "color": "naranja",
            "configuracion": {
                "campos": [
                    "nombre_completo", "carne_identidad", "sexo", "edad",
                    "cargo", "departamento", "fecha_alta",
                ],
                "filtros": [
                    {"campo": "edad", "operador": "mayor", "valor": 59},
                ],
                "desglosar_por": "departamento",
                "ordenar_por": "edad",
                "orden_direccion": "desc",
            },
        },
        {
            "key": "altas_recientes",
            "nombre": "Últimas Altas",
            "descripcion": "Incorporaciones más recientes primero.",
            "icono": "bi-person-plus-fill",
            "color": "esmeralda",
            "configuracion": {
                "campos": [
                    "nombre_completo", "carne_identidad", "cargo",
                    "departamento", "tipo_contrato", "fecha_alta",
                ],
                "filtros": [],
                "desglosar_por": "tipo_contrato",
                "ordenar_por": "fecha_alta",
                "orden_direccion": "desc",
            },
        },
        {
            "key": "escala_salarial",
            "nombre": "Escala Salarial",
            "descripcion": "Salario y grupo escala por cargo, de mayor a menor.",
            "icono": "bi-cash-stack",
            "color": "violeta",
            "configuracion": {
                "campos": [
                    "nombre_completo", "cargo", "categoria_ocupacional",
                    "grupo_escala", "departamento", "salario",
                ],
                "filtros": [],
                "desglosar_por": "grupo_escala",
                "ordenar_por": "salario",
                "orden_direccion": "desc",
            },
        },
        {
            "key": "composicion_plantilla",
            "nombre": "Composición de la Plantilla",
            "descripcion": "Quién compone la plantilla por categoría ocupacional.",
            "icono": "bi-pie-chart-fill",
            "color": "rosa",
            "configuracion": {
                "campos": [
                    "nombre_completo", "sexo", "categoria_ocupacional",
                    "cargo", "departamento", "unidad_organizativa",
                ],
                "filtros": [],
                "desglosar_por": "categoria_ocupacional",
                "ordenar_por": "departamento",
                "orden_direccion": "asc",
            },
        },
    ],
}


def agrupar_campos_por_categoria(definicion_modelo):
    """
    Reorganiza los campos de un modelo en la estructura que espera la
    plantilla de checkboxes: una lista de categorías, cada una con sus campos.
    Respeta el orden de CATEGORIAS_CAMPOS y omite las categorías vacías.

    A cada campo se le adjuntan ya resueltas sus 'opciones' visibles, para que
    la plantilla no tenga que saber si usa choices o grupos_valores.
    """
    agrupados = []
    for key_categoria, meta_categoria in CATEGORIAS_CAMPOS.items():
        campos = [
            {"key": key, "campo": campo, "opciones": opciones_visibles(campo)}
            for key, campo in definicion_modelo["campos"].items()
            if campo.get("categoria") == key_categoria
        ]
        if campos:
            agrupados.append({
                "key": key_categoria,
                "label": meta_categoria["label"],
                "icono": meta_categoria["icono"],
                "color": meta_categoria["color"],
                "campos": campos,
            })
    return agrupados