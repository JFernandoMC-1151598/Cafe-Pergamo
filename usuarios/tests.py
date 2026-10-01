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
        self.assertEqual(data["user"]["email"], self.email)


class JwtSessionTokenGenerationTests(TestCase):
    """Pruebas para HU02-ST3: Generación de Tokens de Sesión (JWT) y Custom Claims."""

    def setUp(self):
        import jwt
        self.jwt = jwt
        self.client = Client()
        self.token_url = reverse('token_obtain_pair')
        self.token_refresh_url = reverse('token_refresh')

        self.username = "productor_jwt"
        self.email = "carlos.valdez@cafepergamo.com"
        self.password = "Pergamo2026*JWT!"
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
            first_name="Carlos",
            last_name="Valdez"
        )

    def test_obtain_token_success_and_custom_claims(self):
        """Verifica emisión de access/refresh token y claims personalizados (role, email, full_name)."""
        from django.conf import settings
        response = self.client.post(
            self.token_url,
            data=json.dumps({"username": self.username, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertIn("user", data)
        self.assertEqual(data["user"]["email"], self.email)
        self.assertEqual(data["user"]["full_name"], "Carlos Valdez")

        # Decodificar el token para verificar claims del payload
        access_token = data["access"]
        payload = self.jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_signature": True}
        )
        self.assertEqual(payload["email"], self.email)
        self.assertEqual(payload["full_name"], "Carlos Valdez")
        self.assertEqual(payload["username"], self.username)
        self.assertIn("role", payload)
        self.assertIn("exp", payload)

    def test_obtain_token_with_email_identifier(self):
        """Verifica que el endpoint acepte 'email' como identificador."""
        response = self.client.post(
            self.token_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)

    def test_refresh_token_lifecycle(self):
        """Verifica que el refresh token permita obtener un nuevo access token válido."""
        token_res = self.client.post(
            self.token_url,
            data=json.dumps({"username": self.username, "password": self.password}),
            content_type="application/json"
        )
        refresh_token = token_res.json()["refresh"]

        refresh_res = self.client.post(
            self.token_refresh_url,
            data=json.dumps({"refresh": refresh_token}),
            content_type="application/json"
        )
        self.assertEqual(refresh_res.status_code, 200)
        self.assertIn("access", refresh_res.json())

    def test_obtain_token_invalid_password(self):
        """Verifica código 401 si las credenciales son erróneas."""
        response = self.client.post(
            self.token_url,
            data=json.dumps({"username": self.username, "password": "BadPassword123"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)


class LogoutSessionTests(TestCase):
    """Pruebas para HU02-ST4: Cierre de Sesión (Logout Web y Revocación JWT)."""

    def setUp(self):
        self.client = Client()
        self.logout_url = reverse('logout')
        self.api_logout_url = reverse('api_auth_logout')
        self.token_url = reverse('token_obtain_pair')
        self.token_refresh_url = reverse('token_refresh')

        self.username = "test_logout_user"
        self.email = "logout_user@cafepergamo.com"
        self.password = "Pergamo2026*Logout!"
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password
        )

    def test_web_logout_via_post_destroys_session(self):
        """Verifica que un POST a /logout/ destruya la sesión HTTP y redirija a login."""
        self.client.login(username=self.username, password=self.password)
        self.assertIn('_auth_user_id', self.client.session)

        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_web_logout_via_get_is_rejected_safely(self):
        """Verifica que una petición GET a /logout/ no cierre sesión (protección CSRF/RFC)."""
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.logout_url)
        # Debe redirigir de forma segura sin destruir la sesión
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_api_logout_blacklists_jwt_refresh_token(self):
        """Verifica que el endpoint /api/auth/logout/ invalide el token de refresco en la lista negra."""
        # 1. Obtener tokens
        token_res = self.client.post(
            self.token_url,
            data=json.dumps({"username": self.username, "password": self.password}),
            content_type="application/json"
        )
        refresh_token = token_res.json()["refresh"]

        # 2. Enviar petición de logout revocando el refresh token
        logout_res = self.client.post(
            self.api_logout_url,
            data=json.dumps({"refresh": refresh_token}),
            content_type="application/json"
        )
        self.assertEqual(logout_res.status_code, 200)

        # 3. Comprobar que el refresh token ya no sirve para refrescar
        refresh_res = self.client.post(
            self.token_refresh_url,
            data=json.dumps({"refresh": refresh_token}),
            content_type="application/json"
        )
        self.assertEqual(refresh_res.status_code, 401)


class AccountLockoutSecurityTests(TestCase):
    """
    Pruebas automatizadas para SCRUM-79 / HU02-ST5: Control de intentos fallidos y bloqueo de cuenta.
    Valida RN03 (5 intentos consecutivos), EX-3 (Bloqueo temporal 15 min), RNF07 (Prevención de enumeración).
    """

    def setUp(self):
        from usuarios.models import RegistroIntentoLogin
        self.RegistroIntentoLogin = RegistroIntentoLogin
        self.client = Client()
        self.login_url = reverse('login')
        self.api_login_url = reverse('api_auth_login')
        self.token_url = reverse('token_obtain_pair')

        self.username = "bloqueo_user"
        self.email = "seguridad@cafepergamo.com"
        self.password = "Pergamo2026*SecureLock!"
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
            first_name="Diana",
            last_name="Segura"
        )

    def test_failed_attempt_increments_counter(self):
        """1. Prueba que incrementa el contador ante cada contraseña errónea (RN03)."""
        # Realizar 3 intentos con contraseña errónea
        for i in range(1, 4):
            response = self.client.post(
                self.api_login_url,
                data=json.dumps({"email": self.email, "password": f"PasswordInvalido_{i}"}),
                content_type="application/json"
            )
            self.assertEqual(response.status_code, 401)

            # Verificar incremento progresivo en la base de datos
            registro = self.RegistroIntentoLogin.objects.get(identificador=self.username.lower())
            self.assertEqual(registro.failed_attempts, i)
            self.assertFalse(registro.is_locked)
            self.assertIsNone(registro.locked_until)

    def test_account_lockout_on_consecutive_failures(self):
        """2. Prueba que bloquea el acceso tras alcanzar el límite y rechaza el intento N+1 (EX-3)."""
        # Ejecutar 5 intentos fallidos consecutivos (límite configurado = 5)
        for i in range(1, 6):
            response = self.client.post(
                self.api_login_url,
                data=json.dumps({"email": self.email, "password": f"WrongPwd_{i}"}),
                content_type="application/json"
            )
            if i < 5:
                self.assertEqual(response.status_code, 401)
            else:
                # En el 5to fallo se activa el bloqueo
                self.assertEqual(response.status_code, 403)
                data = response.json()
                self.assertTrue(data.get("locked"))
                self.assertIn("demasiados intentos", data.get("error", ""))

        # Verificar estado del registro en base de datos
        registro = self.RegistroIntentoLogin.objects.get(identificador=self.username.lower())
        self.assertEqual(registro.failed_attempts, 5)
        self.assertTrue(registro.is_locked)
        self.assertIsNotNone(registro.locked_until)

        # Intento N+1 (intento 6): Incluso con la contraseña CORRECTA, debe ser rechazado por estar bloqueado
        response_n_plus_1 = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response_n_plus_1.status_code, 403)
        data_n1 = response_n_plus_1.json()
        self.assertTrue(data_n1.get("locked"))
        self.assertIn("bloqueada temporalmente", data_n1.get("error", ""))

    def test_successful_login_resets_counter(self):
        """3. Prueba que reinicia el contador de fallos a 0 tras un inicio de sesión exitoso."""
        # Generar 3 intentos fallidos previos
        for i in range(3):
            self.client.post(
                self.api_login_url,
                data=json.dumps({"email": self.email, "password": "BadPassword"}),
                content_type="application/json"
            )

        registro = self.RegistroIntentoLogin.objects.get(identificador=self.username.lower())
        self.assertEqual(registro.failed_attempts, 3)

        # Inicio de sesión exitoso con credenciales correctas
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        # Verificar reinicio del contador a 0
        registro.refresh_from_db()
        self.assertEqual(registro.failed_attempts, 0)
        self.assertIsNone(registro.locked_until)
        self.assertFalse(registro.is_locked)

    def test_generic_error_response_prevents_enumeration_rnf07(self):
        """4. Prueba que valida la respuesta de error genérica uniforme para prevenir enumeración (RNF07)."""
        # Caso A: Usuario existente con contraseña incorrecta
        res_existente = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": "ContraseñaEquivocada"}),
            content_type="application/json"
        )
        self.assertEqual(res_existente.status_code, 401)
        err_existente = res_existente.json().get("error")

        # Caso B: Usuario inexistente en la plataforma
        res_inexistente = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": "no_existe_9876@cafepergamo.com", "password": "Password123"}),
            content_type="application/json"
        )
        self.assertEqual(res_inexistente.status_code, 401)
        err_inexistente = res_inexistente.json().get("error")

        # Ambos mensajes de error deben ser idénticos
        self.assertEqual(err_existente, err_inexistente)
        self.assertIn("incorrectos", err_existente)

    def test_jwt_endpoint_account_lockout(self):
        """5. Prueba que el endpoint de tokens JWT (/api/auth/token/) bloquea el acceso tras 5 fallos."""
        # 5 intentos fallidos en el endpoint JWT
        for i in range(5):
            res = self.client.post(
                self.token_url,
                data=json.dumps({"username": self.username, "password": "WrongPassword"}),
                content_type="application/json"
            )
            self.assertEqual(res.status_code, 401)

        # Intento posterior: cuenta bloqueada
        res_blocked = self.client.post(
            self.token_url,
            data=json.dumps({"username": self.username, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(res_blocked.status_code, 401)
        data = res_blocked.json()
        self.assertIn("bloqueada temporalmente", str(data))

    def test_lockout_cooloff_automatic_expiration(self):
        """6. Prueba que la cuenta se desbloquea automáticamente cuando el período de bloqueo expira."""
        from django.utils import timezone
        from datetime import timedelta

        # Simular una cuenta bloqueada cuyo tiempo de bloqueo ya expiró (en el pasado)
        registro, _ = self.RegistroIntentoLogin.objects.get_or_create(
            identificador=self.username.lower(),
            defaults={"user": self.user}
        )
        registro.failed_attempts = 5
        registro.locked_until = timezone.now() - timedelta(minutes=1)
        registro.save()

        # Al intentar iniciar sesión con credenciales correctas, el cooloff expiró y debe permitir entrar
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        registro.refresh_from_db()
        self.assertEqual(registro.failed_attempts, 0)
        self.assertIsNone(registro.locked_until)
        self.assertFalse(registro.is_locked)



