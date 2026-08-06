"""Mixins de navegación/layout para vistas de edición, reutilizables entre apps.

Distinto de `usuarios/mixins.py` (que es solo de permisos): estos mixins resuelven un
problema transversal a cualquier `UpdateView` cuya plantilla es un fragmento crudo
pensado para cargarse dentro de un modal ya abierto en el listado de su propio módulo
(Contrato, Aspirante, Cargo, Departamento, Unidad Organizativa, Usuario).

Cuando esa misma vista se abre por navegación directa (por ejemplo, un enlace "Abrir
contrato" desde Notificaciones o Subsanación), no hay ningún modal contenedor: el
fragmento se serviría crudo, sin navbar ni CSS. `ModalOPaginaCompletaMixin` decide, y
`VolverAlOrigenMixin` hace que el guardado exitoso vuelva exactamente a donde estaba el
usuario en vez de al listado fijo del módulo. `AdvertenciasDelRegistroMixin` añade el
contexto de «otras advertencias de este mismo registro» a esas mismas 6 vistas.
"""


class ModalOPaginaCompletaMixin:
    """Decide entre el fragmento de siempre (para el modal ya existente en el listado
    del módulo) o una página completa nueva con el layout de Orbith.

    Se distingue por cabecera, no por vista: jQuery añade `X-Requested-With` en toda
    petición `.load()`/`.ajax()` del proyecto, y HTMX añade `HX-Request`. Cualquier otra
    petición (navegación directa por URL) es "página completa". Hay que comprobar AMBAS
    cabeceras: sin `HX-Request`, un `form_invalid()` de una vista basada en HTMX
    devolvería la página completa como si fuera el fragmento a inyectar en el modal,
    rompiendo el HTML.
    """

    template_name_pagina = None

    def _es_peticion_fragmento(self):
        return (self.request.headers.get('x-requested-with') == 'XMLHttpRequest'
                or self.request.headers.get('HX-Request') == 'true')

    def get_template_names(self):
        if self._es_peticion_fragmento():
            return [self.template_name]
        return [self.template_name_pagina]


class VolverAlOrigenMixin:
    """Generaliza el patrón `next` que hoy solo tenía `AspiranteUpdateView`.

    `next` viaja como querystring en el enlace que abrió el formulario (ver
    `subsanacion/enlaces.py::construir_enlace()`, el único punto que genera esos
    enlaces) y como campo oculto una vez dentro del formulario, para sobrevivir al
    POST. Como `next` es la URL completa de origen (incluye pestaña, filtros, búsqueda
    y página), volver ahí restaura todo ese contexto sin lógica adicional.
    """

    url_por_defecto = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self.request.GET.get('next', '')
        context['origen'] = self.request.GET.get('origen', '')
        # Para el botón Cancelar de la plantilla "página completa": sin `next` (llegó
        # sin origen, p.ej. por marcador), debe volver al listado de siempre.
        context['url_por_defecto'] = str(self.url_por_defecto)
        return context

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        return next_url or str(self.url_por_defecto)


class AdvertenciasDelRegistroMixin:
    """Contexto de «otras advertencias de este mismo registro», para las 6 vistas de
    edición que también llevan `VolverAlOrigenMixin`.

    Sin esto, corregir un registro con varios problemas activos solo mostraba el
    formulario del hallazgo que se pulsó: el usuario perdía de vista que el mismo
    registro tenía más advertencias pendientes y tenía que volver a Notificaciones a
    descubrirlo. Alcance limitado al registro que se edita (decisión ya tomada: no
    cruza a un registro vinculado).
    """

    def _advertencias_del_registro(self):
        """`{'activas': [Notificacion...], 'total': N, 'resueltas': N}` de tipo ALERTA
        sobre `self.object`, deduplicadas por `(codigo_regla, clave_extra)` — el mismo
        hallazgo puede haberse notificado a varios destinatarios y no debe contarse dos
        veces. Trae tanto ACTIVA como RESUELTA: es lo que permite calcular el progreso
        (`C.3`) sin una consulta histórica aparte; conviven bien con la purga a 60 días
        (`notificaciones/limpieza.py`), que da margen de sobra mientras el registro
        sigue en edición activa.
        """
        from django.contrib.contenttypes.models import ContentType

        from notificaciones.models import Notificacion

        vacio = {'activas': [], 'total': 0, 'resueltas': 0}
        if getattr(self, 'object', None) is None or self.object.pk is None:
            return vacio

        content_type = ContentType.objects.get_for_model(self.object)
        consulta = (Notificacion.objects
                    .filter(content_type=content_type, object_id=str(self.object.pk),
                            tipo=Notificacion.Tipo.ALERTA,
                            estado__in=[Notificacion.Estado.ACTIVA, Notificacion.Estado.RESUELTA])
                    .order_by('-severidad', 'codigo_regla'))

        agrupadas = {}  # (codigo_regla, clave_extra) -> Notificacion representativa
        for notificacion in consulta:
            clave = (notificacion.codigo_regla, notificacion.clave_extra)
            existente = agrupadas.get(clave)
            # Si dos destinatarios tuvieran estados distintos para el mismo hallazgo
            # (no debería pasar: se resuelven en bloque), se prioriza la ACTIVA, para
            # no dar por resuelto algo que sigue pendiente para alguien.
            if existente is None or (
                    existente.estado == Notificacion.Estado.RESUELTA
                    and notificacion.estado == Notificacion.Estado.ACTIVA):
                agrupadas[clave] = notificacion

        vistas = list(agrupadas.values())
        activas = [n for n in vistas if n.estado == Notificacion.Estado.ACTIVA]
        return {'activas': activas, 'total': len(vistas), 'resueltas': len(vistas) - len(activas)}

    def mensaje_de_guardado_exitoso(self, mensaje_por_defecto):
        """Sustituye `mensaje_por_defecto` por el mensaje de cierre cuando, tras
        guardar, el registro ya no tiene ninguna advertencia activa — pero solo si se
        llegó aquí desde una advertencia (`next` presente). Sin `next` no hay una
        redirección real de vuelta a ningún sitio (ver `VolverAlOrigenMixin`), así que
        el mensaje de cierre no debe sustituir al genérico: quedaría «colgado» en la
        sesión de Django y podría aparecer en una navegación posterior no relacionada.
        """
        if not (self.request.POST.get('next') or self.request.GET.get('next')):
            return mensaje_por_defecto
        if self._advertencias_del_registro()['activas']:
            return mensaje_por_defecto
        return '✅ Cambios aplicados. Este registro ya no tiene advertencias pendientes.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        datos = self._advertencias_del_registro()
        context['advertencias_del_registro'] = datos['activas']
        context['advertencias_total'] = datos['total']
        context['advertencias_resueltas'] = datos['resueltas']
        return context
