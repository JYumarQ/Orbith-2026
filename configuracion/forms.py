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
            'provincia_entidad',  # ← AÑADIDO
            'auditoria_borrar_antigua', 'auditoria_anios_conservar',
        )
        labels = {
            'nombre_empresa': 'Nombre de la Empresa',
            'org_superior': 'Organismo',
            'reup': 'REUP',
            'rama': 'Rama',
            'unidad_presup': 'Sector',
            'moneda_local': 'Moneda Local',
            'periodo': 'Período de Pago',
            'fondo_tiempo_calc_tarif': 'Fondo de tiempo para el cálculo',
            'correo': 'Correo',
            'telefono': 'Teléfono',
            'logo': 'Logo',
            'direccion': 'Dirección',
            'provincia_entidad': 'Provincia Entidad',  # ← AÑADIDO
            'auditoria_borrar_antigua': 'Borrar la auditoría antigua',
            'auditoria_anios_conservar': 'Conservar (años)',
        }
        widgets = {
            'nombre_empresa': forms.TextInput(attrs={'class': 'form-control'}),
            'org_superior': forms.TextInput(attrs={'class': 'form-control'}),
            # El guion va ESCAPADO. Sin escapar, `[0-9-]*` es un patrón inválido:
            # los navegadores compilan el atributo `pattern` con la bandera `v`, y
            # ahí un guion suelto al final de una clase de caracteres es un error de
            # sintaxis. El efecto era que el campo lanzaba una excepción al
            # validarse («Failed to read the 'valid' property from ValidityState»),
            # así que el REUP no se validaba en el navegador en absoluto.
            #
            # El validador del modelo (`configuracion/models.py`) usa el mismo
            # patrón SIN escapar y es correcto: la sintaxis de expresiones regulares
            # de Python sí admite el guion final como literal. Son dos motores
            # distintos, no una incoherencia.
            'reup': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': '15',
                'pattern': r'[0-9\-]*',
                'title': 'Solo números y guiones (-).',
            }),
            'rama': forms.TextInput(attrs={'class': 'form-control'}),
            'unidad_presup': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'moneda_local': forms.TextInput(attrs={'class': 'form-control'}),
            # Se pinta como toggle Quincenal/Mensual en la plantilla. Los radios
            # van ocultos por CSS y se recorren a mano (ver parametros_generales.html),
            # igual que el toggle Empresarial/Presupuestado de `unidad_presup`.
            'periodo': forms.RadioSelect(),
            'fondo_tiempo_calc_tarif': forms.NumberInput(attrs={'class': 'form-control'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control', 'rows': 3}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'porcentaje_horas_extras': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'auditoria_borrar_antigua': forms.CheckboxInput(attrs={
                'class': 'form-check-input', 'id': 'id_auditoria_borrar_antigua', 'role': 'switch'}),
            # Nace deshabilitado; lo enciende el switch (como «País» con «Misión»).
            'auditoria_anios_conservar': forms.NumberInput(attrs={
                'class': 'form-control', 'id': 'id_auditoria_anios_conservar',
                'min': '2', 'max': '99', 'step': '1', 'disabled': 'disabled'}),

        }
        # El toggle solo ofrece Quincenal o Mensual, así que este error únicamente
        # aparece si se manipula el envío. Aun así se traduce: Django lo emitiría
        # en inglés porque LANGUAGE_CODE es 'en-us' (ver core/settings.py).
        error_messages = {
            'periodo': {
                'invalid_choice': 'Seleccione un período de pago válido: Quincenal o Mensual.',
            },
            'auditoria_anios_conservar': {
                'invalid': 'Los años deben ser un número entero.',
                'min_value': 'Hay que conservar como mínimo 2 años de auditoría.',
                'max_value': 'Se pueden conservar como máximo 99 años de auditoría.',
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Django pinta `min="0"` por ser un entero positivo y pisa el de
        # `Meta.widgets`; el mínimo real (2 años) es el del validador del modelo.
        self.fields['auditoria_anios_conservar'].widget.attrs['min'] = '2'

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('auditoria_borrar_antigua'):
            if not cleaned_data.get('auditoria_anios_conservar') and                     'auditoria_anios_conservar' not in self.errors:
                self.add_error(
                    'auditoria_anios_conservar',
                    'Indique cuántos años de auditoría se conservan (de 2 a 99).')
        else:
            # Apagado es «Nunca»: no tiene sentido guardar un plazo.
            cleaned_data['auditoria_anios_conservar'] = None
        return cleaned_data