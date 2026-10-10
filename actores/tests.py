"""Pruebas del acceso RBAC al registro de actores (HU08-ST2)."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from actores.views import registro_actor_view


class RegistroActorPermisosTests(SimpleTestCase):
    """Comprueba el contrato de autorización de la pantalla de actores."""

    def _request(self, authenticated: bool, role: str = "", data=None):
        request = RequestFactory().post(
            reverse("registro_actor"), data=data or {}
        ) if data is not None else RequestFactory().get(reverse("registro_actor"))
        request.user = type(
            "User",
            (),
            {"is_authenticated": authenticated, "username": "admin@example.com"},
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    def test_sesion_no_iniciada_redirige_al_login(self):
        response = registro_actor_view(self._request(False))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_rol_sin_permiso_recibe_403(self, _mock_permission):
        response = registro_actor_view(
            self._request(True, role="PRODUCTOR")
        )

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_administrador_con_permiso_puede_ver_el_formulario(
        self, _mock_permission, _mock_template_permission
    ):
        response = registro_actor_view(
            self._request(True, role="ADMINISTRADOR")
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Registrar actor de la cadena", response.content.decode())

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("actores.views.ActorCadenaForm")
    def test_post_valido_persiste_y_redirige(
        self, mock_form_class, _mock_permission
    ):
        form = mock_form_class.return_value
        form.is_valid.return_value = True
        form.save.return_value = SimpleNamespace(
            razon_social="Cooperativa Cafetera"
        )

        response = registro_actor_view(
            self._request(
                True,
                role="ADMINISTRADOR",
                data={
                    "tipo": "COOPERATIVA",
                    "razon_social": "Cooperativa Cafetera",
                    "nit": "900123456-7",
                    "contacto": "Carlos Pérez",
                    "correo": "contacto@example.com",
                },
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("registro_actor"))
        mock_form_class.assert_called_once()
        form.save.assert_called_once_with()

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_post_invalido_muestra_errores_y_no_redirige(
        self, _mock_permission, _mock_template_permission
    ):
        response = registro_actor_view(
            self._request(True, role="ADMINISTRADOR", data={})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Por favor revise los errores", response.content.decode())
