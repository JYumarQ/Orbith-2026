from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'es_admin', 'es_moderador', 'contrato', 'unidades')
        labels = {
            'es_admin': 'Es Administrador',
            'es_moderador': 'Es Moderador'
        }

        widgets = {
            'es_admin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
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

    def clean(self):
        cleaned = super().clean()
    
    #    if cleaned.get('es_admin') and cleaned.get('es_moderador'):
     #       self.add_error('es_moderador', 'No puede ser Administrador y Moderador a la vez.')
        
        return cleaned

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'es_admin', 'es_moderador', 'contrato', 'unidades')

        labels = {
            'es_admin': 'Es Administrador',
            'es_moderador': 'Es Moderador'
        }
        
    def clean_username(self):
        username = self.cleaned_data['username']
        if CustomUser.objects.exclude(pk=self.instance.pk).filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso.")
        return username


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control'})
        self.fields['es_admin'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['es_moderador'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['contrato'].widget.attrs.update({'class': 'form-select'})
        self.fields['unidades'].widget.attrs.update({'class': 'form-select', 'multiple': 'multiple'})

    def clean(self):
        cleaned = super().clean()
    #    if cleaned.get('es_admin') and cleaned.get('es_moderador'):
     #       self.add_error('es_moderador', 'No puede ser Administrador y Moderador a la vez.')
        return cleaned

from django import forms
from django.contrib.auth import get_user_model
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
        new_password1 = self.cleaned_data.get('new_password1')
        # Aquí agregamos las validaciones para la nueva contraseña
        if len(new_password1) < 8:
            raise ValidationError("La nueva contraseña debe tener al menos 8 caracteres.")
        if not any(char.isupper() for char in new_password1):
            raise ValidationError("La nueva contraseña debe tener al menos una letra mayúscula.")
        if not any(char.isdigit() for char in new_password1):
            raise ValidationError("La nueva contraseña debe tener al menos un número.")
#        if not any(char in "!@#$%^&*()-_+=<>?/" for char in new_password1):
#            raise ValidationError("La nueva contraseña debe tener al menos un carácter especial.")
        return new_password1

    def clean_new_password2(self):
        new_password1 = self.cleaned_data.get('new_password1')
        new_password2 = self.cleaned_data.get('new_password2')
        if new_password1 != new_password2:
            raise ValidationError("Las contraseñas no coinciden.")
        return new_password2

