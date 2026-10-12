from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from . import servicios
from .middleware import RankingMiddleware
from .models import Actividad, ActividadXP, GanadorMes, MesCerrado, Rol
from .puntos import nivel_de
from .servicios import (cerrar_mes, cerrar_mes_si_toca, clasificacion, limpiar_meses_antiguos,
                        mes_anterior, registrar_actividad)

CustomUser = get_user_model()


def crear_usuario(username, **roles):
    datos = {'password': 'ClaveSegura123'}
    datos.update(roles or {'es_moderador': True})
    return CustomUser.objects.create_user(username=username, **datos)


def anotar(usuario, actividad, xp, dia, rol=Rol.MODERADOR):
    """Fila directa, para preparar meses pasados sin pasar por los topes."""
    fecha = timezone.make_aware(datetime(dia.year, dia.month, dia.day, 10))
    return ActividadXP.objects.create(usuario=usuario, rol=rol, actividad=actividad,
                                      fecha=fecha, dia=dia, xp=xp)


class RegistrarActividadTests(TestCase):
    def setUp(self):
        self.moderador = crear_usuario('mod')
        self.admin = crear_usuario('adm', es_admin=True)
        self.observador = crear_usuario('obs', es_observador=True)

    def test_da_los_puntos_de_su_rol_y_el_dia_activo(self):
        fila = registrar_actividad(self.moderador, Actividad.ALTA, detalle='Contrato 1')
        self.assertEqual(fila.xp, 10)
        self.assertEqual(fila.rol, Rol.MODERADOR)
        self.assertEqual(fila.detalle, 'Contrato 1')
        dia = ActividadXP.objects.get(usuario=self.moderador, actividad=Actividad.DIA_ACTIVO)
        self.assertEqual(dia.xp, 2)

    def test_dia_activo_una_sola_vez_al_dia(self):
        registrar_actividad(self.moderador, Actividad.ASPIRANTE)
        registrar_actividad(self.moderador, Actividad.BAJA)
        self.assertEqual(ActividadXP.objects.filter(actividad=Actividad.DIA_ACTIVO).count(), 1)

    def test_pasado_el_tope_cuenta_en_el_uso_pero_sin_xp(self):
        for _ in range(12):
            registrar_actividad(self.observador, Actividad.DESCARGA, formato='pdf')
        descargas = ActividadXP.objects.filter(usuario=self.observador, actividad=Actividad.DESCARGA)
        self.assertEqual(descargas.count(), 12)
        self.assertEqual(sum(d.xp for d in descargas), 10)

    def test_tope_de_una_por_dia(self):
        registrar_actividad(self.admin, Actividad.ANALISIS_SUBSANACION)
        segunda = registrar_actividad(self.admin, Actividad.ANALISIS_SUBSANACION)
        self.assertEqual(segunda.xp, 0)

    def test_cierre_en_plazo_sin_tope(self):
        for _ in range(20):
            fila = registrar_actividad(self.moderador, Actividad.CIERRE_EN_PLAZO)
        self.assertEqual(fila.xp, 20)

    def test_actividad_de_otro_rol_no_se_registra(self):
        self.assertIsNone(registrar_actividad(self.observador, Actividad.ALTA))
        self.assertIsNone(registrar_actividad(self.admin, Actividad.ASPIRANTE))
        self.assertIsNone(registrar_actividad(self.moderador, Actividad.SOLICITUD_DECIDIDA))
        self.assertFalse(ActividadXP.objects.exists())

    def test_anonimo_desactivado_o_nulo_no_registran(self):
        self.moderador.is_active = False
        self.moderador.save()
        self.assertIsNone(registrar_actividad(self.moderador, Actividad.ALTA))
        self.assertIsNone(registrar_actividad(AnonymousUser(), Actividad.ALTA))
        self.assertIsNone(registrar_actividad(None, Actividad.ALTA))

    def test_nunca_rompe_al_llamador(self):
        with patch.object(ActividadXP.objects, 'create', side_effect=RuntimeError('fallo')):
            self.assertIsNone(registrar_actividad(self.moderador, Actividad.ALTA))

    def test_detalle_que_falla_al_convertirse_no_rompe(self):
        class Raro:
            def __str__(self):
                raise ValueError('sin texto')
        self.assertIsNone(registrar_actividad(self.moderador, Actividad.ALTA, detalle=Raro()))


class ClasificacionTests(TestCase):
    def setUp(self):
        self.a = crear_usuario('ana')
        self.b = crear_usuario('beto')
        self.c = crear_usuario('carla')
        self.d = crear_usuario('dani')
        self.obs = crear_usuario('olga', es_observador=True)
        dia = date(2026, 9, 10)
        anotar(self.a, Actividad.ALTA, 50, dia)
        anotar(self.b, Actividad.ALTA, 50, dia)
        anotar(self.c, Actividad.ALTA, 30, dia)
        anotar(self.obs, Actividad.INFORME, 5, dia, rol=Rol.OBSERVADOR)
        # Otro mes: no cuenta.
        anotar(self.d, Actividad.ALTA, 99, date(2026, 8, 31))

    def test_empates_comparten_puesto(self):
        filas = clasificacion(2026, 9, Rol.MODERADOR)
        self.assertEqual([(f['usuario'].username, f['xp'], f['puesto']) for f in filas],
                         [('ana', 50, 1), ('beto', 50, 1), ('carla', 30, 3)])

    def test_agrupa_por_rol_actual(self):
        self.obs.es_observador = False
        self.obs.es_moderador = True
        self.obs.save()
        nombres = [f['usuario'].username for f in clasificacion(2026, 9, Rol.MODERADOR)]
        self.assertIn('olga', nombres)
        self.assertEqual(clasificacion(2026, 9, Rol.OBSERVADOR), [])

    def test_excluye_desactivados(self):
        self.a.is_active = False
        self.a.save()
        nombres = [f['usuario'].username for f in clasificacion(2026, 9, Rol.MODERADOR)]
        self.assertNotIn('ana', nombres)

    def test_incluir_sin_xp(self):
        filas = clasificacion(2026, 9, Rol.MODERADOR, incluir_sin_xp=True)
        self.assertEqual(filas[-1]['usuario'].username, 'dani')
        self.assertEqual(filas[-1]['xp'], 0)

    def test_niveles_por_rol(self):
        self.assertEqual(nivel_de(Rol.MODERADOR, 49), 'Inicial')
        self.assertEqual(nivel_de(Rol.MODERADOR, 50), 'Activo')
        self.assertEqual(nivel_de(Rol.ADMINISTRADOR, 250), 'Experto')
        self.assertEqual(nivel_de(Rol.OBSERVADOR, 40), 'Destacado')


class CierreMesTests(TestCase):
    def setUp(self):
        servicios._mes_revisado = None
        self.usuarios = [crear_usuario(f'm{i}') for i in range(5)]
        for i, (usuario, xp) in enumerate(zip(self.usuarios, (90, 80, 80, 70, 0))):
            anotar(usuario, Actividad.ALTA, xp, date(2026, 9, 5 + i))

    def tearDown(self):
        servicios._mes_revisado = None

    def test_mes_anterior(self):
        self.assertEqual(mes_anterior(2026, 1), (2025, 12))
        self.assertEqual(mes_anterior(2026, 10, 2), (2026, 8))
        self.assertEqual(mes_anterior(2026, 12, -1), (2027, 1))

    def test_reparte_los_tres_primeros_puestos_con_empates(self):
        self.assertTrue(cerrar_mes(2026, 9))
        ganadores = GanadorMes.objects.filter(anno=2026, mes=9).order_by('puesto', 'usuario__username')
        self.assertEqual([(g.usuario.username, g.puesto) for g in ganadores],
                         [('m0', 1), ('m1', 2), ('m2', 2)])

    def test_no_cierra_dos_veces(self):
        self.assertTrue(cerrar_mes(2026, 9))
        self.assertFalse(cerrar_mes(2026, 9))
        self.assertEqual(GanadorMes.objects.count(), 3)

    def test_cierre_automatico_el_primer_dia_del_mes(self):
        self.assertTrue(cerrar_mes_si_toca(date(2026, 10, 1)))
        self.assertTrue(MesCerrado.objects.filter(anno=2026, mes=9).exists())
        # El resto del mes ya no consulta nada.
        with self.assertNumQueries(0):
            self.assertFalse(cerrar_mes_si_toca(date(2026, 10, 20)))

    def test_si_nadie_entra_el_dia_1_cierra_el_dia_que_entre(self):
        self.assertTrue(cerrar_mes_si_toca(date(2026, 10, 4)))
        self.assertTrue(MesCerrado.objects.filter(anno=2026, mes=9).exists())

    def test_cierre_sin_actividad_no_premia_a_nadie(self):
        self.assertTrue(cerrar_mes(2026, 3))
        self.assertFalse(GanadorMes.objects.filter(anno=2026, mes=3).exists())

    def test_limpia_lo_anterior_a_tres_meses(self):
        viejo = anotar(self.usuarios[0], Actividad.ALTA, 5, date(2026, 7, 31))
        GanadorMes.objects.create(anno=2026, mes=7, rol=Rol.MODERADOR, usuario=self.usuarios[0],
                                  puesto=1, xp=5)
        limpiar_meses_antiguos(2026, 10)  # se conservan agosto, septiembre y octubre
        self.assertFalse(ActividadXP.objects.filter(pk=viejo.pk).exists())
        self.assertFalse(GanadorMes.objects.filter(mes=7).exists())
        self.assertEqual(ActividadXP.objects.filter(dia__month=9).count(), 5)

    def test_un_error_no_rompe_la_peticion(self):
        with patch.object(servicios, 'cerrar_mes', side_effect=RuntimeError('fallo')):
            self.assertFalse(cerrar_mes_si_toca(date(2026, 10, 1)))
        # Sigue pendiente: lo intentará en la siguiente petición.
        self.assertIsNone(servicios._mes_revisado)


class DescargasMiddlewareTests(TestCase):
    def setUp(self):
        servicios._mes_revisado = (timezone.localdate().year, timezone.localdate().month)
        self.usuario = crear_usuario('obs', es_observador=True)
        self.factory = RequestFactory()

    def tearDown(self):
        servicios._mes_revisado = None

    def _pasar(self, content_type, status=200, usuario=None):
        respuesta = HttpResponse(b'x', content_type=content_type, status=status)
        respuesta['Content-Disposition'] = 'attachment; filename="plantilla.xlsx"'
        request = self.factory.get('/exportar/')
        request.user = usuario or self.usuario
        return RankingMiddleware(lambda r: respuesta)(request)

    def test_cuenta_la_descarga_con_su_formato(self):
        self._pasar('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        fila = ActividadXP.objects.get(actividad=Actividad.DESCARGA)
        self.assertEqual((fila.formato, fila.detalle, fila.xp), ('excel', 'plantilla.xlsx', 1))

    def test_no_cuenta_html_ni_errores_ni_anonimos(self):
        self._pasar('text/html')
        self._pasar('application/pdf', status=404)
        self._pasar('application/pdf', usuario=AnonymousUser())
        self.assertFalse(ActividadXP.objects.exists())


class VentanaUsuarioTests(TestCase):
    HOY = date(2026, 10, 15)

    def setUp(self):
        self.yo = crear_usuario('yo_login_secreto')
        self.otros = [crear_usuario(f'otro{i}') for i in range(11)]
        for i, usuario in enumerate(self.otros):
            anotar(usuario, Actividad.ALTA, 100 - i, date(2026, 10, 3))
        anotar(self.yo, Actividad.ALTA, 40, date(2026, 10, 4))
        anotar(self.yo, Actividad.DIA_ACTIVO, 2, date(2026, 10, 4))
        anotar(self.yo, Actividad.ALTA, 30, date(2026, 9, 4))

    def test_fuera_del_top_ve_su_fila_y_lo_que_le_falta(self):
        datos = servicios.datos_ventana(self.yo, hoy=self.HOY)
        self.assertEqual(len(datos['top']), 10)
        self.assertEqual(datos['puesto'], 12)
        self.assertEqual(datos['fuera_del_top']['xp'], 42)
        # El 10º tiene 91 XP: le faltan 49 para igualarlo.
        self.assertEqual(datos['fuera_del_top']['faltan_top'], 49)

    def test_barra_de_nivel(self):
        progreso = servicios.progreso_nivel(Rol.MODERADOR, 42)
        self.assertEqual((progreso['nivel'], progreso['siguiente'], progreso['faltan'], progreso['porcentaje']),
                         ('Inicial', 'Activo', 8, 84))
        self.assertIsNone(servicios.progreso_nivel(Rol.MODERADOR, 300)['siguiente'])

    def test_detalle_y_tres_meses(self):
        datos = servicios.datos_ventana(self.yo, hoy=self.HOY)
        self.assertEqual([(d['actividad'], d['xp']) for d in datos['detalle']],
                         [(Actividad.ALTA, 40), (Actividad.DIA_ACTIVO, 2)])
        self.assertEqual([(m['etiqueta'], m['xp']) for m in datos['meses']],
                         [('Agosto', 0), ('Septiembre', 30), ('Octubre', 42)])

    def test_nunca_muestra_el_nombre_de_usuario(self):
        datos = servicios.datos_ventana(self.yo, hoy=self.HOY)
        self.assertEqual(datos['fuera_del_top']['nombre'], servicios.SIN_NOMBRE)
        self.yo.first_name, self.yo.last_name = 'Ana', 'Pérez'
        self.yo.save()
        datos = servicios.datos_ventana(self.yo, hoy=self.HOY)
        self.assertEqual(datos['fuera_del_top']['nombre'], 'Ana Pérez')
        self.assertEqual(datos['fuera_del_top']['iniciales'], 'AP')

    def test_ganadores_solo_de_su_rol(self):
        obs = crear_usuario('obs', es_observador=True)
        GanadorMes.objects.create(anno=2026, mes=9, rol=Rol.MODERADOR, usuario=self.otros[0], puesto=1, xp=90)
        GanadorMes.objects.create(anno=2026, mes=9, rol=Rol.OBSERVADOR, usuario=obs, puesto=1, xp=20)
        datos = servicios.datos_ventana(self.yo, hoy=self.HOY)
        self.assertEqual(len(datos['ganadores']), 1)
        self.assertEqual(datos['ganadores'][0]['etiqueta'], 'Septiembre 2026')
        self.assertEqual(len(datos['ganadores'][0]['personas']), 1)

    def test_la_vista_no_filtra_nombres_de_usuario(self):
        servicios._mes_revisado = (timezone.localdate().year, timezone.localdate().month)
        try:
            anotar(self.yo, Actividad.ALTA, 5, timezone.localdate())
            self.client.force_login(self.yo)
            respuesta = self.client.get('/ranking/panel/')
        finally:
            servicios._mes_revisado = None
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ranking de Moderadores')
        self.assertNotContains(respuesta, 'yo_login_secreto')
        self.assertNotContains(respuesta, 'otro1')


class AvisosCierreTests(TestCase):
    def setUp(self):
        from notificaciones.models import Notificacion
        self.Notificacion = Notificacion
        self.oro = crear_usuario('oro')
        self.quinto = [crear_usuario(f'mod{i}') for i in range(4)]
        self.cero = crear_usuario('sin_xp')
        self.admin = crear_usuario('jefa', es_admin=True)
        self.admin2 = crear_usuario('jefe', es_admin=True)
        anotar(self.oro, Actividad.ALTA, 300, date(2026, 9, 3))
        for i, usuario in enumerate(self.quinto):
            anotar(usuario, Actividad.ALTA, 100 - i, date(2026, 9, 3))
        anotar(self.admin, Actividad.SOLICITUD_DECIDIDA, 40, date(2026, 9, 3), rol=Rol.ADMINISTRADOR)

    def avisos_de(self, usuario, **filtros):
        return self.Notificacion.objects.filter(destinatario=usuario, codigo_regla='RANKING', **filtros)

    def test_avisa_a_todos_con_su_resultado(self):
        cerrar_mes(2026, 9)
        oro = self.avisos_de(self.oro).get()
        self.assertEqual(oro.titulo, '🥇 ¡Medalla de oro en Septiembre!')
        self.assertIn('1º de los Moderadores con 300 XP (nivel Experto)', oro.mensaje)
        quinto = self.avisos_de(self.quinto[3]).get()
        self.assertEqual(quinto.titulo, 'Ranking de Septiembre cerrado')
        self.assertIn('Terminaste 5º de 5 Moderadores con 97 XP', quinto.mensaje)
        self.assertIn('no sumaste XP', self.avisos_de(self.cero).get().mensaje)
        self.assertEqual(self.avisos_de(self.oro).get().tipo, self.Notificacion.Tipo.EVENTO)

    def test_resumen_para_cada_administrador(self):
        cerrar_mes(2026, 9)
        for admin in (self.admin, self.admin2):
            resumen = self.avisos_de(admin, clave_extra='RESUMEN').get()
            self.assertEqual(resumen.titulo, 'Ranking de Septiembre 2026: ganadores')
            self.assertIn('Moderadores: 🥇 Usuario sin nombre (300 XP)', resumen.mensaje)
            self.assertIn('Observadores: nadie sumó XP.', resumen.mensaje)
        # Su aviso personal, aparte del resumen.
        self.assertEqual(self.avisos_de(self.admin2).count(), 2)

    def test_mes_sin_actividad_no_avisa(self):
        cerrar_mes(2026, 3)
        self.assertFalse(self.Notificacion.objects.filter(codigo_regla='RANKING').exists())

    def test_el_admin_solo_ve_sus_avisos_del_ranking(self):
        from notificaciones.views import _notificaciones_visibles
        cerrar_mes(2026, 9)
        visibles = _notificaciones_visibles(self.admin).filter(codigo_regla='RANKING')
        self.assertEqual(set(visibles.values_list('destinatario', flat=True)), {self.admin.pk})
        # Las demás notificaciones las sigue viendo todas.
        from django.contrib.contenttypes.models import ContentType
        otra = self.Notificacion.objects.create(
            titulo='Alta', mensaje='x', destinatario=self.oro,
            content_type=ContentType.objects.get_for_model(MesCerrado), object_id='1')
        self.assertTrue(_notificaciones_visibles(self.admin).filter(pk=otra.pk).exists())

    def test_si_fallan_los_avisos_el_mes_no_se_cierra(self):
        with patch('ranking.avisos.avisar_cierre', side_effect=RuntimeError('fallo')):
            with self.assertRaises(RuntimeError):
                cerrar_mes(2026, 9)
        self.assertFalse(MesCerrado.objects.filter(anno=2026, mes=9).exists())
        self.assertFalse(GanadorMes.objects.exists())


class CampanaTests(TestCase):
    def test_los_avisos_del_ranking_salen_primero(self):
        from django.contrib.contenttypes.models import ContentType
        from notificaciones.models import Notificacion
        usuario = crear_usuario('mod')
        ct = ContentType.objects.get_for_model(MesCerrado)
        for i in range(6):
            Notificacion.objects.create(titulo=f'Alerta {i}', mensaje='x', destinatario=usuario, severidad=1,
                                        tipo=Notificacion.Tipo.ALERTA, content_type=ct, object_id=str(i))
        Notificacion.objects.create(titulo='Ranking', mensaje='x', destinatario=usuario, codigo_regla='RANKING',
                                    content_type=ct, object_id='99')
        self.client.force_login(usuario)
        datos = self.client.get(reverse('ultimas_notificaciones')).json()['notificaciones']
        self.assertEqual(datos[0]['titulo'], 'Ranking')
        self.assertEqual(datos[0]['codigo_regla'], 'RANKING')
        self.assertEqual(len(datos), 5)


class EstadisticasUsoTests(TestCase):
    """Página "Estadísticas de uso": XP y uso separados, reglas de Auditoría."""
    MES = (2026, 9)

    def setUp(self):
        from auditoria.models import EventoAuditoria
        self.Evento = EventoAuditoria
        self.admin = crear_usuario('jefa_login', es_admin=True)
        self.mod = crear_usuario('mod_login')
        self.obs = crear_usuario('obs_login', es_observador=True)
        self.inactivo = crear_usuario('nadie_login')
        dia = date(2026, 9, 10)
        # 12 descargas: el uso cuenta 12, el XP solo 10.
        for i in range(12):
            ActividadXP.objects.create(usuario=self.mod, rol='M', actividad=Actividad.DESCARGA, formato='pdf',
                                       dia=dia, fecha=timezone.make_aware(datetime(2026, 9, 10, 9, i)),
                                       xp=1 if i < 10 else 0)
        anotar(self.mod, Actividad.DIA_ACTIVO, 2, dia)
        self.evento(self.mod, 'UPD', 'contratos', 'Contrato 0001')
        self.evento(self.mod, 'MOV', 'contratos', 'Contrato 0001')  # tiene su columna: no es edición
        self.evento(self.mod, 'BAJ', 'contratos', 'Contrato 0002')  # tiene su columna: no es eliminación
        self.evento(self.mod, 'ALT', 'contratos', 'Contrato 0003')  # tiene su columna
        self.evento(self.mod, 'DEL', 'aspirantes', 'Aspirante Ana')
        self.evento(self.mod, 'ADD', 'solicitudes', 'Cargo Técnico')  # cuenta como plantilla
        self.evento(self.mod, 'UPD', 'prenomina', 'Pre-Nómina')  # no cuenta todavía
        self.evento(self.mod, 'ACC', 'usuarios', 'Inicio de sesión')
        self.evento(self.mod, 'ACC', 'usuarios', 'Inicio de sesión')
        self.evento(self.obs, 'ACC', 'usuarios', 'Inicio de sesión')
        self.evento(self.admin, 'UPD', 'estructura', 'Cargo Jefe')

    def evento(self, usuario, accion, modulo, descriptor):
        e = self.Evento.objects.create(usuario=usuario, accion=accion, modulo=modulo, descriptor=descriptor)
        self.Evento.objects.filter(pk=e.pk).update(fecha=timezone.make_aware(datetime(2026, 9, 10, 11)))

    def seccion(self, datos, rol):
        return next(s for s in datos['secciones'] if s['rol'] == rol)

    def fila_uso(self, datos, rol, usuario):
        return next(f for f in self.seccion(datos, rol)['uso'] if f['pk'] == usuario.pk)

    def valores(self, datos, rol, usuario):
        return dict(zip(self.seccion(datos, rol)['columnas'], self.fila_uso(datos, rol, usuario)['trabajo']))

    def test_uso_sin_topes_y_sin_duplicados(self):
        from . import estadisticas
        datos = estadisticas.datos_pagina(*self.MES, hoy=date(2026, 10, 7))
        valores = self.valores(datos, Rol.MODERADOR, self.mod)
        self.assertEqual(valores['Descargas'], 12)
        self.assertEqual(valores['Ediciones'], 2)       # contrato + solicitud enviada
        self.assertEqual(valores['Eliminaciones'], 1)   # el aspirante; la baja no
        self.assertEqual(valores['Días activos'], 1)
        fila = self.fila_uso(datos, Rol.MODERADOR, self.mod)
        self.assertEqual((fila['sesiones'], fila['dias_sesion']), (2, 1))
        ranking = {f['pk']: f['xp'] for f in self.seccion(datos, Rol.MODERADOR)['ranking']}
        self.assertEqual(ranking[self.mod.pk], 12)  # 10 de descargas + 2 del día

    def test_columnas_por_rol(self):
        from . import estadisticas
        datos = estadisticas.datos_pagina(*self.MES, hoy=date(2026, 10, 7))
        self.assertEqual(self.seccion(datos, Rol.OBSERVADOR)['columnas'], ['Informes', 'Descargas', 'Días activos'])
        self.assertEqual(self.valores(datos, Rol.ADMINISTRADOR, self.admin)['Ediciones'], 1)  # la plantilla

    def test_sin_actividad_distingue_quien_entro(self):
        from . import estadisticas
        datos = estadisticas.datos_pagina(*self.MES, hoy=date(2026, 10, 7))
        por_pk = {p['pk']: p for p in datos['sin_actividad']}
        self.assertNotIn(self.mod.pk, por_pk)
        self.assertTrue(por_pk[self.obs.pk]['entro'])
        self.assertFalse(por_pk[self.inactivo.pk]['entro'])

    def test_detalle_del_usuario(self):
        from . import estadisticas
        d = estadisticas.detalle_usuario(self.mod, *self.MES)
        descarga = next(a for a in d['desglose_xp'] if a['etiqueta'] == 'Archivo descargado')
        self.assertEqual((descarga['veces'], descarga['xp'], descarga['tope']), (12, 10, True))
        self.assertEqual({e['etiqueta']: e['veces'] for e in d['ediciones']}, {'Contratos': 1, 'Plantilla': 1})
        self.assertEqual({e['etiqueta']: e['veces'] for e in d['eliminaciones']}, {'Datos personales': 1})
        self.assertEqual(d['descargas'][0], {'etiqueta': 'PDF', 'veces': 12})
        dia_10 = next(c for c in d['calendario'] if c['dia'] == 10)
        self.assertEqual(dia_10['clase'], 'trabajo')
        self.assertEqual(len(d['ultimas']), 10)
        self.assertEqual(d['calendario'][0], {'dia': None})  # el 1-9-2026 es martes

    def test_solo_para_administradores(self):
        servicios._mes_revisado = (timezone.localdate().year, timezone.localdate().month)
        try:
            self.client.force_login(self.mod)
            self.assertEqual(self.client.get(reverse('ranking_estadisticas')).status_code, 403)
            self.assertEqual(self.client.get(reverse('ranking_detalle_usuario', args=[self.mod.pk])).status_code, 403)
            self.client.force_login(self.admin)
            respuesta = self.client.get(reverse('ranking_estadisticas'))
            detalle = self.client.get(reverse('ranking_detalle_usuario', args=[self.mod.pk]))
        finally:
            servicios._mes_revisado = None
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(detalle.status_code, 200)
        # Esta página es solo del Administrador: quien no tiene trabajador vinculado
        # ni nombre en su ficha sale con su nombre de usuario (decisión de RRHH). En
        # la ventana del Ranking, que ven todos, no (ver VentanaUsuarioTests).
        for login in ('mod_login', 'obs_login', 'nadie_login'):
            self.assertContains(respuesta, login)
        self.assertContains(detalle, 'mod_login')
        self.assertNotContains(respuesta, 'Usuario sin nombre')
        # Con nombre en la ficha, se usa el nombre, no el usuario.
        self.mod.first_name, self.mod.last_name = 'Marta', 'Gil'
        self.mod.save()
        self.assertEqual(estadisticas_nombre(self.mod), 'Marta Gil')


class UnidadesSinCierreTests(TestCase):
    def setUp(self):
        from cierres.models import CierreUnidad
        from nomencladores.models import NTipoUnidadOrganizativa
        from strorganizativa.models import UnidadOrganizativa
        tipo = NTipoUnidadOrganizativa.objects.create(descripcion='UEB', es_principal=False, es_subunidad=False)
        self.al_dia = UnidadOrganizativa.objects.create(descripcion='UEB Al día', tipo=tipo, grupo_nomina=1)
        self.tarde = UnidadOrganizativa.objects.create(descripcion='UEB Tarde', tipo=tipo, grupo_nomina=2)
        self.sin = UnidadOrganizativa.objects.create(descripcion='UEB Sin declarar', tipo=tipo, grupo_nomina=3)
        self.nueva = UnidadOrganizativa.objects.create(descripcion='UEB Nueva', tipo=tipo, grupo_nomina=4)

        def cierre(unidad, anno, mes, en_plazo):
            CierreUnidad.objects.create(unidad=unidad, anno=anno, mes=mes, en_plazo=en_plazo,
                                        fecha_declaracion=timezone.now(), unidad_descripcion=unidad.descripcion)
        hoy = timezone.localdate()
        self.anterior = mes_anterior(hoy.year, hoy.month, 1)
        dos_antes = mes_anterior(hoy.year, hoy.month, 2)
        for unidad in (self.al_dia, self.tarde, self.sin):
            cierre(unidad, *dos_antes, True)
        cierre(self.al_dia, *self.anterior, True)
        cierre(self.tarde, *self.anterior, False)
        cierre(self.nueva, hoy.year, hoy.month, True)  # su obligación empieza este mes

    def test_sin_cierre_o_fuera_de_plazo(self):
        from .estadisticas import unidades_sin_cierre_en_plazo
        resultado = {u['unidad'].descripcion: u for u in unidades_sin_cierre_en_plazo(*self.anterior)}
        self.assertEqual(set(resultado), {'UEB Tarde', 'UEB Sin declarar'})
        self.assertTrue(resultado['UEB Sin declarar']['puede_recordar'])
        self.assertFalse(resultado['UEB Tarde']['puede_recordar'])

    def test_mes_en_curso_solo_tras_el_plazo(self):
        from .estadisticas import unidades_sin_cierre_en_plazo
        anno, mes = self.anterior
        self.assertEqual(unidades_sin_cierre_en_plazo(anno, mes, hoy=date(anno, mes, 25)), [])
        self.assertTrue(unidades_sin_cierre_en_plazo(anno, mes, hoy=date(anno, mes, 26)))

    def test_enviar_recordatorio(self):
        from notificaciones.models import Notificacion
        servicios._mes_revisado = (timezone.localdate().year, timezone.localdate().month)
        admin = crear_usuario('jefa', es_admin=True)
        clave = '%d-%02d' % self.anterior
        try:
            self.client.force_login(admin)
            url = reverse('ranking_recordar_cierre', args=[self.sin.pk])
            self.client.post(url, {'mes': clave})
            Notificacion.objects.filter(destinatario=admin).update(leido=True)
            self.client.post(url, {'mes': clave})  # reenviar: vuelve a no leído, sin duplicar
            # Una unidad que ya declaró no recibe recordatorio.
            self.client.post(reverse('ranking_recordar_cierre', args=[self.al_dia.pk]), {'mes': clave})
        finally:
            servicios._mes_revisado = None
        avisos = Notificacion.objects.filter(destinatario=admin, object_id=str(self.sin.pk))
        self.assertEqual(avisos.count(), 1)
        self.assertFalse(avisos.get().leido)
        self.assertFalse(Notificacion.objects.filter(object_id=str(self.al_dia.pk)).exists())


class DistincionTests(TestCase):
    """La medalla del mes anterior: oro, plata o bronce, solo para el ganador."""

    def setUp(self):
        servicios._mes_revisado = (timezone.localdate().year, timezone.localdate().month)
        self.ganador = crear_usuario('ganador')
        self.otro = crear_usuario('otro')
        hoy = timezone.localdate()
        anno, mes = mes_anterior(hoy.year, hoy.month)
        GanadorMes.objects.create(anno=anno, mes=mes, rol=Rol.MODERADOR, usuario=self.ganador, puesto=2, xp=80)
        # Una medalla de hace dos meses ya no se luce.
        anno2, mes2 = mes_anterior(hoy.year, hoy.month, 2)
        GanadorMes.objects.create(anno=anno2, mes=mes2, rol=Rol.MODERADOR, usuario=self.otro, puesto=1, xp=90)

    def tearDown(self):
        servicios._mes_revisado = None

    def test_distincion_del_mes_anterior(self):
        self.assertEqual(servicios.distincion_de(self.ganador), {'metal': 'plata', 'puesto': 2})
        self.assertIsNone(servicios.distincion_de(self.otro))

    def test_se_pinta_y_se_puede_apagar(self):
        self.client.force_login(self.ganador)
        pagina = self.client.get(reverse('dashboard'))
        self.assertContains(pagina, 'distincion-plata')
        self.assertContains(pagina, 'distincion-medalla')
        self.client.post(reverse('guardar_preferencias'), {'mostrar_distincion': 'false'})
        from usuarios.models import PreferenciasUsuario
        self.assertFalse(PreferenciasUsuario.objects.get(usuario=self.ganador).mostrar_distincion)
        pagina = self.client.get(reverse('dashboard'))
        self.assertNotContains(pagina, 'class="light-style layout-menu-fixed distincion-plata"')
        # El interruptor sigue disponible para volver a encenderla.
        self.assertContains(pagina, 'data-metal="plata"')

    def test_sin_distincion_el_interruptor_sale_desactivado(self):
        self.client.force_login(self.otro)
        pagina = self.client.get(reverse('dashboard'))
        self.assertNotContains(pagina, 'distincion-medalla')
        self.assertContains(pagina, 'Este mes no tienes distinción.')


def estadisticas_nombre(usuario):
    from .estadisticas import nombre_para_admin
    return nombre_para_admin(usuario)
