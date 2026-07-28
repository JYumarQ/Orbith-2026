from django.db import models
from django.conf import settings
from auditoria.models import Base


class InformePersonalizado(models.Model):
    """
    Un informe guardado por un usuario (o una plantilla del sistema si usuario es None).
    La configuración completa (campos, filtros, agrupación, orden) vive en 'configuracion'
    como JSON, porque su estructura es variable según lo que el usuario haya elegido.
    """
    nombre = models.CharField(max_length=150, verbose_name="Nombre del informe")
    descripcion = models.CharField(max_length=300, blank=True, null=True)

    # Sobre qué modelo se construye el informe. Ej: 'CAlta'.
    # Debe coincidir con una clave registrada en informe_inteligente/metadata.py
    modelo_raiz = models.CharField(max_length=50, verbose_name="Modelo base")

    configuracion = models.JSONField(
        verbose_name="Configuración del informe",
        help_text="Campos, filtros, agrupación y orden elegidos por el usuario."
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="informes_personalizados",
        verbose_name="Creado por",
        help_text="Vacío si es una plantilla del sistema, disponible para todos."
    )
    es_plantilla = models.BooleanField(
        default=False,
        verbose_name="Es plantilla del sistema",
        help_text="Las plantillas las ve cualquier usuario; los informes propios solo su dueño."
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Informe Personalizado"
        verbose_name_plural = "Informes Personalizados"
        ordering = ['-fecha_actualizacion']

    def __str__(self):
        return self.nombre


class InformeFavorito(models.Model):
    """Relación entre un usuario y los informes que marcó como favoritos."""
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="informes_favoritos"
    )
    informe = models.ForeignKey(
        InformePersonalizado,
        on_delete=models.CASCADE,
        related_name="marcado_como_favorito_por"
    )
    fecha_agregado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Informe Favorito"
        verbose_name_plural = "Informes Favoritos"
        unique_together = ('usuario', 'informe')
        ordering = ['-fecha_agregado']

    def __str__(self):
        return f"{self.usuario} → {self.informe.nombre}"


class UltimoInformeEjecutado(models.Model):
    """
    Recuerda la última configuración de informe que cada usuario ejecutó,
    para que al volver al módulo pueda continuar donde lo dejó.
    Una sola fila por usuario (OneToOne): siempre se sobrescribe, no se acumula historial.
    """
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ultimo_informe_ejecutado"
    )
    modelo_raiz = models.CharField(max_length=50)
    configuracion = models.JSONField()
    total_registros = models.PositiveIntegerField(default=0)
    fecha_ejecucion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Último Informe Ejecutado"
        verbose_name_plural = "Últimos Informes Ejecutados"

    def __str__(self):
        return f"Último informe de {self.usuario} — {self.fecha_ejecucion:%d/%m/%Y %H:%M}"