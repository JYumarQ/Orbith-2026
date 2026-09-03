from django.apps import AppConfig


class StrorganizativaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'strorganizativa'

    def ready(self):
        # Importar aquí, y no arriba, es el patrón obligado de Django: al
        # cargarse este módulo todavía no está listo el registro de modelos.
        # Ver `strorganizativa/signals.py` para qué mantiene sincronizado.
        from . import signals  # noqa: F401
