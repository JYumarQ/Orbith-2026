from django.db import models

class PlanMensualRegistro(models.Model):
    mes = models.CharField(max_length=2)
    anno = models.CharField(max_length=4)
    ueb_id = models.CharField(max_length=10, null=True, blank=True)
    familia_id = models.CharField(max_length=10, null=True, blank=True)
    valor = models.IntegerField(default=0)

    class Meta:
        unique_together = ('mes', 'anno', 'ueb_id', 'familia_id')