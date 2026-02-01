from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from auditoria.models import Base


# Create your models here.
class Notificacion(models.Model):
    
    titulo = models.CharField(max_length=150)
    mensaje  = models.TextField()
    fecha_creado = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)
    
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=50)
    objeto_relacionado = GenericForeignKey('content_type', 'object_id')

    unidad = models.ForeignKey('strorganizativa.UnidadOrganizativa', on_delete=models.CASCADE, null=True, blank=True)
    
    # url_destino = models.URLField(blank=True, null=True)  # URL a la vista correspondiente

    class Meta:
        verbose_name = ("Notificación")
        verbose_name_plural = ("Notificaciones")

    def __str__(self):
        return f"{self.titulo} - {self.mensaje}"

