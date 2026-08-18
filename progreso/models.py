from django.conf import settings
from django.db import models


class TareaGuia(models.Model):
    """Catálogo de acciones reales de Orbith que la Guía reconoce la primera
    vez que un usuario las completa. Administrable desde Django Admin: el
    Admin puede desactivar una tarea o ajustar su texto/orden sin tocar
    código. Agregar una tarea nueva que dependa de un evento sin instrumentar
    sí requiere una línea de código en el punto correspondiente (ver
    `progreso/servicios.py`).
    """

    class Categoria(models.TextChoices):
        PRIMEROS_PASOS = 'PRI', 'Primeros pasos'
        EXPLORAR = 'EXP', 'Explorar Orbith'
        DOMINAR = 'DOM', 'Dominar Orbith'

    codigo = models.SlugField(unique=True, verbose_name='Código')
    titulo = models.CharField(max_length=150, verbose_name='Título')
    descripcion = models.CharField(max_length=255, blank=True, verbose_name='Descripción')
    categoria = models.CharField(max_length=3, choices=Categoria.choices, verbose_name='Categoría')
    modulo = models.CharField(max_length=50, blank=True, default='', verbose_name='Módulo')

    # Enlace directo "Ir a X ->" desde el panel (Fase B).
    url_relacionada = models.CharField(max_length=255, blank=True, default='', verbose_name='URL relacionada')

    # Fase B: pasos del "¿Cómo se hace?", consultable en cualquier momento
    # (incluso con la tarea ya completada). Un paso por línea a propósito: es
    # el formato más simple que cubre lo que se pidió (instrucciones cortas,
    # numeradas al renderizar) sin introducir Markdown ni un modelo aparte de
    # "pasos" que hoy no hace falta — se puede migrar a algo más rico después
    # sin romper este campo, si algún día un paso necesita más que una línea.
    instrucciones = models.TextField(
        blank=True, default='',
        verbose_name='Instrucciones (un paso por línea)',
    )

    activo = models.BooleanField(default=True, verbose_name='Activo')
    orden = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')

    class Meta:
        verbose_name = 'Tarea de la Guía'
        verbose_name_plural = 'Tareas de la Guía'
        ordering = ['orden', 'id']

    def __str__(self):
        return self.titulo

    @property
    def pasos(self):
        """Lista de pasos no vacíos, para iterar en el template sin lógica ahí."""
        return [linea.strip() for linea in self.instrucciones.splitlines() if linea.strip()]


class TareaGuiaUsuario(models.Model):
    """Una tarea de la Guía completada por un usuario. `unique_together` a
    nivel de base de datos impide duplicados incluso con requests
    concurrentes (Django reintenta `get_or_create` con un savepoint interno
    cuando choca contra esta restricción)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tareas_guia',
        verbose_name='Usuario',
    )
    tarea = models.ForeignKey(TareaGuia, on_delete=models.CASCADE, verbose_name='Tarea')
    fecha_completada = models.DateTimeField(auto_now_add=True, verbose_name='Fecha completada')

    # Controla el indicador de "novedades sin ver" en el navbar. Se marca en
    # bloque al abrir el modal de la Guía (ver progreso/views.py), no aquí.
    visto = models.BooleanField(default=False, verbose_name='Visto')

    class Meta:
        verbose_name = 'Tarea completada'
        verbose_name_plural = 'Tareas completadas'
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'tarea'], name='progreso_una_vez_por_usuario'),
        ]
        ordering = ['-fecha_completada']

    def __str__(self):
        return f'{self.usuario} · {self.tarea}'
