"""Cierres mensuales de Unidades Organizativas.

Existen porque **el pasado de Orbith no es reconstruible**: al dar de baja a un
trabajador su `CAlta` se borra físicamente (queda un `CBaja`), `cant_cubierta` se
recalcula contra los contratos vivos, y los informes clasifican por atributos de
nomencladores globales (`NCargo.cat_ocupacional`, `NTipoContrato.ocupa_plaza`) que
pueden cambiar en cualquier momento. Sin fotografía, reimprimir el consolidado de
agosto en noviembre daría números distintos y nadie sabría cuál era el bueno.

De ahí la decisión de diseño que gobierna todo el módulo: las filas de la
fotografía **no tienen ForeignKey a los datos vivos**, sino copias planas de los
valores. Los `*_id_original` son referencias blandas, para trazar de dónde salió
cada fila; jamás para reconstruir el informe con un JOIN. Si mañana alguien
renombra un cargo o cambia su categoría ocupacional, agosto no se mueve.

La mutación de estado pasa siempre por `servicios.py`. Aquí solo viven los datos
y los permisos por instancia, junto a los campos de los que dependen.
"""

from django.conf import settings
from django.db import models

from auditoria.models import Base
from strorganizativa.models import UnidadOrganizativa

from .periodos import Periodo


class EstadoUnidad(models.TextChoices):
    PENDIENTE = 'P', 'Pendiente'
    ACTUALIZADA = 'A', 'Actualizada'
    DESACTUALIZADA = 'D', 'Desactualizada'


class CierreUnidad(Base):
    """Cabecera de un cierre: una unidad declaró su información al día para un mes.

    La estructura de la propia unidad se congela aquí (descripción, si es
    principal, su padre, su orden) porque los informes agrupan por rama y ordenan
    por `orden_informe`: si la jerarquía cambia en octubre, el informe de agosto
    debe seguir saliendo con la jerarquía de agosto.
    """

    unidad = models.ForeignKey(
        UnidadOrganizativa,
        on_delete=models.CASCADE,
        related_name='cierres',
        verbose_name='Unidad Organizativa',
    )
    anno = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')

    declarado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cierres_declarados',
    )
    # Congelado: si el usuario se borra, el historial debe seguir diciendo quién
    # declaró. Mismo criterio que `EventoAuditoria.usuario_nombre`.
    declarado_por_nombre = models.CharField(max_length=150, blank=True)

    fecha_declaracion = models.DateTimeField(verbose_name='Fecha de declaración')
    en_plazo = models.BooleanField(
        default=True,
        verbose_name='Declarado en plazo',
        help_text='Falso si se declaró fuera de la ventana del 20 al 25 de su propio mes.',
    )
    # --- Estructura de la unidad, congelada ---
    unidad_descripcion = models.CharField(max_length=150)
    unidad_padre_id_original = models.IntegerField(null=True, blank=True)
    unidad_es_principal = models.BooleanField(default=False)
    unidad_es_subunidad = models.BooleanField(default=False)
    unidad_orden_informe = models.PositiveIntegerField(null=True, blank=True)
    unidad_grupo_nomina = models.IntegerField(null=True, blank=True)

    # --- Totales congelados, para listar el historial sin recorrer las filas ---
    total_cargos = models.PositiveIntegerField(default=0)
    total_plazas_aprobadas = models.PositiveIntegerField(default=0)
    total_plazas_cubiertas = models.PositiveIntegerField(default=0)
    total_contratos = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Cierre de Unidad'
        verbose_name_plural = 'Cierres de Unidades'
        ordering = ['-anno', '-mes', 'unidad_orden_informe']
        constraints = [
            models.UniqueConstraint(
                fields=['unidad', 'anno', 'mes'],
                name='cierre_unico_por_unidad_y_periodo',
            )
        ]
        indexes = [
            models.Index(fields=['anno', 'mes'], name='cierre_periodo_idx'),
        ]

    def __str__(self):
        return f'{self.unidad_descripcion} — {self.periodo.etiqueta}'

    @property
    def periodo(self):
        return Periodo(self.anno, self.mes)

    @property
    def plazas_vacantes(self):
        return max(self.total_plazas_aprobadas - self.total_plazas_cubiertas, 0)

    @property
    def estado_plazo(self):
        return 'En plazo' if self.en_plazo else 'Fuera de plazo'


class CierreCargo(models.Model):
    """Una fila por CargoPlantilla activo de la unidad, en el instante del cierre.

    No hereda de `Base`: es un hecho inmutable, nadie lo edita. Nace y muere con
    su `CierreUnidad`.
    """

    cierre = models.ForeignKey(CierreUnidad, on_delete=models.CASCADE, related_name='cargos')
    cargo_id_original = models.IntegerField(null=True, blank=True)

    # --- Departamento congelado ---
    departamento_id_original = models.IntegerField(null=True, blank=True)
    departamento_descripcion = models.CharField(max_length=150, blank=True)
    departamento_orden = models.PositiveIntegerField(null=True, blank=True)

    # --- Nomenclador congelado. Sin esto, cambiar un NCargo reescribiría el pasado ---
    ncargo_id_original = models.IntegerField(null=True, blank=True)
    ncargo_descripcion = models.CharField(max_length=150, blank=True)
    cat_ocupacional = models.CharField(max_length=20, blank=True)
    puesto_clave = models.BooleanField(default=False)
    grupo_escala_nivel = models.CharField(max_length=8, blank=True)
    salario_basico = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    # `NCargo.familias` es M2M; se aplana para no crear otra tabla solo por esto.
    familias_ids = models.JSONField(default=list, blank=True)

    # --- Cifras de plantilla ---
    cant_aprobada = models.IntegerField(default=0)
    cant_cubierta = models.IntegerField(default=0)
    funcionario = models.BooleanField(default=False)
    designado = models.BooleanField(default=False)
    orden_informe = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Cargo del cierre'
        verbose_name_plural = 'Cargos del cierre'
        ordering = ['departamento_orden', 'orden_informe', 'ncargo_descripcion']
        indexes = [
            models.Index(fields=['cierre', 'cat_ocupacional'], name='cierre_cargo_categoria_idx'),
            models.Index(fields=['cierre', 'puesto_clave'], name='cierre_cargo_clave_idx'),
        ]

    def __str__(self):
        return f'{self.ncargo_descripcion} ({self.cant_aprobada})'

    @property
    def vacantes(self):
        return max(self.cant_aprobada - self.cant_cubierta, 0)


class CierreContrato(models.Model):
    """Una fila por CAlta activo de la unidad, en el instante del cierre.

    Los datos del cargo se repiten aquí aunque ya estén en `CierreCargo`: los
    informes agrupan contratos por categoría ocupacional, y repetir cuatro
    columnas sale mucho más barato que un JOIN por fila en cada informe.
    """

    cierre = models.ForeignKey(CierreUnidad, on_delete=models.CASCADE, related_name='contratos')
    cierre_cargo = models.ForeignKey(
        CierreCargo,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='contratos',
    )
    contrato_id_original = models.IntegerField(null=True, blank=True)
    no_expediente = models.CharField(max_length=5, blank=True)

    # --- Trabajador congelado ---
    aspirante_id_original = models.IntegerField(null=True, blank=True)
    aspirante_nombre = models.CharField(max_length=100, blank=True)
    doc_identidad = models.CharField(max_length=11, blank=True)
    sexo = models.CharField(max_length=1, blank=True)
    # Se congela porque los informes no coinciden en esto: el Consolidado cuenta
    # todos los contratos y Puestos Clave solo los de aspirantes ACTIVO. Sin el
    # campo, la fotografía no podría reproducir ambos comportamientos.
    aspirante_estado = models.CharField(max_length=20, blank=True)

    # --- Cargo congelado (repetido a propósito) ---
    ncargo_id_original = models.IntegerField(null=True, blank=True)
    ncargo_descripcion = models.CharField(max_length=150, blank=True)
    cat_ocupacional = models.CharField(max_length=20, blank=True)
    puesto_clave = models.BooleanField(default=False)
    grupo_escala_nivel = models.CharField(max_length=8, blank=True)
    departamento_descripcion = models.CharField(max_length=150, blank=True)

    # --- Tipo de contrato congelado. `ocupa_plaza` decide si consume plaza ---
    tipo_id_original = models.IntegerField(null=True, blank=True)
    tipo_descripcion = models.CharField(max_length=150, blank=True)
    ocupa_plaza = models.BooleanField(default=False)
    requiere_motivo = models.BooleanField(default=False)
    motivo_id_original = models.IntegerField(null=True, blank=True)
    motivo_descripcion = models.CharField(max_length=150, blank=True)

    # --- Datos del propio contrato ---
    mision = models.BooleanField(default=False)
    pais = models.CharField(max_length=100, blank=True)
    fecha_alta = models.DateField(null=True, blank=True)
    duracion = models.IntegerField(null=True, blank=True)
    salario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'Contrato del cierre'
        verbose_name_plural = 'Contratos del cierre'
        ordering = ['departamento_descripcion', 'aspirante_nombre']
        indexes = [
            models.Index(fields=['cierre', 'cat_ocupacional'], name='cierre_contrato_categ_idx'),
            models.Index(fields=['cierre', 'mision'], name='cierre_contrato_mision_idx'),
        ]

    def __str__(self):
        return f'{self.aspirante_nombre} — {self.ncargo_descripcion}'


class EstadoCierreUnidad(Base):
    """Estado actual del ciclo de una unidad. Una fila por unidad.

    Es una **materialización**, no la fuente de verdad: quien manda es
    `servicios.calcular_estado()`, que lo deriva de los cierres existentes y de la
    fecha. Esta tabla existe para poder listar, filtrar y notificar en SQL sin
    recorrer todas las unidades en Python — mismo criterio que
    `CargoPlantilla.cant_cubierta` frente a `cant_cubierta_real`.

    Se refresca en cada declaración y en el barrido diario (`procesar_cierres`).
    """

    unidad = models.OneToOneField(
        UnidadOrganizativa,
        on_delete=models.CASCADE,
        related_name='estado_cierre',
    )
    estado = models.CharField(
        max_length=1,
        choices=EstadoUnidad.choices,
        default=EstadoUnidad.PENDIENTE,
    )
    primer_cierre = models.ForeignKey(
        CierreUnidad,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        help_text='Marca el inicio de la obligación mensual. Si es nulo, la unidad nunca declaró.',
    )
    ultimo_cierre = models.ForeignKey(
        CierreUnidad,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    # Período más antiguo que la unidad debe cerrar. Nulo si está al día.
    periodo_pendiente_anno = models.PositiveSmallIntegerField(null=True, blank=True)
    periodo_pendiente_mes = models.PositiveSmallIntegerField(null=True, blank=True)
    meses_pendientes = models.PositiveSmallIntegerField(default=0)
    fecha_calculo = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Estado de cierre'
        verbose_name_plural = 'Estados de cierre'
        indexes = [
            models.Index(fields=['estado'], name='cierre_estado_idx'),
        ]

    def __str__(self):
        return f'{self.unidad} — {self.get_estado_display()}'

    @property
    def periodo_pendiente(self):
        if self.periodo_pendiente_anno and self.periodo_pendiente_mes:
            return Periodo(self.periodo_pendiente_anno, self.periodo_pendiente_mes)
        return None

    @property
    def nunca_declarada(self):
        return self.primer_cierre_id is None

    @property
    def color_badge(self):
        """Clase de Bootstrap para el badge. La decide el modelo para no repetir
        el mismo `{% if %}` en cada plantilla que muestre el estado."""
        return {
            EstadoUnidad.ACTUALIZADA: 'bg-label-success',
            EstadoUnidad.PENDIENTE: 'bg-label-warning',
            EstadoUnidad.DESACTUALIZADA: 'bg-label-danger',
        }.get(self.estado, 'bg-label-secondary')

    @property
    def color_punto(self):
        """Variante sólida, para el indicador del Gestor de Plantilla."""
        return {
            EstadoUnidad.ACTUALIZADA: 'bg-success',
            EstadoUnidad.PENDIENTE: 'bg-warning',
            EstadoUnidad.DESACTUALIZADA: 'bg-danger',
        }.get(self.estado, 'bg-secondary')
