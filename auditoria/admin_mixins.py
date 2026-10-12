"""Mixins reutilizables para conectar cualquier ModelAdmin con `auditoria.EventoAuditoria`.

El Admin de Django no pasa por `solicitudes` (el único flujo que originalmente escribía
en Auditoría), así que sin esto una edición, eliminación o alta hecha desde el Admin no
dejaba ningún rastro. Nunca debe romper el guardado/borrado real si falla: todo va en
try/except, igual que el resto de integraciones "silenciosas" del proyecto (ver
`notificaciones/avisos.py`).
"""
import logging
from contextlib import contextmanager

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType

from auditoria.middleware import _user_ctx_var
from auditoria.models import AccionAuditoria
from auditoria.registro_automatico import es_auditado
from auditoria.servicios import registrar as registrar_auditoria

logger = logging.getLogger(__name__)


@contextmanager
def _como_usuario_de(request):
    """El usuario de la petición, para el registro automático de Auditoría.

    En una petición real ya lo pone `CurrentUserMiddleware`; esto lo garantiza
    también cuando el Admin se llama sin pasar por él (pruebas, scripts).
    """
    usuario = getattr(request, 'user', None)
    if usuario is None:
        yield
        return
    token = _user_ctx_var.set(usuario)
    try:
        yield
    finally:
        _user_ctx_var.reset(token)


class AuditoriaAdminMixin:
    """Audita crear/editar/eliminar (fila a fila, en bloque y vía inlines)."""

    modulo_auditoria = 'auditoria'

    def _registrar(self, request, accion, *, instancia=None, content_type=None,
                    object_id=None, descriptor=''):
        # Los modelos del registro automático ya dejan su evento, y además con el
        # antes/después de cada campo. Registrarlo también aquí lo duplicaría.
        modelo = type(instancia) if instancia is not None else (
            content_type.model_class() if content_type is not None else None)
        if modelo is not None and es_auditado(modelo):
            return
        try:
            registrar_auditoria(
                usuario=request.user, accion=accion, instancia=instancia,
                content_type=content_type, object_id=object_id,
                descriptor=descriptor or str(instancia)[:200],
                modulo=self.modulo_auditoria)
        except Exception:
            logger.exception(
                "No se pudo registrar en Auditoría la acción %s sobre %s.",
                accion, instancia if instancia is not None else object_id)

    def save_model(self, request, obj, form, change):
        with _como_usuario_de(request):
            super().save_model(request, obj, form, change)
        self._registrar(
            request, AccionAuditoria.MODIFICAR if change else AccionAuditoria.CREAR,
            instancia=obj)

    def delete_model(self, request, obj):
        content_type = ContentType.objects.get_for_model(type(obj))
        object_id, descriptor = str(obj.pk), str(obj)[:200]
        with _como_usuario_de(request):
            super().delete_model(request, obj)
        self._registrar(
            request, AccionAuditoria.ELIMINAR, content_type=content_type,
            object_id=object_id, descriptor=descriptor)

    def delete_queryset(self, request, queryset):
        content_type = ContentType.objects.get_for_model(queryset.model)
        congelados = [(str(o.pk), str(o)[:200]) for o in queryset]
        with _como_usuario_de(request):
            super().delete_queryset(request, queryset)
        for object_id, descriptor in congelados:
            self._registrar(
                request, AccionAuditoria.ELIMINAR, content_type=content_type,
                object_id=object_id, descriptor=descriptor)

    def save_formset(self, request, form, formset, change):
        """Audita altas/bajas/cambios hechos vía inlines (p. ej. NMunicipioInline
        dentro de NProvinciaAdmin), que Django NO pasa por save_model/delete_model:
        `ModelAdmin.save_formset()` por defecto solo llama a `formset.save()`.

        Los objetos a eliminar se congelan ANTES de `super().save_formset(...)`,
        leyendo `formset.deleted_forms` (disponible tras `is_valid()`, sin tocar la
        BD) en vez de `formset.deleted_objects` (que Django solo puebla DESPUÉS de
        llamar a `obj.delete()`, momento en que `obj.pk` ya quedó en `None` — mismo
        motivo por el que `delete_model`/`delete_queryset` de arriba congelan antes).
        """
        eliminados = [
            (ContentType.objects.get_for_model(type(f.instance)),
             str(f.instance.pk), str(f.instance)[:200])
            for f in formset.deleted_forms
        ]
        with _como_usuario_de(request):
            super().save_formset(request, form, formset, change)
        for content_type, object_id, descriptor in eliminados:
            self._registrar(
                request, AccionAuditoria.ELIMINAR, content_type=content_type,
                object_id=object_id, descriptor=descriptor)
        for obj in formset.new_objects:
            self._registrar(request, AccionAuditoria.CREAR, instancia=obj)
        for obj, _campos_cambiados in formset.changed_objects:
            self._registrar(request, AccionAuditoria.MODIFICAR, instancia=obj)


class AuditoriaSoloEdicionAdminMixin(AuditoriaAdminMixin):
    """Variante para modelos cuyo borrado ya se audita vía una señal `post_delete`
    (ver `contratos.models._al_eliminar_movimiento`, usada por `TMovimiento`).

    Solo audita crear/editar; el borrado NO se audita aquí a propósito, para no
    duplicar el evento que ya genera la señal (que además cubre TODOS los caminos
    de borrado: uno a uno, «Eliminar seleccionados» y acciones agrupadas custom, no
    solo el de este ModelAdmin).
    """

    def delete_model(self, request, obj):
        with _como_usuario_de(request):
            admin.ModelAdmin.delete_model(self, request, obj)

    def delete_queryset(self, request, queryset):
        with _como_usuario_de(request):
            admin.ModelAdmin.delete_queryset(self, request, queryset)
