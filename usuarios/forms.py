from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.db.models import Count, Q
from django.forms.models import ModelChoiceIterator
from django.utils import timezone
import math

from .models import CustomUser, IntentoAcceso, PreferenciasUsuario
from django.contrib.auth.forms import AuthenticationForm
from contratos.models import CAlta
from core.validators import validar_imagen
from strorganizativa.models import UnidadOrganizativa


# =========================================================================
# ASIGNACION DE UNIDADES ORGANIZATIVAS A UN USUARIO
#
# Una subunidad NO se asigna por separado: se asigna su Unidad Principal, y las
# subunidades entran con ella. Así lo pidió el usuario, y además evita el caso
# absurdo que existía antes —un moderador con una subunidad suelta cuyo padre
# llevaba otra persona—.
#
# La restricción vive SOLO en esta pantalla. El Gestor de Plantilla y el resto
# de la aplicación siguen mostrando las subunidades con toda normalidad; lo que
# cambia es cómo se REPARTEN, no cómo se ven.
#
# Por qué se guardan también las hijas en la tabla, en vez de deducirlas al leer:
# `CustomUser.unidades` lo consultan quince sitios de diez módulos (cierres,
# contratos, dashboard, pre-nómina, solicitudes, notificaciones...). Guardando
# las hijas, todos siguen funcionando sin tocarlos. Y hay un motivo de negocio
# que lo decide: `cierres.permisos.puede_declarar` niega declarar una Unidad
# Principal —no tiene departamentos propios, su estado se deriva de sus hijas— y
# solo acepta unidades que el moderador tenga asignadas. Si las hijas no
# estuvieran en la tabla, el moderador no podría declarar NI el padre (regla
# estructural) NI las hijas (no asignadas): el cierre quedaría bloqueado.
#
# El precio de guardarlas es que hay que mantenerlas al día; de eso se encarga
# `strorganizativa/signals.py` cuando nace o se muda una subunidad.
# =========================================================================

ETIQUETA_PRINCIPALES = 'UNIDADES PRINCIPALES'
ETIQUETA_INDEPENDIENTES = 'UNIDADES INDEPENDIENTES'


def unidades_asignables():
    """Unidades que se pueden ELEGIR: las que no cuelgan de otra.

    Son las principales y las independientes. Las subunidades se excluyen a
    propósito: no se eligen, se heredan del padre.

    `annotate` precalcula cuántas subunidades arrastra cada principal, para que
    la etiqueta pueda decirlo sin lanzar una consulta por fila.
    """
    return (UnidadOrganizativa.objects
            .filter(padre__isnull=True)
            .select_related('tipo')
            .annotate(num_subunidades=Count('direcciones_hijas'))
            .order_by('descripcion'))


class _IteradorUnidadesAgrupadas(ModelChoiceIterator):
    """Separa el desplegable en dos grupos, para que se vea qué es cada cosa.

    Sin esto, principales e independientes salían mezcladas y con el mismo
    aspecto, y nada indicaba que elegir una principal arrastra a sus hijas.
    """

    def __iter__(self):
        principales, independientes = [], []
        for objeto in self.queryset:
            opcion = self.choice(objeto)
            if objeto.tipo_id and objeto.tipo.es_principal:
                principales.append(opcion)
            else:
                independientes.append(opcion)
        if principales:
            yield (ETIQUETA_PRINCIPALES, principales)
        if independientes:
            yield (ETIQUETA_INDEPENDIENTES, independientes)


def moderadores_por_unidad(excluir_pk=None):
    """Qué moderador lleva cada unidad: `{pk_unidad: username}`.

    `excluir_pk` deja fuera al usuario que se está editando: sus propias
    unidades no son un choque consigo mismo.
    """
    consulta = CustomUser.objects.filter(es_moderador=True, unidades__isnull=False)
    if excluir_pk:
        consulta = consulta.exclude(pk=excluir_pk)
    return dict(consulta.values_list('unidades__pk', 'username'))


class SelectUnidadesConDueno(forms.SelectMultiple):
    """Desplegable que APAGA las unidades que ya tiene otro moderador.

    Una unidad organizativa solo puede tener un moderador. Esa regla ya la
    imponía `validar_moderador_unico()`, pero solo al GUARDAR: el usuario elegía
    la unidad, rellenaba el resto y descubría el choque al enviar.

    Aquí se ve antes. Y se APAGAN en vez de ocultarlas a propósito: una lista a
    la que le faltan unidades sin decir por qué obliga al Administrador a ir
    usuario por usuario para averiguar quién la lleva. Apagada, la respuesta
    está escrita en la propia opción.

    La validación del servidor se mantiene: esto es la comodidad, no la barrera.
    """

    #: `{pk_unidad: username}` de las unidades que lleva OTRO moderador.
    ocupadas = None
    #: Unidades que el usuario editado YA tiene. Nunca se apagan, aunque
    #: figuren como ocupadas: apagar una opción marcada haría que el navegador
    #: no la enviara y el guardado se la llevaría por delante en silencio.
    ya_asignadas = None

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if not self.ocupadas:
            return opcion

        try:
            pk = int(getattr(value, 'value', value))
        except (TypeError, ValueError):
            return opcion   # la opción vacía

        dueno = self.ocupadas.get(pk)
        if dueno and pk not in (self.ya_asignadas or ()):
            opcion['attrs']['disabled'] = True
            opcion['label'] = f'{label}  ·  la lleva {dueno}'
        return opcion


class CampoUnidadesAsignables(forms.ModelMultipleChoiceField):
    """El selector de unidades de la pantalla de Usuarios.

    Se declara como campo explícito del formulario (y no se deja generar a
    Django) para que el Admin de Django herede exactamente las mismas reglas:
    los campos declarados tienen prioridad sobre los que genera el ModelAdmin.
    """

    iterator = _IteradorUnidadesAgrupadas

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('queryset', unidades_asignables())
        kwargs.setdefault('required', False)
        kwargs.setdefault('label', 'Unidades')
        kwargs.setdefault('widget', SelectUnidadesConDueno(attrs={
            'class': 'form-select select2',
            'data-placeholder': 'Buscar unidades...'}))
        super().__init__(*args, **kwargs)

    def marcar_ocupadas(self, usuario):
        """Prepara el widget para apagar lo que ya lleva otro moderador.

        Lo llaman los dos formularios de usuario desde su `__init__`; el campo
        por sí solo no puede saber a quién se está editando.
        """
        if not isinstance(self.widget, SelectUnidadesConDueno):
            return   # el Admin de Django puede haberlo sustituido
        pk = getattr(usuario, 'pk', None)
        self.widget.ocupadas = moderadores_por_unidad(excluir_pk=pk)
        self.widget.ya_asignadas = (
            set(usuario.unidades.values_list('pk', flat=True)) if pk else set())

    def label_from_instance(self, objeto):
        cuantas = getattr(objeto, 'num_subunidades', 0) or 0
        if cuantas:
            nombre = 'subunidad' if cuantas == 1 else 'subunidades'
            return '%s  (incluye %d %s)' % (objeto.descripcion, cuantas, nombre)
        return objeto.descripcion


def expandir_a_subunidades(cleaned):
    """Añade al conjunto elegido las subunidades de cada padre seleccionado.

    Se ejecuta ANTES de `validar_moderador_unico`, y ese orden no es un detalle:
    esa validación comprueba que ninguna unidad tenga ya otro moderador, y si
    expandiéramos después, un choque en una HIJA pasaría desapercibido y se
    guardaría una unidad con dos moderadores.

    Devuelve un queryset (no una lista) porque tanto `validar_moderador_unico`
    como el guardado del ManyToMany esperan poder seguir consultándolo.
    """
    seleccionadas = cleaned.get('unidades')
    if not seleccionadas:
        return cleaned
    elegidas = [u.pk for u in seleccionadas]
    cleaned['unidades'] = UnidadOrganizativa.objects.filter(
        Q(pk__in=elegidas) | Q(padre_id__in=elegidas))
    return cleaned


def validar_invariante_subunidades(formulario, cleaned):
    """Regla: una subunidad asignada SIEMPRE va acompañada de su padre.

    Segunda línea de defensa, y conviene decirlo con claridad: la primera es el
    queryset de `CampoUnidadesAsignables`, que ya rechaza cualquier subunidad
    enviada a mano en el POST con el mensaje estándar de Django. Esta
    comprobación existe para que la regla quede escrita y verificada, y para que
    unos datos incoherentes que llegaran por otra vía (una importación, el shell)
    se detecten al primer guardado en vez de propagarse en silencio.
    """
    unidades = cleaned.get('unidades')
    if not unidades:
        return cleaned
    presentes = {u.pk for u in unidades}
    huerfanas = sorted(u.descripcion for u in unidades
                       if u.padre_id and u.padre_id not in presentes)
    if huerfanas:
        formulario.add_error(
            'unidades',
            'Una subunidad no se asigna por separado: debe asignarse su Unidad '
            'Principal, y las subunidades entran con ella. Sin su unidad '
            'principal: ' + '; '.join(huerfanas) + '.')
    return cleaned


def validar_moderador_unico(formulario, cleaned):
    """Una Unidad Organizativa solo puede tener UN moderador.

    Regla global del negocio: un moderador puede llevar varias unidades, pero
    cada unidad tiene un único moderador responsable (más todos los
    administradores, que deciden sobre cualquiera de ellas por su rol y no por
    esta relación).

    Vive en una función suelta, y no en `CustomUser.clean()`, porque la relación
    `unidades` es ManyToMany: hasta que el usuario no está guardado no hay filas
    que consultar, así que el único punto donde se puede comprobar antes de
    escribir es el formulario, con los datos aún en `cleaned_data`.
    """
    if not cleaned.get('es_moderador'):
        return cleaned

    unidades = cleaned.get('unidades')
    if not unidades:
        return cleaned

    ocupadas = (CustomUser.objects
                .filter(es_moderador=True, unidades__in=unidades)
                .exclude(pk=formulario.instance.pk)
                .values_list('unidades__descripcion', 'username')
                .distinct())
    # `unidades__in` cruza con TODAS las unidades del otro moderador, no solo con
    # las del choque: hay que quedarse con las que se están intentando asignar.
    nombres = {u.descripcion for u in unidades}
    choques = sorted({f'{d} (ya la lleva {u})'
                      for d, u in ocupadas if d in nombres})
    if choques:
        formulario.add_error(
            'unidades',
            'Cada Unidad Organizativa solo puede tener un moderador. '
            'Ya tienen uno asignado: ' + '; '.join(choques) + '.')
    return cleaned


class CustomUserCreationForm(UserCreationForm):

    # Declarado, no generado: ver `CampoUnidadesAsignables`.
    unidades = CampoUnidadesAsignables()

    contrato = forms.ModelChoiceField(
        queryset=CAlta.objects.all().order_by('aspirante__nombre', 'aspirante__papellido'),
        widget=forms.Select(attrs={'class': 'form-select select2', 'data-placeholder': 'Buscar contrato...'}),
        label='Contrato',
        required=False
    )
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'es_admin', 'es_moderador', 'es_observador', 'contrato', 'unidades', 'is_active')
        labels = {
            'es_admin': 'Es Administrador',
            'es_moderador': 'Es Moderador',
            'es_observador': 'Es Observador',
            'is_active': 'Activo'
        }

        widgets = {
            'es_admin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_moderador': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_observador': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),

            'unidades': forms.SelectMultiple(attrs={'class': 'form-select select2', 'data-placeholder': 'Buscar unidades...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            elif isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'

            if 'password' in field_name:
                field.widget.attrs['type'] = 'password'

        # Apaga las unidades que ya lleva otro moderador (ver
        # `SelectUnidadesConDueno`). En el alta no hay instancia guardada, así
        # que se apagan todas las ocupadas: el usuario aún no lleva ninguna.
        self.fields['unidades'].marcar_ocupadas(self.instance)

        self.fields['contrato'].label_from_instance = lambda obj: (
            f"{obj.aspirante.nombre} {obj.aspirante.papellido} {obj.aspirante.sapellido}".strip()
        )

    def clean(self):
        cleaned = super().clean()
        # El orden importa: primero se añaden las hijas, y solo después se
        # comprueba que ninguna unidad tenga ya otro moderador. Al revés, un
        # choque en una subunidad no se detectaría.
        cleaned = expandir_a_subunidades(cleaned)
        cleaned = validar_invariante_subunidades(self, cleaned)
        return validar_moderador_unico(self, cleaned)

class CustomUserChangeForm(UserChangeForm):

    # Declarado, no generado: ver `CampoUnidadesAsignables`.
    unidades = CampoUnidadesAsignables()

    contrato = forms.ModelChoiceField(
        queryset=CAlta.objects.all().order_by('aspirante__nombre', 'aspirante__papellido'),
        widget=forms.Select(attrs={'class': 'form-select select2', 'data-placeholder': 'Buscar contrato...'}),
        label='Contrato',
        required=False
    )
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'es_admin', 'es_moderador', 'es_observador', 'contrato', 'unidades', 'is_active')

        labels = {
            'es_admin': 'Es Administrador',
            'es_moderador': 'Es Moderador',
            'es_observador': 'Es Observador',
            'is_active': 'Activo'
        }

    def clean_username(self):
        username = self.cleaned_data['username']
        if CustomUser.objects.exclude(pk=self.instance.pk).filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso.")
        return username


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control'})
        self.fields['email'].widget.attrs.update({'class': 'form-control'})
        self.fields['es_admin'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['es_moderador'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['es_observador'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['is_active'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['contrato'].widget.attrs.update({'class': 'form-select select2', 'data-placeholder': 'Buscar contrato...'})
        self.fields['unidades'].widget.attrs.update({'class': 'form-select select2', 'data-placeholder': 'Buscar unidades...'})
        # Apaga las unidades que ya lleva otro moderador (ver `SelectUnidadesConDueno`).
        self.fields['unidades'].marcar_ocupadas(self.instance)
        self.fields['contrato'].label_from_instance = lambda obj: (
            f"{obj.aspirante.nombre} {obj.aspirante.papellido} {obj.aspirante.sapellido}".strip()
        )
        

    def clean(self):
        cleaned = super().clean()
        # Mismo orden que en el formulario de alta: expandir, comprobar el
        # invariante y solo entonces mirar si alguna unidad ya tiene moderador.
        cleaned = expandir_a_subunidades(cleaned)
        cleaned = validar_invariante_subunidades(self, cleaned)
        return validar_moderador_unico(self, cleaned)

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()

class CustomPasswordChangeForm(forms.Form):
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label='Nueva contraseña'
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label='Confirmar nueva contraseña'
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)  # Si necesitas usar el usuario
        super().__init__(*args, **kwargs)

    def clean_new_password1(self):
        """Aplica AUTH_PASSWORD_VALIDATORS: las MISMAS reglas que el alta de
        usuario y el panel de administración de Django.

        Antes aquí vivían tres comprobaciones escritas a mano (8 caracteres,
        una mayúscula y un dígito) que se saltaban la lista de contraseñas
        comunes y el parecido con el nombre de usuario. El resultado era que
        este formulario ACEPTABA claves que el alta rechazaba: `Password1`
        cumple las tres y es de las contraseñas más usadas del mundo.

        Se pasa `self.user` —el usuario al que se le cambia la clave, que no es
        necesariamente quien está rellenando el formulario— para que el
        validador de parecido compare contra los datos correctos.
        """
        password = self.cleaned_data.get('new_password1')
        validate_password(password, self.user)
        return password

    def clean_new_password2(self):
        new_password1 = self.cleaned_data.get('new_password1')
        new_password2 = self.cleaned_data.get('new_password2')
        if new_password1 != new_password2:
            raise ValidationError("Las contraseñas no coinciden.")
        return new_password2

class AvatarForm(forms.ModelForm):
    """Subida o cambio de la foto de perfil del propio usuario."""

    TAMANO_MAXIMO_MB = 2

    # El campo se declara a mano para poder traducir los mensajes de Django.
    # El proyecto tiene LANGUAGE_CODE = 'en-us', así que los textos por defecto
    # ("Upload a valid image...") saldrían en inglés.
    avatar = forms.ImageField(
        required=True,
        label='Foto de perfil',
        error_messages={
            'required': "Debe seleccionar una imagen.",
            'invalid': "El archivo seleccionado no es una imagen válida.",
            'invalid_image': (
                "El archivo seleccionado no es una imagen válida o está dañado. "
                "Use una imagen JPG, PNG o WEBP."
            ),
            'missing': "No se recibió ningún archivo.",
            'empty': "El archivo enviado está vacío.",
        },
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg,image/png,image/webp',
        })
    )

    class Meta:
        model = CustomUser
        fields = ('avatar',)

    def clean_avatar(self):
        return validar_imagen(self.cleaned_data.get('avatar'), self.TAMANO_MAXIMO_MB)


class PreferenciasUsuarioForm(forms.ModelForm):
    """Preferencias personales de interfaz."""

    class Meta:
        model = PreferenciasUsuario
        fields = ('sidebar_colapsada', 'animaciones_activas')
        widgets = {
            'sidebar_colapsada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'animaciones_activas': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CustomAuthenticationForm(AuthenticationForm):
    """Formulario del login de Orbith.

    Añade sobre el de Django tres cosas, en este orden:

    1. **Bloqueo por intentos fallidos**, ANTES de comprobar la contraseña. Si la
       cuenta está bloqueada no se llama siquiera a `authenticate()`, así que un
       ataque por fuerza bruta deja de consumir tiempo de servidor y de sumar
       fallos nuevos.
    2. Que el usuario tenga un rol asignado.
    3. Que, si Orbith está en mantenimiento, solo entren los Administradores.

    El bloqueo real lo aplica `usuarios.backends.BackendConBloqueo`, que cubre
    también `/admin/login/`. Aquí se repite la comprobación con un único fin:
    poder EXPLICAR al usuario por qué no entra, en lugar de dejarle con un
    "usuario o contraseña incorrectos" que no le dice nada.
    """

    error_messages = {
        'invalid_login': 'Usuario o contraseña incorrectos. Recuerde que ambos campos distinguen mayúsculas y minúsculas.',
        'inactive': 'Esta cuenta está desactivada.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Los atributos se ponen aquí, y no a mano en la plantilla, para que el
        # formulario siga siendo la única fuente de verdad: la plantilla ya
        # dibuja `{{ form.username }}` y `{{ form.password }}`.
        self.fields['username'].widget.attrs.update({
            'class': 'floating-input',
            'placeholder': 'Usuario de red',
            'autofocus': True,
            # Sin esto, el teclado del móvil pone mayúscula inicial y el login
            # falla por el mismo motivo que advierte el mensaje de error.
            'autocapitalize': 'none',
            'autocorrect': 'off',
            'spellcheck': 'false',
            # Deja que el gestor de contraseñas del navegador rellene y guarde.
            'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            'class': 'floating-input',
            'placeholder': 'Contraseña',
            'autocomplete': 'current-password',
            # Lo usa el botón de "ver contraseña" de la plantilla.
            'id': 'id_password',
        })

    def clean(self):
        username = self.cleaned_data.get('username')

        if username:
            bloqueado_hasta = IntentoAcceso.bloqueado_hasta(username)
            if bloqueado_hasta:
                restante = bloqueado_hasta - timezone.now()
                minutos = max(1, math.ceil(restante.total_seconds() / 60))
                raise ValidationError(
                    f"Demasiados intentos fallidos. Por seguridad, esta cuenta "
                    f"no admite más intentos durante {minutos} minuto"
                    f"{'s' if minutos != 1 else ''}. Si no recuerda su "
                    f"contraseña, avise al Administrador.",
                    code='cuenta_bloqueada',
                )

        cleaned_data = super().clean()
        user = self.get_user()

        if user is not None:
            # Verificar que el usuario tenga al menos un rol activo
            if not (user.es_admin or user.es_moderador or user.es_observador):
                raise ValidationError(
                    "Tu usuario no tiene un rol asignado. Contacta al administrador.",
                    code='invalid_login'
                )

            # Modo de mantenimiento: solo los Administradores pueden entrar.
            # Reutiliza el mismo singleton que usuarios.middleware.ControlAccesoMiddleware.
            from configuracion.models import Configuracion
            if not user.es_admin:
                config = Configuracion.objects.first()
                if config and config.modo_mantenimiento:
                    raise ValidationError(
                        "Orbith se encuentra temporalmente en mantenimiento. "
                        "Por favor, intenta iniciar sesión más tarde.",
                        code='invalid_login'
                    )

        return cleaned_data
