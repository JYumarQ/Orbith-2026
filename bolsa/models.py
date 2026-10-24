import logging

from django.db import models
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa
from nomencladores.models import NEspecialidad, NMunicipio, NProvincia
from django.core.validators import MinValueValidator, RegexValidator
from datetime import date, timedelta
from auditoria.models import Base
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Edad mínima de pre-jubilación y edad máxima de la ventana, por sexo. Mismo criterio
# que ya usaba `dashboard/views.py::DashboardView` de forma inline (58-60 F, 63-65 M);
# se centraliza aquí para que `Aspirante.dias_hasta_jubilacion` y el dashboard no
# puedan divergir. Fuera de estos dos sexos (o de la ventana) la property devuelve
# `None`: no es un caso de error, simplemente no aplica.
EDAD_MINIMA_JUBILACION = {'F': 58, 'M': 63}
EDAD_MAXIMA_VENTANA_JUBILACION = {'F': 60, 'M': 65}

# Formato de la serie del carnet de identidad: exactamente 9 caracteres alfanuméricos
# en mayúsculas. Vive aquí (y no en el formulario) para que la regla de Subsanación
# ASP-009 y el propio modelo compartan un único criterio.
PATRON_SERIE_CI = r'^[A-Z0-9]{9}$'
SERIE_CI_VALIDATOR = RegexValidator(
    regex=PATRON_SERIE_CI,
    message='La serie del carnet debe tener exactamente 9 caracteres alfanuméricos (A-Z, 0-9).')


# CONTACTO
class Contacto(Base):

    doc_identidad = models.CharField(max_length=11, unique=True, verbose_name="Carnet de Identidad")
    # Serie impresa en el carnet de identidad. Opcional (muchos registros antiguos no
    # la tienen y el dato puede llegar después del alta), pero única cuando se rellena:
    # identifica un único ejemplar del documento. Por eso el formulario normaliza el
    # vacío a NULL — PostgreSQL permite múltiples NULL en una columna UNIQUE, pero no
    # múltiples cadenas vacías. Que falte no bloquea el guardado: lo reporta
    # Subsanación (ASP-008), igual que la dirección o el nivel educativo.
    serie_ci = models.CharField(
        max_length=9, unique=True, null=True, blank=True,
        validators=[SERIE_CI_VALIDATOR],
        verbose_name="Serie del Carnet",
        help_text="9 caracteres alfanuméricos en mayúsculas, tal como aparecen en el carnet.")
    nombre = models.CharField(max_length=20, blank=False, null=False)
    papellido = models.CharField(max_length=30, null=False, blank=False)
    sapellido = models.CharField(max_length=30, null=False, blank=False)
    movil_personal = models.CharField(max_length=15, blank=True, null= True)
    fijo_personal = models.CharField(max_length=10, blank= True, null=True)
    direccion = models.TextField(null=True, blank=True)
    municipio = models.ForeignKey(NMunicipio, on_delete=models.RESTRICT)
    provincia = models.ForeignKey(NProvincia, on_delete=models.RESTRICT)
    codigo_postal = models.CharField(max_length=10, null= True, blank=True)
    nota_adicional = models.TextField(null=True, blank=True)


    class Meta:
        abstract = True

class Aspirante(Contacto):

    ESTADOS = [
        ('ASPIRANTE', 'Aspirante'),
        ('ACTIVO', 'Activo'),
        ('BAJA', 'Baja'),
    ]

    unidad_organizativa = models.ForeignKey(
        UnidadOrganizativa,
        on_delete=models.RESTRICT,
        null=True, blank=True
    )

    estado = models.CharField(max_length=20, choices=ESTADOS, default='ASPIRANTE')

    sexo = models.CharField(max_length=1, choices=[
        ('M', 'Masculino'),
        ('F', 'Femenino')
    ], blank=False, null=False)
    
    raza = models.CharField(max_length=50, choices= [
        ('BL', 'Blanca'),
        ('NE', 'Negra'),
        ('ME', 'Mestiza')
    ], blank=False, null=False)
    grado_cientifico = models.CharField(max_length=50, choices=[
        ('MC', 'Master'),
        ('DC', 'Doctor')
    ], blank=True, null= True)
    nivel_educ = models.CharField(max_length=50, choices=[
        ('SA', 'Sin Acreditar'),
        ('PR', 'Primaria'),
        ('NG', 'Medio'),
        ('OC','Obrero Calificado'),
        ('TM','Medio Superior (TM)'),
        ('MS','Medio Superior (DG)'),
        ('NS','Nivel Superior'),
    ],
        # Obligatorio: `blank=False` hace que ni el formulario ni `full_clean()`
        # acepten dejarlo sin elegir, y `null=False` cierra la puerta a que un
        # script o una importación vuelvan a dejarlo vacío en la base de datos.
        #
        # Los trabajadores YA registrados sin nivel no se tocan ni bloquean nada:
        # la migración pasa sus `NULL` a cadena vacía para poder poner la columna
        # NOT NULL, y la regla ASP-007 de Subsanación (ahora Crítica) los reclama
        # uno a uno. El `default=''` existe solo por eso; no es un valor válido
        # para un alta nueva.
        blank=False, null=False, default='',
        verbose_name='Nivel Educacional')

    titulo_oro = models.BooleanField(default=False, verbose_name="Título de Oro")

    fecha_nacimiento = models.DateField(
        null=True, blank=True, editable=False,
        verbose_name="Fecha de Nacimiento",
        help_text="Calculada automáticamente desde el Carnet de Identidad."
    )

    especialidad = models.ForeignKey(NEspecialidad,null=True, blank=True, on_delete=models.RESTRICT)

    #?TALLAS
    tpantalon = models.CharField(max_length=5, null=True, blank=True)
    tcamisa = models.CharField(max_length=5, null=True, blank=True)
    tzapatos = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = ("Aspirante")
        verbose_name_plural = ("Aspirantes")

    def clean(self):
        super().clean()
        # Se comprueban los `_id`, NO los objetos: acceder a `self.municipio` cuando
        # el campo está sin asignar lanza `RelatedObjectDoesNotExist`, y eso hacía
        # reventar con un error 500 cualquier envío del formulario al que le faltara
        # el municipio, en vez de mostrar el error de validación normal.
        if self.municipio_id and self.provincia_id:
            if self.municipio.provincia != self.provincia:
                raise ValidationError({'municipio': 'El municipio no pertenece a la provincia seleccionada.'})

    @staticmethod
    def _calcular_fecha_nacimiento(doc_identidad):
        """
        Extrae la fecha de nacimiento del Carnet de Identidad cubano.
        El 7º dígito indica el siglo de nacimiento sin ambigüedad:
          0-5 -> 1900-1999
          6-8 -> 2000-2099
        (El carné siempre es cubano; no se contempla el caso 9=extranjero).
        """
        ci = (doc_identidad or "").strip()
        if len(ci) < 7 or not ci[:7].isdigit():
            return None

        yy, mm, dd = int(ci[0:2]), int(ci[2:4]), int(ci[4:6])
        digito_siglo = int(ci[6])

        century = 1900 if digito_siglo <= 5 else 2000

        try:
            return date(century + yy, mm, dd)
        except ValueError:
            return None

    @staticmethod
    def _normalizar_serie_ci(serie):
        """Deja la serie en mayúsculas y sin espacios, o `None` si viene vacía.

        El `None` no es cosmético: `serie_ci` es UNIQUE, y PostgreSQL permite tantos
        NULL como haga falta pero solo una cadena vacía. Si dos aspirantes sin serie
        se guardaran con `''`, el segundo reventaría con IntegrityError. Vive en el
        modelo (y no en el formulario) para que valga también desde el admin, un
        script o una importación.
        """
        serie = (serie or '').strip().upper()
        return serie or None

    def save(self, *args, **kwargs):
        self.fecha_nacimiento = self._calcular_fecha_nacimiento(self.doc_identidad)
        self.serie_ci = self._normalizar_serie_ci(self.serie_ci)
        # `nivel_educ` es obligatorio, pero no se le puede exigir a los trabajadores
        # que YA estaban registrados sin él: procesos internos como contratar
        # (`Contrato.actualizar_aspirante`) o dar de baja hacen `aspirante.save()`
        # solo para cambiar el estado, y una validación aquí abortaría la
        # contratación de un trabajador heredado por un dato que ese proceso ni
        # toca ni conoce. Quien sí lo exige es el formulario (`AspiranteForm`, con
        # el campo en rojo/amarillo), que es donde una persona puede completarlo, y
        # la regla ASP-007 de Subsanación, que los reclama uno a uno.
        #
        # El alta SÍ queda bloqueada: sin `pk` no hay nada heredado que respetar.
        sin_validar = {'nivel_educ'} if (self.pk and not self.nivel_educ) else None
        self.full_clean(exclude=sin_validar)  # asegura que se ejecute clean()
        grado_anterior = (Aspirante.objects.filter(pk=self.pk)
                          .values_list('grado_cientifico', flat=True).first()) if self.pk else None
        super().save(*args, **kwargs)

        # El grado científico decide los importes de Maestría y Doctorado de sus
        # contratos (que ya no los guardan): cambiarlo es un cambio externo para
        # su histórico (decisión de RRHH del 23-10-2026).
        if self.pk and (grado_anterior or None) != (self.grado_cientifico or None):
            self._registrar_cambio_de_grado(grado_anterior)

        try:
            from notificaciones.avisos import avisar_hallazgos_en_caliente
            avisar_hallazgos_en_caliente(self)
        except Exception:
            logger.exception(
                "No se pudieron evaluar/notificar las alertas de integridad "
                "del trabajador %s.", self.pk)

        # Revisión por registro (Fase 2): la ficha y sus contratos. Nunca lanza.
        from subsanacion.por_registro import revisar_registros
        revisar_registros(aspirantes=[self.pk],
                          contratos=list(self.calta_contratos.values_list('pk', flat=True)))

    def _registrar_cambio_de_grado(self, grado_anterior):
        from contratos.cambios_externos import Afectado, registrar_cambio
        from contratos.models import CambioExterno

        nombres = dict(self._meta.get_field('grado_cientifico').choices)
        antes = nombres.get(grado_anterior, 'sin grado científico')
        ahora = nombres.get(self.grado_cientifico, 'sin grado científico')
        afectados = []
        for contrato in self.calta_contratos.all():
            importes = (contrato.importe_maestria, contrato.importe_doctorado)
            afectados.append(Afectado(
                contrato, f'El grado científico de la ficha cambió: {antes} a {ahora}.',
                f'Grado: {antes}',
                'Grado: %s (Maestría %s, Doctorado %s)' % (ahora, *importes)))
        registrar_cambio(CambioExterno.Origen.FICHA, self, afectados)

    def __str__(self):
        return f"{self.nombre} {self.papellido} {self.sapellido or ''}".strip()

    @property
    def get_especialidad(self):
        if self.especialidad != None:
            return self.especialidad
        else:
            return '-'
    
    @property
    def get_edad(self):
        if not self.fecha_nacimiento:
            return None
        hoy = date.today()
        return hoy.year - self.fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )

    @staticmethod
    def _proximo_aniversario(fecha_base, hoy, anios):
        """`fecha_base` desplazada `anios` a partir de su propio año, buscando la
        primera ocurrencia que caiga en `hoy` o después. 29 de febrero se corre al 1 de
        marzo en años no bisiestos (mismo criterio en los dos usos de este helper)."""
        def _en_anio(year):
            try:
                return fecha_base.replace(year=year)
            except ValueError:
                return fecha_base.replace(year=year, day=28) + timedelta(days=1)

        fecha = _en_anio(fecha_base.year + anios)
        if fecha < hoy:
            fecha = _en_anio(fecha_base.year + anios + 1)
        return fecha

    @property
    def dias_hasta_cumpleanos(self):
        """Días que faltan para el próximo cumpleaños (0 si es hoy), a partir de
        `fecha_nacimiento` (ya calculada al guardar desde el carnet de identidad).
        `None` si no hay fecha de nacimiento registrada."""
        if not self.fecha_nacimiento:
            return None
        hoy = date.today()
        edad_actual = self.get_edad or 0
        proximo = self._proximo_aniversario(self.fecha_nacimiento, hoy, edad_actual)
        return (proximo - hoy).days

    @property
    def dias_hasta_jubilacion(self):
        """Días que faltan para que el trabajador alcance la edad mínima de
        pre-jubilación (58 F / 63 M) — negativo si ya la alcanzó (recordatorio
        "vencido", igual que cualquier otro vencimiento). `None` fuera de la ventana de
        pre-jubilación: sexo no contemplado, sin fecha de nacimiento, o ya superó la
        edad máxima de la ventana (60 F / 65 M) — a partir de ahí ya no es "próxima",
        es una situación ya resuelta, mismo corte que separa hoy `pre_jubilacion` de
        `recontratados` en `dashboard/views.py`.

        Extrae a esta property el criterio de edad por sexo que antes solo vivía
        duplicado dentro de `DashboardView.get_context_data()`.
        """
        edad_minima = EDAD_MINIMA_JUBILACION.get(self.sexo)
        edad_maxima = EDAD_MAXIMA_VENTANA_JUBILACION.get(self.sexo)
        if not self.fecha_nacimiento or edad_minima is None:
            return None

        edad = self.get_edad
        if edad is None or edad > edad_maxima:
            return None

        hoy = date.today()
        fecha_edad_minima = self._proximo_aniversario(
            self.fecha_nacimiento, date.min, edad_minima)
        # `_proximo_aniversario` con `hoy=date.min` siempre da la ÚNICA ocurrencia real
        # (no la "próxima desde hoy"): el cumpleaños en que cumple exactamente
        # `edad_minima`, sin importar si ya pasó.
        return (fecha_edad_minima - hoy).days