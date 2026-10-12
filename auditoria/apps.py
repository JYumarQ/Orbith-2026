from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auditoria'

    def ready(self):
        # Registro automático de crear/editar/eliminar en los modelos de
        # `auditoria.registro_automatico.MODELOS`.
        from auditoria import registro_automatico
        registro_automatico.conectar()
