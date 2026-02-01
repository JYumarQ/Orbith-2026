from typing import cast
from django import forms
from django.forms import ModelChoiceField
from django.urls import reverse, reverse_lazy
from .models import Aspirante
from nomencladores.models import NEspecialidad, NMunicipio

class AspiranteForm(forms.ModelForm):
    # Nivel educacional dispara la carga de especialidades por HTMX
    nivel_educ = forms.ChoiceField(
        label='Nivel Educacional',
        choices=Aspirante._meta.get_field('nivel_educ').choices,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': reverse_lazy('cargar_esp'),     # seguro en import-time
            'hx-target': '#id_especialidad',
            'hx-trigger': 'change'
        })
    )

    # Se llena dinámicamente según nivel_educ
    especialidad = forms.ModelChoiceField(
        label='Especialidad',
        queryset=NEspecialidad.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_especialidad',
            'disabled': 'disabled'
        })
    )

    class Meta:
        model = Aspirante
        fields = (
            'doc_identidad', 'sexo', 'nombre', 'papellido', 'sapellido',
            'movil_personal', 'fijo_personal', 'direccion',
            'provincia', 'municipio', 'codigo_postal',
            'raza', 'grado_cientifico', 'tpantalon', 'tcamisa', 'tzapatos',
            'nivel_educ', 'especialidad',
        )

        labels = {
            'doc_identidad': 'Doc. de Identidad',
            'sexo': 'Sexo',
            'nombre': 'Nombre',
            'papellido': 'Primer Apellido',
            'sapellido': 'Segundo Apellido',
            'movil_personal': 'Móvil',
            'fijo_personal': 'Teléfono Fijo',
            'direccion': 'Dirección',
            'municipio': 'Municipio',
            'provincia': 'Provincia',
            'codigo_postal': 'Código Postal',
            
            'raza': 'Raza',
            'grado_cientifico': 'Grado Científico',
            
            'tpantalon': 'Pantalón/Falda',
            'tcamisa': 'Camisa/Blusa',
            'tzapatos': 'Zapatos',
        }

        widgets = {
            'doc_identidad': forms.TextInput(attrs={'class':'form-control'}),
            'sexo': forms.Select(attrs={'class':'form-select'}),
            'nombre': forms.TextInput(attrs={'class':'form-control'}),
            'papellido': forms.TextInput(attrs={'class':'form-control'}),
            'sapellido': forms.TextInput(attrs={'class':'form-control'}),
            'movil_personal': forms.TextInput(attrs={'class':'form-control'}),
            'fijo_personal': forms.TextInput(attrs={'class':'form-control'}),
            'direccion': forms.Textarea(attrs={'rows': 3, 'class':'form-control'}),

            # Provincia NO lleva reverse() aquí. Se lo ponemos en __init__
            'provincia': forms.Select(attrs={
                'class': 'form-select',
                'hx-trigger': 'change',
                'hx-target': '#id_municipio',
                'hx-swap': 'outerHTML',
            }),

            # Municipio empieza deshabilitado y se habilita tras el swap de HTMX
            'municipio': forms.Select(attrs={
                'class': 'form-select',
                'disabled': 'disabled',
            }),

            
            'codigo_postal': forms.TextInput(attrs={'class':'form-control'}),
            'raza': forms.Select(attrs={'class': 'form-select'}),
            'grado_cientifico': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_grado_cientifico',
                'disabled': 'disabled',
            }),
            'tpantalon': forms.TextInput(attrs={'class':'form-control'}),
            'tcamisa': forms.TextInput(attrs={'class':'form-control'}),
            'tzapatos': forms.NumberInput(attrs={'class':'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        # Extraemos 'user' para evitar error en super().__init__ y para usarlo en permisos
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # ✅ HTMX en Provincia
        self.fields['provincia'].widget.attrs['hx-get'] = reverse('cargar_municipios')

        # ✅ Lógica de Moderador (Protegida y Tipada)
        # Solo se ejecuta si el campo existe en el formulario (escalabilidad)
        if 'unidad_organizativa' in self.fields:
            # Cast para que Pylance sepa que es un ModelChoiceField
            uo_field = cast(ModelChoiceField, self.fields['unidad_organizativa'])
            
            # Lógica de negocio
            if user and getattr(user, 'es_moderador', False):
                uo_field.queryset = user.unidades.all()

        # --- Especialidad dependiente del nivel_educ ---
        nivel = self.data.get('nivel_educ') or getattr(self.instance, 'nivel_educ', None)
        
        # Cast para Pylance
        esp_field = cast(ModelChoiceField, self.fields['especialidad'])

        if nivel == 'NS':
            qs_esp = NEspecialidad.objects.filter(educ_superior=True)
            esp_field.widget.attrs.pop('disabled', None)
        elif nivel == 'TM':
            qs_esp = NEspecialidad.objects.filter(educ_superior=False)
            esp_field.widget.attrs.pop('disabled', None)
        else:
            qs_esp = NEspecialidad.objects.none()
            esp_field.widget.attrs['disabled'] = 'disabled'
        
        esp_field.queryset = qs_esp

        # --- Municipios dependientes de la provincia ---
        provincia_id = self.data.get('provincia') or getattr(getattr(self.instance, 'provincia', None), 'id', None)
        
        # Cast para Pylance
        mun_field = cast(ModelChoiceField, self.fields['municipio'])

        if provincia_id:
            mun_field.queryset = (
                NMunicipio.objects.filter(provincia_id=provincia_id).order_by('nombre')
            )
            mun_field.widget.attrs.pop('disabled', None)
        else:
            mun_field.queryset = NMunicipio.objects.none()
            mun_field.widget.attrs['disabled'] = 'disabled'