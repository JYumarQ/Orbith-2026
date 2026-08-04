"""Reglas de calidad general de los datos: formato de teléfonos, nombres y correos.

A diferencia de las demás categorías, estas reglas no comprueban una relación de
negocio entre dos modelos: comprueban que el TEXTO de un campo tenga la forma que se
espera de él. Son las más baratas de calcular (una expresión regular sobre una sola
columna) y las más fáciles de corregir (el usuario ve el dato mal escrito de un
vistazo).
"""

import re

from django.db.models import F, Q
from django.db.models.functions import Upper

from ..constantes import CRITICIDAD_BAJA, CRITICIDAD_MEDIA, MODULO_CALIDAD, TAMANO_LOTE
from ..formato import referencia_trabajador
from .base import HallazgoDetectado, ReglaBase

# Letras minúsculas del español, incluidas las acentuadas y la eñe. Se declara
# explícita en vez de confiar en clases POSIX como [[:lower:]], cuyo comportamiento
# con acentos depende del `collation` configurado en PostgreSQL.
_MINUSCULAS_ES = 'a-záéíóúüñ'


class ReglaAspiranteTexto(ReglaBase):
    abstracta = True
    modulo = MODULO_CALIDAD
    modelo = 'bolsa.Aspirante'

    COLUMNAS = (
        'id', 'nombre', 'papellido', 'sapellido', 'doc_identidad',
        'unidad_organizativa_id',
    )

    @staticmethod
    def titulo_de(fila, sufijo):
        referencia = referencia_trabajador(
            fila.get('nombre'), fila.get('papellido'),
            fila.get('sapellido'), fila.get('doc_identidad'))
        return f'{referencia} · {sufijo}'


class MovilConFormatoInvalido(ReglaAspiranteTexto):
    codigo = 'CAL-001'
    nombre = 'Móvil personal con formato inválido'
    criticidad = CRITICIDAD_BAJA

    descripcion = (
        'El móvil personal debe empezar por «+53» seguido de exactamente 8 '
        'dígitos.')
    causa_probable = (
        'El dato se escribió sin el prefijo internacional, con espacios o '
        'guiones, o el formulario no exige todavía este formato (hoy no lo '
        'valida).')
    impacto = (
        'Un número sin el formato estándar puede fallar al usarse en '
        'integraciones futuras (SMS, WhatsApp) o simplemente dificultar '
        'contactar al trabajador si el número está incompleto.')
    solucion = (
        'Abra el trabajador y escriba el móvil como «+53» seguido de los 8 '
        'dígitos, sin espacios ni guiones.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .exclude(movil_personal__isnull=True)
                 .exclude(movil_personal='')
                 .exclude(movil_personal__regex=r'^\+53\d{8}$')
                 .values(*self.COLUMNAS, 'movil_personal')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            movil = fila['movil_personal']
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'móvil «{movil}» con formato inválido'),
                detalle=(
                    f'El móvil «{movil}» no tiene el formato «+53» seguido de 8 '
                    f'dígitos.'),
                datos={'movil_registrado': movil, 'formato_esperado': '+53XXXXXXXX'},
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class FijoConCaracteresNoNumericos(ReglaAspiranteTexto):
    codigo = 'CAL-002'
    nombre = 'Teléfono fijo con caracteres no numéricos'
    criticidad = CRITICIDAD_BAJA

    descripcion = (
        'El teléfono fijo debe contener solo dígitos. Al variar su longitud '
        'según la provincia y el municipio, no se exige un número exacto de '
        'cifras, solo que sean todas numéricas.')
    causa_probable = (
        'Se escribieron espacios, guiones o paréntesis al capturar el número.')
    impacto = (
        'Dificulta usar el número de forma automática (marcado, exportación) y '
        'es inconsistente con el resto de los teléfonos fijos registrados.')
    solucion = 'Abra el trabajador y deje solo los dígitos del teléfono fijo.'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .exclude(fijo_personal__isnull=True)
                 .exclude(fijo_personal='')
                 .exclude(fijo_personal__regex=r'^\d+$')
                 .values(*self.COLUMNAS, 'fijo_personal')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            fijo = fila['fijo_personal']
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=self.titulo_de(fila, f'fijo «{fijo}» con caracteres no numéricos'),
                detalle=f'El teléfono fijo «{fijo}» contiene algo que no es un dígito.',
                datos={'fijo_registrado': fijo, 'formato_esperado': 'Solo dígitos'},
                unidad_organizativa_id=fila.get('unidad_organizativa_id'),
            )


class EspaciosIrregularesEnElNombre(ReglaAspiranteTexto):
    codigo = 'CAL-003'
    nombre = 'Espacios irregulares en el nombre o los apellidos'
    criticidad = CRITICIDAD_BAJA

    descripcion = (
        'Busca espacios dobles o espacios al principio o al final del nombre '
        'y los apellidos.')
    causa_probable = (
        'Un espacio de más al escribir o pegar el dato desde otro documento.')
    impacto = (
        'Los espacios de más rompen las búsquedas por nombre exacto y hacen '
        'que el mismo nombre parezca distinto en dos registros diferentes.')
    solucion = 'Abra el trabajador y quite los espacios de más.'

    CAMPOS = ('nombre', 'papellido', 'sapellido')
    ETIQUETAS = {'nombre': 'nombre', 'papellido': 'primer apellido', 'sapellido': 'segundo apellido'}

    def ejecutar(self, contexto):
        condicion = Q()
        for campo in self.CAMPOS:
            # espacio doble, o al principio, o al final
            condicion |= Q(**{f'{campo}__regex': r'(  )|(^ )|( $)'})

        filas = (self.base_queryset()
                 .filter(condicion)
                 .values(*self.COLUMNAS)
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            for campo in self.CAMPOS:
                valor = fila.get(campo) or ''
                if valor != valor.strip() or '  ' in valor:
                    yield HallazgoDetectado(
                        object_id=str(fila['id']),
                        clave_extra=campo,
                        titulo=self.titulo_de(
                            fila, f'el {self.ETIQUETAS[campo]} tiene espacios de más'),
                        detalle=(
                            f'El campo «{self.ETIQUETAS[campo]}» tiene espacios '
                            f'dobles o al principio/final: «{valor}».'),
                        datos={'campo': self.ETIQUETAS[campo], 'valor_actual': repr(valor)},
                        unidad_organizativa_id=fila.get('unidad_organizativa_id'),
                    )


class CapitalizacionIrregularDelNombre(ReglaAspiranteTexto):
    codigo = 'CAL-004'
    nombre = 'Capitalización irregular del nombre o los apellidos'
    criticidad = CRITICIDAD_BAJA

    descripcion = (
        'Busca nombres o apellidos escritos completamente en mayúsculas, o que '
        'empiezan con una letra minúscula.')
    causa_probable = (
        'El dato se copió de un documento que lo tenía en mayúsculas (como el '
        'carnet de identidad), o se escribió sin usar mayúscula inicial.')
    impacto = (
        'Es un problema estético que afecta a los documentos oficiales '
        'impresos (contratos, certificaciones), donde el nombre debe aparecer '
        'con la capitalización habitual.')
    solucion = (
        'Abra el trabajador y escriba el nombre y los apellidos con la primera '
        'letra en mayúscula y el resto en minúscula.')

    CAMPOS = ('nombre', 'papellido', 'sapellido')
    ETIQUETAS = {'nombre': 'nombre', 'papellido': 'primer apellido', 'sapellido': 'segundo apellido'}

    def ejecutar(self, contexto):
        anotaciones = {f'{campo}_mayus': Upper(campo) for campo in self.CAMPOS}

        # Filtro empujado a SQL: candidatas son las filas donde ALGÚN campo coincide
        # con su propia versión en mayúsculas (posible «todo mayúsculas»; una letra
        # suelta como «A» también coincide, y se descarta después en Python) o
        # empieza por una minúscula. Solo estas llegan a Python; el resto —la
        # inmensa mayoría en un sistema sano— las descarta PostgreSQL.
        condicion = Q()
        for campo in self.CAMPOS:
            condicion |= Q(**{campo: F(f'{campo}_mayus')})
            condicion |= Q(**{f'{campo}__regex': rf'^[{_MINUSCULAS_ES}]'})

        filas = (self.base_queryset()
                 .annotate(**anotaciones)
                 .filter(condicion)
                 .values(*self.COLUMNAS, *[f'{c}_mayus' for c in self.CAMPOS])
                 .iterator(chunk_size=TAMANO_LOTE))

        empieza_minuscula = re.compile(rf'^[{_MINUSCULAS_ES}]')

        for fila in filas:
            for campo in self.CAMPOS:
                valor = (fila.get(campo) or '').strip()
                if len(valor) < 2:
                    continue

                todo_mayusculas = valor == fila.get(f'{campo}_mayus') and valor.lower() != valor
                minuscula_inicial = bool(empieza_minuscula.match(valor))

                if not todo_mayusculas and not minuscula_inicial:
                    continue

                motivo = ('está todo en mayúsculas' if todo_mayusculas
                          else 'empieza con minúscula')
                yield HallazgoDetectado(
                    object_id=str(fila['id']),
                    clave_extra=campo,
                    titulo=self.titulo_de(
                        fila, f'el {self.ETIQUETAS[campo]} {motivo}'),
                    detalle=f'El campo «{self.ETIQUETAS[campo]}» ({valor}) {motivo}.',
                    datos={'campo': self.ETIQUETAS[campo], 'valor_actual': valor,
                           'problema': motivo},
                    unidad_organizativa_id=fila.get('unidad_organizativa_id'),
                )


class CorreoDeUsuarioInvalido(ReglaBase):
    codigo = 'CAL-005'
    nombre = 'Correo del usuario con formato inválido'
    modulo = MODULO_CALIDAD
    criticidad = CRITICIDAD_MEDIA
    modelo = 'usuarios.CustomUser'

    descripcion = (
        'Comprueba que el correo electrónico de cada usuario tenga forma de '
        'correo. `EmailField` solo valida el formato al pasar por el '
        'formulario (`full_clean()`), no a nivel de base de datos, así que una '
        'fila escrita por otra vía puede dejarlo mal formado.')
    causa_probable = (
        'El usuario se creó o se actualizó por una vía que no pasó por el '
        'formulario y su validación (una consola de administración, una '
        'importación, un script).')
    impacto = (
        'Un correo mal formado no puede recibir ningún aviso del sistema '
        '(recuperación de contraseña, notificaciones), y ese usuario queda '
        'aislado de esas comunicaciones sin que nadie lo note hasta que las '
        'necesite.')
    solucion = 'Abra el usuario y corrija su correo electrónico.'

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .exclude(email='')
                 .exclude(email__regex=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
                 .values('id', 'username', 'email')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            correo = fila['email']
            usuario = fila.get('username') or f'Usuario {fila["id"]}'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{usuario} · correo «{correo}» con formato inválido',
                detalle=f'El correo «{correo}» no tiene la forma de una dirección válida.',
                datos={'correo_registrado': correo},
            )
