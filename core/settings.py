import os
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# Definimos el esquema (NombreVariable=(Tipo, ValorPorDefecto)) al instanciar
env = environ.Env(
    DEBUG=(bool, True)
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
    'soporte', 'subsanacion',
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

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
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
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
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


# Asegúrate de haberlo añadido al final de settings.py
LOGIN_URL = 'login'  # Redirige a login si no autenticado
LOGOUT_REDIRECT_URL = 'login'  # A dónde llevar al cerrar sesión
LOGIN_REDIRECT_URL = '/'  # Redirige a la página principal



