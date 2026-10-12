from decimal import Decimal
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from auditoria.models import Base
from nomencladores.models import NProvincia

# Create your models here.
class Configuracion(Base):

    # Frecuencia con la que la entidad paga el salario. Se sigue guardando en
    # DÍAS (no como booleano) porque el valor numérico es el que consume el
    # asistente de exportar contrato para marcar las casillas «Quincenal» /
    # «Mensual» de la plantilla Word (ver contratos/views.py). El dominio queda
    # cerrado a estas dos opciones; en la interfaz se muestra como un toggle.
    PERIODO_QUINCENAL = 15
    PERIODO_MENSUAL = 30
    PERIODO_PAGO_CHOICES = [
        (PERIODO_QUINCENAL, 'Quincenal'),
        (PERIODO_MENSUAL, 'Mensual'),
    ]

    #?GENERALES
    nombre_empresa = models.CharField(max_length=100)
    org_superior = models.CharField(max_length=50, blank=True, null=True)
    reup = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        verbose_name="REUP",
        validators=[RegexValidator(
            regex=r'^[0-9-]*$',
            message='El REUP solo puede contener números y guiones (-).'
        )]
    )
    unidad_presup = models.BooleanField(default=False)
    rama = models.CharField(max_length=50, blank=True, null=True)
    moneda_local = models.CharField(max_length=10, default='CUP')
    # El validador de mínimo ya no hace falta: `choices` cierra el dominio a 15 o 30.
    periodo = models.PositiveIntegerField(
        default=PERIODO_QUINCENAL,
        choices=PERIODO_PAGO_CHOICES,
        null=False,
        blank=False,
        verbose_name="Período de Pago",
    )
    fondo_tiempo_calc_tarif = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('190.6'), null=False, blank=False)
    porcentaje_horas_extras = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.25'), null=False, blank=False, verbose_name="Porcentaje Horas Extras")
    correo = models.EmailField(null=True, blank=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    direccion = models.TextField(max_length=200, blank=True, null=True)
    logo = models.ImageField(upload_to='img/empr/', blank=True, null=True)
    
    provincia_entidad = models.ForeignKey(
        NProvincia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Provincia de la Entidad"
    )

    #?MANTENIMIENTO
    # Interruptor global, independiente de is_active/is_staff/is_superuser/es_admin.
    # No usar para nada más: solo bloquea el acceso de usuarios normales (ver
    # usuarios.middleware.ControlAccesoMiddleware y CustomAuthenticationForm).
    modo_mantenimiento = models.BooleanField(default=False, verbose_name="Modo de mantenimiento")

    #?AUDITORÍA
    # Cuánto se conserva el historial de Auditoría. Apagado (el valor inicial)
    # significa «Nunca»: no se borra nada. Encendido, al abrir la pantalla de
    # Auditoría se eliminan los eventos más antiguos que `auditoria_anios_conservar`
    # (ver `auditoria/limpieza.py`). El mínimo de 2 años lo decidió RRHH.
    auditoria_borrar_antigua = models.BooleanField(
        default=False, verbose_name="Borrar la auditoría antigua")
    auditoria_anios_conservar = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(2), MaxValueValidator(99)],
        verbose_name="Años de auditoría a conservar")

    class Meta:
        verbose_name = ("Configuracion")
        verbose_name_plural = ("Configuraciones")

    def __str__(self):
        return f"Configuracion: {self.nombre_empresa}"
    
    def save(self, *args, **kwargs):
        if not self.pk and Configuracion.objects.exists():
            raise ValueError('Ya existe una configuracion')
        super().save(*args, **kwargs)

    