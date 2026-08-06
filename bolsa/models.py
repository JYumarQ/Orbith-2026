import logging

from django.db import models
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa
from nomencladores.models import NTridente, NSalario, NJornada, NEspecialidad, NMunicipio, NProvincia
from django.core.validators import MinValueValidator
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
# CONTACTO
class Contacto(Base):

    doc_identidad = models.CharField(max_length=11, unique=True, verbose_name="Carnet de Identidad")
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
    ], blank=True, null= True)

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
        # Usamos los objetos directos para evitar falsos positivos de Pylance con los campos _id
        if self.municipio and self.provincia:
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

    def save(self, *args, **kwargs):
        self.fecha_nacimiento = self._calcular_fecha_nacimiento(self.doc_identidad)
        self.full_clean()  # asegura que se ejecute clean()
        super().save(*args, **kwargs)

        try:
            from notificaciones.avisos import avisar_hallazgos_en_caliente
            avisar_hallazgos_en_caliente(self)
        except Exception:
            logger.exception(
                "No se pudieron evaluar/notificar las alertas de integridad "
                "del trabajador %s.", self.pk)

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