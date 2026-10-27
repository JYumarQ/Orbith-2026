"""Borrar y guardar nomencladores sin errores técnicos ni pérdidas en cadena (3.8.2).

Errores que motivaron este módulo (27-10-2026):

* Borrar un nomenclador en uso (el Tridente II, que usan dos contratos) devolvía un
  error 500 en HTML y la pantalla, que esperaba JSON, decía «Unexpected token».
* Borrar uno sin contratos (el Tridente III) se llevaba en cadena sus 66 importes de
  la escala salarial sin avisar.

Decisión del usuario: NUNCA se borra en cadena. Si algo usa el registro o depende
de él, no se borra y un mensaje dice qué y cuántos. Los modelos llevan PROTECT o
RESTRICT por si se borra desde otro sitio; aquí se cuentan los usos antes de
intentarlo para redactar el mensaje completo.
"""
import functools
import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import ProtectedError, RestrictedError
from django.http import Http404, JsonResponse

logger = logging.getLogger(__name__)

#: Cómo se nombra en pantalla lo que usa un nomenclador: (singular, plural).
NOMBRES = {
    'contratos.calta': ('contrato', 'contratos'),
    'contratos.cbaja': ('baja', 'bajas'),
    'nomencladores.nsalario': ('importe de la escala salarial', 'importes de la escala salarial'),
    'strorganizativa.cargoplantilla': ('cargo de la plantilla', 'cargos de la plantilla'),
    'bolsa.aspirante': ('persona', 'personas'),
    'nomencladores.ncargo': ('cargo del nomenclador', 'cargos del nomenclador'),
    'strorganizativa.unidadorganizativa': ('unidad organizativa', 'unidades organizativas'),
    'nomencladores.nmunicipio': ('municipio', 'municipios'),
    'nomencladores.nmotivocontrato': ('motivo de contrato', 'motivos de contrato'),
    'nomencladores.nfamiliacargo': ('familia de cargos', 'familias de cargos'),
    'nomencladores.ncondicionlaboralanormal': ('condición laboral', 'condiciones laborales'),
    'nomencladores.ntipounidadorganizativa': ('tipo de unidad', 'tipos de unidad'),
    'nomencladores.ngrupoescala': ('grupo escala', 'grupos escala'),
    'configuracion.configuracion': ('los Parámetros Generales', 'los Parámetros Generales'),
}

#: Qué hacer para poder borrarlo, según lo que lo usa.
CONSEJOS = {
    'nomencladores.nsalario': 'Borre primero sus importes en Parámetros → Escala salarial.',
    'nomencladores.ngrupoescala': 'Quítelo primero de los grupos escala que lo llevan.',
    'configuracion.configuracion': 'Elija primero otra provincia en Parámetros Generales.',
}

ERROR_GENERICO = ('No se pudo completar la operación. Inténtelo de nuevo y, si se repite, '
                  'avise al administrador de Orbith.')


def _contar(etiqueta, cantidad, modelo):
    singular, plural = NOMBRES.get(etiqueta, (modelo._meta.verbose_name, modelo._meta.verbose_name_plural))
    if etiqueta == 'configuracion.configuracion':
        return singular
    return f'{cantidad} {singular if cantidad == 1 else plural}'


def _enumerar(partes):
    return partes[0] if len(partes) == 1 else ', '.join(partes[:-1]) + ' y ' + partes[-1]


#: Relaciones que NO impiden borrar porque su pantalla lo hace a propósito: una
#: familia de cargos se borra con sus cargos dentro y estos vuelven a «Sin
#: Clasificar» (la pantalla lo avisa); los cargos no se pierden.
PERMITIDAS = {('nomencladores.nfamiliacargo', 'nomencladores.ncargo')}


def _usos(objeto):
    """[(etiqueta, cantidad, modelo)] de TODO lo que apunta a `objeto`.

    Se cuenta cada relación inversa (claves foráneas, uno a uno y varios a varios)
    en lugar de simular el borrado: el borrado de Django se para en el primer
    bloqueo y el mensaje diría solo una parte («66 importes de la escala») cuando
    también lo usan contratos.
    """
    propia = objeto._meta.label_lower
    usos = []
    for relacion in objeto._meta.related_objects:
        modelo = relacion.related_model
        etiqueta = modelo._meta.label_lower
        if (propia, etiqueta) in PERMITIDAS:
            continue
        if relacion.many_to_many:
            cantidad = getattr(objeto, relacion.get_accessor_name()).count()
        else:
            cantidad = modelo._base_manager.filter(**{relacion.field.name: objeto}).count()
        if cantidad:
            usos.append((etiqueta, cantidad, modelo))
    # Varias relaciones con el mismo modelo (la CLA y las dos nocturnidades del
    # contrato) se dicen juntas: «3 contratos», no «contratos» tres veces.
    juntos = {}
    for etiqueta, cantidad, modelo in usos:
        anterior = juntos.get(etiqueta, (0, modelo))[0]
        juntos[etiqueta] = (anterior + cantidad, modelo)
    return [(etiqueta, cantidad, modelo) for etiqueta, (cantidad, modelo) in juntos.items()]


def motivo_para_no_borrar(objeto):
    """Texto que explica por qué no se puede borrar `objeto`, o '' si se puede."""
    usos = _usos(objeto)
    if not usos:
        return ''
    partes = [_contar(etiqueta, cantidad, modelo) for etiqueta, cantidad, modelo in usos]
    consejos = [CONSEJOS[e] for e, _, _ in usos if e in CONSEJOS]
    texto = f'No se puede eliminar «{objeto}»: lo usan {_enumerar(partes)}.'
    return ' '.join([texto] + consejos)


def borrar_o_explicar(objeto):
    """Borra `objeto` o devuelve el motivo en JSON (409), con el formato que leen todas
    las pantallas de Nomencladores: `{'success': False, 'error': ...}`."""
    motivo = motivo_para_no_borrar(objeto)
    if motivo:
        return JsonResponse({'success': False, 'error': motivo}, status=409)
    try:
        with transaction.atomic():
            objeto.delete()
    except (ProtectedError, RestrictedError):
        # Alguien empezó a usarlo entre la comprobación y el borrado.
        return JsonResponse({'success': False, 'error': motivo_para_no_borrar(objeto)
                             or 'No se puede eliminar: está en uso.'}, status=409)
    return JsonResponse({'success': True})


def texto_de(error):
    """Los mensajes de un ValidationError, en una sola frase."""
    if hasattr(error, 'message_dict'):
        return ' '.join(m for mensajes in error.message_dict.values() for m in mensajes)
    return ' '.join(error.messages)


def json_seguro(vista):
    """Red de seguridad de las vistas JSON de Nomencladores (decisión del 27-10-2026).

    Ningún fallo llega a la pantalla como error técnico: una validación devuelve su
    mensaje (400), un registro en uso explica qué lo usa (409) y cualquier otro error
    se anota en el registro del servidor y devuelve un aviso comprensible (500).
    """
    @functools.wraps(vista)
    def envoltura(request, *args, **kwargs):
        try:
            return vista(request, *args, **kwargs)
        except (Http404, PermissionDenied):
            raise  # «No existe» y «sin permiso» siguen siendo lo que son.
        except ValidationError as error:
            return JsonResponse({'success': False, 'error': texto_de(error)}, status=400)
        except (ProtectedError, RestrictedError):
            return JsonResponse({'success': False, 'error': 'No se puede eliminar: está en uso.'}, status=409)
        except Exception:
            logger.exception('Error en %s', getattr(vista, '__name__', vista))
            return JsonResponse({'success': False, 'error': ERROR_GENERICO}, status=500)
    return envoltura


def guardar_validado(objeto, **campos):
    """Asigna `campos`, valida con las reglas del modelo (también «sin repetidos») y
    guarda. Lanza ValidationError, que `json_seguro` convierte en mensaje."""
    for campo, valor in campos.items():
        setattr(objeto, campo, valor)
    objeto.full_clean()
    objeto.save()
    return objeto
