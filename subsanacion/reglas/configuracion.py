"""Reglas de integridad de la configuración general de la entidad.

Estas dos reglas son el único camino de los HALLAZGOS GLOBALES: los que no apuntan a
una fila concreta (`object_id` vacío) porque el problema es la ausencia del registro.
"""

from ..constantes import (
    CRITICIDAD_CRITICA,
    CRITICIDAD_MEDIA,
    MODULO_CONFIGURACION,
)
from .base import HallazgoDetectado, ReglaBase


class ConfiguracionDeLaEntidad(ReglaBase):
    """Debe existir exactamente una fila de configuración.

    El modelo lo fuerza en `save()` (lanza ValueError si ya hay una), pero eso solo
    protege las escrituras que pasan por el modelo: una importación, un `.create()`
    masivo o un INSERT directo pueden dejar cero filas o más de una.
    """

    codigo = 'CFG-001'
    nombre = 'Configuración de la entidad ausente o duplicada'
    modulo = MODULO_CONFIGURACION
    criticidad = CRITICIDAD_CRITICA
    modelo = 'configuracion.Configuracion'

    descripcion = (
        'Comprueba que exista una y solo una configuración general de la entidad.')
    causa_probable = (
        'Nunca se completó la configuración inicial, o se insertaron filas sin pasar '
        'por el formulario (importación, restauración de una copia de seguridad o una '
        'consulta SQL directa).')
    impacto = (
        'Sin configuración no hay nombre de entidad, REUP, moneda ni período de pago, '
        'así que los informes y los documentos oficiales salen incompletos o fallan. '
        'Con más de una fila, Orbith usa la primera que encuentra y el resultado deja '
        'de ser predecible: dos informes pueden citar datos de entidad distintos.')
    solucion = (
        'Si falta, abra Parámetros Generales y complete la configuración de la '
        'entidad. Si hay más de una, decida cuál es la correcta y elimine las demás '
        'con ayuda del administrador de la base de datos, porque el formulario no '
        'permite borrarlas.')

    def ejecutar(self, contexto):
        modelo = self.obtener_modelo()
        total = modelo._default_manager.count()

        if total == 0:
            yield HallazgoDetectado(
                # Hallazgo GLOBAL: no hay ninguna fila a la que apuntar.
                object_id='',
                clave_extra='ausente',
                titulo='No existe la configuración general de la entidad',
                detalle=(
                    'La tabla de configuración está vacía. Orbith no conoce el nombre '
                    'de la entidad, su REUP ni sus parámetros de cálculo.'),
                datos={'configuraciones_encontradas': 0},
            )
            return

        if total > 1:
            yield HallazgoDetectado(
                object_id='',
                clave_extra='duplicada',
                titulo=f'Hay {total} configuraciones de entidad y debería haber una sola',
                detalle=(
                    f'Se encontraron {total} filas de configuración. Orbith usa la '
                    f'primera, así que el comportamiento del sistema depende del orden '
                    f'en que la base de datos las devuelva.'),
                datos={'configuraciones_encontradas': total},
            )


class ConfiguracionIncompleta(ReglaBase):
    """Faltan datos de la entidad que los informes oficiales necesitan.

    Es una regla separada de CFG-001 a propósito: la criticidad es un atributo de la
    regla, así que una regla debe agrupar solo problemas de gravedad equivalente. Que
    falte el correo de contacto no es lo mismo que no exista la configuración, y
    mezclarlos haría aparecer «falta el correo» como crítico.
    """

    codigo = 'CFG-002'
    nombre = 'Datos de la entidad incompletos'
    modulo = MODULO_CONFIGURACION
    criticidad = CRITICIDAD_MEDIA
    modelo = 'configuracion.Configuracion'

    descripcion = (
        'Revisa que la configuración de la entidad tenga completos los datos que usan '
        'los informes y los documentos oficiales.')
    causa_probable = (
        'Son campos opcionales en el formulario, así que la configuración se puede '
        'guardar sin ellos y quedan pendientes de completar.')
    impacto = (
        'Los informes y documentos oficiales se emiten con esos datos en blanco. En el '
        'caso del REUP y la provincia, eso puede invalidar el documento ante la '
        'entidad que lo recibe.')
    solucion = (
        'Abra Parámetros Generales y complete los campos que se indican abajo.')

    # (nombre del campo en .values(), etiqueta para el usuario, por qué hace falta)
    CAMPOS_REQUERIDOS = (
        ('reup', 'REUP',
         'identifica la entidad en el Registro Estatal de Unidades Presupuestadas'),
        ('provincia_entidad_id', 'Provincia de la entidad',
         'aparece en el encabezado de los informes oficiales'),
        ('correo', 'Correo electrónico',
         'es el contacto que figura en los documentos que emite la entidad'),
    )

    def ejecutar(self, contexto):
        modelo = self.obtener_modelo()
        fila = (modelo._default_manager
                .values('id', 'nombre_empresa', 'reup', 'provincia_entidad_id', 'correo')
                .first())

        if fila is None:
            # La ausencia de configuración la reporta CFG-001. Esta regla no duplica
            # ese hallazgo: cada problema debe tener una sola ficha.
            return

        entidad = fila.get('nombre_empresa') or 'la entidad'

        for campo, etiqueta, motivo in self.CAMPOS_REQUERIDOS:
            if fila.get(campo):
                continue
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                # Un hallazgo por campo: así el usuario puede ignorar uno y atender
                # otro. Sin `clave_extra` los tres se pisarían en el UPSERT.
                clave_extra=campo,
                titulo=f'{entidad} · falta el dato «{etiqueta}» en la configuración',
                detalle=f'El campo «{etiqueta}» está vacío, y {motivo}.',
                datos={
                    'entidad': entidad,
                    'campo_vacio': etiqueta,
                    'para_que_sirve': motivo,
                },
            )
