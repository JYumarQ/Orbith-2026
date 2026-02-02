from django.db import models
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa
from nomencladores.models import NTridente, NSalario, NJornada, NEspecialidad, NMunicipio, NProvincia
from django.core.validators import MinValueValidator
from datetime import date
from auditoria.models import Base
from django.core.exceptions import ValidationError
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
    ], blank=True, null= True) 
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
    especialidad = models.ForeignKey(NEspecialidad,null=True, blank=True, on_delete=models.RESTRICT)
    habilidades = models.TextField(null=True, blank=True)
    contratado = models.BooleanField(null=True, blank=True, default=False)

    
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
        
    def save(self, *args, **kwargs):
        self.full_clean()  # asegura que se ejecute clean()
        super().save(*args, **kwargs)

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
        ci = (self.doc_identidad or "").strip()
        # Posibilidad de exigir 11 dígitos exactos:
        # if len(ci) != 11 or not ci.isdigit(): return None
        if len(ci) < 6 or not ci[:6].isdigit():
            return None  # edad desconocida

        yy = int(ci[:2]); mm = int(ci[2:4]); dd = int(ci[4:6])
        hoy = date.today()
        century = 2000 if yy <= hoy.year % 100 else 1900  # De 00 a 25 -> 2000..2025; 26 a 99 -> 1926..1999
        try:
            fn = date(century + yy, mm, dd)
        except ValueError:
            return None  # fecha inválida

        return hoy.year - fn.year - ((hoy.month, hoy.day) < (fn.month, fn.day))
