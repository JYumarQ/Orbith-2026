from django.apps import AppConfig


class RankingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ranking'
    verbose_name = 'Ranking Mensual Orbith'

    def ready(self):
        """Se engancha a las señales de Subsanación, igual que `progreso`:
        Subsanación no sabe que estos receptores existen."""
        from subsanacion.signals import analisis_finalizado, hallazgo_revisado

        from .receptores import al_finalizar_analisis, al_revisar_hallazgo

        hallazgo_revisado.connect(al_revisar_hallazgo, dispatch_uid='ranking_hallazgo_revisado')
        analisis_finalizado.connect(al_finalizar_analisis, dispatch_uid='ranking_analisis_finalizado')
