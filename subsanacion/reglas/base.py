"""Contrato de una regla de integridad.

Cómo añadir una regla nueva:

    1. Cree (o abra) el archivo de su categoría en `subsanacion/reglas/`.
    2. Escriba una clase que herede de `ReglaBase`.
    3. Nada más. Se registra sola al importarse el módulo.

No hay que tocar el motor, ni el registro, ni las vistas, ni el dashboard. Nunca.

Dos invariantes que NO se pueden romper:

    * `codigo` es inmutable para siempre. Forma parte de la clave natural del
      hallazgo en la base de datos: cambiarlo equivale a borrar el historial y las
      decisiones («Ignorado», «Falso positivo») que el usuario tomó sobre él.
    * `ejecutar()` JAMÁS escribe en la base de datos. Solo produce valores. Así la
      regla es testeable en aislamiento y el módulo no puede modificar datos de
      negocio ni por accidente.

Y una consecuencia del diseño que conviene tener presente al escribir reglas: la
criticidad es un atributo de la REGLA, no del hallazgo. Por tanto una regla debe
agrupar solo problemas de gravedad equivalente. Si al escribirla nota que un caso es
crítico y otro es menor, son dos reglas, no una (véase CFG-001 y CFG-002). Lo que sí
puede producir varios hallazgos con la misma gravedad es `clave_extra` (véase CTR-002).
"""

from dataclasses import dataclass, field
from typing import Iterator, Optional

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured

from ..constantes import CLAVES_MODULOS, COLOR_POR_CRITICIDAD, ETIQUETA_CRITICIDAD


@dataclass(frozen=True)
class HallazgoDetectado:
    """Lo que produce una regla: un valor puro, no una fila de la base de datos.

    `datos` guarda los valores que definen el problema (el valor guardado, el
    esperado, el contexto). Es lo que se muestra en «¿Qué encontró?» y también lo
    que se resume en la huella del hallazgo, así que NO debe contener valores
    volátiles (fechas de ejecución, contadores): si cambian sin que el problema
    cambie, la huella se movería y un hallazgo silenciado volvería a Pendiente sin
    motivo.
    """

    object_id: str
    titulo: str
    detalle: str = ''
    datos: dict = field(default_factory=dict)
    clave_extra: str = ''
    unidad_organizativa_id: Optional[int] = None


# Registro de reglas, en orden de declaración. La clave es el código de la regla.
_REGISTRO = {}

# Campos que toda regla concreta tiene que declarar. Los cuatro textos de la guía
# son obligatorios a propósito: un hallazgo que no explica por qué es un problema ni
# cómo se corrige incumple la razón de ser del módulo.
CAMPOS_OBLIGATORIOS = (
    'codigo', 'nombre', 'modulo', 'criticidad', 'modelo',
    'descripcion', 'causa_probable', 'impacto', 'solucion',
)


def registrar(clase):
    """Valida y registra una regla. Se llama sola al heredar de `ReglaBase`.

    Cualquier error se lanza en tiempo de importación, es decir al arrancar el
    servidor o al ejecutar `manage.py check`, nunca en producción a mitad de un
    análisis.
    """
    ruta = f'{clase.__module__}.{clase.__qualname__}'

    for campo in CAMPOS_OBLIGATORIOS:
        if not getattr(clase, campo, None):
            raise ImproperlyConfigured(
                f'La regla {ruta} no define «{campo}». Todas las reglas deben '
                f'declarar {", ".join(CAMPOS_OBLIGATORIOS)}.'
            )

    if clase.modulo not in CLAVES_MODULOS:
        raise ImproperlyConfigured(
            f'La regla {ruta} declara la categoría «{clase.modulo}», que no existe. '
            f'Categorías válidas: {", ".join(CLAVES_MODULOS)}.'
        )

    if clase.criticidad not in ETIQUETA_CRITICIDAD:
        raise ImproperlyConfigured(
            f'La regla {ruta} declara la criticidad {clase.criticidad}, que no existe. '
            f'Use las constantes CRITICIDAD_* de subsanacion.constantes.'
        )

    if clase.modelo.count('.') != 1:
        raise ImproperlyConfigured(
            f'La regla {ruta} declara el modelo «{clase.modelo}». El formato correcto '
            f'es «app.Modelo», por ejemplo «contratos.CAlta».'
        )

    ya_registrada = _REGISTRO.get(clase.codigo)
    if ya_registrada is not None:
        if f'{ya_registrada.__module__}.{ya_registrada.__qualname__}' == ruta:
            # Mismo módulo reimportado (recarga del servidor de desarrollo): no es un error.
            return
        raise ImproperlyConfigured(
            f'El código «{clase.codigo}» está duplicado: lo usan {ruta} y '
            f'{ya_registrada.__module__}.{ya_registrada.__qualname__}. Los códigos son '
            f'la clave natural de los hallazgos y tienen que ser únicos.'
        )

    _REGISTRO[clase.codigo] = clase


class ReglaBase:
    """Clase base de todas las reglas de integridad."""

    # --- Identidad (obligatorio) -----------------------------------------
    codigo = ''          # 'CTR-001'. INMUTABLE: es la clave natural del hallazgo.
    nombre = ''          # 'Contrato sin cargo asignado'
    modulo = ''          # una de las constantes MODULO_* de constantes.py
    criticidad = 0       # una de las constantes CRITICIDAD_* de constantes.py
    modelo = ''          # 'contratos.CAlta'

    # --- Textos de la guía (obligatorio) ---------------------------------
    descripcion = ''     # qué comprueba la regla, en general
    causa_probable = ''  # por qué suele ocurrir
    impacto = ''         # por qué es un problema
    solucion = ''        # qué tiene que hacer el usuario, en concreto

    # --- Comportamiento --------------------------------------------------
    activa = True
    # `abstracta = True` en una base intermedia evita que se registre. No se hereda:
    # las clases hijas se registran con normalidad.
    abstracta = True
    # Por defecto el botón «Abrir registro» se resuelve por `modelo`. Estos dos
    # atributos permiten apuntar a otro sitio cuando el registro afectado no es donde
    # se corrige el problema (por ejemplo, una regla de TMovimiento que se arregla en
    # el contrato de alta).
    modelo_enlace = None
    enlace_url = None

    def __init_subclass__(cls, **kwargs):
        """Registra la regla por el simple hecho de heredar.

        Se usa `__init_subclass__` en lugar de un decorador `@registrar_regla` porque
        el requisito es que añadir una regla no obligue a escribir ni importar nada
        más: basta con heredar.

        La comprobación es sobre `cls.__dict__` y no sobre `cls.abstracta` a
        propósito. Así `abstracta` NO se hereda: una base intermedia (por ejemplo
        `ReglaContratos`) la declara y se salta el registro, mientras que sus clases
        hijas, que no la declaran, se registran con normalidad.
        """
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get('abstracta', False):
            return
        registrar(cls)

    # ------------------------------------------------------------------
    # API que usa el motor
    # ------------------------------------------------------------------
    def obtener_modelo(self):
        """Resuelve el modelo con `apps.get_model` para evitar imports circulares."""
        app_label, nombre_modelo = self.modelo.split('.')
        return apps.get_model(app_label, nombre_modelo)

    def modelo_del_enlace(self):
        """Etiqueta «app.Modelo» a la que apunta el botón «Abrir registro»."""
        return self.modelo_enlace or self.modelo

    def base_queryset(self):
        """QuerySet de partida.

        Ojo: SIN filtro de alcance por rol. El barrido lee siempre toda la empresa
        (ver el docstring de `subsanacion.servicios`); el alcance por unidad se
        aplica al LEER el listado, no al detectar.
        """
        return self.obtener_modelo()._default_manager.all()

    def ejecutar(self, contexto) -> Iterator[HallazgoDetectado]:
        """Produce los hallazgos. Debe ser un generador y no debe escribir en la BD."""
        raise NotImplementedError(
            f'La regla {self.codigo} no implementa ejecutar().')

    # ------------------------------------------------------------------
    # Evaluación en caliente (al guardar una instancia, no en el barrido)
    # ------------------------------------------------------------------
    # `False` por defecto: la inmensa mayoría de las reglas solo tienen sentido en el
    # barrido periódico (recorren la tabla, agregan, comparan contra miles de filas).
    # Solo las reglas pensadas para dispararse al guardar activan este flag.
    evaluable_en_caliente = False

    def evaluar_instancia(self, instancia) -> Optional[list]:
        """Evalúa UNA instancia recién guardada. `None` (o lista vacía) si no hay
        problema; si no, una lista de `HallazgoDetectado`.

        RESTRICCIÓN DE RENDIMIENTO, NO NEGOCIABLE: este método se ejecuta dentro de
        `save()` de un modelo de negocio (ver `notificaciones/avisos.py`), en el
        camino síncrono de cada guardado del sistema. Por tanto SOLO puede contener
        comprobaciones de coste O(1):

            * campos propios de `instancia`;
            * como mucho, UN salto de relación directa ya accesible por FK
              (`instancia.aspirante.grado_cientifico`, `instancia.cargo.funcionario`).

        PROHIBIDO explícitamente, aquí y en cualquier regla que implemente esto:
            * recorrer una tabla completa (`.all()`, `.filter()` sobre miles de filas);
            * agregaciones (`Count`, `Sum`, `annotate` sobre un queryset grande);
            * cualquier búsqueda que no sea instantánea.

        Si una regla necesita recorrer la base de datos para detectar un problema,
        esa regla vive EXCLUSIVAMENTE en `ejecutar()` (el barrido periódico de
        Subsanación) y jamás activa `evaluable_en_caliente`. Convertir `CAlta.save()`
        en un cuello de botella por una regla pesada añadida aquí sin darse cuenta es
        precisamente lo que esta restricción existe para evitar.

        La condición booleana de la regla NO se repite aquí: se extrae a una función
        pura de módulo que tanto `ejecutar()` como este método llaman (mismo patrón
        que `contratos/salarios.py::calcular_salario`), para que ambos caminos nunca
        puedan divergir. Ver `subsanacion/reglas/contratos.py` (p. ej. CTR-007) como
        referencia de implementación.
        """
        raise NotImplementedError(
            f'La regla {self.codigo} no implementa evaluar_instancia().')

    # ------------------------------------------------------------------
    # Ayudas para las plantillas
    # ------------------------------------------------------------------
    @property
    def etiqueta_criticidad(self):
        return ETIQUETA_CRITICIDAD.get(self.criticidad, '')

    @property
    def color(self):
        """Nombre de la clase CSS `sub-color-*` de la criticidad."""
        return COLOR_POR_CRITICIDAD.get(self.criticidad, 'gris')

    def __str__(self):
        return f'{self.codigo} · {self.nombre}'
