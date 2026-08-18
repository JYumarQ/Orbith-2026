from django.apps import AppConfig


class ProgresoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'progreso'
    verbose_name = 'Guía de Orbith'

    def ready(self):
        """Conecta los receptores a las señales ya existentes de Subsanación.

        Es `progreso` quien se engancha a las señales de `subsanacion`, no al
        revés: Subsanación no importa `progreso` ni sabe que estos receptores
        existen, así que pueden desconectarse sin tocar nada allí. Mismo
        patrón que ya usa `notificaciones/apps.py`.
        """
        from subsanacion.signals import analisis_finalizado, hallazgo_revisado

        from .receptores import al_finalizar_analisis, al_revisar_hallazgo

        hallazgo_revisado.connect(al_revisar_hallazgo, dispatch_uid='progreso_hallazgo_revisado')
        analisis_finalizado.connect(al_finalizar_analisis, dispatch_uid='progreso_analisis_finalizado')
