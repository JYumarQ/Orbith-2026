from django.apps import AppConfig


class NotificacionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notificaciones'

    def ready(self):
        """Conecta el receptor que avisa a los administradores de una crítica nueva.

        Es `notificaciones` quien se engancha a la señal de `subsanacion`, no al
        revés: Subsanación no importa `notificaciones` ni sabe que este receptor
        existe, así que puede desconectarse sin tocar nada allí.
        """
        from subsanacion.signals import analisis_finalizado

        from .receptores import avisar_criticas_nuevas

        analisis_finalizado.connect(avisar_criticas_nuevas, dispatch_uid='notificaciones_avisar_criticas')
