"""Reglas de integridad de las cuentas de usuario.

Dos reglas del catálogo original se descartaron aquí, deliberadamente, tras medir la
base de datos real:

* «Usuario sin trabajador asociado», de forma genérica: una cuenta de administrador o
  de sistema no tiene por qué estar ligada a ningún trabajador (`CustomUser.contrato`
  es opcional a propósito). Implementarla así habría repetido el error de VIS-004:
  ruido estructural sobre una situación válida por diseño. Solo se implementa el caso
  inequívoco, `UsuarioActivoConTrabajadorDeBaja`: ahí SÍ hay un contrato asociado, y
  ese contrato SÍ resultó ser de alguien que ya no trabaja en la entidad.
* «Es admin sin superuser» se implementa (`AdminSinSuperusuario`), porque
  `CustomUser.save()` lo sincroniza siempre que se pasa por el formulario; solo se
  puede violar escribiendo directamente en la base de datos, y detectarlo no tiene
  ambigüedad posible.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ..constantes import (
    CRITICIDAD_ALTA,
    CRITICIDAD_INFORMATIVA,
    CRITICIDAD_MEDIA,
    MODULO_USUARIOS,
    TAMANO_LOTE,
)
from .base import HallazgoDetectado, ReglaBase

# Días sin iniciar sesión a partir de los cuales se considera inactividad prolongada.
# No hay ningún valor de referencia en el código ni en la configuración de Orbith; se
# asume 90 días como un umbral razonable para una aplicación de uso diario, y se deja
# como constante de módulo para poder ajustarlo sin tocar la regla.
DIAS_INACTIVIDAD = 90


class ReglaUsuarios(ReglaBase):
    abstracta = True
    modulo = MODULO_USUARIOS
    modelo = 'usuarios.CustomUser'


class UsuarioActivoConTrabajadorDeBaja(ReglaUsuarios):
    codigo = 'USR-001'
    nombre = 'Usuario activo cuyo trabajador está de baja'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Busca cuentas de usuario activas cuyo contrato asociado pertenece a '
        'un trabajador que ya está de baja.')
    causa_probable = (
        'Se dio de baja al trabajador pero no se desactivó ni se desvinculó '
        'su cuenta de usuario en Orbith.')
    impacto = (
        'Una persona que ya no trabaja en la entidad conserva acceso al '
        'sistema, con el rol y los permisos que tuviera asignados.')
    solucion = (
        'Abra el usuario y desactive la cuenta, o quítele el contrato '
        'asociado si la cuenta debe conservarse por otro motivo.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(is_active=True, contrato__isnull=False,
                         contrato__aspirante__estado='BAJA')
                 .values('id', 'username', 'contrato__no_expediente',
                         'contrato__aspirante__nombre',
                         'contrato__aspirante__papellido',
                         'contrato__aspirante__sapellido')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            usuario = fila.get('username') or f'Usuario {fila["id"]}'
            trabajador = ' '.join(filter(None, [
                fila.get('contrato__aspirante__nombre'),
                fila.get('contrato__aspirante__papellido'),
                fila.get('contrato__aspirante__sapellido'),
            ])) or '—'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{usuario} · activo, y su trabajador ({trabajador}) está de baja',
                detalle=(
                    f'La cuenta «{usuario}» está activa y vinculada al expediente '
                    f'{fila.get("contrato__no_expediente") or "—"}, pero ese '
                    f'trabajador ya está de baja.'),
                datos={'usuario': usuario, 'trabajador': trabajador,
                       'cuenta_activa': 'Sí', 'trabajador_en_estado': 'BAJA'},
            )


class AdminSinSuperusuario(ReglaUsuarios):
    codigo = 'USR-002'
    nombre = 'Administrador sin privilegios de superusuario'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Todo usuario con el rol «Administrador» debe tener también el '
        'privilegio de superusuario de Django: `CustomUser.save()` lo '
        'sincroniza siempre que la cuenta se guarda desde el formulario.')
    causa_probable = (
        'La cuenta se creó o se modificó por una vía que no pasa por '
        '`save()` (una consola de administración, una importación, un '
        'script), así que la sincronización automática no se aplicó.')
    impacto = (
        'Un administrador sin privilegios de superusuario puede no tener '
        'acceso a partes del sistema que dependen de `is_superuser`, así que '
        'su rol y sus permisos reales quedan desincronizados.')
    solucion = (
        'Abra el usuario y guárdelo de nuevo desde el formulario: al '
        'guardar, Orbith sincroniza el privilegio de superusuario con el rol '
        'de administrador.')

    def ejecutar(self, contexto):
        filas = (self.base_queryset()
                 .filter(es_admin=True)
                 .exclude(is_superuser=True)
                 .values('id', 'username')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            usuario = fila.get('username') or f'Usuario {fila["id"]}'
            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=f'{usuario} · es administrador y no tiene privilegios de superusuario',
                detalle=(
                    f'La cuenta «{usuario}» tiene el rol de Administrador, pero '
                    f'`is_superuser` está en False.'),
                datos={'usuario': usuario, 'rol': 'Administrador', 'is_superuser': 'No'},
            )


class UsuarioInactivoProlongado(ReglaUsuarios):
    codigo = 'USR-003'
    nombre = 'Usuario sin iniciar sesión desde hace mucho tiempo'
    criticidad = CRITICIDAD_INFORMATIVA

    descripcion = (
        f'Señala cuentas activas que no han iniciado sesión en los últimos '
        f'{DIAS_INACTIVIDAD} días, o que nunca lo han hecho desde que se '
        f'crearon.')
    causa_probable = (
        'El trabajador dejó de usar el sistema sin que se haya desactivado '
        'su cuenta, o la cuenta se creó y nunca llegó a utilizarse.')
    impacto = (
        'Es informativo: una cuenta activa que nadie usa es una puerta de '
        'acceso innecesaria. No implica ningún error de datos.')
    solucion = (
        'Confirme con el área correspondiente si la cuenta sigue siendo '
        'necesaria. Si no lo es, desactívela desde el formulario de usuario.')

    def ejecutar(self, contexto):
        limite = timezone.now() - timedelta(days=DIAS_INACTIVIDAD)

        # Dos casos distintos, cada uno con su propio texto: no es lo mismo llevar
        # mucho tiempo sin entrar que no haber entrado nunca desde que se creó la
        # cuenta. Se exige `fecha_creado` anterior al límite en el segundo caso para
        # no marcar como «inactiva» una cuenta creada ayer que aún no ha tenido
        # ocasión de usarse.
        filas = (self.base_queryset()
                 .filter(is_active=True)
                 .filter(Q(last_login__lt=limite)
                         | Q(last_login__isnull=True, fecha_creado__lt=limite.date()))
                 .values('id', 'username', 'last_login', 'fecha_creado')
                 .iterator(chunk_size=TAMANO_LOTE))

        for fila in filas:
            usuario = fila.get('username') or f'Usuario {fila["id"]}'
            ultimo_acceso = fila.get('last_login')

            if ultimo_acceso is None:
                titulo = f'{usuario} · nunca ha iniciado sesión'
                detalle = (
                    f'La cuenta «{usuario}» existe desde el '
                    f'{fila["fecha_creado"]:%d/%m/%Y} y nunca ha iniciado sesión.')
                dato_acceso = 'Nunca'
            else:
                dias = (timezone.now() - ultimo_acceso).days
                titulo = f'{usuario} · sin iniciar sesión desde hace {dias} días'
                detalle = (
                    f'La cuenta «{usuario}» no inicia sesión desde el '
                    f'{ultimo_acceso:%d/%m/%Y} ({dias} días).')
                dato_acceso = ultimo_acceso.strftime('%d/%m/%Y')

            yield HallazgoDetectado(
                object_id=str(fila['id']),
                titulo=titulo,
                detalle=detalle,
                datos={'usuario': usuario, 'ultimo_acceso': dato_acceso,
                       'umbral_de_inactividad_dias': DIAS_INACTIVIDAD},
            )
