"""Formatos de Orbith en español (19-11-2026, decisión del usuario).

Orbith pasa a `LANGUAGE_CODE = 'es'` para que todo lo que escribe Django (errores de
formulario, panel de administración…) salga en español. Pero el español de Django
trae también sus formatos, y algunos romperían Orbith. Este archivo los sustituye
(`FORMAT_MODULE_PATH` en core/settings.py); lo que no está aquí lo pone Django.

* Fechas que se ven: dd/mm/aaaa, como el resto de Orbith (antes «Nov. 18, 2026»).
* Fechas que viajan en los formularios: la primera de `DATE_INPUT_FORMATS` es la que
  usan los campos al pintarse, y los `<input type="date">` del navegador solo
  entienden aaaa-mm-dd. Con la de Django (dd/mm/aaaa) aparecerían vacíos al editar.
* Decimales con punto, como siempre: lo esperan el código de las pantallas, los
  datos que leen los importes y los Excel. El de Django pondría coma.
"""

DATE_FORMAT = 'd/m/Y'
SHORT_DATE_FORMAT = 'd/m/Y'
DATETIME_FORMAT = 'd/m/Y H:i'
SHORT_DATETIME_FORMAT = 'd/m/Y H:i'
TIME_FORMAT = 'H:i'
YEAR_MONTH_FORMAT = r'F \d\e Y'
MONTH_DAY_FORMAT = r'j \d\e F'
FIRST_DAY_OF_WEEK = 1  # lunes

DATE_INPUT_FORMATS = ['%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']
DATETIME_INPUT_FORMATS = [
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M',
    '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M',
]
TIME_INPUT_FORMATS = ['%H:%M:%S', '%H:%M:%S.%f', '%H:%M']

DECIMAL_SEPARATOR = '.'
THOUSAND_SEPARATOR = ','
NUMBER_GROUPING = 3
