"""Pruebas del rediseño de avisos del 18-11-2026: campana que solo cuenta lo que hay
que hacer, limpieza diaria, autor de los eventos y avisos de chófer unidos.

    python manage.py test notificaciones.tests_agrupadas
"""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from nomencladores.models import NProvincia
from subsanacion.constantes import CRITICIDAD_ALTA, CRITICIDAD_INFORMATIVA, CRITICIDAD_MEDIA

from .models import Notificacion


class _ConAvisos(TestCase):

    def setUp(self):
        from usuarios.models import CustomUser

        self.admin = CustomUser.objects.create_user(username='admin_campana', password='x', es_admin=True)
        self.otro_admin = CustomUser.objects.create_user(username='admin_campana_2', password='x', es_admin=True)
        self.provincia = NProvincia.objects.create(nombre='Provincia campana')
        self.tipo_ct = ContentType.objects.get_for_model(self.provincia)
        self.contador = 0
        # Sin el aviso de mitad de mes del Ranking, que el middleware lanzaría al
        # pedir una página (son pruebas que cuentan avisos).
        from ranking import servicios
        hoy = timezone.localdate()
        servicios._rezagados_avisados = (hoy.year, hoy.month)

    def _aviso(self, **campos):
        self.contador += 1
        datos = dict(titulo='Aviso', mensaje='...', content_type=self.tipo_ct,
                     object_id=str(self.provincia.pk), destinatario=self.admin,
                     codigo_regla=f'X-{self.contador}', clave_extra=f'k{self.contador}')
        datos.update(campos)
        return Notificacion.objects.create(**datos)


class CampanaAccionableTests(_ConAvisos):

    def test_solo_cuenta_lo_que_hay_que_hacer(self):
        hoy = timezone.localdate()
        ale, rec, eve = Notificacion.Tipo.ALERTA, Notificacion.Tipo.RECORDATORIO, Notificacion.Tipo.EVENTO
        cuentan = [
            self._aviso(tipo=ale, severidad=CRITICIDAD_ALTA),
            self._aviso(tipo=ale, severidad=None, codigo_regla='ALE-CRITICAS'),
            self._aviso(tipo=rec, fecha_objetivo=hoy + timedelta(days=5)),
            self._aviso(tipo=rec, fecha_objetivo=hoy - timedelta(days=3)),
            self._aviso(tipo=rec, fecha_objetivo=hoy + timedelta(days=40), codigo_regla='CIE-VENTANA'),
            self._aviso(tipo=eve, codigo_regla='SOL-NUEVA'),
        ]
        # No cuentan: Media, recordatorio lejano, actividad, leído, resuelto, de otro.
        self._aviso(tipo=ale, severidad=CRITICIDAD_MEDIA)
        self._aviso(tipo=rec, fecha_objetivo=hoy + timedelta(days=30))
        self._aviso(tipo=eve, codigo_regla='EVT-ALTA')
        self._aviso(tipo=ale, severidad=CRITICIDAD_ALTA, leido=True)
        self._aviso(tipo=ale, severidad=CRITICIDAD_ALTA, estado=Notificacion.Estado.RESUELTA)
        self._aviso(tipo=ale, severidad=CRITICIDAD_ALTA, destinatario=self.otro_admin)

        cliente = Client()
        cliente.force_login(self.admin)
        respuesta = cliente.get(reverse('notificaciones_json'))
        self.assertEqual(respuesta.json(), {'total': len(cuentan)})


class LimpiezaDiariaTests(_ConAvisos):

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_borra_informativas_y_lo_viejo_pero_no_solicitudes_pendientes(self):
        from .limpieza import limpieza_diaria

        informativa = self._aviso(tipo=Notificacion.Tipo.ALERTA, severidad=CRITICIDAD_INFORMATIVA,
                                  codigo_regla='EXT-001')
        media = self._aviso(tipo=Notificacion.Tipo.ALERTA, severidad=CRITICIDAD_MEDIA, codigo_regla='MOV-016')
        viejo = self._aviso(tipo=Notificacion.Tipo.EVENTO, codigo_regla='EVT-ALTA')
        pendiente = self._aviso(tipo=Notificacion.Tipo.EVENTO, codigo_regla='SOL-NUEVA')
        hace_tiempo = timezone.now() - timedelta(days=61)
        Notificacion.objects.filter(pk__in=[viejo.pk, pendiente.pk]).update(fecha_creado=hace_tiempo)

        limpieza_diaria()

        quedan = set(Notificacion.objects.values_list('pk', flat=True))
        self.assertNotIn(informativa.pk, quedan)
        self.assertNotIn(viejo.pk, quedan)
        self.assertIn(media.pk, quedan)
        self.assertIn(pendiente.pk, quedan)

    def test_solo_una_vez_al_dia(self):
        from . import limpieza

        with patch.object(limpieza, 'limpieza_diaria', return_value={}) as limpiar:
            limpieza.limpiar_si_toca()
            limpieza.limpiar_si_toca()
        self.assertEqual(limpiar.call_count, 1)

    def test_un_fallo_no_rompe_la_campana(self):
        from . import limpieza

        cliente = Client()
        cliente.force_login(self.admin)
        with patch.object(limpieza, 'limpieza_diaria', side_effect=RuntimeError('fallo')):
            respuesta = cliente.get(reverse('notificaciones_json'))
        self.assertEqual(respuesta.status_code, 200)


class AutorDeEventoTests(_ConAvisos):

    def test_quien_hace_el_cambio_no_recibe_aviso_pero_queda_como_autor(self):
        from . import avisos

        with patch.object(avisos, 'get_current_user', return_value=self.admin):
            avisos.avisar_cambio_salarial(self.provincia, codigo='EVT-ROL', titulo='Rol', mensaje='...')

        propia = Notificacion.objects.get(destinatario=self.admin)
        ajena = Notificacion.objects.get(destinatario=self.otro_admin)
        self.assertEqual((propia.autor, propia.leido), (self.admin, True))
        self.assertEqual((ajena.autor, ajena.leido), (self.admin, False))


class AvisoDeChoferTests(TestCase):

    def test_documentos_del_mismo_dia_van_en_un_aviso(self):
        from types import SimpleNamespace

        from . import recordatorios

        dia = date.today() + timedelta(days=10)
        contrato = SimpleNamespace(pk=7, aspirante='Pedro Pérez', fecha_vence_lic=dia + timedelta(days=5),
                                   fecha_vence_recal=dia, fecha_vence_seg=dia)
        consulta = SimpleNamespace(select_related=lambda *a: [contrato])
        with patch.object(recordatorios.CAlta.objects, 'filter', return_value=consulta), \
                patch.object(recordatorios, '_unidad_del_contrato', return_value=None):
            avisos = list(recordatorios.detectar_documentos_chofer())

        self.assertEqual(len(avisos), 2)
        unido = next(a for a in avisos if a.fecha_objetivo == dia)
        self.assertEqual(unido.clave_extra, 'fecha_vence_recal+fecha_vence_seg')
        self.assertEqual(unido.titulo, 'Vence recalificación y seguro de chófer: Pedro Pérez')
        self.assertIn('La recalificación y el seguro de Pedro Pérez vencen el', unido.mensaje)


class BandejaAgrupadaTests(_ConAvisos):
    """Advertencias por regla, Recordatorios por tipo, Actividad por día y la
    campana agrupada (Fase B del 18-11-2026)."""

    def setUp(self):
        super().setUp()
        self.cliente = Client()
        self.cliente.force_login(self.admin)
        self.lista = reverse('lista_notificaciones')

    def _copias(self, **campos):
        """El mismo aviso para los dos administradores."""
        campos.setdefault('clave_extra', f'copia{self.contador}')
        for destinatario in (self.admin, self.otro_admin):
            self._aviso(destinatario=destinatario, **campos)

    def test_advertencias_una_linea_por_regla(self):
        ale = Notificacion.Tipo.ALERTA
        self._copias(tipo=ale, severidad=CRITICIDAD_MEDIA, codigo_regla='MOV-016', object_id='1')
        self._copias(tipo=ale, severidad=CRITICIDAD_MEDIA, codigo_regla='MOV-016', object_id='2')
        self._copias(tipo=ale, severidad=CRITICIDAD_ALTA, codigo_regla='MOV-014', object_id='3')
        Notificacion.objects.filter(destinatario=self.admin, object_id='1').update(leido=True)

        respuesta = self.cliente.get(self.lista + '?tab=advertencias')
        self.assertTrue(respuesta.context['vista_grupos'])
        grupos = [(g['codigo_regla'], g['registros'], g['nuevos']) for g in respuesta.context['grupos']]
        self.assertEqual(grupos, [('MOV-014', 1, 1), ('MOV-016', 2, 1)])

        # Al elegir la regla («Ver todos»), la tabla de siempre.
        respuesta = self.cliente.get(self.lista + '?tab=advertencias&regla=MOV-016')
        self.assertFalse(respuesta.context['vista_grupos'])
        self.assertEqual(len(respuesta.context['notificaciones']), 2)

        respuesta = self.cliente.get(reverse('grupo_advertencias') + '?regla=MOV-016')
        self.assertEqual(respuesta.context['total'], 2)
        self.assertIn('regla=MOV-016', respuesta.context['ver_todos'])

    def test_marcar_un_grupo_solo_toca_mis_copias_de_ese_grupo(self):
        ale = Notificacion.Tipo.ALERTA
        self._copias(tipo=ale, severidad=CRITICIDAD_ALTA, codigo_regla='CTR-018')
        otra = self._aviso(tipo=ale, severidad=CRITICIDAD_ALTA, codigo_regla='CTR-004')

        self.cliente.post(reverse('notificaciones_marcar_grupo_leido'), {'grupo': 'ALE:CTR-018'})

        self.assertTrue(Notificacion.objects.get(destinatario=self.admin, codigo_regla='CTR-018').leido)
        self.assertFalse(Notificacion.objects.get(destinatario=self.otro_admin, codigo_regla='CTR-018').leido)
        otra.refresh_from_db()
        self.assertFalse(otra.leido)
        self.assertEqual(self.cliente.post(reverse('notificaciones_marcar_grupo_leido'),
                                           {'grupo': 'XXX:CTR-018'}).status_code, 400)

    def test_recordatorios_por_tipo_con_los_urgentes_primero(self):
        rec, hoy = Notificacion.Tipo.RECORDATORIO, timezone.localdate()
        sistema = Notificacion.Origen.SISTEMA
        self._aviso(tipo=rec, origen=sistema, codigo_regla='REC-CHOFER', fecha_objetivo=hoy + timedelta(days=40))
        self._aviso(tipo=rec, origen=sistema, codigo_regla='REC-CONTRATO', fecha_objetivo=hoy - timedelta(days=1))
        self._aviso(tipo=rec, origen=sistema, codigo_regla='REC-CONTRATO', fecha_objetivo=hoy + timedelta(days=5))

        respuesta = self.cliente.get(self.lista + '?tab=recordatorios')
        grupos = respuesta.context['grupos']
        self.assertEqual([(g['codigo_regla'], g['rojo'], g['amarillo'], g['naranja']) for g in grupos],
                         [('REC-CONTRATO', 1, 1, 0), ('REC-CHOFER', 0, 0, 1)])
        self.assertEqual(len(grupos[0]['filas']), 2)
        respuesta = self.cliente.get(self.lista + '?tab=recordatorios&codigo=REC-CHOFER')
        self.assertFalse(respuesta.context['vista_grupos'])

    def test_actividad_por_dia_con_autor_y_repetidos_juntos(self):
        eve = Notificacion.Tipo.EVENTO
        for _ in range(3):
            self._aviso(tipo=eve, codigo_regla='EVT-CARGO', mensaje='Nuevo cargo: Director en Dirección.',
                        autor=self.otro_admin, leido=True)
        self._aviso(tipo=eve, codigo_regla='EVT-ALTA', mensaje='Alta de Ana.', autor=self.admin, leido=True)
        self._aviso(tipo=eve, codigo_regla='SOL-NUEVA', mensaje='Solicitud.')

        respuesta = self.cliente.get(self.lista + '?tab=notificaciones')
        dias = list(respuesta.context['dias'])
        self.assertEqual(len(dias), 1)
        self.assertEqual([(t['codigo_regla'], t['total']) for t in dias[0]['tipos']],
                         [('EVT-ALTA', 1), ('EVT-CARGO', 3)])
        # La solicitud no es actividad: va en Avisos.
        self.assertEqual([n.codigo_regla for n in respuesta.context['notificaciones']], ['SOL-NUEVA'])

        respuesta = self.cliente.get(reverse('actividad_dia') + f'?dia={timezone.localdate().isoformat()}')
        lineas = {t['codigo_regla']: t['lineas'] for t in respuesta.context['tipos']}
        self.assertEqual(lineas['EVT-CARGO'][0]['veces'], 3)
        self.assertTrue(lineas['EVT-ALTA'][0]['es_mio'])
        self.assertContains(respuesta, 'por ti')
        self.assertContains(respuesta, 'por admin_campana_2')

    def test_campana_agrupada_con_ranking_primero_y_actividad_aparte(self):
        ale = Notificacion.Tipo.ALERTA
        for _ in range(3):
            self._aviso(tipo=ale, severidad=CRITICIDAD_ALTA, codigo_regla='MOV-014')
        self._aviso(tipo=Notificacion.Tipo.EVENTO, codigo_regla='RANKING', titulo='Ranking de octubre')
        self._aviso(tipo=Notificacion.Tipo.EVENTO, codigo_regla='EVT-ALTA', leido=True)

        datos = self.cliente.get(reverse('ultimas_notificaciones')).json()
        self.assertEqual([(l['codigo_regla'], l['total']) for l in datos['lineas']],
                         [('RANKING', 1), ('MOV-014', 3)])
        self.assertIsNone(datos['lineas'][0]['href'])
        self.assertIn('abrir=MOV-014', datos['lineas'][1]['href'])
        self.assertEqual(datos['actividad'], [{'nombre': 'altas', 'total': 1}])
