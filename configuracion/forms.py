from django import forms
from .models import Configuracion
from nomencladores.models import NSalario

class ConfiguracionForm(forms.ModelForm):
    
    class Meta:
        model = Configuracion
        fields = (
            'nombre_empresa', 'org_superior', 'rama', 'unidad_presup', 'moneda_local' , 'periodo',
            'fondo_tiempo_calc_tarif' , 'correo', 'telefono', 'direccion', 'logo'
        )
        labels = {
            'nombre_empresa': 'Nombre de la Empresa',
            'org_superior': 'Organismo Superior',
            'rama': 'Rama',
            'unidad_presup': 'Sector',
            'moneda_local': 'Modena Local',
            'periodo': 'Período',
            'fondo_tiempo_calc_tarif': 'Fondo de tiempo para el cálculo',
            'correo': 'Correo',
            'telefono': 'Teléfono',
            'logo': 'Logo',
            'direccion': 'Dirección'
        }
        widgets = {
            'nombre_empresa': forms.TextInput(attrs={'class':'form-control'}),
            'org_superior': forms.TextInput(attrs={'class':'form-control'}),
            'rama': forms.TextInput(attrs={'class': 'form-control'}),
            'unidad_presup': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'moneda_local': forms.TextInput(attrs={'class':'form-control'}),
            'periodo': forms.NumberInput(attrs={'class':'form-control'}),
            'fondo_tiempo_calc_tarif': forms.NumberInput(attrs={'class':'form-control'}),
            'correo': forms.EmailInput(attrs={'class':'form-control'}),
            'telefono': forms.TextInput(attrs={'class':'form-control'}),
            'direccion': forms.TextInput(attrs={'class':'form-control', 'rows' : 3}),
            'logo': forms.FileInput(attrs={'class':'form-control'})           
            
        }
        


