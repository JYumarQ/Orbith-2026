from django.db import models
from django.contrib.auth.models import AbstractUser
from strorganizativa.models import UnidadOrganizativa
from contratos.models import CAlta
from django.core.exceptions import ValidationError
from django.db.models import Q, CheckConstraint

# Create your models here.
class CustomUser(AbstractUser):
    
    #? DATOS PERSONALES
    contrato = models.OneToOneField(CAlta, on_delete=models.SET_NULL, null=True, blank=True)
    
    unidades = models.ManyToManyField(UnidadOrganizativa, blank=True)

    es_admin = models.BooleanField(default=False)
    es_moderador = models.BooleanField(default=False)
    es_observador = models.BooleanField(default=False)
    fecha_creado = models.DateField(auto_now_add=True)
    fecha_actualizado = models.DateTimeField(auto_now=True)
    
    
    class Meta:
        verbose_name = ("Usuario")
        verbose_name_plural = ("Usuarios")
        constraints = [
            # Un usuario solo puede tener UN rol activo
            CheckConstraint(
                check=(
                    Q(es_admin=True) & Q(es_moderador=False) & Q(es_observador=False) |
                    Q(es_admin=False) & Q(es_moderador=True) & Q(es_observador=False) |
                    Q(es_admin=False) & Q(es_moderador=False) & Q(es_observador=True) 

                ),
                name='exactamente_un_rol'
            )
        ]
        
    def clean(self):
        super().clean()
        roles_activos = sum([self.es_admin, self.es_moderador, self.es_observador])
        if roles_activos == 0:
            raise ValidationError("El usuario debe tener al menos un rol asignado (Administrador, Moderador o Observador).")
        if roles_activos > 1:
            raise ValidationError("El usuario no puede tener más de un rol activo.")
#no levantar para permitir autocorreccion en save
#if self.es_admin and self.es_moderador:
#raise ValidationError('No puede ser Administrador y Moderador a la vez.')

    def save(self, *args, **kwargs):
        # Resolución de conflictos (si hay más de un rol, prioriza Admin > Moderador > Observador)
        if self.es_admin and self.es_moderador:
            self.es_moderador = False
        if self.es_admin and self.es_observador:
            self.es_observador = False
        if self.es_moderador and self.es_observador:
            self.es_observador = False

        # Permisos de staff/superuser
        self.is_staff = bool(self.es_admin)
        self.is_superuser = bool(self.es_admin)

        # 👇 Ejecuta validaciones antes de guardar
        self.full_clean()  # Lanza ValidationError si roles_activos == 0 o > 1

        super().save(*args, **kwargs)