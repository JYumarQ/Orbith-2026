from django.conf import settings
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

# `CRITICIDADES` es una lista de tuplas `(entero, etiqueta)` definida en un módulo
# hoja puro (`subsanacion/constantes.py` no importa nada). Se reutiliza DIRECTAMENTE
# como `choices` de `severidad`, en vez de declarar un vocabulario propio con los
# mismos valores "por convención": dos listas idénticas hoy pueden divergir mañana si
# alguien edita una y no la otra, que es exactamente lo que esta reutilización evita
# garantizar. El coste es que `notificaciones` pasa a depender de que `subsanacion`
# esté instalada — aceptable aquí porque Orbith es un proyecto único, no una
# librería reutilizable, y ambas apps siempre se despliegan juntas.
from subsanacion.constantes import CRITICIDADES


# Create your models here.
class Notificacion(models.Model):

    class Tipo(models.TextChoices):
        EVENTO = 'EVE', 'Evento'                # alta/baja de contrato, nuevo cargo, solicitud
        ALERTA = 'ALE', 'Alerta'                # hallazgos de integridad (en caliente o Subsanación)
        SISTEMA = 'SIS', 'Sistema'              # reservado: nada lo emite todavía
        RECORDATORIO = 'REC', 'Recordatorio'    # vencimientos, cumpleaños, jubilación próxima, etc.

    class Estado(models.TextChoices):
        ACTIVA = 'ACT', 'Activa'
        RESUELTA = 'RES', 'Resuelta'
        DESCARTADA = 'DES', 'Descartada'        # reservado: nadie lo escribe todavía

    class Origen(models.TextChoices):
        """Solo se usa en RECORDATORIO — distingue si lo generó el escaneo periódico
        (`notificaciones/recordatorios.py`) o lo creó a mano un administrador. Campo
        explícito a propósito: se descartó inferirlo de una convención de prefijo en
        `codigo_regla` (p. ej. 'REC-' = automático) por implícito y frágil — cualquiera
        que lea el dato sin conocer la convención no sabría qué significa, y una regla
        mal nombrada rompería la clasificación en silencio."""
        SISTEMA = 'SIS', 'Sistema'
        ADMINISTRACION = 'ADM', 'Administración'

    titulo = models.CharField(max_length=150)
    mensaje = models.TextField()
    fecha_creado = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    # «Leído» y «resuelto» son ejes independientes a propósito: una alerta puede
    # corregirse antes de que nadie la abra (estado=RESUELTA, leido=False), o el
    # usuario puede haberla visto sin que el problema esté corregido todavía
    # (estado=ACTIVA, leido=True). Nunca se toca uno al modificar el otro.
    # `default=EVENTO` es sobre todo para las filas existentes al migrar (las 2 vías
    # de creación anteriores a este cambio — cargo nuevo, solicitud — son eventos).
    # Cada punto de creación nuevo lo fija explícitamente; el default no debe
    # entenderse como "vale para cualquier caso no pensado".
    tipo = models.CharField(max_length=3, choices=Tipo.choices, default=Tipo.EVENTO)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.ACTIVA)
    fecha_resolucion = models.DateTimeField(null=True, blank=True)

    # `null=True`: no todo EVENTO tiene una gravedad real (un alta de contrato no es
    # "crítica" ni "baja", simplemente informa) — se deja vacío en vez de forzar un
    # valor arbitrario.
    severidad = models.PositiveSmallIntegerField(choices=CRITICIDADES, null=True, blank=True)

    # Identifican de qué regla de Subsanación viene una alerta, en campos separados
    # (no un texto combinado) para poder filtrar/agrupar directamente. Es también la
    # clave real de deduplicación junto con content_type/object_id/destinatario: ver
    # `notificaciones/avisos.py`. Vacíos para los EVENTO, que no vienen de una regla.
    codigo_regla = models.CharField(max_length=20, blank=True, default='')
    clave_extra = models.CharField(max_length=50, blank=True, default='')

    # Copiado de `HallazgoDetectado.campo_formulario` al registrar la notificación
    # (ver `notificaciones/avisos.py::_registrar_notificacion_de_hallazgo`): el nombre
    # real del campo del modelo al que corresponde el hallazgo, si la regla lo declara.
    # Se persiste aquí (en vez de recalcularlo) porque el panel "otras advertencias del
    # registro" lee filas ya guardadas, no vuelve a evaluar la regla. Vacío si la regla
    # no lo declara o la alerta es un EVENTO sin campo asociado.
    campo_formulario = models.CharField(max_length=100, blank=True, default='')

    # Solo para RECORDATORIO: cuándo vence/ocurre lo recordado (vencimiento de
    # contrato, fecha del próximo cumpleaños, fecha en la que se alcanza la edad de
    # pre-jubilación...). Es lo que permite calcular el color de prioridad (🟢🟠🟡🔴) al
    # vuelo, sin guardar un estado "Vencido" aparte — ver `notificaciones/recordatorios.py`.
    fecha_objetivo = models.DateField(null=True, blank=True)
    origen = models.CharField(max_length=3, choices=Origen.choices, blank=True, default='')

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=50)
    objeto_relacionado = GenericForeignKey('content_type', 'object_id')

    # Se conserva como contexto/filtrado aunque ya no sea el mecanismo de entrega
    # (ese es `destinatario`, ver abajo).
    unidad = models.ForeignKey('strorganizativa.UnidadOrganizativa', on_delete=models.CASCADE, null=True, blank=True)

    # Dirige la notificación a UNA persona. Nula por compatibilidad con datos
    # históricos que aún no se hayan repartido (ver migración de backfill);
    # `notificaciones_json` y `ultimas_notificaciones` la incluyen con un OR junto al
    # filtro por unidad.
    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name='notificaciones_personales', verbose_name='Destinatario')

    # url_destino = models.URLField(blank=True, null=True)  # URL a la vista correspondiente

    class Meta:
        verbose_name = ("Notificación")
        verbose_name_plural = ("Notificaciones")
        # Por importancia primero, no solo por fecha: una crítica antigua no debe
        # quedar tapada por un evento reciente sin gravedad. Mismo criterio que ya usa
        # `subsanacion.models.Hallazgo.Meta.ordering`. Los EVENTO sin severidad
        # (NULL) quedan al final con PostgreSQL (NULLS LAST es el comportamiento por
        # defecto de ORDER BY ASC), que es la posición correcta.
        ordering = ['severidad', '-fecha_creado']

    def __str__(self):
        return f"{self.titulo} - {self.mensaje}"
