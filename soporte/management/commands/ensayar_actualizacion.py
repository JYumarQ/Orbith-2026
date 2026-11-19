"""Ensayo de actualización en un proceso aparte (lo lanza el admin, ver
`core.actualizacion.lanzar_ensayo`). No toca el Orbith en uso ni su base."""

from django.core.management.base import BaseCommand

from core.actualizacion import ensayar


class Command(BaseCommand):
    help = 'Ensaya un paquete de actualización de Orbith sin tocar la versión en uso.'

    def add_arguments(self, parser):
        parser.add_argument('paquete', help='Ruta del paquete orbith.tar.gz subido.')
        parser.add_argument('registro', help='Nombre del fichero de registro (ensayo-<fecha>.log).')

    def handle(self, *args, **options):
        ensayar(options['paquete'], options['registro'])
