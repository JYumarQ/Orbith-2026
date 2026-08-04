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
# CATEGORÍAS PARA AGRUPAR LOS CAMPOS EN LA INTERFAZ
# ---------------------------------------------------------------------------
# Solo afectan a cómo se presentan los checkboxes al usuario, no a la consulta.
# El orden de este diccionario es el orden en que aparecen las columnas.

CATEGORIAS_CAMPOS = {
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
        "estado": {
            "label": "Estado del Aspirante",
            "ruta_orm": "aspirante__estado",
            "tipo": "opcion",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("ASPIRANTE", "Aspirante"), ("ACTIVO", "Activo"), ("BAJA", "Baja")],
        },
        "fecha_nacimiento": {
            "label": "Fecha de Nacimiento",
            "ruta_orm": "aspirante__fecha_nacimiento",
            "tipo": "fecha",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
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
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
            "label": "Profesional",
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
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "unidad_organizativa": {
            "label": "Unidad Organizativa",
            "ruta_orm": "cargo__departamento__unidad_organizativa__descripcion",
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "nivel_preparacion": {
            "label": "Nivel de Preparación",
            "ruta_orm": "cargo__nivel_preparacion__nombre",
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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

        # ---------------- DATOS DEL CONTRATO ----------------
        "tipo_contrato": {
            "label": "Tipo de Contrato",
            "ruta_orm": "tipo__descripcion",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "fecha_alta": {
            "label": "Fecha de Alta",
            "ruta_orm": "fecha_alta",
            "tipo": "fecha",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "no_expediente": {
            "label": "No. Expediente",
            "ruta_orm": "no_expediente",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "motivo": {
            "label": "Motivo de Contrato",
            "ruta_orm": "motivo__descripcion",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "duracion": {
            "label": "Duración",
            "ruta_orm": "duracion",
            "tipo": "numero",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },
        "jornada": {
            "label": "Jornada",
            "ruta_orm": "jornada__descripcion",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
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
            "label": "País",
            "ruta_orm": "pais",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "en_proceso_movimiento": {
            "label": "En Proceso de Movimiento",
            "ruta_orm": "en_proceso_movimiento",
            "tipo": "booleano",
            "categoria": "contrato",
            "filtrable": True, "ordenable": False, "agrupable": True,
            "sensible": False,
        },
        "cla": {
            "label": "Condición Laboral Anormal (CLA)",
            "ruta_orm": "cla__nombre",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "nocturnidad_1": {
            "label": "Nocturnidad 1",
            "ruta_orm": "nocturnidad_1__nombre",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "nocturnidad_2": {
            "label": "Nocturnidad 2",
            "ruta_orm": "nocturnidad_2__nombre",
            "tipo": "texto",
            "categoria": "contrato",
            "filtrable": True, "ordenable": True, "agrupable": True,
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
            "tipo": "texto",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "tridente": {
            "label": "Tridente",
            "ruta_orm": "tridente__tipo",
            "tipo": "texto",
            "categoria": "salariales",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
    jornada, nocturnidad, salario, vencimientos, maestrías...) y se agregan
    los propios del proceso de baja.
    """
    base = _campos_calta()
    solo_calta = {
        "duracion", "tipo_salario", "rol", "tridente", "maestria", "doctorado",
        "cnci", "instructor", "jornada", "cla", "nocturnidad_1", "nocturnidad_2",
        "fecha_vence_lic", "fecha_vence_recal", "fecha_vence_seg",
        "jubilado_recontratado", "en_proceso_movimiento", "salario",
    }
    campos = {key: valor for key, valor in base.items() if key not in solo_calta}

    campos.update({
        "causa_baja": {
            "label": "Causa de Baja",
            "ruta_orm": "causa_baja__descripcion",
            "tipo": "texto",
            "categoria": "baja",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "nivel_preparacion": {
            "label": "Nivel de Preparación",
            "ruta_orm": "nivel_preparacion__nombre",
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "departamento": {
            "label": "Departamento",
            "ruta_orm": "departamento__descripcion",
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "unidad_organizativa": {
            "label": "Unidad Organizativa",
            "ruta_orm": "departamento__unidad_organizativa__descripcion",
            "tipo": "texto",
            "categoria": "cargo",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "provincia": {
            "label": "Provincia",
            "ruta_orm": "provincia__nombre",
            "tipo": "texto",
            "categoria": "trabajador",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
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
    return list(campo.get("choices") or [])


def mapa_valor_a_etiqueta(campo):
    """Traduce el valor guardado en la base de datos a lo que ve el usuario."""
    if campo.get("grupos_valores"):
        mapa = {}
        for etiqueta, valores_db in campo["grupos_valores"]:
            for valor in valores_db:
                mapa[valor] = etiqueta
        return mapa
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