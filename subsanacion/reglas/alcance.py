"""Reglas del reparto de Unidades Organizativas entre los moderadores.

EL INVARIANTE QUE VIGILAN
-------------------------
Una subunidad no se asigna por separado: se asigna su Unidad Principal y las
subunidades entran con ella. Dicho al revés, que es como se comprueba:

    quien lleva la subunidad = quien lleva a su padre

Lo imponen `usuarios/forms.py` al guardar y `strorganizativa/signals.py` cuando
nace o se muda una subunidad. Pero ninguno de los dos alcanza a lo que ya estaba
escrito antes de que existieran, ni a lo que entre por fuera del formulario: una
importación, el shell o el Admin de Django.

POR QUÉ MERECE UNA REGLA Y NO SOLO EL COMANDO
---------------------------------------------
Porque el fallo es SILENCIOSO y el síntoma no apunta a la causa. Un moderador al
que le falta una subunidad simplemente «no ve a su gente»: desaparece de
Contratos, Informes, Dashboard, Pre-Nómina y Notificaciones, y además no puede
declarar el cierre de esa unidad —`cierres.permisos.puede_declarar` exige tenerla
asignada y NIEGA declarar directamente la principal—. Nadie relaciona eso con un
reparto de unidades incompleto.

`manage.py sincronizar_unidades` lo repara, pero hay que acordarse de ejecutarlo.
Esta regla lo saca en el panel sin que nadie lo pida.
"""

from ..constantes import (CRITICIDAD_ALTA, CRITICIDAD_MEDIA, MODULO_USUARIOS,
                          TAMANO_LOTE)
from .base import HallazgoDetectado, ReglaBase


class ReglaRepartoDeUnidades(ReglaBase):
    """Base común. Carga una sola vez la jerarquía y el reparto."""

    abstracta = True
    modulo = MODULO_USUARIOS
    modelo = 'usuarios.CustomUser'

    def _mapa(self):
        """`(hijas_de, asignadas_por_usuario, nombre_de_unidad)`.

        Tres consultas en total, no una por usuario: la estructura y el reparto
        completos caben de sobra en memoria (decenas de unidades, unos pocos
        moderadores).
        """
        from django.apps import apps

        UnidadOrganizativa = apps.get_model('strorganizativa', 'UnidadOrganizativa')

        hijas_de = {}
        nombre_de = {}
        for pk, padre_id, descripcion in UnidadOrganizativa.objects.values_list(
                'pk', 'padre_id', 'descripcion'):
            nombre_de[pk] = descripcion
            if padre_id:
                hijas_de.setdefault(padre_id, []).append(pk)

        asignadas = {}
        for usuario in (self.base_queryset()
                        .filter(es_moderador=True)
                        .prefetch_related('unidades')
                        .iterator(chunk_size=TAMANO_LOTE)):
            asignadas[usuario] = {u.pk for u in usuario.unidades.all()}

        return hijas_de, asignadas, nombre_de


class ModeradorSinLasSubunidadesDeSuPrincipal(ReglaRepartoDeUnidades):
    """El moderador lleva una Unidad Principal pero le faltan subunidades suyas.

    Es el caso que deja a alguien a medio ver sin que nada lo diga: una Dirección
    Principal no tiene cargos propios, así que si le faltan las hijas, el
    moderador puede acabar sin ver absolutamente nada de su propia dirección.
    """

    codigo = 'VIS-008'
    nombre = 'Moderador sin todas las subunidades de su unidad principal'
    criticidad = CRITICIDAD_ALTA

    descripcion = (
        'Comprueba que un moderador que lleva una Unidad Principal tenga también '
        'asignadas todas las subunidades que cuelgan de ella.')
    causa_probable = (
        'La asignación se hizo antes de que el formulario expandiera a las '
        'subunidades, o se escribió por fuera de la pantalla de Usuarios (una '
        'importación, el Admin de Django o el shell).')
    impacto = (
        'El moderador no ve a los trabajadores de esas subunidades en Contratos, '
        'Informes, Dashboard, Pre-Nómina ni Notificaciones, y no puede declarar su '
        'cierre mensual. Nada se lo advierte: para él, esa gente no existe.')
    solucion = (
        'Ejecute «manage.py sincronizar_unidades» para repararlo de una vez, o '
        'abra la ficha del usuario en Administración → Usuarios y vuelva a '
        'guardarla: al guardar, las subunidades entran solas.')

    def ejecutar(self, contexto):
        hijas_de, asignadas, nombre_de = self._mapa()

        for usuario, unidades in asignadas.items():
            faltantes = sorted(
                {hija for pk in unidades for hija in hijas_de.get(pk, ())
                 if hija not in unidades})
            if not faltantes:
                continue

            nombres = [nombre_de.get(pk, str(pk)) for pk in faltantes]
            yield HallazgoDetectado(
                object_id=str(usuario.pk),
                titulo=f'{usuario.username} · le faltan subunidades de su unidad principal',
                detalle=(
                    'Lleva una Unidad Principal pero no tiene asignadas todas sus '
                    'subunidades, así que no ve a los trabajadores de: '
                    + ', '.join(nombres) + '.'),
                datos={
                    'moderador': usuario.username,
                    'subunidades_sin_asignar': ', '.join(nombres),
                },
                campo_formulario='unidades',
            )


class ModeradorConSubunidadSuelta(ReglaRepartoDeUnidades):
    """El moderador lleva una subunidad pero NO su Unidad Principal.

    Es el reverso del anterior y el reparto absurdo que la pantalla de Usuarios
    dejó de permitir: una subunidad cuyo padre lleva otra persona, o nadie.
    """

    codigo = 'VIS-009'
    nombre = 'Moderador con una subunidad sin su unidad principal'
    criticidad = CRITICIDAD_MEDIA

    descripcion = (
        'Busca moderadores que tengan asignada una subunidad sin tener también la '
        'Unidad Principal de la que cuelga.')
    causa_probable = (
        'Un reparto anterior a la regla actual, o una asignación hecha por fuera '
        'de la pantalla de Usuarios, que es la única que impide elegir una '
        'subunidad suelta.')
    impacto = (
        'El reparto queda ambiguo: la subunidad la lleva una persona y su unidad '
        'principal otra (o nadie), así que no está claro quién responde de ella ni '
        'quién debe declarar su cierre.')
    solucion = (
        'Decida quién lleva la Unidad Principal y asígnesela: sus subunidades '
        'entrarán con ella. Si la subunidad debe ir por su cuenta, conviértala en '
        'una unidad independiente en el Gestor de Plantilla.')

    def ejecutar(self, contexto):
        from django.apps import apps

        UnidadOrganizativa = apps.get_model('strorganizativa', 'UnidadOrganizativa')
        padre_de = dict(UnidadOrganizativa.objects.exclude(padre__isnull=True)
                        .values_list('pk', 'padre_id'))
        _, asignadas, nombre_de = self._mapa()

        for usuario, unidades in asignadas.items():
            huerfanas = sorted(
                pk for pk in unidades
                if padre_de.get(pk) and padre_de[pk] not in unidades)
            if not huerfanas:
                continue

            detalle = '; '.join(
                f'{nombre_de.get(pk, pk)} (cuelga de {nombre_de.get(padre_de[pk], "?")})'
                for pk in huerfanas)
            yield HallazgoDetectado(
                object_id=str(usuario.pk),
                titulo=f'{usuario.username} · lleva una subunidad sin su unidad principal',
                detalle=('Tiene asignada una subunidad sin la unidad principal de '
                         'la que depende: ' + detalle + '.'),
                datos={
                    'moderador': usuario.username,
                    'subunidades_sueltas': detalle,
                },
                campo_formulario='unidades',
            )
