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

import calendar
from datetime import date
from decimal import Decimal

from django import forms

from .models import (NClaveAusencia, NEscalaAnnosServicio, NPagoHoras,
                     NPagoImporte, TipoValorImporte)

# Clases de Bootstrap. Se declaran una vez para que las cuatro fichas se vean
# iguales sin repetir `attrs` en cada campo.
_TEXTO = {'class': 'form-control form-control-sm'}
_SELECT = {'class': 'form-select form-select-sm'}
_SWITCH = {'class': 'form-check-input'}


def _limites_del_mes(anno, mes):
    """Primer y último día del mes, para prerrellenar el período de pago."""
    return date(anno, mes, 1), date(anno, mes, calendar.monthrange(anno, mes)[1])


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

    class Meta:
        model = NPagoImporte
        fields = ('codigo', 'descripcion', 'relacionado_con', 'tipo_valor',
                  'importe_fijo', 'formula')
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
        self.fields['importe_fijo'].required = False
        self.fields['formula'].required = False

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
    fondo_tarifa = forms.DecimalField(
        label='Fondo para la tarifa horaria', min_value=Decimal('0.01'),
        max_digits=6, decimal_places=2,
        widget=forms.NumberInput(attrs={**_TEXTO, 'step': '0.01'}),
        help_text='Divisor con el que se obtiene la tarifa horaria a partir del '
                  'salario. Es una magnitud distinta de las horas del mes.')
    fecha_desde = forms.DateField(
        label='Período de pago — desde',
        widget=forms.DateInput(attrs={**_TEXTO, 'type': 'date'}))
    fecha_hasta = forms.DateField(
        label='Período de pago — hasta',
        widget=forms.DateInput(attrs={**_TEXTO, 'type': 'date'}))
    hecho_por = forms.CharField(
        label='Hecho por', required=False, max_length=150,
        widget=forms.TextInput(attrs={**_TEXTO}))

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .filtros import unidades_gestionables
        from .models import PlantillaReporte
        self.fields['unidad'].queryset = unidades_gestionables(usuario)
        self.fields['unidad'].empty_label = '— Seleccione —'

        # Solo las plantillas del propio usuario: son catálogos personales.
        self.fields['plantilla'].queryset = (
            PlantillaReporte.objects.filter(usuario=usuario)
            if usuario is not None else PlantillaReporte.objects.none())
        self.fields['plantilla'].empty_label = '— Seleccione —'

        if not self.is_bound:
            self.initial.setdefault('fondo_tarifa', self._fondo_de_tarifa())
            hoy = date.today()
            self.initial.setdefault('anno', hoy.year)
            self.initial.setdefault('mes', hoy.month)
            primero, ultimo = _limites_del_mes(hoy.year, hoy.month)
            self.initial.setdefault('fecha_desde', primero)
            self.initial.setdefault('fecha_hasta', ultimo)

    @staticmethod
    def _fondo_de_tarifa():
        """Sugerencia tomada de la configuración global de Orbith.

        Es solo el valor inicial: una vez creado el reporte queda congelado en
        él, así que cambiar la configuración más adelante no altera ningún
        reporte existente.
        """
        from configuracion.models import Configuracion
        configuracion = Configuracion.objects.first()
        if configuracion and configuracion.fondo_tiempo_calc_tarif:
            return configuracion.fondo_tiempo_calc_tarif
        return Decimal('190.60')

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('fecha_desde'), datos.get('fecha_hasta')
        if desde and hasta and hasta < desde:
            self.add_error(
                'fecha_hasta',
                'La fecha final no puede ser anterior a la inicial.')
        return datos
