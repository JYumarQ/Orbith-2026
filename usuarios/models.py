from datetime import timedelta
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from strorganizativa.models import UnidadOrganizativa
from contratos.models import CAlta
from django.core.exceptions import ValidationError
from django.db.models import Q, CheckConstraint

UMBRAL_CONECTADO = timedelta(minutes=5)

# --- Protección contra fuerza bruta en el inicio de sesión ---
# Tras MAX_INTENTOS_FALLIDOS fallos dentro de VENTANA_BLOQUEO, la cuenta no admite
# más intentos hasta que la ventana se vacía. Los valores viven aquí (y no en
# settings) porque son una regla del módulo de usuarios, no configuración del
# despliegue.
MAX_INTENTOS_FALLIDOS = 10
VENTANA_BLOQUEO = timedelta(minutes=5)
# Cuánto se conservan los intentos ya caducados, solo como rastro para el
# Administrador. Se purgan solos (ver `limpiar_tras_acceso_correcto`).
RETENCION_INTENTOS = timedelta(days=30)

# Create your models here.
class CustomUser(AbstractUser):

    #? DATOS PERSONALES
    contrato = models.OneToOneField(CAlta, on_delete=models.SET_NULL, null=True, blank=True)

    unidades = models.ManyToManyField(UnidadOrganizativa, blank=True)

    es_admin = models.BooleanField(default=False)
    es_moderador = models.BooleanField(default=False)
    es_observador = models.BooleanField(default=False)
    fecha_creado = models.DateField(auto_now_add=True)
    fecha_actualizado = models.DateTimeField(auto_now=True)

    avatar = models.ImageField(
        upload_to='img/avatares/',
        blank=True,
        null=True,
        verbose_name="Foto de perfil"
    )

    #? SESIÓN / CONEXIÓN
    # Campos operativos, NO de permisos. Se escriben SIEMPRE con
    # CustomUser.objects.filter(pk=...).update(...), nunca con instancia.save():
    # save() (ver más abajo) ejecuta full_clean() y reajusta roles en cada
    # llamada, y estos campos se actualizan con demasiada frecuencia para pagar
    # ese costo (mismo motivo por el que PreferenciasUsuario vive aparte).
    ultima_actividad = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Última actividad")
    sesion_invalidada_en = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Sesión invalidada en")

    class Meta:
        verbose_name = ("Usuario")
        verbose_name_plural = ("Usuarios")
        constraints = [
            # Un usuario solo puede tener UN rol activo
            CheckConstraint(
                check=(
                    Q(es_admin=True) & Q(es_moderador=False) & Q(es_observador=False) |
                    Q(es_admin=False) & Q(es_moderador=True) & Q(es_observador=False) |
                    Q(es_admin=False) & Q(es_moderador=False) & Q(es_observador=True) 

                ),
                name='exactamente_un_rol'
            )
        ]
        
    def clean(self):
        super().clean()
        roles_activos = sum([self.es_admin, self.es_moderador, self.es_observador])
        if roles_activos == 0:
            raise ValidationError("El usuario debe tener al menos un rol asignado (Administrador, Moderador o Observador).")
        if roles_activos > 1:
            raise ValidationError("El usuario no puede tener más de un rol activo.")
#no levantar para permitir autocorreccion en save
#if self.es_admin and self.es_moderador:
#raise ValidationError('No puede ser Administrador y Moderador a la vez.')

    def save(self, *args, **kwargs):
        # Resolución de conflictos (si hay más de un rol, prioriza Admin > Moderador > Observador)
        if self.es_admin and self.es_moderador:
            self.es_moderador = False
        if self.es_admin and self.es_observador:
            self.es_observador = False
        if self.es_moderador and self.es_observador:
            self.es_observador = False

        # Permisos de staff/superuser
        self.is_staff = bool(self.es_admin)
        self.is_superuser = bool(self.es_admin)

        # 👇 Ejecuta validaciones antes de guardar
        self.full_clean()  # Lanza ValidationError si roles_activos == 0 o > 1

        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # DATOS PARA EL PERFIL
    # Los datos personales NO viven en first_name/last_name (el proyecto no los
    # usa): siempre se leen del trabajador vinculado (contrato -> aspirante).
    # Todas estas propiedades devuelven None si no hay contrato vinculado, para
    # que la plantilla pueda mostrar "Sin trabajador vinculado".
    # ------------------------------------------------------------------
    @property
    def aspirante_vinculado(self):
        """Trabajador asociado al usuario, o None si es una cuenta sin contrato."""
        if self.contrato_id and self.contrato:
            return self.contrato.aspirante
        return None

    @property
    def nombre_completo(self):
        asp = self.aspirante_vinculado
        if not asp:
            return None
        partes = [asp.nombre, asp.papellido, asp.sapellido]
        return " ".join(p for p in partes if p).strip() or None

    @property
    def cargo_actual(self):
        """Descripción del cargo que ocupa hoy el trabajador vinculado."""
        contrato = self.contrato if self.contrato_id else None
        if contrato and contrato.cargo and contrato.cargo.ncargo:
            return contrato.cargo.ncargo.descripcion
        return None

    @property
    def rol_descripcion(self):
        if self.es_admin:
            return "Administrador"
        if self.es_moderador:
            return "Moderador"
        if self.es_observador:
            return "Observador"
        return "Sin rol asignado"

    @property
    def esta_conectado(self):
        """Conectado = actividad registrada dentro del umbral. Independiente de
        `is_active`: una cuenta desactivada puede, en teoría, seguir figurando
        conectada hasta que su última actividad expire."""
        if not self.ultima_actividad:
            return False
        return timezone.now() - self.ultima_actividad <= UMBRAL_CONECTADO

    def obtener_preferencias(self):
        """Devuelve las preferencias del usuario, creándolas la primera vez."""
        preferencias, _ = PreferenciasUsuario.objects.get_or_create(usuario=self)
        return preferencias


class PreferenciasUsuario(models.Model):
    """Preferencias personales de interfaz.

    Va en un modelo aparte y no como campos de CustomUser a propósito:
    CustomUser.save() ejecuta full_clean() y reajusta los roles en cada guardado,
    y no queremos disparar esa lógica cada vez que alguien pliega la barra lateral.
    """

    usuario = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='preferencias',
        verbose_name="Usuario"
    )
    sidebar_colapsada = models.BooleanField(
        default=False,
        verbose_name="Barra lateral colapsada por defecto"
    )
    animaciones_activas = models.BooleanField(
        default=True,
        verbose_name="Animaciones de la interfaz activas"
    )

    # --- Firmas del Reporte de Pago (Pre-Nómina) ---
    # Los tres nombres que imprime el encabezado del reporte se escriben una vez
    # y se arrastran a TODOS los reportes que cree ese usuario, hasta que él
    # mismo los cambie. Van aquí y no en `ReportePago` porque son una comodidad
    # de quien prepara la nómina, no un dato del documento: cada reporte guarda
    # su propia copia congelada en el momento de crearse.
    #
    # Son preferencias de interfaz como las dos de arriba, así que comparten
    # tabla y el mismo motivo para no vivir en `CustomUser`: guardarlas no debe
    # disparar el `full_clean()` ni el reajuste de roles de `CustomUser.save()`.
    reporte_hecho_por = models.CharField(
        max_length=150, blank=True, default='',
        verbose_name="Reporte de pago — Hecho por"
    )
    reporte_revisado_por = models.CharField(
        max_length=150, blank=True, default='',
        verbose_name="Reporte de pago — Revisado por"
    )
    reporte_aprobado_por = models.CharField(
        max_length=150, blank=True, default='',
        verbose_name="Reporte de pago — Aprobado por"
    )

    fecha_actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Preferencias de usuario"
        verbose_name_plural = "Preferencias de usuarios"

    def __str__(self):
        return f"Preferencias de {self.usuario.username}"

class IntentoAcceso(models.Model):
    """Un intento de inicio de sesión FALLIDO. Solo se guardan los fallos.

    Existe para frenar la fuerza bruta: antes, `/accounts/login/` admitía
    intentos ilimitados y un script podía probar miles de contraseñas contra una
    cuenta de Recursos Humanos sin que nada lo detuviera ni dejara rastro.

    **El bloqueo se cuenta por nombre de usuario, no por IP.** La IP se guarda
    únicamente como dato para el Administrador, porque la cabecera de la que se
    obtiene se puede falsificar (ver `usuarios.utils.obtener_ip`) y porque, tras
    un proxy, todas las peticiones compartirían la misma IP: bloquear por IP
    dejaría fuera a toda la empresa de golpe.

    La consecuencia conocida de contar por usuario es que alguien puede dejar
    bloqueada la cuenta de otro fallando diez veces a propósito. Con una ventana
    de 5 minutos la molestia es pequeña y el Administrador puede desbloquear al
    instante (ver `desbloquear`); a cambio, ningún usuario legítimo queda fuera
    por culpa del tráfico de un compañero.
    """

    # Se normaliza a minúsculas al escribir para que "Pedro" y "pedro" cuenten
    # como la misma cuenta: si no, bastaría alternar mayúsculas para no llegar
    # nunca al límite.
    username = models.CharField(max_length=150, verbose_name="Usuario intentado")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP de origen")
    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Fecha del intento")

    class Meta:
        verbose_name = "Intento de acceso fallido"
        verbose_name_plural = "Intentos de acceso fallidos"
        ordering = ['-fecha']
        indexes = [
            # El índice compuesto cubre la única consulta que se hace: los
            # intentos de UN usuario dentro de una ventana de tiempo.
            models.Index(fields=['username', 'fecha']),
            models.Index(fields=['fecha']),
        ]

    def __str__(self):
        return f'Intento fallido de «{self.username}» el {self.fecha:%d/%m/%Y %H:%M}'

    # ------------------------------------------------------------------
    @staticmethod
    def normalizar(username):
        return (username or '').strip().lower()[:150]

    @classmethod
    def bloqueado_hasta(cls, username):
        """Instante en que se levanta el bloqueo, o None si la cuenta no lo está.

        Es una ventana deslizante: se miran los `MAX_INTENTOS_FALLIDOS` fallos
        más recientes y, si todos caben dentro de `VENTANA_BLOQUEO`, la cuenta
        sigue bloqueada hasta que el más antiguo de ellos salga de la ventana.
        Así el bloqueo se disuelve solo, sin ninguna tarea programada.
        """
        nombre = cls.normalizar(username)
        if not nombre:
            return None

        desde = timezone.now() - VENTANA_BLOQUEO
        fechas = list(
            cls.objects.filter(username=nombre, fecha__gte=desde)
            .order_by('-fecha')
            .values_list('fecha', flat=True)[:MAX_INTENTOS_FALLIDOS]
        )
        if len(fechas) < MAX_INTENTOS_FALLIDOS:
            return None
        # `fechas[-1]` es el más ANTIGUO de los que se han traído.
        return fechas[-1] + VENTANA_BLOQUEO

    @classmethod
    def registrar_fallo(cls, username, ip=None):
        """Anota un fallo. Devuelve el objeto creado, o None si no se anotó nada.

        No se anota nada si la cuenta YA está bloqueada: si cada intento durante
        el bloqueo alargara la ventana, un usuario legítimo que reintenta a los
        dos minutos se auto-castigaría cinco minutos más, y el bloqueo no
        terminaría nunca mientras alguien siguiera probando.
        """
        nombre = cls.normalizar(username)
        if not nombre:
            return None
        if cls.bloqueado_hasta(nombre):
            return None
        return cls.objects.create(username=nombre, ip=ip)

    @classmethod
    def limpiar_tras_acceso_correcto(cls, username):
        """Borra los fallos de esa cuenta: ya demostró conocer su contraseña.

        Aprovecha para purgar los intentos de cualquier cuenta más viejos que
        `RETENCION_INTENTOS`. Se hace aquí porque los inicios de sesión correctos
        son poco frecuentes (unas decenas al día) y así la tabla se mantiene sola,
        sin depender de que alguien ejecute una tarea programada.
        """
        nombre = cls.normalizar(username)
        if nombre:
            cls.objects.filter(username=nombre).delete()
        cls.objects.filter(fecha__lt=timezone.now() - RETENCION_INTENTOS).delete()

    @classmethod
    def desbloquear(cls, username):
        """Levanta el bloqueo de una cuenta a mano (acción de Administrador)."""
        return cls.objects.filter(username=cls.normalizar(username)).delete()
