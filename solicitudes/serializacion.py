"""Convertir un formulario en datos guardables, y volver a leerlos para compararlos.

Todo lo que se guarda en `Solicitud.datos_originales` y `Solicitud.datos_propuestos` pasa
por aquí. La decisión de fondo: **los campos se recorren desde el ModelForm, no desde el
modelo**. Así la fotografía y la propuesta tienen siempre exactamente las mismas claves y
en el mismo orden, que es lo que permite compararlas fila a fila; y la pantalla de
revisión hereda gratis las etiquetas, el orden y los widgets que el usuario ya conoce del
formulario real, sin declararlos por segunda vez.

Los valores se guardan normalizados (las claves ajenas como pk, las fechas y decimales
como texto) porque JSONField no serializa objetos de Django ni `Decimal`, y porque un pk
sigue siendo válido aunque el registro apuntado cambie de nombre después.
"""

import datetime
from decimal import Decimal

from django.db.models import Model, QuerySet

# Lo que se muestra en la columna «Situación Actual» cuando un campo no tiene valor.
VACIO = '—'


def _normalizar(valor):
    """Deja el valor listo para JSONField, conservando su identidad.

    Las instancias de modelo se reducen a su pk (no a su texto) para que la comparación
    entre fotografía y propuesta detecte un cambio real de registro y no un simple
    cambio de nombre del registro apuntado.
    """
    if valor is None:
        return None
    if isinstance(valor, Model):
        return valor.pk
    if isinstance(valor, QuerySet):
        return sorted(objeto.pk for objeto in valor)
    if isinstance(valor, (list, tuple, set)):
        return sorted(_normalizar(elemento) for elemento in valor)
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime.datetime, datetime.date, datetime.time)):
        return valor.isoformat()
    if isinstance(valor, (bool, int, float, str)):
        return valor
    return str(valor)


def _comparable(valor):
    """Forma canónica para decidir si dos valores son «el mismo».

    None, cadena vacía y lista vacía significan lo mismo para un usuario («no hay nada
    aquí»), y sin unificarlos un campo opcional que nunca se tocó aparecería resaltado
    como modificado. Los números se comparan como texto porque el mismo valor puede
    llegar como `3`, `3.0` o `'3.00'` según venga de la base de datos o del formulario.
    """
    normalizado = _normalizar(valor)
    if normalizado is None or normalizado == '' or normalizado == []:
        return None
    if isinstance(normalizado, bool):
        return normalizado
    if isinstance(normalizado, (int, float)):
        return str(Decimal(str(normalizado)).normalize())
    if isinstance(normalizado, str):
        texto = normalizado.strip()
        try:
            return str(Decimal(texto).normalize())
        except Exception:
            return texto
    return normalizado


def construir_formulario(form_class, *, instancia=None, datos=None, initial=None,
                         form_kwargs=None):
    """Instancia un ModelForm del proyecto de forma uniforme.

    Existe para que el resto del módulo no tenga que saber que unos formularios de Orbith
    aceptan `user=` y otros no, ni repetir el mismo `**kwargs` en cinco sitios.
    """
    kwargs = dict(form_kwargs or {})
    if instancia is not None:
        kwargs['instance'] = instancia
    if initial is not None:
        kwargs['initial'] = initial
    if datos is not None:
        return form_class(datos, **kwargs)
    return form_class(**kwargs)


def formulario_de_propuesta(form_class, campos_solo_admin=()):
    """Variante del ModelForm para CONSTRUIR una propuesta, no para guardarla.

    Enviar una solicitud no escribe nada en la base de datos, así que las comprobaciones
    que existen para proteger la integridad al persistir no aplican todavía: se evalúan
    cuando el Administrador aprueba, contra el estado que haya en ese momento y con los
    valores que él haya dejado. Aplicarlas al proponer impediría al Moderador pedir cosas
    perfectamente legítimas —por ejemplo, colocar un departamento en una posición hoy
    ocupada, que es justo el caso que el Administrador resolverá desplazando el resto.

    Lo que se omite y por qué:

    * Los errores de unicidad: son restricciones de la tabla. Nada se va a insertar, así
      que no hay nada que pueda chocar.
    * El conflicto de posición de orden: se inyecta `autoriza_desplazamiento` para que el
      `clean()` de estos formularios no lo reporte. Al proponer, la respuesta es siempre
      sí, porque el desplazamiento no ocurre ahora sino al aprobar.

    Lo que NO se omite: todo el resto de `clean()`, es decir las reglas de negocio reales
    (funcionario contra designado, rol obligatorio, un NCargo repetido en el mismo
    departamento...). Una propuesta inválida sigue siendo inválida y el Moderador ve los
    mismos errores de siempre.

    Campos que se deshabilitan —Django ignora lo que llegue en el POST y conserva el valor
    inicial, así que no se pueden proponer ni manipulando la petición—:

    * Los de `campos_solo_admin`, decididos por operación en el catálogo.
    * Los que el formulario original ya pinta deshabilitados, como el «Estado
      (Automático)» de Cargo Plantilla: el modelo lo calcula solo, y sin esto llegaría
      vacío en el POST y aparecería como un cambio propuesto que nadie pidió.
    """
    class _Propuesta(form_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._neutralizar_conflicto_de_orden()
            for nombre, campo in self.fields.items():
                if nombre in campos_solo_admin or _widget_deshabilitado(campo.widget):
                    campo.disabled = True

        def _neutralizar_conflicto_de_orden(self):
            """Marca el envío como «ya autorizado a desplazar».

            Se hace sobre `self.data` y no sobreescribiendo un método porque los
            formularios de Orbith lo consultan de dos maneras distintas: `DepartamentoForm`
            y `UnidadOrganizativaForm` tienen un método `_autoriza_desplazamiento()`, pero
            `CargoPlantillaForm` mira `self.data` directamente en su `clean()`. Tocar el
            dato cubre ambas.
            """
            if not self.is_bound:
                return
            datos = self.data.copy()
            datos['autoriza_desplazamiento'] = 'true'
            self.data = datos

        def _autoriza_desplazamiento(self):
            return True

        def _post_clean(self):
            super()._post_clean()
            _descartar_errores_de_persistencia(self)

    _Propuesta.__name__ = f'Propuesta{form_class.__name__}'
    return _Propuesta


def _widget_deshabilitado(widget):
    valor = getattr(widget, 'attrs', {}).get('disabled')
    return bool(valor) or valor == ''


#: Errores que Django emite al comprobar que la fila cabría en la tabla. No describen un
#: dato mal puesto, sino un choque con lo que hay guardado ahora mismo.
CODIGOS_DE_PERSISTENCIA = {'unique', 'unique_together', 'unique_for_date',
                           'unique_for_month', 'unique_for_year'}


def _descartar_errores_de_persistencia(formulario):
    """Quita del formulario los errores de unicidad, conservando todos los demás.

    Se filtra por CÓDIGO de error y no interceptando `validate_unique()`: Django genera
    estas comprobaciones desde varios puntos —`Model.full_clean`, `BaseModelForm`, las
    `UniqueConstraint` del modelo— y sobrescribir uno solo deja pasar los otros, que es
    exactamente lo que ocurrió al implementarlo así la primera vez. El código de error sí
    es estable venga de donde venga.
    """
    if not formulario._errors:
        return
    for campo in list(formulario._errors):
        conservados = [error for error in formulario._errors[campo].as_data()
                       if error.code not in CODIGOS_DE_PERSISTENCIA]
        if conservados:
            formulario._errors[campo] = formulario.error_class(conservados)
        else:
            del formulario._errors[campo]


def capturar(instancia, form_class, form_kwargs=None):
    """Fotografía del registro tal y como lo vería el formulario ahora mismo.

    Se toma de `form.initial` (lo que el formulario mostraría al abrirlo) en vez de leer
    el modelo directamente, para que incluya también los campos declarados que no existen
    en el modelo —como `unidad` en `CargoPlantillaForm`— y quede alineada campo a campo
    con lo que después se guarde como propuesta.
    """
    if instancia is None:
        return {}
    formulario = construir_formulario(
        form_class, instancia=instancia, form_kwargs=form_kwargs)
    return {
        nombre: _normalizar(formulario.get_initial_for_field(campo, nombre))
        for nombre, campo in formulario.fields.items()
    }


def serializar(formulario):
    """Datos validados de un formulario ya limpio (`is_valid()` en True)."""
    return {
        nombre: _normalizar(formulario.cleaned_data.get(nombre))
        for nombre in formulario.fields
    }


def comparar(originales, propuestos):
    """Nombres de los campos que difieren, para resaltarlos en la revisión.

    Solo mira las claves presentes en la propuesta: un campo que se retiró del formulario
    después de crear la solicitud sigue en la fotografía pero ya no es comparable, y
    marcarlo como «modificado» sería engañoso.
    """
    if not originales:
        return set()
    return {
        nombre for nombre, valor in propuestos.items()
        if _comparable(originales.get(nombre)) != _comparable(valor)
    }


def _texto_de_campo(campo, valor):
    """Valor legible de un campo: 'Especialista B', no '47'."""
    if valor is None or valor == '' or valor == []:
        return VACIO

    if hasattr(campo, 'queryset') and campo.queryset is not None:
        pks = valor if isinstance(valor, list) else [valor]
        nombres = []
        for pk in pks:
            objeto = campo.queryset.model.objects.filter(pk=pk).first()
            # El registro apuntado pudo borrarse después de tomar la fotografía. Se
            # muestra el pk crudo en vez de ocultar que allí había algo.
            nombres.append(str(objeto) if objeto else f'(eliminado: {pk})')
        return ', '.join(nombres) if nombres else VACIO

    opciones = getattr(campo, 'choices', None)
    if opciones:
        for clave, etiqueta in opciones:
            if str(clave) == str(valor):
                return etiqueta

    if isinstance(valor, bool):
        return 'Sí' if valor else 'No'

    return str(valor)


def para_mostrar(form_class, datos, form_kwargs=None):
    """`{nombre_campo: texto legible}` para la columna «Situación Actual».

    Esa columna es de solo lectura, así que se pinta como texto y no como widgets
    deshabilitados: un `<select disabled>` con la opción antigua ya no seleccionable
    llevaría a confusión, y además arrastraría al DOM los atributos HTMX de las cascadas
    del formulario original, que no deben dispararse en la mitad izquierda.
    """
    if not datos:
        return {}
    formulario = construir_formulario(form_class, form_kwargs=form_kwargs)
    return {
        nombre: _texto_de_campo(campo, datos.get(nombre))
        for nombre, campo in formulario.fields.items()
    }


def resumen_de_cambios(form_class, originales, propuestos, form_kwargs=None):
    """Lista de `(etiqueta, antes, después)` de los campos modificados.

    Se usa en el texto de las notificaciones y en la confirmación de aprobación, donde no
    hay sitio para la tabla completa pero sí para decir qué cambia de verdad.
    """
    if not originales:
        return []
    formulario = construir_formulario(form_class, form_kwargs=form_kwargs)
    cambiados = comparar(originales, propuestos)
    filas = []
    for nombre, campo in formulario.fields.items():
        if nombre not in cambiados:
            continue
        filas.append((
            campo.label or nombre.replace('_', ' ').capitalize(),
            _texto_de_campo(campo, originales.get(nombre)),
            _texto_de_campo(campo, propuestos.get(nombre)),
        ))
    return filas


def coincide_con_registro(solicitud, form_class, form_kwargs=None):
    """¿El registro real sigue como estaba cuando se creó la solicitud?

    La fotografía nunca se recaptura, así que si alguien modificó el registro por otra
    vía entretanto, la columna «Situación Actual» dejó de reflejar la realidad. No es un
    error —la fotografía es correcta y debe conservarse— pero tanto el Moderador al
    editar como el Administrador al revisar tienen que saberlo, porque las diferencias
    resaltadas ya no describen el cambio que se aplicaría hoy.
    """
    objeto = solicitud.objeto_afectado
    if objeto is None or not solicitud.datos_originales:
        return True
    actual = capturar(objeto, form_class, form_kwargs=form_kwargs)
    return not comparar(solicitud.datos_originales, actual)
