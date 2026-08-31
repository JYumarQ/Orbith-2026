from django import forms

from .models import ReporteProblema


class ReporteProblemaForm(forms.ModelForm):
    """Formulario del botón "Reportar problema".

    Las imágenes NO van aquí: Django no admite varios ficheros en un mismo
    ImageField. Se procesan a mano en la vista con request.FILES.getlist().
    """

    LONGITUD_MINIMA = 15

    class Meta:
        model = ReporteProblema
        fields = ('mensaje', 'error_consola')
        labels = {
            'mensaje': 'Describa el problema',
            'error_consola': 'Error de consola (F12)',
        }
        widgets = {
            'mensaje': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Explique qué ocurrió, en qué pantalla y qué esperaba que sucediera.',
            }),
            'error_consola': forms.Textarea(attrs={
                'class': 'form-control font-monospace',
                'rows': 4,
                'style': 'font-size: .8125rem;',
                'placeholder': 'Pegue aquí el texto exacto del error, si lo vio en la consola.',
            }),
        }

    def clean_mensaje(self):
        mensaje = (self.cleaned_data.get('mensaje') or '').strip()
        if len(mensaje) < self.LONGITUD_MINIMA:
            raise forms.ValidationError(
                f"Describa el problema con algo más de detalle "
                f"(al menos {self.LONGITUD_MINIMA} caracteres)."
            )
        return mensaje

    def clean_error_consola(self):
        return (self.cleaned_data.get('error_consola') or '').strip()


class AyudaAccesoForm(forms.ModelForm):
    """Reporte enviado desde el login por alguien que NO ha podido entrar.

    Es deliberadamente más pobre que `ReporteProblemaForm`: solo dos campos de
    texto y ninguna imagen. El motivo es de seguridad, no de pereza: esta vista
    es la única de todo Orbith que acepta datos de alguien sin autenticar, así
    que no puede permitir subir ficheros al servidor —cualquiera en la red
    llenaría el disco en minutos— ni ofrecer campos que no hagan falta.
    """

    LONGITUD_MINIMA = 15

    usuario_declarado = forms.CharField(
        max_length=150,
        label="Su usuario de red",
        widget=forms.TextInput(attrs={
            'class': 'floating-input',
            'placeholder': 'Su usuario de red',
            'autocapitalize': 'none',
            'autocomplete': 'username',
        }),
        error_messages={'required': "Indique su usuario de red para poder ayudarle."},
    )

    class Meta:
        model = ReporteProblema
        fields = ('usuario_declarado', 'mensaje')
        widgets = {
            'mensaje': forms.Textarea(attrs={
                'class': 'floating-input',
                'rows': 4,
                'placeholder': 'Explique qué ocurre al intentar entrar (mensaje que ve, desde cuándo...).',
            }),
        }

    def clean_usuario_declarado(self):
        return (self.cleaned_data.get('usuario_declarado') or '').strip()

    def clean_mensaje(self):
        mensaje = (self.cleaned_data.get('mensaje') or '').strip()
        if len(mensaje) < self.LONGITUD_MINIMA:
            raise forms.ValidationError(
                f"Describa el problema con algo más de detalle "
                f"(al menos {self.LONGITUD_MINIMA} caracteres)."
            )
        return mensaje
