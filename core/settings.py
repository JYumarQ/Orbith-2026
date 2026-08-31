import os
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# Definimos el esquema (NombreVariable=(Tipo, ValorPorDefecto)) al instanciar
# El valor por defecto de DEBUG es False A PROPÓSITO: si `core/.env` se pierde o
# se despliega sin él, el sistema debe arrancar en modo seguro. Con `True` como
# defecto, producción mostraría trazas completas (rutas de ficheros, versiones,
# fragmentos de configuración) ante cualquier error. El entorno local define
# DEBUG=True en su propio .env, así que el desarrollo no cambia.
env = environ.Env(
    DEBUG=(bool, False)
)
env.read_env(BASE_DIR / "core" / ".env", encoding="utf-8")


SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')  # Limpio y sin errores: toma el tipo y default definidos arriba

#SECRET_KEY = 'django-insecure-ee#a$ki#9h1=@&4o8u^e4aih+0g-=c5h+yrx0n2i-bgiwjnxe_'
#DEBUG = True
ALLOWED_HOSTS = ['*']
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

AUTH_USER_MODEL = 'usuarios.CustomUser'

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'import_export',
    'django_htmx',
    #?APLICACIONES
    'bolsa', 'contratos', 'strorganizativa', 'nomencladores',
    'notificaciones', 'dashboard', 'configuracion', 'usuarios', 'auditoria',
    'solicitudes', 'informes',  'informe_inteligente', 'informes_anexo',
    'soporte', 'subsanacion', 'cierres', 'progreso', 'prenomina',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.LoginRequiredMiddleware',
    'auditoria.middleware.CurrentUserMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Después de MessageMiddleware a propósito: ver docstring de
    # DeteccionExportacionMiddleware (necesita messages.info() disponible).
    'progreso.middleware.DeteccionExportacionMiddleware',
    # Al final a propósito: ver docstring de ControlAccesoMiddleware.
    'usuarios.middleware.ControlAccesoMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.orbith',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

# Las credenciales viven en `core/.env` (ignorado por git). Antes estaban aquí en
# texto plano y viajaban en cada commit.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DATABASE_NAME'),
        'USER': env('DATABASE_USER'),
        'PASSWORD': env('DATABASE_PASSWORD'),
        'HOST': env('DATABASE_HOST'),
        'PORT': env('DATABASE_PORT'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

# Reglas de contraseña. Apuntan a `usuarios.validadores` y no directamente a los
# de Django porque estos emiten sus mensajes en el idioma de LANGUAGE_CODE
# ('en-us' aquí), y en Orbith todo mensaje va en español: al dar de alta una
# cuenta se leía "This password is too common.". Las subclases reutilizan la
# lógica de Django intacta —incluida la lista de 20.000 contraseñas comunes— y
# solo sustituyen el texto. Ver el docstring de ese módulo.
#
# Declararlas AQUÍ es lo que hace que se apliquen solas en los TRES sitios donde
# se fija una contraseña: el alta de usuario, el cambio desde «Mi Perfil» y el
# panel de administración de Django. Antes cada uno aplicaba reglas distintas, y
# el cambio aceptaba claves que el alta rechazaba (`Password1` entre ellas).
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'usuarios.validadores.NoParecidaAlUsuario'},
    {
        'NAME': 'usuarios.validadores.LongitudMinima',
        # Explícito aunque coincida con el defecto de Django: es el número que
        # aparece en el mensaje que lee el usuario.
        'OPTIONS': {'min_length': 8},
    },
    {'NAME': 'usuarios.validadores.NoDemasiadoComun'},
    {'NAME': 'usuarios.validadores.NoSoloNumeros'},
    # Regla propia de Orbith: Django no la trae. Ya se exigía en el cambio de
    # contraseña; ahora alcanza también al alta y al panel de administración.
    {'NAME': 'usuarios.validadores.MayusculaYDigito'},
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Havana'
USE_I18N = True
USE_TZ = True


# Configuración de archivos estáticos y multimedia
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# OJO: `STATICFILES_STORAGE` (el ajuste antiguo) fue ELIMINADO en Django 5.1 y
# este proyecto va por Django 5.2, así que estaba ahí sin efecto ninguno: el
# almacenamiento real era el `StaticFilesStorage` de serie. Consecuencias en
# producción, que es donde se notaba la lentitud al pulsar en la barra lateral:
#
#   * Sin precompresión: WhiteNoise servía los ficheros en crudo. Solo
#     `vendor/css/core.css` son 959 KB que comprimidos bajan a ~110 KB.
#   * Sin nombres con hash: WhiteNoise no puede marcar los ficheros como
#     "inmutables", así que el navegador revalidaba los ~30 estáticos de cada
#     página EN CADA NAVEGACIÓN. Con hash pasan a `Cache-Control: immutable`
#     durante un año y, de la segunda página en adelante, no se descarga nada.
#
# El almacenamiento con manifiesto exige que todo `{% static %}` apunte a un
# fichero que exista: si falta uno, `collectstatic` falla en el despliegue en
# lugar de dejar un 404 silencioso en producción. `core.storages` es ese
# almacenamiento de WhiteNoise con una única excepción documentada: los mapas de
# código (`*.map`), que varias librerías de terceros mencionan sin incluirlos.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "core.storages.AlmacenEstaticosOrbith",
    },
}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / "media"

# El default de Django (2.5 MB) se queda corto para el reporte de problemas,
# que admite hasta 4 imágenes de 2 MB cada una más el texto del mensaje.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# core/settings.py

if DEBUG:
    # Desarrollo (local)
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

    # Tunel temporal (cloudflared) para que alguien fuera de la red revise el
    # portatil sin publicarlo permanentemente. Cloudflare termina el HTTPS en
    # su borde y reenvia a este runserver por HTTP simple, asi que:
    #
    # 1. Django recibe un Origin "https://..." en una peticion que el ve como
    #    insegura -> sin CSRF_TRUSTED_ORIGINS la verificacion de CSRF falla
    #    con "Origin checking failed", que es exactamente el error que
    #    aparecio al usar el tunel.
    # 2. SECURE_PROXY_SSL_HEADER hace que Django confie en el encabezado
    #    X-Forwarded-Proto que cloudflared SI envia, y trate la peticion como
    #    HTTPS de verdad (request.is_secure() == True).
    #
    # El comodin cubre cualquier subdominio de trycloudflare.com: un "quick
    # tunnel" genera uno aleatorio distinto cada vez que se arranca. No afecta
    # a produccion: esta rama solo se activa con DEBUG=True.
    CSRF_TRUSTED_ORIGINS = ['https://*.trycloudflare.com']
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    # Producción
    ALLOWED_HOSTS = ['orbith.eleccmg.une.cu', 'localhost']  # sin "https://"

    CSRF_TRUSTED_ORIGINS = ['https://orbith.eleccmg.une.cu']

    # Sin EMAIL_HOST configurado en ningún sitio y sin un solo send_mail() en
    # todo el proyecto, el backend SMTP era configuración muerta que solo
    # sugería una salida a Internet inexistente. Producción usa el mismo
    # backend de consola fijado arriba: coherente con el requisito de
    # funcionar 100% offline en la intranet.

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_REDIRECT_EXEMPT = []
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # SOLO Postgres en prod (sin duplicados)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DATABASE_NAME'),
            'USER': env('DATABASE_USER'),
            'PASSWORD': env('DATABASE_PASSWORD'),
            'HOST': env('DATABASE_HOST'),
            'PORT': env('DATABASE_PORT'),
        }
    }


# =========================================================================
# AUTENTICACIÓN Y SESIÓN
# =========================================================================

# `ModelBackend` con bloqueo por intentos fallidos. Se declara como backend (y no
# solo dentro del formulario del login) para que el bloqueo cubra TODAS las
# puertas, incluida la del panel de administración de Django.
AUTHENTICATION_BACKENDS = [
    'usuarios.backends.BackendConBloqueo',
]

# Techo absoluto de la sesión. La caducidad que se nota en el día a día es la de
# INACTIVIDAD (60 minutos), que aplica `usuarios.middleware.ControlAccesoMiddleware`;
# esto es solo el límite máximo que ninguna sesión puede superar aunque se use sin
# parar. Antes se quedaba en el valor por defecto de Django: DOS SEMANAS.
SESSION_COOKIE_AGE = 12 * 60 * 60  # 12 horas

# La cookie muere al cerrar el navegador. En PCs compartidas es la diferencia
# entre que el siguiente que se siente entre en Recursos Humanos o no.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# NO se activa SESSION_SAVE_EVERY_REQUEST: haría que el sondeo automático del
# contador de notificaciones (cada 5 minutos, ver templates/base/navbar.html)
# renovara la sesión para siempre mientras hubiera una pestaña abierta, anulando
# por completo la caducidad por inactividad.

SESSION_COOKIE_HTTPONLY = True   # JavaScript no puede leer la cookie de sesión
SESSION_COOKIE_SAMESITE = 'Lax'  # no viaja en peticiones desde otros sitios
CSRF_COOKIE_SAMESITE = 'Lax'

# Asegúrate de haberlo añadido al final de settings.py
LOGIN_URL = 'login'  # Redirige a login si no autenticado
LOGOUT_REDIRECT_URL = 'login'  # A dónde llevar al cerrar sesión
LOGIN_REDIRECT_URL = '/'  # Redirige a la página principal



