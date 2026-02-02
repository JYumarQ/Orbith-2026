from decimal import Decimal
from django.db import models
from bolsa.models import Aspirante
from strorganizativa.models import CargoPlantilla
from nomencladores.models import NTridente, NSalario, NJornada, NCausaAltaBaja
from django.core.validators import MinValueValidator
from datetime import timedelta
from django.utils import timezone
from auditoria.models import Base

#?CONTRATO
class ContratoBase(Base):
    
    aspirante = models.ForeignKey(Aspirante, on_delete=models.RESTRICT)
    no_expediente = models.CharField(max_length=5, primary_key=True)
    #?CONTRATO
    tipo = models.CharField(max_length=50, choices=[
        ('IND', 'Indeterminado'), 
        ('DET', 'Determinado'),
        ('EAD', 'En Adiestramiento'), 
        ('MOT', 'Movimiento Temporal')
    ])
    
    cargo = models.ForeignKey(CargoPlantilla, on_delete=models.RESTRICT, blank=True, null= True)
    
    reg_militar = models.TextField(max_length=3, choices=[
        ('MTT', 'MTT'),
        ('IMP', 'Imprescindible'),
        ('BPD', 'BPD'),
        ('NIN', 'No Incorporado')
    ], blank=True, null= True)
        
    #?CHOFER
    profesional = models.BooleanField(default=False)
    
    
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
    funcionario = models.BooleanField(default=False)    
    designado = models.BooleanField(default=False)    
    c_formal_res = models.TextField(max_length=7, null=True, blank=True)    
    funcionario_res = models.TextField(max_length=7, null=True, blank=True)    
    designado_res = models.TextField(max_length=7, null=True, blank=True)
    
    #?SALARIO
    tipo_salario = models.CharField(max_length=3, choices=[
        ('FIJ', 'Fijo'),
        ('DIN', 'Dinámico')
    ], default='DIN')
    tridente = models.ForeignKey(
        NTridente,
        on_delete=models.RESTRICT,
        blank=True,
        null= True
        )
    maestria = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)], null=True, blank=True)
    doctorado = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)], null=True, blank=True)
    cnci = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=5, decimal_places=2, null=True, blank=True)
    instructor = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    
    cla1 = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    cla2 = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    cla3 = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    cla4 = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    cla5 = models.DecimalField(default=Decimal('0.00'), validators=[MinValueValidator(0)], max_digits=4, decimal_places=2, null=True, blank=True)
    
    jornada = models.ForeignKey(NJornada, blank=True, null=True, on_delete=models.RESTRICT)

    fecha_vence_lic = models.DateField(null=True, blank=True)
    fecha_vence_recal = models.DateField(null=True, blank=True)
    fecha_vence_seg = models.DateField(null=True, blank=True)
    
    fecha_alta = models.DateField(null=True, blank=True)

    jubilado_recontratado = models.BooleanField(default=False)
    en_proceso_movimiento = models.BooleanField(default=False, verbose_name="En Proceso de Movimiento")

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
        cargo = CargoPlantilla.objects.filter(pk=cargo_id).first() # Usamos pk por consistencia
        if cargo: # Verificamos que exista antes de editar
            cargo.cant_cubierta += 1
            cargo.save()
        
    def calcular_salario_escala(self):
        try:
            if self.tipo_salario == 'DIN':
                if not self.cargo or not self.tridente:
                    return None
                grupo_escala_temp = self.cargo.ncargo.grupo_escala
                rol_temp = self.cargo.rol
                tridente_temp = self.tridente
                
                salario_obj = NSalario.objects.get(
                    grupo_escala = grupo_escala_temp,
                    rol = rol_temp,
                    tridente = tridente_temp
                )
                return round(float(salario_obj.monto),2)
            else:
                return self.cargo.ncargo.salario_basico if self.cargo else None
        except NSalario.DoesNotExist:
            return None
    
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
        return max(delta, 0)
        
    def get_director(self):
        if self.cargo and self.cargo.ncargo.cat_ocupacional != 'CDI' and self.cargo.ncargo.cat_ocupacional != 'CEJ':
            director = CAlta.objects.filter(cargo__ncargo__cat_ocupacional__in=['CDI','CEJ']).first()
            return director
        else:
            return 'Es Director' 
    
    

    def save(self, *args, **kwargs):
        try:
            # CORRECCIÓN CRÍTICA:
            # Como 'no_expediente' es PK manual, self.pk NUNCA es None.
            # Usamos self._state.adding para saber si es una inserción real (Create) o edición (Update).
            es_nuevo = self._state.adding
            
            # Asignar tridente por defecto
            if not self.tridente:
                self.tridente = NTridente.objects.filter(tipo='I').first()
            
            # Ejecutar lógica SOLO si es una inserción nueva en la BD
            if es_nuevo:
                self.actualizar_aspirante(self.aspirante.doc_identidad)
                
                # Solo sumamos plaza si es contrato INDETERMINADO y tiene cargo
                if self.tipo == 'IND' and self.cargo:
                    self.actualizar_plantilla(self.cargo.pk)
            
            super().save(*args, **kwargs)
            
        except Exception as e:
            print(f"Error al guardar el contrato: {e}")
            raise

    def delete(self, *args, **kwargs):
        try:
            # 1. Liberar plaza (Si era Indeterminado y tenía cargo)
            if self.tipo == 'IND' and self.cargo:
                try:
                    cargo_obj = CargoPlantilla.objects.get(pk=self.cargo.pk)
                    if cargo_obj.cant_cubierta > 0:
                        cargo_obj.cant_cubierta -= 1
                        cargo_obj.save()
                except CargoPlantilla.DoesNotExist:
                    pass # Si el cargo ya no existe, ignoramos
            
            # 2. Mover Aspirante a BAJA (No a Aspirante)
            if self.aspirante:
                try:
                    aspirante_obj = Aspirante.objects.get(pk=self.aspirante.pk)
                    aspirante_obj.estado = 'BAJA'  # <--- CAMBIO CLAVE
                    aspirante_obj.save()
                except Aspirante.DoesNotExist:
                    pass
                
        except Exception as e:
            print(f"Error al eliminar contrato: {e}")

        super().delete(*args, **kwargs)


    def __str__(self):
        return self.aspirante.nombre

class CBaja(ContratoBase):
    
    fecha_baja = models.DateField(null=True, blank=True)
    fecha_alta = models.DateField(null=True, blank=True) # Necesario para guardar el historial
    
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
    
    # Asumo que 'observaciones' viene de 'Base', si no, agrégalo aquí también.

    class Meta:
        verbose_name = ("Baja")
        verbose_name_plural = ("Bajas")

    def __str__(self):
        return self.aspirante.nombre