"""Reglas de los nomencladores de Pre-Nómina.

Las del Calendario viven en `calendario.py`; aquí van las de los conceptos de
pago, que es otra cosa: allí se comprueba que el trabajador tenga jornada, aquí
que los conceptos con los que se le paga sigan siendo calculables.
"""

from ..constantes import CRITICIDAD_ALTA, MODULO_NOMINA, TAMANO_LOTE
from .base import HallazgoDetectado, ReglaBase


class FormulaDePagoQueYaNoValida(ReglaBase):
    """Un Pago por Importe cuya fórmula ya no pasa la validación.

    `NPagoImporte.clean()` valida la fórmula AL GUARDARLA, así que ninguna nace
    rota. Pero la validación depende de cosas que cambian después:

    * el juego de variables permitidas (`prenomina.formulas.VARIABLES`) puede
      crecer o menguar entre versiones;
    * el ensayo en seco rechaza las fórmulas que dividirían entre cero, y ese
      criterio se ha endurecido con el tiempo.

    Y el desenlace es el peor posible: `calculos.importe_de()` atrapa el fallo y
    registra **cero** para no tumbar el guardado del reporte entero. El
    trabajador cobra de menos y en pantalla no aparece ningún error.
    """

    codigo = 'PNM-002'
    nombre = 'Fórmula de un Pago por Importe que ya no es válida'
    modulo = MODULO_NOMINA
    criticidad = CRITICIDAD_ALTA
    modelo = 'prenomina.NPagoImporte'

    descripcion = (
        'Revalida las fórmulas de los conceptos de Pago por Importe con el mismo '
        'validador que las comprueba al guardarlas.')
    causa_probable = (
        'La fórmula se guardó cuando era válida y después cambió el juego de '
        'variables disponibles o se endureció la validación. Nada revisa las '
        'fórmulas ya guardadas.')
    impacto = (
        'Al montar el reporte, una fórmula que falla se registra como CERO para no '
        'tumbar el guardado. El trabajador cobra de menos por ese concepto y no '
        'salta ningún error en pantalla.')
    solucion = (
        'Abra Configuración → Parámetros Generales → Tiempo de Trabajo → Pagos por '
        'Importe, edite el concepto y corrija la fórmula. El comprobador en vivo '
        'del modal le dirá si ya es válida.')

    def ejecutar(self, contexto):
        from prenomina import formulas
        from prenomina.models import TipoValorImporte

        filas = (self.base_queryset()
                 .filter(tipo_valor=TipoValorImporte.FORMULA)
                 .exclude(formula='')
                 .values('id', 'codigo', 'descripcion', 'formula')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            try:
                formulas.validar(fila['formula'])
            except formulas.ErrorDeFormula as error:
                motivo = str(error)
            except Exception as error:   # noqa: BLE001
                # Una fórmula guardada no debería romper el barrido entero. Si el
                # validador falla de una forma que no contempla, se reporta igual:
                # una fórmula que ni siquiera se puede validar es, sin duda, un
                # problema que alguien tiene que mirar.
                motivo = f'{type(error).__name__}: {error}'
            else:
                continue

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=(f'{fila["codigo"]} · {fila["descripcion"]} · '
                        f'fórmula no válida'),
                detalle=f'La fórmula guardada no pasa la validación: {motivo}',
                datos={
                    'concepto': fila['descripcion'],
                    'formula': fila['formula'],
                    'motivo': motivo,
                },
                # Los conceptos de pago son de la entidad entera, no de una unidad.
                campo_formulario='formula',
            )
