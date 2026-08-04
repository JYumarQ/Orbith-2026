"""Validadores reutilizables entre apps.

El proyecto tiene LANGUAGE_CODE = 'en-us', así que los mensajes de validación
por defecto de Django ("Upload a valid image...") saldrían en inglés. Estas
funciones centralizan la validación de imágenes subidas por el usuario
(avatar, adjuntos de reportes de problemas) con mensajes en español, en vez
de repetir la misma lógica en cada formulario.
"""
from django import forms

EXTENSIONES_IMAGEN_PERMITIDAS = ('.jpg', '.jpeg', '.png', '.webp')


def validar_imagen(fichero, tamano_maximo_mb=2):
    """Valida tamaño y extensión de una imagen subida por el usuario.

    Lanza forms.ValidationError con un mensaje en español si no es válida.
    No valida que sea una imagen de verdad (magic bytes): eso ya lo hace
    forms.ImageField al decodificarla con Pillow antes de llegar aquí.
    """
    if not fichero:
        return fichero

    # Si el valor es el fichero ya guardado (edición sin cambios), no tiene
    # 'size' utilizable de la misma forma que un fichero recién subido.
    if not hasattr(fichero, 'size'):
        return fichero

    limite = tamano_maximo_mb * 1024 * 1024
    if fichero.size > limite:
        raise forms.ValidationError(
            f"La imagen no puede superar los {tamano_maximo_mb} MB. "
            f"La seleccionada ocupa {fichero.size / (1024 * 1024):.1f} MB."
        )

    nombre = (getattr(fichero, 'name', '') or '').lower()
    if not nombre.endswith(EXTENSIONES_IMAGEN_PERMITIDAS):
        raise forms.ValidationError(
            "Formato no admitido. Use una imagen JPG, PNG o WEBP."
        )

    return fichero
