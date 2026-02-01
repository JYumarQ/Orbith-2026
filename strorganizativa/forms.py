from cProfile import label
from dataclasses import fields
from pyexpat import model
from django import forms
from django.forms import widgets
from .models import CargoPlantilla, Departamento, UnidadOrganizativa

#CARGO
class CargoPlantillaForm(forms.ModelForm):
    unidad = forms.ModelChoiceField(
        label='Unidad Organizativa',
        queryset=UnidadOrganizativa.objects.all(),   # ⬅️ antes: .none()
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': '/estructuras/cargar_dptos/',
            'hx-target': '#id_departamento',
            'hx-trigger': 'change',
            'hx-swap': 'innerHTML',
        })
    )
    
    class Meta:
        model = CargoPlantilla
        fields = ('ncargo', 'departamento', 'rol', 'cant_aprobada', 'cant_cubierta', 'activo')
        labels = {
            'ncargo': 'Cargo', 
            'departamento': 'Departamento', 
            'rol': 'Rol', 
            'cant_aprobada': 'Cantidad Aprobada', 
            'cant_cubierta': 'Cantidad Cubierta', 
            'activo': 'Activo'
        }
        widgets = {
            'ncargo': forms.Select(attrs={
                'class':'form-select js-cargo-select', 
                'id':'id_ncargo',
                'style': 'width: 100%'
            }),
            'departamento': forms.Select(attrs={'class':'form-select'}),
            'rol': forms.Select(attrs={'class':'form-select', 'id':'id_rol'}),
            'cant_aprobada': forms.NumberInput(attrs={'class': 'form-control'}),
            'cant_cubierta': forms.NumberInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class':'form-check-input'})
        }
    
    # strorganizativa/forms.py (Corregido)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # 1) Restringe por usuario (si aplica)
        # 1) Restringe por usuario (Solo si NO es superusuario)
        if user:
            if not user.is_superuser:
                # Si es usuario normal, filtra por sus unidades asignadas
                permitidas = user.unidades.all()
                self.fields['unidad'].queryset = permitidas if permitidas.exists() else UnidadOrganizativa.objects.all()
            else:
                # Si es superusuario, muestra TODAS (esto arregla tu problema)
                self.fields['unidad'].queryset = UnidadOrganizativa.objects.all()

        # 2) Cascada unidad → departamento (GET/POST)
        if 'unidad' in self.data:
            try:
                unidad_id = int(self.data.get('unidad'))
                self.fields['departamento'].queryset = (
                    Departamento.objects.filter(unidad_organizativa_id=unidad_id).order_by('descripcion')
                )
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and getattr(self.instance, 'departamento', None):
            # Editar: precargar unidad y departamentos de esa unidad
            self.fields['unidad'].initial = self.instance.departamento.unidad_organizativa
            self.fields['departamento'].queryset = (
                self.instance.departamento.unidad_organizativa.departamento_set.all().order_by('descripcion')
            )
        else:
            self.fields['departamento'].queryset = Departamento.objects.none()



        
#DEPARTAMENTO
class DepartamentoForm(forms.ModelForm):
    class Meta:
        model = Departamento
        fields = ('descripcion', 'unidad_organizativa')
        label ={
            'descripcion': 'Descripción', 
            'unidad_organizativa': 'Unidad Organizativa'
        }
        widgets={
            'descripcion': forms.TextInput(attrs={'class':'form-control'}), 
            'unidad_organizativa': forms.Select(attrs={'class':'form-control'})
        }

    def __init__(self, *args, user = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        
        # LOGICA CORREGIDA: Acceso total para admin
        if user:
            if user.is_superuser:
                self.fields['unidad_organizativa'].queryset = UnidadOrganizativa.objects.all()
            elif hasattr(user, 'unidades'):
                self.fields['unidad_organizativa'].queryset = user.unidades.all()
            else:
                self.fields['unidad_organizativa'].queryset = UnidadOrganizativa.objects.none()


#UNIDAD ORGANIZATIVA
class UnidadOrganizativaForm(forms.ModelForm):
    class Meta:
        model = UnidadOrganizativa
        fields = ('grupo_nomina', 'descripcion', 'tipo')
        label = {
            'grupo_nomina': 'Grupo de Nómina',
            'descripcion': 'Descripción',
            'tipo': 'Tipo'
        }
        widgets = {
            'grupo_nomina': forms.NumberInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo':forms.Select(attrs={'class':'form-control'})
        }
        