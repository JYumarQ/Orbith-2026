from cProfile import label
from dataclasses import fields
from pyexpat import model
from django import forms
from django.forms import widgets
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from nomencladores.models import NTipoUnidadOrganizativa



class SelectNCargoConGrupoWidget(forms.Select):
    """
    Select del campo 'ncargo' que añade a cada <option>:
      - data-grupo : nivel del Grupo Escala (tooltip de Select2).
      - disabled   : si ese NCargo ya está usado en el departamento actual.
    """

    # Ids de NCargo ya usados en el departamento.
    # Lo rellena CargoPlantillaForm.__init__
    ncargos_usados = frozenset()

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )

        # La opción vacía ("---------") llega con value = '' -> se ignora
        if value:
            # --- Grupo Escala (para el tooltip) ---
            instancia = getattr(value, 'instance', None)
            grupo = getattr(instancia, 'grupo_escala', None) if instancia else None
            if grupo is not None:
                option['attrs']['data-grupo'] = grupo.nivel

            # --- ¿Este cargo ya existe en el departamento? ---
            try:
                pk = int(getattr(value, 'value', value))
            except (TypeError, ValueError):
                pk = None

            if pk is not None and pk in self.ncargos_usados:
                option['attrs']['disabled'] = True     # Select2 lo respeta de forma nativa
                option['attrs']['data-usado'] = 'true'  # Para el gris del templateResult

        return option
    
#CARGO
class CargoPlantillaForm(forms.ModelForm):
    unidad = forms.ModelChoiceField(
        label='Unidad Organizativa',
        queryset=UnidadOrganizativa.objects.all(),
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
        fields = ('ncargo', 'departamento', 'rol', 'nivel_preparacion', 'cant_aprobada', 'cant_cubierta', 'activo', 'funcionario', 'designado', 'orden_informe')
        labels = {
            'ncargo': 'Cargo', 
            'departamento': 'Departamento', 
            'rol': 'Rol', 
            'nivel_preparacion': 'Nivel de Preparación',
            'cant_aprobada': 'Cantidad Aprobada', 
            'cant_cubierta': 'Cantidad Cubierta', 
            'activo': 'Estado (Automático)',
            'orden_informe': 'Orden de Prioridad',
        }
        widgets = {
            'ncargo': SelectNCargoConGrupoWidget(attrs={'class':'form-select js-cargo-select', 'id':'id_ncargo', 'style': 'width: 100%'}),
            'departamento': forms.Select(attrs={'class':'form-select'}),
            'rol': forms.Select(attrs={'class':'form-select', 'id':'id_rol'}),
            'nivel_preparacion': forms.Select(attrs={'class':'form-select', 'id':'id_nivel_preparacion'}),
            'cant_aprobada': forms.NumberInput(attrs={'class': 'form-control'}),
            'cant_cubierta': forms.NumberInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class':'form-check-input', 'disabled': 'disabled', 'id': 'id_activo'}),
            'funcionario': forms.CheckboxInput(attrs={'class':'form-check-input', 'id': 'id_funcionario'}),
            'designado': forms.CheckboxInput(attrs={'class':'form-check-input', 'id': 'id_designado'}),
            'orden_informe': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Ej: 1 (Mayor prioridad)'}),
        }
    
    # strorganizativa/forms.py (Corregido)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['ncargo'].queryset = self.fields['ncargo'].queryset.select_related('grupo_escala').order_by('descripcion')

        # --- Cargos ya utilizados en este departamento (se muestran deshabilitados) ---
        dpto_id = self._obtener_departamento_id()
        usados = set()

        if dpto_id:
            qs_usados = CargoPlantilla.objects.filter(departamento_id=dpto_id)
            # En edición, el propio registro no debe bloquearse a sí mismo
            if self.instance.pk:
                qs_usados = qs_usados.exclude(pk=self.instance.pk)
            usados = set(qs_usados.values_list('ncargo_id', flat=True))

        self.fields['ncargo'].widget.ncargos_usados = frozenset(usados)

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
                    Departamento.objects.filter(unidad_organizativa_id=unidad_id).order_by('orden_informe', 'id')
                )
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and getattr(self.instance, 'departamento', None):
            # Editar: precargar unidad y departamentos de esa unidad
            self.fields['unidad'].initial = self.instance.departamento.unidad_organizativa
            self.fields['departamento'].queryset = (
                self.instance.departamento.unidad_organizativa.departamentos.all().order_by('orden_informe', 'id')
            )
        else:
            self.fields['departamento'].queryset = Departamento.objects.none()

    def _obtener_departamento_id(self):
        """
        Devuelve el id del departamento sobre el que se está trabajando.
        Orden de búsqueda: instancia (edición) -> POST -> initial (creación por GET).
        """
        if self.instance.pk and self.instance.departamento_id:
            return self.instance.departamento_id

        valor = self.data.get('departamento') or self.initial.get('departamento')
        if not valor:
            return None

        # 'initial' puede traer el objeto Departamento; 'data' trae texto
        valor = getattr(valor, 'pk', valor)
        try:
            return int(valor)
        except (TypeError, ValueError):
            return None

        
    def clean(self):
        cleaned_data = super().clean()
        funcionario = cleaned_data.get('funcionario')
        designado = cleaned_data.get('designado')

        if funcionario and designado:
            self.add_error(
                'funcionario',
                'No puede ser Funcionario y Designado simultáneamente.'
            )
            self.add_error(                 # <--- Fíjate que esto ahora está dentro del 'if'
                'designado',
                'No puede ser Funcionario y Designado simultáneamente.'
            )
            
        ncargo = cleaned_data.get('ncargo')
        rol = cleaned_data.get('rol')

        # --- Un departamento no puede repetir el mismo NCargo ---
        departamento = cleaned_data.get('departamento')
        if ncargo and departamento:
            duplicados = CargoPlantilla.objects.filter(departamento=departamento, ncargo=ncargo)
            if self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                self.add_error(
                    'ncargo',
                    f'El cargo "{ncargo.descripcion}" ya existe en el departamento "{departamento.descripcion}".'
                )

        # --- La posición de orden no puede repetirse dentro del departamento ---
        # Si el usuario autorizó desplazar, no hay conflicto que reportar:
        # la posición se libera en la misma transacción que el guardado.
        if self.data.get('autoriza_desplazamiento') != 'true':
            departamento = cleaned_data.get('departamento')
            orden = cleaned_data.get('orden_informe')

            if departamento and orden is not None:
                ocupados = CargoPlantilla.objects.filter(
                    departamento=departamento,
                    orden_informe=orden
                )
                if self.instance.pk:
                    ocupados = ocupados.exclude(pk=self.instance.pk)

                ocupado = ocupados.select_related('ncargo').first()
                if ocupado:
                    self.add_error(
                        'orden_informe',
                        f'La posición {orden} ya está ocupada por "{ocupado.ncargo.descripcion}" '
                        f'en este departamento.'
                    )
        
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
        # Movimos 'orden_informe' al final de la lista
        fields = ('descripcion', 'unidad_organizativa', 'orden_informe') 
        labels = {
            'descripcion': 'Descripción', 
            'unidad_organizativa': 'Unidad Organizativa',
            'orden_informe': 'Orden de Prioridad'
        }
        widgets = {
            'orden_informe': forms.NumberInput(attrs={
                'class': 'form-control', 
                'min': '1', 
                'placeholder': 'Ej: 1 (Mayor prioridad)'
            }),
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

    def _autoriza_desplazamiento(self):
        """
        Indica si el usuario confirmó en el SweetAlert que quiere intercalar
        y desplazar los departamentos siguientes.
        """
        return self.data.get('autoriza_desplazamiento') == 'true'

    
    def clean(self):
        cleaned_data = super().clean()

        # Si el usuario ya autorizó desplazar, no hay conflicto que reportar
        if self._autoriza_desplazamiento():
            return cleaned_data

        unidad = cleaned_data.get('unidad_organizativa')
        orden = cleaned_data.get('orden_informe')

        if unidad and orden is not None:
            ocupados = Departamento.objects.filter(
                unidad_organizativa=unidad,
                orden_informe=orden
            )
            if self.instance.pk:
                ocupados = ocupados.exclude(pk=self.instance.pk)

            ocupado = ocupados.first()
            if ocupado:
                self.add_error(
                    'orden_informe',
                    f'La posición {orden} ya está ocupada por "{ocupado.descripcion}" '
                    f'en esta unidad organizativa.'
                )

        return cleaned_data


class SelectTipoNomencladorWidget(forms.Select):
    """Widget que inyecta data-subunidad a las opciones según la BD"""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value:
            try:
                pk = int(getattr(value, 'value', value))
                from nomencladores.models import NTipoUnidadOrganizativa
                tipo = NTipoUnidadOrganizativa.objects.get(pk=pk)
                if tipo.es_subunidad:
                    option['attrs']['data-subunidad'] = 'true'
            except Exception:
                pass
        return option
    
class SelectPadreWidget(forms.Select):
    """Widget que inyecta data-grupo-nomina a las opciones según la Unidad Principal"""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value:
            try:
                pk = int(getattr(value, 'value', value))
                from strorganizativa.models import UnidadOrganizativa
                padre = UnidadOrganizativa.objects.get(pk=pk)
                if padre.grupo_nomina is not None:
                    option['attrs']['data-grupo-nomina'] = str(padre.grupo_nomina)
            except Exception:
                pass
        return option

#UNIDAD ORGANIZATIVA
class UnidadOrganizativaForm(forms.ModelForm):
    
    tipo = forms.ModelChoiceField(
        queryset=NTipoUnidadOrganizativa.objects.all(),
        empty_label="Seleccione un tipo...",
        widget=SelectTipoNomencladorWidget(attrs={'class': 'form-select', 'id': 'id_tipo'}), # 🟢 CORREGIDO AQUÍ
        label="Tipo de Unidad"
    )
    # NUEVO: Selector de Unidad Principal (Aparecerá en el orden 2)
    padre = forms.ModelChoiceField(
        queryset=UnidadOrganizativa.objects.none(), 
        empty_label="Seleccione la Unidad Principal...",
        required=False,
        widget=SelectPadreWidget(attrs={'class': 'form-select', 'id': 'id_padre'}), # <--- CAMBIADO AQUÍ
        label="Unidad Principal Asociada"
    )

    class Meta:
        model = UnidadOrganizativa
        # Inyectamos 'orden_informe' al principio de la lista
        fields = ['orden_informe', 'tipo', 'padre', 'descripcion', 'grupo_nomina'] 
        labels = {
            'orden_informe': 'Orden de Prioridad',
            'grupo_nomina': 'Grupo de Nómina',
            'descripcion': 'Descripción',
        }
        widgets = {
            'orden_informe': forms.NumberInput(attrs={
                'class': 'form-control', 
                'min': '1',
                'placeholder': 'Ej: 1 (Mayor prioridad)'
            }),
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

    
        