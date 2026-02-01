from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, View
from .models import CustomUser
from .forms import CustomUserCreationForm, CustomUserChangeForm, CustomPasswordChangeForm
from django.views.generic.edit import FormView
from django.urls import reverse_lazy
from django.db.models import Q
from django.contrib.auth import get_user_model, update_session_auth_hash

class UsuarioListView(ListView):
    model = CustomUser
    template_name = "pages/usuarios/list_usuarios.html"

    def get_queryset(self):
        # Excluye al usuario con username "superadmin"
        return CustomUser.objects.exclude(username='admin').order_by('username')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CustomUserCreationForm()  
        return context


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

class CustomUserCreateView(CreateView):
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

class CustomUserUpdateView(UpdateView):
    model = CustomUser
    form_class = CustomUserChangeForm
    template_name = 'pages/usuarios/updt_usuario.html'
    success_url = reverse_lazy('list_usuarios')

    def form_valid(self, form):
        user = form.save()
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'form_is_valid': True,  # <-- usa la misma clave que en create
                'message': 'Usuario actualizado correctamente',
                'es_admin': user.es_admin,
                'es_moderador': user.es_moderador,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            })
        messages.success(self.request, 'Usuario actualizado correctamente')
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

class CambiarPasswordView(FormView):
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

class CustomUserDeleteView(DeleteView):
    def get(self, request, *args, **kwargs):
        usuario = get_object_or_404(CustomUser, pk=kwargs['pk'])
        usuario.delete()
        messages.success(request, f'Usuario "{usuario.username}" eliminado correctamente.')
        return redirect('list_usuarios')
    