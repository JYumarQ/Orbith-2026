"""Registro automático en Auditoría de crear, editar y eliminar.

Hasta octubre de 2026 solo escribían en Auditoría Solicitudes, el Admin de Django y
algún proceso suelto: lo que un Administrador hacía desde los formularios normales
(contratos, aspirantes, estructura, nomencladores, movimientos) no dejaba rastro.

En vez de añadir una llamada en cada una de las ~80 vistas que escriben, aquí se
escucha a Django una sola vez por modelo (señales `pre_save`/`post_save` y
`pre_delete`/`post_delete`). Así queda cubierta cualquier vista, la de hoy y la que
se añada mañana.

Cómo se decide qué se registra:

* **Modificación**: justo antes de guardar se lee el registro de la base de datos
  (una consulta por clave primaria, solo al guardar; las lecturas no pagan nada) y
  después se comparan campo a campo. Solo se guardan los campos que cambiaron; si
  no cambió ninguno, no hay evento.
* **Creación**: los campos con valor del registro nuevo.
* **Eliminación**: la fotografía completa del registro, tomada antes de borrarlo.
  Lo que se borra en cascada (por ejemplo, los movimientos de un aspirante
  eliminado) no genera eventos propios: es consecuencia del borrado principal.
* Los valores se guardan **legibles y congelados**: la etiqueta del campo («Días de
  misión», no `mision_dias`) y el texto del valor («Especialista B», no `37`). Así
  el evento se entiende aunque el registro relacionado cambie o desaparezca.

Cuándo NO se registra automáticamente (`sin_auditoria_automatica()`):

* Donde el cambio ya se audita a mano con más contexto: la aprobación de una
  Solicitud, el alta, la baja y el movimiento de nómina de un contrato, la escala
  salarial o el guardado desde el informe de Misiones.
* Los cambios **derivados** que Orbith hace por su cuenta como consecuencia de otro
  (el estado del aspirante al contratarlo, el recuento de plazas del cargo, el
  movimiento de alta que se crea solo...). El evento principal ya los explica.
  Para esto existe el alias `cambios_derivados()`, que hace lo mismo pero se lee
  mejor en el código que lo usa.

Limitación conocida: las actualizaciones masivas con `QuerySet.update()` no pasan
por las señales de Django y no se registran (por ejemplo, el corrimiento automático
del «orden en informe» al insertar un cargo). Son efectos secundarios, no
ediciones de una persona.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Model, QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.utils import timezone

from auditoria.middleware import get_current_user
from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar as registrar_evento

logger = logging.getLogger(__name__)

#: Firma de los cambios que no vienen de ninguna persona (comandos, procesos).
NOMBRE_SISTEMA = 'Sistema'

#: Lo que se escribe cuando un campo está vacío.
VACIO = '—'

#: Campos de control que no dicen nada sobre el cambio en sí.
CAMPOS_TECNICOS = {'id', 'created_at', 'updated_at', 'created_by', 'updated_by'}


# --------------------------------------------------------------------------
# Pausa del registro automático
# --------------------------------------------------------------------------

# Un contador y no un sí/no: las pausas se pueden anidar (una vista en pausa que
# llama a un modelo que también se pone en pausa) y la exterior no debe
# reanudarse cuando termina la interior. `ContextVar`, igual que el middleware
# del usuario, para que una petición no contagie a otra.
_pausas = ContextVar('auditoria_registro_automatico_pausas', default=0)


@contextmanager
def sin_auditoria_automatica():
    """Apaga el registro automático mientras dura el bloque.

    Sirve como `with` y también como decorador (`@sin_auditoria_automatica()`).
    No afecta a `registrar()`, que es justo lo que usan quienes auditan a mano.
    """
    token = _pausas.set(_pausas.get() + 1)
    try:
        yield
    finally:
        _pausas.reset(token)


#: Mismo efecto; se usa para marcar los cambios que Orbith hace por su cuenta.
cambios_derivados = sin_auditoria_automatica


def _en_pausa():
    return _pausas.get() > 0


# --------------------------------------------------------------------------
# Qué modelos se auditan y cómo se describen
# --------------------------------------------------------------------------

def _id_unidad_de_departamento(departamento_id):
    if not departamento_id:
        return None
    Departamento = apps.get_model('strorganizativa', 'Departamento')
    return (Departamento.objects.filter(pk=departamento_id)
            .values_list('unidad_organizativa_id', flat=True).first())


def _id_unidad_de_cargo(cargo_id):
    if not cargo_id:
        return None
    CargoPlantilla = apps.get_model('strorganizativa', 'CargoPlantilla')
    return (CargoPlantilla.objects.filter(pk=cargo_id)
            .values_list('departamento__unidad_organizativa_id', flat=True).first())


def _nombre_de_aspirante(objeto):
    return str(objeto.aspirante) if objeto.aspirante_id else 'trabajador sin datos'


def _texto_contrato(objeto):
    return '%s (exp. %s)' % (_nombre_de_aspirante(objeto), objeto.no_expediente or VACIO)


def _texto_movimiento(objeto):
    return '%s de %s (exp. %s)' % (
        objeto.tipo_movimiento or 'Movimiento', _nombre_de_aspirante(objeto),
        objeto.no_expediente or VACIO)


_MOVIMIENTO = {
    'modulo': 'movimientos', 'nombre': 'Movimiento de nómina',
    'unidad': lambda o: o.unidad_nueva_fk_id or o.unidad_anterior_fk_id,
    'texto': _texto_movimiento,
    # Su borrado ya lo audita `contratos.models._al_eliminar_movimiento`, con el
    # cierre automático del ciclo del trabajador si se queda sin movimientos.
    'auditar_eliminacion': False,
}

MODELOS = {
    'contratos.CAlta': {
        'modulo': 'contratos', 'nombre': 'Contrato',
        # Calculado en cada guardado a partir de la escala salarial.
        'excluir': {'salario_actual'},
        'unidad': lambda o: _id_unidad_de_cargo(o.cargo_id),
        'texto': _texto_contrato,
    },
    'contratos.CBaja': {
        'modulo': 'contratos', 'nombre': 'Baja',
        'unidad': lambda o: _id_unidad_de_cargo(o.cargo_id),
        'texto': _texto_contrato,
    },
    'contratos.TMovimiento': _MOVIMIENTO,
    # Proxy de TMovimiento que usa el Admin: Django avisa con el proxy como emisor.
    'contratos.TMovimientoAgrupado': _MOVIMIENTO,
    'bolsa.Aspirante': {
        'modulo': 'aspirantes', 'nombre': 'Aspirante',
        'unidad': lambda o: o.unidad_organizativa_id,
    },
    'strorganizativa.UnidadOrganizativa': {
        'modulo': 'estructura', 'nombre': 'Unidad Organizativa',
        'unidad': lambda o: o.pk,
    },
    'strorganizativa.Departamento': {
        'modulo': 'estructura', 'nombre': 'Departamento',
        'unidad': lambda o: o.unidad_organizativa_id,
    },
    'strorganizativa.CargoPlantilla': {
        'modulo': 'estructura', 'nombre': 'Cargo de plantilla',
        # Los recalcula Orbith al contar los contratos (`refrescar_conteo_plazas`)
        # y al guardar (`activo = cant_aprobada > 0`).
        'excluir': {'cant_cubierta', 'activo'},
        'unidad': lambda o: _id_unidad_de_departamento(o.departamento_id),
        'texto': lambda o: '%s (%s)' % (o.ncargo, o.departamento),
    },
    # Permisos especiales de Moderadores (25-10-2026).
    'usuarios.PerfilPermisos': {'modulo': 'usuarios', 'nombre': 'Perfil de permisos', 'unidad': lambda o: None},
}

# `NSalario` no está: la escala salarial se borra y se recrea entera en cada
# edición, así que se audita a mano un solo evento por grupo
# (`nomencladores/views.py`).
#
# El nombre va aquí y no en `Meta.verbose_name` porque varios modelos tienen como
# nombre el técnico («NTridente», «NCausa Alta/Baja») y cambiarlo pediría migrar.
_NOMENCLADORES = {
    'NTridente': 'Tridente',
    'NRol': 'Rol de pago',
    'NGrupoEscala': 'Grupo escala',
    'NTipoFamilia': 'Tipo de familia',
    'NFamiliaCargo': 'Familia de cargos',
    'NCargo': 'Cargo (nomenclador)',
    'NNocturnidad': 'Nocturnidad',
    'NCondicionLaboralAnormal': 'Condición laboral anormal',
    'NProvincia': 'Provincia',
    'NMunicipio': 'Municipio',
    'NCausaAltaBaja': 'Causa de alta/baja',
    'NEspecialidad': 'Especialidad',
    'NNivelPreparacion': 'Nivel de preparación',
    'NTipoContrato': 'Tipo de contrato',
    'NMotivoContrato': 'Motivo de contrato',
    'NTipoUnidadOrganizativa': 'Tipo de unidad organizativa',
    'NImporteGradoCientifico': 'Importe por grado científico',
    'NPagoAdicional': 'Pago adicional',
}
for _modelo, _nombre in _NOMENCLADORES.items():
    MODELOS['nomencladores.' + _modelo] = {'modulo': 'nomencladores', 'nombre': _nombre}

#: Nombre legible de cada `modulo` para el filtro de la pantalla de Auditoría.
#: Los que no estén aquí se muestran tal cual, con la primera letra en mayúscula.
NOMBRES_DE_MODULO = {
    'solicitudes': 'Solicitudes',
    'contratos': 'Contratos',
    'movimientos': 'Movimientos de nómina',
    'aspirantes': 'Aspirantes',
    'estructura': 'Estructura Organizativa',
    'nomencladores': 'Nomencladores',
    'auditoria': 'Panel de administración',
    'usuarios': 'Usuarios y permisos',
}


def _config(modelo):
    return MODELOS.get(modelo._meta.label)


def es_auditado(modelo):
    """¿Los cambios de este modelo los registra ya este módulo?"""
    return _config(modelo) is not None


# --------------------------------------------------------------------------
# Valores legibles
# --------------------------------------------------------------------------

_campos_por_modelo = {}


def _campos(modelo):
    """Campos que se auditan, en orden de declaración. Se calculan una vez."""
    if modelo not in _campos_por_modelo:
        excluir = CAMPOS_TECNICOS | set((_config(modelo) or {}).get('excluir', ()))
        _campos_por_modelo[modelo] = [
            campo for campo in modelo._meta.concrete_fields
            if not campo.primary_key and campo.name not in excluir
        ]
    return _campos_por_modelo[modelo]


def _etiqueta(campo):
    texto = str(campo.verbose_name)
    return texto[:1].upper() + texto[1:]


def _normal(campo, valor):
    """El valor en su tipo de Python, para comparar sin falsos cambios
    (`'1250.5'` y `Decimal('1250.50')` son lo mismo; `''` y `None` también)."""
    if campo.get_internal_type() in ('FileField', 'ImageField'):
        valor = getattr(valor, 'name', valor)
    else:
        try:
            valor = campo.to_python(valor)
        except (ValidationError, TypeError, ValueError):
            pass
    return None if valor == '' else valor


def _texto(campo, valor):
    """Cómo se lee el valor en el detalle del evento."""
    if valor is None or valor == '':
        return VACIO
    if campo.is_relation:
        relacionado = campo.related_model._base_manager.filter(pk=valor).first()
        return str(relacionado) if relacionado is not None else '(id %s, ya no existe)' % valor
    if campo.flatchoices:
        return str(dict(campo.flatchoices).get(valor, valor))
    if isinstance(valor, bool):
        return 'Sí' if valor else 'No'
    if isinstance(valor, datetime):
        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.strftime('%d/%m/%Y %H:%M')
    if isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')
    if isinstance(valor, Decimal) and getattr(campo, 'decimal_places', None) is not None:
        return '%.*f' % (campo.decimal_places, valor)
    return str(valor)


def _legible(modelo, valores, solo=None, con_vacios=False):
    """`{etiqueta: texto}` a partir de `{attname: valor normalizado}`."""
    resultado = {}
    for campo in _campos(modelo):
        if solo is not None and campo.attname not in solo:
            continue
        valor = valores.get(campo.attname)
        if not con_vacios and valor in (None, False):
            continue
        clave = _etiqueta(campo)
        if clave in resultado:
            clave = '%s (%s)' % (clave, campo.name)
        resultado[clave] = _texto(campo, valor)
    return resultado


def _valores_de(instancia):
    return {campo.attname: _normal(campo, campo.value_from_object(instancia))
            for campo in _campos(type(instancia))}


def fotografia(instancia, con_vacios=False):
    """El registro tal y como está ahora, legible. Para auditar a mano."""
    return _legible(type(instancia), _valores_de(instancia), con_vacios=con_vacios)


# --------------------------------------------------------------------------
# Escritura del evento
# --------------------------------------------------------------------------

def _usuario():
    usuario = get_current_user()
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return None
    return usuario


def _descriptor(instancia, config):
    nombre = config.get('nombre') or _etiqueta_modelo(type(instancia))
    texto = config.get('texto', str)(instancia)
    return '%s «%s»' % (nombre, texto)


def _etiqueta_modelo(modelo):
    texto = str(modelo._meta.verbose_name)
    return texto[:1].upper() + texto[1:]


def _unidad(instancia, config):
    """La unidad como objeto sin consultar la base (basta con su id)."""
    calcular = config.get('unidad')
    unidad_id = calcular(instancia) if calcular else None
    if not unidad_id:
        return None
    UnidadOrganizativa = apps.get_model('strorganizativa', 'UnidadOrganizativa')
    return UnidadOrganizativa(pk=unidad_id)


def registrar(instancia, accion, antes=None, despues=None, descripcion='',
              object_id=None, unidad=False, descriptor=None):
    """Escribe un evento sobre `instancia`. Lo usan las señales y quien audita a mano.

    En una modificación o un movimiento de nómina solo se conservan las claves
    cuyo valor cambió. Una modificación sin cambios no se escribe (devuelve None);
    un movimiento sí, porque el movimiento en sí es el hecho auditado.
    `descripcion` antepone un texto al del evento («Proceso: Contrato «…»»).
    """
    antes, despues = dict(antes or {}), dict(despues or {})
    if accion in (AccionAuditoria.MODIFICAR, AccionAuditoria.MOVIMIENTO):
        cambiadas = {clave for clave in set(antes) | set(despues)
                     if antes.get(clave, VACIO) != despues.get(clave, VACIO)}
        if not cambiadas and accion == AccionAuditoria.MODIFICAR:
            return None
        antes = {clave: antes.get(clave, VACIO) for clave in cambiadas}
        despues = {clave: despues.get(clave, VACIO) for clave in cambiadas}

    config = _config(type(instancia)) or {}
    texto = descriptor or _descriptor(instancia, config)
    if descripcion:
        texto = '%s: %s' % (descripcion, texto)
    usuario = _usuario()
    return registrar_evento(
        usuario=usuario,
        usuario_nombre=None if usuario else NOMBRE_SISTEMA,
        accion=accion,
        content_type=ContentType.objects.get_for_model(type(instancia)),
        object_id=object_id if object_id is not None else instancia.pk,
        datos_antes=antes, datos_despues=despues,
        descriptor=texto[:200],
        unidad=_unidad(instancia, config) if unidad is False else unidad,
        modulo=config.get('modulo', 'auditoria'),
    )


# --------------------------------------------------------------------------
# Señales
# --------------------------------------------------------------------------

def _antes_de_guardar(sender, instance, raw=False, using=None, **kwargs):
    instance._auditoria_antes = None
    instance._auditoria_omitir = raw or _en_pausa()
    if instance._auditoria_omitir or instance._state.adding or instance.pk is None:
        return
    campos = _campos(sender)
    fila = (sender._base_manager.using(using).filter(pk=instance.pk)
            .values(*[campo.attname for campo in campos]).first())
    if fila is not None:
        instance._auditoria_antes = {
            campo.attname: _normal(campo, fila[campo.attname]) for campo in campos}


def _despues_de_guardar(sender, instance, created, update_fields=None, **kwargs):
    omitir = getattr(instance, '_auditoria_omitir', True)
    antes = getattr(instance, '_auditoria_antes', None)
    instance._auditoria_omitir, instance._auditoria_antes = True, None
    if omitir:
        return
    # Una auditoría que falla nunca debe tumbar el guardado real (mismo criterio
    # que `auditoria/admin_mixins.py`). `registrar_evento` va en su propio
    # punto de guardado, así que un error no deja la transacción inservible.
    try:
        despues = _valores_de(instance)
        if created or antes is None:
            registrar(instance, AccionAuditoria.CREAR,
                      despues=_legible(sender, despues))
            return
        cambiados = {attname for attname, valor in despues.items()
                     if antes.get(attname) != valor}
        if update_fields:
            nombres = set(update_fields)
            cambiados = {campo.attname for campo in _campos(sender)
                         if campo.attname in cambiados
                         and (campo.name in nombres or campo.attname in nombres)}
        if not cambiados:
            return
        registrar(instance, AccionAuditoria.MODIFICAR,
                  antes=_legible(sender, antes, solo=cambiados, con_vacios=True),
                  despues=_legible(sender, despues, solo=cambiados, con_vacios=True))
    except Exception:
        logger.exception('No se pudo registrar en Auditoría el guardado de %s %s.',
                         sender._meta.label, instance.pk)


def _es_borrado_principal(sender, instance, origin):
    """False si el registro cae en cascada por el borrado de otro."""
    if isinstance(origin, Model):
        return origin is instance
    if isinstance(origin, QuerySet):
        return origin.model._meta.concrete_model is sender._meta.concrete_model
    return True


def _antes_de_eliminar(sender, instance, origin=None, **kwargs):
    instance._auditoria_borrado = None
    config = _config(sender)
    if (_en_pausa() or not config.get('auditar_eliminacion', True)
            or not _es_borrado_principal(sender, instance, origin)):
        return
    try:
        # Todo se calcula ahora: después del borrado ya no se pueden leer las
        # relaciones de este registro.
        es_unidad = sender._meta.label == 'strorganizativa.UnidadOrganizativa'
        instance._auditoria_borrado = {
            'antes': fotografia(instance),
            'descriptor': _descriptor(instance, config),
            'object_id': instance.pk,
            # Una unidad borrada no puede ser la unidad de su propio evento.
            'unidad': None if es_unidad else _unidad(instance, config),
        }
    except Exception:
        logger.exception('No se pudo preparar la auditoría del borrado de %s %s.',
                         sender._meta.label, instance.pk)


def _despues_de_eliminar(sender, instance, **kwargs):
    borrado = getattr(instance, '_auditoria_borrado', None)
    instance._auditoria_borrado = None
    if not borrado:
        return
    try:
        registrar(instance, AccionAuditoria.ELIMINAR, antes=borrado['antes'],
                  object_id=borrado['object_id'], unidad=borrado['unidad'],
                  descriptor=borrado['descriptor'])
    except Exception:
        logger.exception('No se pudo registrar en Auditoría el borrado de %s %s.',
                         sender._meta.label, borrado['object_id'])


def conectar():
    """Engancha las señales. Lo llama `AuditoriaConfig.ready()` una vez."""
    for etiqueta in MODELOS:
        modelo = apps.get_model(etiqueta)
        uid = 'auditoria_automatica_%s' % etiqueta
        pre_save.connect(_antes_de_guardar, sender=modelo, dispatch_uid=uid + '_pre_save')
        post_save.connect(_despues_de_guardar, sender=modelo, dispatch_uid=uid + '_post_save')
        pre_delete.connect(_antes_de_eliminar, sender=modelo, dispatch_uid=uid + '_pre_delete')
        post_delete.connect(_despues_de_eliminar, sender=modelo, dispatch_uid=uid + '_post_delete')
