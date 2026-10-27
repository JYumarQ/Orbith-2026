import re
import unicodedata
from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from auditoria.models import Base
from datetime import timedelta
from django.core.exceptions import ValidationError


# --------------------------------------------------------------------------
# COMUNES A LOS NOMENCLADORES (3.8.2, 27-10-2026)
# --------------------------------------------------------------------------

def clave_nomenclador(texto):
    """«  Flórida » → «florida»: sin mayúsculas, acentos ni espacios de más. Es la
    forma de comparar dos nombres para saber si son el mismo."""
    descompuesto = unicodedata.normalize('NFKD', ' '.join(str(texto or '').split()).lower())
    return ''.join(c for c in descompuesto if not unicodedata.combining(c))


class SinRepetidos:
    """Impide dos registros que solo se distinguen por mayúsculas, acentos o espacios.

    La comprobación vive en el programa y NO como regla de la base de datos (decisión
    del 27-10-2026): así la actualización del servidor nunca se para por repetidos
    antiguos, que la regla CFG-007 de Subsanación lista para corregirlos a mano.

    `campo_unico` es el campo que no se repite; `ambito_unico`, los campos (por su
    nombre de columna) que delimitan dónde no se repite: el municipio, dentro de su
    provincia; el motivo, dentro de su tipo de contrato.
    """
    campo_unico = None
    ambito_unico = ()

    def repetido(self):
        """El registro que ya tiene ese nombre, o None."""
        clave = clave_nomenclador(getattr(self, self.campo_unico))
        if not clave:
            return None
        otros = type(self)._default_manager.filter(
            **{campo: getattr(self, campo) for campo in self.ambito_unico})
        if self.pk:
            otros = otros.exclude(pk=self.pk)
        return next((o for o in otros if clave_nomenclador(getattr(o, self.campo_unico)) == clave), None)

    def _error_de_repetido(self):
        otro = self.repetido()
        if otro:
            return ValidationError({self.campo_unico: (
                f'Ya existe «{getattr(otro, self.campo_unico)}». No se puede repetir '
                f'(da igual mayúsculas, acentos o espacios).')})
        return None

    def clean(self):
        super().clean()
        error = self._error_de_repetido()
        if error:
            raise error

    def save(self, *args, **kwargs):
        # También al guardar, no solo en `clean()`: las vistas JSON, los importadores
        # y los scripts guardan sin validar, y por ahí entraría el repetido.
        error = self._error_de_repetido()
        if error:
            raise error
        super().save(*args, **kwargs)


class Ordenable(models.Model):
    """Orden que fija el Administrador arrastrando las filas (decisión del 27-10-2026).

    Es el orden de TODO Orbith: la tarjeta del nomenclador, los desplegables, los
    filtros y los informes, porque cada modelo lo declara en su `Meta.ordering`.
    Un registro nuevo se coloca al final de su lista (`ambito_orden`: el municipio,
    al final de los de su provincia).
    """
    orden = models.PositiveIntegerField(default=0, editable=False, db_index=True, verbose_name='Orden')

    ambito_orden = ()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.pk and not self.orden:
            ultimo = (type(self)._default_manager
                      .filter(**{campo: getattr(self, campo) for campo in self.ambito_orden})
                      .aggregate(m=models.Max('orden'))['m'])
            self.orden = (ultimo or 0) + 1
        super().save(*args, **kwargs)


#: Los únicos tridentes posibles: «tridente» son tres niveles (decisión del 27-10-2026).
TRIDENTES_VALIDOS = ('I', 'II', 'III')

#?SALARIO
class NTridente(SinRepetidos, Base):

    tipo = models.CharField(max_length=10, blank=False, null=False)

    campo_unico = 'tipo'

    class Meta:
        verbose_name = ("NTridente")
        verbose_name_plural = ("NTridentes")
        # I < II < III también en orden alfabético: solo existen esos tres.
        ordering = ['tipo']

    def clean(self):
        self.tipo = (self.tipo or '').strip().upper()
        if self.tipo not in TRIDENTES_VALIDOS:
            raise ValidationError({'tipo': 'El tridente es un número romano: I, II o III.'})
        super().clean()

    def __str__(self):
        return f"Tridente {self.tipo}"

# nomencladores/models.py

class NRol(SinRepetidos, Ordenable, Base):
    tipo = models.CharField(max_length=50)
    # Se eliminó el campo es_cuadro de aquí

    campo_unico = 'tipo'

    class Meta:
        verbose_name = ("NRol")
        verbose_name_plural = ("NRoles")
        # Orden oficial de la escala: Decisorio, Fundamental, Apoyo (de más a menos).
        ordering = ['orden', 'tipo']

    def __str__(self):
        return self.tipo

class NGrupoEscala(SinRepetidos, Base):
    nivel = models.CharField(max_length=8, unique=True)

    campo_unico = 'nivel'
    
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
        # Por su número romano (I, II, … XXV), en todo Orbith.
        ordering = ['valor_numerico_db', 'nivel']
    
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

    # PROTECT (27-10-2026): borrar un grupo, un rol o un tridente se llevaba en silencio
    # sus importes de la escala (así se perdieron los 66 del Tridente III). Ahora se
    # impide y se explica; la escala se vacía antes, a propósito, desde su pantalla.
    grupo_escala = models.ForeignKey(NGrupoEscala, on_delete=models.PROTECT)
    rol = models.ForeignKey(NRol, null=True, blank=True, on_delete=models.PROTECT)
    tridente = models.ForeignKey(NTridente, null=True, blank=True, on_delete=models.PROTECT)
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
        
class NTipoFamilia(SinRepetidos, Ordenable, Base):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Tipo de Familia")

    campo_unico = 'nombre'

    class Meta:
        verbose_name = "Tipo de Familia"
        verbose_name_plural = "Tipos de Familias"
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre

class NFamiliaCargo(SinRepetidos, Ordenable, Base):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    # PROTECT (27-10-2026): borrar un tipo de familia se llevaba todas sus familias.
    tipo_familia = models.ForeignKey(NTipoFamilia, on_delete=models.PROTECT, related_name='familias')

    campo_unico = 'nombre'
    ambito_orden = ('tipo_familia_id',)

    class Meta:
        verbose_name = "Familia de Cargos"
        verbose_name_plural = "Familias de Cargos"
        unique_together = ('nombre', 'tipo_familia')
        ordering = ['orden', 'nombre']

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
# COLORES QUE ELIGE EL USUARIO: QUE SE PUEDAN LEER
# --------------------------------------------------------------------------
# El color de cada tipo de unidad lo elige el usuario en el nomenclador. Como
# fondo o como icono vale cualquiera, pero como LETRA sobre blanco un amarillo o
# un verde limón no se lee (informe de contratos determinados, 24-10-2026).
# Se mide con el contraste de las pautas de accesibilidad (WCAG): 4.5 es el
# mínimo recomendado para texto normal.

CONTRASTE_MINIMO = 4.5


def _luminancia(hexadecimal):
    """Luminancia relativa (0 = negro, 1 = blanco) de un color «#RRGGBB»."""
    canales = []
    for i in (1, 3, 5):
        c = int(hexadecimal[i:i + 2], 16) / 255
        canales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = canales
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste_con_blanco(hexadecimal):
    return 1.05 / (_luminancia(hexadecimal) + 0.05)


def _normalizar_hex(color):
    """«#abc» o «#AABBCC» → «#aabbcc»; None si no es un color hexadecimal."""
    texto = (color or '').strip().lower()
    if len(texto) == 4 and texto.startswith('#'):
        texto = '#' + ''.join(c * 2 for c in texto[1:])
    if len(texto) != 7 or not texto.startswith('#'):
        return None
    try:
        int(texto[1:], 16)
    except ValueError:
        return None
    return texto


def es_color_claro(color):
    """¿Este color, como letra sobre blanco, se lee mal?"""
    normal = _normalizar_hex(color)
    return bool(normal) and contraste_con_blanco(normal) < CONTRASTE_MINIMO


def color_legible(color):
    """El mismo color, oscurecido lo justo para leerse como letra sobre blanco.

    Conserva el tono (un amarillo pasa a mostaza, un verde claro a verde oscuro)
    mezclándolo poco a poco con negro hasta llegar al contraste mínimo. Un color
    que ya se lee se devuelve tal cual, y uno que no es hexadecimal también.
    """
    normal = _normalizar_hex(color)
    if not normal or contraste_con_blanco(normal) >= CONTRASTE_MINIMO:
        return color
    r, g, b = (int(normal[i:i + 2], 16) for i in (1, 3, 5))
    for paso in range(1, 21):
        factor = 1 - paso * 0.05
        oscuro = '#%02x%02x%02x' % (round(r * factor), round(g * factor), round(b * factor))
        if contraste_con_blanco(oscuro) >= CONTRASTE_MINIMO:
            return oscuro
    return '#000000'


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

    def save(self, *args, **kwargs):
        anterior = None
        if self.pk:
            anterior = NCargo.objects.filter(pk=self.pk).select_related('grupo_escala').first()
        super().save(*args, **kwargs)
        if anterior is not None:
            self._aplicar_a_sus_contratos(anterior)

    def _aplicar_a_sus_contratos(self, anterior):
        """El nomenclador define el grupo escala, el salario básico (Fijo), la
        categoría y el nombre del cargo de quienes lo ocupan: si cambian, cambian sus
        datos sin tocar su contrato (decisión de RRHH del 23-10-2026).

        * Pasa a Cuadro: un cuadro no tiene rol ni tridente; se quitan del cargo y
          de sus contratos. Si su grupo no tiene importe de Cuadros, SAL-002 avisa.
        * Deja de ser Cuadro: el cargo queda sin rol (lo avisa la regla «cargo sin
          rol») y sus contratos dinámicos sin tridente (lo avisa SAL-002) hasta que
          RRHH los asigne.
        * Se recalcula el salario guardado, se anota un cambio externo por contrato
          y se avisa en la campana.
        """
        from contratos.cambios_externos import Afectado, registrar_cambio, texto_del_motivo
        from contratos.models import CAlta, CambioExterno
        from strorganizativa.models import CargoPlantilla

        cambios = []
        if anterior.descripcion != self.descripcion:
            cambios.append('pasó a llamarse «%s»' % self.descripcion)
        if anterior.grupo_escala_id != self.grupo_escala_id:
            cambios.append('cambió del grupo escala %s al %s' % (
                anterior.grupo_escala.nivel, self.grupo_escala.nivel))
        if anterior.salario_basico != self.salario_basico:
            cambios.append('cambió su salario básico de %s a %s' % (
                anterior.salario_basico, self.salario_basico))
        if anterior.cat_ocupacional != self.cat_ocupacional:
            cambios.append('cambió de categoría: %s a %s' % (
                anterior.get_cat_ocupacional_display(), self.get_cat_ocupacional_display()))
        if not cambios:
            return

        contratos = CAlta.objects.filter(cargo__ncargo=self)
        if self.es_cuadro and not anterior.es_cuadro:
            CargoPlantilla.objects.filter(ncargo=self).update(rol=None)
            contratos.update(tridente=None)
        if not contratos.exists():
            return

        salarios = {c.pk: (antes, despues)
                    for c, antes, despues in CAlta.recalcular_salarios(contratos)}
        descripcion = 'El cargo «%s» %s.' % (anterior.descripcion, ' y '.join(cambios))
        if self.es_cuadro and not anterior.es_cuadro:
            descripcion += ' Como Cuadro, se le quitaron el rol y el tridente.'
        elif anterior.es_cuadro and not self.es_cuadro:
            descripcion += ' Queda pendiente asignar el rol del cargo y el tridente.'
        lista = list(contratos.select_related('aspirante'))
        registrar_cambio(CambioExterno.Origen.NOMENCLADOR_CARGO, self, [
            Afectado(c, descripcion,
                     *(('Salario %s' % salarios[c.pk][0], 'Salario %s' % salarios[c.pk][1])
                       if c.pk in salarios else ('', '')))
            for c in lista])
        try:
            from notificaciones.avisos import CODIGO_CAMBIO_ROL, avisar_cambio_salarial
            total = len(lista)
            avisar_cambio_salarial(
                self, codigo=CODIGO_CAMBIO_ROL, titulo='Cambio en un nomenclador de cargo',
                mensaje=' '.join(p for p in (
                    descripcion,
                    'Afecta a %s %s; a %s se le actualizó el salario.' % (
                        total, 'contrato' if total == 1 else 'contratos', len(salarios)),
                    texto_del_motivo()) if p))
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'No se pudo avisar del cambio del nomenclador de cargo %s.', self.pk)

    class Meta:
        verbose_name = ("NCargo")
        verbose_name_plural = ("NCargos")

    def __str__(self):
        return self.descripcion
    
class NNocturnidad(SinRepetidos, Ordenable, Base):
    codigo = models.CharField(max_length=50, unique=True, verbose_name="Código (Ej: N1)")
    hora_inicio = models.TimeField(verbose_name="Hora Inicio")
    hora_fin = models.TimeField(verbose_name="Hora Fin")

    campo_unico = 'codigo'

    class Meta:
        verbose_name = "Nocturnidad"
        verbose_name_plural = "Nocturnidades"
        ordering = ['orden', 'codigo']

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

class NCondicionLaboralAnormal(SinRepetidos, Ordenable):
    nombre = models.CharField(max_length=10, unique=True)
    descripcion = models.TextField(max_length=200, blank=True, null=True)

    tarifa_hora = models.DecimalField(
        validators=[MinValueValidator(0)],
        max_digits=7,
        decimal_places=2,
        default=Decimal("0")
    )

    # PROTECT (27-10-2026): borrar la nocturnidad dejaba la condición sin ella en silencio.
    nocturnidad = models.OneToOneField(
        NNocturnidad,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="condicion"
    )

    campo_unico = 'nombre'

    class Meta:
        verbose_name = "Condición Laboral Anormal"
        verbose_name_plural = "Condiciones Laborales Anormales"
        ordering = ['orden', 'nombre']

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


class NProvincia(SinRepetidos, Ordenable, Base):

    nombre = models.CharField(max_length=50, unique=True)
    siglas = models.CharField(
        max_length=3,
        null=True, blank=True,
        verbose_name="Siglas",
        help_text="Exactamente 3 letras mayúsculas"
    )

    campo_unico = 'nombre'

    class Meta:
        verbose_name = ("NProvincia")
        verbose_name_plural = ("NProvincias")
        ordering = ['orden', 'nombre']

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

class NMunicipio(SinRepetidos, Ordenable, Base):

    nombre = models.CharField(max_length=50)
    provincia = models.ForeignKey(NProvincia, on_delete=models.RESTRICT)    
    siglas = models.CharField(
        max_length=3,
        null=True, blank=True,
        verbose_name="Siglas",
        help_text="Exactamente 3 letras mayúsculas"
    )

    campo_unico = 'nombre'
    ambito_unico = ('provincia_id',)
    ambito_orden = ('provincia_id',)

    class Meta:
        verbose_name = ("NMunicipio")
        verbose_name_plural = ("NMunicipios")
        unique_together = ('nombre', 'provincia')
        ordering = ['orden', 'nombre']

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
class NCausaAltaBaja(SinRepetidos, Ordenable, Base):

    descripcion = models.CharField(max_length=50, blank=False, null=False)
    alta = models.BooleanField(default=False, blank=False, null=False)

    campo_unico = 'descripcion'

    class Meta:
        verbose_name = ("NCausa Alta/Baja")
        verbose_name_plural = ("NCausas de Alta/Baja")
        ordering = ['orden', 'descripcion']

    def __str__(self):
        return self.descripcion


#?TIEMPO DE TRABAJO
# `NHorario` y `NJornada` se eliminaron: sus tarjetas se habían retirado del
# acordeón «Tiempo de Trabajo» hacía tiempo, ninguna plantilla las usaba, las
# dos tablas estaban vacías y ningún contrato tenía jornada asignada. El tiempo
# de trabajo se gestiona ahora desde Pre-Nómina → Calendario.

#?PROFESIONES
class NEspecialidad(SinRepetidos, Ordenable):

    nombre = models.CharField( max_length=50, unique=True)
    educ_superior = models.BooleanField(verbose_name='Educ. Superior', default=False)

    campo_unico = 'nombre'

    class Meta:
        verbose_name = ("NEspecialidad")
        verbose_name_plural = ("NEspecialidad")
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class NNivelPreparacion(SinRepetidos, Ordenable, Base):
    nombre = models.CharField(max_length=50, unique=True)

    campo_unico = 'nombre'

    class Meta:
        verbose_name = "Nivel de Preparación"
        verbose_name_plural = "Niveles de Preparación"
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre

class NTipoContrato(SinRepetidos, Ordenable, Base):
    descripcion = models.CharField(max_length=50, unique=True, verbose_name="Descripción")
    ocupa_plaza = models.BooleanField(default=False, verbose_name="¿Ocupa Plaza en Plantilla?")
    # NUEVO SWITCH
    requiere_motivo = models.BooleanField(default=False, verbose_name="¿Requiere Motivo?") 
    es_adiestrado = models.BooleanField(default=False, verbose_name="¿Es Adiest?")

    campo_unico = 'descripcion'

    class Meta:
        verbose_name = "Tipo de Contrato"
        verbose_name_plural = "Tipos de Contratos"
        ordering = ['orden', 'descripcion']

    def __str__(self):
        return self.descripcion

    def save(self, *args, **kwargs):
        ocupaba = (NTipoContrato.objects.filter(pk=self.pk)
                   .values_list('ocupa_plaza', flat=True).first()) if self.pk else None
        super().save(*args, **kwargs)
        if ocupaba is not None and ocupaba != self.ocupa_plaza:
            self._recontar_plazas()

    def _recontar_plazas(self):
        """«Ocupa plaza» decide qué contratos cuentan como plazas cubiertas. Al
        cambiarlo se recuentan los cargos que tienen contratos de este tipo (antes se
        quedaban desfasados hasta guardar algún contrato, y podían mostrar plazas
        libres que no lo estaban). Si algún cargo queda con más ocupantes que plazas
        aprobadas, se avisa a los administradores (decisión de RRHH, 23-10-2026)."""
        from strorganizativa.models import CargoPlantilla

        cargos = CargoPlantilla.objects.filter(calta__tipo=self).distinct()
        sobrepasados = []
        for cargo in cargos:
            cargo.refrescar_conteo_plazas()
            if cargo.cant_cubierta > cargo.cant_aprobada:
                sobrepasados.append(cargo)
        if not sobrepasados:
            return
        try:
            from notificaciones.avisos import CODIGO_CAMBIO_ESTRUCTURA, avisar_cambio_salarial
            lista = ', '.join('%s (%s de %s plazas)' % (
                c.ncargo.descripcion, c.cant_cubierta, c.cant_aprobada) for c in sobrepasados[:10])
            avisar_cambio_salarial(
                self, codigo=CODIGO_CAMBIO_ESTRUCTURA,
                titulo='Cargos con más ocupantes que plazas',
                mensaje=('El tipo de contrato «%s» %s ocupa plaza. Quedaron %s cargos con más '
                         'ocupantes que plazas aprobadas: %s.' % (
                             self.descripcion, 'ahora' if self.ocupa_plaza else 'ya no',
                             len(sobrepasados), lista)))
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'No se pudo avisar del recuento de plazas del tipo %s.', self.pk)

# NUEVO NOMENCLADOR
class NMotivoContrato(SinRepetidos, Ordenable, Base):
    descripcion = models.CharField(max_length=100, verbose_name="Descripción")   # ← quitado unique=True
    tipo_contrato = models.ForeignKey(
        NTipoContrato,
        on_delete=models.RESTRICT,
        related_name="motivos",                # ← quitados null=True y blank=True
        verbose_name="Tipo de Contrato Asociado"
    )

    campo_unico = 'descripcion'
    ambito_unico = ('tipo_contrato_id',)

    class Meta:
        verbose_name = "Motivo de Contrato"
        verbose_name_plural = "Motivos de Contratos"
        ordering = ['orden', 'descripcion']
        constraints = [
            models.UniqueConstraint(
                fields=['descripcion', 'tipo_contrato'],
                name='unique_motivo_por_tipo',
            )
        ]

    def __str__(self):
        return self.descripcion

class NTipoUnidadOrganizativa(SinRepetidos, Ordenable, Base):
    descripcion = models.CharField(max_length=150, unique=True, verbose_name="Tipo de Unidad")
    es_temporal = models.BooleanField(default=False, verbose_name="Es temporal")
    es_principal = models.BooleanField(default=False, verbose_name="Unidad Principal")
    es_subunidad = models.BooleanField(default=False, verbose_name="Subunidad")
    # PROTECT (27-10-2026): un tipo con subtipos no se borra (antes los dejaba sin padre).
    tipo_padre = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='subtipos', verbose_name="Tipo Principal (Padre)")

    # Aquí guardaremos el código HEX del color (ej. #FF5733)
    color = models.CharField(max_length=20, blank=True, null=True, verbose_name="Color de Jerarquía")

    campo_unico = 'descripcion'

    class Meta:
        verbose_name = "Tipo de Unidad Organizativa"
        verbose_name_plural = "Tipos de Unidades Organizativas"
        ordering = ['orden', 'descripcion']

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
# Aquí viven esas cuantías, y desde el 23-10-2026 el contrato ya NO guarda el
# número: el nomenclador manda (`CAlta.importe_*`). El pasado lo protegen las
# copias que congelan la Pre-Nómina y los cierres al emitirse.


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

    def save(self, *args, **kwargs):
        anterior = (NImporteGradoCientifico.objects.filter(pk=self.pk)
                    .values_list('importe', flat=True).first()) if self.pk else None
        super().save(*args, **kwargs)
        if anterior is not None and anterior != self.importe:
            from contratos.cambios_externos import registrar_cambio_de_importe
            registrar_cambio_de_importe(
                self, self.get_grado_display(), anterior, self.importe,
                aspirante__grado_cientifico=self.grado)


class NPagoAdicional(SinRepetidos, Ordenable, Base):
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

    campo_unico = 'descripcion'
    ambito_unico = ('tipo',)
    ambito_orden = ('tipo',)

    class Meta:
        verbose_name = 'Pago adicional'
        verbose_name_plural = 'Pagos adicionales'
        ordering = ['tipo', 'orden', 'descripcion']
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

    def save(self, *args, **kwargs):
        anterior = (NPagoAdicional.objects.filter(pk=self.pk)
                    .values_list('importe', flat=True).first()) if self.pk else None
        super().save(*args, **kwargs)
        if anterior is not None and anterior != self.importe:
            from contratos.cambios_externos import registrar_cambio_de_importe
            campo = 'cnci_nomenclador' if self.tipo == self.CNCI else 'instructor_nomenclador'
            registrar_cambio_de_importe(
                self, f'{self.get_tipo_display()} «{self.descripcion}»', anterior, self.importe,
                **{campo: self})
