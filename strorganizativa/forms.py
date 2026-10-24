from django import forms
from django.forms import widgets
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from nomencladores.models import NTipoUnidadOrganizativa, NMunicipio
from configuracion.models import Configuracion



class SelectNCargoConGrupoWidget(forms.Select):
    """
    Select del campo 'ncargo' que añade a cada <option>:
      - data-grupo    : nivel del Grupo Escala (tooltip de Select2).
      - data-usado-si : ese NCargo ya existe en el departamento DENTRO de la plantilla.
      - data-usado-no : ese NCargo ya existe en el departamento FUERA de la plantilla.
      - disabled      : si está bloqueado para el estado actual del switch «En Plantilla».

    Un mismo NCargo puede repetirse en el departamento como PAREJA: uno dentro
    de la plantilla aprobada y otro fuera. Nunca dos con el mismo estado. Por eso
    ya no basta un único conjunto de «usados»: hay que saber en qué lado está
    cada uno. El bloqueo definitivo lo decide `CargoPlantillaForm.clean`; esto
    solo pinta el desplegable, y el JS lo recalcula al mover el switch.
    """

    # Ids de NCargo ya usados en el departamento, separados por lado.
    # Los rellena CargoPlantillaForm.__init__
    ncargos_en_plantilla = frozenset()
    ncargos_fuera_plantilla = frozenset()
    # Estado del switch con el que se pinta el formulario (True = En Plantilla).
    en_plantilla_actual = True

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

            # --- ¿Este cargo ya existe en el departamento, y de qué lado? ---
            try:
                pk = int(getattr(value, 'value', value))
            except (TypeError, ValueError):
                pk = None

            if pk is not None:
                usado_si = pk in self.ncargos_en_plantilla
                usado_no = pk in self.ncargos_fuera_plantilla

                if usado_si:
                    option['attrs']['data-usado-si'] = 'true'
                if usado_no:
                    option['attrs']['data-usado-no'] = 'true'

                # Solo choca con el lado en el que se está creando/editando
                bloqueado = usado_si if self.en_plantilla_actual else usado_no
                if bloqueado:
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
        fields = ('ncargo', 'departamento', 'rol', 'nivel_preparacion', 'cant_aprobada', 'cant_cubierta', 'activo', 'en_plantilla', 'funcionario', 'designado', 'de_confianza', 'orden_informe')
        labels = {
            'ncargo': 'Cargo', 
            'departamento': 'Departamento', 
            'rol': 'Rol', 
            'nivel_preparacion': 'Nivel de Preparación',
            'cant_aprobada': 'Cantidad Aprobada', 
            'cant_cubierta': 'Cantidad Cubierta', 
            'activo': 'Estado (Automático)',
            'en_plantilla': 'En Plantilla',
            'de_confianza': 'De Confianza',
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
            'en_plantilla': forms.CheckboxInput(attrs={'class':'form-check-input', 'role': 'switch', 'id': 'id_en_plantilla'}),
            'funcionario': forms.CheckboxInput(attrs={'class':'form-check-input', 'id': 'id_funcionario'}),
            'designado': forms.CheckboxInput(attrs={'class':'form-check-input', 'id': 'id_designado'}),
            'de_confianza': forms.CheckboxInput(attrs={'class':'form-check-input', 'id': 'id_de_confianza'}),
            'orden_informe': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Ej: 1 (Mayor prioridad)'}),
        }
    
    # strorganizativa/forms.py (Corregido)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['ncargo'].queryset = self.fields['ncargo'].queryset.select_related('grupo_escala').order_by('descripcion')

        # --- Valor inicial del switch «En Plantilla» ---
        # Regla única de excepción: los cargos que cuelgan de una Unidad
        # Organizativa de tipo temporal nacen FUERA de la plantilla aprobada.
        # Es solo el valor de arranque: el usuario puede cambiarlo sin ninguna
        # restricción.
        dpto_id = self._obtener_departamento_id()

        if not self.instance.pk and 'en_plantilla' not in self.data:
            self.fields['en_plantilla'].initial = not self._departamento_es_temporal(dpto_id)

        en_plantilla_actual = self._en_plantilla_actual()

        # --- Cargos ya utilizados en este departamento (se muestran deshabilitados) ---
        # Un mismo NCargo admite PAREJA (uno dentro de la plantilla y otro fuera),
        # así que se separan por lado: solo bloquea el que choca con el estado
        # actual del switch.
        usados_si = set()
        usados_no = set()

        if dpto_id:
            qs_usados = CargoPlantilla.objects.filter(departamento_id=dpto_id)
            # En edición, el propio registro no debe bloquearse a sí mismo
            if self.instance.pk:
                qs_usados = qs_usados.exclude(pk=self.instance.pk)
            for ncargo_id, en_plantilla in qs_usados.values_list('ncargo_id', 'en_plantilla'):
                (usados_si if en_plantilla else usados_no).add(ncargo_id)

        widget_ncargo = self.fields['ncargo'].widget
        widget_ncargo.ncargos_en_plantilla = frozenset(usados_si)
        widget_ncargo.ncargos_fuera_plantilla = frozenset(usados_no)
        widget_ncargo.en_plantilla_actual = en_plantilla_actual

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

    @staticmethod
    def _departamento_es_temporal(dpto_id):
        """¿El departamento cuelga de una Unidad Organizativa de tipo temporal?"""
        if not dpto_id:
            return False
        return Departamento.objects.filter(
            pk=dpto_id, unidad_organizativa__tipo__es_temporal=True
        ).exists()

    def _en_plantilla_actual(self):
        """Estado del switch con el que se está pintando el formulario.

        Un checkbox que viene apagado NO aparece en el POST, así que en un
        formulario enviado la ausencia de la clave significa False. Fuera del
        POST manda la instancia (edición) y, si no la hay, el valor inicial.
        """
        if self.is_bound:
            return 'en_plantilla' in self.data
        if self.instance.pk:
            return bool(self.instance.en_plantilla)
        return bool(self.fields['en_plantilla'].initial)

    def _contrato_que_ocupa_plaza(self):
        """Contrato activo del cargo que consume plaza oficial, o None.

        Es lo único que impide sacar un cargo de la plantilla aprobada: si la
        plaza no es plantilla, no puede sostener un contrato que ocupe plaza.
        """
        if not self.instance.pk:
            return None

        from contratos.models import CAlta
        return (CAlta.objects
                .filter(cargo=self.instance,
                        aspirante__estado='ACTIVO',
                        tipo__ocupa_plaza=True)
                .select_related('tipo', 'aspirante')
                .first())

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

        # --- Un departamento no puede repetir el mismo NCargo EN EL MISMO LADO ---
        # Sí admite la pareja: uno dentro de la plantilla aprobada y otro fuera.
        en_plantilla = cleaned_data.get('en_plantilla')
        departamento = cleaned_data.get('departamento')
        if ncargo and departamento:
            duplicados = CargoPlantilla.objects.filter(
                departamento=departamento, ncargo=ncargo, en_plantilla=en_plantilla)
            if self.instance.pk:
                duplicados = duplicados.exclude(pk=self.instance.pk)
            if duplicados.exists():
                lado = ('dentro de la plantilla aprobada' if en_plantilla
                        else 'fuera de la plantilla aprobada')
                self.add_error(
                    'ncargo',
                    f'El cargo "{ncargo.descripcion}" ya existe {lado} en el departamento '
                    f'"{departamento.descripcion}". Un mismo cargo solo puede repetirse '
                    f'si uno está dentro de la plantilla aprobada y el otro fuera.'
                )

        # --- Sacar un cargo de la plantilla aprobada: solo si nadie ocupa plaza ---
        # Se comprueba únicamente en el sentido True -> False. Volver a meter un
        # cargo en la plantilla no rompe nada y no necesita permiso.
        if self.instance.pk and self.instance.en_plantilla and en_plantilla is False:
            if self._contrato_que_ocupa_plaza():
                self.add_error(
                    'en_plantilla',
                    'El cargo que desea sacar de la plantilla aprobada tiene asociado '
                    'un contrato indeterminado. Para poder quitar este cargo de la '
                    'plantilla aprobada, el contrato asociado no puede ser Indeterminado.'
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

    # Municipio: se filtra en __init__ según la provincia fijada en Parámetros
    # Generales (Configuracion.provincia_entidad). No depende de otro campo
    # del propio formulario, así que no hace falta cascada HTMX.
    municipio = forms.ModelChoiceField(
        queryset=NMunicipio.objects.none(),
        empty_label="Seleccione un municipio...",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_municipio'}),
        label="Municipio"
    )

    class Meta:
        model = UnidadOrganizativa
        # Inyectamos 'orden_informe' al principio de la lista
        fields = ['orden_informe', 'tipo', 'padre', 'descripcion', 'grupo_nomina', 'municipio']
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

        # Municipio disponible según la provincia configurada en Parámetros
        # Generales. Si aún no se ha definido, el select queda vacío.
        configuracion = Configuracion.objects.first()
        if configuracion and configuracion.provincia_entidad_id:
            self.fields['municipio'].queryset = (
                NMunicipio.objects.filter(provincia_id=configuracion.provincia_entidad_id).order_by('nombre')
            )
        else:
            self.fields['municipio'].widget.attrs['disabled'] = 'disabled'
            self.fields['municipio'].help_text = (
                'Defina la provincia de la entidad en Parámetros Generales para habilitar este campo.'
            )

    
        