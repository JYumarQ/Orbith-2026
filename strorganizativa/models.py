from django.db import models
from notificaciones.models import Notificacion
from django.contrib.contenttypes.models import ContentType
from nomencladores.models import NCargo, NRol
from auditoria.models import Base

# Create your models here.
class UnidadOrganizativa(Base):

    grupo_nomina = models.IntegerField(primary_key=True, blank=False, null=False)
    descripcion = models.CharField(max_length=150, blank=False, null=False)
    tipo = models.CharField(max_length=50, choices=[
        ('UEB','UEB'),
        ('DF','Dirección Funcional'),
        ('DG','Dirección General')
    ])

    class Meta:
        verbose_name = ("Unidad Organizativa")
        verbose_name_plural = ("Unidades Organizativas")

    def __str__(self):
        return self.descripcion
    
class Departamento(Base):

    descripcion = models.CharField(max_length=150, blank=False, null=False)
    unidad_organizativa = models.ForeignKey(UnidadOrganizativa, on_delete=models.RESTRICT)

    class Meta:
        verbose_name = ("Departamento")
        verbose_name_plural = ("Departamentos")
        
    def __str__(self):
        return f"Dpto. {self.descripcion}"

class CargoPlantilla(Base):

    ncargo = models.ForeignKey(NCargo, verbose_name='Nomenclador de Cargo', on_delete=models.RESTRICT)
    departamento = models.ForeignKey(Departamento, on_delete=models.RESTRICT)
    rol = models.ForeignKey(NRol, verbose_name=('Nomenclador de Rol'), on_delete=models.RESTRICT, null=True, blank=True)
    cant_aprobada = models.IntegerField()
    cant_cubierta = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = ("Cargo")
        verbose_name_plural = ("Cargos")
        
    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)  # Guarda primero para obtener el PK

        if es_nuevo:
            Notificacion.objects.create(
                titulo="Nuevo Cargo creado",
                mensaje=f"Se ha creado un nuevo cargo: {self.ncargo.descripcion} en {self.departamento}.",
                content_type=ContentType.objects.get_for_model(self),
                object_id=str(self.pk),  # ¡Convertir a string para coincidir con CharField!
                unidad = self.departamento.unidad_organizativa

            )

    def __str__(self):
        return self.ncargo.descripcion

