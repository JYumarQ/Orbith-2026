"""Solicitudes de operaciones que requieren aprobación de un Administrador.

Un Moderador no ejecuta directamente ciertas operaciones sensibles: propone el cambio,
y un Administrador lo revisa, lo ajusta si hace falta y decide. Este módulo guarda esa
propuesta mientras espera decisión.

Un SOLO modelo genérico para las 10 operaciones aprobadas por RRHH (sobre NCargo,
Departamento, CargoPlantilla, UnidadOrganizativa, Aspirante y CAlta), en vez de un
modelo por entidad. Lo que cambia entre operaciones no es la estructura de la solicitud
—siempre es «esto había, esto se propone, quién decide»— sino qué formulario la valida y
qué función la aplica al aprobar; eso vive en `solicitudes/operaciones.py`. Añadir una
operación futura es una entrada en ese diccionario, no un modelo ni una tabla nuevos.

Dos campos JSON sostienen la comparación de la pantalla de revisión:

* `datos_originales` es la FOTOGRAFÍA del registro en el momento de crear la solicitud, y
  es INMUTABLE — ni siquiera se recaptura cuando el Moderador edita su propia solicitud.
  Si el registro real cambia después, la solicitud debe seguir contando cómo estaba
  cuando se propuso el cambio; recapturarla haría que el resaltado de diferencias
  comparase contra un punto de partida distinto del que vio el Moderador.
* `datos_propuestos` es lo que el Moderador pide, y lo puede reescribir él mientras la
  solicitud siga En Espera, o el Administrador durante la revisión antes de aprobar.

Este modelo NO crea notificaciones en `save()`. El modelo anterior sí lo hacía, pero aquí
hay que avisar en varias transiciones distintas (envío, aprobación, rechazo) y con
destinatarios distintos en cada una, y ninguna de ellas es «cualquier guardado». Vive en
`solicitudes/avisos.py`, invocado desde `solicitudes/servicios.py`, que es el único sitio
que cambia de estado.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.utils import timezone

from auditoria.models import Base

# Un Administrador puede abrir una revisión y cerrar el navegador sin pulsar Cancelar.
# Sin caducidad, esa solicitud quedaría bloqueada para siempre: el Moderador no podría
# editarla ni retirarla, y ningún otro Administrador podría revisarla. Se evalúa al leer
# (ver `bloqueada`), no con un proceso en segundo plano que habría que mantener vivo.
MINUTOS_BLOQUEO_REVISION = 30


class AccionSolicitud(models.TextChoices):
    """Qué se pide hacer. Es el eje que decide cómo se rellenan los dos JSON:
    ADD no tiene fotografía original, DEL no tiene datos propuestos."""
    CREAR = 'ADD', 'Añadir'
    EDITAR = 'UPD', 'Editar'
    ELIMINAR = 'DEL', 'Eliminar'


class EstadoSolicitud(models.TextChoices):
    """RRHH definió tres estados visibles como pestañas: En Espera, Aprobadas y
    Rechazadas. `EN_REVISION` NO es una cuarta pestaña: es el bloqueo temporal mientras
    un Administrador la tiene abierta, y esas solicitudes se siguen listando dentro de
    «En Espera» con un distintivo de quién las está revisando."""
    EN_ESPERA = 'E', 'En Espera'
    EN_REVISION = 'R', 'En Revisión'
    APROBADA = 'A', 'Aprobada'
    RECHAZADA = 'X', 'Rechazada'

    @classmethod
    def pendientes(cls):
        """Los dos estados que cuentan como «todavía sin decidir»."""
        return [cls.EN_ESPERA, cls.EN_REVISION]


class Solicitud(Base):
    # Clave del registro de `solicitudes/operaciones.py`. Se guarda la clave y no el
    # modelo+acción por separado porque es lo que identifica la operación de forma
    # única y legible ('dpto_del'), y porque de ella cuelgan el formulario y el ejecutor.
    operacion = models.CharField(max_length=30, verbose_name='Operación')
    estado = models.CharField(
        max_length=1, choices=EstadoSolicitud.choices,
        default=EstadoSolicitud.EN_ESPERA, verbose_name='Estado')

    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_creadas', verbose_name='Solicitante')
    # Congelado al crear. `solicitante` puede quedar en NULL si algún día se borra ese
    # usuario, y la pantalla de revisión tiene que poder seguir diciendo «Cambio
    # propuesto por ...» en vez de quedarse en blanco.
    solicitante_nombre = models.CharField(max_length=150, blank=True, default='')

    # A qué registro apunta. `object_id` es CharField y no entero a propósito: la PK de
    # UnidadOrganizativa es `codigo_interno`, no `id` — mismo criterio que ya sigue
    # `notificaciones.Notificacion`. Es NULL en las operaciones de creación, porque
    # todavía no existe ningún registro al que apuntar.
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, verbose_name='Modelo afectado')
    object_id = models.CharField(max_length=50, null=True, blank=True)
    objeto_afectado = GenericForeignKey('content_type', 'object_id')

    # Texto legible del registro afectado, congelado al crear ('Especialista B
    # (Contabilidad)'). Necesario para que el listado y las notificaciones sigan siendo
    # comprensibles después de aprobar una eliminación: en ese momento el registro ya no
    # existe y la GenericForeignKey devuelve None.
    descriptor = models.CharField(max_length=200, blank=True, default='')

    datos_originales = models.JSONField(default=dict, blank=True)
    datos_propuestos = models.JSONField(default=dict, blank=True)

    # Contexto para el filtro del Administrador y para resolver a quién se notifica.
    # NULL en las solicitudes de NCargo, que es un nomenclador global sin unidad; esas
    # se notifican a todos los administradores activos.
    unidad = models.ForeignKey(
        'strorganizativa.UnidadOrganizativa', on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='Unidad Organizativa')

    motivo = models.TextField(verbose_name='Motivo de la solicitud')
    motivo_decision = models.TextField(
        blank=True, default='', verbose_name='Motivo de la decisión')

    # Bloqueo de revisión. Los dos campos van juntos: `revisor` dice quién la tiene
    # abierta y `revision_iniciada` desde cuándo, que es lo que permite caducar el
    # bloqueo. Cancelar la revisión los pone a NULL.
    revisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_en_revision', verbose_name='En revisión por')
    revision_iniciada = models.DateTimeField(null=True, blank=True)

    decidida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_decididas', verbose_name='Decidida por')
    fecha_decision = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Solicitud'
        verbose_name_plural = 'Solicitudes'
        ordering = ['-created_at']
        constraints = [
            # Impide dos solicitudes sin decidir sobre el mismo registro. Sin esto, un
            # Administrador podría aprobar dos cambios contradictorios sobre lo mismo, y
            # el segundo pisaría al primero sin que nadie lo advirtiera. Aplica también
            # entre operaciones distintas (editar y eliminar el mismo departamento a la
            # vez), que es justo el caso peligroso. No cubre las creaciones, que no
            # apuntan a ningún registro todavía.
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                condition=Q(estado__in=['E', 'R'], object_id__isnull=False),
                name='solicitud_unica_pendiente_por_registro',
            ),
        ]
        indexes = [
            # Los dos accesos reales del listado: «mis solicitudes por estado» para el
            # Moderador y «todas las de esta unidad por estado» para el Administrador.
            models.Index(fields=['estado', 'solicitante']),
            models.Index(fields=['estado', 'unidad']),
        ]

    def __str__(self):
        return f'{self.etiqueta_operacion} — {self.descriptor or "(sin descripción)"}'

    # ------------------------------------------------------------------
    # Lectura del registro de operaciones
    # ------------------------------------------------------------------

    @property
    def definicion(self):
        """Entrada de `OPERACIONES` para esta solicitud, o None si la clave ya no existe.

        Devuelve None en vez de fallar para que una operación retirada del registro no
        rompa el listado entero: la fila se sigue viendo, solo pierde las acciones.
        Import local porque `operaciones.py` importa formularios que importan modelos.
        """
        from solicitudes.operaciones import OPERACIONES
        return OPERACIONES.get(self.operacion)

    @property
    def etiqueta_operacion(self):
        definicion = self.definicion
        return definicion['etiqueta'] if definicion else self.operacion

    @property
    def accion(self):
        definicion = self.definicion
        return definicion['accion'] if definicion else None

    @property
    def es_eliminacion(self):
        return self.accion == AccionSolicitud.ELIMINAR

    @property
    def es_creacion(self):
        return self.accion == AccionSolicitud.CREAR

    # ------------------------------------------------------------------
    # Estado y bloqueo
    # ------------------------------------------------------------------

    @property
    def pendiente(self):
        """Sin decidir todavía, esté o no bloqueada por una revisión en curso."""
        return self.estado in EstadoSolicitud.pendientes()

    @property
    def decidida(self):
        return self.estado in (EstadoSolicitud.APROBADA, EstadoSolicitud.RECHAZADA)

    @property
    def bloqueada(self):
        """True si un Administrador la tiene abierta y el bloqueo no ha caducado.

        Se calcula en lectura en lugar de guardarse: un bloqueo caducado que siguiera
        marcado como activo en base de datos dejaría la solicitud inaccesible hasta que
        alguien la tocara a mano.
        """
        if self.estado != EstadoSolicitud.EN_REVISION or self.revision_iniciada is None:
            return False
        limite = self.revision_iniciada + timedelta(minutes=MINUTOS_BLOQUEO_REVISION)
        return timezone.now() < limite

    @property
    def bloqueada_por_nombre(self):
        if not self.bloqueada or self.revisor is None:
            return ''
        return self.revisor.get_full_name() or self.revisor.username

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------
    # Se resuelven aquí y no en cada vista porque son las reglas del módulo, no de una
    # pantalla concreta: el listado, el detalle, la edición y el borrado necesitan las
    # mismas respuestas y no deben poder divergir entre sí.

    def es_visible_para(self, usuario):
        """El Administrador (y quien tiene el permiso «Resolver solicitudes») ve todas;
        el Moderador solo las suyas."""
        from usuarios.permisos_especiales import puede_resolver
        if puede_resolver(usuario):
            return True
        if getattr(usuario, 'es_moderador', False):
            return self.solicitante_id == usuario.pk
        return False

    def puede_editarla(self, usuario):
        """Solo el Moderador autor, solo mientras siga En Espera y nadie la revise.

        El Administrador no edita la solicitud por esta vía: modifica la propuesta desde
        la pantalla de revisión, que es un flujo distinto con su propia decisión al final.
        """
        if not getattr(usuario, 'es_moderador', False):
            return False
        if self.solicitante_id != usuario.pk:
            return False
        return self.pendiente and not self.bloqueada

    def puede_retirarla(self, usuario):
        """Retirar es que el propio autor elimine su solicitud antes de que la revisen.

        Mismas condiciones que editarla: si un Administrador ya está dentro, el autor no
        puede quitarle de las manos lo que está revisando.
        """
        return self.puede_editarla(usuario)

    def puede_revisarla(self, usuario):
        """Cualquier Administrador (o Moderador con «Resolver solicitudes», también la suya),
        si está pendiente y no la tiene abierta otro."""
        from usuarios.permisos_especiales import puede_resolver
        if not puede_resolver(usuario, self):
            return False
        if not self.pendiente:
            return False
        return not self.bloqueada or self.revisor_id == usuario.pk

    def puede_eliminarla(self, usuario):
        """Borrado físico. El Administrador puede con cualquiera; el Moderador solo
        retira la suya (ver `puede_retirarla`)."""
        if getattr(usuario, 'es_admin', False) or usuario.is_superuser:
            return True
        return self.puede_retirarla(usuario)


class EstadoPersonalizada(models.TextChoices):
    ABIERTA = 'ABI', 'Abierta'
    ATENDIDA = 'ATE', 'Atendida'
    CERRADA = 'CER', 'Cerrada sin cambios'


class SolicitudPersonalizada(Base):
    """Mensaje directo del Moderador al Administrador (decisión de RRHH del
    24-10-2026), para lo que no tiene una solicitud propia: sobre todo, un error
    en el contrato vigente (cargo, tipo, fecha de contratación…) que no se puede
    corregir editando el contrato porque falsearía el histórico. El Administrador
    responde una vez y la cierra; la corrección en sí la hace él (admin de Django
    o, más adelante, el editor del histórico).

    No toca ningún registro: es solo la comunicación, con su respuesta.
    """

    asunto = models.CharField(max_length=150)
    descripcion = models.TextField(verbose_name='Descripción')
    # El trabajador del que se habla, si lo hay. SET_NULL: si causa baja, el contrato
    # se borra y la solicitud tiene que seguir explicándose sola (`trabajador_texto`).
    contrato = models.ForeignKey(
        'contratos.CAlta', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_personalizadas', verbose_name='Trabajador')
    trabajador_texto = models.CharField(max_length=200, blank=True, default='')
    unidad = models.ForeignKey(
        'strorganizativa.UnidadOrganizativa', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')

    estado = models.CharField(max_length=3, choices=EstadoPersonalizada.choices,
                              default=EstadoPersonalizada.ABIERTA, db_index=True)
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='solicitudes_personalizadas')
    solicitante_nombre = models.CharField(max_length=150, blank=True, default='')

    respuesta = models.TextField(blank=True, default='')
    respondida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    fecha_respuesta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Solicitud personalizada'
        verbose_name_plural = 'Solicitudes personalizadas'
        ordering = ['-created_at']

    def __str__(self):
        return self.asunto

    @property
    def abierta(self):
        return self.estado == EstadoPersonalizada.ABIERTA
