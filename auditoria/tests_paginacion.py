"""Paginación común de las tablas (core/paginacion.py), probada en su piloto: Auditoría."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.paginacion import filas_por_pagina, paginas_visibles

from .models import AccionAuditoria, EventoAuditoria


def pagina(numero, total):
    return SimpleNamespace(number=numero, paginator=SimpleNamespace(num_pages=total))


class PaginasVisiblesTests(TestCase):
    def test_con_puntos_suspensivos(self):
        self.assertEqual(paginas_visibles(pagina(6, 12)), [1, None, 4, 5, 6, 7, 8, None, 12])

    def test_al_principio_y_al_final(self):
        self.assertEqual(paginas_visibles(pagina(1, 12)), [1, 2, 3, None, 12])
        self.assertEqual(paginas_visibles(pagina(12, 12)), [1, None, 10, 11, 12])

    def test_pocas_paginas_sin_puntos(self):
        self.assertEqual(paginas_visibles(pagina(2, 4)), [1, 2, 3, 4])
        self.assertEqual(paginas_visibles(pagina(1, 1)), [1])


class FilasPorPaginaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username='admin_pag', password='ClaveSegura123', es_admin=True)
        self.factory = RequestFactory()

    def peticion(self, consulta=''):
        request = self.factory.get('/?' + consulta)
        request.user = self.admin
        return request

    def test_por_defecto_25(self):
        self.assertEqual(filas_por_pagina(self.peticion()), 25)

    def test_usa_la_preferencia_y_la_peticion_manda(self):
        preferencias = self.admin.obtener_preferencias()
        preferencias.filas_por_pagina = 50
        preferencias.save()
        self.admin.refresh_from_db()
        self.assertEqual(filas_por_pagina(self.peticion()), 50)
        self.assertEqual(filas_por_pagina(self.peticion('filas=10')), 10)
        # Un valor que no está entre las opciones no cuela.
        self.assertEqual(filas_por_pagina(self.peticion('filas=5000')), 50)

    def test_guardar_la_preferencia(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse('guardar_preferencias'), {'filas_por_pagina': '100'})
        self.assertEqual(respuesta.json()['filas_por_pagina'], 100)
        self.assertEqual(self.client.post(reverse('guardar_preferencias'), {'filas_por_pagina': '7'}).status_code, 400)

    def test_auditoria_pagina_con_la_preferencia(self):
        for i in range(30):
            EventoAuditoria.objects.create(usuario=self.admin, accion=AccionAuditoria.ACCESO,
                                           modulo='usuarios', descriptor=f'Acceso {i}')
        self.client.force_login(self.admin)  # el inicio de sesión también se audita
        total = EventoAuditoria.objects.count()
        respuesta = self.client.get(reverse('auditoria:index'))
        self.assertEqual(respuesta.context['page_obj'].paginator.per_page, 25)
        self.assertContains(respuesta, 'Filas por página')
        self.assertContains(respuesta, f'de <b>{total}</b> eventos')
        parcial = self.client.get(reverse('auditoria:buscar_eventos') + '?page=2&filas=10',
                                  HTTP_HX_REQUEST='true')
        self.assertEqual(parcial.context['page_obj'].number, 2)
        self.assertContains(parcial, 'hx-swap-oob="true"')
        self.assertContains(parcial, f'<b>11</b>–<b>20</b> de <b>{total}</b> eventos')
