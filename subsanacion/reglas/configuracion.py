"""Reglas de integridad de la configuración general de la entidad.

Estas dos reglas son el único camino de los HALLAZGOS GLOBALES: los que no apuntan a
una fila concreta (`object_id` vacío) porque el problema es la ausencia del registro.
"""

from django.db.models import Count

from ..constantes import (
    CRITICIDAD_ALTA,
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


class NomencladorDeGradoCientificoVacio(ReglaBase):
    """Hay trabajadores con grado científico pero el nomenclador no tiene importe.

    Nace de una decisión concreta: los campos «Maestría» y «Doctorado» del
    contrato pasaron a ser de solo lectura y a rellenarse desde el nomenclador.
    Si el nomenclador está vacío, el contrato muestra «Nomenc. Vacío» y guarda 0
    — y quien edita el contrato ya NO puede arreglarlo desde ahí.

    Por eso el hallazgo vive en Configuración y no en Contratos: apunta a quien
    SÍ puede resolverlo, el Administrador, y una sola vez en lugar de repetirse
    en cada contrato afectado.

    Solo salta si hay alguien a quien le afecte. Un nomenclador sin definir en
    una empresa sin ningún máster ni doctor no es un problema, y avisar de él
    sería ruido.
    """

    codigo = 'CFG-003'
    nombre = 'Nomenclador de grado científico sin importe definido'
    modulo = MODULO_CONFIGURACION
    criticidad = CRITICIDAD_ALTA
    modelo = 'nomencladores.NImporteGradoCientifico'

    descripcion = (
        'Comprueba que, si hay trabajadores registrados como Máster o como Doctor, '
        'el importe correspondiente esté definido en el nomenclador.')
    causa_probable = (
        'Los importes de Maestría y Doctorado son tarjetas nuevas de Configuración '
        'y todavía no se han rellenado, o se registró el primer trabajador con ese '
        'grado científico después de configurar el sistema.')
    impacto = (
        'El contrato de esos trabajadores muestra «Nomenc. Vacío» y cobran 0 por ese '
        'concepto, es decir, de menos. Y no se puede arreglar desde el propio '
        'contrato: el importe sale siempre del nomenclador.')
    solucion = (
        'Abra Configuración → Parámetros Generales → Nomencladores → Laborales y '
        'Profesionales y defina el importe en la tarjeta que se indica abajo. Los '
        'contratos lo toman solos.')

    #: (clave del grado, etiqueta de la tarjeta) — la clave es la misma que usa
    #: `bolsa.Aspirante.grado_cientifico`, así que no hay tabla de equivalencias
    #: que se pueda desincronizar.
    GRADOS = (('MC', 'Maestría'), ('DC', 'Doctorado'))

    def ejecutar(self, contexto):
        from django.apps import apps

        Aspirante = apps.get_model('bolsa', 'Aspirante')
        modelo = self.obtener_modelo()

        # Dos consultas agregadas en total, no una por trabajador.
        definidos = set(modelo._default_manager.values_list('grado', flat=True))
        con_grado = {
            grado: total for grado, total in
            Aspirante.objects.filter(grado_cientifico__in=[g for g, _ in self.GRADOS],
                                     estado='ACTIVO')
            .values_list('grado_cientifico')
            .annotate(total=Count('id'))
        }

        for grado, etiqueta in self.GRADOS:
            afectados = con_grado.get(grado, 0)
            if not afectados or grado in definidos:
                continue

            yield HallazgoDetectado(
                # Hallazgo GLOBAL: el problema es la AUSENCIA del registro, así que
                # no hay ninguna fila a la que apuntar. Es el mismo patrón que
                # CFG-001. `clave_extra` separa el de Maestría del de Doctorado.
                object_id='',
                clave_extra=grado,
                titulo=f'Sin importe de {etiqueta} y hay trabajadores con ese grado',
                detalle=(
                    f'{afectados} trabajador(es) activo(s) tienen el grado de '
                    f'{etiqueta}, pero su importe no está definido en el nomenclador, '
                    f'así que cobran 0 por ese concepto.'),
                # El número de afectados NO entra en `datos`: cambia con cada alta o
                # baja y movería la huella del hallazgo, devolviendo a Pendiente uno
                # ya silenciado sin que el problema haya cambiado.
                datos={
                    'tarjeta_del_nomenclador': etiqueta,
                    'importe': 'Sin definir',
                },
                campo_formulario='importe',
            )


class ParametrosDeTarifaInvalidos(ReglaBase):
    """El fondo de tiempo o el porcentaje de horas extras no permiten calcular.

    Son los dos parámetros de Configuración de los que sale la tarifa horaria y la
    de horas extras de TODOS los trabajadores (`contratos/tarifas.py`) y el fondo
    que congela cada Pre-Nómina. Desde el 23-10-2026 no hay valor fijo de respaldo
    en el código: si faltan, la tarifa queda vacía y la Pre-Nómina no se crea.
    """

    codigo = 'CFG-004'
    nombre = 'Parámetros del cálculo de la tarifa sin definir o inválidos'
    modulo = MODULO_CONFIGURACION
    criticidad = CRITICIDAD_CRITICA
    modelo = 'configuracion.Configuracion'

    descripcion = (
        'Comprueba que el fondo de tiempo para el cálculo de la tarifa sea mayor que '
        'cero y que el porcentaje de horas extras esté entre 0 y 1 (0.25 = 25 %).')
    causa_probable = (
        'El valor se cambió fuera del formulario (Admin de Django, importación o '
        'restauración de una copia), o el porcentaje se escribió como «25» en vez '
        'de «0.25».')
    impacto = (
        'Sin fondo de tiempo no hay tarifa horaria ni de horas extras en ninguna '
        'pantalla y no se puede crear la Pre-Nómina. Con un porcentaje mayor que 1, '
        'las horas extras salen multiplicadas (con «25», por 26).')
    solucion = (
        'Abra Configuración → Parámetros Generales y corrija el fondo de tiempo o el '
        'porcentaje de horas extras.')

    def ejecutar(self, contexto):
        fila = (self.obtener_modelo()._default_manager
                .values('id', 'fondo_tiempo_calc_tarif', 'porcentaje_horas_extras').first())
        if fila is None:
            return  # Lo reporta CFG-001.

        fondo = fila.get('fondo_tiempo_calc_tarif')
        if fondo is None or fondo <= 0:
            yield HallazgoDetectado(
                object_id=str(fila['id']), clave_extra='fondo',
                titulo='El fondo de tiempo para el cálculo de la tarifa no es válido',
                detalle=(f'El fondo de tiempo vale {fondo if fondo is not None else "vacío"}: '
                         'debe ser mayor que cero para poder calcular la tarifa horaria.'),
                datos={'parametro': 'Fondo de tiempo', 'valor': str(fondo)},
                campo_formulario='fondo_tiempo_calc_tarif',
            )

        porcentaje = fila.get('porcentaje_horas_extras')
        if porcentaje is None or not (0 <= porcentaje <= 1):
            yield HallazgoDetectado(
                object_id=str(fila['id']), clave_extra='porcentaje',
                titulo='El porcentaje de horas extras no es válido',
                detalle=(f'El porcentaje de horas extras vale '
                         f'{porcentaje if porcentaje is not None else "vacío"}: debe ser una '
                         'fracción entre 0 y 1 (0.25 para un 25 %).'),
                datos={'parametro': 'Porcentaje de horas extras', 'valor': str(porcentaje)},
                campo_formulario='porcentaje_horas_extras',
            )


class EscalaSalarialIncompleta(ReglaBase):
    """Un grupo escala en uso no tiene en la escala los importes que necesita.

    SAL-002 ya avisa contrato por contrato («sin salario calculable»); esta regla
    señala la CAUSA en Parámetros Generales, una sola vez por grupo, para quien puede
    arreglarla: el Administrador que mantiene la escala salarial.
    """

    codigo = 'CFG-005'
    nombre = 'Escala salarial sin los importes que usan los contratos'
    modulo = MODULO_CONFIGURACION
    criticidad = CRITICIDAD_CRITICA
    modelo = 'nomencladores.NGrupoEscala'

    descripcion = (
        'Busca grupos escala con contratos de salario dinámico cuyo importe no está '
        'en la escala salarial: el de Cuadros para los cargos de Cuadro, o el de su '
        'rol y tridente para los demás.')
    causa_probable = (
        'El grupo se creó o se editó en la escala sin completar todos sus importes, o '
        'se asignó un cargo a un grupo (o un rol a un cargo) que la escala no tiene '
        'previsto.')
    impacto = (
        'Esos trabajadores aparecen sin salario en las pantallas, los informes, el '
        'Word del contrato y la Pre-Nómina.')
    solucion = (
        'Abra Configuración → Parámetros Generales → Salarios y complete los '
        'importes del grupo que se indican abajo.')

    def ejecutar(self, contexto):
        from django.apps import apps

        CAlta = apps.get_model('contratos', 'CAlta')
        NSalario = apps.get_model('nomencladores', 'NSalario')
        NCargo = apps.get_model('nomencladores', 'NCargo')

        escala = set(NSalario.objects.filter(monto__gt=0).values_list(
            'grupo_escala_id', 'rol_id', 'tridente_id'))
        usados = (CAlta.objects
                  .filter(tipo_salario='DIN', cargo__ncargo__grupo_escala__isnull=False)
                  .values_list('cargo__ncargo__grupo_escala_id', 'cargo__ncargo__grupo_escala__nivel',
                               'cargo__ncargo__cat_ocupacional', 'cargo__rol_id',
                               'cargo__rol__tipo', 'tridente_id', 'tridente__tipo')
                  .distinct())

        faltan = {}
        for grupo, nivel, categoria, rol, rol_tipo, tridente, tridente_tipo in usados:
            if categoria in NCargo.CATEGORIAS_CUADRO:
                if (grupo, rol, None) in escala or (grupo, None, None) in escala:
                    continue
                falta = 'Cuadros'
            else:
                # Sin rol o sin tridente el problema es del cargo o del contrato
                # (lo avisan SAL-002 y la regla de cargo sin rol), no de la escala.
                if rol is None or tridente is None or (grupo, rol, tridente) in escala:
                    continue
                falta = f'{rol_tipo} · Tridente {tridente_tipo}'
            faltan.setdefault((grupo, nivel), set()).add(falta)

        for (grupo, nivel), combinaciones in sorted(faltan.items(), key=lambda x: x[0][1]):
            lista = ', '.join(sorted(combinaciones))
            yield HallazgoDetectado(
                object_id=str(grupo),
                titulo=f'Grupo {nivel}: faltan importes en la escala salarial',
                detalle=(f'Hay contratos del grupo {nivel} que necesitan estos importes y la '
                         f'escala no los tiene: {lista}.'),
                datos={'grupo_escala': nivel, 'importes_que_faltan': lista},
            )
