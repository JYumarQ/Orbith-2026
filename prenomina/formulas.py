"""Evaluador seguro de las fórmulas de los pagos por importe.

Módulo **puro**: no importa Django ni toca la base de datos, así que se prueba
entero con `SimpleTestCase` y corre en milisegundos.

Por qué no `eval()`
-------------------
`eval('().__class__.__bases__[0].__subclasses__()')` da acceso a todo el
intérprete. La defensa no es filtrar cadenas peligrosas —siempre falta una— sino
**parsear a AST y aceptar solo una lista blanca de nodos**. Lo que no está en la
lista se rechaza, aunque parezca inofensivo.

Por qué implementación propia y no `simpleeval`
-----------------------------------------------
1. `simpleeval` no está instalado y el proyecto declara explícitamente que no
   añade dependencias nuevas (ver `subsanacion/exportar.py`).
2. Sus valores por defecto son permisivos: admite `**`, comparaciones, `if/else`
   y un diccionario de funciones precargado. Asegurarlo obliga a escribir la
   misma lista blanca a través de su API.
3. Nuestra gramática son 6 tipos de nodo y 4 operadores. Esto son ~200 líneas
   con mensajes en español; `simpleeval` son ~600 que habría que auditar.
4. Necesitamos `Decimal` de punta a punta; `simpleeval` trabaja con `int`/`float`.

Si algún día el requisito pide `min()`, `max()` o condicionales, este módulo hay
que ampliarlo a mano y es el momento de reconsiderar una biblioteca.

Gramática admitida
------------------
Números enteros y decimales, `+`, `-`, `*`, `/`, paréntesis, y las variables de
`VARIABLES` escritas como `{{nombre}}`. Nada más.
"""

import ast
from decimal import (Decimal, DivisionByZero, InvalidOperation, Overflow,
                     localcontext)

# Variables que una fórmula puede referenciar. Todas están congeladas en la fila
# del trabajador del reporte (`ReporteTrabajador`), así que evaluar una fórmula
# nunca consulta datos vivos: un reporte cerrado se recalcula igual dentro de
# cinco años.
VARIABLES = (
    'horas',           # horas del concepto por horas relacionado
    'salario_escala',  # salario de escala congelado
    'tarifa_horaria',  # salario_escala / fondo de tarifa, congelada
    'cnci',
    'maestria',
    'instructor',
    'anos_servicio',
)

LONGITUD_MAXIMA = 200
NODOS_MAXIMOS = 100
PROFUNDIDAD_MAXIMA = 20

#: Valores con los que `validar()` hace el ensayo en seco. El 0 es el que
#: importa: atrapa las fórmulas que dividen entre una variable.
VALORES_DE_ENSAYO = (Decimal('0'), Decimal('1'), Decimal('1000'))


class ErrorDeFormula(ValueError):
    """Fórmula inválida. El mensaje va directo al usuario, en español."""


def _lista_de_variables():
    return ', '.join('{{' + nombre + '}}' for nombre in VARIABLES)


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #

def normalizar(expresion):
    """Convierte «{{horas}} * 2» en «horas * 2».

    Se acepta también la variable escrita sin llaves, porque es lo que teclea
    quien ya conoce la sintaxis; las llaves son la forma canónica que muestra la
    interfaz.
    """
    if expresion is None:
        raise ErrorDeFormula('Escriba una fórmula.')

    texto = str(expresion).strip()
    if not texto:
        raise ErrorDeFormula('Escriba una fórmula.')
    if len(texto) > LONGITUD_MAXIMA:
        raise ErrorDeFormula(
            'La fórmula no puede pasar de %d caracteres.' % LONGITUD_MAXIMA)

    # Se sustituyen las llaves antes de parsear, y después se comprueba que no
    # quede ninguna suelta. Es más claro que una expresión regular que intente
    # validar y sustituir a la vez.
    limpio = texto.replace('{{', ' ').replace('}}', ' ')
    if '{' in limpio or '}' in limpio:
        raise ErrorDeFormula(
            'Hay llaves sueltas. Las variables se escriben así: {{horas}}')
    return ' '.join(limpio.split())


# --------------------------------------------------------------------------- #
# Compilación y validación estructural
# --------------------------------------------------------------------------- #

_OPERADORES_BINARIOS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_OPERADORES_UNARIOS = (ast.UAdd, ast.USub)

# Mensajes por tipo de nodo prohibido. Se nombra el nodo en español y se explica
# qué hacer: quien escribe estas fórmulas es un administrador de RRHH, no un
# programador.
_MENSAJES_PROHIBIDOS = (
    (ast.Call, 'No se permiten llamadas a funciones en la fórmula.'),
    (ast.Attribute, 'No se permite el acceso a atributos (el punto) en la fórmula.'),
    (ast.Subscript, 'No se permiten corchetes en la fórmula.'),
    (ast.Lambda, 'La fórmula solo admite operaciones aritméticas.'),
    (ast.IfExp, 'La fórmula no admite condicionales.'),
    (ast.Compare, 'La fórmula no admite comparaciones.'),
    (ast.BoolOp, 'La fórmula no admite operadores lógicos.'),
    ((ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
     'La fórmula solo admite operaciones aritméticas.'),
    ((ast.List, ast.Tuple, ast.Set, ast.Dict),
     'La fórmula no admite listas ni conjuntos.'),
    (ast.JoinedStr, 'La fórmula no admite texto.'),
    (ast.NamedExpr, 'La fórmula no admite asignaciones.'),
    (ast.Starred, 'La fórmula solo admite operaciones aritméticas.'),
    (ast.Await, 'La fórmula solo admite operaciones aritméticas.'),
)

_MENSAJES_OPERADOR = (
    # `**` se rechaza a propósito: `9**9**9` es una denegación de servicio de una
    # línea y ningún concepto de nómina necesita potenciación.
    (ast.Pow, 'No se permite la potenciación (**) en la fórmula.'),
    (ast.Mod, 'No se permite el resto (%) en la fórmula.'),
    (ast.FloorDiv, 'No se permite la división entera (//). Para dividir use /.'),
    # En Python `^` es XOR, no potencia. Sin este mensaje, quien escriba «2^3»
    # obtendría 1 en silencio.
    (ast.BitXor, 'El símbolo ^ no está permitido. Para multiplicar use *.'),
    (ast.BitOr, 'No se permite el operador | en la fórmula.'),
    (ast.BitAnd, 'No se permite el operador & en la fórmula.'),
    (ast.LShift, 'No se permite el operador de desplazamiento en la fórmula.'),
    (ast.RShift, 'No se permite el operador de desplazamiento en la fórmula.'),
    (ast.MatMult, 'No se permite el operador @ en la fórmula.'),
)


def _mensaje_de_operador(operador):
    for tipo, mensaje in _MENSAJES_OPERADOR:
        if isinstance(operador, tipo):
            return mensaje
    return 'La fórmula solo admite las operaciones + - * / y paréntesis.'


def _revisar(nodo, profundidad=0):
    """Recorre el árbol aceptando solo lo que está en la lista blanca."""
    if profundidad > PROFUNDIDAD_MAXIMA:
        # Mide operaciones anidadas, no paréntesis: `ast.parse` colapsa los
        # paréntesis redundantes, así que «((((1))))» es profundidad 0.
        raise ErrorDeFormula(
            'La fórmula es demasiado compleja: encadena demasiadas operaciones.')

    for tipos, mensaje in _MENSAJES_PROHIBIDOS:
        if isinstance(nodo, tipos):
            raise ErrorDeFormula(mensaje)

    if isinstance(nodo, ast.Constant):
        # `type(...) is`, no `isinstance`: `isinstance(True, int)` es True y
        # `True + True == 2`, así que un booleano colaría como número.
        if type(nodo.value) is int or type(nodo.value) is float:
            return
        raise ErrorDeFormula('La fórmula solo admite números.')

    if isinstance(nodo, ast.Name):
        if not isinstance(nodo.ctx, ast.Load):
            raise ErrorDeFormula('La fórmula no admite asignaciones.')
        if nodo.id not in VARIABLES:
            raise ErrorDeFormula(
                'La variable «%s» no existe. Disponibles: %s.'
                % (nodo.id, _lista_de_variables()))
        return

    if isinstance(nodo, ast.BinOp):
        if not isinstance(nodo.op, _OPERADORES_BINARIOS):
            raise ErrorDeFormula(_mensaje_de_operador(nodo.op))
        _revisar(nodo.left, profundidad + 1)
        _revisar(nodo.right, profundidad + 1)
        return

    if isinstance(nodo, ast.UnaryOp):
        if not isinstance(nodo.op, _OPERADORES_UNARIOS):
            raise ErrorDeFormula(_mensaje_de_operador(nodo.op))
        _revisar(nodo.operand, profundidad + 1)
        return

    raise ErrorDeFormula('La fórmula solo admite operaciones aritméticas.')


def compilar(expresion):
    """Parsea y valida contra la lista blanca. Devuelve el `ast.Expression`."""
    texto = normalizar(expresion)

    try:
        # `mode='eval'` ya descarta por sí solo sentencias, asignaciones,
        # `import`, `def`, `del` y `exec`: no hay forma de expresarlos.
        arbol = ast.parse(texto, mode='eval')
    except SyntaxError:
        raise ErrorDeFormula(
            'La fórmula está mal escrita. Revise los paréntesis y los operadores.')

    total = sum(1 for _ in ast.walk(arbol))
    if total > NODOS_MAXIMOS:
        raise ErrorDeFormula('La fórmula es demasiado larga.')

    _revisar(arbol.body)
    return arbol


def variables_usadas(expresion):
    """Conjunto de variables que referencia la fórmula.

    Lo usa `NPagoImporte.clean()` para exigir `relacionado_con` cuando la fórmula
    usa `{{horas}}`: sin concepto relacionado no hay horas de donde tomarlas.
    """
    arbol = compilar(expresion)
    return {nodo.id for nodo in ast.walk(arbol) if isinstance(nodo, ast.Name)}


# --------------------------------------------------------------------------- #
# Evaluación
# --------------------------------------------------------------------------- #

def _evaluar_nodo(nodo, contexto):
    if isinstance(nodo, ast.Constant):
        # `str()` primero: `Decimal(0.1)` es 0.1000000000000000055511151231257827
        # y `Decimal(str(0.1))` es exactamente Decimal('0.1').
        return Decimal(str(nodo.value))

    if isinstance(nodo, ast.Name):
        valor = contexto.get(nodo.id)
        if valor is None:
            raise ErrorDeFormula(
                'Falta el valor de la variable «%s» para calcular.' % nodo.id)
        return Decimal(str(valor))

    if isinstance(nodo, ast.UnaryOp):
        valor = _evaluar_nodo(nodo.operand, contexto)
        return -valor if isinstance(nodo.op, ast.USub) else valor

    if isinstance(nodo, ast.BinOp):
        izquierda = _evaluar_nodo(nodo.left, contexto)
        derecha = _evaluar_nodo(nodo.right, contexto)
        if isinstance(nodo.op, ast.Add):
            return izquierda + derecha
        if isinstance(nodo.op, ast.Sub):
            return izquierda - derecha
        if isinstance(nodo.op, ast.Mult):
            return izquierda * derecha
        if derecha == 0:
            raise ErrorDeFormula('La fórmula divide entre cero.')
        return izquierda / derecha

    # Inalcanzable si `compilar()` hizo su trabajo. Se deja como red por si
    # alguien evalúa un árbol que no pasó por ahí.
    raise ErrorDeFormula('La fórmula solo admite operaciones aritméticas.')


def evaluar(expresion, contexto=None):
    """Evalúa la fórmula con precisión `Decimal`.

    **No redondea**: devuelve el valor exacto. El redondeo a dos decimales se
    aplica una sola vez, al almacenar el importe (`calculos.py`). Redondear los
    resultados intermedios acumularía error a lo largo de 30 columnas.
    """
    arbol = compilar(expresion)
    valores = {nombre: Decimal('0') for nombre in VARIABLES}
    valores.update(contexto or {})

    with localcontext() as ctx:
        ctx.prec = 28
        ctx.traps[InvalidOperation] = True
        ctx.traps[DivisionByZero] = True
        ctx.traps[Overflow] = True
        try:
            return _evaluar_nodo(arbol.body, valores)
        except ErrorDeFormula:
            raise
        except ArithmeticError:
            # Cubre InvalidOperation, DivisionByZero y Overflow, que heredan de
            # ArithmeticError.
            raise ErrorDeFormula('La fórmula produce un resultado no válido.')


def validar(expresion):
    """Punto ÚNICO de validación. Lanza `ErrorDeFormula` si algo falla.

    Lo llaman `NPagoImporte.clean()`, el admin, el endpoint HTMX de comprobación
    en vivo y el congelado de conceptos: una sola implementación en las cuatro
    superficies.

    Además de la revisión estructural hace un **ensayo en seco**, porque la
    división entre cero no es detectable estáticamente (`{{horas}}` vale 0 en
    tiempo de ejecución, no de guardado). Rechazar aquí una fórmula que
    reventaría con un trabajador de 0 horas es mucho mejor que dejar al Moderador
    bloqueado a mitad de cierre.
    """
    usadas = variables_usadas(expresion)

    for valor in VALORES_DE_ENSAYO:
        contexto = {nombre: valor for nombre in VARIABLES}
        try:
            evaluar(expresion, contexto)
        except ErrorDeFormula as error:
            if 'divide entre cero' in str(error) and valor == 0 and usadas:
                nombres = ', '.join('{{' + v + '}}' for v in sorted(usadas))
                raise ErrorDeFormula(
                    'La fórmula divide entre una variable (%s) y fallaría con '
                    'cualquier trabajador que tenga 0. Reformúlela.' % nombres)
            raise
