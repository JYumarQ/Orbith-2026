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
    "fecha":   ["entre_fechas", "mayor", "menor", "es_nulo", "no_es_nulo"],
    "opcion":  ["igual", "diferente", "es_nulo", "no_es_nulo"],
    "booleano": ["igual"],
}

# Traducción de cada operador a su lookup real de Django ORM.
# '{campo}' se sustituye por la ruta ORM del campo en tiempo de ejecución.
LOOKUP_POR_OPERADOR = {
    "igual":        "exact",
    "diferente":    "exact",       # se niega con .exclude() en vez de .filter()
    "mayor":        "gt",
    "menor":        "lt",
    "contiene":     "icontains",
    "entre_fechas": "range",
    "es_nulo":      "isnull",
    "no_es_nulo":   "isnull",      # se usa con valor=False
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
            "filtrable": True, "ordenable": False, "agrupable": False,
            "sensible": False,
        },
        "carne_identidad": {
            "label": "Carné de Identidad",
            "ruta_orm": "aspirante__doc_identidad",
            "tipo": "texto",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
        "sexo": {
            "label": "Sexo",
            "ruta_orm": "aspirante__sexo",
            "tipo": "opcion",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [("M", "Masculino"), ("F", "Femenino")],
        },
        "edad": {
            "label": "Edad",
            "ruta_orm": None,  # se resuelve por anotación sobre fecha_nacimiento
            "tipo": "numero",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },

        # ---------------- DATOS DEL CARGO ----------------
        "cargo": {
            "label": "Cargo",
            "ruta_orm": "cargo__ncargo__descripcion",
            "tipo": "texto",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "categoria_ocupacional": {
            "label": "Categoría Ocupacional",
            "ruta_orm": "cargo__ncargo__cat_ocupacional",
            "tipo": "opcion",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
            "choices": [
                ("TEC", "Técnico"), ("ADM", "Administrativo"), ("SER", "Servicio"),
                ("OPE", "Obrero"), ("CDI", "Cuadro Directivo"), ("CEJ", "Cuadro Ejecutivo"),
            ],
        },
        "grupo_escala": {
            "label": "Grupo Escala",
            "ruta_orm": "cargo__ncargo__grupo_escala__valor_numerico_db",
            "ruta_visual": "cargo__ncargo__grupo_escala__nivel",  # lo que se MUESTRA
            "tipo": "numero",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "departamento": {
            "label": "Departamento",
            "ruta_orm": "cargo__departamento__descripcion",
            "tipo": "texto",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "unidad_organizativa": {
            "label": "Unidad Organizativa",
            "ruta_orm": "cargo__departamento__unidad_organizativa__descripcion",
            "tipo": "texto",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },

        # ---------------- DATOS DEL CONTRATO ----------------
        "tipo_contrato": {
            "label": "Tipo de Contrato",
            "ruta_orm": "tipo__descripcion",
            "tipo": "texto",
            "filtrable": True, "ordenable": True, "agrupable": True,
            "sensible": False,
        },
        "fecha_alta": {
            "label": "Fecha de Alta",
            "ruta_orm": "fecha_alta",
            "tipo": "fecha",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": False,
        },

        # ---------------- DATOS SALARIALES ----------------
        "salario": {
            "label": "Salario",
            "ruta_orm": "salario_actual",
            "tipo": "numero",
            "filtrable": True, "ordenable": True, "agrupable": False,
            "sensible": True,
        },
    }


REGISTRO_MODELOS = {
    "CAlta": {
        "app_label": "contratos",
        "label": "Contratos / Trabajadores Activos",
        "ruta_unidad_organizativa": "cargo__departamento__unidad_organizativa",
        "campos": _campos_calta(),
    },
    # Aquí se añadirán 'CBaja', 'Aspirante', 'CargoPlantilla', 'TMovimiento'
    # en fases posteriores, cada uno como su propia entrada.
}