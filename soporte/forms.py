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
