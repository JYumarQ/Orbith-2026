"""Firmantes de los Anexos 17 elegidos en las preferencias de cada usuario (25-10-2026).

Antes Orbith buscaba a los firmantes por el NOMBRE del cargo («Director General»,
«Director de Capital Humano»), fijado en el código. En la empresa esos nombres no
están en el nomenclador de cargos, y cada unidad puede tener firmantes distintos.
Ahora cada Administrador o Moderador elige, en Configuración, qué PLAZA de cuadro
firma «Propuesto por» y cuál «Aprobado por», y el título que se imprime.

Orden al exportar un Anexo:
1. si se eligió a mano una persona en la pantalla del Anexo, esa;
2. si el usuario configuró la plaza, quien la ocupe hoy (con su título);
3. si no, lo de siempre: el cargo por su nombre (`views._resolver_firmante`).
"""

from contratos.models import CAlta
from strorganizativa.jerarquia import expandir
from strorganizativa.models import CargoPlantilla
from usuarios.alcance import ve_toda_la_empresa

#: Categorías de cuadro: solo sus plazas pueden firmar.
CATEGORIAS_DE_CUADRO = ('CDI', 'CEJ')

FIRMAS = {
    'propuesto': {'campo': 'firma_propuesto', 'titulo': 'firma_propuesto_titulo',
                  'etiqueta': 'Propuesto por', 'ejemplo': 'Directora de Capital Humano'},
    'aprobado': {'campo': 'firma_aprobado', 'titulo': 'firma_aprobado_titulo',
                 'etiqueta': 'Aprobado por', 'ejemplo': 'Director General'},
}


def plazas_para_firmar(usuario):
    """Las plazas de cuadro que este usuario puede elegir: todas para quien ve toda
    la empresa; las de sus unidades (con sus subunidades) para el Moderador."""
    plazas = (CargoPlantilla.objects
              .filter(ncargo__cat_ocupacional__in=CATEGORIAS_DE_CUADRO)
              .select_related('ncargo', 'departamento__unidad_organizativa')
              .order_by('departamento__unidad_organizativa__orden_informe',
                        'departamento__orden_informe', 'orden_informe'))
    if not ve_toda_la_empresa(usuario):
        unidades = expandir([str(pk) for pk in usuario.unidades.values_list('pk', flat=True)])
        plazas = plazas.filter(departamento__unidad_organizativa_id__in=unidades)
    return plazas


def ocupantes(plaza):
    return list(CAlta.objects.filter(cargo=plaza, aspirante__estado='ACTIVO')
                .select_related('aspirante').order_by('fecha_alta'))


def opciones(usuario):
    """`[(pk, texto)]` para el desplegable: cargo · departamento · unidad — quien la ocupa."""
    salida = []
    for plaza in plazas_para_firmar(usuario):
        quienes = ocupantes(plaza)
        if not quienes:
            ocupa = 'vacante'
        elif len(quienes) == 1:
            ocupa = str(quienes[0].aspirante)
        else:
            ocupa = '%d ocupantes' % len(quienes)
        salida.append((plaza.pk, '%s · %s · %s — %s' % (
            plaza.ncargo.descripcion, plaza.departamento.descripcion,
            plaza.departamento.unidad_organizativa.descripcion, ocupa)))
    return salida


def titulo_para(titulo, aspirante):
    """El título escrito por el usuario, en femenino si firma una mujer y el título
    empieza por «Director »/«Jefe »."""
    titulo = (titulo or '').strip()
    if aspirante is not None and aspirante.sexo == 'F':
        for masculino, femenino in (('Director ', 'Directora '), ('Jefe ', 'Jefa ')):
            if titulo.startswith(masculino):
                return femenino + titulo[len(masculino):]
    return titulo


def firmante_configurado(usuario, cual):
    """El firmante que el usuario eligió en sus preferencias, en el mismo formato que
    `views._resolver_firmante`, o None si no configuró ninguno."""
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return None
    preferencias = usuario.obtener_preferencias()
    plaza = getattr(preferencias, FIRMAS[cual]['campo'])
    if plaza is None:
        return None
    quienes = ocupantes(plaza)
    aspirante = quienes[0].aspirante if len(quienes) == 1 else None
    titulo = getattr(preferencias, FIRMAS[cual]['titulo']) or plaza.ncargo.descripcion
    return {
        'aspirante': aspirante,
        'titulo': titulo_para(titulo, aspirante),
        'cargo_existe': True,
        'es_manual': False,
        'ambiguo': len(quienes) > 1,
        'configurado': True,
        'plaza': plaza,
    }
