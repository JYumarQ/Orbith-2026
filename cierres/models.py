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

    # Denormalización de (anno, mes) como 'AAAA-MM'. Es exactamente
    # `Periodo.clave`, guardado en columna para que Informe Inteligente pueda
    # ofrecer el período como UN solo desplegable con únicamente los meses que
    # de verdad tienen cierre. Con `anno` y `mes` por separado el usuario podría
    # combinar un año y un mes que nunca se cerraron juntos y recibir un informe
    # vacío sin entender por qué. Se rellena en `save()` para que no pueda
    # quedar desincronizada de los dos campos de los que deriva.
    periodo_clave = models.CharField(max_length=7, blank=True, db_index=True,
                                     verbose_name='Período')

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

    def save(self, *args, **kwargs):
        # `periodo_clave` es dato derivado: se recalcula siempre, nunca se
        # confía en lo que traiga la instancia.
        self.periodo_clave = self.periodo.clave
        super().save(*args, **kwargs)

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

    # Congelados para que el informe histórico pueda ofrecer las mismas
    # columnas que el informe en tiempo real (ver `informe_inteligente`).
    rol_tipo = models.CharField(max_length=50, blank=True)
    nivel_preparacion_nombre = models.CharField(max_length=150, blank=True)
    activo = models.BooleanField(default=True)

    # --- Cifras de plantilla ---
    cant_aprobada = models.IntegerField(default=0)
    cant_cubierta = models.IntegerField(default=0)
    # Se congela igual que el resto: un cargo fuera de la plantilla aprobada
    # existía ese mes y su gente cobró, pero sus plazas NUNCA sumaron en los
    # totales aprobados. Sin este campo la fotografía no podría reproducirlo.
    en_plantilla = models.BooleanField(default=True)
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

    # --- Formación congelada ---
    # Estos SÍ evolucionan legítimamente con el tiempo (alguien termina una
    # maestría), así que un informe del cierre de 2024 debe mostrar la formación
    # que esa persona tenía en 2024, no la de hoy. Por eso se congelan, a
    # diferencia de los datos de contacto (ver `aspirante_vivo` más abajo).
    # Mismos anchos que los campos de `Aspirante` de los que se copian: si allí
    # se añade un código más largo, aquí no se trunca en silencio.
    nivel_educ = models.CharField(max_length=50, blank=True)
    especialidad_nombre = models.CharField(max_length=150, blank=True)
    grado_cientifico = models.CharField(max_length=50, blank=True)
    titulo_oro = models.BooleanField(default=False)
    # La FECHA se congela, no la edad: guardar "34 años" obligaría a decidir de
    # antemano si el informe habla de la edad de entonces o la de hoy. Con la
    # fecha se pueden calcular ambas.
    fecha_nacimiento = models.DateField(null=True, blank=True)

    # Única relación viva de toda la fotografía, y deliberada.
    #
    # El módulo evita las FK a datos vivos porque un cargo renombrado no debe
    # mover el informe de agosto (ver la cabecera de este archivo). Pero los
    # datos de contacto y ubicación de una persona (dirección, teléfonos,
    # tallas, provincia, municipio, raza, serie del carné) no son historia: no
    # cambian con el tiempo, y cuando cambian es porque estaban mal cargados.
    # Congelarlos perpetuaría el error en cada cierre ya tomado; leerlos en vivo
    # hace que corregirlos hoy arregle también los informes de años anteriores.
    #
    # `SET_NULL` y no CASCADE: si se borra a la persona, el cierre debe
    # sobrevivir — es un documento histórico. Esos campos quedarán vacíos, que
    # es la degradación correcta. `aspirante_id_original` se conserva aparte
    # como rastro, y sigue sin usarse para JOINs.
    aspirante_vivo = models.ForeignKey(
        'bolsa.Aspirante',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name='Trabajador (datos actuales)',
    )

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
    # Nulos, como en el contrato: vacío no es lo mismo que 0. Los cierres
    # tomados antes de existir estos campos los tienen vacíos.
    mision_dias = models.PositiveIntegerField(null=True, blank=True)
    mision_importe = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    fecha_alta = models.DateField(null=True, blank=True)
    duracion = models.IntegerField(null=True, blank=True)
    salario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # --- Resto del contrato, congelado ---
    # Todo esto existe para que el informe histórico pueda ofrecer las MISMAS
    # columnas que el informe en tiempo real. Sin ello, elegir un mes pasado
    # dejaba sin respuesta a la mitad de los campos que el usuario puede marcar.
    # Lo que no se puede recuperar hacia atrás son los cierres ya declarados
    # antes de añadir estas columnas: ahí saldrán vacías.
    reg_militar = models.CharField(max_length=3, blank=True)
    profesional = models.BooleanField(default=False)
    jubilado_recontratado = models.BooleanField(default=False)
    fecha_alta_entidad = models.DateField(null=True, blank=True)
    # La Calificación Formal se guardaba a medias: su número de resolución sí, y
    # el sí/no que dice si la tiene, no. Con solo la resolución, un mes pasado
    # no podía responder «cuántos tienen calificación formal», que es justo la
    # pregunta que se hace. Los cierres declarados antes de esta columna la
    # tendrán en falso, como el resto de columnas añadidas después.
    c_formal = models.BooleanField(default=False)
    funcionario_res = models.CharField(max_length=50, blank=True)
    designado_res = models.CharField(max_length=50, blank=True)
    c_formal_res = models.CharField(max_length=50, blank=True)
    fecha_vence_lic = models.DateField(null=True, blank=True)
    fecha_vence_recal = models.DateField(null=True, blank=True)
    fecha_vence_seg = models.DateField(null=True, blank=True)
    rol_tipo = models.CharField(max_length=50, blank=True)
    tridente_tipo = models.CharField(max_length=50, blank=True)
    tipo_salario = models.CharField(max_length=3, blank=True)
    # `Decimal(10, 2)` y no `Integer`: estos cuatro campos copian los del
    # contrato (`captura.py`), y allí `cnci` e `instructor` SIEMPRE fueron
    # decimales. Al guardarlos en una columna entera, Django truncaba —un CNCI
    # de 12,50 quedaba congelado como 12— sin lanzar ningún error, así que la
    # fotografía de cierre no coincidía con el contrato del que salió.
    #
    # La migración amplía la columna, pero NO recupera los centavos de los
    # cierres ya declarados: ese dato se perdió al guardarlos y el contrato vivo
    # ya puede haber cambiado, así que rellenarlo desde él metería en la
    # fotografía de un mes un importe de otro. Los cierres nuevos sí salen bien.
    maestria = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    doctorado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cnci = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    instructor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

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
        """Clase de la insignia de estado. La decide el modelo para no repetir
        el mismo `{% if %}` en cada plantilla que muestre el estado.

        Son las clases `inf-estado--*` de `static/css/informes-rrhh.css`, la
        paleta de los Informes de RRHH. Antes devolvía los `bg-label-*` de
        Vuexy, que son de otra paleta: en la misma pantalla convivían una tabla
        de Informes y unas insignias del tema, y el verde de una no era el verde
        de la otra."""
        return {
            EstadoUnidad.ACTUALIZADA: 'inf-estado inf-estado--ok',
            EstadoUnidad.PENDIENTE: 'inf-estado inf-estado--aviso',
            EstadoUnidad.DESACTUALIZADA: 'inf-estado inf-estado--critico',
        }.get(self.estado, 'inf-estado inf-estado--neutro')

    @property
    def color_punto(self):
        """Variante sólida, para el indicador del Gestor de Plantilla."""
        return {
            EstadoUnidad.ACTUALIZADA: 'bg-success',
            EstadoUnidad.PENDIENTE: 'bg-warning',
            EstadoUnidad.DESACTUALIZADA: 'bg-danger',
        }.get(self.estado, 'bg-secondary')
