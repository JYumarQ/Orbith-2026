import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, View
from .models import CustomUser
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm, CustomPasswordChangeForm,
    CustomAuthenticationForm, AvatarForm,
)

logger = logging.getLogger(__name__)
from django.views.generic.edit import FormView
from django.urls import reverse_lazy
from django.db.models import Q
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from core.mixins import AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin

class UsuarioListView(LoginRequiredMixin, ListView):
    model = CustomUser
    template_name = "pages/usuarios/list_usuarios.html"

    def get_queryset(self):
        # Excluye al usuario con username "superadmin"
        return CustomUser.objects.exclude(username='admin').order_by('username')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CustomUserCreationForm()  
        return context

@login_required
def search_usuarios(request):
    query = request.GET.get('filter_usuario', '')
    
    results = CustomUser.objects.filter(
        Q(username__icontains=query)|
        Q(contrato__aspirante__nombre__icontains=query)|
        Q(contrato__aspirante__papellido__icontains=query)|
        Q(contrato__aspirante__sapellido__icontains=query)
    ).exclude(username='admin').order_by('username')
    return render(request, 'pages/usuarios/partials/filter_usuarios_list.html', {'usuarios':results})

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
        user = form.save(commit=False)
        user.save()
        form.save_m2m()
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
        user = form.save()
        self.object = user
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
    template_name = 'pages/usuarios/partials/cambiar_password_form.html'
    form_class = CustomPasswordChangeForm
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user'] = self.get_user()
        return context

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
        print(f"[DEBUG] Cambiando contraseña al usuario: {user.username} (ID: {user.id})")
        user.set_password(form.cleaned_data['new_password1'])  # Establecer nueva contraseña
        user.save()  # Guardar el usuario con la nueva contraseña
        update_session_auth_hash(self.request, user)  # Mantener la sesión activa
        
        messages.success(self.request, 'Contraseña cambiada exitosamente.')

        # Si la petición es AJAX, devolvemos una respuesta JSON
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'form_is_valid': True,
                'message': 'Contraseña cambiada exitosamente.'
            })

        # Si no es AJAX, redirigimos al listado de usuarios
        return redirect('list_usuarios')

    def form_invalid(self, form):
        """
        Si el formulario no es válido, devolvemos los errores y el formulario.
        """
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'form_is_valid': False,
                'html_form': self.render_to_string(self.template_name, {'form': form})
            }, status=400)

        return self.render_to_response(self.get_context_data(form=form))

class CustomUserDeleteView(LoginRequiredMixin, DeleteView):
    def get(self, request, *args, **kwargs):
        usuario = get_object_or_404(CustomUser, pk=kwargs['pk'])
        usuario.delete()
        messages.success(request, f'Usuario "{usuario.username}" eliminado correctamente.')
        return redirect('list_usuarios')
    

class CustomLoginView(LoginView):
    form_class = CustomAuthenticationForm
    template_name = 'registration/login.html'


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

    campos = []
    if sidebar is not None:
        preferencias.sidebar_colapsada = sidebar
        campos.append('sidebar_colapsada')
    if animaciones is not None:
        preferencias.animaciones_activas = animaciones
        campos.append('animaciones_activas')

    if not campos:
        return JsonResponse({'exito': False, 'mensaje': 'No se recibió ninguna preferencia.'}, status=400)

    preferencias.save(update_fields=campos + ['fecha_actualizado'])

    return JsonResponse({
        'exito': True,
        'mensaje': 'Preferencias guardadas.',
        'sidebar_colapsada': preferencias.sidebar_colapsada,
        'animaciones_activas': preferencias.animaciones_activas,
    })