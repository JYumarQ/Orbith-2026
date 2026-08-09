"""Formularios propios del módulo.

Deliberadamente pocos. Los datos del cambio propuesto NO se capturan con formularios de
este módulo, sino con los ModelForm que ya existen en el módulo de cada entidad
(`NCargoForm`, `DepartamentoForm`, ...), resueltos desde `solicitudes/operaciones.py`.
Duplicarlos aquí significaría mantener dos veces los mismos campos, etiquetas y
validaciones, y garantizaría que tarde o temprano divergieran de los originales.

Lo que sí vive aquí es lo que rodea a esos datos: elegir qué se quiere solicitar y por
qué, y motivar una decisión.
"""

from django import forms
from django.urls import reverse_lazy

from solicitudes.operaciones import definicion_de, operaciones_desde_tabla


class SolicitudDesdeTablaForm(forms.Form):
    """Cabecera del alta manual de una solicitud desde el botón «Añadir Solicitud».

    Solo aplica a las operaciones marcadas con `desde_tabla` en el catálogo —hoy, las dos
    de NCargo—. El resto de operaciones nacen del formulario de su propio módulo y nunca
    pasan por aquí.

    Los campos del registro en sí (descripción, grupo de escala, salario...) NO están en
    este formulario: se cargan por HTMX debajo, con el ModelForm real de la operación
    elegida, y llegan en el mismo POST. Así el Moderador rellena exactamente los mismos
    campos que rellenaría un Administrador haciéndolo directamente.
    """

    operacion = forms.ChoiceField(
        label='¿Qué desea solicitar?',
        choices=[],
        widget=forms.Select(attrs={
            'class': 'form-select',
            'hx-get': reverse_lazy('campos_solicitud'),
            'hx-target': '#campos-de-la-operacion',
            'hx-trigger': 'change',
            'hx-include': '[name="registro"]',
        }))

    # El widget real de este campo NO se renderiza con `{{ form.registro }}`: el select
    # se pinta a mano en `add_solicitud.html`/`campos_operacion.html`, porque sus
    # opciones dependen de la operación elegida y tienen que refrescarse por HTMX con un
    # swap fuera de banda (ver `solicitudes/views.py::campos_solicitud`). El campo se
    # conserva aquí solo para la validación del lado servidor.
    registro = forms.ChoiceField(
        label='Registro a modificar', choices=[], required=False)

    motivo = forms.CharField(
        label='Motivo de la solicitud',
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3, 'class': 'form-control',
            'placeholder': 'Opcional: explique brevemente por qué solicita este cambio.'}),
        help_text='Lo verá el Administrador que revise la solicitud.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['operacion'].choices = [('', 'Seleccione…')] + operaciones_desde_tabla()
        self.fields['registro'].choices = [('', 'Seleccione…')] + self._opciones_de_registro()

    def _opciones_de_registro(self):
        """Registros elegibles para la operación seleccionada.

        Se construye desde el modelo declarado en el catálogo, no desde una lista fija,
        para que siga funcionando si mañana se marca otra operación como `desde_tabla`.
        """
        clave = self.data.get('operacion') or self.initial.get('operacion')
        if not clave:
            return []
        try:
            definicion = definicion_de(clave)
        except KeyError:
            return []
        if definicion['accion'] == 'ADD':
            return []
        return [(objeto.pk, str(objeto))
                for objeto in definicion['modelo'].objects.all().order_by('pk')]

    def clean(self):
        datos = super().clean()
        clave = datos.get('operacion')
        if not clave:
            return datos

        try:
            definicion = definicion_de(clave)
        except KeyError:
            self.add_error('operacion', 'Esa operación no está disponible.')
            return datos

        # Editar exige decir qué se edita. Sin esta comprobación la solicitud se crearía
        # sin registro afectado y no habría contra qué comparar en la revisión.
        if definicion['accion'] != 'ADD' and not datos.get('registro'):
            self.add_error('registro', 'Indique qué registro desea modificar.')

        return datos

    @property
    def objeto_seleccionado(self):
        """Instancia elegida en `registro`, o None en las operaciones de creación."""
        clave = self.cleaned_data.get('operacion')
        pk = self.cleaned_data.get('registro')
        if not clave or not pk:
            return None
        definicion = definicion_de(clave)
        return definicion['modelo'].objects.filter(pk=pk).first()


class MotivoDecisionForm(forms.Form):
    """Motivo del rechazo. Obligatorio a propósito.

    El Moderador recibe este texto en su notificación: un rechazo sin explicación le deja
    sin saber si debe corregir algo y volver a enviarlo o si la petición no procede.
    """

    motivo_decision = forms.CharField(
        label='Motivo del rechazo',
        widget=forms.Textarea(attrs={
            'rows': 3, 'class': 'form-control',
            'placeholder': 'Explique por qué se rechaza esta solicitud.'}))


class MotivoSolicitudForm(forms.Form):
    """Motivo suelto, para los envíos que nacen de un formulario de otro módulo.

    Se inyecta en esos formularios junto al aviso de «esto se enviará como solicitud»,
    de modo que el Moderador no tenga que pasar por una segunda pantalla solo para
    escribir la justificación.
    """

    motivo = forms.CharField(
        label='Motivo de la solicitud',
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2, 'class': 'form-control',
            'placeholder': 'Opcional: explique por qué solicita este cambio.'}))
