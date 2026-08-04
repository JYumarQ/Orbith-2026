"""Cálculos que necesitan las reglas, resueltos sin consultar la base por cada fila.

Aquí NO se duplica ninguna regla de negocio. El árbol de decisión del salario vive en
`contratos/salarios.py` y es el mismo que usa `CAlta.calcular_salario_escala()`; lo que
aporta este módulo es la forma de alimentarlo con datos precargados, para poder revisar
miles de contratos con una sola consulta en lugar de una por contrato.
"""

from django.apps import apps

from contratos.salarios import calcular_salario, clave_salario


# ---------------------------------------------------------------------------
# Índice de salarios
# ---------------------------------------------------------------------------

def construir_indice_salarios():
    """Toda la tabla `NSalario` en un diccionario `{(grupo, rol, tridente): monto}`.

    `NSalario` es diminuta: su `unique_together ('grupo_escala', 'rol', 'tridente')`
    limita el número de filas al de combinaciones válidas de la escala salarial (unos
    cientos como mucho). Cargarla entera cuesta UNA consulta y sustituye a una o dos
    consultas por cada contrato revisado.

    Las claves con `None` son entradas legítimas del propio diccionario: un cuadro se
    guarda con `tridente` nulo, y la escala de respaldo con `rol` y `tridente` nulos.
    Por eso el mismo diccionario cubre los tres caminos del cálculo.
    """
    NSalario = apps.get_model('nomencladores', 'NSalario')
    return {
        clave_salario(fila['grupo_escala_id'], fila['rol_id'], fila['tridente_id']):
            fila['monto']
        for fila in NSalario.objects.values(
            'grupo_escala_id', 'rol_id', 'tridente_id', 'monto')
    }


# Columnas mínimas para calcular el salario esperado de un contrato. Se piden con
# `.values()` y no como instancias: una fila es un diccionario de nueve claves, en vez
# de un objeto CAlta con CargoPlantilla y NCargo hidratados detrás.
COLUMNAS_SALARIO = (
    'id',
    'no_expediente',
    'salario_actual',
    'tipo_salario',
    'rol_id',
    'tridente_id',
    'cargo_id',
    'cargo__rol_id',
    'cargo__ncargo__grupo_escala_id',
    'cargo__ncargo__cat_ocupacional',
    'cargo__ncargo__salario_basico',
    'cargo__ncargo__descripcion',
    'cargo__departamento__unidad_organizativa_id',
    'aspirante__nombre',
    'aspirante__papellido',
    'aspirante__sapellido',
    'aspirante__doc_identidad',
)


def salario_esperado(fila, indice_salarios):
    """Salario que le correspondería a un contrato, sin tocar la base de datos.

    `fila` es un diccionario obtenido con `.values(*COLUMNAS_SALARIO)`.

    Usa EXACTAMENTE el mismo árbol de decisión que `CAlta.calcular_salario_escala()`,
    porque ambos llaman a `contratos.salarios.calcular_salario()`. Lo único que cambia
    es de dónde sale el monto: aquí de un diccionario en memoria, allí de una consulta.
    """
    NCargo = apps.get_model('nomencladores', 'NCargo')
    categoria = fila.get('cargo__ncargo__cat_ocupacional')

    return calcular_salario(
        tipo_salario=fila.get('tipo_salario'),
        tiene_cargo=fila.get('cargo_id') is not None,
        # `es_cuadro` es una property del modelo y no se puede llamar sobre un
        # diccionario, así que se evalúa con la constante que la property usa. De ese
        # modo el criterio sigue viviendo en un solo sitio.
        es_cuadro=categoria in NCargo.CATEGORIAS_CUADRO,
        grupo_escala_id=fila.get('cargo__ncargo__grupo_escala_id'),
        rol_id_contrato=fila.get('rol_id'),
        rol_id_cargo=fila.get('cargo__rol_id'),
        tridente_id=fila.get('tridente_id'),
        salario_basico=fila.get('cargo__ncargo__salario_basico'),
        buscar_monto=lambda grupo, rol, tridente: indice_salarios.get(
            clave_salario(grupo, rol, tridente)),
    )
