"""Días e Importe de la Misión editados desde el informe de Misiones Internacionales.

El informe deja retocar Días e Importe de varios trabajadores con doble clic. Esos
valores pueden acabar en dos sitios distintos, y este módulo atiende a los dos:

* **En una exportación** (PDF, Word o Excel), sin tocar la base de datos. La
  pantalla manda los valores que tiene y el documento sale con ellos, avisando
  en letra pequeña de que no coinciden con lo guardado.
* **En los contratos**, al pulsar «Guardar». Aquí sí se escribe: con los permisos
  del formulario de contrato, comprobando que nadie haya cambiado el dato desde
  que se abrió la pantalla y dejando constancia en Auditoría.

Convención que recorre todo el módulo: el valor vacío (`None`) NO es lo mismo
que 0. Vacío significa «sin registrar» y así se guarda; en pantalla y en los
documentos se pinta como 0, pero Subsanación (CTR-021) lo sigue reclamando.
"""

from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from auditoria.models import AccionAuditoria
from auditoria.registro_automatico import sin_auditoria_automatica
from auditoria.servicios import registrar as registrar_auditoria
from contratos.models import CAlta
from solicitudes.integracion import _fuera_de_alcance, requiere_solicitud
from solicitudes.operaciones import definicion_de

DIAS_MAXIMO = 9999
IMPORTE_MAXIMO = Decimal('9999999.99')

NOTA_VALORES_MANUALES = (
    'Este documento contiene valores de Días o Importe modificados manualmente '
    'que no coinciden con los guardados en la base de datos.')


class ValorInvalido(ValueError):
    """Un Día o Importe que no se puede aceptar. El mensaje va al usuario."""


# --------------------------------------------------------------------------
# Lectura y validación de un valor suelto
# --------------------------------------------------------------------------

def _es_vacio(valor):
    return valor is None or (isinstance(valor, str) and not valor.strip())


def leer_dias(valor):
    """`'15'` → 15, `''` → None. Lanza `ValorInvalido` con el motivo en español."""
    if _es_vacio(valor):
        return None
    texto = str(valor).strip()
    if not texto.lstrip('-').isdigit():
        raise ValorInvalido('Los días deben ser un número entero.')
    dias = int(texto)
    if dias < 0:
        raise ValorInvalido('Los días no pueden ser negativos.')
    if dias > DIAS_MAXIMO:
        raise ValorInvalido('Los días admiten como máximo %d.' % DIAS_MAXIMO)
    return dias


def leer_importe(valor):
    """`'1250.5'` → Decimal('1250.50'), `''` → None. Admite coma decimal."""
    if _es_vacio(valor):
        return None
    texto = str(valor).strip().replace(',', '.')
    try:
        importe = Decimal(texto)
    except InvalidOperation:
        raise ValorInvalido('El importe debe ser un número.')
    if not importe.is_finite():
        raise ValorInvalido('El importe debe ser un número.')
    if importe < 0:
        raise ValorInvalido('El importe no puede ser negativo.')
    if importe != importe.quantize(Decimal('0.01')):
        raise ValorInvalido('El importe admite como máximo 2 decimales.')
    if importe > IMPORTE_MAXIMO:
        raise ValorInvalido(
            'El importe admite como máximo 7 cifras enteras y 2 decimales.')
    return importe.quantize(Decimal('0.01'))


def texto_dias(dias):
    """Cómo se compara y se transmite un valor de días: `''` si está vacío."""
    return '' if dias is None else str(int(dias))


def texto_importe(importe):
    return '' if importe is None else '%.2f' % Decimal(importe)


# --------------------------------------------------------------------------
# Exportaciones con los valores de la pantalla
# --------------------------------------------------------------------------

def leer_valores_manuales(datos):
    """`{expediente: {'dias': .., 'importe': ..}}` validado, desde el JSON del POST.

    Una entrada mal formada se descarta entera en vez de tumbar la exportación:
    la pantalla ya valida al escribir, y si algo llega roto es preferible que el
    documento salga con el dato de la base de datos a que no salga.
    """
    valores = {}
    if not isinstance(datos, dict):
        return valores
    for expediente, entrada in datos.items():
        if not isinstance(entrada, dict):
            continue
        try:
            valores[str(expediente)] = {
                'dias': leer_dias(entrada.get('dias')),
                'importe': leer_importe(entrada.get('importe')),
            }
        except ValorInvalido:
            continue
    return valores


def aplicar_valores_manuales(misiones_por_unidad, valores):
    """Pone en las filas del informe los valores de la pantalla.

    Devuelve True si alguno difiere de lo guardado: es lo que decide si el
    documento lleva la nota de valores manuales. Solo toca a los trabajadores
    que ya están en el informe; un expediente ajeno que llegue en el POST no
    añade a nadie.
    """
    hay_diferencias = False
    for unidad in misiones_por_unidad:
        for trabajador in unidad['trabajadores']:
            nuevo = valores.get(str(trabajador['expediente']))
            if nuevo is None:
                continue
            if (nuevo['dias'] != trabajador['dias']
                    or nuevo['importe'] != trabajador['importe']):
                hay_diferencias = True
            trabajador['dias'] = nuevo['dias']
            trabajador['importe'] = nuevo['importe']
    return hay_diferencias


def importe_total(misiones_por_unidad):
    """Suma de importes; el vacío cuenta como 0."""
    return sum((t['importe'] or Decimal('0')
                for unidad in misiones_por_unidad
                for t in unidad['trabajadores']), Decimal('0'))


# --------------------------------------------------------------------------
# Guardado en los contratos
# --------------------------------------------------------------------------

class ErrorDeGuardado(Exception):
    """No se guardó nada. `errores` lista los motivos, uno por trabajador."""

    def __init__(self, mensaje, errores=None, actuales=None):
        super().__init__(mensaje)
        self.errores = errores or []
        # Valores que tiene ahora la base de datos para los trabajadores en
        # conflicto, para que la pantalla actualice su referencia.
        self.actuales = actuales or {}


def _leer_cambio(cambio):
    expediente = str(cambio.get('expediente') or '').strip()
    if not expediente:
        raise ValorInvalido('Falta el expediente del trabajador.')
    return (expediente,
            leer_dias(cambio.get('dias')),
            leer_importe(cambio.get('importe')),
            leer_dias(cambio.get('dias_original')),
            leer_importe(cambio.get('importe_original')))


def _nombre(contrato):
    aspirante = contrato.aspirante
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido or '']
    return ' '.join(p for p in partes if p).strip()


def _unidad(contrato):
    cargo = contrato.cargo
    departamento = cargo.departamento if cargo else None
    return departamento.unidad_organizativa if departamento else None


def _descriptor(contrato, antes, despues):
    """«Misión de Ana Pérez: Días 10 → 15; Importe 0.00 → 350.00 (desde …)»."""
    def mostrar(valor):
        return 'vacío' if valor in (None, '') else valor

    partes = []
    if antes['mision_dias'] != despues['mision_dias']:
        partes.append('Días %s → %s' % (
            mostrar(antes['mision_dias']), mostrar(despues['mision_dias'])))
    if antes['mision_importe'] != despues['mision_importe']:
        partes.append('Importe %s → %s' % (
            mostrar(antes['mision_importe']), mostrar(despues['mision_importe'])))
    return 'Misión de %s: %s (desde el informe de Misiones Internacionales)' % (
        _nombre(contrato), '; '.join(partes))


def guardar_cambios(usuario, cambios):
    """Guarda Días e Importe de varios contratos. Todo o nada.

    `cambios` es la lista que manda la pantalla: por trabajador, los valores
    nuevos y los que tenía la base de datos cuando se abrió el informe.

    Se rechaza el lote entero —y no se guarda ninguno— si algún trabajador:
    no existe o ya no está en misión, queda fuera de las unidades de un
    Moderador, trae un valor inválido, o cambió en la base de datos desde que se
    abrió la pantalla (otro usuario lo modificó mientras tanto). Guardar solo una
    parte dejaría al usuario sin saber bien qué quedó grabado y qué no.

    El Moderador guarda directo, sin Solicitud: `mision_dias` y `mision_importe`
    son `campos_libres` de `contrato_upd`, igual que en el formulario del
    contrato. Y con la misma restricción de unidad que aplica ese formulario.

    Devuelve `{expediente: {'dias': '15', 'importe': '350.00'}}` con lo guardado.
    """
    if not isinstance(cambios, list) or not cambios:
        raise ErrorDeGuardado('No hay cambios que guardar.')

    errores = []
    leidos = {}
    for cambio in cambios:
        if not isinstance(cambio, dict):
            errores.append('Se recibió un cambio con un formato no válido.')
            continue
        try:
            expediente, dias, importe, dias_orig, importe_orig = _leer_cambio(cambio)
        except ValorInvalido as error:
            etiqueta = cambio.get('nombre') or cambio.get('expediente') or '¿?'
            errores.append('%s: %s' % (etiqueta, error))
            continue
        leidos[expediente] = (dias, importe, dias_orig, importe_orig)
    if errores:
        raise ErrorDeGuardado('Hay valores que no se pueden guardar.', errores)

    definicion = definicion_de('contrato_upd')
    es_moderador = requiere_solicitud(usuario)

    with transaction.atomic():
        # `select_for_update` bloquea las filas hasta el final de la transacción:
        # entre comprobar el valor original y escribir el nuevo no puede colarse
        # otro guardado.
        contratos = {
            c.no_expediente: c
            for c in CAlta.objects
            .select_for_update(of=('self',))
            .select_related('aspirante', 'cargo__departamento__unidad_organizativa')
            .filter(no_expediente__in=list(leidos))
        }

        actuales = {}
        for expediente, (dias, importe, dias_orig, importe_orig) in leidos.items():
            contrato = contratos.get(expediente)
            if contrato is None:
                errores.append('Expediente %s: el contrato ya no existe.' % expediente)
                continue
            nombre = _nombre(contrato)
            if not contrato.mision:
                errores.append('%s: el contrato ya no está en misión.' % nombre)
                continue
            if es_moderador and _fuera_de_alcance(usuario, definicion, contrato, {}):
                errores.append('%s: está fuera de su Unidad Organizativa asignada.' % nombre)
                continue
            if contrato.mision_dias != dias_orig or contrato.mision_importe != importe_orig:
                errores.append(
                    '%s: otro usuario modificó sus datos de misión mientras usted '
                    'editaba (ahora tiene %s días y un importe de %s).' % (
                        nombre, contrato.mision_dias if contrato.mision_dias is not None else 'vacío',
                        texto_importe(contrato.mision_importe) or 'vacío'))
                actuales[expediente] = {
                    'dias': texto_dias(contrato.mision_dias),
                    'importe': texto_importe(contrato.mision_importe),
                }
        if errores:
            raise ErrorDeGuardado(
                'No se guardó ningún cambio.', errores, actuales)

        tipo_contrato = ContentType.objects.get_for_model(CAlta)
        guardados = {}
        for expediente, (dias, importe, _dias_orig, _importe_orig) in leidos.items():
            contrato = contratos[expediente]
            antes = {'mision_dias': contrato.mision_dias,
                     'mision_importe': texto_importe(contrato.mision_importe) or None}
            despues = {'mision_dias': dias,
                       'mision_importe': texto_importe(importe) or None}
            guardados[expediente] = {'dias': texto_dias(dias),
                                     'importe': texto_importe(importe)}
            if antes == despues:
                continue

            contrato.mision_dias = dias
            contrato.mision_importe = importe
            # `update_fields` a propósito: `CAlta.save()` retoca otros campos en
            # memoria (el tridente, por ejemplo) y aquí solo se ha pedido cambiar
            # la misión. `updated_by`/`updated_at` los rellena `Base.save()`.
            # En pausa el registro automático: el evento se escribe justo debajo,
            # con la descripción del informe de origen.
            with sin_auditoria_automatica():
                contrato.save(update_fields=[
                    'mision_dias', 'mision_importe', 'updated_by', 'updated_at'])

            registrar_auditoria(
                usuario=usuario, accion=AccionAuditoria.MODIFICAR, modulo='contratos',
                content_type=tipo_contrato, object_id=contrato.pk,
                datos_antes=antes, datos_despues=despues,
                descriptor=_descriptor(contrato, antes, despues),
                unidad=_unidad(contrato))
    return guardados
