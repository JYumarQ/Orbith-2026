from django.core.validators import MinValueValidator
from django.db import models
from auditoria.models import Base

#?SALARIO
class NTridente(Base):
    
    tipo = models.CharField(max_length=10, blank=False, null=False)
    
    class Meta:
        verbose_name = ("NTridente")
        verbose_name_plural = ("NTridentes")

    def __str__(self):
        return f"Tridente {self.tipo}"

class NRol(Base):
    
    tipo = models.CharField(max_length=50)    

    class Meta:
        verbose_name = ("NRol")
        verbose_name_plural = ("NRoles")

    def __str__(self):
        return self.tipo

class NGrupoEscala(Base):

    nivel = models.CharField(max_length=8, unique=True)
    es_cuadro = models.BooleanField(default=False)

    class Meta:
        verbose_name = ("NGrupoEscala")
        verbose_name_plural = ("NGruposEscalas")
    
    @property
    def valor_numerico(self):
        """Convierte el nivel en número romano a un valor entero para ordenamiento"""
        roman_values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        result = 0
        prev_value = 0
        
        # Recorrer el número romano de derecha a izquierda
        for char in reversed(self.nivel.upper()):
            if char not in roman_values:
                return 999  # Valor por defecto para caracteres no romanos
                
            current_value = roman_values[char]
            # Si el valor actual es mayor o igual al anterior, sumamos
            if current_value >= prev_value:
                result += current_value
            # Si es menor, restamos (como en IV = 5-1 = 4)
            else:
                result -= current_value
            
            prev_value = current_value
            
        return result

    def __str__(self):
        return self.nivel
    
class NSalario(Base):

    grupo_escala = models.ForeignKey(NGrupoEscala, on_delete=models.CASCADE)
    rol = models.ForeignKey(NRol, null=True, blank=True, on_delete=models.CASCADE)
    tridente = models.ForeignKey(NTridente, null=True, blank=True, on_delete=models.CASCADE)
    monto = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = ("NSalario")
        verbose_name_plural = ("NSalarios")
        unique_together = ('grupo_escala', 'rol', 'tridente')

    def __str__(self):
        if self.rol and self.tridente:
            return f"{self.grupo_escala} - {self.rol} - Tridente {self.tridente}: ${self.monto}"
        else:
            return f"{self.grupo_escala} (CUADRO): ${self.monto}"

class NCargo(Base):

    descripcion = models.CharField(max_length=150)
    cat_ocupacional = models.CharField(max_length=20, choices=[
        ('TEC', 'Técnico'),
        ('ADM', 'Administrativo'),
        ('SER', 'Servicio'),
        ('OPE', 'Operario'),
        ('CDI', 'Cuadro Directivo'),
        ('CEJ', 'Cuadro Ejecutivo')
    ])
    grupo_escala = models.ForeignKey(NGrupoEscala, on_delete=models.RESTRICT)
    salario_basico = models.DecimalField(max_digits=8, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = ("NCargo")
        verbose_name_plural = ("NCargos")

    def __str__(self):
        return self.descripcion

class NCondicionLaboralAnormal(models.Model):
    nombre = models.CharField(max_length=10, unique=True)
    descripcion = models.TextField(max_length=200, blank=True, null=True)
    tarifa_hora = models.DecimalField(validators=[MinValueValidator(0)], max_digits=7, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Condición Laboral Anormal"
        verbose_name_plural = "Condiciones Laborales Anormales"

    def __str__(self):
        return f"{self.nombre} ({self.tarifa_hora} CUP/h)"


#?PARAMETROS GENERALES
class NProvincia(Base):
    
    nombre = models.CharField(max_length=50, unique=True)
    
    class Meta:
        verbose_name = ("NProvincia")
        verbose_name_plural = ("NProvincias")

    def __str__(self):
        return self.nombre

class NMunicipio(Base):
    
    nombre = models.CharField(max_length=50)
    provincia = models.ForeignKey(NProvincia, on_delete=models.RESTRICT)    

    class Meta:
        verbose_name = ("NMunicipio")
        verbose_name_plural = ("NMunicipios")
        unique_together = ('nombre', 'provincia')

    def __str__(self):
        return self.nombre
    
    
#?CAUSAS ALTA/BAJA
class NCausaAltaBaja(Base):
    
    descripcion = models.CharField(max_length=50, blank=False, null=False)
    alta = models.BooleanField(default=False, blank=False, null=False)

    class Meta:
        verbose_name = ("NCausa Alta/Baja")
        verbose_name_plural = ("NCausas de Alta/Baja")

    def __str__(self):
        return self.descripcion


#?TIEMPO DE TRABAJO
class NHorario(Base):

    descripcion = models.CharField(max_length=50)
    hora_inicio = models.TimeField(blank=True, null=True)
    hora_fin = models.TimeField(blank=True, null=True)

    class Meta:
        verbose_name = ("NHorario")
        verbose_name_plural = ("NHorarios")

    def __str__(self):
        return self.descripcion

class NJornada(Base):

    tipo = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=50, blank=False, null=False)
    horario = models.ForeignKey(NHorario, blank=True, null=True, on_delete=models.RESTRICT)
    
    class Meta:
        verbose_name = ("NJornada")
        verbose_name_plural = ("NJornadas")

    def __str__(self):
        return self.tipo

#?PROFESIONES
class NEspecialidad(models.Model):

    nombre = models.CharField( max_length=50, unique=True)
    educ_superior = models.BooleanField(verbose_name='Educ. Superior', default=False)

    class Meta:
        verbose_name = ("NEspecialidad")
        verbose_name_plural = ("NEspecialidad")

    def __str__(self):
        return self.nombre



