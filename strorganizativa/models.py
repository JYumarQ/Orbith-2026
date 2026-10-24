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
        nombre_anterior = None
        if self.pk:
            nombre_anterior = (UnidadOrganizativa.objects.filter(pk=self.pk)
                               .values_list('descripcion', flat=True).first())
        super().save(*args, **kwargs)

        # Renombrar la unidad cambia cómo aparece en los documentos de quienes
        # trabajan en ella: se anota en su histórico como cambio externo.
        if nombre_anterior is not None and nombre_anterior != self.descripcion:
            from contratos.cambios_externos import registrar_renombre
            from contratos.models import CambioExterno
            registrar_renombre(
                CambioExterno.Origen.UNIDAD, self,
                'La unidad «%s» pasó a llamarse «%s».' % (nombre_anterior, self.descripcion),
                nombre_anterior, self.descripcion, unidad=self,
                cargo__departamento__unidad_organizativa=self)

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

    def save(self, *args, **kwargs):
        anterior = None
        if self.pk:
            anterior = (Departamento.objects.filter(pk=self.pk)
                        .select_related('unidad_organizativa').first())
        super().save(*args, **kwargs)
        if anterior is None:
            return

        # Renombrar el departamento o pasarlo a otra unidad cambia los datos de
        # quienes trabajan en él sin tocar su contrato: cambio externo.
        from contratos.cambios_externos import registrar_renombre
        from contratos.models import CambioExterno
        if anterior.unidad_organizativa_id != self.unidad_organizativa_id:
            registrar_renombre(
                CambioExterno.Origen.DEPARTAMENTO, self,
                'El departamento «%s» pasó de la unidad «%s» a la unidad «%s».' % (
                    self.descripcion, anterior.unidad_organizativa.descripcion,
                    self.unidad_organizativa.descripcion),
                anterior.unidad_organizativa.descripcion, self.unidad_organizativa.descripcion,
                unidad=self.unidad_organizativa, cargo__departamento=self)
        elif anterior.descripcion != self.descripcion:
            registrar_renombre(
                CambioExterno.Origen.DEPARTAMENTO, self,
                'El departamento «%s» pasó a llamarse «%s».' % (anterior.descripcion, self.descripcion),
                anterior.descripcion, self.descripcion, unidad=self.unidad_organizativa,
                cargo__departamento=self)

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
    # Un cargo «en plantilla» es la plaza aprobada por el organismo: es lo que
    # ha existido siempre y su lógica no cambia. En False significa que la plaza
    # existe y tiene gente, pero NO está en la plantilla aprobada: no suma en
    # ningún total de plazas aprobadas (dashboard, Anexo 14, informes de
    # plantilla, cierres) y no admite contratos que ocupen plaza.
    en_plantilla = models.BooleanField(default=True, verbose_name='En Plantilla')
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
            ),
            # Un mismo NCargo puede repetirse en el departamento SOLO como pareja:
            # uno dentro de la plantilla aprobada y otro fuera. Nunca dos iguales
            # del mismo lado. La validación amable (con mensaje) vive en
            # `CargoPlantillaForm.clean`; esto es el blindaje de la base de datos,
            # para las vías que no pasan por el formulario: shell, Django Admin,
            # importaciones masivas.
            models.UniqueConstraint(
                fields=['departamento', 'ncargo', 'en_plantilla'],
                name='unique_cargo_por_departamento_y_plantilla',
            ),
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

        # Mismo criterio que `UnidadOrganizativa.save()`: la validación del
        # modelo corre SIEMPRE, no solo cuando el guardado viene de un
        # formulario. Sin esto, un `objects.create()` desde el shell, el Django
        # Admin o una importación podían dejar un cargo marcado a la vez como
        # Funcionario y Designado, que es justo lo que `clean()` prohíbe.
        self.clean()

        es_nuevo = self.pk is None
        anterior = None
        if not es_nuevo:
            anterior = (CargoPlantilla.objects.filter(pk=self.pk)
                        .select_related('rol', 'ncargo__grupo_escala',
                                        'departamento__unidad_organizativa').first())
        super().save(*args, **kwargs)  # Guarda primero para obtener el PK

        if anterior is not None:
            self._registrar_cambios_externos(anterior)

        # Revisión por registro (Fase 2): el cargo y sus contratos. Nunca lanza. El
        # recuento de plazas (`refrescar_conteo_plazas`, en cada guardado de un
        # contrato) solo toca el conteo: basta con revisar el cargo.
        if not es_nuevo:
            from subsanacion.por_registro import revisar_registros
            campos = set(kwargs.get('update_fields') or ())
            if campos and campos <= {'cant_cubierta', 'activo'}:
                revisar_registros(cargos=[self.pk])
            else:
                from contratos.models import CAlta
                revisar_registros(cargos=[self.pk], contratos=list(
                    CAlta.objects.filter(cargo=self).values_list('pk', flat=True)))

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

    def _registrar_cambios_externos(self, anterior):
        """El rol de pago, el nomenclador (grupo escala) y el departamento son del
        CARGO: si cambian, cambian el salario o los datos de quienes lo ocupan sin
        que su contrato se toque. Se recalcula su salario guardado, se anota un
        cambio externo en el histórico de cada uno y se avisa a administradores,
        a quien hizo el cambio y al moderador de la unidad (decisión de RRHH del
        23-10-2026). Si viene de una pantalla sin motivo, `registrar_cambio` lanza
        `MotivoRequerido` y la vista deshace el guardado."""
        from contratos.cambios_externos import Afectado, registrar_cambio, texto_del_motivo
        from contratos.models import CAlta, CambioExterno

        def rol(cargo):
            return cargo.rol.tipo if cargo.rol_id else 'sin rol (Cuadro)'

        def ubicacion(cargo):
            return '%s (%s)' % (cargo.departamento.descripcion,
                                cargo.departamento.unidad_organizativa.descripcion)

        cambios = []
        if anterior.rol_id != self.rol_id:
            cambios.append('cambió de rol: %s a %s' % (rol(anterior), rol(self)))
        if anterior.ncargo_id != self.ncargo_id:
            def grupo(cargo):
                return cargo.ncargo.grupo_escala.nivel if cargo.ncargo.grupo_escala_id else '—'
            cambios.append('cambió de nomenclador: %s (grupo %s) a %s (grupo %s)' % (
                anterior.ncargo.descripcion, grupo(anterior), self.ncargo.descripcion, grupo(self)))
        if anterior.departamento_id != self.departamento_id:
            cambios.append('pasó del departamento %s al departamento %s' % (
                ubicacion(anterior), ubicacion(self)))
        if not cambios:
            return

        contratos = list(CAlta.objects.filter(cargo=self).select_related('aspirante'))
        if not contratos:
            return
        salarios = {}
        if anterior.rol_id != self.rol_id or anterior.ncargo_id != self.ncargo_id:
            salarios = {c.pk: (antes, despues) for c, antes, despues
                        in CAlta.recalcular_salarios(CAlta.objects.filter(cargo=self))}

        descripcion = 'El cargo «%s» %s.' % (self.ncargo.descripcion, ' y '.join(cambios))
        registrar_cambio(CambioExterno.Origen.CARGO, self, [
            Afectado(c, descripcion,
                     *(('Salario %s' % salarios[c.pk][0], 'Salario %s' % salarios[c.pk][1])
                       if c.pk in salarios else ('', '')))
            for c in contratos])

        partes = ['El cargo «%s» del departamento %s %s.' % (
            self.ncargo.descripcion, self.departamento.descripcion, ' y '.join(cambios))]
        if salarios:
            partes.append('Debido a este cambio se actualizó el salario de %s %s a dicho cargo.' % (
                len(salarios), 'contrato asignado' if len(salarios) == 1 else 'contratos asignados'))
        else:
            partes.append('Afecta a %s %s a dicho cargo.' % (
                len(contratos), 'contrato asignado' if len(contratos) == 1 else 'contratos asignados'))
        partes.append(texto_del_motivo())
        titulo = ('Cambio de rol en un cargo' if anterior.rol_id != self.rol_id
                  else 'Cambio de grupo escala en un cargo' if anterior.ncargo_id != self.ncargo_id
                  else 'Cargo trasladado de departamento')
        try:
            from notificaciones.avisos import CODIGO_CAMBIO_ROL, avisar_cambio_salarial
            avisar_cambio_salarial(self, codigo=CODIGO_CAMBIO_ROL, titulo=titulo,
                                   mensaje=' '.join(p for p in partes if p),
                                   unidad=self.departamento.unidad_organizativa)
        except Exception:
            # El aviso no es parte del cambio: si fallara, el cargo y los salarios
            # quedan guardados igual.
            logger.exception('No se pudo avisar del cambio del cargo %s.', self.pk)


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
