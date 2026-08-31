"""Backend de autenticación de Orbith.

Es el `ModelBackend` de Django con una sola diferencia: se niega a comprobar la
contraseña de una cuenta bloqueada por intentos fallidos.

Vive aquí, y no solo en `CustomAuthenticationForm`, porque el formulario del
login NO es la única puerta: el panel de administración de Django
(`/admin/login/`) usa su propio formulario. Si la comprobación viviera solo en el
formulario, bastaría atacar `/admin/login/` para saltarse el bloqueo por
completo. El backend es el punto por el que pasan todas las autenticaciones.
"""

from django.contrib.auth.backends import ModelBackend

from .models import IntentoAcceso


class BackendConBloqueo(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):
        # `username` puede llegar por kwargs si quien llama usa el nombre real
        # del campo (`USERNAME_FIELD`), como hace el admin de Django.
        if username is None:
            username = kwargs.get('username')

        if username and IntentoAcceso.bloqueado_hasta(username):
            # Devolver None (y no lanzar) es lo correcto: `authenticate()` espera
            # que un backend que no autoriza devuelva None y siga con el
            # siguiente. Quien deba explicar POR QUÉ es el formulario del login,
            # que sí puede mostrar un mensaje entendible.
            return None

        return super().authenticate(request, username=username, password=password, **kwargs)
