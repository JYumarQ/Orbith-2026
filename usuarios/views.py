import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, View
from django.utils import timezone
from .models import CustomUser
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm, CustomPasswordChangeForm,
    CustomAuthenticationForm, AvatarForm,
)
from .decorators import admin_required
from configuracion.models import Configuracion

logger = logging.getLogger(__name__)
from django.views.generic.edit import FormView


def _con_progreso(queryset):
    """Añade a cada usuario su avance en la Guía de Orbith (`progreso_total`
    y `progreso_completadas_count`). Cada rol tiene su propio total de
    tareas, así que se calcula en `progreso.servicios.anotar_progreso` con
    dos consultas para toda la tabla, sin N+1. Devuelve una lista.
    """
    from progreso.servicios import anotar_progreso
    return anotar_progreso(queryset)
from django.urls import reverse_lazy
from django.db.models import Q
from django.contrib.auth import get_user_model, logout, update_session_auth_hash
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from core.mixins import AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin

class UsuarioListView(LoginRequiredMixin, ListView):
    model = CustomUser
    template_name = "pages/usuarios/list_usuarios.html"

    def get_queryset(self):
        # Excluye al usuario con username "superadmin"
        return _con_progreso(CustomUser.objects.exclude(username='admin').order_by('username'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CustomUserCreationForm()
        context['configuracion'] = Configuracion.objects.first()
        return context

@login_required
def search_usuarios(request):
    query = request.GET.get('filter_usuario', '')
    
    results = _con_progreso(CustomUser.objects.filter(
        Q(username__icontains=query)|
        Q(contrato__aspirante__nombre__icontains=query)|
        Q(contrato__aspirante__papellido__icontains=query)|
        Q(contrato__aspirante__sapellido__icontains=query)
    ).exclude(username='admin').order_by('username'))

    # Paginación común: las filas por página del usuario (core/paginacion.py).
    from core.paginacion import paginar
    pagina = paginar(request, results)
    contexto = {'usuarios': pagina, 'page_obj': pagina}
    return render(request, 'pages/usuarios/partials/filter_usuarios_list.html', contexto)

User = get_user_model()

@login_required
def validar_username(request):
    username = request.GET.get('username', None)
    user_id = request.GET.get('user_id')  # <-- NUEVO
    qs = User.objects.filter(username__iexact=username)

    # Excluir al propio usuario en caso de edición
    if user_id:
        qs = qs.exclude(pk=user_id)

    data = {
        'exists': qs.exists()
    }
    return JsonResponse(data)

class CustomUserCreateView(LoginRequiredMixin, CreateView):
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'pages/usuarios/add_usuario.html'

#    def form_invalid(self, form):
#        context = {'form': form}
#        html_form = render_to_string(self.template_name, context, request=self.request)
#        return JsonResponse({'form_is_valid': False, 'html_form': html_form})

    def form_valid(self, form):
        from .permisos_especiales import registrar_cambio_de_perfil
        user = form.save(commit=False)
        user.save()
        form.save_m2m()
        registrar_cambio_de_perfil(user, {'perfil': '', 'vence': '', 'motivo': ''})
        message = f'Usuario "{user.username}" creado correctamente.'
        return JsonResponse({
            'form_is_valid': True,
            'message': message
        })
    
    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                'pages/usuarios/add_usuario.html',  # <-- este, no updt_usuario.html
                {'form': form},
                request=self.request
            )
            return JsonResponse({'form_is_valid': False, 'html_form': html}, status=200)
        return super().form_invalid(form)

class CustomUserUpdateView(LoginRequiredMixin, AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    model = CustomUser
    form_class = CustomUserChangeForm
    template_name = 'pages/usuarios/updt_usuario.html'
    template_name_pagina = 'pages/usuarios/updt_usuario_pagina.html'
    url_por_defecto = reverse_lazy('list_usuarios')

    def form_valid(self, form):
        from .permisos_especiales import foto_de_asignacion, registrar_cambio_de_perfil
        antes = foto_de_asignacion(form.instance.pk)
        user = form.save()
        self.object = user
        registrar_cambio_de_perfil(user, antes)
        hay_origen = bool(self.request.POST.get('next') or self.request.GET.get('next'))
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            # Hay una redirección real posterior SOLO cuando hay `next` (ver
            # `next_url` abajo): sin eso, el modal se cierra en la MISMA página y un
            # `messages.success()` aquí quedaría «colgado» en la sesión.
            if hay_origen:
                messages.success(self.request, self.mensaje_de_guardado_exitoso('Usuario actualizado correctamente'))
            return JsonResponse({
                'form_is_valid': True,  # <-- usa la misma clave que en create
                'message': 'Usuario actualizado correctamente',
                'es_admin': user.es_admin,
                'es_moderador': user.es_moderador,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                # Solo poblado cuando se abrió desde fuera (Notificaciones/Subsanación,
                # ver core.mixins.VolverAlOrigenMixin); vacío en el flujo normal dentro
                # de list_usuarios.html, que no lo necesita.
                'next_url': self.get_success_url() if hay_origen else '',
            })
        messages.success(self.request, self.mensaje_de_guardado_exitoso('Usuario actualizado correctamente'))
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                'pages/usuarios/updt_usuario.html',
                {'form': form, 'object': form.instance},
                request=self.request
            )
            return JsonResponse({'form_is_valid': False, 'html_form': html}, status=200)
        return super().form_invalid(form)

class CambiarPasswordView(LoginRequiredMixin, FormView):
    """Cambia la contraseña de `pk`. Un usuario siempre puede cambiar la suya
    propia; para cambiar la de otro usuario hace falta ser Administrador."""
    template_name = 'pages/usuarios/partials/cambiar_password_form.html'
    form_class = CustomPasswordChangeForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # deja que LoginRequiredMixin redirija al login
        objetivo = self.get_user()
        es_propia_cuenta = objetivo.pk == request.user.pk
        if not es_propia_cuenta and not getattr(request.user, 'es_admin', False):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("No tienes permiso para cambiar la contraseña de otro usuario.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user'] = self.get_user()
        # Página desde la que se abrió el modal, para volver a ella al guardar.
        # El modal se carga por AJAX desde la propia pantalla, así que el
        # Referer de ESA petición GET es justo la página en la que está el
        # usuario («Mi Perfil», el listado de usuarios...). Se guarda en un
        # campo oculto porque el POST posterior es un envío normal de
        # formulario y ahí ya no tenemos ese dato de forma fiable.
        context['url_de_regreso'] = self._url_segura(
            self.request.GET.get('next') or self.request.META.get('HTTP_REFERER')
        )
        return context

    def _url_segura(self, url):
        """Devuelve `url` solo si apunta a este mismo sitio; si no, cadena vacía.

        Sin esta comprobación, cualquiera podría fabricar un enlace con
        `?next=https://sitio-malicioso/` y usar el cambio de contraseña como
        trampolín de redirección (open redirect).
        """
        if not url:
            return ''
        es_segura = url_has_allowed_host_and_scheme(
            url=url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        )
        return url if es_segura else ''

    def get_user(self):
        """
        Recupera el usuario al que le queremos cambiar la contraseña.
        """
        user_id = self.kwargs.get('pk')  # El pk debe ser pasado por la URL
        return get_object_or_404(User, pk=user_id)

    def get_form_kwargs(self):
        """
        Pasa el usuario al formulario para que CustomPasswordChangeForm lo reciba.
        """
        kwargs= super().get_form_kwargs()
        kwargs['user'] = self.get_user()  # Pasar el usuario al formulario
        return kwargs

    def form_valid(self, form):
        """
        Si el formulario es válido, guardamos la nueva contraseña del usuario.
        """
        user = self.get_user()  # Obtén el usuario al que le cambiarás la contraseña
        es_propia_cuenta = user.pk == self.request.user.pk

        user.set_password(form.cleaned_data['new_password1'])  # Establecer nueva contraseña
        user.save()  # Guardar el usuario con la nueva contraseña

        # `update_session_auth_hash` SOLO cuando uno cambia su propia contraseña.
        # Cambiar la contraseña invalida la sesión de ese usuario, y esta llamada
        # es la que evita que se le eche fuera. Si un Administrador cambia la
        # contraseña de OTRO usuario y se llama igualmente, se escribe en la
        # sesión del Administrador el hash del otro usuario y quien acaba
        # desconectado es el propio Administrador.
        if es_propia_cuenta:
            update_session_auth_hash(self.request, user)

        messages.success(self.request, 'Contraseña cambiada exitosamente.')

        # Si la petición es AJAX, devolvemos una respuesta JSON
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'form_is_valid': True,
                'message': 'Contraseña cambiada exitosamente.'
            })

        return redirect(self.get_success_url())

    def get_success_url(self):
        """A dónde volver después de guardar la contraseña.

        1. A la página desde la que se abrió el modal (campo oculto `next`), que
           es lo que el usuario espera: si cambió su contraseña desde «Mi
           Perfil», se queda en «Mi Perfil».
        2. Si no hay `next` utilizable, se decide por rol: el Administrador va al
           listado de usuarios (viene de ahí cuando cambia la contraseña de otro)
           y cualquier otro usuario va al inicio.

        Antes se redirigía SIEMPRE a `list_usuarios`, así que un Moderador que
        cambiaba su propia contraseña acababa en una pantalla exclusiva de
        Administradores.
        """
        destino = self._url_segura(self.request.POST.get('next'))
        if destino:
            return destino
        if getattr(self.request.user, 'es_admin', False):
            return reverse_lazy('list_usuarios')
        return reverse_lazy('dashboard')

    def form_invalid(self, form):
        """
        Si el formulario no es válido, devolvemos los errores y el formulario.

        Antes se llamaba a `self.render_to_string(...)`, que no existe en las
        vistas de Django (la función es `django.template.loader.render_to_string`),
        así que esta rama reventaba con AttributeError en vez de mostrar el error
        de validación. Ahora se devuelven los mensajes ya montados: el modal de
        «Mi Perfil» solo necesita el texto para el aviso.
        """
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            errores = [str(e) for lista in form.errors.values() for e in lista]
            return JsonResponse({
                'form_is_valid': False,
                'message': " ".join(errores) or "No se pudo cambiar la contraseña.",
                'html_form': render_to_string(
                    self.template_name,
                    self.get_context_data(form=form),
                    request=self.request,
                ),
            }, status=400)

        return self.render_to_response(self.get_context_data(form=form))

def dependencias_del_usuario(usuario):
    """Lo que impide borrar a un usuario, listo para explicárselo.

    Devuelve una lista de `{'que', 'detalle', 'donde'}`, vacía si se puede
    borrar. Se comprueban tres cosas, y las tres por el mismo motivo: son datos
    **personales suyos** de los que dependen otras partes del sistema.

    * **Unidades Organizativas**: cada unidad tiene un solo moderador. Borrarlo
      dejaría a sus unidades sin responsable en silencio.
    * **Plantillas de reporte**: si alguna se usó en un reporte de pago, la
      clave foránea es `PROTECT` y el borrado reventaría con un error 500 en
      lugar de una explicación. Se comprueba antes para poder dar el motivo.
    * **Calendarios y períodos de pago**: sus asignaciones de jornada a
      trabajadores se irían con él, y los reportes futuros de esas unidades no
      podrían calcular las horas del mes.

    Los reportes que el usuario haya cerrado NO bloquean: el nombre de quien
    cerró está congelado en el propio reporte (`cerrado_por_nombre`), así que el
    histórico sobrevive intacto aunque la cuenta desaparezca.
    """
    from prenomina.models import Calendario, CalendarioPago, PlantillaReporte

    impedimentos = []

    unidades = list(usuario.unidades.all()[:6])
    total_unidades = usuario.unidades.count()
    if total_unidades:
        nombres = ', '.join(u.descripcion for u in unidades)
        if total_unidades > len(unidades):
            nombres += f' y {total_unidades - len(unidades)} más'
        impedimentos.append({
            'que': f'{total_unidades} Unidad'
                   f'{"es" if total_unidades != 1 else ""} Organizativa'
                   f'{"s" if total_unidades != 1 else ""} asignada'
                   f'{"s" if total_unidades != 1 else ""}',
            'detalle': nombres,
            'donde': 'Quítelas desde «Editar usuario».',
        })

    plantillas = list(PlantillaReporte.objects.filter(usuario=usuario)[:6])
    total_plantillas = PlantillaReporte.objects.filter(usuario=usuario).count()
    if total_plantillas:
        nombres = ', '.join(p.descripcion for p in plantillas)
        if total_plantillas > len(plantillas):
            nombres += f' y {total_plantillas - len(plantillas)} más'
        impedimentos.append({
            'que': f'{total_plantillas} plantilla'
                   f'{"s" if total_plantillas != 1 else ""} de reporte',
            'detalle': nombres,
            'donde': 'Se gestionan en Pre-Nómina → Mis Plantillas. Las que ya se '
                     'hayan usado en un reporte no se pueden eliminar.',
        })

    total_calendarios = Calendario.objects.filter(usuario=usuario).count()
    total_periodos = CalendarioPago.objects.filter(usuario=usuario).count()
    if total_calendarios or total_periodos:
        partes = []
        if total_calendarios:
            partes.append(f'{total_calendarios} jornada'
                          f'{"s" if total_calendarios != 1 else ""}')
        if total_periodos:
            partes.append(f'{total_periodos} Calendario'
                          f'{"s" if total_periodos != 1 else ""} de Pago')
        impedimentos.append({
            'que': 'Calendarios propios',
            'detalle': ' y '.join(partes),
            'donde': 'Se gestionan en Pre-Nómina → Calendario.',
        })

    return impedimentos


def bloqueo_por_rol(objetivo, actor):
    """Motivo por el que el rol impide borrar, o `None` si no lo impide.

    Dos reglas, y las dos existen para que nadie pueda dejar a otro fuera ni
    dejar a Orbith sin quien lo administre:

    * **Un administrador solo puede eliminar su propia cuenta.** Entre iguales,
      nadie decide por otro: si un administrador debe irse, lo hace él mismo.
    * **No se borra al último administrador activo.** Sin ninguno, nadie podría
      volver a entrar a administrar y la única salida sería crear un superusuario
      por consola.

    El mensaje del primer caso dice lo que NO se puede hacer y por qué, sin
    explicar rodeos: quien tenga que darle una vuelta, la encontrará.
    """
    if objetivo.es_admin and objetivo.pk != actor.pk:
        return ('Un usuario Administrador solo puede eliminar su propia cuenta. '
                'No es posible eliminar la cuenta de otro Administrador.')

    if objetivo.es_admin:
        quedan = (CustomUser.objects
                  .filter(es_admin=True, is_active=True)
                  .exclude(pk=objetivo.pk).count())
        if not quedan:
            return ('Es el único Administrador activo de Orbith. Si elimina su '
                    'cuenta nadie podría volver a administrar el sistema. '
                    'Nombre antes a otro Administrador.')

    return None


@admin_required
@require_POST
def inhabilitar_usuario(request, pk):
    """Desactiva una cuenta en lugar de borrarla.

    Es la alternativa que se ofrece cuando el borrado está bloqueado: conserva
    las unidades, plantillas y calendarios del usuario —y su rastro en
    Auditoría— pero le quita el acceso, que casi siempre es lo que se buscaba.

    No se admite sobre un Administrador: dejar fuera a un igual sin su
    consentimiento es justo lo que impide `bloqueo_por_rol`, y permitirlo aquí
    sería la misma puerta por otro lado.
    """
    usuario = get_object_or_404(CustomUser, pk=pk)

    if usuario.es_admin:
        messages.error(request,
                       'No se puede inhabilitar la cuenta de un Administrador.')
        return redirect('list_usuarios')

    if not usuario.is_active:
        messages.info(request, f'La cuenta de «{usuario.username}» ya estaba inhabilitada.')
        return redirect('list_usuarios')

    usuario.is_active = False
    usuario.save(update_fields=['is_active'])
    messages.success(
        request,
        f'Cuenta de «{usuario.username}» inhabilitada. Sus Unidades '
        f'Organizativas, plantillas y calendarios se conservan.')
    return redirect('list_usuarios')


class CustomUserDeleteView(LoginRequiredMixin, View):
    """Confirmación y borrado de un usuario.

    Antes esto era un `DeleteView` cuyo `get()` borraba directamente. Eran tres
    problemas a la vez, y el primero era de seguridad:

    * **un GET destruía datos**: Django no protege los GET con CSRF, así que
      bastaba un enlace o una imagen apuntando a esa URL para borrar una cuenta
      con la sesión de un administrador abierta;
    * no había ninguna confirmación, de modo que un clic en la papelera bastaba;
    * no se comprobaba nada de lo que colgaba del usuario.

    Ahora `GET` solo pinta el modal y el borrado viaja por `POST`, que sí lleva
    token CSRF, como el resto de acciones destructivas del proyecto.
    """

    def _contexto(self, request, usuario):
        return {
            'objetivo': usuario,
            'bloqueo_rol': bloqueo_por_rol(usuario, request.user),
            'impedimentos': dependencias_del_usuario(usuario),
            'es_propia_cuenta': usuario.pk == request.user.pk,
            # Inhabilitar solo tiene sentido sobre una cuenta que no sea de
            # Administrador y que siga activa.
            'puede_inhabilitar': not usuario.es_admin and usuario.is_active,
        }

    def get(self, request, *args, **kwargs):
        usuario = get_object_or_404(CustomUser, pk=kwargs['pk'])
        return render(request, 'pages/usuarios/partials/confirmar_eliminar.html',
                      self._contexto(request, usuario))

    def post(self, request, *args, **kwargs):
        usuario = get_object_or_404(CustomUser, pk=kwargs['pk'])

        # Las comprobaciones se repiten aquí y no se dejan solo en la plantilla:
        # ocultar el botón no es la protección, y este POST puede llegar de
        # cualquier sitio. El rol va primero porque es la regla más fuerte.
        motivo = bloqueo_por_rol(usuario, request.user)
        if motivo:
            messages.error(request, motivo)
            return redirect('list_usuarios')

        impedimentos = dependencias_del_usuario(usuario)
        if impedimentos:
            messages.error(
                request,
                f'No se puede eliminar a «{usuario.username}»: '
                + '; '.join(f'{i["que"]} ({i["detalle"]})' for i in impedimentos)
                + '.')
            return redirect('list_usuarios')

        nombre = usuario.username
        es_propia_cuenta = usuario.pk == request.user.pk
        usuario.delete()

        # Quien borra su propia cuenta se queda sin cuenta: se cierra la sesión
        # explícitamente y se le manda al login. Sin esto quedaría navegando con
        # una sesión que apunta a un usuario que ya no existe.
        if es_propia_cuenta:
            logout(request)
            messages.success(
                request, f'Su cuenta «{nombre}» fue eliminada. Sesión cerrada.')
            return redirect('login')

        messages.success(request, f'Usuario "{nombre}" eliminado correctamente.')
        return redirect('list_usuarios')


# =========================================================================
# MODO DE MANTENIMIENTO Y GESTIÓN DE SESIONES
# Estas tres vistas se envuelven con `admin_required` en usuarios/urls.py:
# no basta con ocultar los botones en la plantilla, el backend también
# rechaza la petición si quien la hace no es Administrador.
# =========================================================================

@require_POST
def activar_mantenimiento(request):
    config = Configuracion.objects.first()
    if not config:
        return JsonResponse({'exito': False, 'mensaje': 'No existe una Configuracion global.'}, status=400)
    config.modo_mantenimiento = True
    config.save()
    return JsonResponse({'exito': True, 'mensaje': 'Modo de mantenimiento activado.', 'modo_mantenimiento': True})


@require_POST
def desactivar_mantenimiento(request):
    config = Configuracion.objects.first()
    if not config:
        return JsonResponse({'exito': False, 'mensaje': 'No existe una Configuracion global.'}, status=400)
    config.modo_mantenimiento = False
    config.save()
    return JsonResponse({'exito': True, 'mensaje': 'Modo de mantenimiento desactivado.', 'modo_mantenimiento': False})


@require_POST
def expulsar_sesion(request, pk):
    """Invalida la sesión de un usuario normal conectado. No borra al usuario,
    no toca is_active ni ningún campo de permisos: solo marca
    `sesion_invalidada_en`, que usuarios.middleware.ControlAccesoMiddleware
    compara contra `last_login` en la siguiente petición del usuario expulsado.

    Solo puede expulsarse a usuarios normales (Moderador/Observador): un
    Administrador nunca puede ser expulsado, ni siquiera por otro Administrador
    ni por sí mismo. Estas comprobaciones se repiten aquí aunque la plantilla
    ya deshabilite el botón: la validación real vive en el backend.
    """
    usuario = get_object_or_404(CustomUser, pk=pk)

    if usuario.pk == request.user.pk:
        return JsonResponse({'exito': False, 'mensaje': 'No puedes expulsar tu propia sesión.'}, status=400)

    if usuario.es_admin:
        return JsonResponse({'exito': False, 'mensaje': 'No se puede expulsar a un Administrador.'}, status=400)

    if not usuario.esta_conectado:
        return JsonResponse({'exito': False, 'mensaje': 'El usuario ya está desconectado.'}, status=400)

    # `ultima_actividad` se limpia también: si no, "Conectado/Desconectado" seguiría
    # mostrando verde hasta que expire el umbral, aunque la sesión ya esté invalidada.
    CustomUser.objects.filter(pk=usuario.pk).update(
        sesion_invalidada_en=timezone.now(), ultima_actividad=None,
    )
    return JsonResponse({
        'exito': True,
        'mensaje': f'Sesión de "{usuario.username}" cerrada correctamente.',
    })


class CustomLoginView(LoginView):
    form_class = CustomAuthenticationForm
    template_name = 'registration/login.html'

    # Quien ya tiene sesión abierta y vuelve a /accounts/login/ va directo al
    # dashboard en lugar de ver otra vez el formulario. Antes se le mostraba el
    # login, y volver a autenticarse le creaba una sesión nueva sin necesidad.
    redirect_authenticated_user = True


# =========================================================================
# MENÚ DE USUARIO: perfil y preferencias personales
# Cada usuario actúa SIEMPRE sobre su propia cuenta (request.user); estas
# vistas no aceptan un pk de destino, así que nadie puede tocar la ficha de
# otro usuario desde aquí.
# =========================================================================

@login_required
@require_POST
def actualizar_avatar(request):
    """Sube o reemplaza la foto de perfil del usuario que hace la petición."""
    form = AvatarForm(request.POST, request.FILES, instance=request.user)

    if not form.is_valid():
        errores = [str(e) for lista in form.errors.values() for e in lista]
        return JsonResponse({
            'exito': False,
            'mensaje': " ".join(errores) or "No se pudo guardar la imagen.",
        }, status=400)

    avatar_anterior = CustomUser.objects.filter(pk=request.user.pk).values_list(
        'avatar', flat=True
    ).first()

    usuario = form.save()

    # Borramos el fichero anterior para no dejar imágenes huérfanas en /media.
    # Se hace después de guardar: si el guardado falla, no perdemos la foto vieja.
    if avatar_anterior and avatar_anterior != usuario.avatar.name:
        try:
            default_storage.delete(avatar_anterior)
        except Exception:
            logger.warning("No se pudo eliminar el avatar anterior: %s", avatar_anterior)

    return JsonResponse({
        'exito': True,
        'mensaje': 'Foto de perfil actualizada.',
        'avatar_url': usuario.avatar.url if usuario.avatar else '',
    })


@login_required
@require_POST
def eliminar_avatar(request):
    """Quita la foto de perfil y vuelve al avatar por defecto."""
    usuario = request.user
    nombre_fichero = usuario.avatar.name if usuario.avatar else None

    if not nombre_fichero:
        return JsonResponse({'exito': True, 'mensaje': 'No había foto de perfil.'})

    usuario.avatar = None
    usuario.save()

    try:
        default_storage.delete(nombre_fichero)
    except Exception:
        logger.warning("No se pudo eliminar el avatar: %s", nombre_fichero)

    return JsonResponse({'exito': True, 'mensaje': 'Foto de perfil eliminada.'})


@login_required
@require_POST
def guardar_preferencias(request):
    """Guarda las preferencias de interfaz del usuario.

    Lo usan tanto el modal de Configuración como el botón de plegar la barra
    lateral. Devuelve siempre JSON: el frontend aplica el cambio al instante y
    esta llamada solo lo persiste, así que un fallo aquí no debe romper la UI.
    """
    preferencias = request.user.obtener_preferencias()

    def _leer_booleano(clave):
        """Solo actualiza el campo si la clave viene en la petición."""
        if clave not in request.POST:
            return None
        return request.POST.get(clave) in ('true', 'True', '1', 'on')

    sidebar = _leer_booleano('sidebar_colapsada')
    animaciones = _leer_booleano('animaciones_activas')
    distincion = _leer_booleano('mostrar_distincion')

    campos = []
    if sidebar is not None:
        preferencias.sidebar_colapsada = sidebar
        campos.append('sidebar_colapsada')
    if animaciones is not None:
        preferencias.animaciones_activas = animaciones
        campos.append('animaciones_activas')
    if distincion is not None:
        preferencias.mostrar_distincion = distincion
        campos.append('mostrar_distincion')
    if 'filas_por_pagina' in request.POST:
        from core.paginacion import OPCIONES_FILAS
        try:
            filas = int(request.POST.get('filas_por_pagina'))
        except (TypeError, ValueError):
            filas = None
        if filas not in OPCIONES_FILAS:
            return JsonResponse({'exito': False, 'mensaje': 'Número de filas no válido.'}, status=400)
        preferencias.filas_por_pagina = filas
        campos.append('filas_por_pagina')

    # Firmas de los Anexos 17 (25-10-2026): solo Administrador y Moderador, y solo
    # plazas de cuadro de su alcance (`informes_anexo/firmantes.py`).
    from informes_anexo.firmantes import FIRMAS, plazas_para_firmar
    for cual, datos in FIRMAS.items():
        if datos['campo'] not in request.POST and datos['titulo'] not in request.POST:
            continue
        if not (request.user.es_admin or request.user.es_moderador):
            return JsonResponse({'exito': False, 'mensaje': 'Las firmas solo las configuran '
                                 'Administradores y Moderadores.'}, status=403)
        if datos['campo'] in request.POST:
            valor = (request.POST.get(datos['campo']) or '').strip()
            plaza = None
            if valor:
                plaza = plazas_para_firmar(request.user).filter(pk=valor if valor.isdigit() else 0).first()
                if plaza is None:
                    return JsonResponse({'exito': False, 'mensaje': 'Esa plaza no es de un cuadro de sus '
                                         'unidades.'}, status=400)
            setattr(preferencias, datos['campo'], plaza)
            campos.append(datos['campo'])
        if datos['titulo'] in request.POST:
            setattr(preferencias, datos['titulo'], (request.POST.get(datos['titulo']) or '').strip()[:100])
            campos.append(datos['titulo'])

    if not campos:
        return JsonResponse({'exito': False, 'mensaje': 'No se recibió ninguna preferencia.'}, status=400)

    preferencias.save(update_fields=campos + ['fecha_actualizado'])

    return JsonResponse({
        'exito': True,
        'mensaje': 'Preferencias guardadas.',
        'sidebar_colapsada': preferencias.sidebar_colapsada,
        'animaciones_activas': preferencias.animaciones_activas,
        'mostrar_distincion': preferencias.mostrar_distincion,
        'filas_por_pagina': preferencias.filas_por_pagina,
    })

@login_required
def firmas_preferencias(request):
    """La sección «Firmas de los Anexos 17» del modal Configuración (25-10-2026). Se
    carga al abrir el modal para no consultar la plantilla en cada página."""
    from django.http import HttpResponse
    from django.shortcuts import render

    from informes_anexo.firmantes import FIRMAS, opciones

    if not (request.user.es_admin or request.user.es_moderador):
        return HttpResponse('')
    preferencias = request.user.obtener_preferencias()
    bloques = [{
        'cual': cual, 'etiqueta': datos['etiqueta'], 'ejemplo': datos['ejemplo'],
        'campo': datos['campo'], 'campo_titulo': datos['titulo'],
        'elegida': getattr(preferencias, datos['campo'] + '_id'),
        'titulo': getattr(preferencias, datos['titulo']),
    } for cual, datos in FIRMAS.items()]
    return render(request, 'base/partials/preferencias_firmas.html',
                  {'bloques': bloques, 'opciones': opciones(request.user)})


# =========================================================================
# «EJECUTAR TODOS LOS ANÁLISIS» (solo Administrador)
#
# Los tres procesos de mantenimiento de Orbith (escaneo de incidencias,
# recordatorios y análisis de integridad de Subsanación) estaban pensados para
# correr como tareas programadas del sistema operativo —de ahí los comandos
# `escanear_incidencias` y `analizar_integridad`—, pero en este despliegue no hay
# acceso para configurarlas, así que en la práctica solo corrían si alguien
# pulsaba tres botones repartidos por dos pantallas. Este botón los junta.
#
# Dos decisiones importantes:
#
# 1) Alcance GLOBAL, no el del administrador que pulsa. Se llama a
#    `escanear_globalmente_y_notificar_por_unidad()`, la misma función que usa el
#    comando de consola, y NO a `escanear_para_usuario()` (la del botón «Buscar
#    incidencias»), que solo crea notificaciones para quien lo pulsa. Aquí se
#    reparte cada hallazgo a los destinatarios de SU unidad, que es lo que se
#    espera de un mantenimiento de toda la empresa.
#
# 2) El análisis de Subsanación NO se ejecuta aquí dentro. No cabe en una sola
#    petición: `subsanacion/views.py::ejecutar_modulo` documenta que la cadena
#    está troceada por categorías precisamente para no pasar el límite de tiempo
#    de Gunicorn, ya que el proyecto no tiene workers de fondo. Esta vista solo
#    ABRE la ejecución y devuelve el primer eslabón de esa cadena, que continúa
#    sola por HTMX contra las URLs que ya existen en Subsanación.
# =========================================================================

@require_POST
def ejecutar_todos_los_analisis(request):
    """Encadena los tres procesos de mantenimiento y devuelve el parcial de progreso.

    Los dos primeros pasos (incidencias y recordatorios) son rápidos y se resuelven
    en esta misma petición. El tercero solo se arranca: la plantilla devuelta lleva
    el disparador HTMX que va ejecutando las categorías una a una.
    """
    from notificaciones.escaneo import escanear_globalmente_y_notificar_por_unidad
    from notificaciones.recordatorios import generar_recordatorios
    from subsanacion import servicios
    from subsanacion.constantes import CLAVES_MODULOS, ETIQUETA_MODULO, MODULOS
    from subsanacion.models import EjecucionAnalisis
    from subsanacion.reglas import total_reglas
    from subsanacion.servicios import AnalisisEnCurso

    contexto = {'pasos': [], 'ejecucion': None}

    def _paso(etiqueta, funcion):
        """Ejecuta un paso y lo traduce a una línea de resultado.

        Cada paso se aísla: si el escaneo falla, los recordatorios deben correr
        igual. Ninguno de los dos deja la base de datos a medias —ambos son
        idempotentes y se reconcilian en la pasada siguiente—, así que abortar
        todo por un fallo parcial daría menos información y ninguna seguridad
        extra.
        """
        try:
            return funcion(), None
        except Exception as exc:                     # noqa: BLE001
            logger.exception('Falló el paso «%s» de Ejecutar todos los análisis', etiqueta)
            contexto['pasos'].append({'etiqueta': etiqueta, 'error': str(exc)})
            return None, exc

    resumen_incidencias, fallo = _paso('Búsqueda de incidencias',
                                       escanear_globalmente_y_notificar_por_unidad)
    if fallo is None:
        detalle = (f"{resumen_incidencias['notificados']} incidencia(s) notificada(s) "
                   f"a los destinatarios de cada unidad")
        if resumen_incidencias['sin_unidad']:
            detalle += (f"; {resumen_incidencias['sin_unidad']} sin unidad organizativa "
                        f"se enviaron a los administradores")
        contexto['pasos'].append({'etiqueta': 'Búsqueda de incidencias', 'detalle': detalle})

    resumen_recordatorios, fallo = _paso('Actualización de recordatorios',
                                         generar_recordatorios)
    if fallo is None:
        detalle = f"{resumen_recordatorios['generados']} recordatorio(s) actualizado(s)"
        if resumen_recordatorios['sin_unidad']:
            detalle += (f"; {resumen_recordatorios['sin_unidad']} sin unidad organizativa "
                        f"se enviaron a los administradores")
        contexto['pasos'].append({'etiqueta': 'Actualización de recordatorios',
                                  'detalle': detalle})

    # --- Tercer paso: solo se abre la ejecución; la cadena sigue por HTMX ---
    try:
        ejecucion = servicios.iniciar_ejecucion(
            usuario=request.user, origen=EjecucionAnalisis.MANTENIMIENTO)
    except AnalisisEnCurso as exc:
        minutos = 0
        if exc.ejecucion is not None:
            minutos = int((timezone.now() - exc.ejecucion.iniciada_en).total_seconds() // 60)
        contexto['pasos'].append({
            'etiqueta': 'Análisis de la base de datos',
            'error': (f'Ya había un análisis en curso, iniciado hace {minutos} minuto(s), '
                      f'así que este no se lanzó. Los dos pasos anteriores sí se '
                      f'completaron.'),
        })
        return render(request, 'pages/usuarios/partials/analisis_global.html', contexto)

    if total_reglas() == 0:
        servicios.finalizar_ejecucion(ejecucion)
        contexto['pasos'].append({
            'etiqueta': 'Análisis de la base de datos',
            'error': 'No hay ninguna regla de diagnóstico activa, así que no había nada '
                     'que analizar.',
        })
        return render(request, 'pages/usuarios/partials/analisis_global.html', contexto)

    solicitados = list(ejecucion.modulos_solicitados or CLAVES_MODULOS)
    contexto.update({
        'ejecucion': ejecucion,
        'modulos': MODULOS,
        'primer_modulo': solicitados[0] if solicitados else None,
        'etiqueta_primero': ETIQUETA_MODULO.get(solicitados[0]) if solicitados else '',
    })
    return render(request, 'pages/usuarios/partials/analisis_global.html', contexto)


# --------------------------------------------------------------------------
# Perfiles de permisos especiales (25-10-2026). Solo el Administrador.
# --------------------------------------------------------------------------

def perfiles_permisos(request):
    """Lista de perfiles y formulario para crear uno o editar el elegido (?editar=id)."""
    from .forms import PerfilPermisosForm
    from .models import PerfilPermisos
    from .permisos_especiales import PERMISOS, foto_de_asignacion, registrar_cambio_de_perfil

    editando = None
    if request.GET.get('editar') or request.POST.get('pk'):
        editando = get_object_or_404(PerfilPermisos, pk=request.GET.get('editar') or request.POST.get('pk'))
    if request.method == 'POST':
        form = PerfilPermisosForm(request.POST, instance=editando)
        if form.is_valid():
            afectados = list(editando.moderadores.all()) if editando else []
            antes = {m.pk: foto_de_asignacion(m.pk) for m in afectados}
            perfil = form.save()
            # Si cambian los permisos de un perfil en uso, se avisa a quienes lo tienen.
            if editando and form.changed_data:
                for moderador in afectados:
                    antes[moderador.pk]['perfil'] = antes[moderador.pk]['perfil'] + ' (antes del cambio)'
                    moderador.refresh_from_db()
                    registrar_cambio_de_perfil(moderador, antes[moderador.pk])
            messages.success(request, 'Perfil «%s» guardado.' % perfil.nombre)
            return redirect('perfiles_permisos')
    else:
        form = PerfilPermisosForm(instance=editando)
    perfiles = PerfilPermisos.objects.prefetch_related('moderadores').order_by('nombre')
    return render(request, 'pages/usuarios/perfiles_permisos.html', {
        'form': form, 'editando': editando, 'perfiles': perfiles,
        'campos_permisos': [(form[codigo], nombre, ayuda) for codigo, nombre, ayuda in PERMISOS],
    })


@require_POST
def borrar_perfil_permisos(request, pk):
    """Borra el perfil; los Moderadores que lo tenían se quedan sin permisos especiales
    (se les avisa y queda en Auditoría)."""
    from .models import PerfilPermisos
    from .permisos_especiales import foto_de_asignacion, registrar_cambio_de_perfil

    perfil = get_object_or_404(PerfilPermisos, pk=pk)
    moderadores = list(perfil.moderadores.all())
    antes = {m.pk: foto_de_asignacion(m.pk) for m in moderadores}
    CustomUser.objects.filter(pk__in=[m.pk for m in moderadores]).update(
        perfil_permisos=None, perfil_vence=None, perfil_motivo='')
    for moderador in moderadores:
        moderador.refresh_from_db()
        registrar_cambio_de_perfil(moderador, antes[moderador.pk])
    nombre = perfil.nombre
    perfil.delete()
    messages.success(request, 'Perfil «%s» borrado.%s' % (
        nombre, ' %d moderador(es) se quedaron sin permisos especiales.' % len(moderadores) if moderadores else ''))
    return redirect('perfiles_permisos')
