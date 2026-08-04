from django.apps import AppConfig


class SubsanacionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'subsanacion'
    verbose_name = 'Subsanación'

    def ready(self):
        """Descubre las reglas al arrancar.

        El autodescubrimiento solo IMPORTA los módulos de `reglas/`; las clases se
        registran solas al heredar de ReglaBase. Ninguna regla consulta la base de
        datos al importarse (en `ready()` todavía no se puede), y todas resuelven su
        modelo con `apps.get_model()` dentro de `ejecutar()`.

        Si una regla está mal declarada (falta un campo obligatorio o su código está
        repetido), el error salta AQUÍ, al arrancar, no en producción a mitad de un
        análisis.
        """
        from .reglas import autodescubrir_reglas

        autodescubrir_reglas()
