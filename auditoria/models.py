from django.db import models
from django.conf import settings
from .middleware import get_current_user

class Base(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(class)s_created",
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(class)s_updated",
        null=True, blank=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Obtiene el usuario actual guardado por el middleware
        user = get_current_user()
        # DEBUG: ver en consola el estado y usuario
        print(f"[AUDIT] {self.__class__.__name__} adding={self._state.adding}, pk={self.pk}, user={user}")

        if user:
            # Solo asignar created_by en inserciones nuevas
            if getattr(self._state, 'adding', False) and self.created_by is None:
                self.created_by = user
            # Siempre asignar updated_by
            self.updated_by = user

        super().save(*args, **kwargs)  # Llama al save original

# Al confirmar que funciona, puedes eliminar el print de DEBUG
