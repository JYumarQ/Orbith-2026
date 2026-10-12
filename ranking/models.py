from django.conf import settings
from django.db import models
from django.utils import timezone


class Rol(models.TextChoices):
    ADMINISTRADOR = 'A', 'Administrador'
    MODERADOR = 'M', 'Moderador'
    OBSERVADOR = 'O', 'Observador'


class Actividad(models.TextChoices):
    """Lo que da XP. Los puntos y los topes de cada rol están en `puntos.py`."""
    ASPIRANTE = 'ASP', 'Aspirante registrado'
    ALTA = 'ALT', 'Alta de contrato'
    MOVIMIENTO = 'MOV', 'Movimiento de nómina'
    ENVIO_MOVIMIENTO = 'ENV', 'Enviado a Mov. Nómina'
    BAJA = 'BAJ', 'Baja'
    SOLICITUD_APROBADA = 'SAP', 'Solicitud aprobada'
    CIERRE_EN_PLAZO = 'CIE', 'Cierre en plazo'
    HALLAZGO_REVISADO = 'HAL', 'Hallazgo revisado'
    RECORDATORIO_COMPLETADO = 'RCO', 'Recordatorio completado a tiempo'
    SOLICITUD_DECIDIDA = 'SDE', 'Solicitud decidida'
    ANALISIS_SUBSANACION = 'ANA', 'Análisis de Subsanación'
    RECORDATORIO_CREADO = 'RCR', 'Recordatorio creado'
    INFORME = 'INF', 'Informe generado o consultado'
    DESCARGA = 'DES', 'Archivo descargado'
    DIA_ACTIVO = 'DIA', 'Día con actividad'


class ActividadXP(models.Model):
    """Una fila por cada acción que cuenta para el Ranking.

    Sirve a la vez para el XP (campo `xp`, que es 0 cuando la acción pasó del
    tope diario) y para el USO (se cuentan las filas, sin topes). Solo se
    guardan los últimos 3 meses: ver `servicios.cerrar_mes_si_toca()`.
    """
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='actividades_xp')
    # Rol en el momento de la acción: decide los puntos y el tope. El ranking,
    # en cambio, agrupa por el rol ACTUAL del usuario.
    rol = models.CharField(max_length=1, choices=Rol.choices)
    actividad = models.CharField(max_length=3, choices=Actividad.choices)
    fecha = models.DateTimeField(default=timezone.now)
    dia = models.DateField(db_index=True)
    xp = models.PositiveSmallIntegerField(default=0)
    # Texto corto para "Últimas acciones" (el aspirante, el informe...).
    detalle = models.CharField(max_length=200, blank=True, default='')
    # Solo en las descargas: pdf, word o excel.
    formato = models.CharField(max_length=10, blank=True, default='')

    class Meta:
        verbose_name = 'Actividad del Ranking'
        verbose_name_plural = 'Actividades del Ranking'
        ordering = ['-fecha']
        indexes = [
            # El tope diario: "¿cuántas de esta actividad lleva hoy?".
            models.Index(fields=['usuario', 'dia', 'actividad']),
        ]
        constraints = [
            # Un solo "Día con actividad" por usuario y día, aunque lleguen
            # dos peticiones a la vez.
            models.UniqueConstraint(fields=['usuario', 'dia'], condition=models.Q(actividad='DIA'),
                                    name='ranking_un_dia_activo_por_dia'),
        ]

    def __str__(self):
        return f'{self.usuario} · {self.get_actividad_display()} · {self.xp} XP'


class MesCerrado(models.Model):
    """Marca que un mes ya se cerró (ganadores repartidos y limpieza hecha).

    La restricción única hace que, aunque dos peticiones lleguen a la vez el
    día 1, solo una cierre el mes.
    """
    anno = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    fecha_cierre = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Mes cerrado'
        verbose_name_plural = 'Meses cerrados'
        ordering = ['-anno', '-mes']
        constraints = [
            models.UniqueConstraint(fields=['anno', 'mes'], name='ranking_mes_cerrado_unico'),
        ]

    def __str__(self):
        return f'{self.mes:02d}/{self.anno}'


class GanadorMes(models.Model):
    """Los 3 primeros puestos de cada rol en un mes cerrado (con empates
    puede haber más de 3 personas). Se guardan 3 meses, como lo demás."""
    anno = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    rol = models.CharField(max_length=1, choices=Rol.choices)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='premios_ranking')
    puesto = models.PositiveSmallIntegerField()
    xp = models.PositiveIntegerField()

    class Meta:
        verbose_name = 'Ganador del mes'
        verbose_name_plural = 'Ganadores del mes'
        ordering = ['-anno', '-mes', 'rol', 'puesto']
        constraints = [
            models.UniqueConstraint(fields=['anno', 'mes', 'usuario'], name='ranking_ganador_unico'),
        ]

    def __str__(self):
        return f'{self.mes:02d}/{self.anno} · {self.get_rol_display()} · {self.puesto}º {self.usuario}'
