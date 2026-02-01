from django import forms
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
                # Si limpian la provincia, vaciamos y deshabilitamos municipio
                
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
        # Para limitar UO al moderador, la vista debe pasar user=...
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # ✅ Poner aquí la URL HTMX (evita ciclos de importación)
        self.fields['provincia'].widget.attrs['hx-get'] = reverse('cargar_municipios')

        # Moderador: ver solo sus UO asignadas (si el campo existe en el form)
        if user and getattr(user, 'es_moderador', False) and 'unidad_organizativa' in self.fields:
            self.fields['unidad_organizativa'].queryset = user.unidades.all()

        # --- Especialidad dependiente del nivel_educ ---
        nivel = self.data.get('nivel_educ') or getattr(self.instance, 'nivel_educ', None)
        if nivel == 'NS':
            qs_esp = NEspecialidad.objects.filter(educ_superior=True)
            self.fields['especialidad'].widget.attrs.pop('disabled', None)
        elif nivel == 'TM':
            qs_esp = NEspecialidad.objects.filter(educ_superior=False)
            self.fields['especialidad'].widget.attrs.pop('disabled', None)
        else:
            qs_esp = NEspecialidad.objects.none()
            self.fields['especialidad'].widget.attrs['disabled'] = 'disabled'
        self.fields['especialidad'].queryset = qs_esp

        # --- Municipios dependientes de la provincia (estado inicial/render) ---
        provincia_id = self.data.get('provincia') or getattr(getattr(self.instance, 'provincia', None), 'id', None)
        if provincia_id:
            self.fields['municipio'].queryset = (
                NMunicipio.objects.filter(provincia_id=provincia_id).order_by('nombre')
            )
            self.fields['municipio'].widget.attrs.pop('disabled', None)
        else:
            self.fields['municipio'].queryset = NMunicipio.objects.none()
            self.fields['municipio'].widget.attrs['disabled'] = 'disabled'
