from django import forms
from django.urls import reverse_lazy
from .models import CAlta
from strorganizativa.models import UnidadOrganizativa, Departamento, CargoPlantilla


class CAltaForm(forms.ModelForm):
    
    unidad = forms.ModelChoiceField(
        label='Unidad Organizativa',
        queryset=UnidadOrganizativa.objects.all(), 
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': reverse_lazy('cargar_departamentos'),  # <--- URL CORRECTA
            'hx-target': '#id_departamento',
            'hx-trigger': 'change',  # Aseguramos que sea al cambiar
            'required': True
        }))

    departamento = forms.ModelChoiceField(
        label='Departamento',
        queryset=Departamento.objects.none(), 
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': reverse_lazy('cargar_cargos'),  # <--- URL CORRECTA
            'hx-target': '#id_cargo',
            'hx-trigger': 'change',
            'required': True
        }))
    cargo = forms.ModelChoiceField(
        label='Cargo',
        queryset=CargoPlantilla.objects.none(), 
        widget=forms.Select(attrs={'class': 'form-select', 'required': True})
    )
    
    
    class Meta:
            
        model = CAlta        
        fields = (
            'no_expediente', 'tipo', 'fecha_alta', 'duracion', 'cargo', 'reg_militar',
            'tridente', 'profesional', 'fecha_vence_lic', 'fecha_vence_recal', 
            'fecha_vence_seg', 'c_formal', 'funcionario', 'designado', 
            'c_formal_res', 'funcionario_res', 'designado_res', 'tipo_salario',
            'maestria', 'doctorado', 'cnci', 'instructor', 'jubilado_recontratado', 'jornada'
        )
        labels = {
            'no_expediente': 'Exp. Laboral', 
            'tipo': 'Tipo de Contrato',
            'fecha_alta': 'F. de Contratación',
            'duracion': 'D. de Contrato',
            'reg_militar': 'Registro Militar',
            'tridente': 'Tridente',
            'profesional': 'Chofer Profesional',
            'fecha_vence_lic': 'Venc. Licencia',
            'fecha_vence_recal': 'Venc. Recalificación',
            'fecha_vence_seg': 'Venc. Seguro',
            'c_formal': 'C. Formal',
            'funcionario': 'Funcionario',
            'designado': 'Designado', 
            'c_formal_res': 'No. Resolución',
            'funcionario_res': 'No. Resolución',
            'designado_res':'No. Resolución',
            'tipo_salario': 'Tipo de Salario',
            'maestria': 'Maetría',
            'cnci': 'CNCI',
            'jubilado_recontratado': 'Jubilado Recontratado',
            'jornada': 'Jornada Laboral'
        }
        widgets = {
            'no_expediente': forms.TextInput(attrs={'class':'form-control'}), 
            'tipo': forms.Select(attrs={'class':'form-select'}),
            'fecha_alta': forms.DateInput(attrs={'type':'date', 'class':'form-control', 'disabled': 'disabled'}),
            'duracion': forms.NumberInput(attrs={'class':'form-control', 'disabled': 'disabled'}),
            'reg_militar': forms.Select(attrs={'class':'form-select'}),
            'tridente': forms.Select(attrs={'class':'form-select'}),
            'profesional': forms.CheckboxInput(attrs={'class': 'form-check-input',  'id': 'id_profesional'}),
            'fecha_vence_lic': forms.DateInput(attrs={'type':'date', 'class':'form-control', 'id': 'id_fv_lic', 'disabled': 'disabled'}),
            'fecha_vence_recal': forms.DateInput(attrs={'type':'date', 'class':'form-control', 'id': 'id_fv_rec', 'disabled': 'disabled'}),
            'fecha_vence_seg': forms.DateInput(attrs={'type':'date', 'class':'form-control', 'id': 'id_fv_seg', 'disabled': 'disabled'}),
            'c_formal': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_c_formal'}),
            'c_formal_res': forms.TextInput(attrs={'class':'form-control', 'placeholder' : '###/AA', 'id': 'id_c_formal_res', 'disabled': 'disabled'}),
            'funcionario': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_funcionario'}),
            'funcionario_res': forms.TextInput(attrs={'class':'form-control', 'placeholder' : '###/AA', 'id': 'id_funcionario_res', 'disabled': 'disabled'}),
            'designado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_designado'}), 
            'designado_res': forms.TextInput(attrs={'class':'form-control', 'placeholder' : '###/AA', 'id': 'id_designado_res', 'disabled': 'disabled'}),
            'tipo_salario': forms.Select(attrs={'class': 'form-select'}),
            'maestria':forms.NumberInput(attrs={'class':'form-control'}),
            'doctorado':forms.NumberInput(attrs={'class':'form-control'}),
            'cnci':forms.NumberInput(attrs={'class':'form-control'}),
            'instructor':forms.NumberInput(attrs={'class':'form-control'}),
            'jubilado_recontratado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_jubilado_recontratado'}),
            'jornada': forms.Select(attrs={'class':'form-select'})
        }
        
    def __init__(self, *args, user = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if user:
            if user.is_superuser:
                self.fields['unidad'].queryset = UnidadOrganizativa.objects.all()
            else:
                self.fields['unidad'].queryset = user.unidades.all()
        
        # 1. PRIMERO: Cargar datos iniciales de la instancia (BD) si existen
        # Esto establece los valores por defecto al abrir el formulario de edición
        if self.instance and self.instance.pk and self.instance.cargo:
            # departamento elegido del cargo
            dpto = self.instance.cargo.departamento
            # unidad asociada a ese departamento
            unidad = dpto.unidad_organizativa

            self.fields['unidad'].initial = unidad.pk

            self.fields['departamento'].queryset = Departamento.objects.filter(
                unidad_organizativa=unidad
            )
            self.fields['departamento'].initial = dpto.pk

            self.fields['cargo'].queryset = CargoPlantilla.objects.filter(
                departamento=dpto
            )
            self.fields['cargo'].initial = self.instance.cargo.pk

        # 2. SEGUNDO: Sobrescribir con datos del formulario (POST) si existen
        # Esto es crucial: si el usuario cambió la unidad/departamento, 
        # cargamos los nuevos querysets para que la validación pase.
        if "unidad" in self.data:
            try:
                unidad_id = int(self.data.get("unidad"))
                self.fields["departamento"].queryset = Departamento.objects.filter(unidad_organizativa=unidad_id)
            except (ValueError, TypeError):
                pass  # Si hay error, dejamos el queryset vacío o el que estaba
            
        if "departamento" in self.data:
            try:
                dpto_id = int(self.data.get("departamento"))
                self.fields["cargo"].queryset = CargoPlantilla.objects.filter(departamento=dpto_id)
            except (ValueError, TypeError):
                pass
        self.fields['reg_militar'].required = True

    def clean(self):
        cleaned_data = super().clean()
        cargo = cleaned_data.get('cargo')
        tipo_contrato = cleaned_data.get('tipo')

        # VALIDACIÓN DE CAPACIDAD (Solo para plazas fijas INDETERMINADAS)
        if cargo and tipo_contrato == 'IND':
            check_capacity = True
            
            # Si estamos editando y el cargo es el mismo, no validamos (ya ocupa la plaza)
            if self.instance and self.instance.pk:
                if self.instance.cargo == cargo:
                    check_capacity = False
            
            if check_capacity:
                if cargo.cant_cubierta >= cargo.cant_aprobada:
                    self.add_error('cargo', f'El cargo "{cargo}" no tiene plazas disponibles ({cargo.cant_cubierta}/{cargo.cant_aprobada}).')
        
        return cleaned_data
        
   


class MovimientoForm(CAltaForm):
    fecha_efectiva = forms.DateField(
        label='Fecha Efectiva del Movimiento',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        required=True
    )

    class Meta(CAltaForm.Meta):
        # Mantenemos los campos pero añadimos fecha_efectiva
        fields = CAltaForm.Meta.fields + ('fecha_efectiva',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 1. Bloquear Expediente (Read Only)
        if 'no_expediente' in self.fields:
            self.fields['no_expediente'].widget.attrs['disabled'] = 'disabled'
            self.fields['no_expediente'].required = False
        
        # 2. Ocultar o desactivar la fecha_alta original (porque usaremos la efectiva)
        if 'fecha_alta' in self.fields:
            self.fields['fecha_alta'].widget = forms.HiddenInput()
            self.fields['fecha_alta'].required = False
            
        # 3. Campos obligatorios para el movimiento
        self.fields['unidad'].required = True
        self.fields['departamento'].required = True
        self.fields['cargo'].required = True