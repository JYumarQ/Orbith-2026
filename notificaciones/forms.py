from django import forms

from strorganizativa.models import UnidadOrganizativa


class RecordatorioManualForm(forms.Form):
    """Formulario de creación de un Recordatorio manual (subpestaña Administración).

    Simple a propósito (título, mensaje, fecha objetivo, unidad): solo se abre desde
    dentro de la propia pestaña Recordatorios, nunca desde un enlace externo de
    Subsanación/Advertencias, así que no necesita el mixin `ModalOPaginaCompletaMixin`
    ni el patrón `next`.
    """
    titulo = forms.CharField(max_length=150, label='Título')
    mensaje = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), label='Mensaje')
    fecha_objetivo = forms.DateField(
        label='Fecha objetivo', widget=forms.DateInput(attrs={'type': 'date'}))
    unidad = forms.ModelChoiceField(
        queryset=UnidadOrganizativa.objects.order_by('descripcion'),
        label='Unidad organizativa')
