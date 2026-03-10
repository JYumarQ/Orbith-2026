from django.db import models
from notificaciones.models import Notificacion
from django.contrib.contenttypes.models import ContentType
from nomencladores.models import NCargo, NRol, NNivelPreparacion
from auditoria.models import Base
from django.core.exceptions import ValidationError
from django.db.models import Max

# Create your models here.
class UnidadOrganizativa(Base):

    # 1. Renombramos la llave primaria para no perder los departamentos que ya existen
    codigo_interno = models.IntegerField(primary_key=True, verbose_name="Código Interno")
    
    # 2. El verdadero Grupo de Nómina (Permite nulos inicialmente para no chocar al crear Direcciones Funcionales)
    grupo_nomina = models.IntegerField(null=True, blank=True, verbose_name="Grupo de Nómina")
    
    descripcion = models.CharField(max_length=150, blank=False, null=False)
    tipo = models.CharField(max_length=50, choices=[
        ('UEB','UEB'),
        ('DF','Dirección Funcional'),
        ('DG','Dirección General')
    ])

    # 3. El campo de jerarquía
    padre = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='direcciones_hijas',
        verbose_name='Pertenece a (Oficina Central)'
    )

    class Meta:
        verbose_name = ("Unidad Organizativa")
        verbose_name_plural = ("Unidades Organizativas")
        # --- LA REGLA ESTRICTA DE BASE DE DATOS ---
        constraints = [
            models.UniqueConstraint(
                fields=['grupo_nomina'], 
                condition=~models.Q(tipo='DF'), # "Que sea único SIEMPRE Y CUANDO el tipo no sea DF"
                name='unique_grupo_nomina_excepto_df'
            )
        ]

    def clean(self):
        super().clean()
        
        # --- LA LÓGICA AUTOMÁTICA DE NEGOCIO ---
        if self.tipo == 'DF':
            # Buscamos la DG, EXCLUYENDO a la unidad actual para que no se auto-asigne si la estás editando
            padre_dg = UnidadOrganizativa.objects.filter(tipo='DG').exclude(pk=self.pk).first()
            
            if padre_dg:
                self.padre = padre_dg
                self.grupo_nomina = padre_dg.grupo_nomina
            else:
                # Si no hay DG creada, permitimos que se cree "huérfana" temporalmente
                self.padre = None 
        else:
            # Si es UEB o Dirección General, nos aseguramos de que no tenga padre
            self.padre = None
            
            if not self.grupo_nomina:
                raise ValidationError({'grupo_nomina': 'Este campo es obligatorio para las UEB y la Dirección General.'})
            
    def save(self, *args, **kwargs):
        # 1. Asignación automática del Código Interno
        if not self.codigo_interno:
            from django.db.models import Max
            ultimo_codigo = UnidadOrganizativa.objects.aggregate(Max('codigo_interno'))['codigo_interno__max']
            self.codigo_interno = (ultimo_codigo or 0) + 1
            
        self.clean() 
        super().save(*args, **kwargs) # Guardamos los cambios en la base de datos

        # --- LÓGICA DE LAZOS FAMILIARES ---
        
        # A) Si la unidad fue degradada y ya no es Dirección General: Desheredar hijas
        if self.tipo != 'DG':
            self.direcciones_hijas.all().update(padre=None)
            
        # B) Si la unidad acaba de ser creada/editada como Dirección General: Adoptar huérfanas
        elif self.tipo == 'DG':
            # Buscamos en la base de datos todas las DFs que no tengan padre asignado
            # y las actualizamos al instante poniéndoles esta DG como padre y copiando la nómina
            UnidadOrganizativa.objects.filter(tipo='DF', padre__isnull=True).update(
                padre=self,
                grupo_nomina=self.grupo_nomina
            )

    def __str__(self):
        return self.descripcion
    
class Departamento(Base):

    descripcion = models.CharField(max_length=150, blank=False, null=False)
    unidad_organizativa = models.ForeignKey(UnidadOrganizativa, on_delete=models.RESTRICT)

    class Meta:
        verbose_name = ("Departamento")
        verbose_name_plural = ("Departamentos")
        
    def __str__(self):
        return f"Dpto. {self.descripcion}"

class CargoPlantilla(Base):

    ncargo = models.ForeignKey(NCargo, verbose_name='Nomenclador de Cargo', on_delete=models.RESTRICT)
    departamento = models.ForeignKey(Departamento, on_delete=models.RESTRICT)
    rol = models.ForeignKey(NRol, verbose_name=('Nomenclador de Rol'), on_delete=models.RESTRICT, null=True, blank=True)
    nivel_preparacion = models.ForeignKey(NNivelPreparacion, verbose_name=('Nivel de Preparación'), on_delete=models.RESTRICT, null=True, blank=True)
    cant_aprobada = models.IntegerField()
    cant_cubierta = models.IntegerField(default=0)
    activo = models.BooleanField(default=True)

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
        """Cuenta solo los contratos INDETERMINADOS (Plantilla Oficial)"""
        if hasattr(self, 'count_ind'): 
            return self.count_ind
        # CORRECCIÓN: Usar 'self.calta' en lugar de 'self.calta_set'
        return self.calta.filter(tipo='IND').count()

    @property
    def plazas_contrato(self):
        """Cuenta el resto de contratos (Determinados, Adiestramiento, etc)"""
        if hasattr(self, 'count_cont'): 
            return self.count_cont
        # CORRECCIÓN: Usar 'self.calta' en lugar de 'self.calta_set'
        return self.calta.exclude(tipo='IND').count()

    def __str__(self):
        return self.ncargo.descripcion
