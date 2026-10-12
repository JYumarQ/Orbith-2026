import logging

from datetime import timedelta

from django.contrib.auth.decorators import login_not_required, login_required
from django.utils import timezone

from usuarios.utils import obtener_ip
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from core.validators import validar_imagen
from usuarios.decorators import admin_required

logger = logging.getLogger(__name__)

from .forms import AyudaAccesoForm, ReporteProblemaForm
from .models import ImagenReporteProblema, ReporteProblema

MAXIMO_IMAGENES = 4
TAMANO_MAXIMO_MB_IMAGEN = 2

# Límite de reportes de ayuda desde el login por IP y hora. Es la única entrada
# de datos de Orbith abierta a quien no ha iniciado sesión, así que necesita un
# freno: sin él, cualquiera en la red llenaría la bandeja del Administrador —y la
# tabla— con un bucle de tres líneas.
MAXIMO_AYUDAS_POR_IP_HORA = 3


@login_required
@require_POST
def crear_reporte(request):
    """Registra una incidencia enviada desde el modal "Acerca de Orbith".

    No envía correos ni usa servicios externos: el reporte queda en base de datos
    y el administrador lo consulta desde la bandeja.

    Las imágenes no viajan en el ModelForm (Django no admite varios ficheros en
    un mismo ImageField): se leen a mano de request.FILES.
    """
    form = ReporteProblemaForm(request.POST)
    imagenes = request.FILES.getlist('imagenes')

    errores = []
    if not form.is_valid():
        errores.extend(str(e) for lista in form.errors.values() for e in lista)

    if len(imagenes) > MAXIMO_IMAGENES:
        errores.append(f"Solo se admiten hasta {MAXIMO_IMAGENES} imágenes.")

    for imagen in imagenes:
        try:
            validar_imagen(imagen, TAMANO_MAXIMO_MB_IMAGEN)
        except Exception as e:
            # forms.ValidationError trae el mensaje en .messages
            errores.extend(getattr(e, 'messages', [str(e)]))

    if errores:
        return JsonResponse({
            'exito': False,
            'mensaje': " ".join(errores) or "Revise el formulario.",
        }, status=400)

    # Transacción: si falla el guardado de una imagen, no debe quedar el
    # reporte a medias (sin sus capturas) en la base de datos.
    with transaction.atomic():
        reporte = form.save(commit=False)
        reporte.usuario = request.user
        # Guardamos desde dónde se reportó: es lo primero que necesita quien lo revise.
        reporte.url_origen = (request.POST.get('url_origen') or '')[:255]
        reporte.save()

        for imagen in imagenes:
            ImagenReporteProblema.objects.create(reporte=reporte, imagen=imagen)

    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primer_reporte_problema')

    return JsonResponse({
        'exito': True,
        'mensaje': 'Reporte enviado. Gracias por avisar; el administrador lo revisará.',
    })


@admin_required
def lista_reportes(request):
    """Bandeja de incidencias. Solo para administradores."""
    estado = request.GET.get('estado', ReporteProblema.ESTADO_PENDIENTE)

    reportes = ReporteProblema.objects.select_related(
        'usuario', 'usuario__contrato__aspirante'
    ).prefetch_related('imagenes')
    if estado and estado != 'TODOS':
        reportes = reportes.filter(estado=estado)

    # Paginación común con enlaces (base/partials/tabla_paginacion_enlaces.html).
    from django.core.paginator import Paginator
    from core.paginacion import filas_por_pagina
    pagina = Paginator(reportes.order_by('-fecha_creado'), filas_por_pagina(request)).get_page(
        request.GET.get('pagina'))

    contexto = {
        'reportes': pagina,
        'querystring_pagina': f'&estado={estado}' if estado else '',
        'estado_actual': estado,
        'estados': ReporteProblema.ESTADOS,
        'total_pendientes': ReporteProblema.objects.filter(
            estado=ReporteProblema.ESTADO_PENDIENTE
        ).count(),
    }
    return render(request, 'pages/soporte/list_reportes.html', contexto)


@admin_required
@require_POST
def cambiar_estado_reporte(request, pk):
    """Marca un reporte como atendido o descartado."""
    reporte = get_object_or_404(ReporteProblema, pk=pk)
    nuevo_estado = request.POST.get('estado')

    estados_validos = dict(ReporteProblema.ESTADOS)
    if nuevo_estado not in estados_validos:
        return JsonResponse({'exito': False, 'mensaje': 'Estado no válido.'}, status=400)

    reporte.estado = nuevo_estado
    reporte.save(update_fields=['estado', 'fecha_actualizado'])

    return JsonResponse({
        'exito': True,
        'mensaje': f'Reporte marcado como "{estados_validos[nuevo_estado]}".',
    })


@admin_required
@require_POST
def eliminar_reporte(request, pk):
    """Borra un reporte de problema y sus imágenes.

    No hace falta guardar un histórico infinito de incidencias ya resueltas:
    el administrador decide cuándo limpiar la bandeja.
    """
    reporte = get_object_or_404(ReporteProblema, pk=pk)

    # ON_DELETE=CASCADE borra las filas de ImagenReporteProblema, pero NO borra
    # los ficheros del disco: hay que quitarlos a mano para no dejar huérfanos
    # en media/img/reportes/.
    for imagen in reporte.imagenes.all():
        nombre_fichero = imagen.imagen.name
        if nombre_fichero and default_storage.exists(nombre_fichero):
            try:
                default_storage.delete(nombre_fichero)
            except Exception:
                logger.warning("No se pudo eliminar la imagen del reporte: %s", nombre_fichero)

    reporte.delete()

    return JsonResponse({
        'exito': True,
        'mensaje': 'Reporte eliminado.',
    })


@login_not_required
@require_POST
def crear_reporte_acceso(request):
    """Reporte enviado desde el login por quien NO consigue entrar.

    Es la ÚNICA vista de Orbith que acepta datos de alguien sin autenticar, así
    que va deliberadamente recortada frente a `crear_reporte`:

    * solo dos campos de texto, **sin imágenes**: no se admite que un anónimo
      escriba ficheros en el disco del servidor;
    * límite de `MAXIMO_AYUDAS_POR_IP_HORA` por IP y hora, para que nadie pueda
      inundar la bandeja del Administrador;
    * `usuario` queda a null y el nombre tecleado se guarda en
      `usuario_declarado`, porque no está verificado y no debe confundirse con
      una identidad real.

    Cae en la misma bandeja que el resto de reportes, marcada en `url_origen`
    para que el Administrador vea de un vistazo que viene del login.

    `@login_not_required` es imprescindible: `LoginRequiredMiddleware` (activo en
    settings) exige sesión en todas las vistas salvo las marcadas así.
    """
    ip = obtener_ip(request)

    if ip:
        desde = timezone.now() - timedelta(hours=1)
        enviados = ReporteProblema.objects.filter(
            ip_origen=ip, usuario__isnull=True, fecha_creado__gte=desde).count()
        if enviados >= MAXIMO_AYUDAS_POR_IP_HORA:
            return JsonResponse({
                'exito': False,
                'mensaje': "Ya se enviaron varios reportes desde este equipo. "
                           "Espere un rato o contacte directamente al Administrador.",
            }, status=429)

    form = AyudaAccesoForm(request.POST)
    if not form.is_valid():
        errores = [str(e) for lista in form.errors.values() for e in lista]
        return JsonResponse({
            'exito': False,
            'mensaje': " ".join(errores) or "Revise el formulario.",
        }, status=400)

    reporte = form.save(commit=False)
    reporte.usuario = None
    reporte.ip_origen = ip
    reporte.url_origen = 'Login — problema de acceso'
    reporte.save()

    return JsonResponse({
        'exito': True,
        'mensaje': 'Reporte enviado. El Administrador lo revisará y se pondrá en contacto.',
    })
