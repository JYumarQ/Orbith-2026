"""Parámetros del ciclo de cierres mensuales.

Están aquí y no en `Configuracion` a propósito: son reglas de negocio, no
preferencias del usuario. Si algún día la entidad necesita moverlas por pantalla,
este es el único sitio del que hay que tirar.
"""

# Ventana ordinaria de declaración: del día 20 al 25 de cada mes, ambos incluidos.
DIA_INICIO_VENTANA = 20
DIA_FIN_VENTANA = 25

# Códigos de las notificaciones del módulo. Se usan como `codigo_regla` para
# deduplicar (ver `notificaciones/avisos.py`), así que no deben repetirse con los
# de Subsanación ni con los de Recordatorios.
CODIGO_VENTANA_ABIERTA = 'CIE-VENTANA'
CODIGO_ULTIMO_DIA = 'CIE-ULTIMO-DIA'
CODIGO_DESACTUALIZADA = 'CIE-DESACTUALIZADA'

# Días antes del cierre de la ventana en que se avisa por última vez.
DIAS_AVISO_FINAL = 1

MESES = (
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
)

# --- Indicador visual del Gestor de Plantilla ---
# Puramente de presentación: no se persisten ni sustituyen a `EstadoUnidad`
# (P/A/D), que sigue siendo la única fuente de verdad para habilitar botones.
# Son cuatro colores porque el requisito distingue "ya declaró este mes" de
# "está al día pero aún no le toca" — algo que el enum P/A/D no separa.
COLOR_VERDE = 'verde'      # declaró el cierre del mes en curso
COLOR_AZUL = 'azul'        # al día, pero la ventana del mes en curso no ha abierto
COLOR_NARANJA = 'naranja'  # ventana abierta (20-25), con historial, aún sin declarar
COLOR_ROJO = 'rojo'        # nunca declaró, o dejó pasar el día 25 sin hacerlo
COLOR_SIN_HIJAS = 'gris'   # unidad principal sin ninguna subunidad todavía
