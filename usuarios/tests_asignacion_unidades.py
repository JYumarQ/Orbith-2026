"""Una subunidad no se asigna por separado: se asigna su Unidad Principal.

Antes, el selector de la pantalla de Usuarios ofrecía las tres clases de unidad
mezcladas y con el mismo aspecto, así que nada impedía dar a un moderador una
subunidad suelta —cuyo padre podía llevar otra persona— ni indicaba que elegir
una principal tuviera consecuencia alguna sobre sus hijas.

Estas pruebas fijan las cuatro piezas de la regla:

1. qué se OFRECE (solo unidades sin padre, agrupadas y con el conteo);
2. qué se GUARDA al elegir un padre (el padre y todas sus hijas);
3. qué se RECHAZA (una subunidad enviada a mano, y un padre cuya hija ya tiene
   otro moderador);
4. qué pasa DESPUÉS (una subunidad nueva o mudada se reparte sola).
"""

from django.test import TestCase

from nomencladores.models import NTipoUnidadOrganizativa
from strorganizativa.models import UnidadOrganizativa

from .forms import (ETIQUETA_INDEPENDIENTES, ETIQUETA_PRINCIPALES,
                    CustomUserChangeForm, CustomUserCreationForm)
from .models import CustomUser

CLAVE = 'Orbith.Segura.2026'


class BaseEstructura(TestCase):
    """Estructura mínima que reproduce la real: un padre con hijas y una suelta."""

    @classmethod
    def setUpTestData(cls):
        cls.tipo_principal = NTipoUnidadOrganizativa.objects.create(
            descripcion='Oficina', es_principal=True)
        cls.tipo_sub = NTipoUnidadOrganizativa.objects.create(
            descripcion='Subunidad', es_subunidad=True)
        cls.tipo_normal = NTipoUnidadOrganizativa.objects.create(
            descripcion='UEB')

        cls.padre = UnidadOrganizativa.objects.create(
            codigo_interno=10, descripcion='Oficina Central',
            tipo=cls.tipo_principal, grupo_nomina=1)
        cls.hija_a = UnidadOrganizativa.objects.create(
            codigo_interno=11, descripcion='Camaguey',
            tipo=cls.tipo_sub, grupo_nomina=1, padre=cls.padre)
        cls.hija_b = UnidadOrganizativa.objects.create(
            codigo_interno=12, descripcion='Capital Humano',
            tipo=cls.tipo_sub, grupo_nomina=1, padre=cls.padre)
        cls.independiente = UnidadOrganizativa.objects.create(
            codigo_interno=13, descripcion='Florida',
            tipo=cls.tipo_normal, grupo_nomina=2)

    def datos(self, **extra):
        base = {
            'username': 'moderador_nuevo',
            'email': 'mod@orbith.test',
            'password1': CLAVE,
            'password2': CLAVE,
            'es_admin': False,
            'es_moderador': True,
            'es_observador': False,
            'is_active': True,
        }
        base.update(extra)
        return base


class SelectorDeUnidadesTests(BaseEstructura):
    """Qué se le OFRECE al Administrador en el desplegable."""

    def test_las_subunidades_no_se_ofrecen(self):
        formulario = CustomUserCreationForm()
        ofrecidas = {u.pk for u in formulario.fields['unidades'].queryset}
        self.assertIn(self.padre.pk, ofrecidas)
        self.assertIn(self.independiente.pk, ofrecidas)
        self.assertNotIn(self.hija_a.pk, ofrecidas)
        self.assertNotIn(self.hija_b.pk, ofrecidas)

    def test_se_ofrecen_en_dos_grupos(self):
        grupos = dict(CustomUserCreationForm().fields['unidades'].choices)
        self.assertIn(ETIQUETA_PRINCIPALES, grupos)
        self.assertIn(ETIQUETA_INDEPENDIENTES, grupos)

    def test_la_principal_dice_cuantas_subunidades_arrastra(self):
        """Sin esto, elegir un padre tendría un efecto que nadie anuncia."""
        grupos = dict(CustomUserCreationForm().fields['unidades'].choices)
        etiquetas = [texto for _, texto in grupos[ETIQUETA_PRINCIPALES]]
        self.assertEqual(len(etiquetas), 1)
        self.assertIn('Oficina Central', etiquetas[0])
        self.assertIn('incluye 2 subunidades', etiquetas[0])

    def test_la_independiente_no_habla_de_subunidades(self):
        grupos = dict(CustomUserCreationForm().fields['unidades'].choices)
        etiquetas = [texto for _, texto in grupos[ETIQUETA_INDEPENDIENTES]]
        self.assertIn('Florida', etiquetas)


class ExpansionAlGuardarTests(BaseEstructura):
    """Qué se GUARDA realmente."""

    def test_elegir_el_padre_asigna_tambien_sus_hijas(self):
        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.padre.pk]))
        self.assertTrue(formulario.is_valid(), formulario.errors.as_text())
        usuario = formulario.save()

        asignadas = set(usuario.unidades.values_list('descripcion', flat=True))
        self.assertEqual(
            asignadas, {'Oficina Central', 'Camaguey', 'Capital Humano'})

    def test_una_independiente_no_arrastra_nada(self):
        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.independiente.pk]))
        self.assertTrue(formulario.is_valid(), formulario.errors.as_text())
        usuario = formulario.save()
        self.assertEqual(
            list(usuario.unidades.values_list('descripcion', flat=True)), ['Florida'])

    def test_el_moderador_puede_declarar_las_hijas_que_hereda(self):
        """La razón de negocio por la que las hijas se guardan de verdad.

        `cierres.permisos.puede_declarar` niega declarar una Unidad Principal
        —su estado se deriva del de sus hijas— y solo acepta unidades asignadas.
        Si heredar no dejara las hijas en la tabla, el moderador no podría
        declarar ni el padre ni las hijas, y el cierre quedaría bloqueado.
        """
        from cierres.permisos import puede_declarar

        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.padre.pk]))
        self.assertTrue(formulario.is_valid(), formulario.errors.as_text())
        usuario = formulario.save()

        self.assertFalse(puede_declarar(usuario, self.padre))   # regla estructural
        self.assertTrue(puede_declarar(usuario, self.hija_a))
        self.assertTrue(puede_declarar(usuario, self.hija_b))


class RechazosTests(BaseEstructura):
    """Qué se RECHAZA, y con qué mensaje."""

    def test_no_se_puede_colar_una_subunidad_por_el_post(self):
        """Ocultarla del desplegable no es la protección: el queryset lo es."""
        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.hija_a.pk]))
        self.assertFalse(formulario.is_valid())
        self.assertIn('unidades', formulario.errors)

    def test_se_rechaza_si_una_hija_ya_tiene_otro_moderador(self):
        otro = CustomUser.objects.create_user(
            username='otro_moderador', password=CLAVE, es_moderador=True)
        otro.unidades.add(self.hija_a)

        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.padre.pk]))
        self.assertFalse(formulario.is_valid())
        mensaje = ' '.join(formulario.errors['unidades'])
        # El aviso tiene que nombrar la HIJA en conflicto, no solo el padre:
        # si no, el Administrador no sabe qué liberar.
        self.assertIn('Camaguey', mensaje)
        self.assertIn('otro_moderador', mensaje)

    def test_el_conflicto_en_una_hija_no_se_detectaria_expandiendo_tarde(self):
        """Fija el ORDEN de `clean()`, que es lo que hace posible la prueba anterior.

        Si la expansión ocurriera después de `validar_moderador_unico`, esa
        validación solo vería el padre —que está libre— y guardaría una hija con
        dos moderadores. Aquí se comprueba que la hija llega ya al validador.
        """
        otro = CustomUser.objects.create_user(
            username='duenno_de_la_hija', password=CLAVE, es_moderador=True)
        otro.unidades.add(self.hija_b)

        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.padre.pk]))
        self.assertFalse(formulario.is_valid())
        self.assertIn('Capital Humano', ' '.join(formulario.errors['unidades']))


class PropagacionAutomaticaTests(BaseEstructura):
    """Qué pasa DESPUÉS, cuando la estructura cambia."""

    def _moderador_con_el_padre(self):
        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.padre.pk]))
        self.assertTrue(formulario.is_valid(), formulario.errors.as_text())
        return formulario.save()

    def test_una_subunidad_nueva_entra_sola(self):
        usuario = self._moderador_con_el_padre()

        nueva = UnidadOrganizativa.objects.create(
            codigo_interno=99, descripcion='Nuevitas',
            tipo=self.tipo_sub, grupo_nomina=1, padre=self.padre)

        self.assertIn(nueva, usuario.unidades.all())

    def test_una_subunidad_nueva_sin_padre_asignado_no_se_reparte(self):
        otro_padre = UnidadOrganizativa.objects.create(
            codigo_interno=98, descripcion='Otra Oficina',
            tipo=self.tipo_principal, grupo_nomina=3)
        usuario = self._moderador_con_el_padre()

        ajena = UnidadOrganizativa.objects.create(
            codigo_interno=97, descripcion='Subunidad Ajena',
            tipo=self.tipo_sub, grupo_nomina=3, padre=otro_padre)

        self.assertNotIn(ajena, usuario.unidades.all())

    def test_mudar_una_subunidad_a_otro_padre_cambia_de_titular(self):
        """El invariante se mantiene solo: quien lleva la hija lleva al padre."""
        usuario = self._moderador_con_el_padre()
        self.assertIn(self.hija_a, usuario.unidades.all())

        otro_padre = UnidadOrganizativa.objects.create(
            codigo_interno=96, descripcion='Oficina Destino',
            tipo=self.tipo_principal, grupo_nomina=4)
        self.hija_a.padre = otro_padre
        self.hija_a.save()

        usuario.refresh_from_db()
        self.assertNotIn(self.hija_a, usuario.unidades.all())
        # Y el resto de su parcela sigue intacta.
        self.assertIn(self.padre, usuario.unidades.all())
        self.assertIn(self.hija_b, usuario.unidades.all())


class ElMensajeLlegaALaPantallaTests(BaseEstructura):
    """Rechazar no sirve de nada si el Administrador no ve por qué.

    La pantalla de edición repinta esta misma plantilla dentro del modal cuando
    el formulario no valida (`CustomUserUpdateView.form_invalid`), y no incluía
    el bloque de errores de `unidades`: el formulario reaparecía intacto y sin
    explicación, como si el guardado se hubiera perdido por las buenas.

    Es un fallo que no deja rastro en ningún log y que solo se nota usando la
    pantalla, así que conviene tenerlo fijado aquí.
    """

    def test_al_editar_se_ve_que_unidad_choca(self):
        from django.urls import reverse

        administrador = CustomUser.objects.create_user(
            username='admin_mensaje', password=CLAVE, es_admin=True)
        editado = CustomUser.objects.create_user(
            username='moderador_editado', password=CLAVE, es_moderador=True)
        rival = CustomUser.objects.create_user(
            username='rival', password=CLAVE, es_moderador=True)
        rival.unidades.add(self.hija_a)

        self.client.force_login(administrador)
        respuesta = self.client.post(
            reverse('updt_usuario', args=[editado.pk]),
            {
                'username': 'moderador_editado',
                'email': 'editado@orbith.test',
                'es_moderador': 'on',
                'is_active': 'on',
                'unidades': [self.padre.pk],
            },
            headers={'x-requested-with': 'XMLHttpRequest'},
        )

        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertFalse(cuerpo['form_is_valid'])
        # El nombre de la subunidad en conflicto tiene que viajar hasta el HTML
        # que se inyecta en el modal.
        self.assertIn('Camaguey', cuerpo['html_form'])
        self.assertIn('rival', cuerpo['html_form'])


class ComandoSincronizarUnidadesTests(BaseEstructura):
    """`manage.py sincronizar_unidades` repara lo que el formulario no alcanza.

    El formulario expande al guardar y el signal reparte las subunidades nuevas,
    pero ninguno de los dos toca lo que YA estaba escrito antes de que existieran,
    ni lo que entre por fuera: una importación, el shell o el admin de Django.

    Y cuando los datos se descuadran el fallo es SILENCIOSO: el moderador deja de
    ver a los trabajadores de esa subunidad en media aplicación y no puede
    declarar su cierre, sin que nada avise. De ahí que exista el comando.
    """

    def moderador_descuadrado(self):
        """Un moderador con el padre pero sin sus hijas.

        Se asigna con `set()` a propósito, saltándose el formulario: es
        exactamente la vía por la que aparecen estos datos en la realidad.
        """
        usuario = CustomUser.objects.create_user(
            username='mod_descuadrado', password=CLAVE, es_moderador=True)
        usuario.unidades.set([self.padre])
        return usuario

    def ejecutar(self, *argumentos):
        from io import StringIO

        from django.core.management import call_command

        salida = StringIO()
        call_command('sincronizar_unidades', *argumentos, stdout=salida)
        return salida.getvalue()

    def test_detecta_y_repara_las_subunidades_que_faltan(self):
        usuario = self.moderador_descuadrado()

        self.ejecutar()

        asignadas = set(usuario.unidades.values_list('descripcion', flat=True))
        self.assertEqual(asignadas, {'Oficina Central', 'Camaguey', 'Capital Humano'})

    def test_simular_informa_pero_no_escribe(self):
        usuario = self.moderador_descuadrado()

        salida = self.ejecutar('--simular')

        self.assertIn('mod_descuadrado', salida)
        self.assertIn('Camaguey', salida)
        self.assertEqual(usuario.unidades.count(), 1)   # no se tocó nada

    def test_es_idempotente(self):
        usuario = self.moderador_descuadrado()
        self.ejecutar()
        antes = set(usuario.unidades.values_list('pk', flat=True))

        salida = self.ejecutar()

        self.assertEqual(set(usuario.unidades.values_list('pk', flat=True)), antes)
        self.assertIn('cumplen el invariante', salida)

    def test_no_toca_a_quien_ya_esta_bien(self):
        usuario = CustomUser.objects.create_user(
            username='mod_correcto', password=CLAVE, es_moderador=True)
        usuario.unidades.set([self.independiente])

        self.ejecutar()

        self.assertEqual(
            set(usuario.unidades.values_list('descripcion', flat=True)), {'Florida'})

    def test_nunca_QUITA_unidades(self):
        """Solo añade. Una unidad asignada de más puede responder a una decisión
        que el comando no conoce, y retirarla dejaría a alguien sin acceso por
        sorpresa."""
        usuario = CustomUser.objects.create_user(
            username='mod_con_extra', password=CLAVE, es_moderador=True)
        # Una subunidad suelta, sin su padre: incoherente, pero el comando no la quita.
        usuario.unidades.set([self.hija_a])

        self.ejecutar()

        self.assertIn('Camaguey',
                      usuario.unidades.values_list('descripcion', flat=True))

    def test_por_defecto_no_toca_a_los_observadores(self):
        """El Observador ve toda la empresa por su rol, así que sus unidades no
        deciden nada y no hay motivo para reescribirlas."""
        observador = CustomUser.objects.create_user(
            username='obs_descuadrado', password=CLAVE, es_observador=True)
        observador.unidades.set([self.padre])

        self.ejecutar()

        self.assertEqual(observador.unidades.count(), 1)

    def test_con_la_bandera_si_incluye_a_los_observadores(self):
        observador = CustomUser.objects.create_user(
            username='obs_incluido', password=CLAVE, es_observador=True)
        observador.unidades.set([self.padre])

        self.ejecutar('--incluir-observadores')

        self.assertEqual(observador.unidades.count(), 3)


class UnidadesOcupadasEnElDesplegableTests(BaseEstructura):
    """Una unidad que ya lleva otro moderador se ofrece APAGADA.

    La regla «una unidad, un moderador» ya la imponía `validar_moderador_unico`,
    pero solo al GUARDAR: se elegía la unidad, se rellenaba el resto del
    formulario y el choque aparecía al enviar.

    Se apagan en vez de ocultarlas a propósito: una lista a la que le faltan
    unidades sin decir por qué obliga a ir usuario por usuario averiguando quién
    las lleva. Apagada, la respuesta está en la propia opción.
    """

    def con_moderador(self, username, *unidades):
        usuario = CustomUser.objects.create_user(
            username=username, password=CLAVE, es_moderador=True)
        usuario.unidades.set(unidades)
        return usuario

    def opciones(self, formulario):
        """`{descripcion_de_la_opcion: esta_apagada}`."""
        import re

        html = str(formulario['unidades'])
        return {
            re.sub(r'\s+', ' ', m.group(3)).strip(): 'disabled' in m.group(2)
            for m in re.finditer(r'<option value="(\d+)"([^>]*)>(.*?)</option>', html)
        }

    def test_la_unidad_de_otro_moderador_sale_apagada(self):
        self.con_moderador('mod_titular', self.independiente)

        opciones = self.opciones(CustomUserCreationForm())

        apagadas = [texto for texto, apagada in opciones.items() if apagada]
        self.assertEqual(len(apagadas), 1)
        self.assertIn('Florida', apagadas[0])

    def test_la_opcion_apagada_dice_quien_la_lleva(self):
        """Sin el nombre, el Administrador no sabe a quién reclamársela."""
        self.con_moderador('mod_titular', self.independiente)

        opciones = self.opciones(CustomUserCreationForm())

        apagada = next(t for t, esta in opciones.items() if esta)
        self.assertIn('la lleva mod_titular', apagada)

    def test_una_unidad_libre_no_se_apaga(self):
        self.con_moderador('mod_titular', self.independiente)

        opciones = self.opciones(CustomUserCreationForm())

        libre = next(t for t in opciones if 'Oficina Central' in t)
        self.assertFalse(opciones[libre])

    def test_al_editarse_a_si_mismo_sus_unidades_NO_se_apagan(self):
        """El caso que rompería el formulario: una opción apagada no se envía, así
        que al guardar se perderían las unidades que el moderador ya tenía."""
        titular = self.con_moderador('mod_titular', self.padre)

        opciones = self.opciones(CustomUserChangeForm(instance=titular))

        propia = next(t for t in opciones if 'Oficina Central' in t)
        self.assertFalse(opciones[propia])

    def test_al_editar_a_otro_si_se_apagan(self):
        self.con_moderador('mod_titular', self.padre)
        otro = self.con_moderador('mod_otro')

        opciones = self.opciones(CustomUserChangeForm(instance=otro))

        ocupada = next(t for t in opciones if 'Oficina Central' in t)
        self.assertTrue(opciones[ocupada])

    def test_el_servidor_sigue_rechazando_aunque_se_fuerce_el_envio(self):
        """Apagar la opción es comodidad, no seguridad: quien manda un POST a mano
        se sigue encontrando la validación."""
        self.con_moderador('mod_titular', self.independiente)

        formulario = CustomUserCreationForm(
            data=self.datos(unidades=[self.independiente.pk]))

        self.assertFalse(formulario.is_valid())
        self.assertIn('un moderador', str(formulario.errors['unidades']))
