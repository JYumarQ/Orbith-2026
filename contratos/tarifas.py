"""Tarifa horaria y tarifa de horas extras: UNA sola fórmula para toda la app.

Antes cada pantalla la calculaba a su manera (decisión de RRHH del 23-10-2026):
la de edición con el porcentaje de Configuración, el cálculo en vivo con
«salario ÷ 160.6» y el asistente con «× 1.25» fijo en el código, así que el mismo
trabajador tenía tres tarifas de horas extras según la pantalla. Ahora:

    tarifa horaria = salario ÷ fondo de tiempo            (Configuración)
    horas extras   = tarifa horaria × (1 + porcentaje)    (Configuración)

Sin números fijos en el código: si Configuración no tiene un fondo de tiempo
válido, la tarifa queda vacía (la regla CFG-004 de Subsanación lo avisa) en vez
de inventarse un valor.

El salario en sí sale SIEMPRE de `contratos.salarios.calcular_salario` (a través
de `CAlta.calcular_salario_escala()`).
"""

from decimal import Decimal, InvalidOperation


def parametros_de_tarifa():
    """`(fondo_de_tiempo, porcentaje_horas_extras)` de Configuración, o `None` en
    cada uno que no sea válido (vacío, cero o negativo)."""
    from configuracion.models import Configuracion

    config = Configuracion.objects.first()
    if config is None:
        return None, None
    fondo = config.fondo_tiempo_calc_tarif
    porcentaje = config.porcentaje_horas_extras
    fondo = fondo if fondo is not None and fondo > 0 else None
    porcentaje = porcentaje if porcentaje is not None and porcentaje >= 0 else None
    return fondo, porcentaje


def calcular_tarifas(salario, parametros=None):
    """`{'salario', 'tarifa', 'extras'}` como `float` redondeados (2 y 5 decimales),
    o `None` en lo que no se pueda calcular.

    `parametros` permite pasar `parametros_de_tarifa()` ya leído cuando se calcula
    para muchas filas, y no consultar Configuración en cada una.
    """
    resultado = {'salario': None, 'tarifa': None, 'extras': None}
    try:
        salario = Decimal(str(salario)) if salario not in (None, '') else None
    except InvalidOperation:
        salario = None
    if not salario or salario <= 0:
        return resultado
    resultado['salario'] = round(float(salario), 2)

    fondo, porcentaje = parametros if parametros is not None else parametros_de_tarifa()
    if fondo is None:
        return resultado
    tarifa = salario / Decimal(fondo)
    resultado['tarifa'] = round(float(tarifa), 5)
    if porcentaje is not None:
        resultado['extras'] = round(float(tarifa * (1 + Decimal(porcentaje))), 5)
    return resultado


def salario_de_combinacion(cargo, tridente_id, tipo_salario):
    """Salario de escala para una combinación todavía sin guardar (el cálculo en
    vivo del formulario y el asistente), con el MISMO cálculo que un contrato
    guardado: se construye un contrato en memoria, sin tocar la base de datos."""
    from contratos.models import CAlta

    # El tridente llega del formulario como texto: la escala se indexa por enteros.
    tridente_id = int(tridente_id) if str(tridente_id or '').isdigit() else None
    contrato = CAlta(cargo=cargo, tridente_id=tridente_id,
                     tipo_salario=tipo_salario or 'DIN')
    return contrato.calcular_salario_escala()
