import logging

from django.db import models
from notificaciones.models import Notificacion
from django.contrib.contenttypes.models import ContentType
from nomencladores.models import NCargo, NRol, NNivelPreparacion, NTipoUnidadOrganizativa, NMunicipio
from auditoria.models import Base
from django.core.exceptions import ValidationError
from django.db.models import Max

logger = logging.getLogger(__name__)

# Create your models here.
class UnidadOrganizativa(Base):
    # 1. Identificador único personalizado
    codigo_interno = models.IntegerField(primary_key=True, verbose_name="Código Interno")
    
    # 2. Grupo de Nómina (Heredable)
    grupo_nomina = models.IntegerField(null=True, blank=True, verbose_name="Grupo de Nómina")
    
    descripcion = models.CharField(max_length=150, blank=False, null=False)
    
    # 3. Relación con Nomencladores Dinámicos
    tipo = models.ForeignKey(
        NTipoUnidadOrganizativa,
        on_delete=models.RESTRICT,
        verbose_name="Tipo de Unidad"
    )

    # Municipio donde radica la unidad. Se filtra en el formulario según la
    # provincia definida en Parámetros Generales (Configuracion.provincia_entidad).
    municipio = models.ForeignKey(
        NMunicipio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Municipio"
    )

    # 4. Relación Jerárquica
    padre = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='direcciones_hijas',
        verbose_name='Pertenece a'
    )

    # --- NUEVO CAMPO DE JERARQUÍA (ÁMBITO GLOBAL) ---
    orden_informe = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Posición en el Organigrama",
         # REGLA 1: PostgreSQL prohíbe repetir el número en toda la tabla
    )

    class Meta:
        verbose_name = ("Unidad Organizativa")
        verbose_name_plural = ("Unidades Organizativas")
        ordering = ['orden_informe', 'descripcion']

        constraints = [
            models.UniqueConstraint(
                fields=['padre', 'orden_informe'],
                name='unique_orden_por_rama',
                deferrable=models.Deferrable.DEFERRED,
            )
        ]

    def clean(self):
        super().clean()

        if self.tipo and self.tipo.es_subunidad:
            # Subunidad: el padre lo elige el usuario en el formulario
            if not self.padre:
                raise ValidationError({
                    'padre': 'Debe seleccionar la Unidad Principal a la que pertenece esta subunidad.'
                })
            if not self.padre.tipo.es_principal:
                raise ValidationError({
                    'padre': 'La unidad seleccionada no es una Unidad Principal.'
                })
            if self.pk and self.padre.pk == self.pk:
                raise ValidationError({
                    'padre': 'Una unidad no puede pertenecer a sí misma.'
                })
            # Hereda el Grupo de Nómina de su padre
            self.grupo_nomina = self.padre.grupo_nomina
        else:
            # Principal o normal: no tiene padre y su Grupo de Nómina es propio
            self.padre = None
            if not self.grupo_nomina:
                raise ValidationError({
                    'grupo_nomina': 'Este campo es obligatorio para Unidades Principales o Normales.'
                })
            
    def save(self, *args, **kwargs):
        # Asignación de ID si es nuevo
        if not self.codigo_interno:
            from django.db.models import Max
            ultimo_codigo = UnidadOrganizativa.objects.aggregate(Max('codigo_interno'))['codigo_interno__max']
            self.codigo_interno = (ultimo_codigo or 0) + 1
            
        self.clean()
        super().save(*args, **kwargs)

        # --- SINCRONIZACIÓN EN CASCADA ---
        # Si esta unidad es Principal, forzamos la actualización de todas sus hijas
        if self.tipo and self.tipo.es_principal:
            # Esto soluciona tu problema: actualiza el GN de todas las subunidades de golpe
            self.direcciones_hijas.all().update(grupo_nomina=self.grupo_nomina)

    def __str__(self):
        return self.descripcion
    
class Departamento(Base):

    descripcion = models.CharField(max_length=150, blank=False, null=False)
    unidad_organizativa = models.ForeignKey(
        UnidadOrganizativa, 
        on_delete=models.RESTRICT,
        related_name='departamentos'
    )

    # --- NUEVO CAMPO DE JERARQUÍA (ÁMBITO LOCAL) ---
    orden_informe = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Posición dentro de la Unidad"
    )

    class Meta:
        verbose_name = ("Departamento")
        verbose_name_plural = ("Departamentos")
        ordering = ['orden_informe', 'id'] # Orden local de fábrica
        constraints = [
            models.UniqueConstraint(
                fields=['unidad_organizativa', 'orden_informe'],
                name='unique_orden_depto_por_unidad',
                deferrable=models.Deferrable.DEFERRED,   # ← comprobar al confirmar, no fila por fila
            )
        ]
        
    def __str__(self):
        return f"{self.descripcion}"

class CargoPlantilla(Base):

    ncargo = models.ForeignKey(NCargo, verbose_name='Nomenclador de Cargo', on_delete=models.RESTRICT)
    departamento = models.ForeignKey(Departamento, on_delete=models.RESTRICT)
    rol = models.ForeignKey(NRol, verbose_name=('Nomenclador de Rol'), on_delete=models.RESTRICT, null=True, blank=True)
    nivel_preparacion = models.ForeignKey(NNivelPreparacion, verbose_name=('Nivel de Preparación'), on_delete=models.RESTRICT, null=True, blank=True)
    cant_aprobada = models.IntegerField(default=0)
    cant_cubierta = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)
    funcionario = models.BooleanField(default=False, verbose_name='Funcionario')
    designado = models.BooleanField(default=False, verbose_name='Designado')
    orden_informe = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Orden de prioridad"
    )
    
    @property
    def cant_cubierta_real(self):
        """
        Cuenta la cantidad de personas REALMENTE activas en este cargo
        QUE OCUPAN UNA PLAZA OFICIAL (Ej: Indeterminados).

        Al usarla dentro de un bucle (un listado, un informe) lanza un COUNT con
        dos joins POR CADA CARGO. En pantallas con la plantilla completa eso son
        cientos de consultas. Por eso reconoce la anotación `count_cubiertas`,
        exactamente igual que `plazas_fijas` reconoce `count_ind`: quien recorra
        muchos cargos debe anotarla en el queryset y el cálculo se resuelve en la
        consulta que ya se estaba haciendo.

            CargoPlantilla.objects.annotate(count_cubiertas=Count(
                'calta', filter=Q(calta__aspirante__estado='ACTIVO',
                                  calta__tipo__ocupa_plaza=True)))
        """
        if hasattr(self, 'count_cubiertas'):
            return self.count_cubiertas

        from contratos.models import CAlta
        return CAlta.objects.filter(
            cargo=self, 
            aspirante__estado='ACTIVO',
            tipo__ocupa_plaza=True  # <--- EL FILTRO DE ORO
        ).count()
    
    def refrescar_conteo_plazas(self):
        """Sincroniza el campo de la base de datos con la realidad"""
        self.cant_cubierta = self.cant_cubierta_real
        self.save(update_fields=['cant_cubierta'])

    @property
    def disponibilidad(self):
        """Calcula las plazas libres usando SOLO los contratos que ocupan plaza oficial"""
        return max(0, self.cant_aprobada - self.plazas_fijas)

    class Meta:
        verbose_name = ("Cargo")
        verbose_name_plural = ("Cargos")
        ordering = ['orden_informe', 'ncargo__descripcion']
        constraints = [
            models.UniqueConstraint(
                fields=['departamento', 'orden_informe'],
                name='unique_orden_cargo_por_departamento',
                deferrable=models.Deferrable.DEFERRED,  # comprobar al confirmar, no fila por fila
            )
        ]
            

    def clean(self):
        super().clean()
        # BLINDAJE DE INTEGRIDAD: Exclusividad mutua absoluta
        if self.funcionario and self.designado:
            raise ValidationError("Inconsistencia de datos: Un cargo no puede ser Funcionario y Designado al mismo tiempo.")

        
    def save(self, *args, **kwargs):
        # LÓGICA AUTOMÁTICA: Si plazas es 0 -> Inactivo, si > 0 -> Activo
        if self.cant_aprobada is not None:
            self.activo = self.cant_aprobada > 0
        
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)  # Guarda primero para obtener el PK

        if es_nuevo:
            # Personal por destinatario (moderador de la unidad + administradores),
            # no una sola fila «por unidad»: así cada quien puede marcarla como
            # leída de forma independiente. `unidad` se conserva como contexto.
            # La escritura en sí vive en `notificaciones/avisos.py::avisar_nuevo_cargo`
            # (mismo punto de escritura, con protección de concurrencia, que el resto
            # de eventos del módulo — antes esto se hacía inline con `bulk_create()`
            # sin ninguna protección).
            from notificaciones.avisos import avisar_nuevo_cargo
            avisar_nuevo_cargo(self)


    @property
    def plazas_fijas(self):
        """Cuenta SOLO los contratos cuyo tipo tiene el check 'ocupa_plaza=True' y están activos"""
        if hasattr(self, 'count_ind'): 
            return self.count_ind
        
        from contratos.models import CAlta # Importación local anti-bucle
        return CAlta.objects.filter(
            cargo=self, 
            tipo__ocupa_plaza=True, 
            aspirante__estado='ACTIVO'
        ).count()

    @property
    def plazas_contrato(self):
        """Cuenta los contratos temporales (ocupa_plaza=False) activos"""
        if hasattr(self, 'count_cont'): 
            return self.count_cont
            
        from contratos.models import CAlta # Importación local anti-bucle
        return CAlta.objects.filter(
            cargo=self, 
            tipo__ocupa_plaza=False, 
            aspirante__estado='ACTIVO'
        ).count()

    def __str__(self):
        return self.ncargo.descripcion
