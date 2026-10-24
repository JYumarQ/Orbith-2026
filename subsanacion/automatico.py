"""Búsqueda automática de incidencias sin tocar el servidor (Fase 2, 23-10-2026).

No hay tareas programadas en el servidor, así que las lanza el NAVEGADOR (ver
`static/js/incidencias_automaticas.js`, incluido en la plantilla base):

* **Análisis completo diario de Subsanación**: lo dispara el primer inicio de sesión
  del día, sea del rol que sea. Es una tarea del sistema (origen «Programada», sin
  usuario): el resultado es el mismo la lance quien la lance. Va módulo a módulo,
  una petición por módulo, como «Buscar incidencias» de Subsanación, para no
  acercarse al límite de tiempo del servidor. Si se cierra la pestaña a mitad, la
  ejecución queda abandonada y la retoma el siguiente que entre.
* **Búsqueda ligera**: Administrador, toda la empresa, como mucho cada 2 horas;
  Moderador, solo SUS registros (sus 100-200 trabajadores, no toda la empresa),
  como mucho cada 30 minutos; Observador, nunca. Pone al día SU campana
  (`notificaciones.escaneo.escanear_para_usuario`).
* **Horario** (decisión de RRHH del 24-10-2026): la jornada es de 8:30 a 15:00, así
  que a partir de las 16:00 (hora de Cuba, `TIME_ZONE`) no se lanza ninguna
  comprobación automática. Lo que pase después lo recoge el primer inicio de
  sesión del día siguiente.
"""

from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import servicios
from .constantes import CLAVES_MODULOS
from .contexto import ContextoAnalisis
from .models import EjecucionAnalisis

#: Tiempo mínimo entre dos búsquedas automáticas del mismo usuario, por rol.
INTERVALO_ADMIN = timedelta(hours=2)
INTERVALO_MODERADOR = timedelta(minutes=30)
#: A partir de esta hora (local) no se lanza ninguna comprobación automática.
HORA_LIMITE = 16


def _en_horario():
    return timezone.localtime().hour < HORA_LIMITE


def _intervalo(usuario):
    """Cada cuánto busca este usuario, o None si nunca (Observador)."""
    if usuario.es_admin:
        return INTERVALO_ADMIN
    if usuario.es_moderador:
        return INTERVALO_MODERADOR
    return None


def _sin_sesion():
    return JsonResponse({'error': 'Sesión no iniciada.'}, status=403)


def _analisis_pendiente_hoy():
    """True si es horario, hoy todavía no terminó ningún análisis completo y no hay
    uno en marcha."""
    if not _en_horario():
        return False
    servicios.cerrar_ejecuciones_abandonadas()
    if servicios.obtener_ejecucion_en_curso() is not None:
        return False
    inicio_del_dia = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return not EjecucionAnalisis.objects.filter(
        estado__in=[EjecucionAnalisis.COMPLETA, EjecucionAnalisis.PARCIAL],
        terminada_en__gte=inicio_del_dia).exists()


def _busqueda_pendiente(usuario):
    intervalo = _intervalo(usuario)
    if intervalo is None or not _en_horario():
        return False
    ultima = usuario.ultima_busqueda_incidencias
    return ultima is None or timezone.now() - ultima >= intervalo


@require_GET
def estado(request):
    if not request.user.is_authenticated:
        return _sin_sesion()
    return JsonResponse({
        'analizar': _analisis_pendiente_hoy(),
        'buscar': _busqueda_pendiente(request.user),
    })


@require_POST
def iniciar(request):
    if not request.user.is_authenticated:
        return _sin_sesion()
    if not _analisis_pendiente_hoy():
        return JsonResponse({'ocupado': True})
    try:
        ejecucion = servicios.iniciar_ejecucion(usuario=None, origen=EjecucionAnalisis.PROGRAMADA)
    except servicios.AnalisisEnCurso:
        return JsonResponse({'ocupado': True})
    return JsonResponse({'pk': ejecucion.pk,
                         'modulos': list(ejecucion.modulos_solicitados or CLAVES_MODULOS)})


@require_POST
def modulo(request, pk, clave):
    if not request.user.is_authenticated:
        return _sin_sesion()
    ejecucion = EjecucionAnalisis.objects.filter(
        pk=pk, origen=EjecucionAnalisis.PROGRAMADA, estado=EjecucionAnalisis.EN_CURSO).first()
    if ejecucion is None or clave not in CLAVES_MODULOS:
        return JsonResponse({'error': 'Análisis no disponible.'}, status=409)
    servicios.ejecutar_modulo(ejecucion, clave, contexto=ContextoAnalisis(ejecucion))
    return JsonResponse({'ok': True})


@require_POST
def finalizar(request, pk):
    if not request.user.is_authenticated:
        return _sin_sesion()
    ejecucion = EjecucionAnalisis.objects.filter(
        pk=pk, origen=EjecucionAnalisis.PROGRAMADA, estado=EjecucionAnalisis.EN_CURSO).first()
    if ejecucion is not None:
        servicios.finalizar_ejecucion(ejecucion)
    return JsonResponse({'ok': True})


@require_POST
def buscar(request):
    if not request.user.is_authenticated:
        return _sin_sesion()
    usuario = request.user
    if not _busqueda_pendiente(usuario):
        return JsonResponse({'hecho': False})
    from notificaciones.escaneo import escanear_para_usuario
    from usuarios.models import CustomUser

    # Se anota ANTES de buscar y de forma condicional: si dos pestañas abren a la
    # vez, la actualización solo «gana» en una y la otra no busca.
    from django.db.models import Q
    limite = timezone.now() - _intervalo(usuario)
    ganada = CustomUser.objects.filter(
        Q(ultima_busqueda_incidencias__isnull=True) | Q(ultima_busqueda_incidencias__lte=limite),
        pk=usuario.pk).update(ultima_busqueda_incidencias=timezone.now())
    if not ganada:
        return JsonResponse({'hecho': False})
    total = escanear_para_usuario(usuario)
    return JsonResponse({'hecho': True, 'incidencias': total})
