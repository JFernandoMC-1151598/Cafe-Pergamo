"""
Pruebas unitarias para la subtarea SCRUM-76 / HU02-ST2: Autenticación y verificación de credenciales.

La verificación de credenciales real vive en Supabase Auth (ver
usuarios/supabase_client.py y el docstring de usuarios/views.py), así
que estas pruebas simulan (mock) el cliente de Supabase y la consulta al
perfil de negocio (`usuarios.Usuario`) en vez de tocar la base de datos
real: esas tablas son `managed = False` y no existen en la base de datos
de pruebas que Django crea automáticamente para cada `TestCase`.
"""

import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from supabase_auth.errors import AuthApiError


def _fake_auth_user(user_id, email):
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_user.email = email
    return fake_user


def _fake_perfil(user_id, correo, nombres="Juan", apellidos="Valdez", rol_codigo="PRODUCTOR", activo=True):
    perfil = MagicMock()
    perfil.id = user_id
    perfil.correo = correo
    perfil.nombres = nombres
    perfil.apellidos = apellidos
    perfil.activo = activo
    perfil.rol.codigo = rol_codigo
    return perfil


class AuthCredentialVerificationTests(TestCase):
    """Pruebas de verificación de credenciales y seguridad RNF04."""

    def setUp(self):
        self.client = Client()
        self.login_url = reverse('login')
        self.api_login_url = reverse('api_auth_login')
        self.correo = "productor@cafepergamo.com"
        self.password = "Pergamo2026*Secure!"
        self.user_id = "11111111-1111-1111-1111-111111111111"

    def test_get_login_page(self):
        """Verifica que la página de login responda con código 200 y use la plantilla correspondiente."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "usuarios/login.html")

    def test_login_empty_fields_web(self):
        """Verifica que campos vacíos en el formulario web sean rechazados con mensaje de error."""
        response = self.client.post(self.login_url, {"email": "", "password": ""})
        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any("obligatorios" in str(m) for m in messages))

    def test_login_empty_fields_api(self):
        """Verifica que el endpoint API rechace payloads con campos vacíos con código 400."""
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": "", "password": ""}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    @patch("usuarios.views.get_supabase_client")
    def test_login_invalid_credentials_generic_error_web(self, mock_get_client):
        """Verifica el mensaje genérico contra enumeración de cuentas (seguridad) ante credenciales incorrectas."""
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, "invalid_credentials"
        )
        response = self.client.post(self.login_url, {
            "email": self.correo,
            "password": "WrongPassword123!"
        })
        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any("incorrectos" in str(m) for m in messages))

    @patch("usuarios.views.get_supabase_client")
    def test_login_invalid_credentials_api(self, mock_get_client):
        """Verifica que la API retorne 401 y mensaje genérico ante credenciales incorrectas."""
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, "invalid_credentials"
        )
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": "inexistente@correo.com", "password": "DummyPassword"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn("error", data)

    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.get_supabase_client")
    def test_login_success_with_email_web(self, mock_get_client, mock_usuario_model):
        """Verifica autenticación exitosa contra Supabase y redirección, con sesión de Django sincronizada."""
        mock_get_client.return_value.auth.sign_in_with_password.return_value.user = _fake_auth_user(
            self.user_id, self.correo
        )
        mock_usuario_model.objects.select_related.return_value.get.return_value = _fake_perfil(
            self.user_id, self.correo
        )

        response = self.client.post(self.login_url, {
            "email": self.correo,
            "password": self.password
        })
        # Debe redirigir a 'home'.
        self.assertEqual(response.status_code, 302)
        # La fila "espejo" en auth_user queda identificada por el UUID de Supabase.
        django_user = User.objects.get(username=self.user_id)
        self.assertEqual(int(self.client.session['_auth_user_id']), django_user.pk)
        self.assertFalse(django_user.has_usable_password())
        self.assertEqual(self.client.session["rol"], "PRODUCTOR")

    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.get_supabase_client")
    def test_login_success_api(self, mock_get_client, mock_usuario_model):
        """Verifica autenticación exitosa mediante la API JSON retornando código 200."""
        mock_get_client.return_value.auth.sign_in_with_password.return_value.user = _fake_auth_user(
            self.user_id, self.correo
        )
        mock_usuario_model.objects.select_related.return_value.get.return_value = _fake_perfil(
            self.user_id, self.correo
        )

        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.correo, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data["user"]["correo"], self.correo)
        self.assertEqual(data["user"]["rol"], "PRODUCTOR")

    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.get_supabase_client")
    def test_login_perfil_inactivo_es_rechazado(self, mock_get_client, mock_usuario_model):
        """Un perfil con activo=False no debe poder iniciar sesión, aunque la contraseña sea correcta."""
        mock_get_client.return_value.auth.sign_in_with_password.return_value.user = _fake_auth_user(
            self.user_id, self.correo
        )
        mock_usuario_model.objects.select_related.return_value.get.return_value = _fake_perfil(
            self.user_id, self.correo, activo=False
        )

        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.correo, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
