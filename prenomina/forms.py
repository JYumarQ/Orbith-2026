"""Formularios de Pre-Nómina.

**Todo el CRUD del módulo pasa por aquí.** Es deliberado y es la razón por la
que no se copia el patrón de `nomencladores/views.py`, que lee `request.body` y
llama a `Model.objects.create(**datos)`: ese camino **no ejecuta `clean()`**, y
el requisito dice que la fórmula se valide *al guardar*, no al generar el
reporte.

Como el `ModelForm` es el mismo que usa `admin.py` (`ModelAdmin.form`), existe
una sola implementación de la validación en las tres superficies: modal HTMX,
panel de administración e importación.
"""

from datetime import date

from django import forms

from .models import (NClaveAusencia, NEscalaAnnosServicio, NPagoHoras,
                     NPagoImporte, TipoValorImporte)

# Clases de Bootstrap. Se declaran una vez para que las cuatro fichas se vean
# iguales sin repetir `attrs` en cada campo.
_TEXTO = {'class': 'form-control form-control-sm'}
_SELECT = {'class': 'form-select form-select-sm'}
_SWITCH = {'class': 'form-check-input'}

# El cálculo de las fechas del período vive en `servicios.limites_del_periodo()`:
# lo necesitan igual el formulario (para proponerlas) y la vista que refresca el
# bloque al cambiar de mes, y depende de la quincena, que es cosa del servicio.


class NPagoHorasForm(forms.ModelForm):
    class Meta:
        model = NPagoHoras
        fields = ('codigo', 'descripcion')
        widgets = {
            'codigo': forms.NumberInput(attrs={**_TEXTO, 'min': 1, 'step': 1}),
            'descripcion': forms.TextInput(
                attrs={**_TEXTO, 'placeholder': 'Ej.: Horas Extra'}),
        }


class NClaveAusenciaForm(forms.ModelForm):
    class Meta:
        model = NClaveAusencia
        fields = ('codigo', 'descripcion', 'resta_horas_mes',
                  'resta_sistema_pago', 'resta_utilidades', 'relacionado_con')
        widgets = {
            'codigo': forms.NumberInput(attrs={**_TEXTO, 'min': 1, 'step': 1}),
            'descripcion': forms.TextInput(
                attrs={**_TEXTO, 'placeholder': 'Ej.: Vacaciones'}),
            'resta_horas_mes': forms.CheckboxInput(attrs={**_SWITCH}),
            'resta_sistema_pago': forms.CheckboxInput(attrs={**_SWITCH}),
            'resta_utilidades': forms.CheckboxInput(attrs={**_SWITCH}),
            'relacionado_con': forms.Select(attrs={**_SELECT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['relacionado_con'].empty_label = '— Ninguno —'
        self.fields['relacionado_con'].required = False


class NPagoImporteForm(forms.ModelForm):
    """Ficha del pago por importe.

    La validación de la fórmula vive en `NPagoImporte.clean()`, no aquí: así el
    admin de Django y la importación la ejecutan sin depender de este formulario.
    Lo único que se hace en el formulario es normalizar los campos que el tipo de
    valor deja sin sentido, para que el `CheckConstraint` de la base de datos no
    salte con un error técnico cuando el usuario cambia de tipo y deja restos del
    anterior.
    """

    # Orden pensado para el modal: primero QUÉ es el concepto, después el tipo, y
    # debajo solo los campos de ese tipo (el modal oculta los demás).
    class Meta:
        model = NPagoImporte
        fields = ('codigo', 'descripcion', 'tipo_valor', 'importe_fijo',
                  'formula', 'relacionado_con')
        widgets = {
            'codigo': forms.NumberInput(attrs={**_TEXTO, 'min': 1, 'step': 1}),
            'descripcion': forms.TextInput(
                attrs={**_TEXTO, 'placeholder': 'Ej.: Importe Horas Extras'}),
            'relacionado_con': forms.Select(attrs={**_SELECT}),
            'tipo_valor': forms.Select(attrs={**_SELECT}),
            'importe_fijo': forms.NumberInput(
                attrs={**_TEXTO, 'min': 0, 'step': '0.01'}),
            'formula': forms.TextInput(
                attrs={**_TEXTO,
                       'placeholder': '{{horas}} * {{tarifa_horaria}} * 1.25',
                       'autocomplete': 'off'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['relacionado_con'].empty_label = '— Ninguno —'
        self.fields['relacionado_con'].required = False
        # El texto del modelo no cambia para no generar una migración solo por
        # una ayuda; la que ve el usuario es esta.
        self.fields['relacionado_con'].help_text = (
            'Si se indica, este importe se añade solo al reporte cuando se '
            'seleccione ese concepto por horas. Con importe fijo o escala, solo '
            'cobra quien tenga horas en él; en una fórmula, {{horas}} toma sus horas.')
        self.fields['importe_fijo'].required = False
        self.fields['formula'].required = False
        self.fields['formula'].help_text = (
            'Puede escribir los decimales con coma o con punto. El resultado no '
            'puede ser negativo.')

    def clean(self):
        """Limpia los campos que el tipo elegido deja sin sentido.

        Si el usuario escribió un importe, cambió a «Fórmula» y guardó, el
        importe viejo seguiría en el POST. Vaciarlo aquí convierte lo que sería
        un error de restricción de la base de datos en el comportamiento
        esperado. Las incoherencias *reales* (fórmula vacía en un concepto por
        fórmula) las sigue detectando `clean()` del modelo.
        """
        datos = super().clean()
        tipo = datos.get('tipo_valor')

        if tipo != TipoValorImporte.IMPORTE:
            datos['importe_fijo'] = None
        if tipo != TipoValorImporte.FORMULA:
            datos['formula'] = ''
        else:
            datos['formula'] = (datos.get('formula') or '').strip()

        return datos


class NEscalaAnnosServicioForm(forms.ModelForm):
    class Meta:
        model = NEscalaAnnosServicio
        fields = ('annos', 'cuantia')
        widgets = {
            'annos': forms.NumberInput(attrs={**_TEXTO, 'min': 1, 'step': 1}),
            'cuantia': forms.NumberInput(attrs={**_TEXTO, 'min': 0, 'step': '0.01'}),
        }


class ReportePagoForm(forms.Form):
    """Alta de un reporte de pago.

    Es un `Form` y no un `ModelForm` a propósito: la creación no es un
    `save()`, es la transición `servicios.crear_reporte()`, que además congela
    la unidad y carga los trabajadores. Un `ModelForm` invitaría a guardar el
    modelo por su cuenta y saltarse todo eso.

    El desplegable de unidades se acota al alcance del usuario por comodidad;
    la seguridad la impone `servicios.crear_reporte()`, que lo vuelve a
    comprobar.
    """

    MESES = [
        (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
        (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
        (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
    ]

    #: Aspecto de los campos que solo informan. `disabled` (y no un simple
    #: `readonly`) porque así Django ignora lo que llegue por POST y usa
    #: siempre el `initial`: es un dato que decide el servidor, no el usuario.
    _INFORMATIVO = {**_TEXTO, 'tabindex': '-1'}

    unidad = forms.ModelChoiceField(
        queryset=None, label='Unidad Organizativa',
        widget=forms.Select(attrs={**_SELECT}))
    # La plantilla decide qué conceptos llevará el reporte. Es obligatoria: sin
    # ella el reporte nacería sin columnas y habría que configurarlo aparte, que
    # es justo el flujo que se retiró al mover las plantillas a su propia
    # pantalla.
    plantilla = forms.ModelChoiceField(
        queryset=None, label='Plantilla',
        widget=forms.Select(attrs={**_SELECT}),
        help_text='Define los conceptos del reporte. Se gestionan en '
                  'Pre-Nómina → Mis Plantillas.')
    anno = forms.IntegerField(
        label='Año', min_value=2000, max_value=2100,
        widget=forms.NumberInput(attrs={**_TEXTO}))
    mes = forms.TypedChoiceField(
        label='Mes', choices=MESES, coerce=int,
        widget=forms.Select(attrs={**_SELECT}))
    # `fondo_tiempo` ya no se teclea: las horas del mes de cada trabajador salen
    # del Calendario de Pago según su jornada asignada, y el número de la
    # cabecera del documento lo deriva `servicios._fondo_de_referencia()` de la
    # jornada más repetida del reporte. Se mantiene el campo en el modelo porque
    # el Excel oficial imprime ese número en su encabezado.
    #
    # `fondo_tarifa` TAMPOCO se teclea ya. Era un divisor que el usuario nunca
    # decidía —siempre aceptaba el que se le proponía— y que ya vivía en
    # Configuración → Parámetros Generales, de donde lo toma ahora
    # `servicios._fondo_de_tarifa()`. El reporte lo sigue congelando en su
    # columna: un reporte cerrado debe poder recalcularse igual años después.

    # Solo informa. Es el período de pago declarado en Configuración → Parámetros
    # Generales, y es lo que decide si este mes admite un reporte o dos.
    periodo_pago = forms.CharField(
        label='Período de pago', required=False, disabled=True,
        widget=forms.TextInput(attrs={**_INFORMATIVO}),
        help_text='Se define en Configuración → Parámetros Generales.')
    fecha_desde = forms.DateField(
        label='Período de pago — desde',
        widget=forms.DateInput(attrs={**_TEXTO, 'type': 'date'}))
    fecha_hasta = forms.DateField(
        label='Período de pago — hasta',
        widget=forms.DateInput(attrs={**_TEXTO, 'type': 'date'}))

    # Las tres firmas del encabezado del documento. Se recuerdan por usuario
    # (`PreferenciasUsuario`), así que se escriben una vez y salen ya puestas en
    # todos los reportes siguientes hasta que quien las usa las cambie.
    hecho_por = forms.CharField(
        label='Hecho por', required=False, max_length=150,
        widget=forms.TextInput(attrs={**_TEXTO}))
    revisado_por = forms.CharField(
        label='Revisado por', required=False, max_length=150,
        widget=forms.TextInput(attrs={**_TEXTO}))
    aprobado_por = forms.CharField(
        label='Aprobado por', required=False, max_length=150,
        widget=forms.TextInput(attrs={**_TEXTO}))

    def __init__(self, *args, usuario=None, quincena=None, **kwargs):
        """`quincena` la pasa la vista que refresca el bloque del período.

        Sirve para proponer las fechas correctas (del 1 al 15, del 16 al final o
        el mes entero). Quién crea de verdad el reporte y con qué quincena lo
        decide `servicios.crear_reporte()` con la unidad bloqueada; esto es solo
        lo que se le enseña al usuario mientras rellena el formulario.
        """
        super().__init__(*args, **kwargs)
        from . import servicios
        from .filtros import unidades_gestionables
        from .models import PlantillaReporte, Quincena
        self.fields['unidad'].queryset = unidades_gestionables(usuario)
        self.fields['unidad'].empty_label = '— Seleccione —'

        # Solo las plantillas del propio usuario: son catálogos personales.
        self.fields['plantilla'].queryset = (
            PlantillaReporte.objects.filter(usuario=usuario)
            if usuario is not None else PlantillaReporte.objects.none())
        self.fields['plantilla'].empty_label = '— Seleccione —'

        quincenal = servicios.es_pago_quincenal()
        # `disabled=True` hace que Django tome SIEMPRE el `initial`, también en
        # un formulario enlazado, así que se asigna fuera del `if not is_bound`.
        self.initial['periodo_pago'] = 'Quincenal' if quincenal else 'Mensual'

        if not self.is_bound:
            hoy = date.today()
            anno = self.initial.get('anno') or hoy.year
            mes = self.initial.get('mes') or hoy.month
            self.initial.setdefault('anno', anno)
            self.initial.setdefault('mes', mes)

            # Sin unidad elegida todavía no se sabe qué quincena tocará, así que
            # se propone la primera: es la que corresponde en el caso normal —un
            # mes que aún no tiene ningún reporte—.
            if quincena is None:
                quincena = Quincena.PRIMERA if quincenal else Quincena.MES_COMPLETO
            desde, hasta = servicios.limites_del_periodo(anno, mes, quincena)
            self.initial.setdefault('fecha_desde', desde)
            self.initial.setdefault('fecha_hasta', hasta)

            for campo, valor in self._firmas_recordadas(usuario).items():
                self.initial.setdefault(campo, valor)

    @staticmethod
    def _firmas_recordadas(usuario):
        """Los tres nombres del encabezado, tal como los dejó este usuario.

        Se guardan en `PreferenciasUsuario` al crear cada reporte, así que quien
        prepara la nómina los escribe una vez y ya salen puestos siempre. Si
        nunca ha escrito el «Hecho por», se propone su propio nombre, que es lo
        que hacía `servicios.crear_reporte()` antes de existir esta memoria.
        """
        if usuario is None or not usuario.is_authenticated:
            return {}
        preferencias = usuario.obtener_preferencias()
        propio = (usuario.get_full_name() or '').strip() or usuario.get_username()
        return {
            'hecho_por': preferencias.reporte_hecho_por or propio[:150],
            'revisado_por': preferencias.reporte_revisado_por,
            'aprobado_por': preferencias.reporte_aprobado_por,
        }

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('fecha_desde'), datos.get('fecha_hasta')
        if desde and hasta and hasta < desde:
            self.add_error(
                'fecha_hasta',
                'La fecha final no puede ser anterior a la inicial.')
        return datos
