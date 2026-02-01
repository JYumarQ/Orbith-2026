from cProfile import label
from dataclasses import fields
from pyexpat import model
from django import forms
from django.forms import widgets
from .models import NCargo, NGrupoEscala, NRol, NTridente
from django.db.models import Count


#CARGO
class NCargoForm(forms.ModelForm):
    
    class Meta:
        model = NCargo
        fields = ('descripcion', 'cat_ocupacional', 'grupo_escala', 'salario_basico', 'activo')
        labels = {
            'descripcion': 'Descripción', 
            'cat_ocupacional': 'Cat. Ocup.', 
            'grupo_escala': 'Gpo. Escala', 
            'salario_basico': 'Salario', 
            'activo': 'Activo'
        }
        widgets = {
            'descripcion': forms.TextInput(attrs={'class':'form-control'}), 
            'cat_ocupacional': forms.Select(attrs={'class':'form-select'}), 
            'grupo_escala': forms.Select(attrs={'class':'form-select'}), 
            'salario_basico': forms.NumberInput(attrs={'class':'form-control'}), 
            'activo': forms.CheckboxInput()
        }
        
class NGrupoEscalaForm(forms.ModelForm):
    
    class Meta:
        model = NGrupoEscala
        fields = ('nivel', 'es_cuadro')
        labels = {
            'es_cuadro': 'Es Cuadro'
        }
        widgets = {
            'nivel': forms.TextInput(attrs={'class': 'form-control'}),
            'es_cuadro': forms.CheckboxInput()
        }
        
class RegistrarSalariosForm(forms.Form):
    grupo_escala = forms.ModelChoiceField(
        queryset=NGrupoEscala.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Grupo Escala"
    )
    es_para_cuadro = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-control'}),
        label="Salario para Cuadro"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Obtener solo los grupos de escala que no tienen las 9 combinaciones completas
        used_groups = NGrupoEscala.objects.annotate(
            salario_count=Count('nsalario')
        ).filter(salario_count__gte=9)
        
        # 1. Obtener el queryset filtrado (exactamente como estaba)
        queryset_filtrado = NGrupoEscala.objects.exclude(
            id__in=used_groups.values_list('id', flat=True)
        )
        
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