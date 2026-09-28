"""
Pruebas unitarias para la subtarea SCRUM-76 / HU02-ST2: Autenticación y verificación de credenciales.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
import json


class AuthCredentialVerificationTests(TestCase):
    """Pruebas de verificación de credenciales y seguridad RNF04."""

    def setUp(self):
        self.client = Client()
        self.login_url = reverse('login')
        self.api_login_url = reverse('api_auth_login')
        
        # Crear usuario de prueba en base de datos con contraseña cifrada
        self.username = "cafe_user"
        self.email = "productor@cafepergamo.com"
        self.password = "Pergamo2026*Secure!"
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
            first_name="Juan",
            last_name="Valdez"
        )

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

    def test_login_invalid_credentials_generic_error_web(self):
        """Verifica el mensaje genérico contra enumeración de cuentas (seguridad) ante credenciales incorrectas."""
        response = self.client.post(self.login_url, {
            "email": self.email,
            "password": "WrongPassword123!"
        })
        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any("incorrectos" in str(m) for m in messages))

    def test_login_invalid_credentials_api(self):
        """Verifica que la API retorne 401 y mensaje genérico ante credenciales incorrectas."""
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": "inexistente@correo.com", "password": "DummyPassword"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn("error", data)

    def test_login_success_with_email_web(self):
        """Verifica autenticación exitosa usando correo electrónico y redirección."""
        response = self.client.post(self.login_url, {
            "email": self.email,
            "password": self.password
        })
        # Debe redirigir a 'home'
        self.assertEqual(response.status_code, 302)
        # Verificar que el usuario quedó autenticado en la sesión
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_success_api(self):
        """Verifica autenticación exitosa mediante la API JSON retornando código 200."""
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data["user"]["email"], self.email)
