from cProfile import label
from dataclasses import fields
from pyexpat import model
from django import forms
from django.forms import widgets
from .models import NCargo, NGrupoEscala, NRol, NTridente, NTipoUnidadOrganizativa, NTipoFamilia, NFamiliaCargo
from django.db.models import Count
from django.urls import reverse_lazy


#CARGO
class NCargoForm(forms.ModelForm):
    
    class Meta:
        model = NCargo
        fields = ('descripcion', 'cat_ocupacional', 'grupo_escala', 'salario_basico')
        labels = {
            'descripcion': 'Descripción', 
            'cat_ocupacional': 'Cat. Ocup.', 
            'grupo_escala': 'Gpo. Escala', 
            'salario_basico': 'Salario'
        }
        widgets = {
            'descripcion': forms.TextInput(attrs={'class':'form-control'}), 
            'cat_ocupacional': forms.Select(attrs={'class':'form-select'}), 
            'grupo_escala': forms.Select(attrs={'class':'form-select'}), 
            'salario_basico': forms.NumberInput(attrs={'class':'form-control'})
        }
        
class NGrupoEscalaForm(forms.ModelForm):
    class Meta:
        model = NGrupoEscala
        fields = ('nivel', 'es_cuadro', 'tiene_rol', 'roles')
        widgets = {
            'nivel': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: I, II, XIX...'}),
            'es_cuadro': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'tiene_rol': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'roles': forms.CheckboxSelectMultiple(attrs={'class': 'list-unstyled d-flex flex-wrap gap-3'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ordenamos los roles alfabéticamente
        self.fields['roles'].queryset = NRol.objects.all().order_by('tipo')
        
        # NUEVO: Si el grupo es nuevo (no tiene ID aún), marcamos todos los roles por defecto
        if not self.instance.pk:
            self.fields['roles'].initial = NRol.objects.all()
        
class RegistrarSalariosForm(forms.Form):
    grupo_escala = forms.ModelChoiceField(
        queryset=NGrupoEscala.objects.none(),
        label="Grupo Escala",
        empty_label="Seleccione un Grupo...",
        widget=forms.Select(attrs={
            'class': 'form-select select2'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Obtener solo los grupos de escala que no tienen las 9 combinaciones completas
        used_groups = NGrupoEscala.objects.annotate(
            salario_count=Count('nsalario')
        ).filter(salario_count__gte=9)
        
        # 1. Obtener el queryset filtrado (exactamente como estaba)
        queryset_filtrado = NGrupoEscala.objects.annotate(
            num_salarios=Count('nsalario')
        ).filter(num_salarios=0)
        
        # 2. ¡NUEVO! Convertir a lista y ordenar en Python usando tu helper del modelo
        lista_ordenada = sorted(list(queryset_filtrado), key=lambda g: g.valor_numerico)
        
        # 3. Asignar el queryset (para validación) y las choices ordenadas (para display)
        self.fields['grupo_escala'].queryset = queryset_filtrado
        self.fields['grupo_escala'].choices = [(g.pk, str(g)) for g in lista_ordenada]


class ImportarCargosForm(forms.Form):
    archivo_excel = forms.FileField(
        label="Seleccionar Excel de Cargos",
        help_text="El archivo debe tener una hoja llamada 'CARGOS_CODIGO' o ser la primera hoja."
    )
    
    ESTRATEGIA_CHOICES = [
        ('SALTAR', 'Saltar duplicados (Conservar los datos actuales de la BD)'),
        ('ACTUALIZAR', 'Sobrescribir todo (Actualizar la BD con los datos del Excel)'),
    ]
    
    estrategia = forms.ChoiceField(
        label="Si el cargo ya existe...",
        choices=ESTRATEGIA_CHOICES,
        widget=forms.RadioSelect,
        initial='SALTAR'
    )

# Agregar esto al final de forms.py

class EditarSalariosForm(forms.Form):
    # Campo oculto o de solo lectura para mostrar qué grupo estamos editando
    grupo_nombre = forms.CharField(
        label="Grupo Escala",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'})
    )
    

    def __init__(self, *args, **kwargs):
        # Recibimos el nombre del grupo para mostrarlo
        grupo_label = kwargs.pop('grupo_label', '')
        super().__init__(*args, **kwargs)
        self.fields['grupo_nombre'].initial = grupo_label

class NTipoUnidadOrganizativaForm(forms.ModelForm):
    class Meta:
        model = NTipoUnidadOrganizativa
        fields = ['descripcion', 'es_temporal', 'es_principal', 'es_subunidad', 'color']
        widgets = {
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'es_temporal': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_principal': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'check_principal'}),
            'es_subunidad': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'check_subunidad'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'id': 'input_color'}),
        }


class NTipoFamiliaForm(forms.ModelForm):
    class Meta:
        model = NTipoFamilia
        fields = ['nombre']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Especialidades, Grupos de Reporte...'}),
        }

class NFamiliaCargoForm(forms.ModelForm):
    class Meta:
        model = NFamiliaCargo
        fields = ['nombre', 'descripcion', 'tipo_familia']