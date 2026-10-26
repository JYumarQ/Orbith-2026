from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.conf import settings
from .middleware import get_current_user

class Base(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(class)s_created",
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(class)s_updated",
        null=True, blank=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Obtiene el usuario actual guardado por el middleware
        user = get_current_user()

        if user:
            # Solo asignar created_by en inserciones nuevas
            if getattr(self._state, 'adding', False) and self.created_by is None:
                self.created_by = user
            # Siempre asignar updated_by
            self.updated_by = user

        super().save(*args, **kwargs)  # Llama al save original


class AccionAuditoria(models.TextChoices):
    """Qué ocurrió realmente. Los valores coinciden a propósito con
    `solicitudes.models.AccionSolicitud` (ADD/UPD/DEL) para las tres primeras."""
    CREAR = 'ADD', 'Creación'
    MODIFICAR = 'UPD', 'Modificación'
    ELIMINAR = 'DEL', 'Eliminación'
    RECHAZAR = 'REC', 'Rechazo'
    CANCELAR = 'CAN', 'Cancelación'
    DEVOLVER_A_ESPERA = 'DEV', 'Devuelta a espera'
    # El ciclo del trabajador. Tienen acción propia para no confundirse con crear,
    # editar o borrar un contrato a mano: un movimiento de nómina NO es editar el
    # contrato, y una baja NO es borrarlo (pasa a la lista de Bajas).
    ALTA = 'ALT', 'Alta'
    MOVIMIENTO = 'MOV', 'Movimiento de nómina'
    BAJA = 'BAJ', 'Baja'
    # Accesos al sistema. No afectan a ningún registro (`content_type` y
    # `object_id` quedan a null): el hecho auditado es la entrada o salida en sí.
    ACCESO = 'ACC', 'Inicio de sesión'
    ACCESO_FALLIDO = 'ACF', 'Intento de acceso fallido'
    SALIDA = 'SAL', 'Cierre de sesión'


class EventoAuditoria(models.Model):
    """Hecho inmutable: quién hizo qué, sobre qué, cuándo. Se escribe una única vez
    desde `auditoria.servicios.registrar()`; nada más en el proyecto debe crear,
    editar ni borrar filas de este modelo."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_auditoria', verbose_name='Usuario')
    # Congelado, mismo criterio que Solicitud.solicitante_nombre: si el usuario se
    # elimina más adelante, el listado no debe quedar en blanco.
    usuario_nombre = models.CharField(max_length=150, blank=True, default='')

    fecha = models.DateTimeField(auto_now_add=True)

    accion = models.CharField(max_length=3, choices=AccionAuditoria.choices)

    # Origen del cambio. CharField libre (no choices estrictas) para no requerir
    # migración cuando se integren otros módulos en fases futuras. Sus nombres
    # legibles están en `auditoria.registro_automatico.NOMBRES_DE_MODULO`.
    modulo = models.CharField(max_length=30, blank=True, default='solicitudes')

    # Registro real afectado. Null en rechazos/cancelaciones de una operación de
    # creación, donde el registro nunca llegó a existir.
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True,
        verbose_name='Modelo afectado')
    object_id = models.CharField(max_length=50, null=True, blank=True)
    objeto_afectado = GenericForeignKey('content_type', 'object_id')

    # Texto legible congelado, igual que Solicitud.descriptor: sobrevive a que el
    # registro real se elimine.
    descriptor = models.CharField(max_length=200, blank=True, default='')
    # Nombre del permiso especial con el que un Moderador hizo esto (25-10-2026);
    # vacío si no se usó ninguno. Ver `usuarios/permisos_especiales.py`.
    permiso_especial = models.CharField(max_length=60, blank=True, default='')

    datos_antes = models.JSONField(default=dict, blank=True)
    datos_despues = models.JSONField(default=dict, blank=True)

    unidad = models.ForeignKey(
        'strorganizativa.UnidadOrganizativa', on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='Unidad Organizativa')

    # Único caso de esta entrega: siempre viene de una Solicitud. Queda opcional para
    # cuando existan ediciones directas por Administrador en fases futuras.
    solicitud = models.ForeignKey(
        'solicitudes.Solicitud', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_auditoria', verbose_name='Solicitud de origen')

    class Meta:
        verbose_name = 'Evento de Auditoría'
        verbose_name_plural = 'Eventos de Auditoría'
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['accion', 'fecha']),
            models.Index(fields=['usuario', 'fecha']),
            models.Index(fields=['content_type', 'object_id']),
            # Filtro por módulo de la pantalla de Auditoría.
            models.Index(fields=['modulo', 'fecha']),
        ]

    def __str__(self):
        return f'{self.get_accion_display()} — {self.descriptor or "(sin descripción)"}'
