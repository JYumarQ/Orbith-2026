from django import forms
from solicitudes.models import SolicitudCargo
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa


class SolicitudCargoForm(forms.ModelForm):
    """Formulario con cascada Unidad → Departamento → Cargo (origen / nuevo)."""
    unidad = forms.ModelChoiceField(
        label='Unidad Organizativa',
        queryset=UnidadOrganizativa.objects.all(),
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': '/estructuras/cargar_dptos/',  # endpoint ya existente
            'hx-target': '#id_departamento',
            'hx-trigger': 'change'
        })
    )
    departamento = forms.ModelChoiceField(
        label='Departamento',
        queryset=Departamento.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': '/estructuras/cargar_cargos/',  # endpoint ya existente
            'hx-target': '#id_cargo_origen, #id_nuevo_cargo',
            'hx-trigger': 'change'
        })
    )

    # campos reales del modelo
    cargo_origen = forms.ModelChoiceField(
        label='Cargo origen',
        queryset=CargoPlantilla.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    nuevo_cargo = forms.ModelChoiceField(
        label='Nuevo cargo (solo si modifica)',
        queryset=CargoPlantilla.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = SolicitudCargo
        fields = ('unidad', 'departamento', 'cargo_origen',
                  'nuevo_cargo', 'tipo', 'motivo', 'fecha_vigor'
                  )
        labels ={
            'tipo': 'Tipo',
            'motivo': 'Motivo',
            'fecha_vigor': 'Entrada en Vigor',
        }
        widgets = {
            'fecha_vigor': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'motivo': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'})
        }

    # ----- lógica de cascada -----
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user and not user.is_superuser:
            self.fields['unidad'].queryset = user.unidades.all()

        # POST/GET
        if "unidad" in self.data:
            unidad_id = int(self.data.get("unidad"))
            self.fields['departamento'].queryset = (
                Departamento.objects.filter(unidad_organizativa_id=unidad_id)
            )

        if "departamento" in self.data:
            dpto_id = int(self.data.get("departamento"))
            cargos = CargoPlantilla.objects.filter(departamento_id=dpto_id)
            self.fields['cargo_origen'].queryset = cargos
            self.fields['nuevo_cargo'].queryset = cargos