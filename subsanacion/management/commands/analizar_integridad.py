"""Ejecuta el análisis de integridad desde la consola.

Llama al MISMO servicio que la interfaz web: una sola implementación, dos puertas de
entrada. Sirve para dos cosas:

  1. El primer barrido tras instalar el módulo, que es el más caro de todos porque
     inserta de golpe todos los hallazgos históricos. Conviene hacerlo por aquí, fuera
     de Gunicorn y sin límite de tiempo.
  2. Automatizarlo. Ojo: el servidor es Windows, así que se programa con el
     Programador de tareas, no con cron.

Estilo calcado del único otro comando del proyecto,
`contratos/management/commands/recalcular_salarios.py`.

Este comando NO modifica ningún dato de negocio. Solo lee, y escribe en las tablas de
Subsanación.

=============================================================================
PROGRAMARLO CON EL PROGRAMADOR DE TAREAS DE WINDOWS
=============================================================================
No hay `cron` en un servidor Windows, y no hace falta ninguna dependencia nueva para
programar esto: basta con `schtasks`, que ya viene con el sistema operativo.

Un análisis diario de madrugada, en un servidor donde el proyecto vive en
`C:\\Orbith` y el entorno virtual en `C:\\Orbith\\.venv` (ajuste las rutas a la
instalación real):

    schtasks /create /tn "Orbith - Subsanacion diaria" ^
        /tr "C:\\Orbith\\.venv\\Scripts\\python.exe C:\\Orbith\\manage.py analizar_integridad" ^
        /sc daily /st 03:00 /ru "SYSTEM"

Notas para quien lo configure:

  * `/ru "SYSTEM"` ejecuta la tarea sin depender de que una sesión de usuario esté
    abierta. Si la base de datos o el proyecto exigen credenciales concretas, cambie
    a `/ru "DOMINIO\\usuario" /rp "contraseña"`.
  * El directorio de trabajo (`/tr`) debe resolver correctamente `core/.env` y la
    base de datos configurada allí; si `schtasks` no respeta el directorio del
    proyecto, añada un `.bat` intermedio que haga `cd /d C:\\Orbith` antes de
    invocar `python.exe`.
  * Para un primer barrido puntual en vez de recurrente, no hace falta programar
    nada: se ejecuta una vez a mano, `python manage.py analizar_integridad`, y ya.
  * Comprobar que quedó programada: `schtasks /query /tn "Orbith - Subsanacion diaria"`.
  * Quitarla: `schtasks /delete /tn "Orbith - Subsanacion diaria" /f`.

El dashboard de Subsanación nunca lanza un análisis por su cuenta; siempre lee el
resultado de la última ejecución (manual, por comando o programada), así que no hay
ningún requisito de que el Programador de tareas y el servidor web coincidan en el
mismo proceso.
=============================================================================
"""

from django.core.management.base import BaseCommand, CommandError

from subsanacion import servicios
from subsanacion.constantes import CLAVES_MODULOS, ETIQUETA_MODULO
from subsanacion.models import EjecucionAnalisis
from subsanacion.reglas import obtener_regla, obtener_reglas, total_reglas


class Command(BaseCommand):
    help = (
        'Analiza la integridad de los datos y actualiza los hallazgos. '
        'Solo detecta y explica: no corrige nada.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--modulo', action='append', dest='modulos', metavar='CATEGORIA',
            help=('Analiza solo esta categoría. Se puede repetir. '
                  f'Válidas: {", ".join(CLAVES_MODULOS)}.'))
        parser.add_argument(
            '--regla', dest='regla', metavar='CODIGO',
            help='Analiza solo esta regla (por ejemplo CTR-001).')
        parser.add_argument(
            '--listar', action='store_true',
            help='Muestra el catálogo de reglas y termina, sin analizar nada.')
        parser.add_argument(
            '--silencioso', action='store_true',
            help='Solo imprime el resumen final.')

    # ------------------------------------------------------------------
    def handle(self, *args, **opciones):
        if opciones['listar']:
            self._listar_reglas()
            return

        if total_reglas() == 0:
            raise CommandError('No hay ninguna regla de diagnóstico activa.')

        silencioso = opciones['silencioso']

        if opciones['regla']:
            self._analizar_una_regla(opciones['regla'], silencioso)
            return

        modulos = self._validar_modulos(opciones['modulos'])

        try:
            ejecucion = servicios.iniciar_ejecucion(
                origen=EjecucionAnalisis.COMANDO, modulos=modulos)
        except servicios.AnalisisEnCurso as exc:
            raise CommandError(
                'Ya hay un análisis en curso '
                f'(iniciado el {exc.ejecucion.iniciada_en:%d/%m/%Y %H:%M}). '
                'Espere a que termine.')

        if not silencioso:
            self.stdout.write(f'Análisis #{ejecucion.pk} — {total_reglas()} reglas activas')
            self.stdout.write('')

        # Un contexto por categoría, igual que en la web: es el ámbito en el que tiene
        # sentido compartir cálculos caros entre reglas.
        from subsanacion.contexto import ContextoAnalisis

        for clave in ejecucion.modulos_solicitados:
            resumen = servicios.ejecutar_modulo(
                ejecucion, clave, contexto=ContextoAnalisis(ejecucion))
            if silencioso:
                continue
            if resumen['errores']:
                self.stdout.write(self.style.ERROR(
                    f"  {resumen['etiqueta']:24} {len(resumen['errores'])} regla(s) con error"))
                for codigo, mensaje in resumen['errores'].items():
                    self.stdout.write(self.style.ERROR(f'      {codigo}: {mensaje}'))
            elif resumen['reglas'] == 0:
                self.stdout.write(f"  {resumen['etiqueta']:24} sin reglas todavía")
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"  {resumen['etiqueta']:24} {resumen['reglas']} regla(s) · "
                    f"{resumen['nuevos']} nuevo(s) · "
                    f"{resumen['persistentes']} conocido(s) · "
                    f"{resumen['resueltos']} resuelto(s)"))

        servicios.finalizar_ejecucion(ejecucion)
        self._imprimir_resumen(ejecucion)

    # ------------------------------------------------------------------
    def _validar_modulos(self, solicitados):
        if not solicitados:
            return list(CLAVES_MODULOS)
        desconocidos = [c for c in solicitados if c not in CLAVES_MODULOS]
        if desconocidos:
            raise CommandError(
                f'Categoría(s) no reconocida(s): {", ".join(desconocidos)}. '
                f'Válidas: {", ".join(CLAVES_MODULOS)}.')
        # Se respeta el orden del catálogo, no el de los argumentos.
        return [c for c in CLAVES_MODULOS if c in solicitados]

    def _analizar_una_regla(self, codigo, silencioso):
        """Ejecuta una sola regla. Útil para depurar una regla nueva.

        Ojo: la reconciliación de esa regla sí se aplica (sus hallazgos se actualizan y
        los que ya no se detectan se marcan como corregidos), pero las demás reglas no
        se tocan, porque el paso de resolución está acotado por código de regla.
        """
        regla = obtener_regla(codigo)
        if regla is None:
            raise CommandError(
                f'No existe ninguna regla con el código «{codigo}». '
                f'Use --listar para ver el catálogo.')

        try:
            ejecucion = servicios.iniciar_ejecucion(
                origen=EjecucionAnalisis.COMANDO, modulos=[regla.modulo])
        except servicios.AnalisisEnCurso as exc:
            raise CommandError(
                'Ya hay un análisis en curso '
                f'(iniciado el {exc.ejecucion.iniciada_en:%d/%m/%Y %H:%M}).')

        from django.db import transaction

        from subsanacion.contexto import ContextoAnalisis

        contexto = ContextoAnalisis(ejecucion)
        with transaction.atomic():
            contadores = servicios.reconciliar_regla(regla, ejecucion, contexto)

        ejecucion.modelos_analizados = sorted(contexto.modelos_analizados)
        ejecucion.modulos_completados = [regla.modulo]
        ejecucion.codigos_regla_ejecutados = [regla.codigo]
        ejecucion.reglas_ejecutadas = 1
        ejecucion.hallazgos_nuevos = contadores['nuevos']
        ejecucion.hallazgos_persistentes = contadores['persistentes']
        ejecucion.hallazgos_resueltos = contadores['resueltos']
        ejecucion.save()
        servicios.finalizar_ejecucion(ejecucion)

        if not silencioso:
            self.stdout.write(f'{regla.codigo} · {regla.nombre}')
            self.stdout.write(self.style.SUCCESS(
                f"  {contadores['nuevos']} nuevo(s) · "
                f"{contadores['persistentes']} conocido(s) · "
                f"{contadores['resueltos']} resuelto(s)"))
            if contadores['truncada']:
                self.stdout.write(self.style.WARNING(
                    '  La regla superó el límite de hallazgos y se truncó.'))
        self._imprimir_resumen(ejecucion)

    def _listar_reglas(self):
        self.stdout.write(f'{total_reglas()} regla(s) activa(s):')
        self.stdout.write('')
        modulo_actual = None
        for regla in obtener_reglas():
            if regla.modulo != modulo_actual:
                modulo_actual = regla.modulo
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f'  {ETIQUETA_MODULO.get(modulo_actual, modulo_actual)}'))
            self.stdout.write(
                f'    {regla.codigo:10} [{regla.etiqueta_criticidad:11}] {regla.nombre}')

    def _imprimir_resumen(self, ejecucion):
        self.stdout.write('')
        estilo = self.style.SUCCESS
        if ejecucion.estado == EjecucionAnalisis.FALLIDA:
            estilo = self.style.ERROR
        elif ejecucion.estado == EjecucionAnalisis.PARCIAL:
            estilo = self.style.WARNING

        salud = '—' if ejecucion.indice_salud is None else f'{ejecucion.indice_salud} %'
        self.stdout.write(estilo(
            f'{ejecucion.get_estado_display()} · '
            f'Salud de los datos: {salud} · '
            f'{ejecucion.registros_analizados} registro(s) analizado(s) · '
            f'{ejecucion.hallazgos_vigentes} hallazgo(s) vigente(s) · '
            f'{ejecucion.duracion_ms} ms'))

        if ejecucion.errores:
            self.stdout.write(self.style.WARNING(
                'Avisos (los hallazgos de estas reglas se conservaron sin cambios):'))
            for codigo, mensaje in ejecucion.errores.items():
                self.stdout.write(self.style.WARNING(f'  {codigo}: {mensaje}'))
