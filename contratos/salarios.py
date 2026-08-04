"""Árbol de decisión del salario por escala.

ÚNICA FUENTE DE VERDAD del cálculo salarial de Orbith.

Este módulo es puro: no importa el ORM, no consulta la base de datos y no conoce
ningún modelo. Recibe los datos ya extraídos y una función de búsqueda, así que dos
llamadores muy distintos pueden compartir exactamente el mismo cálculo:

  * `CAlta.calcular_salario_escala()` le pasa una búsqueda que hace una consulta
    puntual a `NSalario` para ese contrato. Es lo que ocurre en cada guardado.
  * El módulo de Subsanación le pasa una búsqueda contra un diccionario precargado en
    memoria con toda la tabla `NSalario`, para poder revisar miles de contratos sin
    hacer una consulta por fila.

Por qué está así y no duplicado en cada sitio: si el cálculo viviera en dos lugares, el
día que cambiara la regla salarial uno de los dos se quedaría atrás y el módulo de
diagnóstico empezaría a reportar miles de discrepancias falsas. Con una sola
implementación ese escenario es imposible.

NO cambie la lógica de `calcular_salario()` sin revisar los dos llamadores.
"""


def calcular_salario(*, tipo_salario, tiene_cargo, es_cuadro, grupo_escala_id,
                     rol_id_contrato, rol_id_cargo, tridente_id, salario_basico,
                     buscar_monto):
    """Devuelve el salario de escala como `float` redondeado a 2 decimales, o `None`.

    Devuelve `None` cuando no hay datos suficientes para calcularlo. Ojo: `None`
    significa «no se puede calcular», que es distinto de «es cero».

    Argumentos:
        tipo_salario:     'DIN' (por escala) o 'FIJ' (el básico del cargo).
        tiene_cargo:      si el contrato tiene un cargo de plantilla asignado.
        es_cuadro:        si la categoría ocupacional del cargo es CDI o CEJ.
        grupo_escala_id:  grupo de escala del nomenclador del cargo.
        rol_id_contrato:  rol de pago propio del contrato (puede ser None).
        rol_id_cargo:     rol del cargo de plantilla, que se usa como respaldo.
        tridente_id:      tridente del contrato (puede ser None).
        salario_basico:   salario básico del nomenclador del cargo, para 'FIJ'.
        buscar_monto:     `f(grupo_escala_id, rol_id, tridente_id) -> monto | None`.
                          Devuelve None solo si NO existe la fila.
    """
    if tipo_salario == 'DIN':
        if not tiene_cargo:
            return None

        # El rol puede venir del contrato o, si no lo tiene, del cargo.
        rol_id = rol_id_contrato or rol_id_cargo

        if es_cuadro:
            # Un cuadro cobra sin tridente.
            monto = buscar_monto(grupo_escala_id, rol_id, None)
            if monto is None:
                # Respaldo: la escala del grupo sin rol concreto.
                monto = buscar_monto(grupo_escala_id, None, None)
        else:
            # Sin tridente no hay forma de situar al trabajador en la escala.
            if not tridente_id:
                return None
            monto = buscar_monto(grupo_escala_id, rol_id, tridente_id)

        if monto:
            return round(float(monto), 2)
        return None

    # 'FIJ': el salario es el básico del cargo, sin escala.
    if tiene_cargo and salario_basico:
        return round(float(salario_basico), 2)
    return None


def clave_salario(grupo_escala_id, rol_id, tridente_id):
    """Clave del índice de salarios precargado.

    Coincide con el `unique_together ('grupo_escala', 'rol', 'tridente')` de
    `NSalario`, así que como máximo hay un monto por clave.
    """
    return (grupo_escala_id, rol_id, tridente_id)
