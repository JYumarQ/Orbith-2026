"""Los Anexos 14, 14A y 14B pasan a llamarse 17, 17.1 y 17.2 (decisión de RRHH del
24-10-2026).

La tarea de la Guía «exportar_anexos» guarda en la base de datos su texto, sus
enlaces (`accesos`, `url_relacionada`) y las claves de sus partes, y cada
usuario guarda las partes que ya completó (`TareaGuiaParte.parte`). Todo eso
se traduce aquí, para que nadie pierda su avance y no quede ningún «14» a la
vista. Las URL nuevas son las de `informes_anexo/urls.py`.
"""

import re

from django.db import migrations

PARTES = {'14': '17', '14a': '17_1', '14b': '17_2'}

#: Del más concreto al más general, como en el código.
TEXTO = [
    (r'/anexo14b/', '/anexo17_2/'), (r'/anexo14a/', '/anexo17_1/'), (r'/anexo14/', '/anexo17/'),
    (r'anexo14b', 'anexo17_2'), (r'anexo14a', 'anexo17_1'), (r'anexo14(?!\d)', 'anexo17'),
    (r'\b14[- ]?B\b', '17.2'), (r'\b14[- ]?A\b', '17.1'),
    (r'(Anexos?\s+)14\b', r'\g<1>17'),
]

CAMPOS = ('titulo', 'descripcion', 'instrucciones', 'accesos', 'url_relacionada')


def _traducir(texto):
    for patron, sustituto in TEXTO:
        texto = re.sub(patron, sustituto, texto)
    return texto


def a_17(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuiaParte = apps.get_model('progreso', 'TareaGuiaParte')
    for tarea in TareaGuia.objects.filter(codigo='exportar_anexos'):
        for campo in CAMPOS:
            setattr(tarea, campo, _traducir(getattr(tarea, campo) or ''))
        tarea.partes = ','.join(PARTES.get(p.strip(), p.strip())
                                for p in (tarea.partes or '').split(',') if p.strip())
        tarea.save()
        for viejo, nuevo in PARTES.items():
            TareaGuiaParte.objects.filter(tarea=tarea, parte=viejo).update(parte=nuevo)


def a_14(apps, schema_editor):
    """Vuelta atrás: solo las claves de las partes y los enlaces, que son los que
    harían fallar la Guía con el código anterior. El texto se deja en 17."""
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuiaParte = apps.get_model('progreso', 'TareaGuiaParte')
    inverso = {v: k for k, v in PARTES.items()}
    for tarea in TareaGuia.objects.filter(codigo='exportar_anexos'):
        tarea.partes = ','.join(inverso.get(p.strip(), p.strip())
                                for p in (tarea.partes or '').split(',') if p.strip())
        for campo in ('accesos', 'url_relacionada'):
            valor = getattr(tarea, campo) or ''
            for viejo, nuevo in (('anexo17_2', 'anexo14b'), ('anexo17_1', 'anexo14a'),
                                 ('anexo17', 'anexo14')):
                valor = valor.replace(viejo, nuevo)
            setattr(tarea, campo, valor)
        tarea.save()
        for nuevo, viejo in inverso.items():
            TareaGuiaParte.objects.filter(tarea=tarea, parte=nuevo).update(parte=viejo)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0038_guia_solicitudes_accesos'),
    ]

    operations = [
        migrations.RunPython(a_17, a_14),
    ]
