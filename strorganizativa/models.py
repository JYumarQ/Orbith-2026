from django.db import models
from notificaciones.models import Notificacion
from django.contrib.contenttypes.models import ContentType
from nomencladores.models import NCargo, NRol, NNivelPreparacion, NTipoUnidadOrganizativa
from auditoria.models import Base
from django.core.exceptions import ValidationError
from django.db.models import Max

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
        unique=True # REGLA 1: PostgreSQL prohíbe repetir el número en toda la tabla
    )

    class Meta:
        verbose_name = ("Unidad Organizativa")
        verbose_name_plural = ("Unidades Organizativas")
        ordering = ['orden_informe', 'descripcion']

    def clean(self):
        super().clean()
        # LÓGICA DE HERENCIA AL CREAR/EDITAR
        if self.tipo and self.tipo.es_subunidad:
            # Busca automáticamente a quién debe pertenecer (Unidad con es_principal=True)
            unidad_raiz = UnidadOrganizativa.objects.filter(tipo__es_principal=True).exclude(pk=self.pk).first()
            
            if unidad_raiz:
                self.padre = unidad_raiz
                self.grupo_nomina = unidad_raiz.grupo_nomina
            else:
                self.padre = None 
        else:
            self.padre = None
            if not self.grupo_nomina:
                raise ValidationError({'grupo_nomina': 'Este campo es obligatorio para Unidades Principales o Normales.'})

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
        ordering = ['orden_informe', 'descripcion'] # Orden local de fábrica
        constraints = [
            # REGLA 2: Blindaje SQL. Garantiza que dentro de una misma Unidad no se repita el orden
            models.UniqueConstraint(
                fields=['unidad_organizativa', 'orden_informe'], 
                name='unique_orden_depto_por_unidad'
            )
        ]
        
    def __str__(self):
        return f"Dpto. {self.descripcion}"

class CargoPlantilla(Base):

    ncargo = models.ForeignKey(NCargo, verbose_name='Nomenclador de Cargo', on_delete=models.RESTRICT)
    departamento = models.ForeignKey(Departamento, on_delete=models.RESTRICT)
    rol = models.ForeignKey(NRol, verbose_name=('Nomenclador de Rol'), on_delete=models.RESTRICT, null=True, blank=True)
    nivel_preparacion = models.ForeignKey(NNivelPreparacion, verbose_name=('Nivel de Preparación'), on_delete=models.RESTRICT, null=True, blank=True)
    cant_aprobada = models.IntegerField(default=0)
    cant_cubierta = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)

    @property
    def cant_cubierta_real(self):
        """
        Cuenta la cantidad de personas REALMENTE activas en este cargo.
        Filtra por los contratos de alta (CAlta) cuyo aspirante esté 'ACTIVO'.
        """
        from contratos.models import CAlta
        # Contamos solo contratos vigentes donde el trabajador no sea baja
        return CAlta.objects.filter(
            cargo=self, 
            aspirante__estado='ACTIVO'
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
        
    def save(self, *args, **kwargs):
        # LÓGICA AUTOMÁTICA: Si plazas es 0 -> Inactivo, si > 0 -> Activo
        if self.cant_aprobada is not None:
            self.activo = self.cant_aprobada > 0
        
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)  # Guarda primero para obtener el PK

        if es_nuevo:
            Notificacion.objects.create(
                titulo="Nuevo Cargo creado",
                mensaje=f"Se ha creado un nuevo cargo: {self.ncargo.descripcion} en {self.departamento}.",
                content_type=ContentType.objects.get_for_model(self),
                object_id=str(self.pk),
                unidad = self.departamento.unidad_organizativa
            )


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
