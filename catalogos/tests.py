"""Pruebas funcionales del listado de variedades de café (HU10-ST2)."""

from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import VariedadCafe
from .views import lista_variedades_view


class ListaVariedadesTests(TestCase):
    """Comprueba autorización y consulta del catálogo."""

    def _request(self, authenticated, role="", estado=""):
        query = f"?estado={estado}" if estado else ""
        request = RequestFactory().get(
            f"{reverse('lista_variedades')}{query}"
        )
        request.user = type(
            "User",
            (),
            {
                "is_authenticated": authenticated,
                "username": "admin@example.com",
                "first_name": "Admin",
            },
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    def setUp(self):
        VariedadCafe.objects.create(
            nombre="Castillo",
            especie=VariedadCafe.Especie.ARABICA,
        )
        VariedadCafe.objects.create(
            nombre="Robusta Tradicional",
            especie=VariedadCafe.Especie.ROBUSTA,
            activo=False,
        )

    def test_sesion_no_iniciada_redirige_al_login(self):
        response = lista_variedades_view(self._request(False))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_rol_sin_permiso_recibe_403(self, _mock_permission):
        response = lista_variedades_view(
            self._request(True, role="PRODUCTOR")
        )

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_lista_variedades_diferencia_estados(
        self, _mock_permission, _mock_template_permission
    ):
        response = lista_variedades_view(
            self._request(True, role="ADMINISTRADOR")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Castillo")
        self.assertContains(response, "Robusta Tradicional")
        self.assertContains(response, "Activa")
        self.assertContains(response, "Inactiva")

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_filtro_muestra_solo_activas(
        self, _mock_permission, _mock_template_permission
    ):
        response = lista_variedades_view(
            self._request(True, role="ADMINISTRADOR", estado="activas")
        )

        self.assertContains(response, "Castillo")
        self.assertNotContains(response, "Robusta Tradicional")
