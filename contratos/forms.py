from django import forms
from django.urls import reverse_lazy
from .models import CAlta
from strorganizativa.models import UnidadOrganizativa, Departamento, CargoPlantilla
from nomencladores.models import NRol, NTipoContrato
import json


class SelectCargosConPlazasWidget(forms.Select):
    """Widget inteligente que inyecta data-aprobadas y data-ocupadas a las opciones nativas de Django"""
    def __init__(self, attrs=None, choices=(), mapa_plazas=None):
        super().__init__(attrs, choices)
        self.mapa_plazas = mapa_plazas or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value:
            try:
                # --- LA MAGIA CONTRA EL OBJETO OCULTO DE DJANGO ---
                # value puede ser un ModelChoiceIteratorValue, extraemos el número real así:
                pk_val = getattr(value, 'value', value) 
                pk = int(pk_val)
                
                if pk in self.mapa_plazas:
                    info = self.mapa_plazas[pk]
                    option['attrs']['data-aprobadas'] = info['aprobadas']
                    option['attrs']['data-ocupadas'] = info['ocupadas']
            except (ValueError, TypeError):
                pass
        return option
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
            'hx-get': reverse_lazy('cargar_cargos_contrato'),  # <--- URL CORRECTA
            'hx-target': '#id_cargo',
            'hx-trigger': 'change',
            'required': True
        }))
    cargo = forms.ModelChoiceField(
        label='Cargo',
        queryset=CargoPlantilla.objects.none(), 
        widget=forms.Select(attrs={
            'class': 'form-select', 
            'required': True,
            # HTMX: Al cambiar cargo -> Calcular Todo (Salario, Rol, Grupo)
            'hx-get': reverse_lazy('cargar_salarios'), 
            'hx-target': '#resultados_salariales', # Apunta al contenedor de salarios
            'hx-swap': 'innerHTML', # Reemplaza el contenido interno
            'hx-trigger': 'change',
            'hx-include': '#id_tridente, #id_tipo_salario' # Solución: Enviar también el tipo de salario
        })
    )

    rol = forms.CharField(
        label='Rol',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': 'readonly',
            'id': 'id_rol',
            'placeholder': '---'
        })
    )

    grupo_escala = forms.CharField(
        label='Grupo Escala',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'readonly': 'readonly',
            'id': 'id_grupo_escala',
            'placeholder': '---'
        })
    )
    
    
    class Meta:
            
        model = CAlta        
        fields = (
            'no_expediente', 'tipo', 'motivo', 'fecha_alta', 'duracion', 'cargo', 'reg_militar',
            'tridente', 'profesional', 'fecha_vence_lic', 'fecha_vence_recal', 
            'fecha_vence_seg', 'c_formal', 'funcionario', 'designado', 
            'c_formal_res', 'funcionario_res', 'designado_res', 'tipo_salario',
            'maestria', 'doctorado', 'cnci', 'instructor', 'jubilado_recontratado', 'jornada',
            'mision', 'pais'
        )
        labels = {
            'no_expediente': 'Exp. Laboral', 
            'tipo': 'Tipo de Contrato',
            'motivo' : 'Motivo de Contrato',
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
            'jornada': 'Jornada Laboral',
            'mision': 'Misión',
            'pais': 'País'
        }
        widgets = {
            'no_expediente': forms.TextInput(attrs={'class':'form-control'}), 
            'tipo': forms.Select(attrs={'class':'form-select'}),
            'motivo': forms.Select(attrs={'class':'form-select', 'id': 'id_motivo', 'disabled': 'disabled'}),
            'fecha_alta': forms.DateInput(attrs={'type':'date', 'class':'form-control', 'disabled': 'disabled'}),
            'duracion': forms.NumberInput(attrs={'class':'form-control', 'disabled': 'disabled'}),
            'reg_militar': forms.Select(attrs={'class':'form-select'}),
            'tridente': forms.Select(attrs={
                'class':'form-select',
                # Tridente también debe recalcular salario si cambia
                'hx-get': reverse_lazy('cargar_salarios'),
                'hx-target': '#resultados_salariales',
                'hx-swap': 'innerHTML',
                'hx-include': '#id_cargo, #id_tipo_salario', # Solución: Enviar también el tipo de salario
                'hx-trigger': 'change'
            }),
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
            'tipo_salario': forms.Select(attrs={
                'class': 'form-select',
                'hx-get': reverse_lazy('cargar_salarios'),
                'hx-target': '#resultados_salariales',
                'hx-swap': 'innerHTML',
                'hx-include': '#id_cargo, #id_tridente',
                'hx-trigger': 'change'
            }),
            'maestria':forms.NumberInput(attrs={'class':'form-control'}),
            'doctorado':forms.NumberInput(attrs={'class':'form-control'}),
            'cnci':forms.NumberInput(attrs={'class':'form-control'}),
            'instructor':forms.NumberInput(attrs={'class':'form-control'}),
            'jubilado_recontratado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_jubilado_recontratado'}),
            'jornada': forms.Select(attrs={'class':'form-select'}),
            'mision': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_mision'}),
            'pais': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_pais', 'disabled': 'disabled'})
        }
        
    def __init__(self, *args, user = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        f_unidad = self.fields['unidad']

        if user and isinstance(f_unidad, forms.ModelChoiceField):
            if user.is_superuser:
                f_unidad.queryset = UnidadOrganizativa.objects.all()
            else:
                f_unidad.queryset = getattr(user, 'unidades').all()
        
        # 1. PRIMERO: Cargar datos iniciales de la instancia (BD) si existen
        # Esto establece los valores por defecto al abrir el formulario de edición
        if self.instance and self.instance.pk and self.instance.cargo:
            # departamento elegido del cargo
            dpto = self.instance.cargo.departamento
            # unidad asociada a ese departamento
            unidad = dpto.unidad_organizativa

            self.fields['unidad'].initial = unidad.pk

            f_dpto = self.fields['departamento']
            if isinstance(f_dpto, forms.ModelChoiceField):
                f_dpto.queryset = Departamento.objects.filter(unidad_organizativa=unidad)
                f_dpto.initial = dpto.pk

            

            f_cargo = self.fields['cargo']
            if isinstance(f_cargo, forms.ModelChoiceField):
                f_cargo.queryset = CargoPlantilla.objects.filter(departamento=dpto)
                f_cargo.initial = self.instance.cargo.pk


        if self.instance and self.instance.pk and self.instance.cargo:
            # Precargar textos visuales
            if self.instance.cargo.rol:
                 self.fields['rol'].initial = self.instance.cargo.rol.tipo
            if self.instance.cargo.ncargo.grupo_escala:
                 self.fields['grupo_escala'].initial = self.instance.cargo.ncargo.grupo_escala.nivel
            

        # 2. SEGUNDO: Sobrescribir con datos del formulario (POST) si existen
        # Esto es crucial: si el usuario cambió la unidad/departamento, 
        # cargamos los nuevos querysets para que la validación pase.
        if "unidad" in self.data:
            try:
                # [Corrección Pylance] Validamos que no sea None antes de int()
                val_unidad = self.data.get("unidad")
                if val_unidad:
                    unidad_id = int(val_unidad)
                    f_dpto = self.fields["departamento"]
                    if isinstance(f_dpto, forms.ModelChoiceField):
                        f_dpto.queryset = Departamento.objects.filter(unidad_organizativa=unidad_id)
            except (ValueError, TypeError):
                pass

        tipos_con_motivo = list(NTipoContrato.objects.filter(requiere_motivo=True).values_list('id', flat=True))
        if 'tipo' in self.fields:
            self.fields['tipo'].widget.attrs['data-requiere-motivo'] = json.dumps(tipos_con_motivo)
            
        if "departamento" in self.data:
            try:
                val_dpto = self.data.get("departamento")
                if val_dpto:
                    dpto_id = int(val_dpto)
                    f_cargo = self.fields["cargo"]
                    if isinstance(f_cargo, forms.ModelChoiceField):
                        f_cargo.queryset = CargoPlantilla.objects.filter(departamento=dpto_id)
            except (ValueError, TypeError):
                pass
                
        if 'reg_militar' in self.fields:
            self.fields['reg_militar'].required = True

        # --- EL ESCUDO DEL SERVIDOR ---
        # Si la instancia ya existe y es de salario Fijo, bloqueamos el tridente desde Python
        if self.instance and self.instance.pk and self.instance.tipo_salario == 'FIJ':
            if 'tridente' in self.fields:
                self.fields['tridente'].widget.attrs['disabled'] = 'disabled'
                self.fields['tridente'].required = False

        # A) Radar de Tipos de Contrato oficiales
        tipos_plantilla = list(NTipoContrato.objects.filter(ocupa_plaza=True).values_list('id', flat=True))
        if 'tipo' in self.fields:
            self.fields['tipo'].widget.attrs['data-ocupa-plaza'] = json.dumps(tipos_plantilla)

        # B) LA CURA DE EDICIÓN: Si el form ya trae cargos precargados, les amarramos el mapa numérico
        if 'cargo' in self.fields and self.fields['cargo'].queryset.exists():
            cargos_qs = self.fields['cargo'].queryset
            # Armamos un diccionario ultrarrápido en RAM: { id_cargo: {'aprobadas': 5, 'ocupadas': 4} }
            mapa = {c.pk: {'aprobadas': c.cant_aprobada, 'ocupadas': c.plazas_fijas} for c in cargos_qs}
            
            # Si estamos editando a Juan y su contrato ocupa plaza, le perdonamos su propio espacio (+1 libre)
            if self.instance and self.instance.pk and getattr(self.instance.tipo, 'ocupa_plaza', False):
                if self.instance.cargo_id in mapa:
                    mapa[self.instance.cargo_id]['ocupadas'] = max(0, mapa[self.instance.cargo_id]['ocupadas'] - 1)

            # Reemplazamos el widget estándar por nuestro widget hipervitamínico
            nuevo_widget = SelectCargosConPlazasWidget(
                attrs={'class': 'form-select select2-cargo'}, 
                mapa_plazas=mapa
            )
            
            # Le pasamos el listado de opciones del campo original al nuevo widget
            nuevo_widget.choices = self.fields['cargo'].choices 
            
            self.fields['cargo'].widget = nuevo_widget

    # ---------------------------------------------------------
    # VALIDACIONES ESTRICTAS DE NEGOCIO (EL ESCUDO)
    # ---------------------------------------------------------
    def clean_no_expediente(self):
        expediente = self.cleaned_data.get('no_expediente')
        if not expediente:
            raise forms.ValidationError("El número de expediente es obligatorio.")
        
        # Validar que solo contenga números enteros positivos mayores a 0
        try:
            exp_num = int(expediente)
            if exp_num <= 0:
                raise forms.ValidationError("El expediente debe ser mayor que 0.")
        except ValueError:
            raise forms.ValidationError("El expediente solo puede contener números.")
            
        return expediente

    def clean(self):
        cleaned_data = super().clean()
        cargo = cleaned_data.get('cargo')
        
        # Obtener tipo_contrato del form, o de la instancia si estamos en un movimiento
        tipo_contrato = cleaned_data.get('tipo')
        if not tipo_contrato and self.instance:
            tipo_contrato = getattr(self.instance, 'tipo', None)
            
        tipo_salario = cleaned_data.get('tipo_salario')
        tridente = cleaned_data.get('tridente')

        # --- 1. LÓGICA UNIFICADA DEL TRIDENTE ---
        es_cuadro = False
        if cargo and cargo.ncargo and cargo.ncargo.cat_ocupacional:
            cat_nombre = str(cargo.ncargo.cat_ocupacional).upper()
            # Validamos si es cuadro por su categoría ocupacional
            if "CUADRO" in cat_nombre or cat_nombre in ["CEJ", "CDI"]:
                es_cuadro = True

        es_fijo = (tipo_salario == 'FIJ')

        # REGLA DE ORO: Si es Fijo O es Cuadro, el Tridente se anula.
        if es_cuadro or es_fijo:
            cleaned_data['tridente'] = None
        else:
            # Si es Dinámico y NO es Cuadro, es estrictamente obligatorio.
            if not tridente:
                self.add_error('tridente', "El tridente es obligatorio para un salario dinámico en este cargo.")

        # --- 2. VALIDACIÓN DE CAPACIDAD (Intacta) ---
        if cargo and tipo_contrato and tipo_contrato.ocupa_plaza:
            check_capacity = True
            if self.instance and self.instance.pk:
                if self.instance.cargo == cargo:
                    check_capacity = False
            
            if check_capacity:
                if cargo.cant_cubierta_real >= cargo.cant_aprobada:
                    self.add_error('cargo', f'El cargo "{cargo}" no tiene plazas disponibles ({cargo.cant_cubierta_real}/{cargo.cant_aprobada}).')
        
        return cleaned_data
    

   


class MovimientoForm(CAltaForm):
    fecha_efectiva = forms.DateField(
        label='Fecha Efectiva del Movimiento',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        required=True
    )

    fecha_solicitud = forms.DateField(
        label='Fecha de Solicitud',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        required=False
    )
    observaciones = forms.CharField(
        label='Observaciones',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False
    )

    class Meta(CAltaForm.Meta):
        fields = ('unidad', 'departamento', 'cargo', 'tipo', 'motivo', 'duracion', 
                  'tipo_salario', 'tridente', 'fecha_efectiva', 'fecha_solicitud', 'observaciones')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 1. Bloquear Expediente (Read Only)
        if 'no_expediente' in self.fields:
            self.fields['no_expediente'].widget.attrs['readonly'] = 'readonly'
            self.fields['no_expediente'].required = False
        
        # 2. Ocultar o desactivar la fecha_alta original (porque usaremos la efectiva)
        if 'fecha_alta' in self.fields:
            self.fields['fecha_alta'].widget = forms.HiddenInput()
            self.fields['fecha_alta'].required = False
            
        # 3. Campos obligatorios para el movimiento
        self.fields['unidad'].required = True
        self.fields['departamento'].required = True
        self.fields['cargo'].required = True

        # --- 4. LIMPIEZA DE HTMX HEREDADO ---
        # Eliminamos los llamados HTMX de la clase padre para evitar que busquen 
        # contenedores inexistentes en el modal de movimiento.
        for campo in ['cargo', 'tridente', 'tipo_salario']:
            if campo in self.fields:
                attrs = self.fields[campo].widget.attrs
                for hx_attr in ['hx-get', 'hx-target', 'hx-swap', 'hx-trigger', 'hx-include']:
                    attrs.pop(hx_attr, None)

        # --- EL ESCUDO DEL SERVIDOR ---
        # Si la instancia ya existe y es de salario Fijo, bloqueamos el tridente desde Python
        if self.instance and self.instance.pk and self.instance.tipo_salario == 'FIJ':
            if 'tridente' in self.fields:
                self.fields['tridente'].widget.attrs['disabled'] = 'disabled'
                self.fields['tridente'].required = False

        # A) Radar de Tipos de Contrato oficiales
        tipos_plantilla = list(NTipoContrato.objects.filter(ocupa_plaza=True).values_list('id', flat=True))
        if 'tipo' in self.fields:
            self.fields['tipo'].widget.attrs['data-ocupa-plaza'] = json.dumps(tipos_plantilla)

        # B) LA CURA DE MOVIMIENTOS:
        if 'cargo' in self.fields and self.fields['cargo'].queryset.exists():
            cargos_qs = self.fields['cargo'].queryset
            mapa = {c.pk: {'aprobadas': c.cant_aprobada, 'ocupadas': c.plazas_fijas} for c in cargos_qs}
            
            if self.instance and self.instance.pk and getattr(self.instance.tipo, 'ocupa_plaza', False):
                if self.instance.cargo_id in mapa:
                    mapa[self.instance.cargo_id]['ocupadas'] = max(0, mapa[self.instance.cargo_id]['ocupadas'] - 1)

            # Reemplazamos el widget estándar por nuestro widget hipervitamínico
            nuevo_widget = SelectCargosConPlazasWidget(
                attrs={'class': 'form-select select2-cargo'}, 
                mapa_plazas=mapa
            )
            
            # Le pasamos el listado de opciones del campo original al nuevo widget
            nuevo_widget.choices = self.fields['cargo'].choices 
            
            self.fields['cargo'].widget = nuevo_widget