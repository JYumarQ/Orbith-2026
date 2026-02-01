from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import models
from auditoria.models import Base
from notificaciones.models import Notificacion
from strorganizativa.models import CargoPlantilla

User = get_user_model()

class TipoSolicitud(models.TextChoices):
    CREACION = 'ADD', 'Creacion'
    ELIMINAR = 'DEL', 'Eliminar'
    MODIFICAR = 'UPD', 'Modificar'

class EstadoSolicitud(models.TextChoices):
    ENVIADA = 'E', 'Enviada'
    EN_REVISION = 'R', 'En Revision'
    APROBADA = 'A', 'Aprobada'
    RECHAZADA = 'X', 'Rechazada'

class Solicitud(Base):
    tipo = models.CharField(max_length=3, choices=TipoSolicitud.choices)

    class Meta:
        abstract = True

class SolicitudCargo(Solicitud):
    cargo_origen =models.ForeignKey(CargoPlantilla, on_delete=models.CASCADE, related_name='solicitudes')
    estado = models.CharField(max_length=1, choices=EstadoSolicitud.choices, default=EstadoSolicitud.ENVIADA)

    # datos para el nuevo cargo (solo si es MODIFICAR)
    nuevo_cargo = models.ForeignKey(CargoPlantilla, null=True, blank=True, on_delete=models.PROTECT)
    motivo = models.TextField()

    fecha_vigor = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_vigor']

    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)

        if es_nuevo:
            Notificacion.objects.create(
                titulo= 'Nueva Solicitud Pendiente',
                mensaje = f"Se ha creado una nueva solicitud de "
                          f"{self.get_tipo_display()}.",
                content_type = ContentType.objects.get_for_model(self),
                object_id=str(self.pk),
                unidad = self.cargo_origen.departamento.unidad_organizativa
            )

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cargo_origen} ({self.get_estado_display()})"
