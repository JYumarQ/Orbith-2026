"""Datos de la página "Estadísticas de uso" (solo Administradores).

Dos cosas distintas que NO se mezclan:
- **XP** (ranking): sale de `ActividadXP.xp`, con los topes diarios.
- **USO**: todo lo que hizo cada usuario en el mes, SIN topes. Sale de
  `ActividadXP` (se cuentan las filas, den XP o no) y de Auditoría
  (ediciones, eliminaciones e inicios de sesión).

Reglas del uso decididas con RRHH:
- Ediciones: modificaciones en contratos, datos personales (aspirantes) y
  plantilla (estructura). Al Moderador, además, cada solicitud que envía
  cuenta como un cambio de plantilla.
- Eliminaciones: en esos mismos módulos.
- Las altas, los movimientos de nómina y las bajas tienen su propia acción en
  Auditoría (`AccionAuditoria.ALTA/MOVIMIENTO/BAJA`) y su propia columna aquí:
  nunca cuentan como edición o eliminación.
- Pre-Nómina no cuenta hasta que el módulo esté terminado.
- Los inicios de sesión van aparte del trabajo: entrar no es trabajar.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from auditoria.models import AccionAuditoria, EventoAuditoria

from .models import Actividad, ActividadXP, Rol
from .servicios import (ICONOS, MESES, MESES_CONSERVADOS, SIN_NOMBRE, clasificacion, iniciales,
                        limites_mes, mes_anterior, nombre_publico, progreso_nivel, rol_de,
                        totales_del_mes)
from .puntos import PUNTOS, XP_DIA_ACTIVO

# Módulos de Auditoría que cuentan como trabajo, y en qué se convierten.
MODULOS_EDICION = {
    'contratos': 'contratos',
    'aspirantes': 'datos_personales',
    'estructura': 'plantilla',
}
ETIQUETAS_EDICION = {
    'contratos': 'Contratos',
    'datos_personales': 'Datos personales',
    'plantilla': 'Plantilla',
}
EDICIONES = 'ediciones'
ELIMINACIONES = 'eliminaciones'
DIAS_ACTIVOS = 'dias'

# Columnas de "Trabajo" de cada rol, en orden.
COLUMNAS_TRABAJO = {
    Rol.MODERADOR: [
        (Actividad.ASPIRANTE, 'Aspirantes'),
        (Actividad.ALTA, 'Altas'),
        (Actividad.MOVIMIENTO, 'Movimientos'),
        (Actividad.ENVIO_MOVIMIENTO, 'Enviados a Mov. Nómina'),
        (Actividad.BAJA, 'Bajas'),
        (Actividad.SOLICITUD_APROBADA, 'Solicitudes aprobadas'),
        (Actividad.CIERRE_EN_PLAZO, 'Cierres en plazo'),
        (Actividad.HALLAZGO_REVISADO, 'Hallazgos revisados'),
        (Actividad.RECORDATORIO_COMPLETADO, 'Recordatorios completados'),
        (Actividad.INFORME, 'Informes'),
        (Actividad.DESCARGA, 'Descargas'),
        (EDICIONES, 'Ediciones'),
        (ELIMINACIONES, 'Eliminaciones'),
        (DIAS_ACTIVOS, 'Días activos'),
    ],
    Rol.ADMINISTRADOR: [
        (Actividad.SOLICITUD_DECIDIDA, 'Solicitudes decididas'),
        (Actividad.ANALISIS_SUBSANACION, 'Análisis de Subsanación'),
        (Actividad.RECORDATORIO_CREADO, 'Recordatorios creados'),
        (Actividad.INFORME, 'Informes'),
        (Actividad.DESCARGA, 'Descargas'),
        (EDICIONES, 'Ediciones'),
        (ELIMINACIONES, 'Eliminaciones'),
        (DIAS_ACTIVOS, 'Días activos'),
    ],
    # El Observador no puede editar ni eliminar nada.
    Rol.OBSERVADOR: [
        (Actividad.INFORME, 'Informes'),
        (Actividad.DESCARGA, 'Descargas'),
        (DIAS_ACTIVOS, 'Días activos'),
    ],
}

ORDEN_ROLES = (Rol.ADMINISTRADOR, Rol.MODERADOR, Rol.OBSERVADOR)
ROLES_PLURAL = {Rol.ADMINISTRADOR: 'Administradores', Rol.MODERADOR: 'Moderadores',
                Rol.OBSERVADOR: 'Observadores'}

FORMATOS = (('pdf', 'PDF'), ('word', 'Word'), ('excel', 'Excel'))


# ----------------------------------------------------------------------
# Meses
# ----------------------------------------------------------------------
def meses_disponibles(hoy=None):
    """Los meses que se conservan, del más reciente al más antiguo."""
    hoy = hoy or timezone.localdate()
    meses = []
    for atras in range(MESES_CONSERVADOS):
        anno, mes = mes_anterior(hoy.year, hoy.month, atras)
        meses.append({'anno': anno, 'mes': mes, 'clave': f'{anno}-{mes:02d}',
                      'etiqueta': f'{MESES[mes - 1]} {anno}', 'en_curso': atras == 0})
    return meses


def mes_elegido(clave, hoy=None):
    """El mes de la lista que corresponde a `clave` ('2026-10'), o el actual."""
    meses = meses_disponibles(hoy)
    return next((m for m in meses if m['clave'] == clave), meses[0])


def _rango_fechas(anno, mes):
    """Inicio y fin del mes como fechas con hora, en la zona de Orbith."""
    inicio, fin = limites_mes(anno, mes)
    zona = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(inicio, time.min), zona),
            timezone.make_aware(datetime.combine(fin, time.min), zona))


# ----------------------------------------------------------------------
# Uso
# ----------------------------------------------------------------------
def _eventos_de_trabajo(anno, mes, usuario=None):
    """Ediciones y eliminaciones de Auditoría que cuentan como trabajo."""
    desde, hasta = _rango_fechas(anno, mes)
    eventos = (EventoAuditoria.objects
               .filter(fecha__gte=desde, fecha__lt=hasta, usuario__isnull=False)
               .filter(modulo__in=list(MODULOS_EDICION) + ['solicitudes']))
    if usuario is not None:
        eventos = eventos.filter(usuario=usuario)
    return eventos


def _clasificar_evento(evento_modulo, accion, descriptor, rol):
    """(tipo, detalle) de un evento de Auditoría para el uso, o None si no cuenta.
    tipo es EDICIONES o ELIMINACIONES; detalle, la clave de ETIQUETAS_EDICION."""
    if evento_modulo == 'solicitudes':
        # Solo las que envía el Moderador: así cambia él la plantilla.
        if accion == AccionAuditoria.CREAR and rol == Rol.MODERADOR:
            return EDICIONES, 'plantilla'
        return None
    # Alta, Movimiento y Baja tienen su propia acción (y su columna): no entran aquí.
    if accion == AccionAuditoria.MODIFICAR:
        return EDICIONES, MODULOS_EDICION[evento_modulo]
    if accion == AccionAuditoria.ELIMINAR:
        return ELIMINACIONES, MODULOS_EDICION[evento_modulo]
    return None


def uso_del_mes(anno, mes, usuarios):
    """{usuario_id: {columna: cantidad, ..., 'sesiones', 'dias_sesion'}} de todos
    los `usuarios` (ya con su rol en `usuario.rol_ranking`)."""
    ids = [u.pk for u in usuarios]
    rol_por_id = {u.pk: u.rol_ranking for u in usuarios}
    uso = {pk: defaultdict(int) for pk in ids}
    inicio, fin = limites_mes(anno, mes)

    actividades = (ActividadXP.objects
                   .filter(usuario_id__in=ids, dia__gte=inicio, dia__lt=fin)
                   .values('usuario_id', 'actividad').annotate(n=Count('id')))
    for fila in actividades:
        clave = DIAS_ACTIVOS if fila['actividad'] == Actividad.DIA_ACTIVO else fila['actividad']
        uso[fila['usuario_id']][clave] += fila['n']

    for evento in (_eventos_de_trabajo(anno, mes).filter(usuario_id__in=ids)
                   .values('usuario_id', 'modulo', 'accion', 'descriptor')):
        tipo = _clasificar_evento(evento['modulo'], evento['accion'], evento['descriptor'],
                                  rol_por_id[evento['usuario_id']])
        if tipo:
            uso[evento['usuario_id']][tipo[0]] += 1

    desde, hasta = _rango_fechas(anno, mes)
    accesos = (EventoAuditoria.objects
               .filter(usuario_id__in=ids, accion=AccionAuditoria.ACCESO, fecha__gte=desde, fecha__lt=hasta)
               .annotate(dia=TruncDate('fecha'))
               .values('usuario_id', 'dia').annotate(n=Count('id')))
    for fila in accesos:
        uso[fila['usuario_id']]['sesiones'] += fila['n']
        uso[fila['usuario_id']]['dias_sesion'] += 1
    return uso


def _usuarios_por_rol():
    """{rol: [usuarios activos de ese rol]} con su rol en `rol_ranking`."""
    por_rol = {rol: [] for rol in ORDEN_ROLES}
    for usuario in (get_user_model().objects.filter(is_active=True)
                    .select_related('contrato__aspirante')):
        rol = rol_de(usuario)
        if rol is not None:
            usuario.rol_ranking = rol
            por_rol[rol].append(usuario)
    return por_rol


def nombre_para_admin(usuario):
    """Nombre de una persona en esta página, que SOLO ve el Administrador: el del
    trabajador vinculado o el de la ficha y, si no hay ninguno, su nombre de usuario
    (el Administrador ya lo conoce). En la ventana del Ranking, que ven todos, se
    sigue usando `nombre_publico`, que nunca muestra el nombre de usuario."""
    nombre = nombre_publico(usuario)
    return usuario.get_username() if nombre == SIN_NOMBRE else nombre


def _persona(usuario):
    nombre = nombre_para_admin(usuario)
    return {'pk': usuario.pk, 'nombre': nombre, 'iniciales': iniciales(nombre),
            'avatar': usuario.avatar.url if usuario.avatar else ''}


def datos_pagina(anno, mes, hoy=None):
    """Todo lo de la página para el mes elegido."""
    por_rol = _usuarios_por_rol()
    todos = [u for usuarios in por_rol.values() for u in usuarios]
    uso = uso_del_mes(anno, mes, todos)

    secciones = []
    sin_actividad = []
    for rol in ORDEN_ROLES:
        columnas = COLUMNAS_TRABAJO[rol]
        ranking = [{**f, **_persona(f['usuario'])}
                   for f in clasificacion(anno, mes, rol, incluir_sin_xp=True)]
        filas_uso = []
        for usuario in sorted(por_rol[rol], key=lambda u: nombre_para_admin(u).lower()):
            datos = uso[usuario.pk]
            trabajo = [datos.get(clave, 0) for clave, _ in columnas]
            filas_uso.append({**_persona(usuario), 'trabajo': trabajo,
                              'sesiones': datos.get('sesiones', 0),
                              'dias_sesion': datos.get('dias_sesion', 0)})
            if not any(trabajo):
                sin_actividad.append({**_persona(usuario), 'rol': Rol(rol).label,
                                      'entro': datos.get('sesiones', 0) > 0,
                                      'ultimo_acceso': usuario.last_login})
        secciones.append({'rol': rol, 'titulo': ROLES_PLURAL[rol], 'ranking': ranking,
                          'columnas': [etiqueta for _, etiqueta in columnas], 'uso': filas_uso})

    return {
        'secciones': secciones,
        'sin_actividad': sin_actividad,
        'unidades': unidades_sin_cierre_en_plazo(anno, mes, hoy),
    }


# ----------------------------------------------------------------------
# Unidades sin cierre en plazo
# ----------------------------------------------------------------------
def unidades_sin_cierre_en_plazo(anno, mes, hoy=None):
    """Unidades que no declararon el cierre del mes o lo declararon fuera de
    plazo. Del mes en curso solo a partir del día siguiente al fin del plazo.

    Solo las que ya tenían obligación: hicieron su primera declaración en ese
    mes o antes (mismo criterio que `cierres.servicios.unidades_sin_cierre`).
    Las Direcciones Principales no declaran.
    """
    from cierres.constantes import DIA_FIN_VENTANA
    from cierres.models import CierreUnidad
    from cierres.permisos import es_principal
    from strorganizativa.models import UnidadOrganizativa

    hoy = hoy or timezone.localdate()
    if (anno, mes) == (hoy.year, hoy.month) and hoy.day <= DIA_FIN_VENTANA:
        return []

    cierres = {c.unidad_id: c for c in CierreUnidad.objects.filter(anno=anno, mes=mes)}
    primeros = {}
    for fila in CierreUnidad.objects.values('unidad_id', 'anno', 'mes').order_by('anno', 'mes'):
        primeros.setdefault(fila['unidad_id'], (fila['anno'], fila['mes']))

    resultado = []
    for unidad in UnidadOrganizativa.objects.select_related('tipo').order_by('descripcion'):
        if es_principal(unidad) or unidad.pk not in primeros or primeros[unidad.pk] > (anno, mes):
            continue
        cierre = cierres.get(unidad.pk)
        if cierre is None:
            resultado.append({'unidad': unidad, 'estado': 'Sin declarar', 'puede_recordar': True})
        elif not cierre.en_plazo:
            resultado.append({'unidad': unidad, 'estado': 'Declarada fuera de plazo', 'puede_recordar': False})
    return resultado


# ----------------------------------------------------------------------
# Panel lateral de un usuario
# ----------------------------------------------------------------------
def detalle_usuario(usuario, anno, mes):
    """XP y uso de `usuario` en el mes, por separado, para el panel lateral."""
    rol = rol_de(usuario)
    inicio, fin = limites_mes(anno, mes)
    etiquetas = dict(Actividad.choices)

    filas = clasificacion(anno, mes, rol, incluir_sin_xp=True) if rol else []
    mia = next((f for f in filas if f['usuario'].pk == usuario.pk), None)
    xp = mia['xp'] if mia else 0

    # --- XP: veces que hizo cada actividad y XP que le dio (con los topes).
    por_actividad = (ActividadXP.objects.filter(usuario=usuario, dia__gte=inicio, dia__lt=fin)
                     .values('actividad').annotate(veces=Count('id'))
                     .order_by('actividad'))
    xp_por_actividad = defaultdict(int)
    for codigo, valor in (ActividadXP.objects.filter(usuario=usuario, dia__gte=inicio, dia__lt=fin)
                          .values_list('actividad', 'xp')):
        xp_por_actividad[codigo] += valor
    desglose_xp = sorted(
        ({'etiqueta': etiquetas.get(f['actividad'], f['actividad']), 'icono': ICONOS.get(f['actividad'], 'bx-star'),
          'veces': f['veces'], 'xp': xp_por_actividad[f['actividad']],
          'tope': f['veces'] > 0 and xp_por_actividad[f['actividad']] < f['veces'] * _valor(rol, f['actividad'])}
         for f in por_actividad),
        key=lambda d: -d['xp'])

    evolucion = []
    for atras in range(MESES_CONSERVADOS - 1, -1, -1):
        a, m = mes_anterior(anno, mes, atras)
        total = totales_del_mes(a, m).get(usuario.pk) or 0
        evolucion.append({'etiqueta': MESES[m - 1], 'xp': total, 'actual': atras == 0})
    maximo = max(e['xp'] for e in evolucion) or 1
    for e in evolucion:
        e['porcentaje'] = max(4, round(100 * e['xp'] / maximo)) if e['xp'] else 0

    # --- Uso: por actividad, ediciones y eliminaciones por tipo, descargas por formato.
    usuario.rol_ranking = rol
    uso = uso_del_mes(anno, mes, [usuario])[usuario.pk]
    actividades_uso = [
        {'etiqueta': etiqueta, 'veces': uso.get(clave, 0)}
        for clave, etiqueta in COLUMNAS_TRABAJO.get(rol, [])
        if clave not in (EDICIONES, ELIMINACIONES, DIAS_ACTIVOS, Actividad.DESCARGA)
    ]
    ediciones = defaultdict(int)
    eliminaciones = defaultdict(int)
    ultimas = []
    dias_trabajo = set()
    for evento in _eventos_de_trabajo(anno, mes, usuario).order_by('-fecha'):
        tipo = _clasificar_evento(evento.modulo, evento.accion, evento.descriptor, rol)
        if not tipo:
            continue
        (ediciones if tipo[0] == EDICIONES else eliminaciones)[tipo[1]] += 1
        dias_trabajo.add(timezone.localtime(evento.fecha).date())
        ultimas.append({'fecha': evento.fecha, 'texto': evento.descriptor,
                        'tipo': 'Edición' if tipo[0] == EDICIONES else 'Eliminación'})

    acciones = (ActividadXP.objects.filter(usuario=usuario, dia__gte=inicio, dia__lt=fin)
                .exclude(actividad=Actividad.DIA_ACTIVO))
    for accion in acciones.order_by('-fecha'):
        dias_trabajo.add(accion.dia)
        ultimas.append({'fecha': accion.fecha, 'texto': accion.detalle,
                        'tipo': accion.get_actividad_display()})
    ultimas.sort(key=lambda u: u['fecha'], reverse=True)

    descargas = dict(acciones.filter(actividad=Actividad.DESCARGA)
                     .values('formato').annotate(n=Count('id')).values_list('formato', 'n'))

    desde, hasta = _rango_fechas(anno, mes)
    dias_sesion = {timezone.localtime(f).date() for f in EventoAuditoria.objects.filter(
        usuario=usuario, accion=AccionAuditoria.ACCESO, fecha__gte=desde, fecha__lt=hasta)
        .values_list('fecha', flat=True)}

    calendario = [{'dia': None}] * inicio.weekday()
    dia = inicio
    while dia < fin:
        clase = 'trabajo' if dia in dias_trabajo else ('sesion' if dia in dias_sesion else '')
        calendario.append({'dia': dia.day, 'clase': clase})
        dia += timedelta(days=1)

    return {
        'persona': _persona(usuario),
        'rol_etiqueta': Rol(rol).label if rol else 'Sin rol',
        'mes_etiqueta': f'{MESES[mes - 1]} {anno}',
        'xp': xp,
        'puesto': mia['puesto'] if mia and xp else None,
        'participantes': sum(1 for f in filas if f['xp'] > 0),
        'progreso': progreso_nivel(rol, xp) if rol else None,
        'desglose_xp': desglose_xp,
        'evolucion': evolucion,
        'actividades_uso': actividades_uso,
        'ediciones': [{'etiqueta': ETIQUETAS_EDICION[k], 'veces': v} for k, v in ediciones.items()],
        'eliminaciones': [{'etiqueta': ETIQUETAS_EDICION[k], 'veces': v} for k, v in eliminaciones.items()],
        'puede_editar': rol != Rol.OBSERVADOR,
        'descargas': [{'etiqueta': etiqueta, 'veces': descargas.get(clave, 0)} for clave, etiqueta in FORMATOS],
        'calendario': calendario,
        'sesiones': uso.get('sesiones', 0),
        'dias_sesion': uso.get('dias_sesion', 0),
        'ultimas': ultimas[:10],
    }


def _valor(rol, actividad):
    """XP por acción de esa actividad en ese rol (para saber si llegó al tope)."""
    if actividad == Actividad.DIA_ACTIVO:
        return XP_DIA_ACTIVO
    return PUNTOS.get(rol, {}).get(actividad, (0, None))[0]
