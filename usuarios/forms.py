from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils import timezone
import math

from .models import CustomUser, IntentoAcceso, PreferenciasUsuario
from django.contrib.auth.forms import AuthenticationForm
from contratos.models import CAlta
from core.validators import validar_imagen


def validar_moderador_unico(formulario, cleaned):
    """Una Unidad Organizativa solo puede tener UN moderador.

    Regla global del negocio: un moderador puede llevar varias unidades, pero
    cada unidad tiene un único moderador responsable (más todos los
    administradores, que deciden sobre cualquiera de ellas por su rol y no por
    esta relación).

    Vive en una función suelta, y no en `CustomUser.clean()`, porque la relación
    `unidades` es ManyToMany: hasta que el usuario no está guardado no hay filas
    que consultar, así que el único punto donde se puede comprobar antes de
    escribir es el formulario, con los datos aún en `cleaned_data`.
    """
    if not cleaned.get('es_moderador'):
        return cleaned

    unidades = cleaned.get('unidades')
    if not unidades:
        return cleaned

    ocupadas = (CustomUser.objects
                .filter(es_moderador=True, unidades__in=unidades)
                .exclude(pk=formulario.instance.pk)
                .values_list('unidades__descripcion', 'username')
                .distinct())
    # `unidades__in` cruza con TODAS las unidades del otro moderador, no solo con
    # las del choque: hay que quedarse con las que se están intentando asignar.
    nombres = {u.descripcion for u in unidades}
    choques = sorted({f'{d} (ya la lleva {u})'
                      for d, u in ocupadas if d in nombres})
    if choques:
        formulario.add_error(
            'unidades',
            'Cada Unidad Organizativa solo puede tener un moderador. '
            'Ya tienen uno asignado: ' + '; '.join(choques) + '.')
    return cleaned


class CustomUserCreationForm(UserCreationForm):

    contrato = forms.ModelChoiceField(
        queryset=CAlta.objects.all().order_by('aspirante__nombre', 'aspirante__papellido'),
        widget=forms.Select(attrs={'class': 'form-select select2', 'data-placeholder': 'Buscar contrato...'}),
        label='Contrato',
        required=False
    )
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'es_admin', 'es_moderador', 'es_observador', 'contrato', 'unidades', 'is_active')
        labels = {
            'es_admin': 'Es Administrador',
            'es_moderador': 'Es Moderador',
            'es_observador': 'Es Observador',
            'is_active': 'Activo'
        }

        widgets = {
            'es_admin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_moderador': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_observador': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),

            'unidades': forms.SelectMultiple(attrs={'class': 'form-select select2', 'data-placeholder': 'Buscar unidades...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'

            if 'password' in field_name:
                field.widget.attrs['type'] = 'password'

        self.fields['contrato'].label_from_instance = lambda obj: (
            f"{obj.aspirante.nombre} {obj.aspirante.papellido} {obj.aspirante.sapellido}".strip()
        )

    def clean(self):
        cleaned = super().clean()
        return validar_moderador_unico(self, cleaned)

class CustomUserChangeForm(UserChangeForm):

    contrato = forms.ModelChoiceField(
        queryset=CAlta.objects.all().order_by('aspirante__nombre', 'aspirante__papellido'),
        widget=forms.Select(attrs={'class': 'form-select select2', 'data-placeholder': 'Buscar contrato...'}),
        label='Contrato',
        required=False
    )
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'es_admin', 'es_moderador', 'es_observador', 'contrato', 'unidades', 'is_active')

        labels = {
            'es_admin': 'Es Administrador',
            'es_moderador': 'Es Moderador',
            'es_observador': 'Es Observador',
            'is_active': 'Activo'
        }

    def clean_username(self):
        username = self.cleaned_data['username']
        if CustomUser.objects.exclude(pk=self.instance.pk).filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso.")
        return username


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control'})
        self.fields['email'].widget.attrs.update({'class': 'form-control'})
        self.fields['es_admin'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['es_moderador'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['es_observador'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['is_active'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['contrato'].widget.attrs.update({'class': 'form-select select2', 'data-placeholder': 'Buscar contrato...'})
        self.fields['unidades'].widget.attrs.update({'class': 'form-select select2', 'data-placeholder': 'Buscar unidades...'})
        self.fields['contrato'].label_from_instance = lambda obj: (
            f"{obj.aspirante.nombre} {obj.aspirante.papellido} {obj.aspirante.sapellido}".strip()
        )
        

    def clean(self):
        cleaned = super().clean()
        return validar_moderador_unico(self, cleaned)

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()

class CustomPasswordChangeForm(forms.Form):
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label='Nueva contraseña'
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label='Confirmar nueva contraseña'
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)  # Si necesitas usar el usuario
        super().__init__(*args, **kwargs)

    def clean_new_password1(self):
        """Aplica AUTH_PASSWORD_VALIDATORS: las MISMAS reglas que el alta de
        usuario y el panel de administración de Django.

        Antes aquí vivían tres comprobaciones escritas a mano (8 caracteres,
        una mayúscula y un dígito) que se saltaban la lista de contraseñas
        comunes y el parecido con el nombre de usuario. El resultado era que
        este formulario ACEPTABA claves que el alta rechazaba: `Password1`
        cumple las tres y es de las contraseñas más usadas del mundo.

        Se pasa `self.user` —el usuario al que se le cambia la clave, que no es
        necesariamente quien está rellenando el formulario— para que el
        validador de parecido compare contra los datos correctos.
        """
        password = self.cleaned_data.get('new_password1')
        validate_password(password, self.user)
        return password

    def clean_new_password2(self):
        new_password1 = self.cleaned_data.get('new_password1')
        new_password2 = self.cleaned_data.get('new_password2')
        if new_password1 != new_password2:
            raise ValidationError("Las contraseñas no coinciden.")
        return new_password2

class AvatarForm(forms.ModelForm):
    """Subida o cambio de la foto de perfil del propio usuario."""

    TAMANO_MAXIMO_MB = 2

    # El campo se declara a mano para poder traducir los mensajes de Django.
    # El proyecto tiene LANGUAGE_CODE = 'en-us', así que los textos por defecto
    # ("Upload a valid image...") saldrían en inglés.
    avatar = forms.ImageField(
        required=True,
        label='Foto de perfil',
        error_messages={
            'required': "Debe seleccionar una imagen.",
            'invalid': "El archivo seleccionado no es una imagen válida.",
            'invalid_image': (
                "El archivo seleccionado no es una imagen válida o está dañado. "
                "Use una imagen JPG, PNG o WEBP."
            ),
            'missing': "No se recibió ningún archivo.",
            'empty': "El archivo enviado está vacío.",
        },
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg,image/png,image/webp',
        })
    )

    class Meta:
        model = CustomUser
        fields = ('avatar',)

    def clean_avatar(self):
        return validar_imagen(self.cleaned_data.get('avatar'), self.TAMANO_MAXIMO_MB)


class PreferenciasUsuarioForm(forms.ModelForm):
    """Preferencias personales de interfaz."""

    class Meta:
        model = PreferenciasUsuario
        fields = ('sidebar_colapsada', 'animaciones_activas')
        widgets = {
            'sidebar_colapsada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'animaciones_activas': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CustomAuthenticationForm(AuthenticationForm):
    """Formulario del login de Orbith.

    Añade sobre el de Django tres cosas, en este orden:

    1. **Bloqueo por intentos fallidos**, ANTES de comprobar la contraseña. Si la
       cuenta está bloqueada no se llama siquiera a `authenticate()`, así que un
       ataque por fuerza bruta deja de consumir tiempo de servidor y de sumar
       fallos nuevos.
    2. Que el usuario tenga un rol asignado.
    3. Que, si Orbith está en mantenimiento, solo entren los Administradores.

    El bloqueo real lo aplica `usuarios.backends.BackendConBloqueo`, que cubre
    también `/admin/login/`. Aquí se repite la comprobación con un único fin:
    poder EXPLICAR al usuario por qué no entra, en lugar de dejarle con un
    "usuario o contraseña incorrectos" que no le dice nada.
    """

    error_messages = {
        'invalid_login': 'Usuario o contraseña incorrectos. Recuerde que ambos campos distinguen mayúsculas y minúsculas.',
        'inactive': 'Esta cuenta está desactivada.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Los atributos se ponen aquí, y no a mano en la plantilla, para que el
        # formulario siga siendo la única fuente de verdad: la plantilla ya
        # dibuja `{{ form.username }}` y `{{ form.password }}`.
        self.fields['username'].widget.attrs.update({
            'class': 'floating-input',
            'placeholder': 'Usuario de red',
            'autofocus': True,
            # Sin esto, el teclado del móvil pone mayúscula inicial y el login
            # falla por el mismo motivo que advierte el mensaje de error.
            'autocapitalize': 'none',
            'autocorrect': 'off',
            'spellcheck': 'false',
            # Deja que el gestor de contraseñas del navegador rellene y guarde.
            'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            'class': 'floating-input',
            'placeholder': 'Contraseña',
            'autocomplete': 'current-password',
            # Lo usa el botón de "ver contraseña" de la plantilla.
            'id': 'id_password',
        })

    def clean(self):
        username = self.cleaned_data.get('username')

        if username:
            bloqueado_hasta = IntentoAcceso.bloqueado_hasta(username)
            if bloqueado_hasta:
                restante = bloqueado_hasta - timezone.now()
                minutos = max(1, math.ceil(restante.total_seconds() / 60))
                raise ValidationError(
                    f"Demasiados intentos fallidos. Por seguridad, esta cuenta "
                    f"no admite más intentos durante {minutos} minuto"
                    f"{'s' if minutos != 1 else ''}. Si no recuerda su "
                    f"contraseña, avise al Administrador.",
                    code='cuenta_bloqueada',
                )

        cleaned_data = super().clean()
        user = self.get_user()

        if user is not None:
            # Verificar que el usuario tenga al menos un rol activo
            if not (user.es_admin or user.es_moderador or user.es_observador):
                raise ValidationError(
                    "Tu usuario no tiene un rol asignado. Contacta al administrador.",
                    code='invalid_login'
                )

            # Modo de mantenimiento: solo los Administradores pueden entrar.
            # Reutiliza el mismo singleton que usuarios.middleware.ControlAccesoMiddleware.
            from configuracion.models import Configuracion
            if not user.es_admin:
                config = Configuracion.objects.first()
                if config and config.modo_mantenimiento:
                    raise ValidationError(
                        "Orbith se encuentra temporalmente en mantenimiento. "
                        "Por favor, intenta iniciar sesión más tarde.",
                        code='invalid_login'
                    )

        return cleaned_data
