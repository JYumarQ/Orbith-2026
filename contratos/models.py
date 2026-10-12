import logging
import threading
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.core.signals import request_started
from django.db import models
from django.db.models.signals import post_delete, post_save
from bolsa.models import Aspirante
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa
from nomencladores.models import NTridente, NSalario, NCausaAltaBaja, NRol, NTipoContrato, NMotivoContrato
from django.core.validators import MaxValueValidator, MinValueValidator
from datetime import timedelta
from django.utils import timezone
from auditoria.models import Base
from auditoria.registro_automatico import cambios_derivados, sin_auditoria_automatica
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

    # La Misión (`mision`, `pais`, días e importe) vive solo en `CAlta`: es un
    # dato del contrato vigente. Estaba aquí y por eso `CBaja` tenía también
    # esas columnas, que nunca se rellenaban (la baja no las copia).


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
    # Los cuatro importes que se suman al salario. Todos `Decimal(10, 2)`:
    #
    #  * `maestria` y `doctorado` eran enteros, así que un importe con centavos
    #    se guardaba truncado sin avisar.
    #  * `instructor` era `Decimal(4, 2)`, es decir con tope en 99,99. Cualquier
    #    cuantía de tres cifras era imposible de registrar.
    #
    # El importe se sigue guardando AQUÍ aunque ahora exista un nomenclador
    # (`nomencladores.NImporteGradoCientifico` y `NPagoAdicional`). Es
    # deliberado: el contrato y la nómina que salió de él no deben cambiar
    # porque alguien actualice una cuantía meses después. La regla CTR-019 de
    # Subsanación es la que reclama las diferencias con el nomenclador para que
    # sea una persona quien decida si toca actualizarlas.
    maestria = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))], max_digits=10, decimal_places=2, null=True, blank=True)
    doctorado = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))], max_digits=10, decimal_places=2, null=True, blank=True)
    cnci = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))], max_digits=10, decimal_places=2, null=True, blank=True)
    instructor = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))], max_digits=10, decimal_places=2, null=True, blank=True)

    # Qué entrada del nomenclador se eligió. El importe de arriba es el que
    # cuenta para el cálculo; esto guarda la DESCRIPCIÓN, que sin la referencia
    # se perdería: al reabrir el contrato no habría forma de saber cuál de las
    # opciones se había elegido, solo su cuantía.
    instructor_nomenclador = models.ForeignKey(
        'nomencladores.NPagoAdicional',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contratos_instructor',
        verbose_name='Instructor (nomenclador)')
    cnci_nomenclador = models.ForeignKey(
        'nomencladores.NPagoAdicional',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contratos_cnci',
        verbose_name='CNCI (nomenclador)')
    
    
    # El campo `jornada` (FK a NJornada) se eliminó: ningún contrato lo tenía
    # relleno y el nomenclador estaba vacío y sin interfaz. El tipo de jornada de
    # cada trabajador se gestiona ahora en Pre-Nómina → Calendario.

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
    fecha_alta_entidad = models.DateField(null=True, blank=True)

    jubilado_recontratado = models.BooleanField(default=False)
    en_proceso_movimiento = models.BooleanField(default=False, verbose_name="En Proceso de Movimiento")

    #?MISION
    # País, días e importe solo tienen sentido con `mision` activa: el formulario
    # los vacía al apagarla. Pueden quedar vacíos (el dato puede llegar después
    # del alta) y Subsanación los reclama: CTR-014 el país, CTR-021 días e importe.
    mision = models.BooleanField(default=False, verbose_name="Misión")
    pais = models.CharField(max_length=100, null=True, blank=True, verbose_name="País")
    mision_dias = models.PositiveIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(9999)],
        verbose_name="Días de misión")
    mision_importe = models.DecimalField(
        max_digits=9, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name="Importe de misión")

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

        # 3. UN CARGO FUERA DE PLANTILLA NO ADMITE CONTRATOS QUE OCUPEN PLAZA
        #
        # La regla ya la comprobaban el formulario (`CAltaForm.clean`) y el JS de
        # los tres modales, pero ahí no bastaba: el admin de Django usa su propio
        # formulario, y una importación o un script guardan el modelo directamente.
        # Por esas puertas entraban justo los contratos que Subsanación (CTR-020)
        # tiene que reclamar después. Aquí la regla vive donde vive el dato y la
        # cumple todo el que guarde un CAlta.
        #
        # Se comprueba por `_id` para no disparar una consulta cuando no hay cargo
        # ni tipo, que es el caso de un objeto a medio construir.
        if self.cargo_id and self.tipo_id:
            if self.tipo.ocupa_plaza and not self.cargo.en_plantilla:
                raise ValidationError({
                    'tipo': (
                        f'El cargo "{self.cargo}" está fuera de la plantilla aprobada, '
                        f'por lo que no admite contratos que ocupen plaza.'
                    )
                })
    class Meta:
        verbose_name = ("Alta")
        verbose_name_plural = ("Altas")
        constraints = [
            # Mitad de la "REGLA DE ORO" que SÍ se puede expresar en una CHECK de una
            # sola tabla: un salario Fijo nunca debe tener tridente. Protege incluso
            # contra escrituras que se saltan `save()` (bulk_update, SQL directo).
            #
            # La otra mitad (Cuadro ⇒ sin tridente) depende de NCargo.cat_ocupacional
            # vía `cargo__ncargo`, una tabla relacionada: PostgreSQL no permite un
            # CHECK entre tablas sin un trigger, así que esa mitad se queda a cargo
            # del "escudo" de `save()`, de `CAltaForm.clean()` y de la regla CTR-009
            # de Subsanación.
            models.CheckConstraint(
                check=~models.Q(tipo_salario='FIJ', tridente__isnull=False),
                name='calta_fijo_sin_tridente',
            ),
        ]

    @staticmethod
    def actualizar_aspirante(doc_aspirante):
        # CAMBIO: Ahora actualizamos el ESTADO a 'ACTIVO'
        aspirante = Aspirante.objects.filter(doc_identidad = doc_aspirante).first()
        if aspirante:
            aspirante.estado = 'ACTIVO'
            # Consecuencia del alta: la Auditoría ya registra la creación del contrato.
            with cambios_derivados():
                aspirante.save()
        
    @staticmethod
    def actualizar_plantilla(cargo_id):
        """Recalcula la cantidad cubierta del cargo contando los contratos reales."""
        cargo = CargoPlantilla.objects.filter(pk=cargo_id).first()
        if cargo:
            with cambios_derivados():
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

    def fecha_efectiva_vigente(self):
        """Fecha efectiva del último movimiento de nómina de ESTE contrato, contando
        el alta, que también es un movimiento («Alta Inicial»). Es la «Fecha
        Efectiva de Firma» que propone el Asistente de Exportación Legal para el
        Contrato de Trabajo y su Modificación (antes proponía siempre la de alta).

        Busca por el ENLACE del movimiento (`TMovimiento.contrato`), no por el
        número de expediente como `fecha_ultima_accion`: si el expediente se corrige
        después de crear un movimiento, el movimiento conserva el número viejo y
        por expediente dejaría de encontrarse (decisión de RRHH, 12-10-2026).
        Nunca devuelve una fecha anterior a la de alta del contrato."""
        ultima = self.trazabilidad.aggregate(ultima=models.Max('fecha_efectiva'))['ultima']
        if ultima and (not self.fecha_alta or ultima > self.fecha_alta):
            return ultima
        return self.fecha_alta

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
            #
            # Misma "REGLA DE ORO" que `CAltaForm.clean()` (contratos/forms.py): un
            # Cuadro no usa tridente (calcular_salario() lo ignora para ese caso), así
            # que aquí también hay que anularlo, no solo cuando el salario es Fijo. Sin
            # esta simetría, un guardado que no pase por el formulario (admin de
            # Django, un script, un cargo que pasa a ser Cuadro después del alta)
            # puede dejar un contrato dinámico de Cuadro con tridente asignado.
            ncargo = self.cargo.ncargo if self.cargo_id else None
            es_cuadro = bool(ncargo.es_cuadro) if ncargo else False

            if es_cuadro or self.tipo_salario == 'FIJ':
                self.tridente = None
            elif self.tipo_salario == 'DIN' and not self.tridente:
                from nomencladores.models import NTridente
                self.tridente = NTridente.objects.filter(tipo='I').first()

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

            # Si este guardado corrigió un hallazgo de Subsanación (p. ej. CTR-009,
            # el tridente indebido), lo cierra ya mismo en vez de esperar al próximo
            # análisis completo. Ver el docstring de la función para por qué esto es
            # seguro sin recorrer toda la tabla.
            try:
                from subsanacion.servicios import reconciliar_hallazgos_en_caliente
                reconciliar_hallazgos_en_caliente(self)
            except Exception:
                logger.exception(
                    "No se pudieron reconciliar los hallazgos de Subsanación del "
                    "contrato %s.", self.pk)

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
                    # Consecuencia del borrado del contrato, que es lo que se audita.
                    with cambios_derivados():
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

    # Sobrescribe el `RESTRICT` de `ContratoBase`, que aquí impedía eliminar a nadie.
    #
    # Toda persona que aparece en la Lista de Bajas tiene por definición un `CBaja`, así
    # que con `RESTRICT` el botón «Eliminar» de esa lista fallaba SIEMPRE con «tiene un
    # historial de contratos o bajas asociado». La protección tiene sentido en `CAlta`
    # —no se puede borrar a alguien con un contrato activo, y ahí sigue vigente— pero no
    # en el registro histórico de la baja, que es precisamente lo que se quiere eliminar
    # junto con la persona.
    #
    # `related_name` se declara explícito para conservar el mismo accesor que generaba
    # `"%(class)s_contratos"` en la clase base: hay código que usa `cbaja_contratos`.
    #
    # Consecuencia asumida: eliminar un Aspirante borra su historial de bajas y, por la
    # cascada de `TMovimiento.aspirante`, también sus movimientos de nómina.
    aspirante = models.ForeignKey(
        Aspirante, on_delete=models.CASCADE, related_name="cbaja_contratos")

    fecha_baja = models.DateField(null=True, blank=True)
    fecha_alta = models.DateField(null=True, blank=True) # Necesario para guardar el historial
    fecha_documento = models.DateField(null=True, blank=True, verbose_name="Fecha de documento")

    # Entrada REAL a la empresa, copiada del contrato al darlo de baja.
    #
    # `fecha_alta` guarda la del CONTRATO, que no es lo mismo: a un trabajador de
    # veinte años recontratado hace dos, `fecha_alta` le da dos. El modelo de bajas
    # de la UNE pide «Años en la Organización», y con la fecha del contrato salía
    # sistemáticamente corta en todo el que hubiera cambiado de contrato alguna vez.
    #
    # Las bajas YA registradas se quedan a NULL —ese dato no existe en ninguna
    # parte y no se puede inventar—; para ellas la antigüedad se sigue calculando
    # con `fecha_alta`. Las nuevas la dan exacta.
    fecha_alta_entidad = models.DateField(
        null=True, blank=True,
        verbose_name="Fecha de entrada a la entidad")

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
        verbose_name = "T Movimiento (detalle sin agrupar)"
        verbose_name_plural = "T Movimientos (detalle sin agrupar)"
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


class TMovimientoAgrupado(TMovimiento):
    """Proxy de solo-navegación para el Admin: una fila por (aspirante, no_expediente).

    No añade tabla ni columnas — es la única forma de registrar en Django Admin una
    vista alternativa agrupada de los mismos datos sin duplicar la tabla real. El
    detalle de cada movimiento se sigue editando en TMovimiento/TMovimientoAdmin.
    """
    class Meta:
        proxy = True
        verbose_name = "T Movimiento"
        verbose_name_plural = "T Movimientos"


# ==================== BORRADO DE TMOVIMIENTO DESDE EL ADMIN ====================
# Decisión tomada con el usuario tras un caso real en producción: el Admin de Django
# puede borrar movimientos de nómina libremente (uno, varios o todo el histórico), pero
# eso NUNCA debe quedar en silencio ni dejar datos a medias.
#
# Va en `post_delete` (no en `TMovimiento.delete()`) porque `post_delete` se dispara
# también en los borrados masivos (`QuerySet.delete()`, la acción «Eliminar
# seleccionados» y la acción agrupada de `TMovimientoAgrupadoAdmin`), que NO pasan por
# el `.delete()` de una instancia concreta.
# En pausa del registro automático: todo lo que hace ya se audita a mano aquí
# mismo, con el motivo de cada cambio (ver `auditoria/registro_automatico.py`).
@sin_auditoria_automatica()
def _al_eliminar_movimiento(sender, instance, **kwargs):
    """Audita CADA borrado de TMovimiento y, si deja al trabajador sin ningún
    movimiento de nómina, cierra su ciclo de contratación.

    «Sin ningún movimiento» se comprueba sobre TODOS los expedientes del aspirante,
    no solo el de `instance`: lo que dispara este cierre es vaciar el histórico
    COMPLETO del trabajador, no un expediente suelto.

    Vaciar el histórico completo de alguien es una decisión deliberada del
    administrador (quiere borrar sus datos de la BD), así que aquí SÍ se borra todo
    lo que se pueda borrar: si el aspirante todavía tenía un `CAlta` vigente, se
    elimina por completo (cargo, unidad, salario, tridente, todo) — solo sobrevive
    el `no_expediente`, para no perder la trazabilidad del expediente. Se crea un
    `CBaja` "vacío" (sin cargo, sin fecha_alta) que sirve de marcador: certifica que
    el trabajador existió y fue dado de baja, pero deja explícito que no tiene
    ningún dato real porque su histórico se borró desde el Admin, no por una baja
    real documentada. `list_aspir.html`/`BajaListView` lo resalta en rojo cuando lo
    detecta (`fecha_alta is None`), para que quede claro a simple vista que esa
    fila no tiene información real detrás.

    Ese `fecha_alta=None` es también la clave de que, si se recontrata a este
    trabajador más adelante, el nuevo ciclo se vea como «Alta Inicial» y no como
    «Recontratación»: `historico_trabajador()` (`contratos/views.py`) solo genera
    un hito de alta para un `CBaja` que tenga `fecha_alta` (`if b.fecha_alta:`), así
    que este marcador vacío no cuenta para esa cronología — no tendría sentido
    "recontratar" a alguien de quien no queda ningún rastro documental.

    Envuelto en try/except: una excepción aquí NUNCA debe impedir que el borrado que
    el usuario pidió se complete.
    """
    from auditoria.middleware import get_current_user
    from auditoria.models import AccionAuditoria
    from auditoria.servicios import registrar as registrar_auditoria

    usuario_actual = get_current_user()

    try:
        registrar_auditoria(
            usuario=usuario_actual, accion=AccionAuditoria.ELIMINAR, modulo='contratos',
            content_type=ContentType.objects.get_for_model(TMovimiento),
            object_id=str(instance.pk),
            descriptor=f'Movimiento de nómina eliminado (expediente '
                       f'{instance.no_expediente or "—"}, {instance.tipo_movimiento}) '
                       f'de {instance.aspirante or "trabajador desconocido"}.')
    except Exception:
        logger.exception(
            "No se pudo registrar en Auditoría la eliminación del movimiento %s.",
            instance.pk)

    if str(instance.tipo_movimiento or '').strip().lower() == TIPO_MOVIMIENTO_BAJA.lower():
        _borrar_cbaja_asociada(instance, usuario_actual)

    aspirante_id = instance.aspirante_id
    if not aspirante_id:
        return

    try:
        if TMovimiento.objects.filter(aspirante_id=aspirante_id).exists():
            return  # todavía le quedan movimientos: nada que cerrar

        aspirante = Aspirante.objects.filter(pk=aspirante_id).first()
        if aspirante is None or aspirante.estado == 'BAJA':
            return  # ya está de baja (o no existe): no hay nada que reconciliar

        no_expediente = instance.no_expediente
        contrato = CAlta.objects.filter(aspirante_id=aspirante_id).first()
        if contrato:
            no_expediente = contrato.no_expediente
            object_id_contrato = str(contrato.pk)
            descriptor_contrato = str(contrato)
            contrato.delete()  # deja al aspirante en BAJA, notifica y recalcula la plaza
            registrar_auditoria(
                usuario=usuario_actual, accion=AccionAuditoria.ELIMINAR, modulo='contratos',
                content_type=ContentType.objects.get_for_model(CAlta),
                object_id=object_id_contrato,
                descriptor=f'Contrato de {descriptor_contrato} cerrado automáticamente: '
                           f'se quedó sin ningún movimiento de nómina en su histórico.')
        else:
            aspirante.estado = 'BAJA'
            aspirante.save(update_fields=['estado'])

        if not no_expediente:
            return

        ya_existe = CBaja.objects.filter(
            aspirante_id=aspirante_id, no_expediente=no_expediente,
            cargo__isnull=True, fecha_alta__isnull=True).exists()
        if ya_existe:
            return

        baja = CBaja.objects.create(
            aspirante=aspirante, no_expediente=no_expediente,
            fecha_alta=None, fecha_baja=timezone.now().date(),
            observaciones=(
                'Baja generada automáticamente por Orbith: se eliminó todo el '
                'histórico de movimientos de nómina de este trabajador desde el '
                'Admin de Django, sin dejar cargo, Unidad Organizativa ni '
                'Departamento asociado. Este registro no tiene datos reales, solo '
                'certifica que el expediente existió.'))
        registrar_auditoria(
            usuario=usuario_actual, accion=AccionAuditoria.CREAR, instancia=baja,
            modulo='contratos',
            descriptor=f'Baja automática de {aspirante} al vaciarse su histórico de '
                       f'movimientos de nómina (expediente {no_expediente}).')
    except Exception:
        logger.exception(
            "No se pudo cerrar automáticamente el ciclo del aspirante %s tras "
            "quedarse sin histórico de movimientos.", aspirante_id)


def _borrar_cbaja_asociada(instance, usuario_actual):
    """Borra el `CBaja` que corresponde al mismo evento que el `TMovimiento` tipo
    «Baja» que se acaba de eliminar.

    Se empareja por (aspirante, expediente, fecha) en vez de por una FK directa
    porque nunca existió ese enlace en el modelo. `fecha_efectiva` del movimiento
    de Baja y `fecha_baja` del CBaja se escriben SIEMPRE con el mismo valor en el
    único lugar del código que crea ambos a la vez (ver `dar_baja` en
    `contratos/views.py`), así que la pareja (aspirante_id, no_expediente,
    fecha_baja) identifica sin ambigüedad un único ciclo de contratación — el
    mismo criterio que ya usa `historico_trabajador()` para asociar cada Baja a
    su ciclo cuando hay expedientes reutilizados por recontratación.
    """
    from auditoria.models import AccionAuditoria
    from auditoria.servicios import registrar as registrar_auditoria

    if not instance.aspirante_id or not instance.no_expediente or not instance.fecha_efectiva:
        return

    try:
        baja = CBaja.objects.filter(
            aspirante_id=instance.aspirante_id,
            no_expediente=instance.no_expediente,
            fecha_baja=instance.fecha_efectiva,
        ).first()
        if not baja:
            return

        object_id, descriptor = str(baja.pk), str(baja)
        baja.delete()
        registrar_auditoria(
            usuario=usuario_actual, accion=AccionAuditoria.ELIMINAR, modulo='contratos',
            content_type=ContentType.objects.get_for_model(CBaja),
            object_id=object_id,
            descriptor=f'Baja de {descriptor} eliminada junto con su movimiento de '
                       f'nómina asociado.')
    except Exception:
        logger.exception(
            "No se pudo eliminar el CBaja asociado al movimiento de Baja %s.",
            instance.pk)


post_delete.connect(_al_eliminar_movimiento, sender=TMovimiento,
                     dispatch_uid='contratos_al_eliminar_movimiento')