"""Escaneo periódico de incidencias en caliente, fuera del flujo de auditoría de
Subsanación.

Llama al MISMO motor de detección que usa el botón "Buscar incidencias" de la página
de Notificaciones (`notificaciones/escaneo.py::escanear_globalmente_y_notificar_por_unidad`),
en modo global: recorre toda la empresa una sola vez y reparte cada hallazgo a los
destinatarios de su unidad. No crea `EjecucionAnalisis`, no escribe `Hallazgo`, no
depende de `subsanacion.servicios` ni dispara `analisis_finalizado` — es un comando
deliberadamente ligero, de una sola responsabilidad, distinto de
`analizar_integridad` (que sí es el barrido completo de Subsanación).

Este comando NO modifica ningún dato de negocio: solo lee, y escribe únicamente en
`notificaciones.Notificacion`.

=============================================================================
PROGRAMARLO CON EL PROGRAMADOR DE TAREAS DE WINDOWS
=============================================================================
Misma infraestructura ya documentada en
`subsanacion/management/commands/analizar_integridad.py`: no hay `cron` en Windows,
se usa `schtasks`, que ya viene con el sistema operativo — esto es una línea MÁS de
esa misma infraestructura, no una tecnología distinta.

Un escaneo cada hora, en un servidor donde el proyecto vive en `C:\\Orbith` y el
entorno virtual en `C:\\Orbith\\.venv` (ajuste las rutas a la instalación real):

    schtasks /create /tn "Orbith - Escaneo de incidencias" ^
        /tr "C:\\Orbith\\.venv\\Scripts\\python.exe C:\\Orbith\\manage.py escanear_incidencias" ^
        /sc hourly /ru "SYSTEM"

Ver las mismas notas de `analizar_integridad.py` sobre `/ru`, el directorio de
trabajo, cómo comprobar la tarea (`schtasks /query /tn "Orbith - Escaneo de incidencias"`)
y cómo quitarla (`schtasks /delete /tn "Orbith - Escaneo de incidencias" /f`).
=============================================================================
"""

from django.core.management.base import BaseCommand

from notificaciones.escaneo import escanear_globalmente_y_notificar_por_unidad
from notificaciones.limpieza import purgar_notificaciones_antiguas
from notificaciones.recordatorios import generar_recordatorios


class Command(BaseCommand):
    help = (
        'Evalúa las reglas de integridad evaluables en caliente sobre toda la '
        'empresa y notifica a los moderadores/administradores de cada unidad '
        'afectada (Advertencias); genera los Recordatorios automáticos '
        '(cumpleaños, contratos y documentos de chófer por vencer, jubilación '
        'próxima); purga las notificaciones inactivas desde hace más de 60 días. '
        'No modifica ningún dato de negocio ajeno a `notificaciones.Notificacion`.')

    def handle(self, *args, **opciones):
        resumen = escanear_globalmente_y_notificar_por_unidad()

        mensaje = f"{resumen['notificados']} advertencia(s) procesada(s)."
        if resumen['sin_unidad']:
            mensaje += (
                f" {resumen['sin_unidad']} hallazgo(s) sin unidad organizativa "
                f"se enviaron a los administradores activos.")

        resumen_recordatorios = generar_recordatorios()
        mensaje += f" {resumen_recordatorios['generados']} recordatorio(s) procesado(s)."
        if resumen_recordatorios['sin_unidad']:
            mensaje += (
                f" {resumen_recordatorios['sin_unidad']} sin unidad organizativa "
                f"se enviaron a los administradores activos.")

        resumen_purga = purgar_notificaciones_antiguas()
        mensaje += (
            f" Purgadas {resumen_purga['advertencias_y_recordatorios']} "
            f"advertencia(s)/recordatorio(s) resueltos y {resumen_purga['eventos']} "
            f"evento(s), inactivos desde hace más de 60 días.")

        self.stdout.write(self.style.SUCCESS(mensaje))
