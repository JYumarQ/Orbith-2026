from cProfile import label
from dataclasses import fields
from pyexpat import model
from django import forms
from django.forms import widgets
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from nomencladores.models import NTipoUnidadOrganizativa


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
        fields = ('ncargo', 'departamento', 'rol', 'nivel_preparacion', 'cant_aprobada', 'cant_cubierta', 'activo')
        labels = {
            'ncargo': 'Cargo', 
            'departamento': 'Departamento', 
            'rol': 'Rol', 
            'nivel_preparacion': 'Nivel de Preparación',
            'cant_aprobada': 'Cantidad Aprobada', 
            'cant_cubierta': 'Cantidad Cubierta', 
            'activo': ' Estado(Automático)',
        }
        widgets = {
            'ncargo': forms.Select(attrs={
                'class':'form-select js-cargo-select', 
                'id':'id_ncargo',
                'style': 'width: 100%'
            }),
            'departamento': forms.Select(attrs={'class':'form-select'}),
            'rol': forms.Select(attrs={'class':'form-select', 'id':'id_rol'}),
            'nivel_preparacion': forms.Select(attrs={'class':'form-select', 'id':'id_nivel_preparacion'}),
            'cant_aprobada': forms.NumberInput(attrs={'class': 'form-control'}),
            'cant_cubierta': forms.NumberInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class':'form-check-input', 'disabled': 'disabled', 'id': 'id_activo'}),
            
        }
    
    # strorganizativa/forms.py (Corregido)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['ncargo'].queryset = self.fields['ncargo'].queryset.order_by('descripcion')

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

    
    def clean(self):
        cleaned_data = super().clean()
        ncargo = cleaned_data.get('ncargo')
        rol = cleaned_data.get('rol')
        
        if ncargo:
            # 1. Definimos qué es un Cuadro según tu base de datos
            categorias_cuadro = ['CEJ', 'CDI', 'Cuadro Ejecutivo', 'Cuadro Directivo', 'Cuadro']
            es_cuadro = (ncargo.cat_ocupacional in categorias_cuadro or 
                         ncargo.get_cat_ocupacional_display() in categorias_cuadro)

            # 2. Si NO es cuadro y lo dejaron vacío, lanzamos el error
            if not es_cuadro and not rol:
                raise forms.ValidationError({'rol': f'El cargo "{ncargo.descripcion}" debe tener un Rol asignado (Ej: Decisorio, Fundamental, Apoyo...).'})
            
            # 3. Si SÍ es cuadro, nos aseguramos de que el rol quede en blanco aunque el usuario haya intentado mandar uno
            if es_cuadro and rol:
                cleaned_data['rol'] = None

        return cleaned_data


        
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
    
    tipo = forms.ModelChoiceField(
        queryset=NTipoUnidadOrganizativa.objects.all(),
        empty_label="Seleccione un tipo...",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo'}),
        label="Tipo de Unidad"
    )
    # NUEVO: Selector de Unidad Principal (Aparecerá en el orden 2)
    padre = forms.ModelChoiceField(
        queryset=UnidadOrganizativa.objects.none(), # Lo llenamos dinámicamente en el __init__
        empty_label="Seleccione la Unidad Principal...",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_padre'}),
        label="Unidad Principal Asociada"
    )

    class Meta:
        model = UnidadOrganizativa
        # ORDEN SOLICITADO: Tipo -> Padre -> Descripcion -> Nomina
        fields = ['tipo', 'padre', 'descripcion', 'grupo_nomina'] 
        labels = {
            'grupo_nomina': 'Grupo de Nómina',
            'descripcion': 'Descripción',
        }
        widgets = {
            'grupo_nomina': forms.NumberInput(attrs={'class': 'form-control', 'id': 'id_grupo_nomina'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Dirección de Recursos Humanos'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtramos para que solo salgan las Unidades Principales reales
        qs = UnidadOrganizativa.objects.filter(tipo__es_principal=True)
        # Si estamos editando, nos excluimos a nosotros mismos para evitar bucles (ser tu propio padre)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        
        self.fields['padre'].queryset = qs
        