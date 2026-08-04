"""Contexto compartido durante un análisis.

Resuelve la tensión entre «una regla = una clase independiente» y «una pasada
costosa sirve a varias reglas»: la primera regla que pide un dato caro lo paga, y
las siguientes lo reutilizan, sin que ninguna dependa de otra.

    indice = contexto.memo('indice_salarios', construir_indice_salarios)

El memo vive SOLO durante la ejecución. No es una caché global: el proyecto no tiene
`CACHES` configurado y, sobre todo, no habría forma fiable de invalidarla — un
diagnóstico que trabaja con datos rancios miente.
"""


class ContextoAnalisis:
    """Se crea una vez por ejecución y se pasa a cada regla."""

    def __init__(self, ejecucion=None):
        self.ejecucion = ejecucion
        self._memo = {}
        # Etiquetas «app.Modelo» revisadas. Es un conjunto a propósito: si tres
        # reglas revisan CAlta, las filas de CAlta se cuentan UNA vez. Lo alimenta
        # el servicio, no las reglas.
        self.modelos_analizados = set()

    def memo(self, clave, fabrica):
        """Devuelve `fabrica()` calculándola solo la primera vez.

        Ojo: el memo solo vive durante una petición. Como el análisis se trocea en
        una petición por categoría, un dato caro se reutiliza entre las reglas de la
        MISMA categoría, no entre categorías distintas. Es suficiente: las reglas
        que comparten un cálculo caro pertenecen a la misma categoría.
        """
        if clave not in self._memo:
            self._memo[clave] = fabrica()
        return self._memo[clave]

    def registrar_modelo(self, etiqueta_modelo):
        """Anota que se revisó un modelo. Idempotente."""
        if etiqueta_modelo:
            self.modelos_analizados.add(etiqueta_modelo)
