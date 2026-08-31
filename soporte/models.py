from django.conf import settings
from django.db import models


class ReporteProblema(models.Model):
    """Incidencia reportada por un usuario desde el menú "Acerca de Orbith".

    No envía correos ni depende de servicios externos: se guarda en base de datos
    y los administradores la consultan desde la bandeja de reportes.
    """

    ESTADO_PENDIENTE = 'PEN'
    ESTADO_ATENDIDO = 'ATE'
    ESTADO_DESCARTADO = 'DES'

    ESTADOS = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_ATENDIDO, 'Atendido'),
        (ESTADO_DESCARTADO, 'Descartado'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reportes_problema',
        verbose_name="Reportado por"
    )
    # Nombre que el usuario DECLARA tener cuando reporta desde el login, donde
    # todavía no está autenticado. Es texto sin verificar (puede escribir
    # cualquier cosa) y por eso NO se guarda como relación al usuario: sirve para
    # que el Administrador sepa a quién llamar, nada más.
    usuario_declarado = models.CharField(
        max_length=150, blank=True, default='',
        verbose_name="Usuario declarado (sin autenticar)"
    )

    # Solo como rastro para el Administrador. La cabecera de la que se obtiene se
    # puede falsificar (ver `usuarios.utils.obtener_ip`), así que no se usa para
    # decidir permisos.
    ip_origen = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="IP de origen"
    )

    mensaje = models.TextField(verbose_name="Descripción del problema")
    error_consola = models.TextField(
        blank=True,
        verbose_name="Error de consola (F12)",
        help_text="Texto exacto del error mostrado en la consola del navegador, si el usuario lo vio."
    )
    url_origen = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Página desde la que se reportó"
    )
    estado = models.CharField(
        max_length=3,
        choices=ESTADOS,
        default=ESTADO_PENDIENTE,
        verbose_name="Estado"
    )
    fecha_creado = models.DateTimeField(auto_now_add=True, verbose_name="Fecha del reporte")
    fecha_actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reporte de problema"
        verbose_name_plural = "Reportes de problemas"
        ordering = ['-fecha_creado']

    def __str__(self):
        return f"Reporte de {self.autor_legible} ({self.get_estado_display()})"

    @property
    def autor_legible(self):
        """Quién lo envió, distinguiendo los tres casos posibles.

        Hace falta porque `usuario` es null en DOS situaciones muy distintas: la
        cuenta se borró después (SET_NULL), o el reporte llegó desde el login sin
        estar autenticado. Mostrar "Usuario eliminado" en el segundo caso sería
        sencillamente falso.
        """
        if self.usuario:
            return self.usuario.username
        if self.usuario_declarado:
            return f"{self.usuario_declarado} (sin autenticar)"
        return "Usuario eliminado"


class ImagenReporteProblema(models.Model):
    """Captura de pantalla adjunta a un reporte de problema.

    Modelo aparte (no un ImageField múltiple: Django no lo soporta) para poder
    aceptar de 0 a 4 imágenes por reporte sin campos vacíos si el usuario sube
    menos de 4.
    """

    reporte = models.ForeignKey(
        ReporteProblema,
        on_delete=models.CASCADE,
        related_name='imagenes',
        verbose_name="Reporte"
    )
    imagen = models.ImageField(upload_to='img/reportes/', verbose_name="Imagen")
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Imagen de reporte"
        verbose_name_plural = "Imágenes de reportes"

    def __str__(self):
        return f"Imagen de {self.reporte_id}"
