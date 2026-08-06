import logging
import threading
from decimal import Decimal
from django.core.signals import request_started
from django.db import models
from django.db.models.signals import post_delete, post_save
from bolsa.models import Aspirante
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa
from nomencladores.models import NTridente, NSalario, NJornada, NCausaAltaBaja, NRol, NTipoContrato, NMotivoContrato
from django.core.validators import MinValueValidator
from datetime import timedelta
from django.utils import timezone
from auditoria.models import Base
from django.core.exceptions import ValidationError
from contratos.salarios import calcular_salario


logger = logging.getLogger(__name__)


# ==================== CACHÉ DE LA ESCALA SALARIAL ====================
# `NSalario` es un nomenclador diminuto (una fila por combinación grupo/rol/tridente)
# que antes se consultaba UNA VEZ POR CONTRATO desde `_buscar_monto_salario`. En el
# dashboard eso producía 14 consultas idénticas por carga, y en el listado de
# contratos una por fila.
#
# La caché es por PETICIÓN (`threading.local` + `request_started`), no global: así no
# puede sobrevivir a un rollback de transacción — un caché de módulo dejaría datos de
# un test revertido visibles para el siguiente. Dentro de una misma petición también
# se invalida si alguien edita la escala.
_local_escala = threading.local()


def _obtener_escala_salarial():
    """`{(grupo_escala_id, rol_id, tridente_id): monto}` de toda la escala."""
    escala = getattr(_local_escala, 'valores', None)
    if escala is None:
        escala = {
            (grupo_id, rol_id, tridente_id): monto
            for grupo_id, rol_id, tridente_id, monto in NSalario.objects.values_list(
                'grupo_escala_id', 'rol_id', 'tridente_id', 'monto')
        }
        _local_escala.valores = escala
    return escala


def invalidar_escala_salarial(**kwargs):
    _local_escala.valores = None


request_started.connect(invalidar_escala_salarial, dispatch_uid='contratos_escala_salarial')
post_save.connect(invalidar_escala_salarial, sender=NSalario, dispatch_uid='contratos_escala_save')
post_delete.connect(invalidar_escala_salarial, sender=NSalario, dispatch_uid='contratos_escala_delete')


# Los movimientos de baja se crean DELIBERADAMENTE sin contrato (véase la creación del
# movimiento de baja en `contratos/views.py`), porque el contrato se borra justo después.
# Es el diseño del histórico inmutable, no un defecto, así que el reenganche los excluye.
#
# Se compara por el texto porque `TMovimiento.tipo_movimiento` es un CharField libre, sin
# `choices`. Si algún día ese literal cambia en views.py, hay que cambiarlo aquí también
# (y en `subsanacion/reglas/nomina.py`, que tiene su propia copia por el mismo motivo).
TIPO_MOVIMIENTO_BAJA = 'Baja'


#?CONTRATO
class ContratoBase(Base):
    
    aspirante = models.ForeignKey(Aspirante, on_delete=models.RESTRICT, related_name="%(class)s_contratos")
    no_expediente = models.CharField(
        max_length=5, 
        unique=True,
        verbose_name="No. Expediente"
    )
    #?CONTRATO
    tipo = models.ForeignKey(
        NTipoContrato, 
        on_delete=models.RESTRICT, 
        null=True,  # Para que no de error la migración inicial
        blank=True,
        verbose_name="Tipo de Contrato"
    )

    motivo = models.ForeignKey(
        NMotivoContrato,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        verbose_name="Motivo de Contrato"
    )
    
    cargo = models.ForeignKey(CargoPlantilla, on_delete=models.RESTRICT, blank=True, null= True)
    
    reg_militar = models.TextField(max_length=3, choices=[
        ('MTT', 'MTT'),
        ('IMP', 'Imprescindible'),
        ('BPD', 'BPD'),
        ('NIN', 'No Incorporado')
    ], blank=True, null= True)
        
    #?CHOFER
    profesional = models.BooleanField(default=False)

    #?MISION
    mision = models.BooleanField(default=False, verbose_name="Misión")
    pais = models.CharField(max_length=100, null=True, blank=True, verbose_name="País")
    
    
    class Meta:
        verbose_name = ("Contrato")
        verbose_name_plural = ("Contratos")
        abstract = True
        
    
    def __str__(self):
        return self.aspirante.nombre

class CAlta(ContratoBase):
    
    duracion = models.IntegerField(null=True, blank=True)
    
     #?CALIFICACION
    c_formal = models.BooleanField(default=False)    
    
    c_formal_res = models.TextField(max_length=7, null=True, blank=True)    
    funcionario_res = models.TextField(max_length=7, null=True, blank=True)    
    designado_res = models.TextField(max_length=7, null=True, blank=True)
    
    #?SALARIO
    tipo_salario = models.CharField(max_length=3, choices=[
        ('FIJ', 'Fijo'),
        ('DIN', 'Dinámico')
    ], default='DIN')

    rol = models.ForeignKey(
        NRol,
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
        verbose_name="Rol de Pago"
    )

    tridente = models.ForeignKey(
        NTridente,
        on_delete=models.RESTRICT,
        blank=True,
        null= True
        )
    maestria = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)], null=True, blank=True)
    doctorado = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)], null=True, blank=True)
    cnci = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=6, decimal_places=2, null=True, blank=True)
    instructor = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    
    
    jornada = models.ForeignKey(NJornada, blank=True, null=True, on_delete=models.RESTRICT)

    cla = models.ForeignKey(
        'nomencladores.NCondicionLaboralAnormal', 
        on_delete=models.RESTRICT, 
        null=True, blank=True, 
        related_name='contratos_cla',
        verbose_name="Condición Laboral Anormal (CLA)"
    )
    nocturnidad_1 = models.ForeignKey(
        'nomencladores.NCondicionLaboralAnormal', 
        on_delete=models.RESTRICT, 
        null=True, blank=True, 
        related_name='contratos_noct1',
        verbose_name="Nocturnidad 1"
    )
    nocturnidad_2 = models.ForeignKey(
        'nomencladores.NCondicionLaboralAnormal', 
        on_delete=models.RESTRICT, 
        null=True, blank=True, 
        related_name='contratos_noct2',
        verbose_name="Nocturnidad 2"
    )

    fecha_vence_lic = models.DateField(null=True, blank=True)
    fecha_vence_recal = models.DateField(null=True, blank=True)
    fecha_vence_seg = models.DateField(null=True, blank=True)
    
    fecha_alta = models.DateField(null=True, blank=True)

    jubilado_recontratado = models.BooleanField(default=False)
    en_proceso_movimiento = models.BooleanField(default=False, verbose_name="En Proceso de Movimiento")

    salario_actual = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True, editable=False,
        verbose_name="Salario actual (calculado)",
        help_text="Se recalcula automáticamente en cada guardado. No editar a mano."
    )

    def clean(self):
        super().clean()
        
        # 1. Regla de Exclusividad: No pueden ser iguales
        if self.nocturnidad_1 and self.nocturnidad_2:
            if self.nocturnidad_1_id == self.nocturnidad_2_id:
                raise ValidationError({
                    'nocturnidad_2': "Las dos nocturnidades seleccionadas deben ser diferentes."
                })

        # 2. Blindaje de Seguridad (Lógica limpia)
        for campo in ['nocturnidad_1', 'nocturnidad_2']:
            condicion = getattr(self, campo)
            # Comprobación directa y optimizada
            if condicion and condicion.nocturnidad_id is None:
                raise ValidationError({
                    campo: f"La condición '{condicion.nombre}' no tiene una nocturnidad configurada."
                })
    class Meta:
        verbose_name = ("Alta")
        verbose_name_plural = ("Altas")
        
    @staticmethod
    def actualizar_aspirante(doc_aspirante):
        # CAMBIO: Ahora actualizamos el ESTADO a 'ACTIVO'
        aspirante = Aspirante.objects.filter(doc_identidad = doc_aspirante).first()
        if aspirante:
            aspirante.estado = 'ACTIVO'
            aspirante.save()
        
    @staticmethod
    def actualizar_plantilla(cargo_id):
        """Recalcula la cantidad cubierta del cargo contando los contratos reales."""
        cargo = CargoPlantilla.objects.filter(pk=cargo_id).first()
        if cargo:
            cargo.refrescar_conteo_plazas()
        
    @staticmethod
    def _buscar_monto_salario(grupo_escala_id, rol_id, tridente_id):
        """Busca el monto de una combinación de la escala. None si no existe la fila.

        La clave usa los `_id` directamente, así que `rol_id=None` corresponde a un
        cuadro (sin tridente) o a la escala del grupo sin rol concreto — el mismo
        criterio que el `rol IS NULL` de la consulta que había antes aquí.

        Lee de `_obtener_escala_salarial()` (una sola consulta por petición) en vez de
        consultar la base de datos en cada llamada.
        """
        return _obtener_escala_salarial().get((grupo_escala_id, rol_id, tridente_id))

    def calcular_salario_escala(self):
        """Salario de escala de este contrato, o None si no se puede calcular.

        El árbol de decisión vive en `contratos/salarios.py`, que es la única fuente de
        verdad del cálculo. Aquí solo se extraen los datos del contrato y se delega, de
        modo que el módulo de Subsanación pueda usar EXACTAMENTE el mismo cálculo sin
        consultar la base de datos por cada fila.
        """
        try:
            cargo = self.cargo
            ncargo = cargo.ncargo if cargo else None

            return calcular_salario(
                tipo_salario=self.tipo_salario,
                tiene_cargo=bool(cargo),
                es_cuadro=bool(ncargo.es_cuadro) if ncargo else False,
                grupo_escala_id=ncargo.grupo_escala_id if ncargo else None,
                rol_id_contrato=self.rol_id,
                rol_id_cargo=cargo.rol_id if cargo else None,
                tridente_id=self.tridente_id,
                salario_basico=ncargo.salario_basico if ncargo else None,
                buscar_monto=self._buscar_monto_salario,
            )
        except Exception as e:
            # Se devuelve None para no romper listados ni informes, pero el error se
            # registra: antes cualquier fallo de cálculo desaparecía sin rastro.
            logger.exception("No se pudo calcular el salario de escala del contrato %s: %s", self.pk, e)
            return None

    @property
    def funcionario(self):
        return self.cargo.funcionario if self.cargo else False

    @property
    def designado(self):
        return self.cargo.designado if self.cargo else False
    
    @property
    def fecha_vencimiento(self):
        if not self.fecha_alta or self.duracion is None:
            return None
        return self.fecha_alta + timedelta(days=self.duracion)

    @property
    def dias_restantes(self):
        venc = self.fecha_vencimiento
        if not venc:
            return None
        hoy   = timezone.localdate()
        delta = (venc - hoy).days
        return delta
        
    def get_director(self):
        if self.cargo and self.cargo.ncargo.cat_ocupacional != 'CDI' and self.cargo.ncargo.cat_ocupacional != 'CEJ':
            director = CAlta.objects.filter(cargo__ncargo__cat_ocupacional__in=['CDI','CEJ']).first()
            return director
        else:
            return 'Es Director' 
    
    

    @property
    def salario_total(self):
        """ ALIAS MÁGICO: Evita que el frontend falle al pedir 'salario_total' """
        return self.calcular_salario_escala()
    
    @property
    def fecha_ultima_accion(self):
        """Devuelve la fecha del último evento. (fecha_alta garantizada por validación)"""
        from .models import TMovimiento
        ultimo_mov = TMovimiento.objects.filter(
            aspirante=self.aspirante, 
            no_expediente=self.no_expediente
        ).order_by('-fecha_efectiva').first()
        
        return ultimo_mov.fecha_efectiva if ultimo_mov else self.fecha_alta

    def movimientos_huerfanos_reenganchables(self):
        """Movimientos del histórico que son de este contrato pero quedaron sueltos.

        `TMovimiento.contrato` es SET_NULL a propósito: al dar de baja al trabajador se
        borra su CAlta y los movimientos sobreviven con el enlace en blanco. El problema
        aparece al recontratarlo reutilizando el mismo número de expediente: el contrato
        nuevo es OTRA fila, así que ese histórico anterior no vuelve solo y no aparece al
        abrir el histórico del trabajador desde su contrato.

        El criterio es deliberadamente estricto: mismo aspirante y mismo `no_expediente`
        EXACTO. No hay ambigüedad posible en el destino, porque `no_expediente` es único
        entre los contratos vivos, así que solo este contrato puede reclamarlos. Los
        movimientos de tipo «Baja» se excluyen: están sin contrato por diseño.

        Este método define el criterio en un solo sitio; lo usan tanto `save()` como el
        comando `reenganchar_movimientos`.
        """
        if not self.pk or not self.aspirante_id or not self.no_expediente:
            return TMovimiento.objects.none()

        return (TMovimiento.objects
                .filter(contrato__isnull=True,
                        aspirante_id=self.aspirante_id,
                        no_expediente=self.no_expediente)
                .exclude(tipo_movimiento__iexact=TIPO_MOVIMIENTO_BAJA))

    def reenganchar_movimientos_huerfanos(self):
        """Reasocia a este contrato su histórico suelto. Devuelve cuántos reenganchó."""
        return self.movimientos_huerfanos_reenganchables().update(contrato=self)

    def save(self, *args, **kwargs):
        try:
            es_nuevo = self._state.adding

            # Cargo que tenía antes, para liberar su plaza si cambió
            cargo_anterior_id = None
            if not es_nuevo:
                anterior = CAlta.objects.filter(pk=self.pk).values('cargo_id').first()
                if anterior:
                    cargo_anterior_id = anterior['cargo_id']

            # EL ESCUDO: Asignación y Limpieza real en base de datos
            if self.tipo_salario == 'DIN' and not self.tridente:
                from nomencladores.models import NTridente
                self.tridente = NTridente.objects.filter(tipo='I').first()
            elif self.tipo_salario == 'FIJ':
                self.tridente = None  # Obligamos a que el fijo sea NULL

            if es_nuevo:
                self.actualizar_aspirante(self.aspirante.doc_identidad)

            super().save(*args, **kwargs)

            # Recalcular el salario cacheado DESPUÉS del primer save
            # (necesita que self.pk y las relaciones ya estén resueltas)
            nuevo_salario = self.calcular_salario_escala()
            if nuevo_salario != self.salario_actual:
                CAlta.objects.filter(pk=self.pk).update(salario_actual=nuevo_salario)
                self.salario_actual = nuevo_salario

            if es_nuevo:
                # Recontratación: recuperar el histórico que se quedó huérfano cuando se
                # borró el contrato anterior de esta misma persona.
                #
                # Va en su propio try/except, y no en el general de abajo, a propósito: el
                # reenganche es una recuperación de histórico, no parte de la contratación.
                # Si fallara, el contrato debe guardarse igual; el aviso queda en el log y
                # el comando `reenganchar_movimientos` lo repara después.
                try:
                    reenganchados = self.reenganchar_movimientos_huerfanos()
                    if reenganchados:
                        logger.info(
                            "Recontratación: reenganchados %s movimiento(s) huérfanos al "
                            "contrato %s (expediente %s, aspirante %s).",
                            reenganchados, self.pk, self.no_expediente, self.aspirante_id)
                except Exception:
                    logger.exception(
                        "No se pudieron reenganchar los movimientos huérfanos del "
                        "contrato %s (expediente %s). El contrato SÍ se guardó; ejecute "
                        "el comando reenganchar_movimientos para repararlo.",
                        self.pk, self.no_expediente)

            # Recalculamos DESPUÉS de guardar, para contar la realidad
            if self.cargo_id:
                self.actualizar_plantilla(self.cargo_id)
            if cargo_anterior_id and cargo_anterior_id != self.cargo_id:
                self.actualizar_plantilla(cargo_anterior_id)

            # Alertas de campos vacíos/inconsistencias (Subsanación en caliente) y
            # aviso de alta. Cada una en su propio try/except: son avisos, no parte
            # de la contratación; si fallaran, el contrato debe guardarse igual.
            try:
                from notificaciones.avisos import avisar_hallazgos_en_caliente
                avisar_hallazgos_en_caliente(self)
            except Exception:
                logger.exception(
                    "No se pudieron evaluar/notificar las alertas de integridad "
                    "del contrato %s.", self.pk)

            if es_nuevo:
                try:
                    from notificaciones.avisos import avisar_alta_contrato
                    avisar_alta_contrato(self)
                except Exception:
                    logger.exception(
                        "No se pudo notificar el alta del contrato %s.", self.pk)

        except Exception as e:
            logger.exception("Error al guardar el contrato %s: %s", self.pk, e)
            raise

    def delete(self, *args, **kwargs):
        # Guardamos el cargo ANTES de borrar, porque después ya no podremos leerlo
        cargo_id_afectado = self.cargo_id

        try:
            # 1. Mover Aspirante a BAJA
            if self.aspirante:
                try:
                    aspirante_obj = Aspirante.objects.get(pk=self.aspirante.pk)
                    aspirante_obj.estado = 'BAJA'
                    aspirante_obj.save()
                except Aspirante.DoesNotExist:
                    pass

            # Aviso de baja ANTES de super().delete(): tiene que apuntar al
            # Aspirante (que sigue existiendo), no a este CAlta, que a partir de
            # aquí queda inaccesible.
            try:
                from notificaciones.avisos import avisar_baja_contrato
                avisar_baja_contrato(self)
            except Exception:
                logger.exception(
                    "No se pudo notificar la baja del contrato %s.", self.pk)

        except Exception as e:
            logger.exception("Error al eliminar el contrato %s: %s", self.pk, e)

        super().delete(*args, **kwargs)

        # 2. Recalculamos la plaza DESPUÉS de borrar, contando la realidad
        if cargo_id_afectado:
            self.actualizar_plantilla(cargo_id_afectado)


    def __str__(self):
        return self.aspirante.nombre

class CBaja(ContratoBase):
    
    no_expediente = models.CharField(max_length=5, unique=False)

    fecha_baja = models.DateField(null=True, blank=True)
    fecha_alta = models.DateField(null=True, blank=True) # Necesario para guardar el historial
    fecha_documento = models.DateField(null=True, blank=True, verbose_name="Fecha de documento")

    tridente = models.ForeignKey(
        NTridente,
        on_delete=models.RESTRICT,
        blank=True, 
        null=True
    )
    
    causa_baja = models.ForeignKey(
        NCausaAltaBaja, 
        on_delete=models.RESTRICT,
        null=True, 
        blank=True
    )

    cobro_sistema_pago = models.BooleanField(
        default=False, 
        verbose_name="Cobró sistema de pago"
    )

    completar_cargo = models.BooleanField(
        default=True, 
        verbose_name="Completar cargo"
    )

    actividad_realizada = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Actividad que realizaba"
    )

    observaciones = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Observaciones de la Baja")
    
    # Asumo que 'observaciones' viene de 'Base', si no, agrégalo aquí también.

    class Meta:
        verbose_name = ("Baja")
        verbose_name_plural = ("Bajas")

    def __str__(self):
        return self.aspirante.nombre
    

# En contratos/models.py

class TMovimiento(models.Model):
    contrato = models.ForeignKey(CAlta, on_delete=models.SET_NULL, null=True, blank=True, related_name='trazabilidad')
    aspirante = models.ForeignKey('bolsa.Aspirante', on_delete=models.CASCADE, null=True, blank=True)
    no_expediente = models.CharField(max_length=20, null=True, blank=True)

    fecha_movimiento = models.DateField(auto_now_add=True)
    fecha_efectiva = models.DateField()
    
    cargo_anterior = models.CharField(max_length=255)
    cargo_nuevo = models.CharField(max_length=255)
    salario_anterior = models.DecimalField(max_digits=10, decimal_places=2)
    salario_nuevo = models.DecimalField(max_digits=10, decimal_places=2)

    unidad_anterior = models.CharField(max_length=255, null=True, blank=True)
    unidad_nueva = models.CharField(max_length=255, null=True, blank=True)

    # FKs reales (además de los campos de texto de arriba, que se conservan
    # tal cual para mostrar el nombre histórico exacto de la unidad en ese
    # momento). Estas sí son relaciones consultables, usadas únicamente para
    # acotar qué movimientos puede ver un Moderador según sus Unidades
    # Organizativas asignadas — no se muestran en ningún informe ni cambian
    # el texto ya guardado. SET_NULL: borrar una Unidad Organizativa nunca
    # debe bloquear ni borrar historial de movimientos.
    unidad_anterior_fk = models.ForeignKey(
        UnidadOrganizativa, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Unidad Anterior (relación)"
    )
    unidad_nueva_fk = models.ForeignKey(
        UnidadOrganizativa, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Unidad Nueva (relación)"
    )

    # -------------------------------------------------------------
    # NUEVOS CAMPOS AÑADIDOS PARA HISTORIAL INMUTABLE (FOTO EXACTA)
    # -------------------------------------------------------------
    departamento_anterior = models.CharField(max_length=255, null=True, blank=True)
    departamento_nuevo = models.CharField(max_length=255, null=True, blank=True)
    
    grupo_escala_anterior = models.CharField(max_length=50, null=True, blank=True)
    grupo_escala_nuevo = models.CharField(max_length=50, null=True, blank=True)
    
    cat_ocupacional_anterior = models.CharField(max_length=150, null=True, blank=True)
    cat_ocupacional_nuevo = models.CharField(max_length=150, null=True, blank=True)
    
    tipo_salario_anterior = models.CharField(max_length=50, null=True, blank=True)
    tipo_salario_nuevo = models.CharField(max_length=50, null=True, blank=True)

    rol_anterior = models.CharField(max_length=150, null=True, blank=True)
    rol_nuevo = models.CharField(max_length=150, null=True, blank=True)
    
    tridente_anterior = models.CharField(max_length=50, null=True, blank=True)
    tridente_nuevo = models.CharField(max_length=50, null=True, blank=True)
    
    tipo_contrato_anterior = models.CharField(max_length=150, null=True, blank=True)
    tipo_contrato_nuevo = models.CharField(max_length=150, null=True, blank=True)
    
    motivo_anterior = models.CharField(max_length=255, null=True, blank=True)
    motivo_nuevo = models.CharField(max_length=255, null=True, blank=True)
    
    duracion_nueva = models.IntegerField(null=True, blank=True)
    # -------------------------------------------------------------

    tipo_movimiento = models.CharField(max_length=50, default="Movimiento de Nómina")
    usuario = models.CharField(max_length=100, null=True, blank=True) 
    fecha_solicitud = models.DateField(null=True, blank=True, verbose_name="Fecha de Solicitud")
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_efectiva']
        indexes = [
            # Sirve exactamente al `partition_by=[aspirante_id]` +
            # `order_by=[fecha_efectiva, id]` que usa la regla MOV-001 de
            # Subsanación para comprobar la continuidad del histórico salarial
            # (subsanacion/reglas/nomina.py). Sin este índice, PostgreSQL resuelve
            # la partición y el orden de la función de ventana con un `Sort`
            # explícito en memoria (confirmado con EXPLAIN ANALYZE antes de
            # añadirlo); con él, el motor puede recorrer el índice ya ordenado.
            # Con el volumen actual de datos (109 filas) la diferencia es
            # inapreciable, pero el plan de ejecución ya muestra el nodo de
            # ordenamiento que este índice existe para eliminar a medida que la
            # tabla crezca.
            models.Index(fields=['aspirante', 'fecha_efectiva', 'id'],
                         name='contratos_tmov_asp_fecha_id'),
        ]