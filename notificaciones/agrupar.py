"""Avisos agrupados (decisiones de RRHH del 18-11-2026).

Por dentro se sigue guardando un aviso por registro y por destinatario (así siguen
funcionando Descartar, Corregir, el panel de cada registro y Supervisión); lo que
cambia es cómo se enseñan: una línea por regla en Advertencias, por tipo en
Recordatorios, por día y tipo en «Actividad» y por moderador y regla en Supervisión.
Las cuentas se hacen en la base de datos (un GROUP BY), no trayendo miles de filas.
"""

from django.db.models import CharField, Count, Max, Min, Q, Value
from django.db.models.functions import Cast, Concat

from subsanacion.constantes import CRITICIDAD_CRITICA

from .campana import PREFIJO_ACTIVIDAD, q_accionable
from .models import Notificacion

#: Nombre para lo que no es una regla de Subsanación (las reglas usan su nombre).
NOMBRES = {
    'ALE-CRITICAS': 'Hallazgos críticos nuevos en Subsanación',
    'CIE-VENTANA': 'Cierre: declarar la plantilla',
    'CIE-ULTIMO-DIA': 'Cierre: último día para declarar',
    'CIE-DESACTUALIZADA': 'Unidad desactualizada en el cierre',
    'CIE-CORREGIDO': 'Cierre corregido',
    'REC-CONTRATO': 'Contratos por vencer',
    'REC-CHOFER': 'Documentos de chófer por vencer',
    'REC-ANTIGUEDAD': 'Cambios de años de servicio',
    'REC-CUMPLE': 'Cumpleaños',
    'REC-JUBILACION': 'Jubilación próxima',
    'EVT-ALTA': 'Altas',
    'EVT-BAJA': 'Bajas',
    'EVT-CARGO': 'Cargos nuevos',
    'EVT-ROL': 'Cambios en nomencladores de cargo',
    'EVT-ESCALA': 'Cambios en la escala salarial',
    'EVT-IMPORTE': 'Cambios en importes',
    'EVT-ESTRUC': 'Cambios en la estructura',
    'SOL-NUEVA': 'Solicitudes nuevas',
    'SOL-DECISION': 'Solicitudes decididas',
    'SOL-REABIERTA': 'Solicitudes reabiertas',
    'SOL-PERS-NUEVA': 'Solicitudes personalizadas nuevas',
    'SOL-PERS-RESPUESTA': 'Respuestas a solicitudes personalizadas',
    'RANKING': 'Ranking mensual',
}

#: Cuántos registros se enseñan al abrir un grupo; el resto, con «Ver todos».
FILAS_AL_ABRIR = 10

DIAS_SEMANA = ('Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo')


def nombre_de_codigo(codigo):
    if codigo in NOMBRES:
        return NOMBRES[codigo]
    from subsanacion.reglas import obtener_regla
    regla = obtener_regla(codigo) if codigo else None
    return regla.nombre if regla else (codigo or 'Otros avisos')


def _clave_de_registro():
    """El mismo problema en el mismo registro, sea cual sea el destinatario."""
    return Concat(Cast('content_type_id', CharField()), Value(':'), 'object_id',
                  Value(':'), 'clave_extra', output_field=CharField())


def grupos_de_advertencias(consulta, usuario):
    """Una línea por regla: gravedad, registros afectados y cuántos son nuevos (sin
    leer) para `usuario`. Orden: gravedad y, dentro de cada una, primero las que
    tienen nuevos."""
    filas = (consulta.order_by().values('codigo_regla')
             .annotate(gravedad=Min('severidad'),
                       registros=Count(_clave_de_registro(), distinct=True),
                       nuevos=Count('pk', filter=Q(destinatario=usuario, leido=False)),
                       ultima=Max('fecha_creado')))
    grupos = [dict(fila, nombre=nombre_de_codigo(fila['codigo_regla'])) for fila in filas]
    # Sin gravedad = «hallazgos críticos nuevos»: arriba del todo.
    grupos.sort(key=lambda g: (g['gravedad'] or 0, g['nuevos'] == 0, -g['registros']))
    return grupos


def grupos_de_recordatorios(recordatorios):
    """Una línea por tipo, con cuántos hay de cada color. `recordatorios` ya viene
    sin copias repetidas y con `.prioridad` (son decenas, no miles). Orden: los que
    tienen algo en rojo primero, luego amarillo…"""
    grupos = {}
    for recordatorio in recordatorios:
        grupo = grupos.setdefault(recordatorio.codigo_regla, {
            'codigo_regla': recordatorio.codigo_regla,
            'nombre': nombre_de_codigo(recordatorio.codigo_regla),
            'total': 0, 'nuevos': 0, 'rojo': 0, 'amarillo': 0, 'naranja': 0, 'verde': 0})
        grupo['total'] += 1
        grupo['nuevos'] += 0 if recordatorio.leido else 1
        clave = recordatorio.prioridad['clave']
        if clave:
            grupo[clave] += 1
    return sorted(grupos.values(),
                  key=lambda g: (-g['rojo'], -g['amarillo'], -g['naranja'], -g['total']))


def dias_de_actividad(bandeja):
    """«Actividad»: por día (hora de Cuba) y tipo, lo más reciente primero."""
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    filas = (bandeja.filter(tipo=Notificacion.Tipo.EVENTO, codigo_regla__startswith=PREFIJO_ACTIVIDAD)
             .annotate(dia=TruncDate('fecha_creado', tzinfo=timezone.get_current_timezone()))
             .order_by().values('dia', 'codigo_regla').annotate(total=Count('pk')))
    dias = {}
    for fila in filas:
        dia = dias.setdefault(fila['dia'], {'dia': fila['dia'], 'tipos': [], 'total': 0})
        dia['tipos'].append({'codigo_regla': fila['codigo_regla'], 'total': fila['total'],
                             'nombre': nombre_de_codigo(fila['codigo_regla'])})
        dia['total'] += fila['total']
    for dia in dias.values():
        dia['nombre_dia'] = DIAS_SEMANA[dia['dia'].weekday()]
        dia['tipos'].sort(key=lambda t: list(NOMBRES).index(t['codigo_regla'])
                          if t['codigo_regla'] in NOMBRES else 99)
    return sorted(dias.values(), key=lambda d: d['dia'], reverse=True)


def actividad_de_un_dia(bandeja, dia, usuario):
    """Lo que pasó un día, por tipo: los `FILAS_AL_ABRIR` más recientes de cada
    tipo. Los avisos idénticos (20 plazas del mismo cargo creadas de golpe) salen en
    una sola línea con «×20»."""
    del_dia = bandeja.filter(tipo=Notificacion.Tipo.EVENTO, codigo_regla__startswith=PREFIJO_ACTIVIDAD,
                             fecha_creado__date=dia)
    tipos = []
    for tipo in dias_de_actividad(del_dia):
        for grupo in tipo['tipos']:
            lineas = list(del_dia.filter(codigo_regla=grupo['codigo_regla'])
                          .order_by().values('mensaje', 'unidad__descripcion', 'autor_id', 'autor__username')
                          .annotate(veces=Count('pk'), ultima=Max('fecha_creado'))
                          .order_by('-ultima')[:FILAS_AL_ABRIR])
            for linea in lineas:
                linea['es_mio'] = linea['autor_id'] == usuario.pk
            tipos.append(dict(grupo, lineas=lineas))
    return tipos


def supervision_por_moderador(solo_pendientes):
    """Supervisión (solo Administrador): por moderador, cuántos avisos tiene sin
    leer de lo que hay que hacer, regla a regla. Así se ve quién va atrasado."""
    pendiente = Q(leido=False) & q_accionable()
    filas = (Notificacion.objects.filter(destinatario__es_moderador=True)
             .order_by().values('destinatario_id', 'destinatario__username', 'tipo', 'codigo_regla')
             .annotate(total=Count('pk'), sin_leer=Count('pk', filter=pendiente)))
    moderadores = {}
    for fila in filas:
        if solo_pendientes and not fila['sin_leer']:
            continue
        moderador = moderadores.setdefault(fila['destinatario_id'], {
            'id': fila['destinatario_id'], 'usuario': fila['destinatario__username'],
            'sin_leer': 0, 'total': 0, 'grupos': []})
        moderador['sin_leer'] += fila['sin_leer']
        moderador['total'] += fila['total']
        moderador['grupos'].append({'tipo': fila['tipo'], 'codigo_regla': fila['codigo_regla'],
                                    'nombre': nombre_de_codigo(fila['codigo_regla']),
                                    'sin_leer': fila['sin_leer'], 'total': fila['total']})
    for moderador in moderadores.values():
        moderador['grupos'].sort(key=lambda g: (-g['sin_leer'], -g['total']))
    return sorted(moderadores.values(), key=lambda m: (-m['sin_leer'], m['usuario']))


def lineas_de_la_campana(usuario, limite=5):
    """El desplegable de la campana: lo que cuenta, agrupado por tipo y código, lo
    más grave primero; y aparte, la Actividad de hoy."""
    from django.utils import timezone

    from .campana import accionables

    filas = (accionables(usuario).order_by().values('tipo', 'codigo_regla')
             .annotate(total=Count('pk'), gravedad=Min('severidad'), objetivo=Min('fecha_objetivo'),
                       ultima=Max('fecha_creado'), titulo=Max('titulo')))
    hoy = timezone.localdate()

    def urgencia(fila):
        """Se mezclan los tipos por urgencia, para que en 5 líneas quepa lo más
        importante de cada cosa y no solo advertencias."""
        if fila['codigo_regla'] == 'RANKING':
            return 0
        if fila['tipo'] == Notificacion.Tipo.ALERTA:
            return 1 if (fila['gravedad'] or 0) <= CRITICIDAD_CRITICA else 4
        if fila['tipo'] == Notificacion.Tipo.RECORDATORIO:
            return 2 if fila['objetivo'] is None or fila['objetivo'] <= hoy else 5
        return 3                          # solicitudes, cierres, decisiones

    lineas = sorted(filas, key=lambda f: (urgencia(f), f['gravedad'] or 0, f['objetivo'] or hoy, -f['total']))
    for linea in lineas:
        linea['nombre'] = nombre_de_codigo(linea['codigo_regla'])
        linea['grupo'] = f"{linea['tipo']}:{linea['codigo_regla']}"
        linea.pop('ultima')
    de_hoy = (Notificacion.objects.filter(destinatario=usuario, tipo=Notificacion.Tipo.EVENTO,
                                          codigo_regla__startswith=PREFIJO_ACTIVIDAD, fecha_creado__date=hoy)
              .order_by().values('codigo_regla').annotate(total=Count('pk')))
    actividad = [{'nombre': nombre_de_codigo(f['codigo_regla']).lower(), 'total': f['total']} for f in de_hoy]
    return lineas[:limite], max(len(lineas) - limite, 0), actividad
