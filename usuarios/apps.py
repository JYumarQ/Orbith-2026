from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'

    def ready(self):
        # Importar el módulo es lo que conecta los @receiver. Sin esta línea los
        # accesos no quedarían auditados y nadie se daría cuenta.
        from . import signals  # noqa: F401
