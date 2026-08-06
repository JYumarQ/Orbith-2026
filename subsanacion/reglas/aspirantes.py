"""Reglas de integridad de los datos personales de los trabajadores."""

from django.apps import apps
from django.db.models import F, Q

from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_BAJA,
    CRITICIDAD_MEDIA,
    MODULO_ASPIRANTES,
    TAMANO_LOTE,
)
from ..formato import referencia_trabajador
from .base import HallazgoDetectado, ReglaBase


class ReglaAspirantes(ReglaBase):
    abstracta = True
    modulo = MODULO_ASPIRANTES
    modelo = 'bolsa.Aspirante'

    COLUMNAS_BASE = (
        'id', 'nombre', 'papellido', 'sapellido', 'doc_identidad', 'estado',
        'unidad_organizativa_id',
    )

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_trabajador(
            fila.get('nombre'), fila.get('papellido'),
            fila.get('sapellido'), fila.get('doc_identidad'))
        return f'{referencia} · {sufijo}'


class CarnetConFormatoInvalido(ReglaAspirantes):
    codigo = 'ASP-001'
    nombre = 'Carnet de identidad con formato inválido'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Comprueba que el carnet de identidad tenga exactamente 11 dígitos y que su '
        'parte de fecha corresponda a una fecha real.')
    causa_probable = (
        'El carnet se escribió con espacios, guiones o letras, le faltan o le sobran '
        'dígitos, o se importó desde otra fuente sin validar.')
    impacto = (
        'Orbith calcula la fecha de nacimiento a partir del carnet, así que con un '
        'carnet inválido el trabajador se queda sin fecha de nacimiento y sin edad. '
        'Además el carnet es el identificador con el que se localiza a una persona en '
        'los documentos oficiales.')
    solucion = (
        'Abra el trabajador y corrija el carnet de identidad: 11 dígitos, sin espacios '
        'ni guiones. Al guardar, Orbith recalcula sola la fecha de nacimiento.')

    def ejecutar(self, contexto):
        Aspirante = self.obtener_modelo()

        # El formato se filtra en PostgreSQL: a Python solo llegan los que ya fallan.
        # Después se comprueba en Python si la fecha del carnet es real, reutilizando el
        # mismo método que usa el modelo para calcularla.
        candidatos = (self.base_queryset()
                      .exclude(doc_identidad__regex=r'^\d{11}$')
                      .values(*self.COLUMNAS_BASE)
                      .iterator(chunk_size=TAMANO_LOTE))

        for fila in candidatos:
            carnet = fila.get('doc_identidad') or ''
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra='formato',
                titulo=self.titulo_de(fila, f'carnet «{carnet}» no tiene 11 dígitos'),
                detalle=(
                    f'El carnet de identidad «{carnet}» no cumple el formato de 11 '
                    f'dígitos, así que Orbith no puede deducir la fecha de nacimiento.'),
                datos={
                    'carnet_registrado': carnet or 'Vacío',
                    'longitud': len(carnet),
                    'formato_esperado': '11 dígitos, sin espacios ni guiones',
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )

        # Con el formato correcto, la fecha que codifica puede seguir siendo imposible
        # (por ejemplo un mes 13 o un 31 de febrero).
        bien_formados = (self.base_queryset()
                         .filter(doc_identidad__regex=r'^\d{11}$')
                         .values(*self.COLUMNAS_BASE)
                         .iterator(chunk_size=TAMANO_LOTE))

        for fila in bien_formados:
            carnet = fila['doc_identidad']
            # Se reutiliza el staticmethod del propio modelo: es puro, no consulta la
            # base de datos, y así el criterio de interpretación del carnet sigue
            # viviendo en un solo sitio.
            if Aspirante._calcular_fecha_nacimiento(carnet) is not None:
                continue
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                clave_extra='fecha_imposible',
                titulo=self.titulo_de(
                    fila, f'carnet «{carnet}» codifica una fecha que no existe'),
                detalle=(
                    f'El carnet «{carnet}» tiene 11 dígitos, pero los primeros seis no '
                    f'forman una fecha válida, así que no se puede deducir la fecha de '
                    f'nacimiento.'),
                datos={
                    'carnet_registrado': carnet,
                    'fecha_que_codifica': f'{carnet[:2]}/{carnet[2:4]}/{carnet[4:6]} (inválida)',
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class FechaNacimientoDesincronizada(ReglaAspirantes):
    codigo = 'ASP-002'
    nombre = 'Fecha de nacimiento distinta a la del carnet'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Comprueba que la fecha de nacimiento guardada coincida con la que codifica el '
        'carnet de identidad.')
    causa_probable = (
        'La fecha de nacimiento no se escribe a mano: Orbith la calcula desde el carnet '
        'cada vez que se guarda el trabajador. Si no coincide es porque la fila se '
        'escribió sin pasar por el formulario, normalmente en una importación o en una '
        'actualización masiva.')
    impacto = (
        'La edad del trabajador sale mal en los informes, y la fecha de nacimiento es un '
        'dato que aparece en documentos oficiales. Además indica que esa fila se escribió '
        'saltándose las validaciones del modelo, así que puede tener más campos mal.')
    solucion = (
        'NO intente cambiar la fecha de nacimiento: no se puede editar, Orbith la '
        'recalcula sola. Compruebe que el carnet de identidad es el correcto y guarde el '
        'trabajador: al guardar, la fecha se recalcula desde el carnet. Si el carnet '
        'está mal, corrija el carnet.')

    def ejecutar(self, contexto):
        Aspirante = self.obtener_modelo()

        filas = (self.base_queryset()
                 .filter(doc_identidad__regex=r'^\d{11}$')
                 .values(*self.COLUMNAS_BASE, 'fecha_nacimiento')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            carnet = fila['doc_identidad']
            esperada = Aspirante._calcular_fecha_nacimiento(carnet)
            if esperada is None:
                # Carnet con fecha imposible: lo reporta ASP-001, no se duplica aquí.
                continue

            guardada = fila.get('fecha_nacimiento')
            if guardada == esperada:
                continue

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila,
                    f'nacimiento {guardada.strftime("%d/%m/%Y") if guardada else "vacío"} '
                    f'frente a {esperada.strftime("%d/%m/%Y")} según el carnet'),
                detalle=(
                    f'El carnet «{carnet}» corresponde al '
                    f'{esperada.strftime("%d/%m/%Y")}, pero la fecha de nacimiento '
                    f'guardada es '
                    f'{guardada.strftime("%d/%m/%Y") if guardada else "está vacía"}.'),
                datos={
                    'carnet_registrado': carnet,
                    'fecha_guardada': (
                        guardada.strftime('%d/%m/%Y') if guardada else 'Vacía'),
                    'fecha_segun_el_carnet': esperada.strftime('%d/%m/%Y'),
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class MunicipioDeOtraProvincia(ReglaAspirantes):
    codigo = 'ASP-003'
    nombre = 'Municipio que no pertenece a la provincia registrada'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Comprueba que el municipio del trabajador pertenezca de verdad a la provincia '
        'que tiene registrada.')
    causa_probable = (
        'El formulario valida esta coherencia, así que la fila se escribió sin pasar por '
        'él: una importación, una actualización masiva o un cambio directo en la base de '
        'datos. También puede ocurrir si se reasignó un municipio a otra provincia '
        'después de haber registrado al trabajador.')
    impacto = (
        'La dirección del trabajador es contradictoria, y los informes que agrupan por '
        'territorio lo cuentan en un lugar equivocado.')
    solucion = (
        'Abra el trabajador y elija de nuevo la provincia y el municipio, en ese orden: '
        'al seleccionar la provincia, la lista de municipios se limita a los que le '
        'corresponden.')

    def ejecutar(self, contexto):
        # Comparación entre dos columnas con F(): la hace PostgreSQL y a Python solo
        # llegan las filas incoherentes. Coste prácticamente nulo.
        filas = (self.base_queryset()
                 .exclude(municipio__provincia=F('provincia'))
                 .values(*self.COLUMNAS_BASE,
                         'municipio__nombre', 'provincia__nombre',
                         'municipio__provincia__nombre')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            municipio = fila.get('municipio__nombre') or '—'
            provincia = fila.get('provincia__nombre') or '—'
            provincia_real = fila.get('municipio__provincia__nombre') or '—'

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila,
                    f'municipio {municipio} no pertenece a {provincia}'),
                detalle=(
                    f'El trabajador tiene registrada la provincia «{provincia}» y el '
                    f'municipio «{municipio}», pero ese municipio pertenece a '
                    f'«{provincia_real}».'),
                datos={
                    'provincia_registrada': provincia,
                    'municipio_registrado': municipio,
                    'provincia_real_del_municipio': provincia_real,
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class SexoIncompatibleConCarnet(ReglaAspirantes):
    """Sexo registrado que no coincide con el que codifica el carnet de identidad.

    El criterio replica EXACTAMENTE la lógica que ya usa el formulario de aspirantes
    (`add_aspir.html` / `updt_aspir.html`, bloque «AUTOCOMPLETAR SEXO»): el décimo
    dígito del carnet (posición 9, contando desde 0) es par para Masculino e impar
    para Femenino. El formulario lo autocompleta y avisa con un mensaje NO bloqueante
    si el usuario lo cambia a mano, precisamente porque puede haber una razón legítima
    para que no coincida (así lo pidió el responsable del área). Por eso esta regla
    tiene criticidad Baja: es una comprobación de coherencia, no una violación segura.
    """

    codigo = 'ASP-004'
    nombre = 'Sexo no coincide con el que indica el carnet'
    criticidad = CRITICIDAD_BAJA

    descripcion = (
        'Compara el sexo registrado con el que codifica el décimo dígito del '
        'carnet de identidad (par = Masculino, impar = Femenino).')
    causa_probable = (
        'El formulario ya advierte de esta diferencia al escribirla (con un aviso '
        'que no bloquea el guardado), así que puede ser una corrección intencional '
        'del usuario o un error de captura sin corregir.')
    impacto = (
        'No es necesariamente un error: el sistema permite guardar un sexo '
        'distinto al que sugiere el carnet a propósito. Conviene revisarlo para '
        'confirmar que la diferencia es intencional y no un dato mal capturado.')
    solucion = (
        'Abra el trabajador y confirme que el sexo registrado es el correcto. Si '
        'fue un error de captura, corríjalo; si es una diferencia intencional, '
        'puede marcar este hallazgo como falso positivo.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(sexo__in=['M', 'F'], doc_identidad__regex=r'^\d{11}$')
                 .values(*self.COLUMNAS_BASE, 'sexo')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            carnet = fila['doc_identidad']
            digito10 = int(carnet[9])
            sexo_calculado = 'M' if digito10 % 2 == 0 else 'F'
            sexo_registrado = fila.get('sexo')

            if sexo_registrado == sexo_calculado:
                continue

            etiqueta = {'M': 'Masculino', 'F': 'Femenino'}
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(
                    fila, f'sexo {etiqueta[sexo_registrado]} y el carnet sugiere '
                          f'{etiqueta[sexo_calculado]}'),
                detalle=(
                    f'El carnet «{carnet}» sugiere sexo {etiqueta[sexo_calculado]} '
                    f'(décimo dígito {digito10}), pero el trabajador tiene '
                    f'registrado {etiqueta[sexo_registrado]}.'),
                datos={
                    'sexo_registrado': etiqueta[sexo_registrado],
                    'sexo_segun_el_carnet': etiqueta[sexo_calculado],
                    'decimo_digito_del_carnet': digito10,
                },
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


def _campo_de_texto_vacio(valor):
    """Pura: la usan ejecutar() y evaluar_instancia() sin repetir el criterio.

    Vacío = None o cadena en blanco tras strip(). La reutilizan ASP-005 y ASP-006:
    ambas son «campo de contacto sin completar», con el mismo criterio de vacío.
    """
    return not (valor or '').strip()


class MovilPersonalVacio(ReglaAspirantes):
    codigo = 'ASP-005'
    nombre = 'Móvil personal sin completar'
    criticidad = CRITICIDAD_BAJA
    # Evaluable en caliente: O(1), solo un campo propio de la instancia.
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el trabajador tenga registrado un número de móvil personal.')
    causa_probable = (
        'El trabajador no facilitó un móvil al registrarse, o el dato llegará más '
        'adelante.')
    impacto = (
        'Sin un móvil registrado, Orbith no tiene ninguna vía rápida de contacto '
        'directo con el trabajador. No es obligatorio a nivel de formulario porque '
        'el dato puede llegar después del alta.')
    solucion = 'Abra el trabajador y complete el móvil personal.'

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle='El trabajador no tiene registrado ningún móvil personal.',
            datos={'movil_personal': 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='movil_personal',
        )

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(Q(movil_personal__isnull=True) | Q(movil_personal=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield self._hallazgo(
                str(fila['id']), self.titulo_de(fila, 'sin móvil personal'),
                fila.get('unidad_organizativa_id'))

    def evaluar_instancia(self, aspirante):
        if not _campo_de_texto_vacio(aspirante.movil_personal):
            return None
        return [self._hallazgo(str(aspirante.pk), 'Sin móvil personal')]


class DireccionVacia(ReglaAspirantes):
    codigo = 'ASP-006'
    nombre = 'Dirección sin completar'
    criticidad = CRITICIDAD_BAJA
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el trabajador tenga registrada una dirección.')
    causa_probable = (
        'El trabajador no facilitó su dirección al registrarse, o el dato llegará '
        'más adelante.')
    impacto = (
        'Sin dirección registrada, Orbith no tiene forma de localizar al '
        'trabajador fuera del contacto telefónico. No es obligatorio a nivel de '
        'formulario porque el dato puede llegar después del alta.')
    solucion = 'Abra el trabajador y complete la dirección.'

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle='El trabajador no tiene registrada ninguna dirección.',
            datos={'direccion': 'Vacía'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='direccion',
        )

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(Q(direccion__isnull=True) | Q(direccion=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield self._hallazgo(
                str(fila['id']), self.titulo_de(fila, 'sin dirección'),
                fila.get('unidad_organizativa_id'))

    def evaluar_instancia(self, aspirante):
        if not _campo_de_texto_vacio(aspirante.direccion):
            return None
        return [self._hallazgo(str(aspirante.pk), 'Sin dirección')]


class NivelEducativoSinCompletar(ReglaAspirantes):
    """Nivel educativo nunca completado.

    OJO: `nivel_educ` tiene la opción explícita `'SA'` («Sin Acreditar»), que es una
    respuesta legítima del formulario, no una falta de dato. Por eso la condición
    NO reutiliza `_campo_de_texto_vacio` (que trataría cualquier valor no vacío como
    válido, cosa que aquí sí sería correcto) sino que compara contra `None`/`''`
    explícitamente: `'SA'` nunca debe reportarse como vacío.
    """

    codigo = 'ASP-007'
    nombre = 'Nivel educativo sin completar'
    criticidad = CRITICIDAD_BAJA
    evaluable_en_caliente = True

    descripcion = (
        'Comprueba que el trabajador tenga registrado un nivel educativo (aunque '
        'sea «Sin Acreditar», que es una respuesta válida).')
    causa_probable = (
        'El campo se dejó sin seleccionar al registrar al trabajador.')
    impacto = (
        'El nivel educativo es un dato reportable; dejarlo sin completar (en vez '
        'de marcar explícitamente «Sin Acreditar») distorsiona cualquier informe '
        'que lo desglose.')
    solucion = 'Abra el trabajador y seleccione su nivel educativo.'

    def _hallazgo(self, object_id, titulo, unidad_organizativa_id=None):
        return HallazgoDetectado(
            object_id=object_id,
            titulo=titulo,
            detalle='El trabajador no tiene registrado ningún nivel educativo.',
            datos={'nivel_educ': 'Vacío'},
            unidad_organizativa_id=unidad_organizativa_id,
            campo_formulario='nivel_educ',
        )

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(Q(nivel_educ__isnull=True) | Q(nivel_educ=''))
                 .values(*self.COLUMNAS_BASE)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            yield self._hallazgo(
                str(fila['id']), self.titulo_de(fila, 'sin nivel educativo'),
                fila.get('unidad_organizativa_id'))

    def evaluar_instancia(self, aspirante):
        nivel_educ = aspirante.nivel_educ
        if nivel_educ is not None and nivel_educ != '':
            return None
        return [self._hallazgo(str(aspirante.pk), 'Sin nivel educativo')]
