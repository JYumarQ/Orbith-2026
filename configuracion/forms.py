from django import forms
from .models import Configuracion
from nomencladores.models import NProvincia

class ConfiguracionForm(forms.ModelForm):
    # Campo adicional (se guarda en la BD)
    provincia_entidad = forms.ModelChoiceField(
        queryset=NProvincia.objects.all().order_by('nombre'),
        required=False,
        empty_label="---------",
        label="Provincia Entidad",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Configuracion
        fields = (
            'nombre_empresa', 'org_superior', 'reup', 'rama', 'unidad_presup', 'moneda_local', 'periodo',
            'fondo_tiempo_calc_tarif', 'porcentaje_horas_extras', 'correo', 'telefono', 'direccion', 'logo',
            'provincia_entidad'  # ← AÑADIDO
        )
        labels = {
            'nombre_empresa': 'Nombre de la Empresa',
            'org_superior': 'Organismo',
            'reup': 'REUP',
            'rama': 'Rama',
            'unidad_presup': 'Sector',
            'moneda_local': 'Moneda Local',
            'periodo': 'Período',
            'fondo_tiempo_calc_tarif': 'Fondo de tiempo para el cálculo',
            'correo': 'Correo',
            'telefono': 'Teléfono',
            'logo': 'Logo',
            'direccion': 'Dirección',
            'provincia_entidad': 'Provincia Entidad',  # ← AÑADIDO
        }
        widgets = {
            'nombre_empresa': forms.TextInput(attrs={'class': 'form-control'}),
            'org_superior': forms.TextInput(attrs={'class': 'form-control'}),
            'reup': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': '15',
                'pattern': '[0-9-]*',
                'title': 'Solo números y guiones (-).',
            }),
            'rama': forms.TextInput(attrs={'class': 'form-control'}),
            'unidad_presup': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'moneda_local': forms.TextInput(attrs={'class': 'form-control'}),
            'periodo': forms.NumberInput(attrs={'class': 'form-control'}),
            'fondo_tiempo_calc_tarif': forms.NumberInput(attrs={'class': 'form-control'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control', 'rows': 3}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'porcentaje_horas_extras': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            
        }