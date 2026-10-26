"""Rutas de Configuración.

Parámetros Generales y Familias de Cargos son pantallas de administración: contienen los
nomencladores de los que depende todo el sistema (cargos, escalas salariales, tipos de
contrato, provincias...). Un Moderador no debe entrar, y por eso existe el flujo de
Solicitud para lo único que sí puede pedir de aquí: añadir o editar un NCargo.

Antes iban con `login_required`, así que cualquier usuario autenticado podía abrirlas
escribiendo la URL aunque el menú lateral no las mostrara.
"""

from django.urls import path

from usuarios.permisos_especiales import permiso_required

# Administrador, o Moderador con el permiso especial «Nomencladores y parámetros»
# (25-10-2026, ver `usuarios/permisos_especiales.py`).
admin_required = permiso_required('nomencladores')

from . import views

urlpatterns = [
    path('parametros/', admin_required(views.ParametrosGeneralesView.as_view()), name='parametros'),
    path('configuracion/actualizar-salario/', admin_required(views.actualizar_salario), name='actualizar_salario'),
    path('familias-cargo/', admin_required(views.FamiliasCargoView.as_view()), name='familias_cargo'),
]
