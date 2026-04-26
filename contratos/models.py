from decimal import Decimal
from django.db import models
from bolsa.models import Aspirante
from strorganizativa.models import CargoPlantilla
from nomencladores.models import NTridente, NSalario, NJornada, NCausaAltaBaja, NRol, NTipoContrato, NMotivoContrato
from django.core.validators import MinValueValidator
from datetime import timedelta
from django.utils import timezone
from auditoria.models import Base


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
                # 1. Validación básica (ya no exigimos el rol aquí)
                if not self.cargo:
                    return None
                
                grupo_temp = self.cargo.ncargo.grupo_escala
                
                # Buscamos el rol (puede venir del contrato o del cargo)
                rol_temp = self.rol or self.cargo.rol 
                
                # 2. REGLA: Si es Cuadro o si NO TIENE ROL (contratos viejos), lo tratamos como Cuadro
                es_cuadro = not rol_temp or rol_temp.tipo.strip() == "Cuadro"
                
                if es_cuadro:
                    salario_obj = NSalario.objects.filter(
                        grupo_escala=grupo_temp,
                        rol=rol_temp, 
                        tridente__isnull=True
                    ).first()
                    
                    # Fallback de seguridad extrema
                    if not salario_obj:
                         salario_obj = NSalario.objects.filter(
                             grupo_escala=grupo_temp,
                             rol__isnull=True,
                             tridente__isnull=True
                         ).first()
                else:
                    if not self.tridente:
                        return None
                    salario_obj = NSalario.objects.filter(
                        grupo_escala=grupo_temp,
                        rol=rol_temp,
                        tridente=self.tridente
                    ).first()

                if salario_obj and salario_obj.monto:
                    return round(float(salario_obj.monto), 2)
                return None
                
            else:
                if self.cargo and self.cargo.ncargo and self.cargo.ncargo.salario_basico:
                    return round(float(self.cargo.ncargo.salario_basico), 2)
                return None
        except Exception as e:
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
    
    def save(self, *args, **kwargs):
        try:
            es_nuevo = self._state.adding
            
            # EL ESCUDO: Asignación y Limpieza real en base de datos
            if self.tipo_salario == 'DIN' and not self.tridente:
                from nomencladores.models import NTridente
                self.tridente = NTridente.objects.filter(tipo='I').first()
            elif self.tipo_salario == 'FIJ':
                self.tridente = None # Obligamos a que el fijo sea NULL
            
            if es_nuevo:
                self.actualizar_aspirante(self.aspirante.doc_identidad)
                if self.tipo and self.tipo.ocupa_plaza and self.cargo:
                    self.actualizar_plantilla(self.cargo.pk)
            
            super().save(*args, **kwargs)
        except Exception as e:
            print(f"Error al guardar el contrato: {e}")
            raise

    def delete(self, *args, **kwargs):
        try:
            # 1. Liberar plaza (Si el contrato ocupaba plaza y tenía cargo)
            if self.tipo and self.tipo.ocupa_plaza and self.cargo:
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

    fecha_documento = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="Fecha de documento"
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
    # -------------------------------------------------------------

    tipo_movimiento = models.CharField(max_length=50, default="Movimiento de Nómina")
    usuario = models.CharField(max_length=100, null=True, blank=True) 
    fecha_solicitud = models.DateField(null=True, blank=True, verbose_name="Fecha de Solicitud")
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_efectiva']

    class Meta:
        ordering = ['-fecha_efectiva']