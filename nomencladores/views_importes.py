"""Los cuatro nomencladores de importes del contrato.

Maestría, Doctorado, Instructor y CNCI. Son las cuantías que hasta ahora se
escribían a mano en cada contrato, una por una y sin ninguna fuente común.

POR QUÉ ESTÁ EN SU PROPIO MÓDULO Y NO EN `views.py`
---------------------------------------------------
`nomencladores/views.py` maneja sus tablas con un CRUD de JSON a medida y con el
editor en línea de `nomencladores_base.html`, un `switch` de 840 líneas que
despacha por el `id` de la tabla. Meter cuatro tablas más ahí significaría
alargar ese `switch` y arriesgar las que ya funcionan.

Estas cuatro siguen en cambio el patrón de las tarjetas de Pre-Nómina
(`prenomina/views.py`): cada tarjeta se trae su contenido por HTMX con
`hx-trigger="revealed"` —así el acordeón cerrado no cuesta ni una consulta— y
edita en un modal propio, respondiendo `204 + HX-Trigger`. Es el patrón más
reciente del proyecto y no toca nada de lo anterior.

DOS FORMAS DE NOMENCLADOR
-------------------------
Maestría y Doctorado son de VALOR ÚNICO: un solo importe cada uno, sin listado
ni alta ni baja. Su tarjeta enseña la cifra y un botón para cambiarla, y el
registro se crea solo la primera vez que se guarda (`get_or_create`).

Instructor y CNCI son LISTADOS: varias entradas, cada una con descripción e
importe, con alta, edición y baja.
"""

import json

from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from contratos.cambios_externos import MotivoRequerido, motivo_de_cambio, motivo_del_post

from usuarios.decorators import admin_required

from .forms import NImporteGradoCientificoForm, NPagoAdicionalForm
from .models import NImporteGradoCientifico, NPagoAdicional

PARCIAL_TARJETA_GRADO = 'pages/config/nomencladores/partials/tarjeta_grado.html'
PARCIAL_TARJETA_PAGOS = 'pages/config/nomencladores/partials/tarjeta_pagos_adicionales.html'
PARCIAL_MODAL = 'pages/config/nomencladores/partials/modal_importe.html'


#: Ficha de cada tarjeta. El slug de la URL se valida SIEMPRE contra este
#: diccionario, así que uno inventado no llega a tocar ningún modelo.
IMPORTES = {
    'maestria': {
        'clase': 'grado',
        'grado': NImporteGradoCientifico.GRADOS[0][0],   # 'MC'
        'titulo': 'Maestría',
        'subtitulo': 'IMPORTE ÚNICO',
        'icono': 'fas fa-user-graduate',
        'color': 'icon-purple',
        'evento': 'importeMaestriaActualizado',
        'ayuda': 'Se aplica automáticamente al contrato de todo trabajador '
                 'registrado como Máster.',
    },
    'doctorado': {
        'clase': 'grado',
        'grado': NImporteGradoCientifico.GRADOS[1][0],   # 'DC'
        'titulo': 'Doctorado',
        'subtitulo': 'IMPORTE ÚNICO',
        'icono': 'fas fa-award',
        'color': 'icon-blue',
        'evento': 'importeDoctoradoActualizado',
        'ayuda': 'Se aplica automáticamente al contrato de todo trabajador '
                 'registrado como Doctor.',
    },
    'instructor': {
        'clase': 'pagos',
        'tipo': NPagoAdicional.INSTRUCTOR,
        'titulo': 'Instructor',
        'singular': 'Pago de Instructor',
        'icono': 'fas fa-chalkboard-teacher',
        'color': 'icon-amber',
        'evento': 'pagosInstructorActualizado',
    },
    'cnci': {
        'clase': 'pagos',
        'tipo': NPagoAdicional.CNCI,
        'titulo': 'CNCI',
        'singular': 'Pago de CNCI',
        'icono': 'fas fa-certificate',
        'color': 'icon-green',
        'evento': 'pagosCnciActualizado',
    },
}


def _ficha(slug):
    try:
        return IMPORTES[slug]
    except KeyError:
        raise Http404('Nomenclador de importes desconocido.')


def _respuesta_htmx(mensaje, evento, icono='success'):
    """204 + `HX-Trigger`, el patrón que ya usan Pre-Nómina y Solicitudes.

    Sin cuerpo, porque quien repinta la tarjeta es el evento y no la respuesta:
    así la vista no necesita saber cómo estaba pintada la tarjeta.
    """
    respuesta = HttpResponse(status=204)
    respuesta['HX-Trigger'] = json.dumps({
        'closeModal': True,
        evento: True,
        'showMessage': {'icon': icono, 'text': mensaje},
    })
    return respuesta


@admin_required
def tarjeta(request, slug):
    """Contenido de una de las cuatro tarjetas."""
    ficha = _ficha(slug)

    if ficha['clase'] == 'grado':
        # `filter().first()` y no `get_or_create()`: mirar la pantalla no debe
        # escribir en la base de datos. Mientras no exista el registro, la
        # tarjeta enseña el aviso de nomenclador vacío, que es la verdad.
        registro = NImporteGradoCientifico.objects.filter(grado=ficha['grado']).first()
        return render(request, PARCIAL_TARJETA_GRADO, {
            'slug': slug, 'ficha': ficha, 'registro': registro,
        })

    return render(request, PARCIAL_TARJETA_PAGOS, {
        'slug': slug, 'ficha': ficha,
        'pagos': NPagoAdicional.objects.filter(tipo=ficha['tipo']),
    })


@admin_required
def guardar(request, slug, pk=None):
    """Modal de alta y edición. `GET` pinta el formulario, `POST` lo valida."""
    ficha = _ficha(slug)

    if ficha['clase'] == 'grado':
        instancia = NImporteGradoCientifico.objects.filter(grado=ficha['grado']).first()
        Formulario, singular = NImporteGradoCientificoForm, ficha['titulo']
    else:
        instancia = get_object_or_404(
            NPagoAdicional, pk=pk, tipo=ficha['tipo']) if pk else None
        Formulario, singular = NPagoAdicionalForm, ficha['singular']

    motivo_error = ''
    if request.method == 'POST':
        formulario = Formulario(request.POST, instance=instancia)
        if formulario.is_valid():
            objeto = formulario.save(commit=False)
            # El grado y el tipo los pone la tarjeta, no el usuario: es lo que
            # impide crear un segundo importe de Maestría, o un Instructor desde
            # la tarjeta de CNCI.
            if ficha['clase'] == 'grado':
                objeto.grado = ficha['grado']
            else:
                objeto.tipo = ficha['tipo']
            # Cambiar un importe en uso cambia lo que cobran esos contratos desde hoy:
            # hace falta un motivo para su histórico (decisión de RRHH, 23-10-2026).
            try:
                with transaction.atomic(), motivo_de_cambio(*motivo_del_post(request)):
                    objeto.save()
            except MotivoRequerido as e:
                motivo_error = str(e)
            else:
                verbo = 'actualizado' if instancia else 'creado'
                return _respuesta_htmx(f'{singular} {verbo}.', ficha['evento'])
    else:
        formulario = Formulario(instance=instancia)

    return render(request, PARCIAL_MODAL, {
        'form': formulario, 'slug': slug, 'ficha': ficha,
        'objeto': instancia, 'titulo': singular,
        'es_grado': ficha['clase'] == 'grado',
        'motivo_error': motivo_error,
        'motivo_valor': motivo_del_post(request)[0] if request.method == 'POST' else '',
        'motivo_error_humano': motivo_del_post(request)[1] if request.method == 'POST' else False,
    })


@admin_required
def eliminar(request, slug, pk):
    """Baja de una entrada de Instructor o de CNCI.

    Los importes por grado científico NO se borran: son de valor único y su
    tarjeta no ofrece papelera. Poner el importe a cero es la forma de anularlo,
    y así el nomenclador nunca queda «sin definir» por accidente.
    """
    ficha = _ficha(slug)
    if ficha['clase'] != 'pagos':
        raise Http404('Este nomenclador no admite eliminación.')

    objeto = get_object_or_404(NPagoAdicional, pk=pk, tipo=ficha['tipo'])
    etiqueta = objeto.descripcion

    # Una entrada que usan contratos no se borra (decisión de RRHH del 23-10-2026):
    # el contrato ya no guarda el importe, así que se quedaría sin él. PROTECT en
    # las dos claves de `CAlta` lo garantiza también fuera de esta pantalla.
    en_uso = (objeto.contratos_cnci.count() + objeto.contratos_instructor.count())
    if en_uso:
        contratos = 'contrato la usa' if en_uso == 1 else 'contratos la usan'
        return _respuesta_htmx(
            f'No se puede eliminar «{etiqueta}»: {en_uso} {contratos}. Asígneles otra '
            f'entrada antes, o edite su importe.', ficha['evento'], icono='warning')
    objeto.delete()
    return _respuesta_htmx(f'{ficha["singular"]} «{etiqueta}» eliminado.',
                           ficha['evento'])
