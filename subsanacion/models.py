"""Modelos del módulo de Subsanación.

NINGUNO de estos modelos hereda de `auditoria.models.Base`, y es deliberado:

1. `bulk_create()` y `bulk_update()` no llaman a `save()`, así que `created_by` y
   `updated_by` quedarían nulos de forma incoherente — peor que no tenerlos.
2. "Quién creó" un hallazgo generado por una máquina no significa nada. Lo que
   importa es QUÉ EJECUCIÓN lo detectó y QUIÉN lo revisó, y eso está modelado
   explícitamente en `Hallazgo.ejecucion` y `Hallazgo.revisado_por`.

Estos modelos son los ÚNICOS que el módulo escribe. Subsanación nunca modifica un
modelo de negocio: detecta, explica y guía, pero la corrección la hace el usuario a
mano desde los formularios normales de Orbith.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from .constantes import (
    COLOR_POR_CRITICIDAD,
    CRITICIDADES,
    ICONO_MODULO,
    ICONO_POR_CRITICIDAD,
    MODULOS_CHOICES,
    VERSION_INDICE_SALUD,
)


class EjecucionAnalisis(models.Model):
    """Resumen de un barrido de integridad.

    Es la fila que lee el dashboard: la pantalla principal NUNCA re-analiza nada,
    solo consulta la última ejecución terminada.
    """

    EN_CURSO = 'CUR'
    COMPLETA = 'COM'
    PARCIAL = 'PAR'
    FALLIDA = 'FAL'
    ESTADOS = [
        (EN_CURSO, 'En curso'),
        (COMPLETA, 'Completa'),
        (PARCIAL, 'Parcial'),
        (FALLIDA, 'Fallida'),
    ]
    ESTADOS_TERMINADOS = (COMPLETA, PARCIAL, FALLIDA)

    MANUAL = 'MAN'
    COMANDO = 'CMD'
    PROGRAMADA = 'PRG'
    ORIGENES = [
        (MANUAL, 'Manual (desde la interfaz)'),
        (COMANDO, 'Comando de consola'),
        (PROGRAMADA, 'Programada'),
    ]

    estado = models.CharField(
        max_length=3, choices=ESTADOS, default=EN_CURSO, verbose_name='Estado')
    origen = models.CharField(
        max_length=3, choices=ORIGENES, default=MANUAL, verbose_name='Origen')
    lanzada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis_lanzados', verbose_name='Lanzada por')

    iniciada_en = models.DateTimeField(auto_now_add=True, verbose_name='Iniciada')
    terminada_en = models.DateTimeField(null=True, blank=True, verbose_name='Terminada')
    duracion_ms = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='Duración (ms)')

    modulos_solicitados = models.JSONField(default=list, blank=True)
    modulos_completados = models.JSONField(default=list, blank=True)
    reglas_ejecutadas = models.PositiveSmallIntegerField(default=0)

    # Etiquetas «app.Modelo» de los modelos que se revisaron, sin repetir.
    # De aquí sale `registros_analizados`: se cuenta cada modelo UNA vez, no una vez
    # por regla. Si se contara por regla, añadir reglas nuevas inflaría el
    # denominador del índice de salud y el índice subiría sin que la base mejorara.
    modelos_analizados = models.JSONField(default=list, blank=True)
    registros_analizados = models.PositiveIntegerField(
        default=0, verbose_name='Registros analizados',
        help_text='Filas distintas revisadas, contando cada modelo una sola vez.')

    # {clave_modulo: nº de filas} — el denominador del porcentaje de cada categoría.
    # Se guarda en el momento del análisis para que el dashboard pueda calcular los
    # porcentajes SIN lanzar un COUNT(*) por modelo en cada carga de la página.
    registros_por_modulo = models.JSONField(default=dict, blank=True)

    # {"CTR-014": "mensaje del error"} — una regla que falla no aborta el barrido.
    errores = models.JSONField(default=dict, blank=True)

    hallazgos_nuevos = models.PositiveIntegerField(default=0)
    hallazgos_persistentes = models.PositiveIntegerField(default=0)
    hallazgos_resueltos = models.PositiveIntegerField(default=0)
    hallazgos_vigentes = models.PositiveIntegerField(default=0)

    indice_salud = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name='Índice de salud (%)')
    # Permite saber con qué fórmula se calculó el índice. Sin esto, una gráfica
    # histórica compararía valores no comparables sin avisar.
    version_indice = models.PositiveSmallIntegerField(default=VERSION_INDICE_SALUD)

    class Meta:
        verbose_name = 'Ejecución de análisis'
        verbose_name_plural = 'Ejecuciones de análisis'
        ordering = ['-iniciada_en']
        indexes = [
            # El dashboard pide siempre "la última terminada".
            models.Index(fields=['-iniciada_en'], name='subs_ejec_fecha_desc'),
        ]
        constraints = [
            # Cerrojo a nivel de base de datos: como máximo UNA ejecución en curso.
            # El proyecto no tiene CACHES configurado, así que no hay dónde poner un
            # lock de aplicación; la propia base de datos hace de cerrojo.
            models.UniqueConstraint(
                fields=['estado'], condition=Q(estado='CUR'),
                name='subs_una_ejecucion_en_curso'),
        ]

    def __str__(self):
        return f'Análisis del {self.iniciada_en:%d/%m/%Y %H:%M} ({self.get_estado_display()})'

    @property
    def duracion_segundos(self):
        """Duración en segundos con un decimal, o None si aún no terminó."""
        if self.duracion_ms is None:
            return None
        return round(self.duracion_ms / 1000, 1)


class Hallazgo(models.Model):
    """Una inconsistencia detectada sobre un registro concreto.

    La clave natural es `(codigo_regla, content_type, object_id, clave_extra)`. Cada
    barrido hace UPSERT sobre esa cuádrupla, así que re-analizar no duplica filas ni
    pierde el estado que el usuario haya fijado a mano.
    """

    PENDIENTE = 'PEN'
    EN_REVISION = 'REV'
    CORREGIDO = 'COR'
    IGNORADO = 'IGN'
    FALSO_POSITIVO = 'FAL'
    ESTADOS = [
        (PENDIENTE, 'Pendiente'),
        (EN_REVISION, 'En revisión'),
        (CORREGIDO, 'Corregido'),
        (IGNORADO, 'Ignorado'),
        (FALSO_POSITIVO, 'Falso positivo'),
    ]
    # Los que penalizan el índice de salud.
    ESTADOS_ABIERTOS = (PENDIENTE, EN_REVISION)
    # Los que sobreviven a un re-análisis: el usuario ya dictaminó sobre ellos.
    ESTADOS_SILENCIADOS = (IGNORADO, FALSO_POSITIVO)

    COLOR_POR_ESTADO = {
        PENDIENTE: 'warning',
        EN_REVISION: 'info',
        CORREGIDO: 'success',
        IGNORADO: 'secondary',
        FALSO_POSITIVO: 'secondary',
    }

    # --- Clave natural ---------------------------------------------------
    codigo_regla = models.CharField(
        max_length=20, verbose_name='Código de la regla',
        help_text='Estable para siempre: es parte de la clave natural del hallazgo.')
    # `content_type` NO puede ser nulable: en PostgreSQL NULL != NULL, así que una
    # UniqueConstraint con una columna nula no impediría duplicados y cada barrido
    # volvería a insertar los hallazgos globales. Toda regla declara su modelo; los
    # hallazgos globales usan object_id = ''.
    content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT,
        related_name='hallazgos_subsanacion', verbose_name='Tipo de registro')
    object_id = models.CharField(
        max_length=50, blank=True, default='', verbose_name='Registro afectado',
        help_text="Vacío cuando el hallazgo es global y no apunta a una fila concreta.")
    clave_extra = models.CharField(
        max_length=50, blank=True, default='',
        help_text='Discrimina varios hallazgos de la misma regla sobre el mismo registro.')
    objeto = GenericForeignKey('content_type', 'object_id')

    # --- Instantánea (se refresca en cada barrido) ------------------------
    modulo = models.CharField(max_length=20, choices=MODULOS_CHOICES, verbose_name='Categoría')
    criticidad = models.PositiveSmallIntegerField(choices=CRITICIDADES, verbose_name='Criticidad')
    titulo = models.CharField(
        max_length=255, verbose_name='Título',
        help_text='Debe incluir los datos buscables del registro (nombre, CI, expediente).')
    detalle = models.TextField(blank=True, default='', verbose_name='Detalle')
    datos = models.JSONField(default=dict, blank=True, verbose_name='Datos del hallazgo')
    # md5 de `datos`. Si cambia, el hallazgo dejó de ser el mismo aunque la clave
    # natural coincida, y un "Ignorado" antiguo no debe seguir silenciándolo.
    huella = models.CharField(max_length=32, blank=True, default='')

    # Denormalización deliberada: no se puede hacer JOIN a través de una
    # GenericForeignKey, y el listado tiene que poder acotarse por unidad en SQL.
    # La regla la calcula al detectar, que es cuando tiene el registro en la mano.
    unidad_organizativa = models.ForeignKey(
        'strorganizativa.UnidadOrganizativa', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='hallazgos_subsanacion',
        verbose_name='Unidad organizativa')

    # --- Ciclo de vida ---------------------------------------------------
    vigente = models.BooleanField(
        default=True, verbose_name='Vigente',
        help_text='False cuando el último análisis ya no lo detectó.')
    primera_deteccion = models.DateTimeField(auto_now_add=True)
    ultima_deteccion = models.DateTimeField()
    veces_detectado = models.PositiveIntegerField(default=1)
    ejecucion = models.ForeignKey(
        EjecucionAnalisis, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hallazgos', verbose_name='Detectado en')
    fecha_resolucion = models.DateTimeField(null=True, blank=True)
    resuelto_automaticamente = models.BooleanField(
        default=False,
        help_text='True cuando dejó de detectarse, no cuando una persona lo cerró.')

    # --- Estado que gestiona el usuario ----------------------------------
    estado = models.CharField(
        max_length=3, choices=ESTADOS, default=PENDIENTE, verbose_name='Estado')
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hallazgos_revisados', verbose_name='Revisado por')
    fecha_revision = models.DateTimeField(null=True, blank=True)
    nota = models.TextField(blank=True, default='', verbose_name='Observación')

    class Meta:
        verbose_name = 'Hallazgo'
        verbose_name_plural = 'Hallazgos'
        ordering = ['criticidad', '-ultima_deteccion']
        constraints = [
            models.UniqueConstraint(
                fields=['codigo_regla', 'content_type', 'object_id', 'clave_extra'],
                name='subs_hallazgo_clave_natural'),
        ]
        # Los índices parciales (condition=) son PostgreSQL, y el proyecto es
        # PostgreSQL exclusivo. Al filtrar por vigente=True no crecen con el
        # histórico archivado, que la interfaz casi nunca consulta.
        indexes = [
            # Listado principal: WHERE vigente ORDER BY criticidad, ultima_deteccion DESC
            models.Index(
                fields=['criticidad', '-ultima_deteccion'], condition=Q(vigente=True),
                name='subs_hall_vigentes_crit'),
            # Contadores del dashboard: values('modulo','criticidad').annotate(Count)
            models.Index(
                fields=['modulo', 'estado'], condition=Q(vigente=True),
                name='subs_hall_modulo_estado'),
            # Alcance por unidad organizativa (lectura del moderador, Fase 2).
            models.Index(
                fields=['unidad_organizativa', 'criticidad'], condition=Q(vigente=True),
                name='subs_hall_uo_crit'),
            # La reconciliación acota SIEMPRE por codigo_regla: este índice es el que
            # la hace proporcional a los hallazgos de la regla y no a la tabla entera.
            models.Index(fields=['codigo_regla', 'vigente'], name='subs_hall_regla_vig'),
        ]

    def __str__(self):
        return f'[{self.codigo_regla}] {self.titulo}'

    @property
    def esta_abierto(self):
        return self.estado in self.ESTADOS_ABIERTOS

    @property
    def esta_silenciado(self):
        return self.estado in self.ESTADOS_SILENCIADOS

    @property
    def color_estado(self):
        """Sufijo de la clase Bootstrap `bg-label-*` para el badge de estado."""
        return self.COLOR_POR_ESTADO.get(self.estado, 'secondary')

    # Estas tres propiedades existen para que las plantillas no tengan que buscar en
    # un diccionario, algo que el lenguaje de plantillas de Django no puede hacer con
    # una clave variable.
    @property
    def color_criticidad(self):
        """Sufijo de la clase CSS `sub-color-*` de la gravedad."""
        return COLOR_POR_CRITICIDAD.get(self.criticidad, 'gris')

    @property
    def icono_criticidad(self):
        return ICONO_POR_CRITICIDAD.get(self.criticidad, 'bi-dash-circle')

    @property
    def icono_modulo(self):
        return ICONO_MODULO.get(self.modulo, 'bi-folder')

    @property
    def es_global(self):
        """True si el hallazgo no apunta a una fila concreta (p.ej. falta la configuración)."""
        return not self.object_id


class RevisionHallazgo(models.Model):
    """Historial de cambios de estado de un hallazgo.

    Es el historial propio del módulo, no la Auditoría del sistema: aquí solo se
    registra lo que ocurre con los hallazgos, nunca cambios en datos de negocio.
    """

    hallazgo = models.ForeignKey(
        Hallazgo, on_delete=models.CASCADE, related_name='revisiones',
        verbose_name='Hallazgo')
    estado_anterior = models.CharField(max_length=3, choices=Hallazgo.ESTADOS)
    estado_nuevo = models.CharField(max_length=3, choices=Hallazgo.ESTADOS)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revisiones_hallazgo', verbose_name='Usuario')
    nota = models.TextField(blank=True, default='', verbose_name='Observación')
    automatica = models.BooleanField(
        default=False, verbose_name='Automática',
        help_text='True cuando la transición la hizo el motor, no una persona.')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Revisión de hallazgo'
        verbose_name_plural = 'Revisiones de hallazgos'
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['hallazgo', '-fecha'], name='subs_revision_hallazgo'),
        ]

    def __str__(self):
        quien = self.usuario.username if self.usuario else 'el sistema'
        return f'{self.hallazgo_id}: {self.estado_anterior} → {self.estado_nuevo} por {quien}'
