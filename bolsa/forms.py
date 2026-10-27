import re
from typing import cast
from django import forms
from django.forms import ModelChoiceField
from django.urls import reverse, reverse_lazy
from django.utils.text import format_lazy
from .models import PATRON_SERIE_CI, Aspirante
from nomencladores.models import NEspecialidad, NMunicipio

class AspiranteForm(forms.ModelForm):
    # Nivel educacional dispara la carga de especialidades por HTMX
    nivel_educ = forms.ChoiceField(
        label='Nivel Educacional',
        # Opción vacía delante: sin ella el navegador deja preseleccionada la
        # primera de la lista ('Sin Acreditar'), así que un alta hecha de prisa
        # guardaba ese nivel sin que nadie lo hubiera elegido. Ahora el campo
        # empieza en blanco y hay que decidirlo a conciencia.
        choices=[('', 'Seleccione un nivel...')] + list(
            Aspirante._meta.get_field('nivel_educ').choices
        ),
        # Obligatorio solo en el formulario: en el modelo sigue siendo
        # `blank=True, null=True` porque hay aspirantes antiguos sin el dato y
        # cambiarlo exigiría migrar y rellenar todos esos registros.
        required=True,
        error_messages={'required': 'Seleccione el nivel educacional.'},
        widget=forms.Select(attrs={
            'class': 'form-select',
            'required': 'required',
            # `solo_opciones=1` + innerHTML: HTMX cambia solo las <option> y el
            # <select> —con su Select2 encima— sobrevive, así que el campo ya no
            # parpadea al cambiar el Nivel Educacional.
            # `format_lazy` (y no una concatenación normal) para que la URL se
            # siga resolviendo tarde: en tiempo de import las rutas aún no están
            # cargadas.
            'hx-get': format_lazy('{}?solo_opciones=1', reverse_lazy('cargar_esp')),
            'hx-target': '#id_especialidad',
            # Solo 'change'. Antes también escuchaba 'select2:select', pero ese
            # evento lo dispara jQuery y NO es un evento nativo del DOM, así que
            # el listener de HTMX nunca llegaba a verlo: era un disparador
            # muerto. Quien avisa de verdad es el puente de
            # `static/js/select2_htmx.js`, que al confirmar la selección reemite
            # un 'change' nativo sobre el <select>.
            'hx-trigger': 'change',
            'hx-swap': 'innerHTML'
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
            'doc_identidad', 'serie_ci', 'sexo', 'nombre', 'papellido', 'sapellido',
            'movil_personal', 'fijo_personal', 'direccion',
            'provincia', 'municipio', 'codigo_postal',
            'raza', 'grado_cientifico', 'tpantalon', 'tcamisa', 'tzapatos',
            'nivel_educ', 'especialidad', 'titulo_oro',
        )

        labels = {
            'doc_identidad': 'Doc. de Identidad',
            'serie_ci': 'Serie CI',
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
            'serie_ci': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': '9',
                'autocapitalize': 'characters',
                'placeholder': '9 caracteres',
            }),
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
                # innerHTML (no outerHTML): así HTMX cambia solo las <option> y el
                # <select> —con su Select2 montado encima— sobrevive al cambio de
                # Provincia. Con outerHTML el <select> se reemplazaba entero y
                # durante un instante se veían dos controles apilados.
                'hx-swap': 'innerHTML',
            }),

            # Municipio empieza deshabilitado y se habilita tras el swap de HTMX
            'municipio': forms.Select(attrs={
                'class': 'form-select',
                'disabled': 'disabled',
            }),

            
            'codigo_postal': forms.TextInput(attrs={'class':'form-control'}),
            'raza': forms.Select(attrs={'class': 'form-select', 'required': 'required'}),
            'grado_cientifico': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_grado_cientifico',
                'disabled': 'disabled',
            }),
            'tpantalon': forms.TextInput(attrs={'class':'form-control'}),
            'tcamisa': forms.TextInput(attrs={'class':'form-control'}),
            'tzapatos': forms.NumberInput(attrs={'class':'form-control'}),

            'titulo_oro': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, **kwargs):
        # Extraemos 'user' para evitar error en super().__init__ y para usarlo en permisos
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # ✅ HTMX en Provincia
        # `solo_opciones=1`: la vista devuelve únicamente las <option>, que es lo
        # que espera el `hx-swap="innerHTML"` del widget.
        self.fields['provincia'].widget.attrs['hx-get'] = (
            reverse('cargar_municipios') + '?solo_opciones=1'
        )

        self.fields['raza'].empty_label = "Seleccione una raza..."
        self.fields['raza'].required = True

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
                NMunicipio.objects.filter(provincia_id=provincia_id)
            )
            mun_field.widget.attrs.pop('disabled', None)
        else:
            mun_field.queryset = NMunicipio.objects.none()
            mun_field.widget.attrs['disabled'] = 'disabled'

    def clean_serie_ci(self):
        """Normaliza la serie y comprueba el formato antes de llegar al modelo.

        Reutiliza `Aspirante._normalizar_serie_ci` (mayúsculas, sin espacios, vacío ->
        `None`) para no tener dos criterios de normalización, y valida contra
        `PATRON_SERIE_CI`, el mismo patrón que usa la regla ASP-009 de Subsanación.

        La serie es OPCIONAL a propósito: dejarla vacía guarda sin error y Subsanación
        lo reporta después como hallazgo de criticidad baja (ASP-008). Lo que sí se
        rechaza aquí es una serie a medio escribir: si el usuario empezó a teclearla,
        tiene que completarla.
        """
        serie = Aspirante._normalizar_serie_ci(self.cleaned_data.get('serie_ci'))
        if serie is None:
            return None
        if not re.match(PATRON_SERIE_CI, serie):
            raise forms.ValidationError(
                'La serie del carnet debe tener exactamente 9 caracteres '
                'alfanuméricos (A-Z, 0-9), sin espacios ni guiones.')
        return serie
