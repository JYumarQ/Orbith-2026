"""Puente entre el motor de reglas y una instancia recién guardada.

Este módulo es la ÚNICA forma en que una regla se evalúa fuera del barrido
periódico. No escribe en `Hallazgo`, no dispara ninguna señal, no sabe que
`notificaciones` existe: devuelve datos puros, igual que `ejecutar()`. Quien traduce
esto en una notificación es `notificaciones/avisos.py`.

RESTRICCIÓN DE RENDIMIENTO: solo se invocan reglas con `evaluable_en_caliente=True`,
y esas reglas están obligadas (ver el docstring de `ReglaBase.evaluar_instancia()`) a
ser de coste O(1). Este módulo no lo impone en tiempo de ejecución —confía en que cada
regla respete la restricción documentada—, pero es el punto exacto donde revisar el
coste si algún día `CAlta.save()` se vuelve lento: la lista de reglas candidatas es
`[r for r in obtener_reglas() if r.evaluable_en_caliente]`, y debería ser corta para
siempre.
"""

from .reglas import obtener_reglas


def evaluar_reglas_de_instancia(instancia):
    """Reglas evaluables en caliente cuyo `modelo` coincide con el de `instancia`.

    Devuelve una lista de `(regla, [HallazgoDetectado, ...])`, solo para las reglas
    que de verdad detectaron algo (sin pares con lista vacía).
    """
    etiqueta = f'{instancia._meta.app_label}.{instancia._meta.model_name}'
    resultados = []

    for regla in obtener_reglas():
        if not regla.evaluable_en_caliente:
            continue
        if regla.modelo.lower() != etiqueta:
            continue

        detectados = regla.evaluar_instancia(instancia)
        if detectados:
            resultados.append((regla, detectados))

    return resultados
