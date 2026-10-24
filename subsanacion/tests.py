"""Pruebas de la reconciliación de hallazgos.

Son las primeras pruebas del proyecto, y están puestas donde un fallo sería silencioso
y caro: la reconciliación es la única pieza del módulo cuyo comportamiento no se puede
verificar leyendo el código, porque depende del estado acumulado en la base de datos a
lo largo de varios análisis.

Se ejecutan con:

    python manage.py test subsanacion

No hace falta instalar nada: es el runner que trae Django.
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .constantes import CRITICIDAD_ALTA, CRITICIDAD_INFORMATIVA, MODULO_CONTRATOS
from .contexto import ContextoAnalisis
from .models import EjecucionAnalisis, Hallazgo, RevisionHallazgo
from .reglas.base import HallazgoDetectado, ReglaBase
from .servicios import reconciliar_regla


class ReglaDePrueba(ReglaBase):
    """Regla de laboratorio: devuelve exactamente los hallazgos que se le pasan.

    `abstracta = True` es imprescindible: evita que se registre en el catálogo global.
    Sin eso, una regla de pruebas acabaría ejecutándose en los análisis de producción.
    `reconciliar_regla()` no consulta el registro —recibe la instancia— así que la
    regla funciona igual sin estar registrada.
    """

    abstracta = True

    codigo = 'PRUEBA-001'
    nombre = 'Regla de prueba'
    modulo = MODULO_CONTRATOS
    criticidad = CRITICIDAD_ALTA
    # Se usa un nomenclador sencillo solo para tener un ContentType válido. Los
    # `object_id` son inventados a propósito: el módulo nunca resuelve la
    # GenericForeignKey, y eso es justamente lo que le permite sobrevivir a que el
    # registro apuntado se borre.
    modelo = 'nomencladores.NProvincia'
    descripcion = 'Comprueba la reconciliación.'
    causa_probable = 'La provoca la propia prueba.'
    impacto = 'Ninguno: es una prueba.'
    solucion = 'No aplica.'

    def __init__(self, hallazgos=None):
        self.hallazgos = list(hallazgos or [])

    def ejecutar(self, contexto):
        yield from self.hallazgos


def hallazgo(object_id, valor='original'):
    """Un hallazgo detectado, con `datos` controlados para poder mover la huella."""
    return HallazgoDetectado(
        object_id=str(object_id),
        titulo=f'Hallazgo de prueba {object_id}',
        detalle='Detalle de prueba.',
        datos={'valor': valor},
    )


class ReconciliacionTests(TestCase):

    def setUp(self):
        self.ejecucion = EjecucionAnalisis.objects.create(
            estado=EjecucionAnalisis.COMPLETA)
        self.tipo = ContentType.objects.get_for_model(
            ReglaDePrueba().obtener_modelo())

    def _analizar(self, hallazgos):
        """Simula un barrido de esta regla y devuelve los contadores."""
        regla = ReglaDePrueba(hallazgos)
        return reconciliar_regla(regla, self.ejecucion, ContextoAnalisis(self.ejecucion))

    # ------------------------------------------------------------------
    def test_segundo_analisis_no_duplica_hallazgos(self):
        """La clave natural hace UPSERT: re-analizar no crea filas nuevas."""
        primera = self._analizar([hallazgo(1), hallazgo(2)])
        self.assertEqual(primera['nuevos'], 2)
        self.assertEqual(Hallazgo.objects.count(), 2)

        segunda = self._analizar([hallazgo(1), hallazgo(2)])
        self.assertEqual(segunda['nuevos'], 0)
        self.assertEqual(segunda['persistentes'], 2)
        self.assertEqual(segunda['resueltos'], 0)
        self.assertEqual(Hallazgo.objects.count(), 2)

        # Y se anota que se volvió a ver, que es lo que da idea de antigüedad real.
        self.assertEqual(
            list(Hallazgo.objects.values_list('veces_detectado', flat=True)), [2, 2])

    def test_hallazgo_ignorado_sobrevive_al_reanalisis(self):
        """Un «Ignorado» conserva su estado: el usuario ya dictaminó sobre él."""
        self._analizar([hallazgo(1)])
        ficha = Hallazgo.objects.get(object_id='1')
        ficha.estado = Hallazgo.IGNORADO
        ficha.nota = 'No aplica por una resolución especial.'
        ficha.save(update_fields=['estado', 'nota'])

        self._analizar([hallazgo(1)])

        ficha.refresh_from_db()
        self.assertEqual(ficha.estado, Hallazgo.IGNORADO)
        self.assertEqual(ficha.nota, 'No aplica por una resolución especial.')
        self.assertTrue(ficha.vigente)

    def test_hallazgo_que_desaparece_se_marca_corregido_y_se_archiva(self):
        """Si deja de detectarse, se archiva con su entrada en el historial.

        No se borra nunca: la ficha es la prueba de que el dato se corrigió.
        """
        self._analizar([hallazgo(1), hallazgo(2)])

        contadores = self._analizar([hallazgo(1)])
        self.assertEqual(contadores['resueltos'], 1)
        # La fila sigue existiendo.
        self.assertEqual(Hallazgo.objects.count(), 2)

        resuelto = Hallazgo.objects.get(object_id='2')
        self.assertFalse(resuelto.vigente)
        self.assertEqual(resuelto.estado, Hallazgo.CORREGIDO)
        self.assertTrue(resuelto.resuelto_automaticamente)
        self.assertIsNotNone(resuelto.fecha_resolucion)

        revision = resuelto.revisiones.get()
        self.assertTrue(revision.automatica)
        self.assertEqual(revision.estado_anterior, Hallazgo.PENDIENTE)
        self.assertEqual(revision.estado_nuevo, Hallazgo.CORREGIDO)
        self.assertIsNone(revision.usuario)

        # El que sigue detectándose no se toca.
        vigente = Hallazgo.objects.get(object_id='1')
        self.assertTrue(vigente.vigente)
        self.assertEqual(vigente.estado, Hallazgo.PENDIENTE)

    def test_ignorado_vuelve_a_pendiente_si_cambian_los_datos(self):
        """Si la huella cambia, ya no es el mismo caso y deja de estar silenciado.

        Es el mecanismo que impide que «Ignorado» se convierta en una alfombra bajo la
        que esconder problemas nuevos.
        """
        self._analizar([hallazgo(1, valor='original')])
        ficha = Hallazgo.objects.get(object_id='1')
        ficha.estado = Hallazgo.IGNORADO
        ficha.save(update_fields=['estado'])
        huella_original = ficha.huella

        self._analizar([hallazgo(1, valor='distinto')])

        ficha.refresh_from_db()
        self.assertNotEqual(ficha.huella, huella_original)
        self.assertEqual(ficha.estado, Hallazgo.PENDIENTE)
        self.assertIsNone(ficha.revisado_por)

        revision = ficha.revisiones.get()
        self.assertTrue(revision.automatica)
        self.assertEqual(revision.estado_anterior, Hallazgo.IGNORADO)
        self.assertEqual(revision.estado_nuevo, Hallazgo.PENDIENTE)
        self.assertIn('cambiaron', revision.nota)

    def test_corregido_que_reaparece_vuelve_a_pendiente(self):
        """Si vuelve a detectarse, no estaba corregido de verdad."""
        self._analizar([hallazgo(1)])
        self._analizar([])                      # desaparece -> Corregido
        self.assertEqual(Hallazgo.objects.get(object_id='1').estado, Hallazgo.CORREGIDO)

        self._analizar([hallazgo(1)])           # reaparece

        ficha = Hallazgo.objects.get(object_id='1')
        self.assertEqual(ficha.estado, Hallazgo.PENDIENTE)
        self.assertTrue(ficha.vigente)
        self.assertIsNone(ficha.fecha_resolucion)
        self.assertFalse(ficha.resuelto_automaticamente)

    def test_una_regla_truncada_no_marca_nada_como_corregido(self):
        """Si la regla se corta por el límite, no se puede saber qué desapareció.

        Marcar como corregidos los que no se alcanzaron sería mentir, y además es la
        propiedad que hace correcto ejecutar el análisis por partes.
        """
        self._analizar([hallazgo(1), hallazgo(2), hallazgo(3)])

        with patch('subsanacion.servicios.LIMITE_HALLAZGOS_POR_REGLA', 1):
            contadores = self._analizar([hallazgo(1), hallazgo(2), hallazgo(3)])

        self.assertTrue(contadores['truncada'])
        self.assertEqual(contadores['resueltos'], 0)
        self.assertEqual(Hallazgo.objects.filter(vigente=True).count(), 3)

    def test_clave_extra_separa_hallazgos_del_mismo_registro(self):
        """Varios problemas sobre el mismo registro no se pisan entre sí."""
        uno = HallazgoDetectado(
            object_id='1', clave_extra='campo_a', titulo='Falta el campo A',
            datos={'campo': 'A'})
        dos = HallazgoDetectado(
            object_id='1', clave_extra='campo_b', titulo='Falta el campo B',
            datos={'campo': 'B'})

        self._analizar([uno, dos])
        self.assertEqual(Hallazgo.objects.filter(object_id='1').count(), 2)

        # Se puede ignorar uno y dejar el otro pendiente.
        ficha_a = Hallazgo.objects.get(object_id='1', clave_extra='campo_a')
        ficha_a.estado = Hallazgo.IGNORADO
        ficha_a.save(update_fields=['estado'])

        self._analizar([uno, dos])

        self.assertEqual(
            Hallazgo.objects.get(object_id='1', clave_extra='campo_a').estado,
            Hallazgo.IGNORADO)
        self.assertEqual(
            Hallazgo.objects.get(object_id='1', clave_extra='campo_b').estado,
            Hallazgo.PENDIENTE)

    def test_hallazgo_global_no_se_duplica(self):
        """Un hallazgo global (object_id vacío) también respeta la clave natural.

        En PostgreSQL `NULL != NULL`, así que si `content_type` fuera nulable la
        restricción única no impediría duplicados y cada barrido crearía otra fila. Por
        eso las reglas globales declaran modelo y usan object_id = ''.
        """
        global_ = HallazgoDetectado(
            object_id='', clave_extra='ausente', titulo='No existe la configuración')

        self._analizar([global_])
        self._analizar([global_])

        self.assertEqual(Hallazgo.objects.filter(object_id='').count(), 1)


class ExportacionTests(TestCase):
    """La exportación tiene que contener exactamente lo que hay en pantalla.

    Es el invariante que hace fiable el módulo: un Excel descargado con filtros puestos
    que trajera más o menos filas que la pantalla llevaría a conclusiones falsas sobre
    cuántos problemas hay.
    """

    def setUp(self):
        from usuarios.models import CustomUser

        from .constantes import CRITICIDAD_CRITICA, CRITICIDAD_MEDIA, MODULO_NOMINA

        self.admin = CustomUser.objects.create_user(
            username='admin_exportacion', password='x', es_admin=True)

        tipo = ContentType.objects.get_for_model(ReglaDePrueba().obtener_modelo())
        ahora = timezone.now()
        self.datos = [
            ('EXP-001', MODULO_CONTRATOS, CRITICIDAD_CRITICA,
             'Pérez Gómez, Juan (85010112345) · contrato sin cargo'),
            ('EXP-002', MODULO_CONTRATOS, CRITICIDAD_MEDIA,
             'Ruiz Díaz, Ana (90020254321) · motivo incoherente'),
            ('EXP-003', MODULO_NOMINA, CRITICIDAD_MEDIA,
             'Pérez Gómez, Juan (85010112345) · salario desincronizado'),
        ]
        for indice, (codigo, modulo, criticidad, titulo) in enumerate(self.datos, start=1):
            Hallazgo.objects.create(
                codigo_regla=codigo, content_type=tipo, object_id=str(indice),
                modulo=modulo, criticidad=criticidad, titulo=titulo,
                ultima_deteccion=ahora, estado=Hallazgo.PENDIENTE)

    def _filas_de_excel(self, contenido):
        import io

        from openpyxl import load_workbook

        hoja = load_workbook(io.BytesIO(contenido)).active
        # La fila 4 es la cabecera; los datos empiezan en la 5 y terminan antes del total.
        return [fila for fila in hoja.iter_rows(min_row=5, values_only=True)
                if fila[0] and not str(fila[0]).startswith('Total')]

    def _comparar(self, querystring):
        from django.test import RequestFactory

        from .exportar import exportar_a_excel
        from .filtros import filtrar_hallazgos

        peticion = RequestFactory().get(f'/subsanacion/exportar/excel/{querystring}')
        peticion.user = self.admin
        esperadas = filtrar_hallazgos(peticion)[0].count()
        obtenidas = len(self._filas_de_excel(exportar_a_excel(peticion).content))
        self.assertEqual(
            obtenidas, esperadas,
            f'Con «{querystring or "sin filtros"}» la pantalla muestra {esperadas} '
            f'hallazgos y el Excel trae {obtenidas}.')
        return esperadas

    def test_sin_filtros_exporta_todos_los_abiertos(self):
        self.assertEqual(self._comparar(''), 3)

    def test_respeta_el_filtro_de_gravedad(self):
        self.assertEqual(self._comparar('?solo_criticos=1'), 1)

    def test_respeta_el_filtro_de_categoria(self):
        from .constantes import MODULO_NOMINA
        self.assertEqual(self._comparar(f'?modulo={MODULO_NOMINA}'), 1)

    def test_respeta_la_busqueda(self):
        """Busca por carnet, que es lo que las reglas escriben en el título."""
        self.assertEqual(self._comparar('?q=85010112345'), 2)

    def test_la_busqueda_no_depende_del_orden_de_las_palabras(self):
        """El título es «Apellidos, Nombre» (formato.py::referencia_trabajador).
        Buscar «Nombre Apellido» — el orden natural en que la gente escribe un
        nombre — tiene que encontrar el mismo hallazgo que «Apellido, Nombre»."""
        from urllib.parse import urlencode

        qs = '?' + urlencode({'q': 'Juan Pérez'})
        self.assertEqual(self._comparar(qs), 2)

    def test_los_archivados_no_salen_salvo_que_se_pidan(self):
        Hallazgo.objects.filter(codigo_regla='EXP-003').update(vigente=False)
        self.assertEqual(self._comparar(''), 2)
        self.assertEqual(self._comparar('?archivados=1'), 3)

    def test_el_pdf_se_genera_sin_errores(self):
        from django.test import RequestFactory

        from .exportar import exportar_a_pdf

        peticion = RequestFactory().get('/subsanacion/exportar/pdf/')
        peticion.user = self.admin
        respuesta = exportar_a_pdf(peticion)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(respuesta.content.startswith(b'%PDF'))


class IndiceDeSaludTests(TestCase):
    """La fórmula del índice: porcentaje de registros limpios."""

    def test_sin_hallazgos_el_indice_es_cien(self):
        from .servicios import indice_desde_afectados
        self.assertEqual(indice_desde_afectados(0, 250), Decimal('100.00'))

    def test_todos_afectados_da_cero(self):
        from .servicios import indice_desde_afectados
        self.assertEqual(indice_desde_afectados(250, 250), Decimal('0.00'))

    def test_nunca_baja_de_cero_ni_se_satura(self):
        """La fórmula anterior se desbordaba; ésta no puede.

        Aunque haya más hallazgos que registros (un registro puede generar varios), el
        número de registros AFECTADOS nunca supera el de registros analizados, así que el
        índice se queda siempre entre 0 y 100 y sigue siendo informativo.
        """
        from .servicios import indice_desde_afectados
        self.assertEqual(indice_desde_afectados(9999, 100), Decimal('0.00'))
        self.assertEqual(indice_desde_afectados(35, 247), Decimal('85.83'))

    def test_sin_registros_no_divide_por_cero(self):
        from .servicios import indice_desde_afectados
        self.assertEqual(indice_desde_afectados(0, 0), Decimal('100.00'))


class IndiceExcluyeExtrasTests(TestCase):
    """Un hallazgo de Extras (dato complementario, no importante para RRHH) no debe
    bajar el índice de salud general — ver `servicios.finalizar_ejecucion()`."""

    def test_hallazgo_de_extras_no_penaliza_el_indice(self):
        from bolsa.models import Aspirante
        from nomencladores.models import NMunicipio, NProvincia

        from .constantes import MODULO_EXTRAS
        from .servicios import finalizar_ejecucion

        provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')
        aspirante = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad='90010112345', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)

        tipo = ContentType.objects.get_for_model(Aspirante)
        Hallazgo.objects.create(
            codigo_regla='ASP-005', content_type=tipo, object_id=str(aspirante.pk),
            modulo=MODULO_EXTRAS, criticidad=CRITICIDAD_INFORMATIVA,
            titulo='Sin móvil personal', ultima_deteccion=timezone.now(),
            estado=Hallazgo.PENDIENTE)

        ejecucion = EjecucionAnalisis.objects.create(
            estado=EjecucionAnalisis.EN_CURSO,
            modulos_solicitados=[MODULO_EXTRAS], modulos_completados=[MODULO_EXTRAS],
            codigos_regla_ejecutados=['ASP-005'], modelos_analizados=['bolsa.Aspirante'])

        finalizar_ejecucion(ejecucion)
        ejecucion.refresh_from_db()

        # El hallazgo se sigue contando y mostrando...
        self.assertEqual(ejecucion.hallazgos_vigentes, 1)
        # ...pero no cuenta como registro afectado para la nota de salud general.
        self.assertEqual(ejecucion.indice_salud, Decimal('100.00'))


class FiltroExcluyeExtrasTests(TestCase):
    """«Todas» (sin filtrar por categoría) no debe incluir Extras: son datos
    complementarios, no problemas de calidad, y mezclarlos es ruido. Solo aparecen si
    el usuario los pide explícitamente filtrando por la categoría Extras."""

    def setUp(self):
        from usuarios.models import CustomUser

        from .constantes import MODULO_EXTRAS

        self.admin = CustomUser.objects.create_user(
            username='admin_filtro_extras', password='x', es_admin=True)

        tipo = ContentType.objects.get_for_model(ReglaDePrueba().obtener_modelo())
        ahora = timezone.now()
        self.extra = Hallazgo.objects.create(
            codigo_regla='EXT-999', content_type=tipo, object_id='1',
            modulo=MODULO_EXTRAS, criticidad=CRITICIDAD_INFORMATIVA,
            titulo='Hallazgo de Extras', ultima_deteccion=ahora, estado=Hallazgo.PENDIENTE)
        self.normal = Hallazgo.objects.create(
            codigo_regla='PRUEBA-002', content_type=tipo, object_id='2',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_ALTA,
            titulo='Hallazgo normal', ultima_deteccion=ahora, estado=Hallazgo.PENDIENTE)

    def _peticion(self, querystring=''):
        from django.test import RequestFactory

        peticion = RequestFactory().get(f'/subsanacion/panel/hallazgos/{querystring}')
        peticion.user = self.admin
        return peticion

    def test_todas_excluye_extras(self):
        from .filtros import filtrar_hallazgos

        consulta, filtros = filtrar_hallazgos(self._peticion())
        ids = set(consulta.values_list('id', flat=True))
        self.assertIn(self.normal.id, ids)
        self.assertNotIn(self.extra.id, ids)

    def test_filtrar_por_extras_explicitamente_lo_muestra(self):
        from .constantes import MODULO_EXTRAS
        from .filtros import filtrar_hallazgos

        consulta, filtros = filtrar_hallazgos(self._peticion(f'?modulo={MODULO_EXTRAS}'))
        ids = set(consulta.values_list('id', flat=True))
        self.assertIn(self.extra.id, ids)
        self.assertNotIn(self.normal.id, ids)

    def test_badge_de_la_pestana_hallazgos_excluye_extras(self):
        from .views import _contexto_dashboard

        self.assertEqual(_contexto_dashboard()['total_vigentes'], 1)


class NotaObligatoriaTests(TestCase):
    """Ignorar un hallazgo o marcarlo como falso positivo exige explicar por qué."""

    def setUp(self):
        tipo = ContentType.objects.get_for_model(ReglaDePrueba().obtener_modelo())
        self.hallazgo = Hallazgo.objects.create(
            codigo_regla='PRUEBA-NOTA', content_type=tipo, object_id='1',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_ALTA,
            titulo='Hallazgo de prueba', ultima_deteccion=timezone.now(),
            estado=Hallazgo.PENDIENTE)

    def test_ignorar_sin_nota_se_rechaza(self):
        from .servicios import cambiar_estado_hallazgo

        with self.assertRaises(ValueError):
            cambiar_estado_hallazgo(self.hallazgo, Hallazgo.IGNORADO, nota='')

        self.hallazgo.refresh_from_db()
        self.assertEqual(self.hallazgo.estado, Hallazgo.PENDIENTE)

    def test_falso_positivo_sin_nota_se_rechaza(self):
        from .servicios import cambiar_estado_hallazgo

        with self.assertRaises(ValueError):
            cambiar_estado_hallazgo(self.hallazgo, Hallazgo.FALSO_POSITIVO, nota='   ')

    def test_ignorar_con_nota_se_acepta(self):
        from .servicios import cambiar_estado_hallazgo

        cambiar_estado_hallazgo(
            self.hallazgo, Hallazgo.IGNORADO, nota='No aplica en este caso.')
        self.hallazgo.refresh_from_db()
        self.assertEqual(self.hallazgo.estado, Hallazgo.IGNORADO)

    def test_marcar_en_revision_no_exige_nota(self):
        """Solo Ignorado y Falso positivo exigen nota; el resto de estados no."""
        from .servicios import cambiar_estado_hallazgo

        cambiar_estado_hallazgo(self.hallazgo, Hallazgo.EN_REVISION, nota='')
        self.hallazgo.refresh_from_db()
        self.assertEqual(self.hallazgo.estado, Hallazgo.EN_REVISION)


class AvisoDeCriticasTests(TestCase):
    """El receptor de `notificaciones` avisa a los administradores de una crítica nueva.

    Vive en `subsanacion/tests.py` y no en `notificaciones` porque lo que se prueba es
    el CONTRATO de la señal (qué hallazgos cuentan como «nuevos» y qué le llega al
    receptor), no los detalles internos de `notificaciones`. El receptor en sí está en
    `notificaciones/receptores.py`, conectado desde `notificaciones/apps.py::ready()`.
    """

    def setUp(self):
        from usuarios.models import CustomUser

        self.admin = CustomUser(username='admin_prueba', es_admin=True, is_active=True)
        self.admin.set_password('contraseña-de-prueba')
        self.admin.save()
        self.ejecucion = EjecucionAnalisis.objects.create(estado=EjecucionAnalisis.COMPLETA)
        self.tipo = ContentType.objects.get_for_model(ReglaDePrueba().obtener_modelo())

    def test_una_critica_nueva_notifica_a_los_admins(self):
        from notificaciones.models import Notificacion
        from subsanacion.constantes import CRITICIDAD_CRITICA
        from subsanacion.signals import analisis_finalizado

        Hallazgo.objects.create(
            codigo_regla='PRUEBA-CRIT', content_type=self.tipo, object_id='1',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_CRITICA,
            titulo='Crítica de prueba', ultima_deteccion=timezone.now(),
            ejecucion=self.ejecucion, estado=Hallazgo.PENDIENTE)

        analisis_finalizado.send(sender=EjecucionAnalisis, ejecucion=self.ejecucion)

        self.assertEqual(
            Notificacion.objects.filter(destinatario=self.admin).count(), 1)

    def test_una_critica_antigua_no_notifica_de_nuevo(self):
        """Un hallazgo que ya existía antes de esta ejecución no es «nuevo»."""
        from notificaciones.models import Notificacion
        from subsanacion.constantes import CRITICIDAD_CRITICA
        from subsanacion.signals import analisis_finalizado

        antigua = timezone.now() - timezone.timedelta(days=10)
        hallazgo = Hallazgo.objects.create(
            codigo_regla='PRUEBA-VIEJA', content_type=self.tipo, object_id='2',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_CRITICA,
            titulo='Crítica antigua', ultima_deteccion=timezone.now(),
            ejecucion=self.ejecucion, estado=Hallazgo.PENDIENTE)
        Hallazgo.objects.filter(pk=hallazgo.pk).update(primera_deteccion=antigua)

        analisis_finalizado.send(sender=EjecucionAnalisis, ejecucion=self.ejecucion)

        self.assertEqual(Notificacion.objects.filter(destinatario=self.admin).count(), 0)

    def test_una_critica_de_media_no_notifica(self):
        from notificaciones.models import Notificacion
        from subsanacion.constantes import CRITICIDAD_MEDIA
        from subsanacion.signals import analisis_finalizado

        Hallazgo.objects.create(
            codigo_regla='PRUEBA-MEDIA', content_type=self.tipo, object_id='3',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_MEDIA,
            titulo='Media de prueba', ultima_deteccion=timezone.now(),
            ejecucion=self.ejecucion, estado=Hallazgo.PENDIENTE)

        analisis_finalizado.send(sender=EjecucionAnalisis, ejecucion=self.ejecucion)

        self.assertEqual(Notificacion.objects.filter(destinatario=self.admin).count(), 0)

    def test_admin_sin_unidades_ve_su_notificacion_personal(self):
        """El caso real que motivó `destinatario`: un admin sin unidades asignadas."""
        from notificaciones.views import _notificaciones_del_usuario
        from subsanacion.constantes import CRITICIDAD_CRITICA
        from subsanacion.signals import analisis_finalizado

        self.assertEqual(self.admin.unidades.count(), 0)

        Hallazgo.objects.create(
            codigo_regla='PRUEBA-VISIBLE', content_type=self.tipo, object_id='4',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_CRITICA,
            titulo='Visible para el admin', ultima_deteccion=timezone.now(),
            ejecucion=self.ejecucion, estado=Hallazgo.PENDIENTE)
        analisis_finalizado.send(sender=EjecucionAnalisis, ejecucion=self.ejecucion)

        self.assertEqual(_notificaciones_del_usuario(self.admin).count(), 1)


class ReglasRetiradasTests(TestCase):
    """Los hallazgos de una regla que ya no existe no pueden quedarse abiertos.

    La reconciliación se acota por `codigo_regla`, así que si una regla se retira su
    consulta no vuelve a ejecutarse y sus hallazgos se quedarían vigentes para siempre,
    penalizando el índice sin que nada pudiera comprobarlos.
    """

    def setUp(self):
        from .constantes import CLAVES_MODULOS
        self.ejecucion = EjecucionAnalisis.objects.create(
            estado=EjecucionAnalisis.EN_CURSO,
            modulos_solicitados=list(CLAVES_MODULOS),
            modulos_completados=list(CLAVES_MODULOS),
        )
        tipo = ContentType.objects.get_for_model(ReglaDePrueba().obtener_modelo())
        self.huerfano = Hallazgo.objects.create(
            codigo_regla='RETIRADA-999', content_type=tipo, object_id='7',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_ALTA,
            titulo='Hallazgo de una regla que ya no existe',
            ultima_deteccion=timezone.now(), estado=Hallazgo.PENDIENTE)

    def test_analisis_completo_archiva_los_huerfanos(self):
        from .servicios import archivar_hallazgos_de_reglas_retiradas

        archivados = archivar_hallazgos_de_reglas_retiradas(self.ejecucion)
        self.assertEqual(archivados, 1)

        self.huerfano.refresh_from_db()
        self.assertFalse(self.huerfano.vigente)
        # NO se marca como corregido: nadie lo corrigió, solo dejó de comprobarse.
        self.assertEqual(self.huerfano.estado, Hallazgo.PENDIENTE)
        self.assertFalse(self.huerfano.resuelto_automaticamente)

        revision = self.huerfano.revisiones.get()
        self.assertTrue(revision.automatica)
        self.assertIn('se retiró', revision.nota)

    def test_analisis_parcial_no_archiva_nada(self):
        """En un análisis parcial no se puede distinguir «retirada» de «no ejecutada»."""
        from .servicios import archivar_hallazgos_de_reglas_retiradas

        self.ejecucion.modulos_solicitados = [MODULO_CONTRATOS]
        self.ejecucion.modulos_completados = [MODULO_CONTRATOS]
        self.ejecucion.save()

        self.assertEqual(archivar_hallazgos_de_reglas_retiradas(self.ejecucion), 0)
        self.huerfano.refresh_from_db()
        self.assertTrue(self.huerfano.vigente)


class RegistroDeReglasTests(TestCase):
    """El catálogo real tiene que estar bien formado."""

    def test_las_reglas_declaran_todo_lo_obligatorio(self):
        from .reglas import obtener_reglas

        reglas = obtener_reglas()
        self.assertGreater(len(reglas), 0, 'No se descubrió ninguna regla.')

        codigos = [regla.codigo for regla in reglas]
        self.assertEqual(len(codigos), len(set(codigos)),
                         'Hay códigos de regla duplicados.')

        for regla in reglas:
            with self.subTest(regla=regla.codigo):
                # Los cuatro textos de la guía son la razón de ser del módulo: un
                # hallazgo sin explicación ni solución no ayuda a nadie.
                self.assertTrue(regla.descripcion)
                self.assertTrue(regla.causa_probable)
                self.assertTrue(regla.impacto)
                self.assertTrue(regla.solucion)
                # El modelo tiene que resolverse de verdad.
                self.assertIsNotNone(regla.obtener_modelo())

    def test_toda_regla_tiene_un_enlace_al_registro(self):
        """Si un hallazgo no lleva a ninguna parte, el usuario no puede corregirlo."""
        from .enlaces import ENLACES_POR_MODELO
        from .reglas import obtener_reglas

        for regla in obtener_reglas():
            with self.subTest(regla=regla.codigo):
                self.assertIn(
                    regla.modelo_del_enlace(), ENLACES_POR_MODELO,
                    f'La regla {regla.codigo} apunta a «{regla.modelo_del_enlace()}», '
                    f'que no está en ENLACES_POR_MODELO, así que sus hallazgos no '
                    f'tendrían botón para llegar al registro.')


class FuncionesPurasEnCalienteTests(TestCase):
    """Las funciones puras que comparten `ejecutar()` y `evaluar_instancia()`.

    Son la garantía real de que el barrido periódico y la alerta en caliente nunca
    puedan divergir: como ambos métodos llaman a la MISMA función, probarla una vez
    cubre a los dos. No hace falta un CAlta real: son funciones de valores escalares.
    """

    def test_funcionario_o_designado_sin_codigo(self):
        from .reglas.contratos import _funcionario_o_designado_sin_codigo

        self.assertEqual(
            _funcionario_o_designado_sin_codigo(True, False, '', ''),
            [('funcionario_sin_codigo', 'Funcionario', 'funcionario_res')])
        self.assertEqual(
            _funcionario_o_designado_sin_codigo(False, True, '', None),
            [('designado_sin_codigo', 'Designado', 'designado_res')])
        self.assertEqual(
            _funcionario_o_designado_sin_codigo(True, True, 'RES-1', 'RES-2'), [])
        self.assertEqual(
            _funcionario_o_designado_sin_codigo(False, False, '', ''), [])

    def test_fechas_de_vencimiento_faltantes(self):
        from datetime import date

        from .reglas.contratos import _fechas_de_vencimiento_faltantes

        hoy = date.today()
        self.assertEqual(_fechas_de_vencimiento_faltantes(None, None, None), [
            ('fecha_vence_lic', 'licencia'),
            ('fecha_vence_recal', 'recalificación'),
            ('fecha_vence_seg', 'seguro')])
        self.assertEqual(_fechas_de_vencimiento_faltantes(hoy, hoy, hoy), [])
        self.assertEqual(_fechas_de_vencimiento_faltantes(hoy, None, hoy), [
            ('fecha_vence_recal', 'recalificación')])

    def test_campo_de_texto_vacio(self):
        from .reglas.aspirantes import _campo_de_texto_vacio

        self.assertTrue(_campo_de_texto_vacio(None))
        self.assertTrue(_campo_de_texto_vacio(''))
        self.assertTrue(_campo_de_texto_vacio('   '))
        self.assertFalse(_campo_de_texto_vacio('54212345'))

    def test_mision_sin_pais(self):
        from .reglas.contratos import _mision_sin_pais

        self.assertTrue(_mision_sin_pais(True, None))
        self.assertTrue(_mision_sin_pais(True, ''))
        self.assertFalse(_mision_sin_pais(True, 'Brasil'))
        self.assertFalse(_mision_sin_pais(False, None))

    def test_c_formal_sin_res(self):
        from .reglas.contratos import _c_formal_sin_res

        self.assertTrue(_c_formal_sin_res(True, None))
        self.assertTrue(_c_formal_sin_res(True, ''))
        self.assertFalse(_c_formal_sin_res(True, 'RES-1'))
        self.assertFalse(_c_formal_sin_res(False, None))

    def test_tridente_indebido(self):
        from .reglas.contratos import _tridente_indebido

        # Fijo con tridente: indebido sin importar si el cargo es Cuadro o no.
        self.assertEqual(_tridente_indebido('FIJ', False), 'fijo_con_tridente')
        self.assertEqual(_tridente_indebido('FIJ', True), 'fijo_con_tridente')
        # Dinámico en cargo de Cuadro: indebido (el caso «Fvdb Fdbfdb Dfb»).
        self.assertEqual(_tridente_indebido('DIN', True), 'cuadro_con_tridente')
        # Dinámico en cargo que no es Cuadro: correcto, el tridente sí aplica.
        self.assertEqual(_tridente_indebido('DIN', False), '')

    def test_tallas_incompletas(self):
        from .reglas.extras import _tallas_incompletas

        self.assertEqual(
            _tallas_incompletas(None, None, None),
            ['pantalón', 'camisa/blusa', 'zapatos'])
        self.assertEqual(_tallas_incompletas('32', 'M', 42), [])
        # `tzapatos` es un IntegerField: 0 es una talla válida, no "vacío".
        self.assertEqual(_tallas_incompletas('32', 'M', 0), [])
        self.assertEqual(_tallas_incompletas('32', None, 42), ['camisa/blusa'])


class EvaluarInstanciaTests(TestCase):
    """`evaluar_instancia()` de CTR-012/013 sobre una instancia real, no un dict.

    Se usa `SimpleNamespace` en vez de un `CAlta` real: los tres métodos solo acceden
    a atributos propios y a un único salto de FK ya resuelto (`contrato.aspirante`),
    exactamente la restricción O(1) que exige `ReglaBase.evaluar_instancia()` — así que
    un objeto con esos atributos puestos a mano ejercita el mismo código que un CAlta
    de verdad, sin necesitar el grafo completo de fixtures (aspirante, cargo,
    plantilla, etc.).
    """

    def test_funcionario_sin_codigo_detectado(self):
        from types import SimpleNamespace

        from .reglas.contratos import FuncionarioODesignadoSinCodigo

        contrato = SimpleNamespace(
            pk=1, funcionario=True, designado=False,
            funcionario_res='', designado_res='')

        detectados = FuncionarioODesignadoSinCodigo().evaluar_instancia(contrato)

        self.assertEqual(len(detectados), 1)
        self.assertEqual(detectados[0].clave_extra, 'funcionario_sin_codigo')

    def test_chofer_sin_fechas_detectado(self):
        from types import SimpleNamespace

        from .reglas.contratos import ChoferSinFechasDeVencimiento

        contrato = SimpleNamespace(
            pk=1, profesional=True,
            fecha_vence_lic=None, fecha_vence_recal=None, fecha_vence_seg=None)

        detectados = ChoferSinFechasDeVencimiento().evaluar_instancia(contrato)

        self.assertEqual(len(detectados), 1)
        self.assertIn('licencia', detectados[0].detalle)

    def test_chofer_no_profesional_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.contratos import ChoferSinFechasDeVencimiento

        contrato = SimpleNamespace(
            pk=1, profesional=False,
            fecha_vence_lic=None, fecha_vence_recal=None, fecha_vence_seg=None)

        self.assertIsNone(ChoferSinFechasDeVencimiento().evaluar_instancia(contrato))

    def test_movil_personal_vacio_detectado(self):
        """ASP-005 vive ahora en `reglas/extras.py` (módulo Extras, ver ronda de
        RRHH que decidió que el móvil no es un dato importante), pero sigue
        detectando exactamente igual: solo cambió dónde cuenta, no qué detecta."""
        from types import SimpleNamespace

        from .reglas.extras import MovilPersonalVacio

        aspirante = SimpleNamespace(pk=1, movil_personal='')

        detectados = MovilPersonalVacio().evaluar_instancia(aspirante)

        self.assertEqual(len(detectados), 1)

    def test_movil_personal_completo_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.extras import MovilPersonalVacio

        aspirante = SimpleNamespace(pk=1, movil_personal='54212345')

        self.assertIsNone(MovilPersonalVacio().evaluar_instancia(aspirante))

    def test_direccion_vacia_detectada(self):
        from types import SimpleNamespace

        from .reglas.aspirantes import DireccionVacia

        aspirante = SimpleNamespace(pk=1, direccion=None)

        detectados = DireccionVacia().evaluar_instancia(aspirante)

        self.assertEqual(len(detectados), 1)

    def test_nivel_educativo_vacio_detectado(self):
        from types import SimpleNamespace

        from .reglas.aspirantes import NivelEducativoSinCompletar

        aspirante = SimpleNamespace(pk=1, nivel_educ=None)

        detectados = NivelEducativoSinCompletar().evaluar_instancia(aspirante)

        self.assertEqual(len(detectados), 1)

    def test_nivel_educativo_sin_acreditar_no_es_vacio(self):
        """'SA' (Sin Acreditar) es una respuesta válida del formulario, no un vacío."""
        from types import SimpleNamespace

        from .reglas.aspirantes import NivelEducativoSinCompletar

        aspirante = SimpleNamespace(pk=1, nivel_educ='SA')

        self.assertIsNone(NivelEducativoSinCompletar().evaluar_instancia(aspirante))

    def test_mision_sin_pais_detectada(self):
        from types import SimpleNamespace

        from .reglas.contratos import MisionSinPais

        contrato = SimpleNamespace(pk=1, mision=True, pais=None)

        detectados = MisionSinPais().evaluar_instancia(contrato)

        self.assertEqual(len(detectados), 1)

    def test_sin_mision_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.contratos import MisionSinPais

        contrato = SimpleNamespace(pk=1, mision=False, pais=None)

        self.assertIsNone(MisionSinPais().evaluar_instancia(contrato))

    def test_c_formal_sin_codigo_detectado(self):
        from types import SimpleNamespace

        from .reglas.contratos import ConformidadFormalSinCodigo

        contrato = SimpleNamespace(pk=1, c_formal=True, c_formal_res='')

        detectados = ConformidadFormalSinCodigo().evaluar_instancia(contrato)

        self.assertEqual(len(detectados), 1)

    def test_sin_c_formal_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.contratos import ConformidadFormalSinCodigo

        contrato = SimpleNamespace(pk=1, c_formal=False, c_formal_res='')

        self.assertIsNone(ConformidadFormalSinCodigo().evaluar_instancia(contrato))

    def test_tridente_indebido_en_cuadro_detectado(self):
        from types import SimpleNamespace

        from .reglas.contratos import TridenteIndebido

        contrato = SimpleNamespace(
            pk=73, tipo_salario='DIN', tridente_id=1,
            tridente=SimpleNamespace(tipo='I'),
            cargo_id=6, cargo=SimpleNamespace(ncargo=SimpleNamespace(es_cuadro=True)))

        detectados = TridenteIndebido().evaluar_instancia(contrato)

        self.assertEqual(len(detectados), 1)
        self.assertEqual(detectados[0].clave_extra, 'cuadro_con_tridente')

    def test_tridente_sin_asignar_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.contratos import TridenteIndebido

        contrato = SimpleNamespace(
            pk=73, tipo_salario='DIN', tridente_id=None, tridente=None,
            cargo_id=6, cargo=SimpleNamespace(ncargo=SimpleNamespace(es_cuadro=True)))

        self.assertIsNone(TridenteIndebido().evaluar_instancia(contrato))

    def test_tallas_incompletas_genera_un_solo_hallazgo(self):
        """Un único hallazgo por aspirante, aunque falten varias tallas — no uno
        por talla (a diferencia de CTR-002/CTR-007, que sí usan `clave_extra`)."""
        from types import SimpleNamespace

        from .reglas.extras import TallasSinCompletar

        aspirante = SimpleNamespace(pk=1, tpantalon='', tcamisa='M', tzapatos=None)

        detectados = TallasSinCompletar().evaluar_instancia(aspirante)

        self.assertEqual(len(detectados), 1)
        self.assertIn('pantalón', detectados[0].detalle)
        self.assertIn('zapatos', detectados[0].detalle)
        self.assertNotIn('camisa', detectados[0].detalle)

    def test_tallas_completas_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.extras import TallasSinCompletar

        aspirante = SimpleNamespace(pk=1, tpantalon='32', tcamisa='M', tzapatos=42)

        self.assertIsNone(TallasSinCompletar().evaluar_instancia(aspirante))

    def test_fijo_personal_vacio_detectado(self):
        from types import SimpleNamespace

        from .reglas.extras import TelefonoFijoSinCompletar

        aspirante = SimpleNamespace(pk=1, fijo_personal='')

        detectados = TelefonoFijoSinCompletar().evaluar_instancia(aspirante)

        self.assertEqual(len(detectados), 1)

    def test_fijo_personal_completo_devuelve_none(self):
        from types import SimpleNamespace

        from .reglas.extras import TelefonoFijoSinCompletar

        aspirante = SimpleNamespace(pk=1, fijo_personal='78345678')

        self.assertIsNone(TelefonoFijoSinCompletar().evaluar_instancia(aspirante))


class EvaluarReglasDeInstanciaTests(TestCase):
    """El despachador de `en_caliente.py`: solo reglas `evaluable_en_caliente` y del
    modelo correcto entran a evaluarse; solo las que detectan algo salen en el resultado."""

    def test_filtra_por_evaluable_en_caliente_y_modelo(self):
        from .en_caliente import evaluar_reglas_de_instancia

        candidata = ReglaDePrueba(hallazgos=[
            HallazgoDetectado(object_id='1', titulo='Detectado')])
        candidata.evaluable_en_caliente = True
        # `ReglaDePrueba` no implementa evaluar_instancia(); se le añade uno mínimo
        # que reutiliza sus propios hallazgos de prueba, para aislar el despachador.
        candidata.evaluar_instancia = lambda instancia: candidata.hallazgos

        no_evaluable = ReglaDePrueba(hallazgos=[
            HallazgoDetectado(object_id='1', titulo='No debería aparecer')])
        no_evaluable.evaluable_en_caliente = False

        from nomencladores.models import NProvincia

        from . import en_caliente

        with patch.object(en_caliente, 'obtener_reglas', return_value=[candidata, no_evaluable]):
            instancia = NProvincia.objects.create(nombre='Provincia de en_caliente')
            resultados = en_caliente.evaluar_reglas_de_instancia(instancia)

        self.assertEqual(len(resultados), 1)
        regla, detectados = resultados[0]
        self.assertIs(regla, candidata)
        self.assertEqual(detectados, candidata.hallazgos)


class ReconciliarHallazgosEnCalienteTests(TestCase):
    """`servicios.reconciliar_hallazgos_en_caliente()`: cierre en caliente de un
    hallazgo cuando la instancia recién guardada ya no lo detecta — sin esperar al
    barrido periódico. Es lo que permite que corregir un dato desde su formulario
    (p. ej. el tridente de CTR-009) marque el hallazgo como Corregido al instante."""

    def _regla_en_caliente(self, hallazgos_actuales):
        candidata = ReglaDePrueba()
        candidata.evaluable_en_caliente = True
        candidata.evaluar_instancia = lambda instancia: hallazgos_actuales
        return candidata

    def _crear_pendiente(self, instancia, estado=Hallazgo.PENDIENTE, clave_extra=''):
        tipo = ContentType.objects.get_for_model(instancia, for_concrete_model=True)
        return Hallazgo.objects.create(
            codigo_regla='PRUEBA-001', content_type=tipo, object_id=str(instancia.pk),
            clave_extra=clave_extra, modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_ALTA,
            titulo='Hallazgo de prueba', ultima_deteccion=timezone.now(), estado=estado)

    def test_cierra_el_hallazgo_que_ya_no_se_detecta(self):
        from nomencladores.models import NProvincia

        from . import en_caliente, servicios

        instancia = NProvincia.objects.create(nombre='Provincia de reconciliación')
        pendiente = self._crear_pendiente(instancia)
        candidata = self._regla_en_caliente([])  # ya no detecta nada

        with patch.object(en_caliente, 'obtener_reglas', return_value=[candidata]):
            servicios.reconciliar_hallazgos_en_caliente(instancia)

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, Hallazgo.CORREGIDO)
        self.assertFalse(pendiente.vigente)
        self.assertTrue(pendiente.resuelto_automaticamente)
        self.assertEqual(pendiente.revisiones.count(), 1)
        self.assertEqual(pendiente.revisiones.first().estado_anterior, Hallazgo.PENDIENTE)

    def test_no_toca_el_hallazgo_si_sigue_detectandose(self):
        from nomencladores.models import NProvincia

        from . import en_caliente, servicios

        instancia = NProvincia.objects.create(nombre='Provincia todavía con problema')
        pendiente = self._crear_pendiente(instancia)
        # Sigue detectando el mismo `clave_extra` ('') que el hallazgo pendiente.
        candidata = self._regla_en_caliente([hallazgo(instancia.pk)])

        with patch.object(en_caliente, 'obtener_reglas', return_value=[candidata]):
            servicios.reconciliar_hallazgos_en_caliente(instancia)

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, Hallazgo.PENDIENTE)
        self.assertTrue(pendiente.vigente)
        self.assertEqual(pendiente.revisiones.count(), 0)

    def test_no_reabre_un_ignorado(self):
        """Un Ignorado lo decidió una persona; no lo toca aunque el dato cambie —
        mismo criterio que la rama «desaparecidos» de `reconciliar_regla()`."""
        from nomencladores.models import NProvincia

        from . import en_caliente, servicios

        instancia = NProvincia.objects.create(nombre='Provincia ignorada')
        ignorado = self._crear_pendiente(instancia, estado=Hallazgo.IGNORADO)
        candidata = self._regla_en_caliente([])  # ya no detecta nada

        with patch.object(en_caliente, 'obtener_reglas', return_value=[candidata]):
            servicios.reconciliar_hallazgos_en_caliente(instancia)

        ignorado.refresh_from_db()
        self.assertEqual(ignorado.estado, Hallazgo.IGNORADO)


class PermisosSubsanacionTests(TestCase):
    """Control de acceso (`subsanacion/permisos.py`): Administrador ve y actúa sobre
    toda la empresa, Moderador solo sobre sus propias Unidades Organizativas (ni
    manipulando la URL a mano), Observador no entra en absoluto."""

    @classmethod
    def setUpTestData(cls):
        from usuarios.models import CustomUser
        from nomencladores.models import NTipoUnidadOrganizativa
        from strorganizativa.models import UnidadOrganizativa

        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        cls.uo_propia = UnidadOrganizativa.objects.create(
            descripcion='UEB del moderador', tipo=tipo_unidad, grupo_nomina=1, orden_informe=1)
        cls.uo_ajena = UnidadOrganizativa.objects.create(
            descripcion='UEB ajena', tipo=tipo_unidad, grupo_nomina=1, orden_informe=2)

        cls.admin = CustomUser.objects.create_user(
            username='admin_permisos', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='moderador_permisos', password='x', es_moderador=True)
        cls.moderador.unidades.set([cls.uo_propia])
        cls.observador = CustomUser.objects.create_user(
            username='observador_permisos', password='x', es_observador=True)

        tipo = ContentType.objects.get_for_model(ReglaDePrueba().obtener_modelo())
        ahora = timezone.now()
        cls.hallazgo_propio = Hallazgo.objects.create(
            codigo_regla='PERM-001', content_type=tipo, object_id='1',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_ALTA, titulo='De la UO propia',
            ultima_deteccion=ahora, estado=Hallazgo.PENDIENTE,
            unidad_organizativa=cls.uo_propia)
        cls.hallazgo_ajeno = Hallazgo.objects.create(
            codigo_regla='PERM-002', content_type=tipo, object_id='2',
            modulo=MODULO_CONTRATOS, criticidad=CRITICIDAD_ALTA, titulo='De la UO ajena',
            ultima_deteccion=ahora, estado=Hallazgo.PENDIENTE,
            unidad_organizativa=cls.uo_ajena)

    # --- Acceso general -----------------------------------------------------

    def test_observador_no_accede_al_index(self):
        self.client.force_login(self.observador)
        respuesta = self.client.get(reverse('subsanacion:index'))
        self.assertEqual(respuesta.status_code, 403)

    def test_anonimo_no_accede_al_index(self):
        respuesta = self.client.get(reverse('subsanacion:index'))
        self.assertIn(respuesta.status_code, (302, 403))

    def test_admin_accede_al_index(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('subsanacion:index'))
        self.assertEqual(respuesta.status_code, 200)

    def test_moderador_accede_al_index(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('subsanacion:index'))
        self.assertEqual(respuesta.status_code, 200)

    # --- Paneles exclusivos de Administrador (barrido completo) -------------

    def test_moderador_no_accede_al_dashboard(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('subsanacion:panel_dashboard'))
        self.assertEqual(respuesta.status_code, 403)

    def test_moderador_no_accede_a_estadisticas(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('subsanacion:panel_estadisticas'))
        self.assertEqual(respuesta.status_code, 403)

    def test_moderador_no_accede_a_revisiones(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('subsanacion:panel_revisiones'))
        self.assertEqual(respuesta.status_code, 403)

    def test_moderador_no_puede_iniciar_analisis(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.post(reverse('subsanacion:iniciar_analisis'))
        self.assertEqual(respuesta.status_code, 403)

    def test_observador_no_accede_a_ningun_panel(self):
        self.client.force_login(self.observador)
        for nombre in ('subsanacion:panel_hallazgos', 'subsanacion:panel_dashboard',
                       'subsanacion:panel_analisis'):
            respuesta = self.client.get(reverse(nombre))
            self.assertEqual(respuesta.status_code, 403, nombre)

    # --- Alcance por Unidad Organizativa en el listado -----------------------

    def test_admin_ve_hallazgos_de_todas_las_uo(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('subsanacion:panel_hallazgos'))
        contenido = respuesta.content.decode('utf-8', errors='replace')
        self.assertIn('De la UO propia', contenido)
        self.assertIn('De la UO ajena', contenido)

    def test_moderador_solo_ve_hallazgos_de_su_uo(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('subsanacion:panel_hallazgos'))
        contenido = respuesta.content.decode('utf-8', errors='replace')
        self.assertIn('De la UO propia', contenido)
        self.assertNotIn('De la UO ajena', contenido)

    # --- Seguridad: manipulación directa de URL/pk ---------------------------

    def test_moderador_no_accede_al_detalle_de_un_hallazgo_ajeno_por_url(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('subsanacion:detalle_hallazgo', args=[self.hallazgo_ajeno.pk]))
        self.assertEqual(respuesta.status_code, 404)

    def test_moderador_accede_al_detalle_de_su_propio_hallazgo(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(
            reverse('subsanacion:detalle_hallazgo', args=[self.hallazgo_propio.pk]))
        self.assertEqual(respuesta.status_code, 200)

    def test_moderador_no_puede_cambiar_estado_de_un_hallazgo_ajeno_por_url(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.post(
            reverse('subsanacion:cambiar_estado', args=[self.hallazgo_ajeno.pk]),
            {'estado': Hallazgo.EN_REVISION, 'nota': ''})
        self.assertEqual(respuesta.status_code, 404)
        self.hallazgo_ajeno.refresh_from_db()
        self.assertEqual(self.hallazgo_ajeno.estado, Hallazgo.PENDIENTE)

    def test_moderador_puede_cambiar_estado_de_su_propio_hallazgo(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.post(
            reverse('subsanacion:cambiar_estado', args=[self.hallazgo_propio.pk]),
            {'estado': Hallazgo.EN_REVISION, 'nota': ''})
        self.assertEqual(respuesta.status_code, 200)
        self.hallazgo_propio.refresh_from_db()
        self.assertEqual(self.hallazgo_propio.estado, Hallazgo.EN_REVISION)

    def test_moderador_no_puede_exportar_hallazgos_ajenos(self):
        self.client.force_login(self.moderador)
        respuesta = self.client.get(reverse('subsanacion:exportar_excel'))
        self.assertEqual(respuesta.status_code, 200)
        import io

        from openpyxl import load_workbook
        hoja = load_workbook(io.BytesIO(respuesta.content)).active
        textos = [str(valor) for fila in hoja.iter_rows(values_only=True) for valor in fila if valor]
        self.assertTrue(any('De la UO propia' in t for t in textos))


class ContratoSinFechaAltaEntidadTests(TestCase):
    """CTR-016: detecta contratos sin F. Alta Entidad registrada."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from bolsa.models import Aspirante
        from contratos.models import CAlta
        from nomencladores.models import NMunicipio, NProvincia, NTipoContrato

        provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=False, requiere_motivo=False)

        cls.aspirante_sin = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Sin', papellido='Alta', sapellido='Entidad',
            doc_identidad='90010112301', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.contrato_sin = CAlta.objects.create(
            aspirante=cls.aspirante_sin, no_expediente='90001', tipo=tipo_contrato,
            fecha_alta=date.today())

        cls.aspirante_con = Aspirante.objects.create(nivel_educ='SA', 
            nombre='Con', papellido='Alta', sapellido='Entidad',
            doc_identidad='90010112302', estado='ACTIVO', sexo='F', raza='BL',
            provincia=provincia, municipio=municipio)
        cls.contrato_con = CAlta.objects.create(
            aspirante=cls.aspirante_con, no_expediente='90002', tipo=tipo_contrato,
            fecha_alta=date.today(), fecha_alta_entidad=date.today())

    def test_detecta_solo_el_contrato_sin_fecha_alta_entidad(self):
        from .reglas.contratos import ContratoSinFechaAltaEntidad

        regla = ContratoSinFechaAltaEntidad()
        hallazgos = list(regla.ejecutar(None))
        object_ids = {h.object_id for h in hallazgos}

        self.assertIn(str(self.contrato_sin.pk), object_ids)
        self.assertNotIn(str(self.contrato_con.pk), object_ids)

    def test_reconciliacion_genera_hallazgo_con_unidad_organizativa(self):
        ejecucion = EjecucionAnalisis.objects.create(estado=EjecucionAnalisis.COMPLETA)
        from .reglas.contratos import ContratoSinFechaAltaEntidad

        regla = ContratoSinFechaAltaEntidad()
        resultado = reconciliar_regla(regla, ejecucion, ContextoAnalisis(ejecucion))
        # Ya lo creó la revisión por registro al guardar el contrato (Fase 2): el
        # análisis lo encuentra y lo refresca en lugar de crearlo de nuevo.
        self.assertEqual(resultado['nuevos'] + resultado['persistentes'], 1)

        creado = Hallazgo.objects.get(
            codigo_regla='CTR-016', object_id=str(self.contrato_sin.pk))
        self.assertIsNone(creado.unidad_organizativa_id)
        self.assertEqual(creado.criticidad, CRITICIDAD_ALTA)


class ContratoFechaAltaEntidadImposibleTests(TestCase):
    """CTR-017: detecta la F. Alta Entidad con un año anterior a 1900.

    Los tres casos que definen la regla: año imposible (se reporta), año correcto
    (no) y sin fecha (no: ese es el terreno de CTR-016, y contarlo dos veces
    duplicaría el mismo contrato en el panel)."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from bolsa.models import Aspirante
        from contratos.models import CAlta
        from nomencladores.models import NMunicipio, NProvincia, NTipoContrato

        provincia = NProvincia.objects.create(nombre='Mayabeque', siglas='MAY')
        municipio = NMunicipio.objects.create(
            nombre='Güines', provincia=provincia, siglas='GUI')
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=False, requiere_motivo=False)

        def _aspirante(nombre, doc):
            return Aspirante.objects.create(nivel_educ='SA',
                nombre=nombre, papellido='Fecha', sapellido='Imposible',
                doc_identidad=doc, estado='ACTIVO', sexo='F', raza='BL',
                provincia=provincia, municipio=municipio)

        # El año 0002 es exactamente lo que deja un `<input type="date">` cuando el
        # usuario escribe «2022» y sale del campo antes de terminar el año.
        cls.contrato_imposible = CAlta.objects.create(
            aspirante=_aspirante('Mala', '90010112401'), no_expediente='90101',
            tipo=tipo_contrato, fecha_alta=date.today(),
            fecha_alta_entidad=date(2, 5, 10))
        cls.contrato_correcto = CAlta.objects.create(
            aspirante=_aspirante('Buena', '90010112402'), no_expediente='90102',
            tipo=tipo_contrato, fecha_alta=date.today(),
            fecha_alta_entidad=date(2020, 5, 10))
        cls.contrato_sin_fecha = CAlta.objects.create(
            aspirante=_aspirante('Vacia', '90010112403'), no_expediente='90103',
            tipo=tipo_contrato, fecha_alta=date.today())

    def test_detecta_solo_el_contrato_con_ano_imposible(self):
        from .reglas.contratos import ContratoFechaAltaEntidadImposible

        regla = ContratoFechaAltaEntidadImposible()
        object_ids = {h.object_id for h in regla.ejecutar(None)}

        self.assertIn(str(self.contrato_imposible.pk), object_ids)
        self.assertNotIn(str(self.contrato_correcto.pk), object_ids)
        self.assertNotIn(str(self.contrato_sin_fecha.pk), object_ids)

    def test_el_hallazgo_muestra_la_fecha_registrada_y_apunta_al_campo(self):
        from .reglas.contratos import ContratoFechaAltaEntidadImposible

        regla = ContratoFechaAltaEntidadImposible()
        hallazgo = next(h for h in regla.ejecutar(None)
                        if h.object_id == str(self.contrato_imposible.pk))

        self.assertEqual(hallazgo.campo_formulario, 'fecha_alta_entidad')
        self.assertEqual(hallazgo.datos['fecha_registrada'], '10/05/0002')
        self.assertIn('10/05/0002', hallazgo.detalle)

    def test_los_contratos_sin_fecha_siguen_siendo_de_ctr_016(self):
        """Las dos reglas se reparten el terreno sin solaparse."""
        from .reglas.contratos import (
            ContratoFechaAltaEntidadImposible, ContratoSinFechaAltaEntidad)

        sin_fecha = {h.object_id for h in ContratoSinFechaAltaEntidad().ejecutar(None)}
        imposibles = {h.object_id
                      for h in ContratoFechaAltaEntidadImposible().ejecutar(None)}

        self.assertIn(str(self.contrato_sin_fecha.pk), sin_fecha)
        self.assertNotIn(str(self.contrato_imposible.pk), sin_fecha)
        self.assertFalse(sin_fecha & imposibles)


class TrabajadorContratadoSinEspecialidadTests(TestCase):
    """ASP-010: la especialidad solo se reclama a quien YA está contratado.

    Los cuatro casos que definen la regla: contratado con nivel que lleva
    especialidad y sin ella (se reporta), el mismo caso pero con especialidad (no),
    sin contrato (no, sigue siendo un candidato de la bolsa) y con un nivel que no
    lleva especialidad (no).
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from bolsa.models import Aspirante
        from contratos.models import CAlta
        from nomencladores.models import (
            NEspecialidad, NMunicipio, NProvincia, NTipoContrato)

        provincia = NProvincia.objects.create(nombre='Granma', siglas='GRM')
        municipio = NMunicipio.objects.create(
            nombre='Bayamo', provincia=provincia, siglas='BAY')
        tipo_contrato = NTipoContrato.objects.create(
            descripcion='Indeterminado', ocupa_plaza=False, requiere_motivo=False)
        especialidad = NEspecialidad.objects.create(
            nombre='Ing. Industrial', educ_superior=True)

        def crear(sufijo, nivel, especialidad_obj=None):
            return Aspirante.objects.create(
                nombre='Test', papellido='Especialidad', sapellido=sufijo,
                doc_identidad=f'900101123{sufijo}', estado='ACTIVO', sexo='F',
                raza='BL', provincia=provincia, municipio=municipio,
                nivel_educ=nivel, especialidad=especialidad_obj)

        def contratar(aspirante, expediente):
            return CAlta.objects.create(
                aspirante=aspirante, no_expediente=expediente, tipo=tipo_contrato,
                fecha_alta=date.today())

        cls.contratado_sin = crear('11', 'NS')
        contratar(cls.contratado_sin, '91001')

        cls.contratado_tm_sin = crear('12', 'TM')
        contratar(cls.contratado_tm_sin, '91002')

        cls.contratado_con = crear('13', 'NS', especialidad)
        contratar(cls.contratado_con, '91003')

        # Sin contrato: sigue siendo un candidato de la bolsa, no se le reclama.
        cls.en_bolsa_sin = crear('14', 'NS')

        # Nivel que no lleva especialidad.
        cls.contratado_otro_nivel = crear('15', 'PR')
        contratar(cls.contratado_otro_nivel, '91005')

    def _detectados(self):
        from .reglas.aspirantes import TrabajadorContratadoSinEspecialidad
        return {h.object_id for h in TrabajadorContratadoSinEspecialidad().ejecutar(None)}

    def test_reporta_a_los_contratados_de_nivel_ns_y_tm_sin_especialidad(self):
        detectados = self._detectados()
        self.assertIn(str(self.contratado_sin.pk), detectados)
        self.assertIn(str(self.contratado_tm_sin.pk), detectados)

    def test_no_reporta_a_quien_si_tiene_especialidad(self):
        self.assertNotIn(str(self.contratado_con.pk), self._detectados())

    def test_no_reporta_a_quien_no_tiene_contrato(self):
        self.assertNotIn(str(self.en_bolsa_sin.pk), self._detectados())

    def test_no_reporta_niveles_que_no_llevan_especialidad(self):
        self.assertNotIn(str(self.contratado_otro_nivel.pk), self._detectados())

    def test_un_trabajador_con_dos_contratos_genera_un_solo_hallazgo(self):
        """El `Exists` evita que el join multiplique el hallazgo."""
        from datetime import date

        from contratos.models import CAlta
        from .reglas.aspirantes import TrabajadorContratadoSinEspecialidad

        CAlta.objects.create(
            aspirante=self.contratado_sin, no_expediente='91009',
            tipo=CAlta.objects.first().tipo, fecha_alta=date.today())

        hallazgos = [h for h in TrabajadorContratadoSinEspecialidad().ejecutar(None)
                     if h.object_id == str(self.contratado_sin.pk)]
        self.assertEqual(len(hallazgos), 1)

    def test_el_hallazgo_apunta_al_campo_especialidad(self):
        from .reglas.aspirantes import TrabajadorContratadoSinEspecialidad

        hallazgo = next(h for h in TrabajadorContratadoSinEspecialidad().ejecutar(None)
                        if h.object_id == str(self.contratado_sin.pk))
        from .constantes import CRITICIDAD_MEDIA

        self.assertEqual(hallazgo.campo_formulario, 'especialidad')
        self.assertEqual(TrabajadorContratadoSinEspecialidad.criticidad, CRITICIDAD_MEDIA)


class EnlaceSoloAdminTests(TestCase):
    """Los enlaces marcados `solo_admin` no se ofrecen a quien no es Administrador.

    `updt_usuario` está protegida con `admin_required` (usuarios/urls.py): sin
    esta comprobación, un Moderador con un hallazgo sobre una cuenta veía el
    botón «Abrir usuario» y recibía un 403 al pulsarlo.
    """

    @classmethod
    def setUpTestData(cls):
        from usuarios.models import CustomUser
        cls.admin = CustomUser.objects.create_user(
            username='admin_enlaces', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='mod_enlaces', password='x', es_moderador=True)
        cls.observador = CustomUser.objects.create_user(
            username='obs_enlaces', password='x', es_observador=True)

    def _enlace(self, usuario):
        from subsanacion.enlaces import construir_enlace
        return construir_enlace('usuarios.CustomUser', self.moderador.pk, usuario=usuario)

    def test_el_admin_si_recibe_el_enlace(self):
        enlace = self._enlace(self.admin)
        self.assertIsNotNone(enlace)
        self.assertIn(str(self.moderador.pk), enlace['href'])

    def test_moderador_y_observador_no_reciben_el_enlace(self):
        for usuario in (self.moderador, self.observador):
            with self.subTest(usuario=usuario.username):
                self.assertIsNone(self._enlace(usuario))

    def test_sin_usuario_tampoco_se_ofrece_el_enlace(self):
        """Por defecto se niega: un llamador que olvide pasar `usuario` no debe
        acabar enseñando una puerta que da 403."""
        self.assertIsNone(self._enlace(None))

    def test_los_demas_modelos_no_se_ven_afectados(self):
        from subsanacion.enlaces import construir_enlace
        enlace = construir_enlace('configuracion.Configuracion', None, usuario=self.moderador)
        self.assertIsNotNone(enlace)


class CargoSinNivelDePreparacionTests(TestCase):
    """EST-007: el nivel de preparación del cargo es opcional, pero debe estar puesto.

    Tres casos definen la regla: cargo sin nivel (se reporta), cargo con nivel (no se
    reporta) y el hallazgo apunta al campo del formulario para que el panel de
    advertencias pueda llevar al usuario directamente al desplegable.
    """

    @classmethod
    def setUpTestData(cls):
        from nomencladores.models import (
            NCargo, NGrupoEscala, NNivelPreparacion, NTipoUnidadOrganizativa)
        from strorganizativa.models import (
            CargoPlantilla, Departamento, UnidadOrganizativa)

        grupo = NGrupoEscala.objects.create(nivel='XV')
        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='Empresa', es_principal=True)
        cls.unidad = UnidadOrganizativa.objects.create(
            codigo_interno=9001, descripcion='Unidad de prueba', tipo=tipo_unidad,
            grupo_nomina=1)
        cls.departamento = Departamento.objects.create(
            descripcion='Recursos Humanos', unidad_organizativa=cls.unidad)
        cls.nivel = NNivelPreparacion.objects.create(nombre='Nivel Superior')

        def crear_cargo(descripcion, nivel_preparacion=None):
            ncargo = NCargo.objects.create(
                descripcion=descripcion, cat_ocupacional='TEC',
                grupo_escala=grupo, salario_basico=Decimal('4000.00'))
            return CargoPlantilla.objects.create(
                ncargo=ncargo, departamento=cls.departamento,
                nivel_preparacion=nivel_preparacion, cant_aprobada=1)

        cls.sin_nivel = crear_cargo('Especialista B')
        cls.con_nivel = crear_cargo('Especialista A', cls.nivel)

    def _detectados(self):
        from .reglas.estructura import CargoSinNivelDePreparacion
        return {h.object_id for h in CargoSinNivelDePreparacion().ejecutar(None)}

    def test_reporta_el_cargo_sin_nivel_de_preparacion(self):
        self.assertIn(str(self.sin_nivel.pk), self._detectados())

    def test_no_reporta_el_cargo_que_si_lo_tiene(self):
        self.assertNotIn(str(self.con_nivel.pk), self._detectados())

    def test_el_hallazgo_apunta_al_campo_y_a_su_unidad(self):
        from .constantes import CRITICIDAD_BAJA, MODULO_ESTRUCTURA
        from .reglas.estructura import CargoSinNivelDePreparacion

        hallazgo = next(h for h in CargoSinNivelDePreparacion().ejecutar(None)
                        if h.object_id == str(self.sin_nivel.pk))

        self.assertEqual(hallazgo.campo_formulario, 'nivel_preparacion')
        # El alcance por unidad depende de este dato: sin él, el hallazgo no se
        # filtraría bien para un usuario limitado a su unidad.
        self.assertEqual(hallazgo.unidad_organizativa_id, self.unidad.pk)
        self.assertEqual(CargoSinNivelDePreparacion.criticidad, CRITICIDAD_BAJA)
        self.assertEqual(CargoSinNivelDePreparacion.modulo, MODULO_ESTRUCTURA)


# ==========================================================================
# REGLAS NUEVAS
# ==========================================================================

from datetime import date, timedelta   # noqa: E402

from bolsa.models import Aspirante   # noqa: E402
from cierres.models import (CierreUnidad, EstadoCierreUnidad,   # noqa: E402
                            EstadoUnidad)
from contratos.models import CAlta   # noqa: E402
from nomencladores.models import (NCargo, NGrupoEscala,   # noqa: E402
                                  NImporteGradoCientifico, NMunicipio,
                                  NPagoAdicional, NProvincia, NTipoContrato,
                                  NTipoUnidadOrganizativa)
from prenomina.models import NPagoImporte, TipoValorImporte   # noqa: E402
from strorganizativa.models import (CargoPlantilla,   # noqa: E402
                                    Departamento, UnidadOrganizativa)
from usuarios.models import CustomUser   # noqa: E402


class _EscenarioContratos:
    """Plantilla mínima para las reglas que miran contratos.

    Reproduce la cadena real trabajador -> unidad de Orbith:
    `CAlta.cargo -> CargoPlantilla.departamento -> Departamento.unidad_organizativa`.
    Se construye una vez por clase de prueba desde `setUpTestData`.
    """

    def __init__(self):
        tipo_unidad = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB', es_principal=False, es_subunidad=False)
        unidad = UnidadOrganizativa.objects.create(
            descripcion='UEB Central', tipo=tipo_unidad, grupo_nomina=1,
            orden_informe=1)
        departamento = Departamento.objects.create(
            descripcion='Contabilidad', unidad_organizativa=unidad, orden_informe=1)
        grupo = NGrupoEscala.objects.create(nivel='IV')
        ncargo = NCargo.objects.create(
            descripcion='Especialista B', cat_ocupacional='TEC',
            grupo_escala=grupo, salario_basico=4000)

        self.unidad = unidad
        self.cargo = CargoPlantilla.objects.create(
            ncargo=ncargo, departamento=departamento, cant_aprobada=50,
            orden_informe=1)
        self.provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        self.municipio = NMunicipio.objects.create(
            nombre='Playa', provincia=self.provincia, siglas='PLA')
        self.tipo_contrato = NTipoContrato.objects.create(
            descripcion='Contrato Determinado', ocupa_plaza=False,
            requiere_motivo=False)

    def aspirante(self, doc, estado='ACTIVO', grado_cientifico=None):
        return Aspirante.objects.create(
            nivel_educ='SA', nombre='Trab', papellido='Prueba', sapellido='Test',
            doc_identidad=doc, estado=estado, sexo='F', raza='BL',
            grado_cientifico=grado_cientifico,
            provincia=self.provincia, municipio=self.municipio)


class ContratoDeterminadoVencidoTests(TestCase):
    """CTR-018: el contrato expiró y el trabajador sigue cobrando.

    La duración se guarda en MESES, así que el vencimiento se calcula con
    aritmética de meses y no sumando días: 6 meses no son 180 días fijos.
    """

    @classmethod
    def setUpTestData(cls):
        cls.base = _EscenarioContratos()

    def _contrato(self, doc, fecha_alta, duracion, estado='ACTIVO', expediente='0001'):
        return CAlta.objects.create(
            aspirante=self.base.aspirante(doc, estado=estado),
            no_expediente=expediente, tipo=self.base.tipo_contrato,
            cargo=self.base.cargo, fecha_alta=fecha_alta, duracion=duracion)

    def hallazgos(self):
        from .reglas.contratos import ContratoDeterminadoVencido
        return {h.object_id for h in ContratoDeterminadoVencido().ejecutar(None)}

    def test_detecta_el_contrato_ya_vencido(self):
        contrato = self._contrato('90010100001', date.today() - timedelta(days=400), 6)
        self.assertIn(str(contrato.pk), self.hallazgos())

    def test_detecta_el_contrato_que_vence_hoy(self):
        """Crítica desde el mismo día del vencimiento (antes avisa el Recordatorio)."""
        contrato = self._contrato('90010100005', date.today() - timedelta(days=90), 90)
        self.assertIn(str(contrato.pk), self.hallazgos())

    def test_no_reclama_un_contrato_todavia_vigente(self):
        contrato = self._contrato('90010100002', date.today() - timedelta(days=10), 12)
        self.assertNotIn(str(contrato.pk), self.hallazgos())

    def test_no_reclama_a_quien_ya_esta_de_baja(self):
        """Un trabajador de baja no cobra: reclamar su contrato sería ruido.

        La baja se pone DESPUÉS de crear el contrato, y no en el propio alta,
        porque `CAlta.save()` pone al trabajador en ACTIVO — crear un contrato es
        precisamente lo que le da el alta. Ponerlo antes no serviría de nada.
        """
        contrato = self._contrato('90010100003', date.today() - timedelta(days=400), 6)
        Aspirante.objects.filter(pk=contrato.aspirante_id).update(estado='BAJA')

        self.assertNotIn(str(contrato.pk), self.hallazgos())

    def test_ignora_los_contratos_sin_duracion(self):
        """Sin duración el contrato es indeterminado: no vence."""
        contrato = self._contrato('90010100004', date.today() - timedelta(days=400), None)
        self.assertNotIn(str(contrato.pk), self.hallazgos())

    def test_el_vencimiento_se_calcula_en_dias(self):
        """La duración es siempre en días (RRHH, 23-10-2026), igual que el Word y el
        Recordatorio de vencimiento."""
        from .reglas.contratos import _vencimiento_de
        self.assertEqual(_vencimiento_de(date(2026, 1, 15), 90), date(2026, 4, 15))
        self.assertEqual(_vencimiento_de(date(2026, 8, 10), 365), date(2027, 8, 10))
        self.assertIsNone(_vencimiento_de(None, 6))
        self.assertIsNone(_vencimiento_de(date(2026, 1, 1), None))


class ImporteAntiguoSinNomencladorTests(TestCase):
    """CTR-023: los importes tecleados a mano que no encajaban con el nomenclador
    cuando el contrato dejó de guardarlos (23-10-2026)."""

    @classmethod
    def setUpTestData(cls):
        cls.base = _EscenarioContratos()
        cls.cnci = NPagoAdicional.objects.create(
            tipo=NPagoAdicional.CNCI, descripcion='Etapa I', importe=Decimal('329.00'))

    def setUp(self):
        from contratos.models import ImporteSinNomenclador
        self.contrato = CAlta.objects.create(
            aspirante=self.base.aspirante('90010200001'), no_expediente='0201',
            tipo=self.base.tipo_contrato, cargo=self.base.cargo, fecha_alta=date.today())
        ImporteSinNomenclador.objects.create(
            contrato=self.contrato, concepto='cnci', importe_antiguo=Decimal('800.00'))

    def hallazgos(self):
        from .reglas.contratos import ImporteAntiguoSinNomenclador
        return list(ImporteAntiguoSinNomenclador().ejecutar(None))

    def test_muestra_el_importe_antiguo_hasta_que_se_elige_la_entrada(self):
        hallazgos = self.hallazgos()
        self.assertEqual([(h.object_id, h.clave_extra) for h in hallazgos],
                         [(str(self.contrato.pk), 'cnci')])
        self.assertIn('800.00', hallazgos[0].detalle)

        self.contrato.cnci_nomenclador = self.cnci
        self.contrato.save()
        self.assertEqual(self.hallazgos(), [])

    def test_dar_por_revisado_lo_borra(self):
        from types import SimpleNamespace
        from .reglas.contratos import ImporteAntiguoSinNomenclador
        texto = ImporteAntiguoSinNomenclador().corregir(
            SimpleNamespace(object_id=str(self.contrato.pk), clave_extra='cnci'))
        self.assertIn('dado por revisado', texto)
        self.assertEqual(self.hallazgos(), [])
        with self.assertRaises(ValueError):
            ImporteAntiguoSinNomenclador().corregir(
                SimpleNamespace(object_id=str(self.contrato.pk), clave_extra='cnci'))


class NomencladorDeGradoCientificoVacioTests(TestCase):
    """CFG-003: apunta a quien puede arreglarlo, el Administrador."""

    @classmethod
    def setUpTestData(cls):
        cls.base = _EscenarioContratos()

    def hallazgos(self):
        from .reglas.configuracion import NomencladorDeGradoCientificoVacio
        return {h.clave_extra
                for h in NomencladorDeGradoCientificoVacio().ejecutar(None)}

    def test_reclama_el_grado_que_tiene_trabajadores_y_no_tiene_importe(self):
        self.base.aspirante('90010300001', grado_cientifico='MC')
        self.assertIn('MC', self.hallazgos())

    def test_no_reclama_si_el_importe_ya_esta_definido(self):
        self.base.aspirante('90010300002', grado_cientifico='MC')
        NImporteGradoCientifico.objects.create(grado='MC', importe=Decimal('500.00'))

        self.assertNotIn('MC', self.hallazgos())

    def test_no_reclama_un_grado_que_no_tiene_a_nadie(self):
        """Un nomenclador vacío sin ningún doctor en la empresa no es un problema."""
        self.base.aspirante('90010300003', grado_cientifico='MC')
        self.assertNotIn('DC', self.hallazgos())

    def test_no_cuenta_a_los_trabajadores_de_baja(self):
        self.base.aspirante('90010300004', grado_cientifico='DC', estado='BAJA')
        self.assertNotIn('DC', self.hallazgos())

    def test_es_un_hallazgo_global_sin_fila_a_la_que_apuntar(self):
        """El problema es la AUSENCIA del registro, igual que en CFG-001."""
        from .reglas.configuracion import NomencladorDeGradoCientificoVacio
        self.base.aspirante('90010300005', grado_cientifico='MC')

        hallazgo = next(iter(NomencladorDeGradoCientificoVacio().ejecutar(None)))
        self.assertEqual(hallazgo.object_id, '')


class FormulaDePagoQueYaNoValidaTests(TestCase):
    """PNM-002: una fórmula rota se registra como CERO en silencio."""

    def hallazgos(self):
        from .reglas.prenomina import FormulaDePagoQueYaNoValida
        return {h.object_id for h in FormulaDePagoQueYaNoValida().ejecutar(None)}

    def test_detecta_una_formula_invalida_guardada_a_la_fuerza(self):
        """Se salta `clean()` con `update()` a propósito: así es como llegan las
        fórmulas rotas, guardadas cuando eran válidas y desfasadas después."""
        pago = NPagoImporte.objects.create(
            codigo=901, descripcion='Prueba', tipo_valor=TipoValorImporte.FORMULA,
            formula='{{horas}} * 2')
        NPagoImporte.objects.filter(pk=pago.pk).update(
            formula='{{variable_que_no_existe}} * 2')

        self.assertIn(str(pago.pk), self.hallazgos())

    def test_no_reclama_una_formula_correcta(self):
        pago = NPagoImporte.objects.create(
            codigo=902, descripcion='Correcta', tipo_valor=TipoValorImporte.FORMULA,
            formula='{{horas}} * {{tarifa_horaria}}')

        self.assertNotIn(str(pago.pk), self.hallazgos())

    def test_ignora_los_conceptos_que_no_usan_formula(self):
        pago = NPagoImporte.objects.create(
            codigo=903, descripcion='Importe fijo',
            tipo_valor=TipoValorImporte.IMPORTE, importe_fijo=Decimal('100.00'))

        self.assertNotIn(str(pago.pk), self.hallazgos())


class UnidadSinDeclararElCierreTests(TestCase):
    """CIE-001: sin cierre, la unidad queda fuera de los informes de ese mes."""

    def _unidad(self, descripcion, es_principal=False, orden=1):
        tipo = NTipoUnidadOrganizativa.objects.create(
            descripcion='Tipo ' + descripcion, es_principal=es_principal,
            es_subunidad=False)
        return UnidadOrganizativa.objects.create(
            descripcion=descripcion, tipo=tipo, grupo_nomina=1, orden_informe=orden)

    def _desactualizar(self, unidad, con_primer_cierre=True):
        primero = None
        if con_primer_cierre:
            primero = CierreUnidad.objects.create(
                unidad=unidad, anno=2026, mes=6, periodo_clave='2026-06',
                fecha_declaracion=timezone.now(),
                unidad_descripcion=unidad.descripcion)
        return EstadoCierreUnidad.objects.create(
            unidad=unidad, estado=EstadoUnidad.DESACTUALIZADA,
            primer_cierre=primero, periodo_pendiente_anno=2026,
            periodo_pendiente_mes=7, meses_pendientes=2)

    def hallazgos(self):
        from .reglas.cierres import UnidadSinDeclararElCierre
        return {h.object_id for h in UnidadSinDeclararElCierre().ejecutar(None)}

    def test_detecta_la_unidad_desactualizada(self):
        unidad = self._unidad('UEB Norte')
        self._desactualizar(unidad)

        self.assertIn(str(unidad.pk), self.hallazgos())

    def test_no_reclama_a_una_direccion_principal(self):
        """Su estado se deriva de sus hijas: no puede declarar por sí misma."""
        unidad = self._unidad('Direccion Tecnica', es_principal=True, orden=2)
        self._desactualizar(unidad)

        self.assertNotIn(str(unidad.pk), self.hallazgos())

    def test_no_reclama_a_una_unidad_que_nunca_declaro(self):
        """Sin primera declaración no hay obligación todavía."""
        unidad = self._unidad('UEB Nueva', orden=3)
        self._desactualizar(unidad, con_primer_cierre=False)

        self.assertNotIn(str(unidad.pk), self.hallazgos())

    def test_no_reclama_a_una_unidad_al_dia(self):
        unidad = self._unidad('UEB Sur', orden=4)
        EstadoCierreUnidad.objects.create(
            unidad=unidad, estado=EstadoUnidad.ACTUALIZADA)

        self.assertNotIn(str(unidad.pk), self.hallazgos())


class RepartoDeUnidadesTests(TestCase):
    """VIS-008 y VIS-009: el reparto de unidades entre moderadores.

    El fallo que vigilan es SILENCIOSO y su síntoma no apunta a la causa: un
    moderador al que le falta una subunidad simplemente «no ve a su gente» en
    media aplicación, y tampoco puede declarar su cierre. Nadie relaciona eso con
    un reparto incompleto, y por eso hace falta que alguien lo reclame.
    """

    @classmethod
    def setUpTestData(cls):
        tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Dirección', es_principal=True)
        tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True)
        tipo_ueb = NTipoUnidadOrganizativa.objects.create(descripcion='UEB')

        cls.principal = UnidadOrganizativa.objects.create(
            descripcion='Dirección Técnica', tipo=tipo_principal, grupo_nomina=1,
            orden_informe=1)
        cls.taller = UnidadOrganizativa.objects.create(
            descripcion='Taller', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=2)
        cls.almacen = UnidadOrganizativa.objects.create(
            descripcion='Almacén', tipo=tipo_sub, padre=cls.principal,
            grupo_nomina=1, orden_informe=3)
        cls.suelta = UnidadOrganizativa.objects.create(
            descripcion='UEB Norte', tipo=tipo_ueb, grupo_nomina=2, orden_informe=4)

    def moderador(self, username, *unidades):
        """Se asigna con `set()`, saltándose el formulario: es la vía por la que
        estos datos incoherentes aparecen en la realidad."""
        usuario = CustomUser.objects.create_user(
            username=username, password='Orbith.Segura.2026', es_moderador=True)
        usuario.unidades.set(unidades)
        return usuario

    def faltan_subunidades(self):
        from .reglas.alcance import ModeradorSinLasSubunidadesDeSuPrincipal
        return {h.object_id
                for h in ModeradorSinLasSubunidadesDeSuPrincipal().ejecutar(None)}

    def sueltas(self):
        from .reglas.alcance import ModeradorConSubunidadSuelta
        return {h.object_id for h in ModeradorConSubunidadSuelta().ejecutar(None)}

    # ---- VIS-008: lleva el padre y le faltan hijas ----

    def test_detecta_al_moderador_al_que_le_faltan_subunidades(self):
        usuario = self.moderador('mod_incompleto', self.principal, self.taller)
        self.assertIn(str(usuario.pk), self.faltan_subunidades())

    def test_no_reclama_a_quien_las_tiene_todas(self):
        usuario = self.moderador(
            'mod_completo', self.principal, self.taller, self.almacen)
        self.assertNotIn(str(usuario.pk), self.faltan_subunidades())

    def test_no_reclama_a_quien_solo_lleva_una_unidad_sin_hijas(self):
        usuario = self.moderador('mod_suelto', self.suelta)
        self.assertNotIn(str(usuario.pk), self.faltan_subunidades())

    def test_el_hallazgo_nombra_las_subunidades_que_faltan(self):
        """Sin decir cuáles, el Administrador tendría que compararlas a mano."""
        from .reglas.alcance import ModeradorSinLasSubunidadesDeSuPrincipal

        self.moderador('mod_incompleto2', self.principal, self.taller)

        hallazgo = next(iter(
            ModeradorSinLasSubunidadesDeSuPrincipal().ejecutar(None)))
        self.assertIn('Almacén', hallazgo.datos['subunidades_sin_asignar'])

    # ---- VIS-009: lleva una hija sin el padre ----

    def test_detecta_la_subunidad_suelta(self):
        usuario = self.moderador('mod_huerfano', self.taller)
        self.assertIn(str(usuario.pk), self.sueltas())

    def test_no_reclama_si_tambien_lleva_al_padre(self):
        usuario = self.moderador(
            'mod_con_padre', self.principal, self.taller, self.almacen)
        self.assertNotIn(str(usuario.pk), self.sueltas())

    def test_una_unidad_independiente_no_es_una_subunidad_suelta(self):
        usuario = self.moderador('mod_independiente', self.suelta)
        self.assertNotIn(str(usuario.pk), self.sueltas())

    # ---- Las dos reglas se complementan, no se solapan ----

    def test_las_dos_reglas_miran_problemas_distintos(self):
        """Un mismo reparto no debe salir en las dos: son fallos opuestos."""
        incompleto = self.moderador('mod_a', self.principal, self.taller)
        huerfano = self.moderador('mod_b', self.almacen)

        self.assertEqual(self.faltan_subunidades(), {str(incompleto.pk)})
        self.assertEqual(self.sueltas(), {str(huerfano.pk)})

    def test_el_comando_deja_a_VIS_008_sin_nada_que_reclamar(self):
        """La regla detecta y el comando repara: tienen que estar de acuerdo."""
        from io import StringIO

        from django.core.management import call_command

        usuario = self.moderador('mod_a_reparar', self.principal)
        self.assertIn(str(usuario.pk), self.faltan_subunidades())

        call_command('sincronizar_unidades', stdout=StringIO())

        self.assertEqual(self.faltan_subunidades(), set())


class MisionSinDiasOImporteTests(TestCase):
    """CTR-021: el 0 se reclama igual que el vacío."""

    def _evaluar(self, **campos):
        from types import SimpleNamespace

        from .reglas.contratos import MisionSinDiasOImporte

        datos = {'pk': 1, 'mision': True, 'mision_dias': 30,
                 'mision_importe': Decimal('100.00')}
        datos.update(campos)
        return MisionSinDiasOImporte().evaluar_instancia(SimpleNamespace(**datos))

    def test_completa_no_genera_hallazgo(self):
        self.assertIsNone(self._evaluar())

    def test_sin_mision_no_genera_hallazgo(self):
        self.assertIsNone(self._evaluar(mision=False, mision_dias=None, mision_importe=None))

    def test_faltan_los_dias(self):
        for valor in (None, 0):
            hallazgo, = self._evaluar(mision_dias=valor)
            self.assertEqual(hallazgo.datos['faltantes'], ['mision_dias'])
            self.assertEqual(hallazgo.campo_formulario, 'mision_dias')
            self.assertIn('días', hallazgo.detalle)

    def test_falta_el_importe(self):
        for valor in (None, Decimal('0.00')):
            hallazgo, = self._evaluar(mision_importe=valor)
            self.assertEqual(hallazgo.datos['faltantes'], ['mision_importe'])

    def test_faltan_los_dos_en_un_solo_hallazgo(self):
        hallazgo, = self._evaluar(mision_dias=0, mision_importe=None)
        self.assertEqual(hallazgo.datos['faltantes'], ['mision_dias', 'mision_importe'])
        self.assertEqual(hallazgo.titulo, 'Misión sin días ni importe')

    def test_el_barrido_encuentra_vacios_y_ceros(self):
        from bolsa.models import Aspirante
        from contratos.models import CAlta
        from nomencladores.models import NMunicipio, NProvincia

        from .reglas.contratos import MisionSinDiasOImporte

        provincia = NProvincia.objects.create(nombre='La Habana', siglas='LHA')
        municipio = NMunicipio.objects.create(nombre='Playa', provincia=provincia, siglas='PLA')

        def contrato(expediente, **campos):
            aspirante = Aspirante.objects.create(
                nivel_educ='SA', nombre='Trab', papellido='Mision', sapellido=expediente,
                doc_identidad='900101' + expediente, estado='ACTIVO', sexo='M', raza='BL',
                provincia=provincia, municipio=municipio)
            return CAlta.objects.create(aspirante=aspirante, no_expediente=expediente, **campos)

        completo = contrato('00001', mision=True, mision_dias=10, mision_importe=Decimal('5'))
        vacio = contrato('00002', mision=True)
        con_cero = contrato('00003', mision=True, mision_dias=0, mision_importe=Decimal('5'))
        sin_mision = contrato('00004', mision=False)

        encontrados = {h.object_id for h in MisionSinDiasOImporte().ejecutar(None)}

        self.assertEqual(encontrados, {str(vacio.pk), str(con_cero.pk)})
        self.assertNotIn(str(completo.pk), encontrados)
        self.assertNotIn(str(sin_mision.pk), encontrados)


class CorreccionDeMovimientosTests(TestCase):
    """MOV-002 y MOV-008 con botón «Corregir» (decisión de RRHH, 12-10-2026): solo
    un Administrador lo ve y lo usa; la corrección queda en Auditoría y el hallazgo
    pasa a Corregido. Y al cambiar el expediente de un contrato, sus movimientos
    toman el número nuevo, para que el caso MOV-008 no vuelva a producirse."""

    @classmethod
    def setUpTestData(cls):
        cls.esc = _EscenarioContratos()
        cls.admin = CustomUser.objects.create_user(
            username='admin_correccion', password='x', es_admin=True)
        cls.moderador = CustomUser.objects.create_user(
            username='moderador_correccion', password='x', es_moderador=True)
        cls.moderador.unidades.set([cls.esc.unidad])

    def setUp(self):
        self.contrato = CAlta.objects.create(
            aspirante=self.esc.aspirante('90010112401'), no_expediente='12131',
            tipo=self.esc.tipo_contrato, cargo=self.esc.cargo, fecha_alta=date(2026, 8, 20))

    def _movimiento(self, expediente, contrato='propio'):
        from contratos.models import TMovimiento
        return TMovimiento.objects.create(
            aspirante=self.contrato.aspirante, no_expediente=expediente,
            contrato=self.contrato if contrato == 'propio' else None,
            fecha_efectiva=date(2026, 9, 20), cargo_anterior='Especialista B',
            cargo_nuevo='Especialista B', salario_anterior=4000, salario_nuevo=4500,
            tipo_movimiento='Movimiento de Nómina', unidad_nueva_fk=self.esc.unidad)

    def _hallazgo(self, codigo, movimiento):
        from contratos.models import TMovimiento
        return Hallazgo.objects.create(
            codigo_regla=codigo, object_id=str(movimiento.pk),
            content_type=ContentType.objects.get_for_model(TMovimiento),
            modulo='nomina', criticidad=CRITICIDAD_ALTA, titulo='Prueba',
            ultima_deteccion=timezone.now(), unidad_organizativa=self.esc.unidad)

    # --- MOV-008: detección ------------------------------------------------

    def test_mov008_detecta_el_expediente_distinto(self):
        from .reglas.nomina import MovimientoConOtroExpediente
        distinto = self._movimiento('1213')
        self._movimiento('12131')  # coincide: no se reporta
        hallazgos = list(MovimientoConOtroExpediente().ejecutar(None))
        self.assertEqual([h.object_id for h in hallazgos], [str(distinto.pk)])
        self.assertEqual(hallazgos[0].datos['expediente_del_contrato'], '12131')

    def test_cambiar_el_expediente_del_contrato_lo_lleva_a_sus_movimientos(self):
        movimiento = self._movimiento('12131')
        self.contrato.no_expediente = '12132'
        self.contrato.save()
        movimiento.refresh_from_db()
        self.assertEqual(movimiento.no_expediente, '12132')

    # --- El botón «Corregir» -----------------------------------------------

    def test_el_administrador_corrige_el_expediente(self):
        from auditoria.models import EventoAuditoria
        movimiento = self._movimiento('1213')
        hallazgo = self._hallazgo('MOV-008', movimiento)
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            reverse('subsanacion:corregir_hallazgo', args=[hallazgo.pk]))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, '1213 → 12131')
        movimiento.refresh_from_db()
        self.assertEqual(movimiento.no_expediente, '12131')
        hallazgo.refresh_from_db()
        self.assertEqual(hallazgo.estado, Hallazgo.CORREGIDO)
        self.assertEqual(hallazgo.revisado_por, self.admin)
        self.assertTrue(EventoAuditoria.objects.filter(
            object_id=str(movimiento.pk), usuario=self.admin).exists())

    def test_el_administrador_reengancha_el_movimiento(self):
        movimiento = self._movimiento('12131', contrato=None)
        hallazgo = self._hallazgo('MOV-002', movimiento)
        self.client.force_login(self.admin)

        self.client.post(reverse('subsanacion:corregir_hallazgo', args=[hallazgo.pk]))

        movimiento.refresh_from_db()
        self.assertEqual(movimiento.contrato_id, self.contrato.pk)
        hallazgo.refresh_from_db()
        self.assertEqual(hallazgo.estado, Hallazgo.CORREGIDO)

    def test_el_moderador_no_puede_corregir(self):
        movimiento = self._movimiento('1213')
        hallazgo = self._hallazgo('MOV-008', movimiento)
        self.client.force_login(self.moderador)

        self.client.post(reverse('subsanacion:corregir_hallazgo', args=[hallazgo.pk]))

        movimiento.refresh_from_db()
        self.assertEqual(movimiento.no_expediente, '1213')
        hallazgo.refresh_from_db()
        self.assertEqual(hallazgo.estado, Hallazgo.PENDIENTE)

    def test_el_boton_solo_lo_ve_el_administrador(self):
        hallazgo = self._hallazgo('MOV-008', self._movimiento('1213'))
        url = reverse('subsanacion:detalle_hallazgo', args=[hallazgo.pk])

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), 'Corregir expediente')
        self.client.force_login(self.moderador)
        self.assertNotContains(self.client.get(url), 'subsanacion/hallazgo/%d/corregir' % hallazgo.pk)

    def test_si_ya_no_aplica_no_toca_nada(self):
        movimiento = self._movimiento('1213')
        hallazgo = self._hallazgo('MOV-008', movimiento)
        type(movimiento).objects.filter(pk=movimiento.pk).update(no_expediente='12131')
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            reverse('subsanacion:corregir_hallazgo', args=[hallazgo.pk]))

        self.assertContains(respuesta, 'ya tiene el expediente de su contrato', status_code=400)
        hallazgo.refresh_from_db()
        self.assertEqual(hallazgo.estado, Hallazgo.PENDIENTE)


class ReglasDeFechasImposiblesTests(TestCase):
    """MOV-009 (baja posterior al contrato vigente), MOV-010 (baja futura), MOV-011 y
    CTR-022 (años anteriores a 1900). Reglas añadidas el 13-10-2026."""

    @classmethod
    def setUpTestData(cls):
        from contratos.models import CBaja, TMovimiento
        esc = _EscenarioContratos()
        cls.activo = esc.aspirante('80010113001')
        cls.contrato = CAlta.objects.create(aspirante=cls.activo, no_expediente='01001',
                                            tipo=esc.tipo_contrato, cargo=esc.cargo,
                                            fecha_alta=date(2026, 4, 30))
        # Baja posterior al contrato vigente (imposible) y otra legítima del mismo día.
        cls.imposible = CBaja.objects.create(
            aspirante=cls.activo, no_expediente='01001', tipo=esc.tipo_contrato, cargo=esc.cargo,
            fecha_alta=date(2026, 1, 1), fecha_baja=date(2026, 8, 20))
        cls.mismo_dia = CBaja.objects.create(
            aspirante=cls.activo, no_expediente='01001', tipo=esc.tipo_contrato, cargo=esc.cargo,
            fecha_alta=date(2026, 1, 1), fecha_baja=date(2026, 4, 30))
        de_baja = esc.aspirante('80010113002', estado='BAJA')
        cls.futura = CBaja.objects.create(
            aspirante=de_baja, no_expediente='01002', tipo=esc.tipo_contrato, cargo=esc.cargo,
            fecha_alta=date(2026, 1, 1), fecha_baja=date.today() + timedelta(days=30))
        cls.contrato_0026 = CAlta.objects.create(
            aspirante=esc.aspirante('80010113003'), no_expediente='01003',
            tipo=esc.tipo_contrato, cargo=esc.cargo, fecha_alta=date(26, 10, 13))
        cls.mov_0026 = TMovimiento.objects.create(
            aspirante=cls.contrato_0026.aspirante, contrato=cls.contrato_0026, no_expediente='01003',
            fecha_efectiva=date(26, 10, 13), cargo_anterior='---', cargo_nuevo='Especialista B',
            salario_anterior=0, salario_nuevo=4000, tipo_movimiento='Alta Inicial')

    def ids(self, codigo):
        from .reglas import obtener_regla
        return {h.object_id for h in obtener_regla(codigo).ejecutar(None)}

    def test_baja_posterior_al_contrato_vigente(self):
        self.assertEqual(self.ids('MOV-009'), {str(self.imposible.pk)})

    def test_baja_futura(self):
        self.assertEqual(self.ids('MOV-010'), {str(self.futura.pk)})

    def test_anos_imposibles(self):
        self.assertEqual(self.ids('CTR-022'), {str(self.contrato_0026.pk)})
        self.assertEqual(self.ids('MOV-011'), {str(self.mov_0026.pk)})
