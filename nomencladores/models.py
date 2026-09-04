import re
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
        # `NRol` ya no tiene `es_cuadro` (se movió a `NCargo.es_cuadro`, basado en
        # `cat_ocupacional`). Una fila de escala de Cuadro se reconoce por tener `rol`
        # pero NO `tridente`: así es como `calcular_salario()` la guarda y la busca
        # (ver `contratos/salarios.py`) — un Cuadro cobra sin tridente.
        if self.rol and self.tridente:
            return f"{self.grupo_escala} - {self.rol} - {self.tridente}: ${self.monto}"
        elif self.rol:
            return f"{self.grupo_escala} - {self.rol} (CUADRO): ${self.monto}"
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


# ==========================================================================
# COLOR DE CADA CATEGORÍA OCUPACIONAL
# ==========================================================================
# Fuente única del color con el que se pinta cada categoría en TODA la
# aplicación: los gráficos del Dashboard y de los informes, las insignias de las
# tablas y los desgloses. Antes cada pantalla elegía los suyos —y en Contratos
# Determinados se asignaban por orden de tamaño, así que la misma categoría
# cambiaba de color según los datos.
#
# Vive aquí, al lado de los códigos que colorea, para que añadir una categoría
# nueva obligue a decidir su color en el mismo sitio.
#
# LA PALETA ES FRÍA A PROPÓSITO. En los informes el naranja significa «falta»
# (plazas vacantes) y el rojo «crítico» (contratos por vencer). Si una categoría
# fuera naranja, una barra naranja dejaría de querer decir algo. Los cinco tonos
# tienen además claridades distintas, así que se distinguen impresos en blanco y
# negro.
#
# Y NINGUNO PUEDE SER CASI NEGRO. Las tarjetas de gráficos del Registro Diario y
# el resumen de Contratos Determinados tienen fondo oscuro: un tono muy oscuro
# desaparece contra ellas. El azul acero de Cuadros es el más oscuro de los
# cinco —sigue leyéndose como «lo alto de la jerarquía»— pero se ve en los dos
# fondos.
#
# Cuadro Directivo y Cuadro Ejecutivo comparten color: la aplicación los agrupa
# como «Cuadros» en todas partes.
COLORES_CAT_OCUPACIONAL = {
    'OPE': '#0ea5e9',   # Obreros — cielo
    'TEC': '#14b8a6',   # Técnicos — turquesa
    'ADM': '#6366f1',   # Administrativos — índigo
    'SER': '#a855f7',   # Servicios — púrpura
    'CDI': '#0369a1',   # Cuadro Directivo — azul acero
    'CEJ': '#0369a1',   # Cuadro Ejecutivo — azul acero (mismo que Directivo)
}

#: Color de lo que no tiene categoría, o la tiene sin reconocer.
COLOR_CAT_DESCONOCIDA = '#94a3b8'


def color_de_categoria(codigo):
    """Color de una categoría ocupacional por su código ('TEC', 'OPE'...).

    Devuelve el gris neutro si el código no existe: un dato incompleto no puede
    dejar una barra sin pintar ni reventar un gráfico.
    """
    return COLORES_CAT_OCUPACIONAL.get(codigo or '', COLOR_CAT_DESCONOCIDA)


# --------------------------------------------------------------------------
# SEXO: SIGLA Y COLOR, GLOBALES
# --------------------------------------------------------------------------
# Igual que las categorías ocupacionales: un color por valor, decidido en un
# solo sitio y usado por la pantalla, los gráficos, el Word, el PDF y el Excel.
#
# Antes había dos criterios distintos: el Dashboard pintaba a las mujeres de
# rojo y a los hombres de cian, e Informe Inteligente usaba rosa para el
# femenino y nada para el masculino. El rojo, además, significa «crítico» en
# todos los informes: no podía significar también «mujer».
#
# El cian del masculino es el que ya usaba la barra de Equilibrio de Género.
# Queda cerca del cielo de los Obreros, así que en una tabla con las dos
# columnas conviene no ampliar ninguno de los dos.
COLORES_SEXO = {
    'F': '#db2777',   # Femenino — rosa
    'M': '#03c3ec',   # Masculino — cian
}

COLOR_SEXO_DESCONOCIDO = '#94a3b8'


def color_de_sexo(codigo):
    """Color del sexo por su código ('F' o 'M'), o gris si no viene."""
    return COLORES_SEXO.get((codigo or '').upper(), COLOR_SEXO_DESCONOCIDO)


# --------------------------------------------------------------------------
# NIVEL EDUCACIONAL: LA SIGLA QUE SE MUESTRA
# --------------------------------------------------------------------------
# La base guarda unos códigos y la aplicación enseña OTROS. No es un descuido:
# los códigos guardados vienen de antiguo y renombrarlos exigiría una migración
# de datos; las siglas que se muestran son las que usa la empresa.
#
# La diferencia entre las dos ramas de Medio Superior —Técnico Medio y Doce
# Grado— tiene que verse: son el mismo nivel por caminos distintos, y en un
# informe de plantilla no da igual cuál de los dos.
SIGLAS_NIVEL_EDUCACIONAL = {
    'SA': 'SA',        # Sin Acreditar
    'PR': 'PR',        # Primaria
    'NG': 'NM',        # Nivel Medio  (el código guardado es NG, de antiguo)
    'OC': 'OC',        # Obrero Calificado
    'TM': 'MS(TM)',    # Medio Superior — Técnico Medio
    'MS': 'MS(DG)',    # Medio Superior — Doce Grado
    'NS': 'NS',        # Nivel Superior
}

#: Lo que significa cada sigla, para la leyenda de los documentos exportados.
LEYENDA_NIVEL_EDUCACIONAL = (
    'SA: Sin Acreditar · PR: Primaria · NM: Nivel Medio · '
    'OC: Obrero Calificado · MS(TM): Medio Superior Técnico Medio · '
    'MS(DG): Medio Superior Doce Grado · NS: Nivel Superior'
)


def sigla_de_nivel_educacional(codigo):
    """La sigla que se muestra, a partir del código guardado.

    Un código que no esté en la tabla se devuelve tal cual: es preferible
    enseñar algo raro que un hueco, porque el hueco no se puede investigar.
    """
    codigo = (codigo or '').strip()
    return SIGLAS_NIVEL_EDUCACIONAL.get(codigo, codigo)


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
# --------------------------------------------------------------------------
# NOMBRE Y SIGLAS DEL TERRITORIO
# --------------------------------------------------------------------------
# El nombre y las siglas son DOS columnas distintas, y así se guardan. Aun así
# apareció un municipio llamado «Florida      Flo»: alguien escribió las siglas
# dentro de la casilla del nombre y dejó la de siglas vacía. No entró por la
# pantalla —su modal ya valida—, sino por una vía que el JavaScript no vigila:
# el admin de Django, un script o la carga inicial de datos.
#
# Por eso la defensa vive AQUÍ, en el modelo: es el único punto por el que
# pasan todas esas vías.

RE_SIGLAS = re.compile(r'^[A-ZÁÉÍÓÚÑ]{3}$')


def _normalizar_nombre(nombre):
    """Recorta los extremos y colapsa los espacios repetidos.

    «Florida      Flo» seguiría estando mal después de esto —quedaría
    «Florida Flo»—, pero los seis espacios seguidos son la señal que delata el
    problema, y `_validar_territorio` la usa para rechazarlo.
    """
    return ' '.join((nombre or '').split())


def _validar_territorio(instancia):
    """Reglas comunes a Provincia y Municipio. Devuelve los errores por campo."""
    errores = {}

    crudo = instancia.nombre or ''
    if '  ' in crudo.strip():
        errores['nombre'] = (
            'El nombre no puede llevar espacios repetidos. Si intentaba '
            'escribir las siglas, van en su propia casilla.')

    if instancia.siglas and not RE_SIGLAS.match(instancia.siglas.strip().upper()):
        errores['siglas'] = (
            'Las siglas son exactamente tres letras, sin números ni espacios.')

    return errores


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

    def clean(self):
        super().clean()
        errores = _validar_territorio(self)
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        # La normalización va en `save` y no solo en `clean` porque `clean` no
        # se ejecuta al guardar desde un script o una importación, que es por
        # donde entró el dato roto que motivó todo esto.
        self.nombre = _normalizar_nombre(self.nombre)
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

    def clean(self):
        super().clean()
        errores = _validar_territorio(self)
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        # Ver la nota en `NProvincia.save`: la normalización va aquí para que
        # también alcance a los scripts y a las importaciones.
        self.nombre = _normalizar_nombre(self.nombre)
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
# `NHorario` y `NJornada` se eliminaron: sus tarjetas se habían retirado del
# acordeón «Tiempo de Trabajo» hacía tiempo, ninguna plantilla las usaba, las
# dos tablas estaban vacías y ningún contrato tenía jornada asignada. El tiempo
# de trabajo se gestiona ahora desde Pre-Nómina → Calendario.

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

# ---------------------------------------------------------------------------
# IMPORTES DEL CONTRATO
# ---------------------------------------------------------------------------
#
# Los cuatro importes de `contratos.CAlta` —maestría, doctorado, instructor y
# CNCI— se escribían a mano en cada contrato, uno por uno. Eso los dejaba sin
# ninguna fuente común: dos trabajadores con el mismo grado científico podían
# acabar con importes distintos sin que nada avisara, y actualizar la cuantía
# obligaba a abrir todos los contratos.
#
# Aquí viven ahora esas cuantías. El contrato SIGUE guardando el número: no es
# una redundancia, es lo que protege el pasado. Si mañana cambia el importe del
# nomenclador, los contratos y las nóminas ya emitidas conservan el suyo, y la
# regla CTR-019 de Subsanación es la que reclama las diferencias para que sea
# una persona quien decida actualizarlas.


class NImporteGradoCientifico(Base):
    """El importe único de Maestría y el de Doctorado.

    Un registro por grado, y solo puede haber uno de cada: la clave es la misma
    (`MC`/`DC`) que usa `bolsa.Aspirante.grado_cientifico`, así que el
    formulario de contrato resuelve el importe con una búsqueda directa, sin
    tablas de equivalencia que se puedan desincronizar.

    Un aspirante es máster, doctor o ninguna de las dos cosas —nunca las dos a
    la vez— porque `grado_cientifico` es un único campo con opciones, no dos
    casillas independientes. Esa regla ya la garantiza el modelo del aspirante y
    no hace falta repetirla aquí.
    """

    GRADOS = [
        ('MC', 'Maestría'),
        ('DC', 'Doctorado'),
    ]

    grado = models.CharField(
        max_length=2, choices=GRADOS, unique=True,
        verbose_name='Grado científico')
    importe = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Importe')

    class Meta:
        verbose_name = 'Importe por grado científico'
        verbose_name_plural = 'Importes por grado científico'
        ordering = ['grado']

    def __str__(self):
        return f'{self.get_grado_display()}: {self.importe}'


class NPagoAdicional(Base):
    """Los pagos de Instructor y de CNCI: varios registros de cada uno.

    Van en una sola tabla con un campo que los distingue, y no en dos modelos,
    por el mismo motivo que `NImporteGradoCientifico` sirve a Maestría y a
    Doctorado: son la misma forma de dato (una descripción y un importe) con el
    mismo mantenimiento, y dos tablas significarían duplicar el CRUD entero para
    no ganar nada. En pantalla siguen siendo dos tarjetas separadas.
    """

    INSTRUCTOR = 'INS'
    CNCI = 'CNC'
    TIPOS = [
        (INSTRUCTOR, 'Instructor'),
        (CNCI, 'CNCI'),
    ]

    tipo = models.CharField(max_length=3, choices=TIPOS, verbose_name='Tipo de pago')
    descripcion = models.CharField(max_length=100, verbose_name='Descripción')
    importe = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Importe')

    class Meta:
        verbose_name = 'Pago adicional'
        verbose_name_plural = 'Pagos adicionales'
        ordering = ['tipo', 'descripcion']
        constraints = [
            # Dos entradas con la misma descripción dentro del mismo tipo serían
            # indistinguibles en el desplegable del contrato.
            models.UniqueConstraint(
                fields=['tipo', 'descripcion'],
                name='unique_pago_adicional_por_tipo',
            )
        ]

    def __str__(self):
        return f'{self.descripcion} ({self.importe})'
