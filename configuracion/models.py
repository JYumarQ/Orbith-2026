from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from auditoria.models import Base

# Create your models here.
class Configuracion(Base):
    
    #?GENERALES
    nombre_empresa = models.CharField(max_length=100)
    org_superior = models.CharField(max_length=50, blank=True, null=True)
    unidad_presup = models.BooleanField(default=False)
    rama = models.CharField(max_length=50, blank=True, null=True)
    moneda_local = models.CharField(max_length=10, default='CUP')
    periodo = models.PositiveIntegerField(default=15, validators=[MinValueValidator(7)], null=False, blank=False)
    fondo_tiempo_calc_tarif = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('190.6'), null=False, blank=False)
    correo = models.EmailField(null=True, blank=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    direccion = models.TextField(max_length=200, blank=True, null=True)
    logo = models.ImageField(upload_to='img/empr/', blank=True, null=True)
    
    
    class Meta:
        verbose_name = ("Configuracion")
        verbose_name_plural = ("Configuraciones")

    def __str__(self):
        return f"Configuracion: {self.nombre_empresa}"
    
    def save(self, *args, **kwargs):
        if not self.pk and Configuracion.objects.exists():
            raise ValueError('Ya existe una configuracion')
        super().save(*args, **kwargs)

