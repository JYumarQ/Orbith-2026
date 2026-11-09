"""Una subunidad no se asigna por separado: se asigna su Unidad Principal.

Antes, el selector de la pantalla de Usuarios ofrecía las tres clases de unidad
mezcladas y con el mismo aspecto, así que nada impedía dar a un moderador una
subunidad suelta —cuyo padre podía llevar otra persona— ni indicaba que elegir
una principal tuviera consecuencia alguna sobre sus hijas.

Estas pruebas fijan las cuatro piezas de la regla:

1. qué se OFRECE (solo unidades sin padre, agrupadas y con el conteo);
2. qué se GUARDA al elegir un padre (el padre y todas sus hijas);
3. qué se RECHAZA (una subunidad enviada a mano);
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

    def test_por_defecto_tambien_repara_a_los_observadores_acotados(self):
        """Desde que el alcance del Observador se puede acotar por unidad (ver
        `usuarios/alcance.py`), sus unidades deciden lo mismo que las de un
        Moderador: un descuadre le esconde media empresa igual de callado.

        Antes el comando los ignoraba salvo que se le pasara una bandera, con el
        razonamiento —correcto entonces— de que el Observador veía toda la
        empresa por su rol."""
        observador = CustomUser.objects.create_user(
            username='obs_descuadrado', password=CLAVE, es_observador=True)
        observador.unidades.set([self.padre])

        self.ejecutar()

        self.assertEqual(observador.unidades.count(), 3)

    def test_no_le_inventa_unidades_al_observador_global(self):
        """Un Observador SIN unidades ve toda la empresa. El comando no debe
        asignarle ninguna: hacerlo lo convertiría en acotado por sorpresa y le
        recortaría justo lo que su rol le da."""
        observador = CustomUser.objects.create_user(
            username='obs_global', password=CLAVE, es_observador=True)

        self.ejecutar()

        self.assertEqual(observador.unidades.count(), 0)

    def test_con_solo_moderadores_no_toca_a_los_observadores(self):
        observador = CustomUser.objects.create_user(
            username='obs_excluido', password=CLAVE, es_observador=True)
        observador.unidades.set([self.padre])

        self.ejecutar('--solo-moderadores')

        self.assertEqual(observador.unidades.count(), 1)


class VariosModeradoresPorUnidadTests(BaseEstructura):
    """3.9.0 (09-11-2026, RRHH): una unidad puede tener VARIOS moderadores. El
    desplegable ya no apaga nada; solo dice quién más la lleva."""

    def test_se_puede_dar_una_unidad_que_ya_lleva_otro(self):
        otro = CustomUser.objects.create_user(username='otro_moderador', password=CLAVE, es_moderador=True)
        otro.unidades.add(self.padre, self.hija_a, self.hija_b)
        formulario = CustomUserCreationForm(data=self.datos(unidades=[self.padre.pk]))
        self.assertTrue(formulario.is_valid(), formulario.errors.as_data())
        nuevo = formulario.save()
        self.assertEqual(set(nuevo.unidades.all()), {self.padre, self.hija_a, self.hija_b})
        self.assertEqual(set(otro.unidades.all()), {self.padre, self.hija_a, self.hija_b})

    def test_la_opcion_dice_quien_mas_la_lleva_y_no_se_apaga(self):
        otro = CustomUser.objects.create_user(username='mod_titular', password=CLAVE, es_moderador=True)
        otro.unidades.add(self.independiente)
        html = str(CustomUserCreationForm()['unidades'])
        opcion = next(linea for linea in html.split('</option>') if 'Florida' in linea)
        self.assertIn('también la lleva mod_titular', opcion)
        self.assertNotIn('disabled', opcion)


class TodasLasUnidadesTests(BaseEstructura):
    """3.9.0: «Todas las unidades (también las futuras)» para Moderador y Observador,
    y unidades obligatorias para los dos."""

    def test_es_la_primera_opcion(self):
        html = str(CustomUserCreationForm()['unidades'])
        self.assertLess(html.index('value="todas"'), html.index('Oficina Central'))

    def test_elegir_todas_marca_y_asigna_todas(self):
        formulario = CustomUserCreationForm(data=self.datos(unidades=['todas']))
        self.assertTrue(formulario.is_valid(), formulario.errors.as_data())
        usuario = formulario.save()
        self.assertTrue(usuario.todas_las_unidades)
        self.assertEqual(usuario.unidades.count(), UnidadOrganizativa.objects.count())

    def test_una_unidad_nueva_le_llega_sola(self):
        formulario = CustomUserCreationForm(data=self.datos(unidades=['todas']))
        self.assertTrue(formulario.is_valid())
        usuario = formulario.save()
        nueva = UnidadOrganizativa.objects.create(
            codigo_interno=99, descripcion='UEB Nueva', tipo=self.tipo_normal, grupo_nomina=9)
        self.assertIn(nueva, usuario.unidades.all())

    def test_al_editar_se_ve_todas_elegida(self):
        usuario = CustomUser.objects.create_user(username='con_todas', password=CLAVE,
                                                 es_observador=True, todas_las_unidades=True)
        html = str(CustomUserChangeForm(instance=usuario)['unidades'])
        self.assertRegex(html, r'<option value="todas"[^>]*selected')

    def test_moderador_y_observador_sin_unidades_se_rechazan(self):
        for rol in ('es_moderador', 'es_observador'):
            datos = self.datos()
            datos.pop('unidades', None)
            datos.update({'es_moderador': False, 'es_observador': False, rol: True})
            formulario = CustomUserCreationForm(data=datos)
            self.assertFalse(formulario.is_valid())
            self.assertIn('Todas las unidades', ' '.join(formulario.errors['unidades']))
