"""Validadores de contraseña de Orbith, con los mensajes en español.

POR QUÉ EXISTE ESTE FICHERO
---------------------------
Django trae cuatro validadores muy buenos —el de contraseñas comunes compara
contra una lista de 20.000 claves reales— pero sus mensajes salen en el idioma
de `LANGUAGE_CODE`, que en este proyecto es 'en-us'. El usuario veía
"This password is too common." al dar de alta una cuenta.

Cambiar `LANGUAGE_CODE` a 'es' lo traduciría de golpe, pero se llevaría por
delante también el formato de fechas y números de TODO el proyecto (pasarían a
d/m/aaaa), que es un cambio mucho mayor y con riesgo en formularios y tests que
hoy asumen el formato en inglés. Así que aquí se hace lo contrario: se reutiliza
la lógica de Django intacta y solo se sustituye el texto.

EL PROBLEMA DE FONDO QUE RESUELVE
---------------------------------
Antes cada sitio donde se fijaba una contraseña aplicaba reglas DISTINTAS:

* el alta de usuario usaba los validadores de Django (en inglés);
* «Mi Perfil» usaba tres comprobaciones escritas a mano en
  `CustomPasswordChangeForm` (8 caracteres, mayúscula y dígito) que se saltaban
  la lista de contraseñas comunes y el parecido con el nombre de usuario.

La consecuencia práctica: el cambio de contraseña ACEPTABA claves que el alta
rechazaba. `Password1` tiene ocho caracteres, mayúscula y número, así que pasaba
el cambio sin problema pese a ser una de las contraseñas más usadas del mundo.

Al declararse en `AUTH_PASSWORD_VALIDATORS`, estas reglas se aplican solas en
los TRES caminos —alta, cambio propio y panel de administración de Django— sin
que ninguno tenga que acordarse de invocarlas.

IMPORTANTE
----------
Los validadores solo actúan al FIJAR una contraseña. Las que ya existen no se
revisan ni se invalidan: quien tenga hoy una clave débil seguirá entrando con
ella hasta que la cambie. Es el comportamiento normal y deliberado; no hay forma
de auditar las existentes porque se guardan cifradas y son irrecuperables por
diseño.
"""

from django.contrib.auth import password_validation as django_validators
from django.core.exceptions import ValidationError


class LongitudMinima(django_validators.MinimumLengthValidator):
    """Longitud mínima. Se reimplementa entero porque el mensaje lleva el número
    dentro y traducirlo a posteriori sería más enredado que escribirlo."""

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                f"La contraseña debe tener al menos {self.min_length} caracteres.",
                code='password_too_short',
                params={'min_length': self.min_length},
            )

    def get_help_text(self):
        return f"La contraseña debe tener al menos {self.min_length} caracteres."


class NoParecidaAlUsuario(django_validators.UserAttributeSimilarityValidator):
    """Impide usar como contraseña algo demasiado parecido al propio nombre de
    usuario o al correo.

    La comparación la sigue haciendo Django (usa `SequenceMatcher`, no una
    igualdad simple): aquí solo se atrapa su error y se relanza en español. Se
    prefiere esto a reimplementar el algoritmo, que es justo la clase de copia
    que acaba divergiendo del original.
    """

    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "La contraseña se parece demasiado a sus datos de usuario. "
                "Elija una que no contenga su nombre de usuario ni su correo.",
                code='password_too_similar',
            )

    def get_help_text(self):
        return "La contraseña no puede parecerse a sus datos de usuario."


class NoDemasiadoComun(django_validators.CommonPasswordValidator):
    """Rechaza las contraseñas de la lista de 20.000 más usadas que trae Django."""

    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "Esta contraseña es demasiado común y sería de las primeras que "
                "probaría un atacante. Elija otra.",
                code='password_too_common',
            )

    def get_help_text(self):
        return "La contraseña no puede ser una de las más usadas."


class NoSoloNumeros(django_validators.NumericPasswordValidator):
    """Rechaza las contraseñas formadas solo por dígitos."""

    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "La contraseña no puede estar formada solo por números.",
                code='password_entirely_numeric',
            )

    def get_help_text(self):
        return "La contraseña no puede estar formada solo por números."


class MayusculaYDigito:
    """Al menos una letra mayúscula y al menos un número.

    Django no trae esta regla, pero Orbith ya la exigía en el cambio de
    contraseña. Se conserva —y ahora se aplica también al alta y al panel de
    administración, donde antes no llegaba— para que el cambio no relaje
    ninguna exigencia que hoy ya existe.

    Los dos avisos van por separado a propósito: decirle a alguien «falta una
    mayúscula» es accionable; «la contraseña no es válida» no lo es.
    """

    def validate(self, password, user=None):
        if not any(caracter.isupper() for caracter in password):
            raise ValidationError(
                "La contraseña debe tener al menos una letra mayúscula.",
                code='password_sin_mayuscula',
            )
        if not any(caracter.isdigit() for caracter in password):
            raise ValidationError(
                "La contraseña debe tener al menos un número.",
                code='password_sin_digito',
            )

    def get_help_text(self):
        return "La contraseña debe tener al menos una letra mayúscula y un número."
