from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from auditoria.models import Base
from datetime import timedelta
from django.core.exceptions import ValidationError

#?SALARIO
class NTridente(Base):
    
    tipo = models.CharField(max_length=10, blank=False, null=False)
    
    class Meta:
        verbose_name = ("NTridente")
        verbose_name_plural = ("NTridentes")

    def __str__(self):
        return f"Tridente {self.tipo}"

# nomencladores/models.py

class NRol(Base):
    tipo = models.CharField(max_length=50)    
    # Se eliminó el campo es_cuadro de aquí

    class Meta:
        verbose_name = ("NRol")
        verbose_name_plural = ("NRoles")

    def __str__(self):
        return self.tipo

class NGrupoEscala(Base):
    nivel = models.CharField(max_length=8, unique=True)
    
    # --- NUEVOS CAMPOS ---
    es_cuadro = models.BooleanField(default=False, verbose_name="Es Cuadro")
    tiene_rol = models.BooleanField(default=True, verbose_name="Tiene Rol")
    valor_numerico_db = models.IntegerField(default=999, editable=False, verbose_name="Valor numérico (orden)")
    # Relación para seleccionar qué roles aplican a este grupo
    roles = models.ManyToManyField(
        NRol, 
        blank=True, 
        related_name="grupos_escala",
        verbose_name="Roles que aplican"
    )

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

    def save(self, *args, **kwargs):
        # Mantener el campo numérico sincronizado con el nivel romano.
        # Reutiliza la misma lógica que la property, para que nunca difieran.
        self.valor_numerico_db = self.valor_numerico
        super().save(*args, **kwargs)

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
        if self.rol and self.rol.es_cuadro:
             return f"{self.grupo_escala} - {self.rol} (CUADRO): ${self.monto}"
        elif self.rol and self.tridente:
            return f"{self.grupo_escala} - {self.rol} - {self.tridente}: ${self.monto}"
        return f"Salario {self.pk}"
        
class NTipoFamilia(Base):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Tipo de Familia")

    class Meta:
        verbose_name = "Tipo de Familia"
        verbose_name_plural = "Tipos de Familias"

    def __str__(self):
        return self.nombre

class NFamiliaCargo(Base):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    tipo_familia = models.ForeignKey(NTipoFamilia, on_delete=models.CASCADE, related_name='familias')
    class Meta:
        verbose_name = "Familia de Cargos"
        verbose_name_plural = "Familias de Cargos"
        unique_together = ('nombre', 'tipo_familia')

    def __str__(self):
        return f"{self.nombre} ({self.tipo_familia.nombre})"


class NCargo(Base):
    descripcion = models.CharField(max_length=150)
    cat_ocupacional = models.CharField(max_length=20, choices=[
        ('TEC', 'Técnico'),
        ('ADM', 'Administrativo'),
        ('SER', 'Servicio'),
        ('OPE', 'Obrero'),
        ('CDI', 'Cuadro Directivo'),
        ('CEJ', 'Cuadro Ejecutivo')
    ])

    puesto_clave = models.BooleanField(default=False, verbose_name='Puesto Clave')
    grupo_escala = models.ForeignKey(NGrupoEscala, on_delete=models.RESTRICT)

    # ¡LA MAGIA OCURRE AQUÍ! ELIMINAMOS EL FOREIGN KEY Y USAMOS MANY-TO-MANY
    familias = models.ManyToManyField(NFamiliaCargo, blank=True, related_name='cargos')
    
    salario_basico = models.DecimalField(max_digits=8, decimal_places=2)

    # Categorías ocupacionales que hacen que un cargo sea Cuadro. Es una constante y no
    # una lista escrita dentro de la property para que otros módulos puedan consultarla
    # sin repetir el criterio: Subsanación la necesita al evaluar filas obtenidas con
    # .values(), donde no hay una instancia sobre la que llamar a `es_cuadro`.
    CATEGORIAS_CUADRO = ('CDI', 'CEJ')

    @property
    def es_cuadro(self):
        """Fuente única de verdad: un cargo es Cuadro solo por su categoría ocupacional."""
        return self.cat_ocupacional in self.CATEGORIAS_CUADRO

    class Meta:
        verbose_name = ("NCargo")
        verbose_name_plural = ("NCargos")

    def __str__(self):
        return self.descripcion
    
class NNocturnidad(Base):
    codigo = models.CharField(max_length=50, unique=True, verbose_name="Código (Ej: N1)")
    hora_inicio = models.TimeField(verbose_name="Hora Inicio")
    hora_fin = models.TimeField(verbose_name="Hora Fin")

    class Meta:
        verbose_name = "Nocturnidad"
        verbose_name_plural = "Nocturnidades"

    def __str__(self):
        return f"{self.codigo} ({self.hora_inicio.strftime('%H:%M')} - {self.hora_fin.strftime('%H:%M')})"

    @property
    def horas(self):
        """Calcula las horas derivadas, soportando el cruce de medianoche (Ej: 23:00 a 07:00 = 8h)"""
        if self.hora_inicio and self.hora_fin:
            start = timedelta(hours=self.hora_inicio.hour, minutes=self.hora_inicio.minute)
            end = timedelta(hours=self.hora_fin.hour, minutes=self.hora_fin.minute)
            
            if end <= start:
                end += timedelta(days=1) # Suma 24 horas si cruza la medianoche
                
            diff = end - start
            return round(diff.total_seconds() / 3600, 2)
        return 0.0

class NCondicionLaboralAnormal(models.Model):
    nombre = models.CharField(max_length=10, unique=True)
    descripcion = models.TextField(max_length=200, blank=True, null=True)

    tarifa_hora = models.DecimalField(
        validators=[MinValueValidator(0)],
        max_digits=7,
        decimal_places=2,
        default=Decimal("0")
    )

    nocturnidad = models.OneToOneField(
        NNocturnidad,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="condicion"
    )

    class Meta:
        verbose_name = "Condición Laboral Anormal"
        verbose_name_plural = "Condiciones Laborales Anormales"

    def __str__(self):
        return f"{self.nombre} ({self.tarifa_hora} CUP/h)"

    def clean(self):
        super().clean()

        if self.nocturnidad:
            ocupante = (
                NCondicionLaboralAnormal.objects
                .filter(nocturnidad=self.nocturnidad)
                .exclude(pk=self.pk)
                .first()
            )

            if ocupante:
                raise ValidationError({
                    "nocturnidad":
                        f'La nocturnidad "{self.nocturnidad.codigo}" '
                        f'ya está asignada a "{ocupante.nombre}".'
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


#?PARAMETROS GENERALES
class NProvincia(Base):
    
    nombre = models.CharField(max_length=50, unique=True)
    siglas = models.CharField(
        max_length=3,
        null=True, blank=True,
        verbose_name="Siglas",
        help_text="Exactamente 3 letras mayúsculas"
    )
    
    class Meta:
        verbose_name = ("NProvincia")
        verbose_name_plural = ("NProvincias")

    def save(self, *args, **kwargs):
        if self.siglas:
            self.siglas = self.siglas.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre

class NMunicipio(Base):
    
    nombre = models.CharField(max_length=50)
    provincia = models.ForeignKey(NProvincia, on_delete=models.RESTRICT)    
    siglas = models.CharField(
        max_length=3,
        null=True, blank=True,
        verbose_name="Siglas",
        help_text="Exactamente 3 letras mayúsculas"
    )

    class Meta:
        verbose_name = ("NMunicipio")
        verbose_name_plural = ("NMunicipios")
        unique_together = ('nombre', 'provincia')

    def save(self, *args, **kwargs):
        if self.siglas:
            self.siglas = self.siglas.strip().upper()
        super().save(*args, **kwargs)

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


class NNivelPreparacion(Base):
    nombre = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = "Nivel de Preparación"
        verbose_name_plural = "Niveles de Preparación"

    def __str__(self):
        return self.nombre

class NTipoContrato(Base):
    descripcion = models.CharField(max_length=50, unique=True, verbose_name="Descripción")
    ocupa_plaza = models.BooleanField(default=False, verbose_name="¿Ocupa Plaza en Plantilla?")
    # NUEVO SWITCH
    requiere_motivo = models.BooleanField(default=False, verbose_name="¿Requiere Motivo?") 
    es_adiestrado = models.BooleanField(default=False, verbose_name="¿Es Adiest?")

    class Meta:
        verbose_name = "Tipo de Contrato"
        verbose_name_plural = "Tipos de Contratos"

    def __str__(self):
        return self.descripcion

# NUEVO NOMENCLADOR
class NMotivoContrato(Base):
    descripcion = models.CharField(max_length=100, verbose_name="Descripción")   # ← quitado unique=True
    tipo_contrato = models.ForeignKey(
        NTipoContrato,
        on_delete=models.RESTRICT,
        related_name="motivos",                # ← quitados null=True y blank=True
        verbose_name="Tipo de Contrato Asociado"
    )

    class Meta:
        verbose_name = "Motivo de Contrato"
        verbose_name_plural = "Motivos de Contratos"
        constraints = [
            models.UniqueConstraint(
                fields=['descripcion', 'tipo_contrato'],
                name='unique_motivo_por_tipo',
            )
        ]

    def __str__(self):
        return self.descripcion

class NTipoUnidadOrganizativa(Base):
    descripcion = models.CharField(max_length=150, unique=True, verbose_name="Tipo de Unidad")
    es_temporal = models.BooleanField(default=False, verbose_name="Es temporal")
    es_principal = models.BooleanField(default=False, verbose_name="Unidad Principal")
    es_subunidad = models.BooleanField(default=False, verbose_name="Subunidad")
    tipo_padre = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subtipos', verbose_name="Tipo Principal (Padre)")

    # Aquí guardaremos el código HEX del color (ej. #FF5733)
    color = models.CharField(max_length=20, blank=True, null=True, verbose_name="Color de Jerarquía")

    class Meta:
        verbose_name = "Tipo de Unidad Organizativa"
        verbose_name_plural = "Tipos de Unidades Organizativas"

    def __str__(self):
        return self.descripcion