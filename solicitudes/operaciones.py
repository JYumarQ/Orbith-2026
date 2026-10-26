"""Catálogo de las operaciones que requieren aprobación de un Administrador.

Es la pieza que permite que un único modelo `Solicitud` y un único flujo de revisión
sirvan para operaciones sobre modelos distintos. Cada entrada declara lo poco que cambia
entre una operación y otra —qué modelo toca, qué formulario la valida, de dónde sale su
unidad organizativa y cómo se aplica al aprobar— y el resto del módulo no necesita saber
nada más. Mismo criterio que `subsanacion/enlaces.py::ENLACES_POR_MODELO`: el
conocimiento específico de cada modelo se concentra en un archivo en lugar de repartirse
en condicionales por las vistas.

La lista es EXACTAMENTE la aprobada por RRHH. No se añaden operaciones por iniciativa
propia: si una operación no está aquí, el Moderador no puede solicitarla y el formulario
correspondiente sigue comportándose como siempre.

Para añadir una operación futura basta con una entrada nueva y, si la operación nace de
un formulario existente, el desvío en su vista.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import F

from bolsa.forms import AspiranteForm
from bolsa.models import Aspirante
from contratos.forms import CAltaForm
from contratos.models import CAlta
from nomencladores.forms import NCargoForm
from nomencladores.models import NCargo
from solicitudes.models import AccionSolicitud
from strorganizativa.forms import (
    CargoPlantillaForm, DepartamentoForm, UnidadOrganizativaForm)
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa


# ----------------------------------------------------------------------
# Resolución de la unidad organizativa
# ----------------------------------------------------------------------
# Cada modelo llega a su unidad por un camino distinto, y en las operaciones de creación
# todavía no hay objeto: hay que deducirla de los datos propuestos. Por eso todos los
# resolutores reciben `(objeto, datos)` y usan el que tengan disponible.

def _sin_unidad(objeto, datos):
    """NCargo es un nomenclador global: no pertenece a ninguna unidad.

    Sus solicitudes van con `unidad = NULL` y se notifican a todos los administradores
    activos (ver `solicitudes/avisos.py`); en el filtro por unidad aparecen como «Global».
    """
    return None


def _unidad_de_departamento(objeto, datos):
    if objeto is not None:
        return objeto.unidad_organizativa
    pk = (datos or {}).get('unidad_organizativa')
    return UnidadOrganizativa.objects.filter(pk=pk).first() if pk else None


def _unidad_de_cargo(objeto, datos):
    if objeto is not None:
        departamento = objeto.departamento
        return departamento.unidad_organizativa if departamento else None
    departamento = Departamento.objects.filter(
        pk=(datos or {}).get('departamento')).first()
    return departamento.unidad_organizativa if departamento else None


def _unidad_de_si_misma(objeto, datos):
    """UnidadOrganizativa es su propia unidad de contexto."""
    return objeto


def _unidad_de_contrato(objeto, datos):
    """La del cargo que ocupa. Un contrato sin cargo asignado se queda sin unidad."""
    if objeto is None or objeto.cargo is None:
        return None
    departamento = objeto.cargo.departamento
    return departamento.unidad_organizativa if departamento else None


def _unidad_de_aspirante(objeto, datos):
    """Ninguna: un aspirante no tiene unidad y una baja ya no la tiene, así que
    cualquier Moderador puede pedir que se elimine (decisión del 26-10-2026)."""
    return None


# ----------------------------------------------------------------------
# Campos calculados desde el Cargo (no desde lo que guardó la propuesta)
# ----------------------------------------------------------------------
# `rol` y `grupo_escala` de `CAltaForm` son texto de solo lectura que la vista deriva
# del Cargo; `funcionario`/`designado` ya no existen en el modelo `CAlta` desde
# `contratos.0007_remove_calta_designado_remove_calta_funcionario` y también los decide
# el Cargo. Los cuatro son inputs sueltos en `updt_contrato.html` sin ningún JavaScript
# que los recalcule si el Moderador cambia de Cargo, así que lo que quedó guardado en
# `datos_originales`/`datos_propuestos` no es de fiar. La pantalla de revisión nunca los
# lee de ahí: siempre le pide a estos resolutores que los recalculen a partir del Cargo
# real de esa columna (ver `solicitudes/views.py::_filas_de_comparacion`).

def _rol_de_cargo(cargo):
    return cargo.rol.tipo if cargo and cargo.rol_id else None


def _grupo_escala_de_cargo(cargo):
    if not cargo or not cargo.ncargo_id or not cargo.ncargo.grupo_escala_id:
        return None
    return cargo.ncargo.grupo_escala.nivel


def _funcionario_de_cargo(cargo):
    return bool(cargo.funcionario) if cargo else False


def _designado_de_cargo(cargo):
    return bool(cargo.designado) if cargo else False


def _de_confianza_de_cargo(cargo):
    return bool(cargo.de_confianza) if cargo else False


# ----------------------------------------------------------------------
# Descriptores legibles
# ----------------------------------------------------------------------
# Se congelan al crear la solicitud (`Solicitud.descriptor`). Tienen que funcionar
# también sin objeto, porque en una creación el registro aún no existe y en una
# eliminación ya aprobada dejó de existir.

def _descriptor_ncargo(objeto, datos):
    if objeto is not None:
        return str(objeto)
    return (datos or {}).get('descripcion') or 'Nuevo nomenclador de cargo'


def _descriptor_departamento(objeto, datos):
    if objeto is not None:
        unidad = objeto.unidad_organizativa
        return f'{objeto.descripcion} ({unidad.descripcion})' if unidad else objeto.descripcion
    descripcion = (datos or {}).get('descripcion') or 'Nuevo departamento'
    unidad = _unidad_de_departamento(None, datos)
    return f'{descripcion} ({unidad.descripcion})' if unidad else descripcion


def _descriptor_cargo(objeto, datos):
    if objeto is not None:
        cargo = str(objeto.ncargo) if objeto.ncargo_id else 'Cargo'
        departamento = objeto.departamento
        return f'{cargo} ({departamento.descripcion})' if departamento else cargo

    ncargo = NCargo.objects.filter(pk=(datos or {}).get('ncargo')).first()
    departamento = Departamento.objects.filter(
        pk=(datos or {}).get('departamento')).first()
    cargo = str(ncargo) if ncargo else 'Nuevo cargo'
    return f'{cargo} ({departamento.descripcion})' if departamento else cargo


def _descriptor_unidad(objeto, datos):
    if objeto is not None:
        return objeto.descripcion
    return (datos or {}).get('descripcion') or 'Unidad organizativa'


def _nombre_de_aspirante(aspirante):
    if aspirante is None:
        return ''
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido]
    return ' '.join(parte for parte in partes if parte).strip()


def _descriptor_contrato(objeto, datos):
    if objeto is None:
        return 'Contrato'
    nombre = _nombre_de_aspirante(objeto.aspirante) or 'Sin trabajador'
    return f'{nombre} — Exp. {objeto.no_expediente}'


def _descriptor_aspirante(objeto, datos):
    if objeto is None:
        return 'Trabajador'
    nombre = _nombre_de_aspirante(objeto) or 'Sin nombre'
    return f'{nombre} ({objeto.doc_identidad})'


# ----------------------------------------------------------------------
# Preparación de la ejecución
# ----------------------------------------------------------------------
# Se ejecuta al APROBAR, dentro de la transacción y ANTES de validar el formulario del
# Administrador. Nunca al proponer: enviar una solicitud no debe mover ni un registro.

def _entero(datos, clave):
    valor = (datos or {}).get(clave)
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _desplazar_por_orden(modelo, campo_agrupador, datos, objeto):
    """Libera la posición de `orden_informe` desplazando las siguientes un puesto.

    Replica lo que hacen hoy las vistas de Estructura Organizativa al aceptar «intercalar
    y desplazar», pero en el momento correcto: cuando el cambio se aplica de verdad, y con
    la posición que dejó el Administrador —que puede no ser la que pidió el Moderador—.

    Solo actúa si la posición está realmente ocupada. Desplazar cuando está libre abriría
    un hueco y descolocaría el resto del organigrama sin motivo.

    Funciona porque la restricción de unicidad de estos modelos es `DEFERRABLE`: el
    `UPDATE` puede dejar posiciones repetidas de forma transitoria mientras dure la
    transacción, y se comprueba al confirmarla.
    """
    orden = _entero(datos, 'orden_informe')
    agrupador = _entero(datos, campo_agrupador)
    if orden is None or agrupador is None:
        return

    hermanos = modelo.objects.filter(**{f'{campo_agrupador}_id': agrupador})
    if objeto is not None and objeto.pk is not None:
        hermanos = hermanos.exclude(pk=objeto.pk)

    if not hermanos.filter(orden_informe=orden).exists():
        return

    hermanos.filter(orden_informe__gte=orden).update(orden_informe=F('orden_informe') + 1)


def _preparar_departamento(solicitud, datos, objeto):
    _desplazar_por_orden(Departamento, 'unidad_organizativa', datos, objeto)


def _preparar_cargo(solicitud, datos, objeto):
    _desplazar_por_orden(CargoPlantilla, 'departamento', datos, objeto)


def _preparar_unidad(solicitud, datos, objeto):
    """El desplazamiento de unidades es por RAMA, no por un agrupador simple.

    Las unidades principales cuelgan de la raíz (`padre` nulo) y las subunidades de su
    principal; el orden se numera dentro de cada rama por separado, así que reordenar debe
    afectar solo a las hermanas. Es el mismo criterio que ya aplica
    `UnidadOrganizativaUpdateView.post()` al guardar directamente.
    """
    orden = _entero(datos, 'orden_informe')
    if orden is None:
        return

    padre_id = _entero(datos, 'padre')
    hermanas = UnidadOrganizativa.objects.all()
    hermanas = (hermanas.filter(padre_id=padre_id) if padre_id is not None
                else hermanas.filter(padre__isnull=True))
    if objeto is not None and objeto.pk is not None:
        hermanas = hermanas.exclude(pk=objeto.pk)

    if not hermanas.filter(orden_informe=orden).exists():
        return

    hermanas.filter(orden_informe__gte=orden).update(orden_informe=F('orden_informe') + 1)




# ----------------------------------------------------------------------
# Ejecutores propios
# ----------------------------------------------------------------------
# Para las operaciones cuyo guardado no es un `form.save()` a secas.

def _ejecutar_contrato(solicitud, formulario, objeto):
    """Guarda el contrato aplicando las mismas reglas que `ContratoUpdateView.form_valid`.

    Ese `form_valid` anula el tridente si el cargo es de cuadro (el rol de pago no hay
    que copiarlo: es del cargo, el contrato no tiene rol propio). Se replica aquí para que aprobar una solicitud deje el contrato exactamente igual que
    si lo hubiera guardado un Administrador desde la pantalla de siempre; si no, el mismo
    cambio produciría dos resultados distintos según por dónde entrara.
    """
    contrato = formulario.save(commit=False)

    if contrato.cargo and contrato.cargo.ncargo.es_cuadro:
        contrato.tridente = None

    contrato.save()
    formulario.save_m2m()
    return contrato


# ----------------------------------------------------------------------
# El catálogo
# ----------------------------------------------------------------------
# Claves de cada entrada:
#   etiqueta          Texto visible en el listado, el filtro y las notificaciones.
#   accion            AccionSolicitud. Decide cómo se rellenan los dos JSON.
#   modelo            Clase del modelo afectado.
#   form              ModelForm que valida y aplica el cambio. None en eliminaciones,
#                     que no tienen datos que validar.
#   form_acepta_user  Si su __init__ admite `user=` (unos formularios de Orbith acotan
#                     los desplegables por las unidades del usuario y otros no).
#   desde_tabla       Si el Moderador puede crearla con «Añadir Solicitud». Solo NCargo:
#                     el resto nace de los formularios de su propio módulo.
#   unidad            Resolutor (objeto, datos) -> UnidadOrganizativa | None.
#   descriptor        Resolutor (objeto, datos) -> texto legible.
#   preparar          Opcional. (solicitud, datos, objeto) -> None. Se ejecuta AL APROBAR,
#                     antes de validar, para dejar la base de datos en condiciones de
#                     aceptar el cambio (p. ej. desplazar posiciones de orden). Nunca se
#                     ejecuta al proponer.
#   campos_solo_admin Opcional. Campos que el Moderador no puede proponer: llegan
#                     deshabilitados en su formulario y conservan su valor actual.
#   campos_libres     Opcional. Lo contrario de `campos_solo_admin`: campos que el
#                     Moderador puede guardar directamente, sin solicitud, cuando son los
#                     ÚNICOS que cambian en el envío (ver
#                     `solicitudes/integracion.py::_solo_cambia_campos_libres`). Si el
#                     envío también toca cualquier otro campo, todo —incluidos estos—
#                     vuelve a pasar por el flujo normal de aprobación.
#   campos_condicionales Opcional. Campos cuyo widget nace deshabilitado en el
#                     formulario original —por eso caerían en el mismo trato que
#                     `campos_solo_admin` si no se declaran aquí— pero que un
#                     JavaScript propio habilita según otra elección del formulario
#                     (p. ej. `motivo` de `CAltaForm`, solo si el tipo de contrato lo
#                     exige). Se respeta lo que el Moderador proponga para ellos, y en
#                     la pantalla de revisión quedan editables para el Administrador
#                     igual que cualquier otro campo (ver
#                     `solicitudes/serializacion.py::formulario_de_aprobacion`): lo que
#                     él deje en el POST al aprobar es lo que se guarda.
#   ejecutor          Opcional. Cómo se aplica al aprobar, cuando no basta el
#                     comportamiento por defecto (guardar el formulario, o borrar el
#                     objeto en las eliminaciones).

OPERACIONES = {
    # --- Nomenclador de Cargos: las dos únicas que se crean desde la propia tabla ---
    'ncargo_add': {
        'etiqueta': 'Añadir Nomenclador de Cargo',
        'accion': AccionSolicitud.CREAR,
        'modelo': NCargo,
        'form': NCargoForm,
        'form_acepta_user': False,
        'desde_tabla': True,
        'unidad': _sin_unidad,
        'descriptor': _descriptor_ncargo,
    },
    'ncargo_upd': {
        'etiqueta': 'Editar Nomenclador de Cargo',
        'accion': AccionSolicitud.EDITAR,
        'modelo': NCargo,
        'form': NCargoForm,
        'form_acepta_user': False,
        'desde_tabla': True,
        'unidad': _sin_unidad,
        'descriptor': _descriptor_ncargo,
    },

    # --- Departamento ---
    # El Moderador puede proponer cualquier posición de orden, incluida una ocupada: al
    # enviar no se mueve nada. El desplazamiento lo ejecuta `preparar` en la aprobación,
    # con la posición final que haya dejado el Administrador.
    'dpto_add': {
        'etiqueta': 'Añadir Departamento',
        'accion': AccionSolicitud.CREAR,
        'modelo': Departamento,
        'form': DepartamentoForm,
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_departamento,
        'descriptor': _descriptor_departamento,
        'preparar': _preparar_departamento,
    },
    'dpto_upd': {
        'etiqueta': 'Editar Departamento',
        'accion': AccionSolicitud.EDITAR,
        'modelo': Departamento,
        'form': DepartamentoForm,
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_departamento,
        'descriptor': _descriptor_departamento,
        'preparar': _preparar_departamento,
    },
    'dpto_del': {
        'etiqueta': 'Eliminar Departamento',
        'accion': AccionSolicitud.ELIMINAR,
        'modelo': Departamento,
        'form': DepartamentoForm,   # solo para PINTAR la ficha del registro a eliminar
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_departamento,
        'descriptor': _descriptor_departamento,
    },

    # --- Cargo Plantilla ---
    # Mismo criterio que Departamento con el orden: el Moderador propone la posición que
    # quiera y el desplazamiento lo ejecuta `preparar` al aprobar.
    'cargo_add': {
        'etiqueta': 'Añadir Cargo Plantilla',
        'accion': AccionSolicitud.CREAR,
        'modelo': CargoPlantilla,
        'form': CargoPlantillaForm,
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_cargo,
        'descriptor': _descriptor_cargo,
        'preparar': _preparar_cargo,
    },
    'cargo_upd': {
        'etiqueta': 'Editar Cargo Plantilla',
        'accion': AccionSolicitud.EDITAR,
        'modelo': CargoPlantilla,
        'form': CargoPlantillaForm,
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_cargo,
        'descriptor': _descriptor_cargo,
        'preparar': _preparar_cargo,
    },
    'cargo_del': {
        'etiqueta': 'Eliminar Cargo Plantilla',
        'accion': AccionSolicitud.ELIMINAR,
        'modelo': CargoPlantilla,
        'form': CargoPlantillaForm,   # solo para PINTAR la ficha del registro a eliminar
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_cargo,
        'descriptor': _descriptor_cargo,
    },

    # --- Unidad Organizativa ---
    # SOLO edición, y solo de las unidades que el Moderador tiene asignadas. Crear y
    # eliminar unidades es competencia exclusiva del Administrador y ni siquiera se puede
    # solicitar: esas dos vistas van con `admin_required` en `strorganizativa/urls.py`.
    #
    # `orden_informe` queda fuera de lo proponible: reordenar el organigrama lo decide el
    # Administrador. Le llega deshabilitado al Moderador, así que conserva su valor aunque
    # alguien manipule la petición; el Administrador sí puede cambiarlo durante la
    # revisión, y de ahí que la operación conserve su `preparar`.
    'uniorg_upd': {
        'etiqueta': 'Editar Unidad Organizativa',
        'accion': AccionSolicitud.EDITAR,
        'modelo': UnidadOrganizativa,
        'form': UnidadOrganizativaForm,
        'form_acepta_user': False,
        'desde_tabla': False,
        'unidad': _unidad_de_si_misma,
        'descriptor': _descriptor_unidad,
        'campos_solo_admin': ('orden_informe',),
        'preparar': _preparar_unidad,
    },

    # --- Contrato ---
    # Solo edición. El alta pasa por un asistente con estado en sesión
    # (`ContratoCreateView` + `wizard_movimiento_nomina`), y la baja es un proceso aparte;
    # ninguno de los dos está en la lista aprobada por RRHH.
    'contrato_upd': {
        'etiqueta': 'Editar Contrato',
        'accion': AccionSolicitud.EDITAR,
        'modelo': CAlta,
        'form': CAltaForm,
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_contrato,
        'descriptor': _descriptor_contrato,
        'ejecutor': _ejecutar_contrato,
        # Decisión de negocio (2026-08): estos no tienen impacto en nómina ni en la
        # estructura organizativa, así que un cambio que toque solo uno de ellos (o
        # varios entre ellos) se guarda directo, sin pasar por el Administrador.
        #
        # `fecha_alta_entidad` se añadió en 2026-09: es un dato que el Moderador conoce
        # de primera mano —la entrada del trabajador en su unidad— y que Subsanación le
        # reclama contrato por contrato (CTR-016/CTR-017). Obligarle a pedir aprobación
        # para cada corrección convertía un saneamiento masivo en una cola de solicitudes
        # sin ningún criterio que el Administrador pudiera aportar.
        #
        # `mision_dias` y `mision_importe` se añadieron en 2026-10 por la misma razón:
        # el Moderador los mantiene al día —también desde el informe de Misiones
        # Internacionales— y no tocan nómina ni estructura. Activar o desactivar la
        # propia `mision`, o cambiar el `pais`, sigue pasando por el Administrador.
        #
        # 24-10-2026 (decisión de RRHH): también los números de resolución —que
        # suelen llegar semanas después del alta o del movimiento— y el switch
        # Jubilado recontratado. Activar Calificación formal sigue pidiendo solicitud;
        # Funcionario y Designado los decide el cargo, no el contrato.
        # `motivo` salió el 24-10-2026: ya no se cambia editando el contrato (va al
        # histórico; solo lo cambia un movimiento de nómina).
        'campos_libres': ('reg_militar', 'fecha_alta_entidad',
                          'mision_dias', 'mision_importe',
                          'c_formal_res', 'funcionario_res', 'designado_res',
                          'confianza_res', 'jubilado_recontratado',
                          # Modalidad de trabajo (24-10-2026): también libres.
                          'trabajo_distancia', 'teletrabajo', 'pluriempleo'),
        # Todos estos nacen deshabilitados en `CAltaForm.Meta.widgets` y un JavaScript
        # propio los habilita según otra elección del formulario: `motivo` si el tipo de
        # contrato lo exige, `duracion` si el tipo no es indeterminado, `c_formal_res`/
        # `funcionario_res`/`designado_res` si el switch correspondiente está activo,
        # `fecha_vence_lic`/`fecha_vence_recal`/`fecha_vence_seg` si es Chofer Profesional,
        # y `pais` si hay Misión. Sin declararlos aquí, `formulario_de_propuesta()` los
        # trata igual que `campos_solo_admin` y descarta en silencio lo que el Moderador
        # sí llegó a escribir (el mismo bug ya detectado y corregido para `motivo`, pero
        # que seguía abierto para el resto: un Moderador que marcaba «Funcionario» y
        # escribía el número de resolución veía la propuesta llegar con ese campo vacío).
        #
        # `fecha_alta_entidad` entra aquí por lo mismo, y no por un JavaScript de
        # cascada: su widget nace deshabilitado en `Meta.widgets` y el propio formulario
        # de contrato se lo habilita al cargar. Sin declararla, todo lo que el Moderador
        # escribiera en ella se descartaba en silencio y al Administrador le llegaba el
        # valor viejo del contrato (o vacío) por muy bien que la hubiera enviado; y en la
        # pantalla de revisión salía gris, así que el Administrador tampoco podía
        # corregirla.
        'campos_condicionales': (
            'motivo', 'duracion', 'c_formal_res', 'funcionario_res', 'designado_res',
            'confianza_res', 'fecha_vence_lic', 'fecha_vence_recal', 'fecha_vence_seg', 'pais',
            'mision_dias', 'mision_importe', 'fecha_alta_entidad',
        ),
        # Ver el bloque «Campos calculados desde el Cargo» más arriba: `rol` y
        # `grupo_escala` los deriva el Cargo (por su NCargo); `funcionario`/`designado`
        # también los decide el Cargo, no el contrato. Se recalculan siempre en la
        # pantalla de revisión, tanto para la columna Original (Cargo actual) como para
        # la Propuesta (Cargo propuesto, si el Moderador también lo cambió).
        'campos_calculados': {
            'rol': _rol_de_cargo,
            'grupo_escala': _grupo_escala_de_cargo,
            'funcionario': _funcionario_de_cargo,
            'designado': _designado_de_cargo,
            'de_confianza': _de_confianza_de_cargo,
        },
    },

    # --- Eliminar persona desde la Lista de Aspirantes o la de Bajas ---
    # Es lo que RRHH llama «eliminar contrato»: el botón de esa lista, que borra el
    # registro del trabajador y con él su historial. El borrado por defecto basta; si
    # algo lo protege todavía —un contrato activo—, el error sube y se muestra al aprobar.
    'aspirante_del': {
        'etiqueta': 'Eliminar Trabajador',
        'accion': AccionSolicitud.ELIMINAR,
        'modelo': Aspirante,
        'form': AspiranteForm,   # solo para PINTAR la ficha de quien se va a eliminar
        'form_acepta_user': True,
        'desde_tabla': False,
        'unidad': _unidad_de_aspirante,
        'descriptor': _descriptor_aspirante,
    },
}


# ----------------------------------------------------------------------
# Consultas sobre el catálogo
# ----------------------------------------------------------------------

class OperacionDesconocida(KeyError):
    """La solicitud apunta a una operación que ya no está en el catálogo."""


def definicion_de(clave):
    """Entrada del catálogo. Lanza `OperacionDesconocida` si la clave no existe."""
    try:
        return OPERACIONES[clave]
    except KeyError:
        raise OperacionDesconocida(
            f'La operación «{clave}» no está en el catálogo de solicitudes.') from None


def clave_para(modelo, accion):
    """Clave de la operación que corresponde a un modelo y una acción, o None.

    Es lo que usan las vistas desviadas: `DepartamentoCreateView` pregunta por
    `(Departamento, CREAR)` sin tener que conocer la cadena 'dpto_add'. Devolver None
    cuando no hay entrada es intencional: significa «esta operación no requiere
    aprobación», y la vista sigue con su comportamiento normal.
    """
    for clave, definicion in OPERACIONES.items():
        if definicion['modelo'] is modelo and definicion['accion'] == accion:
            return clave
    return None


def operaciones_desde_tabla():
    """`[(clave, etiqueta)]` de las que el Moderador puede crear con «Añadir Solicitud»."""
    return [(clave, definicion['etiqueta'])
            for clave, definicion in OPERACIONES.items()
            if definicion.get('desde_tabla')]


def opciones_de_tipo():
    """`[(clave, etiqueta)]` de todas, para el desplegable de filtro por tipo."""
    return [(clave, definicion['etiqueta']) for clave, definicion in OPERACIONES.items()]


def opciones_de_registro(definicion):
    """`[(pk, texto)]` de los registros existentes del modelo de la operación, para el
    selector «Registro a modificar» del alta desde tabla.

    Vacío cuando la operación es de creación (no hay nada que elegir todavía) o cuando
    no se ha elegido operación. Se recalcula en cada petición en vez de cachearse: la
    tabla de NCargo es pequeña y siempre debe reflejar el estado actual.
    """
    if definicion is None or definicion['accion'] == AccionSolicitud.CREAR:
        return []
    return [(objeto.pk, str(objeto))
            for objeto in definicion['modelo'].objects.all().order_by('pk')]


def form_kwargs_de(definicion, usuario):
    """Argumentos extra del formulario según lo que acepte su `__init__`."""
    return {'user': usuario} if definicion.get('form_acepta_user') else {}


def content_type_de(definicion):
    return ContentType.objects.get_for_model(definicion['modelo'])


def form_de_propuesta(definicion):
    """ModelForm para construir la propuesta, sin las validaciones de persistencia.

    Ver `solicitudes/serializacion.py::formulario_de_propuesta`. Se usa cuando el
    Moderador envía; el Administrador siempre valida con el formulario completo.
    """
    from solicitudes.serializacion import formulario_de_propuesta
    return formulario_de_propuesta(
        definicion['form'], definicion.get('campos_solo_admin', ()),
        definicion.get('campos_condicionales', ()))


def form_de_aprobacion(definicion):
    """ModelForm para la pantalla de revisión y para aplicar el cambio al aprobar.

    Ver `solicitudes/serializacion.py::formulario_de_aprobacion`. A diferencia de
    `form_de_propuesta`, no deshabilita `campos_solo_admin`: esos el Administrador sí
    puede decidirlos en este paso.
    """
    from solicitudes.serializacion import formulario_de_aprobacion
    return formulario_de_aprobacion(
        definicion['form'], definicion.get('campos_condicionales', ()))


def preparar_ejecucion(solicitud, definicion, datos, objeto):
    """Deja la base de datos lista para aplicar el cambio. Solo se llama al aprobar."""
    preparador = definicion.get('preparar')
    if preparador is not None:
        preparador(solicitud, datos, objeto)


# ----------------------------------------------------------------------
# Ejecución al aprobar
# ----------------------------------------------------------------------

def ejecutar(solicitud, definicion, formulario, objeto):
    """Aplica el cambio aprobado. Se llama ya dentro de la transacción de `servicios`.

    El ejecutor por defecto cubre las tres formas básicas; una operación con reglas
    propias (las de Contrato y Aspirante, en fase C) declara la suya en `ejecutor`.
    Cualquier excepción sube: `servicios.aprobar()` la convierte en un error visible en
    la pantalla de revisión y deshace la transacción, de modo que la solicitud NO queda
    marcada como aprobada si la operación no llegó a aplicarse.
    """
    ejecutor_propio = definicion.get('ejecutor')
    if ejecutor_propio is not None:
        return ejecutor_propio(solicitud, formulario, objeto)

    if definicion['accion'] == AccionSolicitud.ELIMINAR:
        objeto.delete()
        return None

    return formulario.save()
