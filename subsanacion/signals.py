"""Señales del módulo.

Existen para que el futuro módulo de Auditoría (y `notificaciones`) puedan
engancharse SIN que Subsanación tenga que importarlos ni conocerlos: cuando esa app
tenga modelo y UI, conecta un receptor en su propio `AppConfig.ready()` y listo.
Cero imports cruzados, cero claves ajenas, cero cambios aquí.

Se emiten desde `servicios.py` y NO desde `save()`, por dos razones: `bulk_update()`
no llama a `save()` (las señales se perderían), y así el emisor controla exactamente
en qué momento se dispara cada una.
"""

from django.dispatch import Signal

# Un hallazgo cambió de estado.
# Argumentos: hallazgo, estado_anterior, estado_nuevo, usuario, nota, automatica
hallazgo_revisado = Signal()

# Terminó un barrido completo.
# Argumentos: ejecucion
analisis_finalizado = Signal()
