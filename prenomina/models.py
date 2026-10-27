"""Modelos de Pre-Nómina.

El fichero tiene dos mitades con reglas distintas, y conviene no mezclarlas:

**Configuración viva** (`NPagoHoras`, `NPagoImporte`, `NClaveAusencia`,
`NEscalaAnnosServicio`). Son nomencladores: los edita el Administrador y cambian
con el tiempo. Llevan el prefijo `N` como el resto de nomencladores del
proyecto, pero viven aquí y no en `nomencladores/models.py` por una razón dura:
`NPagoImporte.clean()` llama a `prenomina.formulas`, y `prenomina.models`
importa de `nomencladores` — ponerlos allí sería una importación circular.

**Fotografía** (`ReportePago` y todo lo que cuelga de él). Se rige por la misma
doctrina que `cierres/models.py`, citada aquí a propósito para que nadie la
rompa por comodidad: *las filas de la fotografía no tienen ForeignKey a los
datos vivos, sino copias planas de los valores*. Los `*_id_original` son
referencias blandas para rastrear el origen, jamás para reconstruir el reporte
con un JOIN.

El motivo no es teórico. Cuando un trabajador causa baja, su `CAlta` **se borra
físicamente** (`contratos/models.py`, se crea un `CBaja` en su lugar). Una FK
dejaría el reporte de julio inconsultable en agosto, que es exactamente el
escenario que este módulo existe para sobrevivir.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from auditoria.models import Base
# Orden por arrastre en todo Orbith (27-10-2026); ver `nomencladores.models.Ordenable`.
from nomencladores.models import Ordenable
from strorganizativa.models import UnidadOrganizativa

from . import formulas


# =========================================================================== #
# Configuración: los nomencladores
# =========================================================================== #

class TipoValorImporte(models.TextChoices):
    IMPORTE = 'IMP', 'Importe fijo'
    FORMULA = 'FOR', 'Fórmula'
    ESCALA = 'ESC', 'Escala de años de servicio'


class NPagoHoras(Ordenable, Base):
    """Concepto que se paga en horas. Es una columna del grupo púrpura.

    El `codigo` no es decorativo: es la identidad de la columna en el Excel
    exportado y lo que empareja al reimportar. Por eso es obligatorio y único,
    aunque el fichero de RRHH tenga conceptos sin número.
    """

    codigo = models.PositiveIntegerField(
        unique=True, verbose_name='Código',
        help_text='Número que identifica el concepto. Se usa como clave al '
                  'exportar e importar, así que no debe cambiar.')
    descripcion = models.CharField(
        max_length=150, verbose_name='Descripción',
        help_text='Escriba solo el texto, SIN el código: al exportar se compone '
                  'automáticamente como «código descripción».')

    class Meta:
        verbose_name = 'Pago Asociado por Horas'
        verbose_name_plural = 'Pagos Asociados por Horas'
        ordering = ['orden', 'codigo']
        constraints = [
            models.CheckConstraint(
                condition=Q(codigo__gt=0), name='pagohoras_codigo_positivo'),
        ]

    def __str__(self):
        return f'{self.codigo} {self.descripcion}'

    @property
    def etiqueta(self):
        """Texto tal como aparece en la cabecera del Excel."""
        return f'{self.codigo} {self.descripcion}'


class NEscalaAnnosServicio(Base):
    """Cuantía que corresponde a cada cantidad de años de servicio.

    Orbith ya sabe **cuántos** años lleva un trabajador (se derivan de
    `CAlta.fecha_alta_entidad`, igual que la tarjeta Antigüedad del Dashboard).
    Lo que no sabía es **cuánto dinero** corresponde a cada tramo: eso es esta
    tabla, que venía en la hoja «Rangos» del Excel de RRHH.

    Es un nomenclador y no una constante en el código a propósito: la escala
    cambia con las resoluciones salariales y debe poder corregirse sin
    desplegar.
    """

    annos = models.PositiveSmallIntegerField(
        unique=True, verbose_name='Años de servicio')
    cuantia = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='Cuantía',
        validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        verbose_name = 'Tramo de la Escala de Años de Servicio'
        verbose_name_plural = 'Escala de Años de Servicio'
        ordering = ['annos']

    def __str__(self):
        return f'{self.annos} años → {self.cuantia}'

    @classmethod
    def como_diccionario(cls):
        """La escala completa como `{'1': '200.00', ...}`, lista para congelar.

        Se devuelven cadenas y no `Decimal` porque el destino es un `JSONField`
        y `Decimal` no es serializable a JSON sin perder precisión por el camino.
        """
        return {str(annos): str(cuantia)
                for annos, cuantia in cls.objects.values_list('annos', 'cuantia')}

    @classmethod
    def cuantia_de(cls, escala, annos):
        """Busca en una escala congelada. Devuelve 0 si el tramo no existe.

        Los años por encima del último tramo se llevan al último: es lo que hace
        la hoja de RRHH, donde 30 es el techo y quien lleva 35 cobra igual que
        quien lleva 30.
        """
        if not escala:
            return Decimal('0')
        clave = str(int(annos))
        if clave in escala:
            return Decimal(str(escala[clave]))
        tramos = sorted(int(k) for k in escala)
        if not tramos or int(annos) < tramos[0]:
            return Decimal('0')
        return Decimal(str(escala[str(tramos[-1])]))


class NPagoImporte(Ordenable, Base):
    """Concepto que se paga en dinero. Es una columna del grupo rojo.

    Tres formas de obtener el valor, y ninguna implica escribir lógica de
    negocio en el código:

    * `IMPORTE` — cantidad fija, igual para todos los trabajadores.
    * `FORMULA` — expresión sobre las variables congeladas del trabajador
      (`{{horas}}`, `{{tarifa_horaria}}`, `{{cnci}}`…). Es lo que permite
      expresar «Importe Horas Extras» o «C.N.C.I» sin programarlos.
    * `ESCALA` — búsqueda en la escala de años de servicio.
    """

    codigo = models.PositiveIntegerField(
        unique=True, verbose_name='Código',
        help_text='Número que identifica el concepto. Se usa como clave al '
                  'exportar e importar, así que no debe cambiar.')
    descripcion = models.CharField(
        max_length=150, verbose_name='Descripción',
        help_text='Escriba solo el texto, SIN el código.')
    relacionado_con = models.ForeignKey(
        NPagoHoras, on_delete=models.PROTECT, null=True, blank=True,
        related_name='pagos_importe', verbose_name='Relacionado con',
        help_text='Concepto por horas del que la fórmula toma {{horas}}. Si se '
                  'indica, este importe se añade solo al reporte cuando se '
                  'seleccione ese concepto por horas.')
    tipo_valor = models.CharField(
        max_length=3, choices=TipoValorImporte.choices,
        default=TipoValorImporte.IMPORTE, verbose_name='Tipo de valor')
    importe_fijo = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Importe fijo', validators=[MinValueValidator(Decimal('0'))])
    formula = models.CharField(
        max_length=formulas.LONGITUD_MAXIMA, blank=True, default='',
        verbose_name='Fórmula',
        help_text='Por ejemplo: {{horas}} * {{tarifa_horaria}} * 1.25')

    class Meta:
        verbose_name = 'Pago Asociado por Importe'
        verbose_name_plural = 'Pagos Asociados por Importe'
        ordering = ['orden', 'codigo']
        constraints = [
            models.CheckConstraint(
                condition=Q(codigo__gt=0), name='pagoimporte_codigo_positivo'),
            # Coherencia estructural, verificable en SQL. Lo que el CHECK no
            # puede hacer (parsear la fórmula) lo hace `clean()`; lo que
            # `clean()` no puede garantizar (un `objects.create()` directo, una
            # fixture, un `bulk_create`) lo garantiza esto.
            models.CheckConstraint(
                condition=(
                    Q(tipo_valor='IMP', importe_fijo__isnull=False, formula='')
                    | (Q(tipo_valor='FOR', importe_fijo__isnull=True)
                       & ~Q(formula=''))
                    | Q(tipo_valor='ESC', importe_fijo__isnull=True, formula='')
                ),
                name='pagoimporte_valor_coherente'),
        ]

    def __str__(self):
        return f'{self.codigo} {self.descripcion}'

    @property
    def etiqueta(self):
        return f'{self.codigo} {self.descripcion}'

    def clean(self):
        """Valida la coherencia del valor **al guardar**, no al generar el reporte.

        Es un requisito explícito: una fórmula inválida no debe poder llegar a un
        reporte. Por eso todo el CRUD de este módulo pasa por `ModelForm` (que
        ejecuta `clean()`) y no por JSON escrito a mano.
        """
        super().clean()
        errores = {}
        texto = (self.formula or '').strip()

        if self.tipo_valor == TipoValorImporte.IMPORTE:
            if self.importe_fijo is None:
                errores['importe_fijo'] = 'Indique el importe.'
            if texto:
                errores['formula'] = 'Un concepto de importe fijo no lleva fórmula.'

        elif self.tipo_valor == TipoValorImporte.FORMULA:
            if self.importe_fijo is not None:
                errores['importe_fijo'] = 'Un concepto por fórmula no lleva importe fijo.'
            if not texto:
                errores['formula'] = 'Escriba la fórmula. Por ejemplo: {{horas}} * 1.25'
            else:
                try:
                    formulas.validar(texto)
                except formulas.ErrorDeFormula as error:
                    errores['formula'] = str(error)
                else:
                    if 'horas' in formulas.variables_usadas(texto) and not self.relacionado_con_id:
                        errores['relacionado_con'] = (
                            'La fórmula usa {{horas}}: indique de qué concepto '
                            'por horas debe tomarlas.')

        elif self.tipo_valor == TipoValorImporte.ESCALA:
            if self.importe_fijo is not None:
                errores['importe_fijo'] = 'Un concepto por escala no lleva importe fijo.'
            if texto:
                errores['formula'] = 'Un concepto por escala no lleva fórmula.'
            if not NEscalaAnnosServicio.objects.exists():
                errores['tipo_valor'] = (
                    'La escala de años de servicio está vacía. Configúrela antes '
                    'de usar este tipo de valor.')

        if errores:
            raise ValidationError(errores)


class NClaveAusencia(Ordenable, Base):
    """Clave de ausencia. Es una columna del grupo verde.

    Los tres interruptores de resta son **independientes entre sí** y también
    independientes de `relacionado_con`. La lectura intuitiva («si se paga, no se
    descuenta») es falsa y produce doble conteo: lo normal es que unas vacaciones
    se descuenten de las horas del mes *y además* se paguen a través de un
    concepto por horas.
    """

    codigo = models.PositiveIntegerField(
        unique=True, verbose_name='Código',
        help_text='Número que identifica la clave. Se usa como clave al '
                  'exportar e importar, así que no debe cambiar.')
    descripcion = models.CharField(
        max_length=150, verbose_name='Descripción',
        help_text='Escriba solo el texto, SIN el código.')
    resta_horas_mes = models.BooleanField(
        default=True, verbose_name='Resta de horas mes',
        help_text='Si está activo, sus horas reducen las horas realmente '
                  'trabajadas del trabajador.')
    resta_sistema_pago = models.BooleanField(
        default=True, verbose_name='Resta de sistema de pago')
    resta_utilidades = models.BooleanField(
        default=True, verbose_name='Resta utilidades')
    relacionado_con = models.ForeignKey(
        NPagoHoras, on_delete=models.PROTECT, null=True, blank=True,
        related_name='ausencias', verbose_name='Relacionado con',
        help_text='Si se indica, las horas de esta ausencia ALIMENTAN ese '
                  'concepto por horas, que pasa a ser de solo lectura en el '
                  'reporte. Es independiente de «Resta de horas mes».')

    class Meta:
        verbose_name = 'Clave de Ausencia'
        verbose_name_plural = 'Claves de Ausencia'
        ordering = ['orden', 'codigo']
        constraints = [
            models.CheckConstraint(
                condition=Q(codigo__gt=0), name='claveausencia_codigo_positivo'),
        ]

    def __str__(self):
        return f'{self.codigo} {self.descripcion}'

    @property
    def etiqueta(self):
        return f'{self.codigo} {self.descripcion}'


# =========================================================================== #
# Fotografía: el reporte
# =========================================================================== #

class EstadoReporte(models.TextChoices):
    BORRADOR = 'B', 'Borrador'
    CERRADO = 'C', 'Cerrado'
    HISTORICO = 'H', 'Histórico'


class Quincena(models.IntegerChoices):
    """Qué trozo del mes cubre un reporte.

    Lo decide el período de pago de la entidad (`Configuracion.periodo`), no el
    usuario: con pago Mensual solo existe MES_COMPLETO y hay un reporte por
    unidad y mes; con pago Quincenal hay dos, PRIMERA y SEGUNDA.

    Se guarda como número —y no como un booleano «es quincenal»— porque forma
    parte de la clave que identifica al reporte (`unidad + año + mes +
    quincena`) y porque su orden natural es el que usan `es_ultimo` y
    `_archivar_anteriores` para saber qué reporte va delante de cuál.

    MES_COMPLETO vale 0 a propósito: es el valor que reciben los reportes que ya
    existían cuando se añadió el campo, y es también el que ordena primero.
    """

    MES_COMPLETO = 0, 'Mes completo'
    PRIMERA = 1, '1ra Quincena'
    SEGUNDA = 2, '2da Quincena'


class ReportePago(Base):
    """Cabecera del Reporte de Pago de una unidad para un mes.

    Mismo criterio que `cierres.CierreUnidad`: FK viva a la unidad —la necesitan
    el alcance del Moderador y la restricción de unicidad— **más** copias planas
    de todo lo que el documento imprime. Nada por debajo de esta cabecera tiene
    FK a datos vivos.
    """

    unidad = models.ForeignKey(
        UnidadOrganizativa, on_delete=models.PROTECT,
        related_name='reportes_pago', verbose_name='Unidad Organizativa')
    anno = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')
    # Completa la identidad del reporte. Con pago Mensual siempre es
    # MES_COMPLETO y todo se comporta como antes; con pago Quincenal es lo que
    # permite que convivan dos reportes de la misma unidad en el mismo mes.
    quincena = models.PositiveSmallIntegerField(
        choices=Quincena.choices, default=Quincena.MES_COMPLETO,
        verbose_name='Quincena')

    # Plantilla de la que salieron sus conceptos. Es **trazabilidad, no
    # dependencia**: los conceptos del reporte son copias congeladas
    # (`ReporteConcepto*`), así que editar la plantilla después no cambia nada
    # aquí. Esta FK solo sirve para saber de dónde vino y para que `PROTECT`
    # impida borrar una plantilla ya utilizada.
    #
    # `null=True` por los reportes anteriores a las plantillas, que configuraron
    # sus conceptos a mano y no tienen ninguna a la que apuntar.
    plantilla = models.ForeignKey(
        'PlantillaReporte', on_delete=models.PROTECT, null=True, blank=True,
        related_name='reportes', verbose_name='Plantilla')
    estado = models.CharField(
        max_length=1, choices=EstadoReporte.choices,
        default=EstadoReporte.BORRADOR, verbose_name='Estado')

    # --- Encabezado del documento (filas 1-5 del Excel), congelado ---
    fondo_tiempo = models.DecimalField(
        max_digits=6, decimal_places=2, verbose_name='Horas del mes',
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Fondo de tiempo real del mes. Es el número que aparece como '
                  '«Horas del mes» en la cabecera del reporte.')
    # Divisor de la tarifa horaria. Es una magnitud DISTINTA de `fondo_tiempo`:
    # aquélla son las horas reales del mes concreto, ésta el promedio mensual
    # convencional con el que se calculan las tarifas en todo Orbith
    # (`Configuracion.fondo_tiempo_calc_tarif`). No se deben fusionar.
    fondo_tarifa = models.DecimalField(
        max_digits=6, decimal_places=2,
        verbose_name='Fondo de tiempo para la tarifa horaria',
        validators=[MinValueValidator(Decimal('0.01'))])
    fecha_desde = models.DateField(verbose_name='Período de pago — desde')
    fecha_hasta = models.DateField(verbose_name='Período de pago — hasta')
    hecho_por = models.CharField(max_length=150, blank=True, default='',
                                 verbose_name='Hecho por')
    revisado_por = models.CharField(max_length=150, blank=True, default='',
                                    verbose_name='Revisado por')
    aprobado_por = models.CharField(max_length=150, blank=True, default='',
                                    verbose_name='Aprobado por')

    # --- Estructura de la unidad, congelada (mismo criterio que CierreUnidad) ---
    unidad_codigo_original = models.IntegerField(null=True, blank=True)
    unidad_descripcion = models.CharField(max_length=150, blank=True, default='')
    unidad_grupo_nomina = models.IntegerField(null=True, blank=True)
    unidad_orden_informe = models.PositiveIntegerField(null=True, blank=True)

    # --- Cierre ---
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reportes_pago_cerrados')
    # Congelado, mismo criterio que `CierreUnidad.declarado_por_nombre`: si el
    # usuario se elimina más adelante, el documento no debe quedar en blanco.
    cerrado_por_nombre = models.CharField(max_length=150, blank=True, default='')
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    # --- Totales congelados, para listar el historial sin recorrer las filas ---
    total_trabajadores = models.PositiveIntegerField(default=0)
    total_horas_trabajadas = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'))
    total_importes = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0'))

    class Meta:
        verbose_name = 'Reporte de Pago'
        verbose_name_plural = 'Reportes de Pago'
        ordering = ['-anno', '-mes', '-quincena', 'unidad_orden_informe']
        constraints = [
            # `quincena` entra en la clave: con pago Mensual siempre vale 0 y la
            # regla es la misma de antes (un reporte por unidad y mes); con pago
            # Quincenal permite exactamente dos, la 1ra y la 2da.
            models.UniqueConstraint(
                fields=['unidad', 'anno', 'mes', 'quincena'],
                name='reporte_pago_unico_por_unidad_y_periodo'),
            # Una unidad no puede tener dos borradores a la vez. Es la mitad en
            # base de datos de la regla de ciclo de vida: para empezar el mes
            # siguiente hay que cerrar el actual. Índice único parcial.
            #
            # Se mantiene tal cual con las quincenas: para empezar la 2da hay
            # que cerrar la 1ra, que es lo que se decidió al implementarlas.
            models.UniqueConstraint(
                fields=['unidad'], condition=Q(estado='B'),
                name='reporte_pago_un_borrador_por_unidad'),
            models.CheckConstraint(
                condition=Q(mes__gte=1) & Q(mes__lte=12),
                name='reporte_pago_mes_valido'),
            models.CheckConstraint(
                condition=Q(quincena__gte=0) & Q(quincena__lte=2),
                name='reporte_pago_quincena_valida'),
            models.CheckConstraint(
                condition=Q(fecha_hasta__gte=F('fecha_desde')),
                name='reporte_pago_fechas_coherentes'),
        ]
        indexes = [
            models.Index(fields=['anno', 'mes'], name='reporte_pago_periodo_idx'),
            models.Index(fields=['estado'], name='reporte_pago_estado_idx'),
        ]

    def __str__(self):
        return f'{self.unidad_descripcion} — {self.etiqueta_periodo}'

    @property
    def periodo(self):
        """Reutiliza el `Periodo` de Cierres: mismo concepto, una sola aritmética.

        Se importa solo la dataclass, que no toca la base de datos. Las ventanas
        de declaración de Cierres (día 20 al 25) **no** aplican aquí: un reporte
        de pago se crea y se cierra cuando la unidad lo necesite.
        """
        from cierres.periodos import Periodo
        return Periodo(self.anno, self.mes)

    @property
    def etiqueta_periodo(self):
        """Cómo se nombra este reporte: «Agosto 2026» o «1ra Quincena de Agosto 2026».

        Existe porque `periodo.etiqueta` solo sabe de mes y año, y con pago
        Quincenal habría DOS reportes de la misma unidad con exactamente el
        mismo texto en el listado. La quincena solo se menciona cuando la hay:
        con pago Mensual la etiqueta es la de siempre, sin coletillas.
        """
        if self.quincena == Quincena.MES_COMPLETO:
            return self.periodo.etiqueta
        return f'{self.get_quincena_display()} de {self.periodo.etiqueta}'

    @property
    def editable(self):
        return self.estado == EstadoReporte.BORRADOR

    @property
    def es_ultimo(self):
        """¿Es el reporte más reciente de su unidad?

        Es lo que decide si puede reabrirse: en cuanto existe uno posterior, éste
        queda bloqueado definitivamente.

        La quincena entra en la comparación como tercer criterio de desempate,
        detrás del año y el mes: sin ella, la 1ra quincena de un mes se creería
        reabrible teniendo ya la 2da cerrada detrás.
        """
        return not (ReportePago.objects
                    .filter(unidad_id=self.unidad_id)
                    .filter(Q(anno__gt=self.anno)
                            | Q(anno=self.anno, mes__gt=self.mes)
                            | Q(anno=self.anno, mes=self.mes,
                                quincena__gt=self.quincena))
                    .exists())

    @property
    def reabrible(self):
        return self.estado == EstadoReporte.CERRADO and self.es_ultimo

    @property
    def color_badge(self):
        """El color lo decide el modelo, no una cadena de `{% if %}` en la plantilla.

        Mismo criterio que `cierres.EstadoCierreUnidad.color_badge`.
        """
        return {
            EstadoReporte.BORRADOR: 'warning',
            EstadoReporte.CERRADO: 'success',
            EstadoReporte.HISTORICO: 'secondary',
        }.get(self.estado, 'secondary')


class ReporteConceptoHoras(models.Model):
    """Un concepto por horas, tal como estaba al configurarse este reporte.

    No hereda de `Base`: es un hecho inmutable que nace y muere con su reporte,
    igual que `CierreCargo`.
    """

    reporte = models.ForeignKey(
        ReportePago, on_delete=models.CASCADE, related_name='conceptos_horas')
    pago_id_original = models.IntegerField(null=True, blank=True)
    codigo = models.PositiveIntegerField()
    descripcion = models.CharField(max_length=150)
    orden = models.PositiveSmallIntegerField(default=0)
    # True si alguna clave de ausencia seleccionada en este reporte apunta aquí.
    # Congelado: decide si la columna es de solo lectura en pantalla, en el modal
    # y en la importación.
    es_derivado = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Concepto por horas del reporte'
        verbose_name_plural = 'Conceptos por horas del reporte'
        ordering = ['orden', 'codigo']
        constraints = [
            models.UniqueConstraint(
                fields=['reporte', 'codigo'],
                name='concepto_horas_unico_por_reporte'),
        ]

    def __str__(self):
        return f'{self.codigo} {self.descripcion}'

    @property
    def etiqueta(self):
        return f'{self.codigo} {self.descripcion}'


class ReporteConceptoAusencia(models.Model):
    """Una clave de ausencia, congelada con sus tres interruptores."""

    reporte = models.ForeignKey(
        ReportePago, on_delete=models.CASCADE, related_name='conceptos_ausencia')
    clave_id_original = models.IntegerField(null=True, blank=True)
    codigo = models.PositiveIntegerField()
    descripcion = models.CharField(max_length=150)
    orden = models.PositiveSmallIntegerField(default=0)
    resta_horas_mes = models.BooleanField(default=True)
    resta_sistema_pago = models.BooleanField(default=True)
    resta_utilidades = models.BooleanField(default=True)
    # FK a una fila hermana de la MISMA fotografía, no a datos vivos. Es
    # exactamente `CierreContrato.cierre_cargo`, así que no viola la doctrina.
    relacionado_con = models.ForeignKey(
        ReporteConceptoHoras, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ausencias')
    relacionado_con_codigo = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Clave de ausencia del reporte'
        verbose_name_plural = 'Claves de ausencia del reporte'
        ordering = ['orden', 'codigo']
        constraints = [
            models.UniqueConstraint(
                fields=['reporte', 'codigo'],
                name='concepto_ausencia_unico_por_reporte'),
        ]

    def __str__(self):
        return f'{self.codigo} {self.descripcion}'

    @property
    def etiqueta(self):
        return f'{self.codigo} {self.descripcion}'


class ReporteConceptoImporte(models.Model):
    """Un concepto por importe, congelado con su fórmula o su valor."""

    reporte = models.ForeignKey(
        ReportePago, on_delete=models.CASCADE, related_name='conceptos_importe')
    pago_id_original = models.IntegerField(null=True, blank=True)
    codigo = models.PositiveIntegerField()
    descripcion = models.CharField(max_length=150)
    orden = models.PositiveSmallIntegerField(default=0)
    tipo_valor = models.CharField(max_length=3, choices=TipoValorImporte.choices)
    importe_fijo = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    formula = models.CharField(
        max_length=formulas.LONGITUD_MAXIMA, blank=True, default='')
    # ÚNICO uso de JSON en el módulo, y por el mismo motivo que
    # `CierreCargo.familias_ids`: aplanar 30 tramos aquí evita una tabla de 30
    # filas por concepto y por reporte para un dato que solo se busca por clave
    # y nunca se agrega.
    escala_congelada = models.JSONField(default=dict, blank=True)
    relacionado_con = models.ForeignKey(
        ReporteConceptoHoras, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='importes')
    relacionado_con_codigo = models.PositiveIntegerField(null=True, blank=True)
    # True: entró solo, por estar relacionado con un concepto por horas
    # seleccionado. False: lo añadió el Moderador a mano. Es lo que permite
    # impedir el alta manual de uno ya automático y explicar en pantalla por qué
    # está ahí.
    automatico = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Concepto por importe del reporte'
        verbose_name_plural = 'Conceptos por importe del reporte'
        ordering = ['orden', 'codigo']
        constraints = [
            models.UniqueConstraint(
                fields=['reporte', 'codigo'],
                name='concepto_importe_unico_por_reporte'),
        ]

    def __str__(self):
        return f'{self.codigo} {self.descripcion}'

    @property
    def etiqueta(self):
        return f'{self.codigo} {self.descripcion}'


class ReporteTrabajador(models.Model):
    """Un trabajador dentro del reporte, congelado al cargarse.

    Sin FK a `CAlta` ni a `Aspirante`: al dar de baja a un trabajador su `CAlta`
    se **borra físicamente**, así que una FK dejaría el reporte del mes anterior
    inconsultable. Ver el docstring del módulo.
    """

    reporte = models.ForeignKey(
        ReportePago, on_delete=models.CASCADE, related_name='trabajadores')
    contrato_id_original = models.IntegerField(null=True, blank=True)
    aspirante_id_original = models.IntegerField(null=True, blank=True)

    # --- Identidad. `no_expediente` empareja al importar; `doc_identidad` es la
    #     aserción cruzada que detecta filas desplazadas.
    no_expediente = models.CharField(max_length=5, verbose_name='No. Expediente')
    doc_identidad = models.CharField(max_length=11, blank=True, default='')
    nombre_completo = models.CharField(max_length=150)

    # --- Clasificación congelada. `cat_ocupacional` son `choices` y no una
    #     tabla: se congelan clave Y etiqueta, porque el Excel imprime la
    #     etiqueta y las etiquetas de un `choices` pueden reescribirse.
    cat_ocupacional = models.CharField(max_length=20, blank=True, default='')
    cat_ocupacional_desc = models.CharField(max_length=60, blank=True, default='')
    ncargo_descripcion = models.CharField(max_length=150, blank=True, default='')
    departamento_descripcion = models.CharField(max_length=150, blank=True, default='')

    # --- Subunidad congelada. Solo se rellena cuando el reporte es de una
    #     Unidad Principal (`captura.datos_de_trabajador`): permite agrupar la
    #     rejilla por Sub Unidad → Departamento sin tener que resolver, en cada
    #     visita, a qué subunidad pertenecía el `Departamento` del trabajador —
    #     resolución que además dejaría de ser posible si esa subunidad se
    #     reorganiza o se borra después. En un reporte de una unidad sin hijas
    #     queda en blanco: no hay nivel de Sub Unidad que mostrar.
    unidad_sub_id_original = models.IntegerField(null=True, blank=True)
    unidad_sub_descripcion = models.CharField(max_length=150, blank=True, default='')

    # --- Calendario congelado ---
    # `horas_mes` es el fondo de tiempo DE ESTE TRABAJADOR: sale del Calendario
    # de Pago del período, según la jornada que tenga asignada. Sustituye al
    # antiguo `ReportePago.fondo_tiempo`, que era un único número para todo el
    # reporte y no admitía que dos trabajadores de la misma unidad tuvieran
    # jornadas distintas.
    #
    # Se congela como todo lo demás: cambiar la asignación de un trabajador o las
    # horas del calendario NO reescribe los reportes ya creados.
    calendario_codigo = models.PositiveIntegerField(null=True, blank=True)
    calendario_descripcion = models.CharField(max_length=20, blank=True, default='')
    horas_mes = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Horas del mes')

    # --- Base económica congelada ---
    # `CAlta.salario_actual` es, pese al nombre, exactamente el salario DE
    # ESCALA: `contratos/salarios.py::calcular_salario()` devuelve el monto de
    # `NSalario` (o el básico del cargo si el salario es fijo), sin maestría,
    # CNCI ni instructor, que aquí son columnas rojas aparte.
    salario_escala = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0'))
    # Cuatro decimales a propósito: es un valor intermedio de fórmulas. El
    # redondeo a dos se aplica una sola vez, sobre el importe final.
    tarifa_horaria = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal('0'))
    # Mismo tamaño que el contrato y los cierres (23-10-2026): antes Maestría y
    # Doctorado eran enteros (se perdían los centavos) e Instructor tenía tope en
    # 99,99, así que un instructor de 500 hacía fallar la creación del reporte.
    cnci = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    maestria = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    doctorado = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    instructor = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    anos_servicio = models.PositiveSmallIntegerField(default=0)
    fecha_alta_entidad = models.DateField(null=True, blank=True)

    # --- Denormalizado, recalculado en cada escritura ---
    total_horas_descontadas = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('0'))
    horas_trabajadas = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('0'))
    total_importe = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'))

    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Trabajador del reporte'
        verbose_name_plural = 'Trabajadores del reporte'
        ordering = ['orden', 'nombre_completo']
        constraints = [
            models.UniqueConstraint(
                fields=['reporte', 'no_expediente'],
                name='reporte_trabajador_expediente_unico'),
            models.CheckConstraint(
                condition=Q(horas_trabajadas__gte=0),
                name='reporte_trabajador_horas_no_negativas'),
        ]
        indexes = [
            models.Index(fields=['reporte', 'orden'], name='reporte_trab_orden_idx'),
            models.Index(fields=['reporte', 'cat_ocupacional'],
                         name='reporte_trab_cat_idx'),
        ]

    def __str__(self):
        return f'{self.no_expediente} — {self.nombre_completo}'


class ValorAusencia(models.Model):
    """Horas de una clave de ausencia para un trabajador."""

    trabajador = models.ForeignKey(
        ReporteTrabajador, on_delete=models.CASCADE, related_name='valores_ausencia')
    concepto = models.ForeignKey(
        ReporteConceptoAusencia, on_delete=models.CASCADE, related_name='valores')
    horas = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal('0'))

    class Meta:
        verbose_name = 'Horas de ausencia'
        verbose_name_plural = 'Horas de ausencia'
        constraints = [
            models.UniqueConstraint(
                fields=['trabajador', 'concepto'], name='valor_ausencia_unico'),
            models.CheckConstraint(
                condition=Q(horas__gte=0), name='valor_ausencia_no_negativo'),
        ]
        indexes = [
            models.Index(fields=['concepto'], name='valor_ausencia_concepto_idx'),
        ]


class ValorHoras(models.Model):
    """Horas de un pago asociado por horas para un trabajador.

    Si el concepto es derivado, este valor no lo teclea nadie: lo calcula
    `calculos.py` como la suma de las ausencias que lo alimentan.
    """

    trabajador = models.ForeignKey(
        ReporteTrabajador, on_delete=models.CASCADE, related_name='valores_horas')
    concepto = models.ForeignKey(
        ReporteConceptoHoras, on_delete=models.CASCADE, related_name='valores')
    horas = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal('0'))

    class Meta:
        verbose_name = 'Horas de pago asociado'
        verbose_name_plural = 'Horas de pagos asociados'
        constraints = [
            models.UniqueConstraint(
                fields=['trabajador', 'concepto'], name='valor_horas_unico'),
            models.CheckConstraint(
                condition=Q(horas__gte=0), name='valor_horas_no_negativo'),
        ]
        indexes = [
            models.Index(fields=['concepto'], name='valor_horas_concepto_idx'),
        ]


class ValorImporte(models.Model):
    """Importe de un pago por importe para un trabajador.

    `horas_base` congela la entrada que produjo el número. Sin ella, un reporte
    cerrado enseña una cifra que nadie puede explicar sin volver a ejecutar la
    fórmula — y volver a ejecutarla es exactamente lo que el histórico prohíbe.
    """

    trabajador = models.ForeignKey(
        ReporteTrabajador, on_delete=models.CASCADE, related_name='valores_importe')
    concepto = models.ForeignKey(
        ReporteConceptoImporte, on_delete=models.CASCADE, related_name='valores')
    importe = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'))
    horas_base = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'Importe del trabajador'
        verbose_name_plural = 'Importes del trabajador'
        constraints = [
            models.UniqueConstraint(
                fields=['trabajador', 'concepto'], name='valor_importe_unico'),
        ]
        indexes = [
            models.Index(fields=['concepto'], name='valor_importe_concepto_idx'),
        ]


# =========================================================================== #
# Calendario: tipos de jornada y horas por quincena
#
# Tercera mitad del módulo, con reglas propias que no son ni las de los
# nomencladores ni las de la fotografía:
#
# **Son datos personales.** `Calendario` y `CalendarioPago` pertenecen a un
# usuario concreto (Administrador o Moderador), no a la empresa ni a una unidad.
# Cada uno define sus jornadas y sus horas. El Administrador ve las de todos
# desde el panel de Django, pero en la aplicación cada cual gestiona las suyas.
#
# **El histórico se congela por línea, no por período.** `CalendarioPagoDetalle`
# copia el código y la descripción vigentes al añadirse, igual que
# `ReporteTrabajador` copia los datos del trabajador. Eso es lo que permite
# renombrar un calendario maestro sin reescribir los períodos ya creados —y lo
# que hace posible ofrecer al usuario elegir entre ambas cosas.
# =========================================================================== #

class Calendario(models.Model):
    """Un tipo de jornada laboral. Dato maestro, personal de cada usuario.

    El código es único **por usuario**, no en toda la tabla: son catálogos
    personales, así que dos usuarios pueden tener cada uno su «01» sin que uno
    le pise el número al otro.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='calendarios', verbose_name='Usuario')
    codigo = models.PositiveIntegerField(verbose_name='Código')
    descripcion = models.CharField(max_length=20, verbose_name='Descripción')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        verbose_name = 'Calendario'
        verbose_name_plural = 'Calendarios'
        ordering = ['codigo']
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'codigo'],
                name='calendario_codigo_unico_por_usuario'),
        ]

    def __str__(self):
        return self.etiqueta

    @property
    def etiqueta(self):
        return f'{self.codigo:02d} — {self.descripcion}'

    @property
    def periodos_donde_se_usa(self):
        """Períodos en los que ya se usó, para poder explicar por qué no se borra."""
        return (CalendarioPago.objects
                .filter(detalles__calendario=self)
                .order_by('anno', 'mes').distinct())

    @property
    def eliminable(self):
        """Solo si nunca se ha usado. Una vez usado, es histórico."""
        return not self.detalles.exists()


class CalendarioPago(models.Model):
    """Un período (año + mes) de un usuario, con sus líneas de horas.

    El estado **sí se guarda** aquí, en vez de derivarse de los reportes. La
    razón es que un usuario lleva varias unidades, cada una con su propio
    `ReportePago`: derivar «cerrado» de ellos obligaría a decidir si basta con
    que cierre una o si tienen que cerrar todas, y esa regla cambiaría de
    significado cada vez que al usuario le reasignaran una unidad. Con un campo
    propio, la única fuente de verdad es `servicios_calendario.cerrar_periodo()`,
    que es lo que invoca «Cerrar mes» desde Gestión de Reportes de Pagos.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='calendarios_pago', verbose_name='Usuario')
    anno = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')

    cerrado = models.BooleanField(default=False, verbose_name='Cerrado')
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    cerrado_por_nombre = models.CharField(max_length=150, blank=True, default='')

    class Meta:
        verbose_name = 'Calendario de pago'
        verbose_name_plural = 'Calendarios de pago'
        ordering = ['-anno', '-mes']
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'anno', 'mes'],
                name='calendario_pago_periodo_unico'),
            models.CheckConstraint(
                condition=Q(mes__gte=1) & Q(mes__lte=12),
                name='calendario_pago_mes_valido'),
        ]

    def __str__(self):
        return f'{self.etiqueta} — {self.usuario}'

    @property
    def periodo(self):
        """Reutiliza el `Periodo` de Cierres: misma aritmética de año+mes."""
        from cierres.periodos import Periodo
        return Periodo(self.anno, self.mes)

    @property
    def etiqueta(self):
        return self.periodo.etiqueta

    @property
    def editable(self):
        """Cerrado es histórico: ni se edita ni se elimina."""
        return not self.cerrado


class CalendarioPagoDetalle(models.Model):
    """Una línea del período: un calendario y sus horas por quincena.

    `codigo_historico` y `descripcion_historica` son la fotografía, con la misma
    doctrina que `ReporteTrabajador`. La diferencia es que aquí el usuario puede
    decidir refrescar la descripción al renombrar el calendario maestro
    («Actualizar histórico»), porque un cambio de nombre suele ser una corrección
    y no un dato nuevo. El código y las horas no se tocan nunca.

    La FK a `Calendario` es `PROTECT` a propósito: es lo que impide borrar un
    calendario ya usado aunque alguien se salte la comprobación de la vista.
    """

    calendario_pago = models.ForeignKey(
        CalendarioPago, on_delete=models.CASCADE, related_name='detalles')
    calendario = models.ForeignKey(
        Calendario, on_delete=models.PROTECT, related_name='detalles')

    codigo_historico = models.PositiveIntegerField(verbose_name='Código')
    descripcion_historica = models.CharField(
        max_length=20, verbose_name='Descripción')

    horas_q1 = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Horas 1ra QNA')
    horas_q2 = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Horas 2da QNA')

    class Meta:
        verbose_name = 'Línea del calendario de pago'
        verbose_name_plural = 'Líneas del calendario de pago'
        ordering = ['codigo_historico']
        constraints = [
            models.UniqueConstraint(
                fields=['calendario_pago', 'calendario'],
                name='calendario_pago_detalle_unico'),
            models.CheckConstraint(
                condition=Q(horas_q1__gte=0) & Q(horas_q2__gte=0),
                name='calendario_pago_horas_no_negativas'),
        ]

    def __str__(self):
        return f'{self.codigo_historico:02d} — {self.horas_mes}'

    @property
    def horas_mes(self):
        """Siempre calculado. No se persiste para que no pueda discrepar."""
        return (self.horas_q1 or Decimal('0')) + (self.horas_q2 or Decimal('0'))


class AsignacionCalendario(models.Model):
    """El calendario que le toca a un trabajador. Permanente hasta que se cambie.

    Cuelga del contrato (`CAlta`) y no del aspirante porque es el contrato el que
    define la relación laboral vigente, que es la que tiene jornada. Al causar
    baja, `CAlta` se borra físicamente y la asignación se va con él: es correcto,
    porque el reporte ya habrá congelado las horas que usó.

    Es **una sola por trabajador**, sin importar quién la asignó: aunque los
    calendarios sean catálogos personales, el trabajador es único y sus horas no
    pueden depender de quién abra el reporte.
    """

    contrato = models.OneToOneField(
        'contratos.CAlta', on_delete=models.CASCADE,
        related_name='asignacion_calendario', verbose_name='Contrato')
    calendario = models.ForeignKey(
        Calendario, on_delete=models.PROTECT, related_name='asignaciones')
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_calendario')
    fecha_asignacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Calendario del trabajador'
        verbose_name_plural = 'Calendarios de los trabajadores'

    def __str__(self):
        return f'{self.contrato} → {self.calendario}'


# =========================================================================== #
# Plantillas de reporte de pago
#
# Una plantilla es una **selección reutilizable de conceptos**: qué claves de
# ausencia, qué pagos por horas y qué pagos por importe llevará el reporte. Se
# define una vez y sirve para cualquier unidad y cualquier período.
#
# La diferencia con los `ReporteConcepto*` es la razón de ser de las dos cosas y
# conviene no confundirlas:
#
# * La plantilla apunta a los nomencladores **vivos** (M2M). Es una selección,
#   no una fotografía: si mañana se corrige la descripción de una clave, la
#   plantilla debe reflejar la corrección.
# * Los `ReporteConcepto*` son **copias planas** hechas al aplicar la plantilla a
#   un reporte concreto. Ahí está la fotografía, y por eso editar la plantilla
#   más tarde no altera ningún reporte ya creado.
#
# Esa separación es lo que cumple la regla del histórico sin inventar nada: el
# mecanismo de congelado ya existía, la plantilla solo decide qué se congela.
# =========================================================================== #

class PlantillaReporte(models.Model):
    """Selección de conceptos reutilizable. Personal de cada usuario.

    La descripción es única **por usuario**, no en toda la tabla: son catálogos
    personales, igual que los calendarios, y dos moderadores pueden llamar
    «Oficina» a plantillas distintas sin pisarse.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='plantillas_reporte', verbose_name='Usuario')
    descripcion = models.CharField(max_length=30, verbose_name='Descripción')
    fecha_creado = models.DateTimeField(auto_now_add=True)
    fecha_actualizado = models.DateTimeField(auto_now=True)

    # Relaciones a los nomencladores VIVOS. Los importes guardados son solo los
    # elegidos a mano: los que entran por estar relacionados con un pago por
    # horas seleccionado se derivan al aplicar la plantilla, igual que hoy hace
    # `servicios.configurar_conceptos()`. Guardarlos sería duplicar una regla que
    # ya vive en un solo sitio.
    claves_ausencia = models.ManyToManyField(
        NClaveAusencia, blank=True, related_name='plantillas',
        verbose_name='Claves de ausencia')
    pagos_horas = models.ManyToManyField(
        NPagoHoras, blank=True, related_name='plantillas',
        verbose_name='Pagos asociados por horas')
    pagos_importe = models.ManyToManyField(
        NPagoImporte, blank=True, related_name='plantillas',
        verbose_name='Pagos asociados por importe')

    class Meta:
        verbose_name = 'Plantilla de reporte'
        verbose_name_plural = 'Plantillas de reporte'
        ordering = ['descripcion']
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'descripcion'],
                name='plantilla_descripcion_unica_por_usuario'),
        ]

    def __str__(self):
        return self.descripcion

    # ------------------------------------------------------------------ #
    # Selección
    # ------------------------------------------------------------------ #

    def codigos(self):
        """`(ausencias, horas, importes)` como conjuntos de códigos.

        Es la forma canónica de la selección, y la que se compara para decidir
        si una duplicación cambió algo. Se devuelven conjuntos porque el orden
        de marcado no define una configuración distinta.
        """
        return (
            set(self.claves_ausencia.values_list('codigo', flat=True)),
            set(self.pagos_horas.values_list('codigo', flat=True)),
            set(self.pagos_importe.values_list('codigo', flat=True)),
        )

    @property
    def total_conceptos(self):
        return (self.claves_ausencia.count() + self.pagos_horas.count()
                + self.pagos_importe.count())

    # ------------------------------------------------------------------ #
    # Uso y borrado
    # ------------------------------------------------------------------ #

    @property
    def reportes_que_la_usan(self):
        """Cualquier reporte, en cualquier estado: abierto, cerrado o histórico.

        Una vez usada, la plantilla queda protegida para no romper la
        trazabilidad de por qué un reporte tiene las columnas que tiene.
        """
        return self.reportes.all()

    @property
    def eliminable(self):
        return not self.reportes.exists()
