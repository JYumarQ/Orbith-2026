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
    fecha_creado = models.DateField(auto_now_add=True)
    fecha_actualizado = models.DateTimeField(auto_now=True)
    
    
    class Meta:
        verbose_name = ("Usuario")
        verbose_name_plural = ("Usuarios")
        constraints = [
            CheckConstraint(
                check=~(Q(es_admin=True) & Q(es_moderador=True)),
                name='roles_exclusivos_admin_xor_moderador'
            )
        ]
        
    def clean(self):
        super().clean()
#no levantar para permitir autocorreccion en save
#if self.es_admin and self.es_moderador:
#raise ValidationError('No puede ser Administrador y Moderador a la vez.')

    def save(self, *args, **kwargs):
        """
        Auto-exclusión de roles + sincronía de permisos:
        - Si ambos vienen True, decide según el estado anterior:
        * Antes Admin y ahora también marcaron Moderador => queda Moderador.
        * Antes Moderador y ahora también marcaron Admin => queda Admin.
        * Caso ambiguo => prioriza Admin.
        - Admin => is_staff & is_superuser = True
        - Moderador o Solo lectura => is_staff & is_superuser = False
        """
        if self.es_admin and self.es_moderador:
            prefer_moderador = False
            if self.pk:
                prev = type(self).objects.filter(pk=self.pk).values('es_admin', 'es_moderador').first()
                if prev and prev['es_admin'] and not prev['es_moderador']:
                    prefer_moderador = True
            if prefer_moderador:
                self.es_admin = False
            else:
                self.es_moderador = False

        # Solo los admin entran a /admin/
        self.is_staff = bool(self.es_admin)
        self.is_superuser = bool(self.es_admin)

        # Guardar UNA única vez con todo coherente
        super().save(*args, **kwargs)
