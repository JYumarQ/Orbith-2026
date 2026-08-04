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

    avatar = models.ImageField(
        upload_to='img/avatares/',
        blank=True,
        null=True,
        verbose_name="Foto de perfil"
    )


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

    # ------------------------------------------------------------------
    # DATOS PARA EL PERFIL
    # Los datos personales NO viven en first_name/last_name (el proyecto no los
    # usa): siempre se leen del trabajador vinculado (contrato -> aspirante).
    # Todas estas propiedades devuelven None si no hay contrato vinculado, para
    # que la plantilla pueda mostrar "Sin trabajador vinculado".
    # ------------------------------------------------------------------
    @property
    def aspirante_vinculado(self):
        """Trabajador asociado al usuario, o None si es una cuenta sin contrato."""
        if self.contrato_id and self.contrato:
            return self.contrato.aspirante
        return None

    @property
    def nombre_completo(self):
        asp = self.aspirante_vinculado
        if not asp:
            return None
        partes = [asp.nombre, asp.papellido, asp.sapellido]
        return " ".join(p for p in partes if p).strip() or None

    @property
    def cargo_actual(self):
        """Descripción del cargo que ocupa hoy el trabajador vinculado."""
        contrato = self.contrato if self.contrato_id else None
        if contrato and contrato.cargo and contrato.cargo.ncargo:
            return contrato.cargo.ncargo.descripcion
        return None

    @property
    def rol_descripcion(self):
        if self.es_admin:
            return "Administrador"
        if self.es_moderador:
            return "Moderador"
        if self.es_observador:
            return "Observador"
        return "Sin rol asignado"

    def obtener_preferencias(self):
        """Devuelve las preferencias del usuario, creándolas la primera vez."""
        preferencias, _ = PreferenciasUsuario.objects.get_or_create(usuario=self)
        return preferencias


class PreferenciasUsuario(models.Model):
    """Preferencias personales de interfaz.

    Va en un modelo aparte y no como campos de CustomUser a propósito:
    CustomUser.save() ejecuta full_clean() y reajusta los roles en cada guardado,
    y no queremos disparar esa lógica cada vez que alguien pliega la barra lateral.
    """

    usuario = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='preferencias',
        verbose_name="Usuario"
    )
    sidebar_colapsada = models.BooleanField(
        default=False,
        verbose_name="Barra lateral colapsada por defecto"
    )
    animaciones_activas = models.BooleanField(
        default=True,
        verbose_name="Animaciones de la interfaz activas"
    )
    fecha_actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Preferencias de usuario"
        verbose_name_plural = "Preferencias de usuarios"

    def __str__(self):
        return f"Preferencias de {self.usuario.username}"