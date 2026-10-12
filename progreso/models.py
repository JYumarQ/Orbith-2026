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
        # Entre Explorar y Dominar: el orden de aquí es el del panel.
        EXPORTAR = 'EXR', 'Exportar'
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

    # Varias formas de llegar a la misma tarea (la contratación se hace desde
    # Aspirantes, desde el Gestor o desde Contratos). Una línea por acceso:
    #     Etiqueta | /url/ | clave del recorrido
    # Si está vacío, el panel muestra el único botón "Ir a X" de
    # `url_relacionada`, como siempre. La clave es la de
    # `window.OrbithRecorridos` en la pantalla de destino.
    accesos = models.TextField(
        blank=True, default='',
        verbose_name='Accesos (uno por línea: Etiqueta | /url/ | recorrido)',
    )

    # Qué roles ven la tarea. Un Observador no puede crear aspirantes ni
    # contratar, así que si viera esas tareas nunca podría llegar al 100 %.
    # Tres casillas en vez de una lista de roles en texto: es lo más fácil de
    # marcar desde el Admin y de filtrar con el ORM. Ver
    # `progreso/servicios.py::tareas_visibles`.
    para_admin = models.BooleanField(default=True, verbose_name='Visible para Administrador')
    para_moderador = models.BooleanField(default=True, verbose_name='Visible para Moderador')
    para_observador = models.BooleanField(default=True, verbose_name='Visible para Observador')

    # Tareas con avance ("Exporta un Informe RRHH" pide PDF, Word y Excel): las
    # claves de cada parte, separadas por comas. La tarea se completa al hacer
    # todas (ver `progreso/servicios.py::completar_parte`). Vacío = una sola acción.
    partes = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='Partes (claves separadas por comas)',
    )

    # Tarea de un módulo que aún se está construyendo (por ejemplo, Pre-Nómina):
    # el panel la enseña atenuada con "En desarrollo", pero no cuenta para el
    # avance ni se puede completar. Distinto de `activo=False`, que la esconde.
    en_desarrollo = models.BooleanField(
        default=False, verbose_name='En desarrollo (se ve atenuada y no cuenta)',
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
    def lista_accesos(self):
        """Accesos de `accesos` como diccionarios {etiqueta, url, recorrido}.
        Las líneas mal escritas (sin sus tres partes) se ignoran."""
        resultado = []
        for linea in self.accesos.splitlines():
            partes = [p.strip() for p in linea.split('|')]
            if len(partes) == 3 and all(partes):
                resultado.append({'etiqueta': partes[0], 'url': partes[1], 'recorrido': partes[2]})
        return resultado

    @property
    def lista_partes(self):
        """Claves de `partes` como lista, sin vacíos ni espacios."""
        return [p.strip() for p in self.partes.split(',') if p.strip()]

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


class TareaGuiaParte(models.Model):
    """Una parte hecha de una tarea con avance (por ejemplo, el PDF de
    "Exporta un Informe RRHH"). Cuando el usuario tiene todas las partes de la
    tarea, se completa la tarea en `TareaGuiaUsuario`."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='partes_guia',
        verbose_name='Usuario',
    )
    tarea = models.ForeignKey(TareaGuia, on_delete=models.CASCADE, verbose_name='Tarea')
    parte = models.CharField(max_length=30, verbose_name='Parte')
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')

    class Meta:
        verbose_name = 'Parte de tarea hecha'
        verbose_name_plural = 'Partes de tareas hechas'
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'tarea', 'parte'], name='progreso_parte_una_vez'),
        ]

    def __str__(self):
        return f'{self.usuario} · {self.tarea} · {self.parte}'
