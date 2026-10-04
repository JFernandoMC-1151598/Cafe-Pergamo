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
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from supabase_auth.errors import AuthApiError

from usuarios.models import Usuario


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

    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.get_supabase_client")
    def test_successful_login_resets_counter(self, mock_get_client, mock_usuario_model):
        """3. Prueba que reinicia el contador de fallos a 0 tras un inicio de sesión exitoso."""
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, "invalid_credentials"
        )
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
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = None
        mock_get_client.return_value.auth.sign_in_with_password.return_value.user = _fake_auth_user(
            str(self.user.id), self.email
        )
        mock_usuario_model.objects.select_related.return_value.get.return_value = _fake_perfil(
            str(self.user.id), self.email
        )
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

    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.get_supabase_client")
    def test_lockout_cooloff_automatic_expiration(self, mock_get_client, mock_usuario_model):
        """6. Prueba que la cuenta se desbloquea automáticamente cuando el período de bloqueo expira."""
        from django.utils import timezone
        from datetime import timedelta

        mock_get_client.return_value.auth.sign_in_with_password.return_value.user = _fake_auth_user(
            str(self.user.id), self.email
        )
        mock_usuario_model.objects.select_related.return_value.get.return_value = _fake_perfil(
            str(self.user.id), self.email
        )

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


class RoleCodeJwtClaimTests(TestCase):
    """
    Pruebas para HU04-ST2 (SCRUM-108), parte 1: el JWT debe incluir el
    claim 'role_code' (código estable del rol), además del 'role' ya
    existente (nombre de presentación) de HU02-ST3.
    """

    def setUp(self):
        self.client = Client()
        self.token_url = reverse('token_obtain_pair')
        self.username = "admin_rbac"
        self.email = "admin.rbac@cafepergamo.com"
        self.password = "Pergamo2026*Rbac!"
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
        )

    @patch("usuarios.models.Usuario")
    @patch("django.db.connection.introspection.table_names")
    def test_token_incluye_role_code_del_perfil(self, mock_table_names, mock_usuario_model):
        """El claim 'role_code' debe tomar el código del rol del perfil de negocio."""
        mock_table_names.return_value = ["usuarios"]
        perfil = _fake_perfil(self.user.id, self.email, rol_codigo="ADMINISTRADOR")
        # obtener_rol_usuario() (HU02-ST3) también lee perfil.rol.nombre para
        # el claim 'role' de presentación; sin fijarlo queda como un
        # MagicMock no serializable y rompe la codificación del JWT.
        perfil.rol.nombre = "Administrador"
        mock_usuario_model.objects.filter.return_value.select_related.return_value.first.return_value = perfil

        response = self.client.post(
            self.token_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        import jwt
        from django.conf import settings
        payload = jwt.decode(
            response.json()["access"],
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_signature": True}
        )
        self.assertEqual(payload["role_code"], "ADMINISTRADOR")
        # El claim original de HU02-ST3 sigue intacto.
        self.assertIn("role", payload)

    def test_token_sin_perfil_de_negocio_no_rompe_y_deja_role_code_vacio(self):
        """
        Sin perfil Usuario resoluble (tabla no sincronizada o usuario sin
        perfil), el claim debe quedar vacío en vez de romper la emisión
        del token — igual de "fail-closed" que el resto del sistema.
        """
        response = self.client.post(
            self.token_url,
            data=json.dumps({"email": self.email, "password": self.password}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        import jwt
        from django.conf import settings
        payload = jwt.decode(
            response.json()["access"],
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_signature": True}
        )
        self.assertEqual(payload.get("role_code"), "")


class AuthorizationRBACTests(TestCase):
    """
    Pruebas para HU04-ST2 (SCRUM-108), parte 2: el middleware de
    autorización (usuarios/permissions.py) que decide, a partir del
    claim 'role_code' del JWT, si el rol tiene el permiso requerido
    para un endpoint, consultando la matriz RolPermiso (HU04-ST1).
    """

    # --- usuario_tiene_permiso(): la función que consulta la matriz ---

    @patch("usuarios.models.RolPermiso")
    def test_usuario_tiene_permiso_concedido(self, mock_rol_permiso):
        from usuarios.permissions import usuario_tiene_permiso
        mock_rol_permiso.objects.filter.return_value.exists.return_value = True

        self.assertTrue(usuario_tiene_permiso("ADMINISTRADOR", "usuarios.administrar"))
        mock_rol_permiso.objects.filter.assert_called_once_with(
            rol__codigo="ADMINISTRADOR",
            rol__activo=True,
            permiso__codigo__in=["usuarios.administrar"],
            permiso__activo=True,
        )

    @patch("usuarios.models.RolPermiso")
    def test_usuario_tiene_permiso_denegado(self, mock_rol_permiso):
        from usuarios.permissions import usuario_tiene_permiso
        mock_rol_permiso.objects.filter.return_value.exists.return_value = False

        self.assertFalse(usuario_tiene_permiso("COMPRADOR", "usuarios.administrar"))

    def test_usuario_tiene_permiso_sin_role_code_deniega_sin_consultar_bd(self):
        from usuarios.permissions import usuario_tiene_permiso
        self.assertFalse(usuario_tiene_permiso("", "usuarios.administrar"))
        self.assertFalse(usuario_tiene_permiso(None, "usuarios.administrar"))

    @patch("usuarios.models.RolPermiso")
    def test_usuario_tiene_permiso_acepta_lista_de_codigos_ored(self, mock_rol_permiso):
        from usuarios.permissions import usuario_tiene_permiso
        mock_rol_permiso.objects.filter.return_value.exists.return_value = True

        self.assertTrue(
            usuario_tiene_permiso("PRODUCTOR", ["lotes.crear", "lotes.consultar"])
        )
        mock_rol_permiso.objects.filter.assert_called_once_with(
            rol__codigo="PRODUCTOR",
            rol__activo=True,
            permiso__codigo__in=["lotes.crear", "lotes.consultar"],
            permiso__activo=True,
        )

    # --- TienePermisoRBAC: permission class de DRF para vistas de clase ---

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_permission_class_concede_acceso(self, mock_check):
        from usuarios.permissions import TienePermisoRBAC
        mock_check.return_value = True

        request = MagicMock()
        request.auth = {"role_code": "ADMINISTRADOR"}
        view = MagicMock()
        view.required_permission = "usuarios.administrar"

        self.assertTrue(TienePermisoRBAC().has_permission(request, view))
        mock_check.assert_called_once_with("ADMINISTRADOR", "usuarios.administrar")

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_permission_class_deniega_acceso(self, mock_check):
        from usuarios.permissions import TienePermisoRBAC
        mock_check.return_value = False

        request = MagicMock()
        request.auth = {"role_code": "COMPRADOR"}
        view = MagicMock()
        view.required_permission = "usuarios.administrar"

        self.assertFalse(TienePermisoRBAC().has_permission(request, view))

    def test_permission_class_deniega_sin_token_jwt(self):
        """Petición sin JWT validado (request.auth es None) -> denegar."""
        from usuarios.permissions import TienePermisoRBAC

        request = MagicMock()
        request.auth = None
        view = MagicMock()
        view.required_permission = "usuarios.administrar"

        self.assertFalse(TienePermisoRBAC().has_permission(request, view))

    def test_permission_class_deniega_si_vista_no_declara_permiso_requerido(self):
        """Vista mal configurada (sin required_permission) -> denegar (fail-closed)."""
        from usuarios.permissions import TienePermisoRBAC

        request = MagicMock()
        request.auth = {"role_code": "ADMINISTRADOR"}
        view = MagicMock(spec=[])  # sin el atributo required_permission

        self.assertFalse(TienePermisoRBAC().has_permission(request, view))

    # --- permiso_requerido: decorador para vistas basadas en función ---

    def test_decorador_responde_401_sin_token(self):
        from django.test import RequestFactory
        from usuarios.permissions import permiso_requerido

        with patch(
            "usuarios.permissions.JWTAuthentication.authenticate",
            return_value=None,
        ):
            @permiso_requerido("usuarios.administrar")
            def vista_protegida(request):
                return JsonResponse({"ok": True})

            request = RequestFactory().get("/api/cualquier-endpoint/")
            response = vista_protegida(request)

        self.assertEqual(response.status_code, 401)

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_decorador_responde_403_sin_permiso(self, mock_check):
        from django.test import RequestFactory
        from usuarios.permissions import permiso_requerido

        mock_check.return_value = False
        fake_token = {"role_code": "COMPRADOR"}

        with patch(
            "usuarios.permissions.JWTAuthentication.authenticate",
            return_value=(MagicMock(), fake_token),
        ):
            @permiso_requerido("usuarios.administrar")
            def vista_protegida(request):
                return JsonResponse({"ok": True})

            request = RequestFactory().get("/api/cualquier-endpoint/")
            response = vista_protegida(request)

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_decorador_deja_pasar_con_permiso_concedido(self, mock_check):
        from django.test import RequestFactory
        from usuarios.permissions import permiso_requerido

        mock_check.return_value = True
        fake_user = MagicMock()
        fake_token = {"role_code": "ADMINISTRADOR"}

        with patch(
            "usuarios.permissions.JWTAuthentication.authenticate",
            return_value=(fake_user, fake_token),
        ):
            @permiso_requerido("usuarios.administrar")
            def vista_protegida(request):
                return JsonResponse({"ok": True, "user": request.user is fake_user})

            request = RequestFactory().get("/api/cualquier-endpoint/")
            response = vista_protegida(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertTrue(body["ok"])
        self.assertTrue(body["user"])


class RoleMenuRenderingTests(TestCase):
    """
    Pruebas para HU04-ST3 (SCRUM-109), parte 1: exponer el rol de la
    sesión a las plantillas (rol_actual) y el filtro que consulta la
    matriz RBAC para decidir qué mostrar (tiene_permiso).
    """

    def test_rol_actual_toma_el_rol_de_la_sesion(self):
        from usuarios.context_processors import rol_actual

        request = MagicMock()
        request.session = {"rol": "ADMINISTRADOR"}

        self.assertEqual(rol_actual(request), {"rol_actual": "ADMINISTRADOR"})

    def test_rol_actual_vacio_sin_sesion_iniciada(self):
        from usuarios.context_processors import rol_actual

        request = MagicMock()
        request.session = {}

        self.assertEqual(rol_actual(request), {"rol_actual": ""})

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso")
    def test_filtro_tiene_permiso_delega_en_usuario_tiene_permiso(self, mock_check):
        from usuarios.templatetags.rbac_tags import tiene_permiso

        mock_check.return_value = True
        self.assertTrue(tiene_permiso("ADMINISTRADOR", "usuarios.administrar"))
        mock_check.assert_called_once_with("ADMINISTRADOR", "usuarios.administrar")


class WebNavigationGuardTests(TestCase):
    """
    Pruebas para HU04-ST3 (SCRUM-109), parte 2: el guard de navegación
    para páginas web basadas en sesión (permiso_requerido_sesion), que
    debe comportarse igual de "fail-closed" que su equivalente de JWT
    (HU04-ST2), pero con la UX del resto del sitio (mensaje flash +
    redirección, no un código de error crudo).
    """

    def _fake_request(self, path="/alguna-pantalla/", autenticado=True, rol=""):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        request = RequestFactory().get(path)
        request.user = MagicMock(is_authenticated=autenticado)
        request.session = {"rol": rol} if rol else {}
        request._messages = FallbackStorage(request)
        return request

    def test_sin_sesion_iniciada_redirige_a_login_con_next(self):
        from usuarios.permissions import permiso_requerido_sesion

        @permiso_requerido_sesion("usuarios.administrar")
        def vista_protegida(request):
            return JsonResponse({"ok": True})

        request = self._fake_request(path="/panel-admin/", autenticado=False)
        response = vista_protegida(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertIn("next=/panel-admin/", response.url)

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_autenticado_sin_permiso_redirige_a_home(self, mock_check):
        from usuarios.permissions import permiso_requerido_sesion

        mock_check.return_value = False

        @permiso_requerido_sesion("usuarios.administrar")
        def vista_protegida(request):
            return JsonResponse({"ok": True})

        request = self._fake_request(autenticado=True, rol="COMPRADOR")
        response = vista_protegida(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_sin_rol_en_sesion_deniega_sin_consultar_la_matriz(self):
        """Sesión autenticada pero sin 'rol' asignado -> deniega (fail-closed)."""
        from usuarios.permissions import permiso_requerido_sesion

        @permiso_requerido_sesion("usuarios.administrar")
        def vista_protegida(request):
            return JsonResponse({"ok": True})

        request = self._fake_request(autenticado=True, rol="")
        response = vista_protegida(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_autenticado_con_permiso_deja_pasar(self, mock_check):
        from usuarios.permissions import permiso_requerido_sesion

        mock_check.return_value = True

        @permiso_requerido_sesion("usuarios.administrar")
        def vista_protegida(request):
            return JsonResponse({"ok": True})

        request = self._fake_request(autenticado=True, rol="ADMINISTRADOR")
        response = vista_protegida(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)["ok"])


class AdminUsuariosPanelTests(TestCase):
    """
    Pruebas para HU04-ST4 (SCRUM-119): pantalla de administración de
    usuarios y reasignación de roles.

    El guard de acceso (permiso_requerido_sesion) ya tiene sus propias
    pruebas en WebNavigationGuardTests, así que aquí se mockea
    `usuario_tiene_permiso` para dejarlo pasar y concentrarse en lo que
    hace la vista: filtrar/listar y procesar la reasignación de rol.
    Usuario y Rol son managed=False (ver docstring del módulo), así que
    se mockean en vez de tocar la base de datos de pruebas.
    """

    def _fake_request_autenticado(self, method="get", path="/admin/usuarios/", data=None, rol="ADMINISTRADOR"):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post(path, data or {}) if method == "post" else factory.get(path, data or {})
        request.user = MagicMock(is_authenticated=True)
        request.session = {"rol": rol}
        request._messages = FallbackStorage(request)
        return request

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_listado_filtra_por_rol_y_estado(self, mock_usuario, mock_rol, _mock_check, _mock_check_menu):
        from usuarios.views import panel_administracion_usuarios

        # La lista final solo necesita comportarse como iterable (para el
        # {% for %} de la plantilla) y responder a .count (usado en el
        # encabezado), no como un queryset real.
        lista_final = MagicMock()
        lista_final.__iter__.return_value = iter([])
        lista_final.count.return_value = 0

        queryset_base = MagicMock()
        mock_usuario.objects.select_related.return_value.order_by.return_value = queryset_base
        queryset_base.filter.return_value.filter.return_value = lista_final
        mock_rol.objects.filter.return_value.order_by.return_value = []

        request = self._fake_request_autenticado(data={"rol": "PRODUCTOR", "estado": "activo"})
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 200)
        queryset_base.filter.assert_called_once_with(rol__codigo="PRODUCTOR")
        queryset_base.filter.return_value.filter.assert_called_once_with(activo=True)

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_rol_delega_en_cambiar_rol_usuario_y_redirige(
        self, mock_usuario, mock_rol, _mock_check, mock_cambiar_rol
    ):
        """
        Desde HU04-ST5 (SCRUM-120), la vista ya no actualiza el rol
        directamente: delega en `gestion_roles.cambiar_rol_usuario`, que
        es quien aplica la regla de "no dejar el sistema sin
        administradores" y registra la bitácora de auditoría (RF28).
        """
        from usuarios.views import panel_administracion_usuarios

        usuario_existente = MagicMock(id="u1", rol_id=1, nombres="Ana", apellidos="Gómez")
        nuevo_rol = MagicMock(id=2, nombre="Administrador")
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_rol.objects.filter.return_value.first.return_value = nuevo_rol
        mock_cambiar_rol.return_value = (usuario_existente, MagicMock(id=99))

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "u1", "nuevo_rol": "ADMINISTRADOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_usuarios"))
        mock_cambiar_rol.assert_called_once()
        args, kwargs = mock_cambiar_rol.call_args
        self.assertEqual(args[0], usuario_existente)
        self.assertEqual(args[1], nuevo_rol)

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_al_mismo_rol_no_rompe(self, mock_usuario, mock_rol, _mock_check, mock_cambiar_rol):
        """Cuando `cambiar_rol_usuario` detecta que no hubo cambio real, devuelve bitácora None."""
        from usuarios.views import panel_administracion_usuarios

        usuario_existente = MagicMock(id="u1", rol_id=1, nombres="Ana", apellidos="Gómez")
        rol_sin_cambios = MagicMock(id=1, nombre="Productor")
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_rol.objects.filter.return_value.first.return_value = rol_sin_cambios
        mock_cambiar_rol.return_value = (usuario_existente, None)

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "u1", "nuevo_rol": "PRODUCTOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_con_usuario_o_rol_invalido_no_rompe(
        self, mock_usuario, mock_rol, _mock_check, mock_cambiar_rol
    ):
        from usuarios.views import panel_administracion_usuarios

        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_rol.objects.filter.return_value.first.return_value = MagicMock()

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "no-existe", "nuevo_rol": "ADMINISTRADOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_usuarios"))
        mock_cambiar_rol.assert_not_called()

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_cuando_quedaria_sin_administradores_muestra_error(
        self, mock_usuario, mock_rol, _mock_check, mock_cambiar_rol
    ):
        """RF28: si cambiar_rol_usuario rechaza el cambio, la vista no debe romperse (500)."""
        from usuarios.gestion_roles import CambioRolInvalido
        from usuarios.views import panel_administracion_usuarios

        usuario_existente = MagicMock(id="admin-1", rol_id=1, nombres="Carlos", apellidos="Pérez")
        otro_rol = MagicMock(id=2, nombre="Productor / Comercializador")
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_rol.objects.filter.return_value.first.return_value = otro_rol
        mock_cambiar_rol.side_effect = CambioRolInvalido("el sistema se quedaría sin administradores")

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "admin-1", "nuevo_rol": "PRODUCTOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_usuarios"))


class GestionRolesTests(TestCase):
    """
    Pruebas para HU04-ST5 (SCRUM-120): `gestion_roles.cambiar_rol_usuario`,
    la función que centraliza la reasignación de rol, la restricción de
    "no dejar el sistema sin administradores" (RF28) y el registro en
    la bitácora de auditoría.

    `Usuario` y `Rol` son managed=False y se mockean (igual que en el
    resto del archivo). `BitacoraCambioRol` sí es managed=True — aquí
    se deja escribir de verdad en la base de datos de pruebas, para
    confirmar que la auditoría efectivamente queda registrada.
    """

    def _fake_usuario(self, rol_codigo, activo=True, correo="usuario@example.com"):
        usuario = MagicMock()
        usuario.id = uuid.uuid4()
        usuario.correo = correo
        usuario.activo = activo
        usuario.rol = MagicMock(codigo=rol_codigo)
        usuario.rol_id = rol_codigo  # alcanza para las comparaciones de igualdad de este módulo
        return usuario

    def _fake_rol(self, codigo):
        rol = MagicMock()
        rol.id = codigo
        rol.codigo = codigo
        return rol

    @patch("usuarios.gestion_roles.Usuario")
    def test_cambio_normal_guarda_y_crea_entrada_de_bitacora(self, _mock_usuario_model):
        from usuarios.gestion_roles import cambiar_rol_usuario
        from usuarios.models import BitacoraCambioRol

        usuario = self._fake_usuario(rol_codigo="PRODUCTOR", correo="ana@example.com")
        nuevo_rol = self._fake_rol("COMPRADOR")

        usuario_resultado, entrada = cambiar_rol_usuario(
            usuario, nuevo_rol, realizado_por=None, ip_address="127.0.0.1"
        )

        self.assertIs(usuario_resultado, usuario)
        self.assertIsNotNone(entrada)
        usuario.save.assert_called_once_with(update_fields=["rol"])
        self.assertEqual(usuario.rol, nuevo_rol)

        self.assertEqual(BitacoraCambioRol.objects.count(), 1)
        registro = BitacoraCambioRol.objects.first()
        self.assertEqual(registro.usuario_correo, "ana@example.com")
        self.assertEqual(registro.rol_anterior, "PRODUCTOR")
        self.assertEqual(registro.rol_nuevo, "COMPRADOR")
        self.assertEqual(registro.ip_address, "127.0.0.1")
        self.assertIsNone(registro.realizado_por_correo)

    @patch("usuarios.gestion_roles.Usuario")
    def test_cambio_registra_quien_lo_realizo(self, _mock_usuario_model):
        from usuarios.gestion_roles import cambiar_rol_usuario
        from usuarios.models import BitacoraCambioRol

        usuario = self._fake_usuario(rol_codigo="PRODUCTOR")
        nuevo_rol = self._fake_rol("COMPRADOR")
        admin = self._fake_usuario(rol_codigo="ADMINISTRADOR", correo="admin@example.com")

        cambiar_rol_usuario(usuario, nuevo_rol, realizado_por=admin)

        registro = BitacoraCambioRol.objects.first()
        self.assertEqual(registro.realizado_por_correo, "admin@example.com")
        self.assertEqual(registro.realizado_por_id, admin.id)

    @patch("usuarios.gestion_roles.Usuario")
    def test_cambio_al_mismo_rol_no_hace_nada(self, _mock_usuario_model):
        from usuarios.gestion_roles import cambiar_rol_usuario
        from usuarios.models import BitacoraCambioRol

        rol_actual = self._fake_rol("PRODUCTOR")
        usuario = self._fake_usuario(rol_codigo="PRODUCTOR")
        usuario.rol_id = rol_actual.id

        usuario_resultado, entrada = cambiar_rol_usuario(usuario, rol_actual)

        self.assertIsNone(entrada)
        usuario.save.assert_not_called()
        self.assertEqual(BitacoraCambioRol.objects.count(), 0)

    @patch("usuarios.gestion_roles.Usuario")
    def test_bloquea_dejar_el_sistema_sin_administradores(self, mock_usuario_model):
        from usuarios.gestion_roles import CambioRolInvalido, cambiar_rol_usuario
        from usuarios.models import BitacoraCambioRol

        usuario = self._fake_usuario(rol_codigo="ADMINISTRADOR", activo=True)
        nuevo_rol = self._fake_rol("PRODUCTOR")

        # No queda ningún otro administrador activo aparte de `usuario`.
        mock_usuario_model.objects.filter.return_value.exclude.return_value.exists.return_value = False

        with self.assertRaises(CambioRolInvalido):
            cambiar_rol_usuario(usuario, nuevo_rol)

        usuario.save.assert_not_called()
        self.assertEqual(BitacoraCambioRol.objects.count(), 0)

    @patch("usuarios.gestion_roles.Usuario")
    def test_permite_reasignar_administrador_si_hay_otro_activo(self, mock_usuario_model):
        from usuarios.gestion_roles import cambiar_rol_usuario

        usuario = self._fake_usuario(rol_codigo="ADMINISTRADOR", activo=True, correo="admin1@example.com")
        nuevo_rol = self._fake_rol("PRODUCTOR")

        mock_usuario_model.objects.filter.return_value.exclude.return_value.exists.return_value = True

        usuario_resultado, entrada = cambiar_rol_usuario(usuario, nuevo_rol)

        self.assertIsNotNone(entrada)
        usuario.save.assert_called_once()

    @patch("usuarios.gestion_roles.Usuario")
    def test_administrador_inactivo_no_bloquea_el_cambio(self, mock_usuario_model):
        from usuarios.gestion_roles import cambiar_rol_usuario

        usuario = self._fake_usuario(rol_codigo="ADMINISTRADOR", activo=False, correo="admin2@example.com")
        nuevo_rol = self._fake_rol("PRODUCTOR")

        usuario_resultado, entrada = cambiar_rol_usuario(usuario, nuevo_rol)

        self.assertIsNotNone(entrada)
        # La función ni siquiera debería haber consultado Usuario.objects:
        # el chequeo de 'activo' corta antes de llegar ahí.
        mock_usuario_model.objects.filter.assert_not_called()


class ActualizarRolUsuarioApiTests(TestCase):
    """
    Pruebas para HU04-ST5 (SCRUM-120): endpoint de API
    PUT/PATCH /api/users/<id>/role.
    """

    def _patch_auth(self, role_code="ADMINISTRADOR", email="admin@example.com"):
        fake_user = MagicMock(email=email)
        fake_token = {"role_code": role_code}
        return patch(
            "usuarios.permissions.JWTAuthentication.authenticate",
            return_value=(fake_user, fake_token),
        )

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_put_exitoso_devuelve_200_con_datos_actualizados(
        self, mock_usuario, mock_rol, _mock_check, mock_cambiar_rol
    ):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        usuario_existente = MagicMock(id="u1", correo="ana@example.com")
        usuario_existente.rol.codigo = "COMPRADOR"
        nuevo_rol = MagicMock(codigo="COMPRADOR")
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_usuario.objects.filter.return_value.first.return_value = MagicMock()  # realizado_por
        mock_rol.objects.filter.return_value.first.return_value = nuevo_rol
        mock_cambiar_rol.return_value = (usuario_existente, MagicMock(id=5))

        with self._patch_auth():
            request = RequestFactory().put(
                "/api/users/u1/role", data=json.dumps({"rol": "comprador"}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["usuario"]["rol"], "COMPRADOR")
        self.assertEqual(body["auditoria_id"], 5)
        # El código se normaliza a mayúsculas antes de buscar el rol.
        mock_rol.objects.filter.assert_called_once_with(codigo="COMPRADOR", activo=True, requiere_cuenta=True)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Usuario")
    def test_usuario_inexistente_devuelve_404(self, mock_usuario, _mock_check):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = None

        with self._patch_auth():
            request = RequestFactory().put(
                "/api/users/no-existe/role", data=json.dumps({"rol": "COMPRADOR"}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="no-existe")

        self.assertEqual(response.status_code, 404)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_rol_invalido_devuelve_400(self, mock_usuario, mock_rol, _mock_check):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = MagicMock()
        mock_rol.objects.filter.return_value.first.return_value = None

        with self._patch_auth():
            request = RequestFactory().put(
                "/api/users/u1/role", data=json.dumps({"rol": "NO_EXISTE"}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 400)

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_dejaria_sin_administradores_devuelve_409(self, mock_usuario, mock_rol, _mock_check, mock_cambiar_rol):
        from django.test import RequestFactory
        from usuarios.gestion_roles import CambioRolInvalido
        from usuarios.views import actualizar_rol_usuario_api

        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = MagicMock()
        mock_rol.objects.filter.return_value.first.return_value = MagicMock()
        mock_cambiar_rol.side_effect = CambioRolInvalido("sin administradores")

        with self._patch_auth():
            request = RequestFactory().put(
                "/api/users/u1/role", data=json.dumps({"rol": "PRODUCTOR"}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 409)

    @patch("usuarios.permissions.usuario_tiene_permiso")
    def test_sin_permiso_devuelve_403(self, mock_check):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        mock_check.return_value = False

        with self._patch_auth(role_code="COMPRADOR"):
            request = RequestFactory().put(
                "/api/users/u1/role", data=json.dumps({"rol": "ADMINISTRADOR"}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 403)

    def test_metodo_get_no_permitido(self):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        request = RequestFactory().get("/api/users/u1/role")
        response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 405)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_cuerpo_sin_rol_devuelve_400(self, _mock_check):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        with self._patch_auth():
            request = RequestFactory().put(
                "/api/users/u1/role", data=json.dumps({}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 400)


# ==============================================================================
# HU04-ST6 (SCRUM-127): Pruebas de seguridad y escalamiento de privilegios
# ==============================================================================
#
# A diferencia del resto del archivo — donde cada subtarea mockea
# `usuario_tiene_permiso` para aislar la pieza que está probando — las
# pruebas de esta sección deliberadamente NO lo mockean: dejan correr
# la función real y solo mockean su dependencia de más bajo nivel
# (`RolPermiso`, la tabla de la matriz RBAC), simulando la matriz TAL
# COMO está sembrada hoy en Supabase (HU04-ST1). Así se ejercita la
# cadena completa de autorización de punta a punta — vista → decorador
# → usuario_tiene_permiso → consulta a la matriz — igual que en
# producción, en vez de solo confiar en que cada pieza por separado
# está bien.

# Fotografía de la matriz RBAC vigente en Supabase al momento de esta
# prueba (consultada por SQL contra rol_permisos/roles/permisos). Si la
# matriz cambia en Supabase (HU04-ST1 la administra ahí, no aquí), esta
# constante debe actualizarse junto con el seed real para que la prueba
# siga siendo representativa.
MATRIZ_RBAC_VIGENTE = {
    "ADMINISTRADOR": {
        "asociaciones.gestionar", "auditoria.consultar", "busqueda_global.usar",
        "catalogo.ver_publico", "catalogos_maestros.administrar", "catalogos_maestros.consultar",
        "ficha_digital.ver_completa", "ficha_digital.ver_publica", "fincas.actualizar",
        "fincas.consultar", "fincas.crear", "indicadores.ver_dashboard", "perfil.editar_propio",
        "perfil.ver_propio", "productores.actualizar", "productores.consultar", "productores.crear",
        "productores.inactivar", "reportes.generar", "usuarios.administrar",
    },
    "ASOCIACION": {
        "busqueda_global.usar", "catalogo.publicar_lote", "catalogo.ver_publico",
        "catalogos_maestros.administrar", "catalogos_maestros.consultar", "cosechas.consultar",
        "ficha_digital.ver_completa", "ficha_digital.ver_publica", "fincas.actualizar",
        "fincas.consultar", "fincas.crear", "indicadores.ver_dashboard", "lotes.cambiar_estado",
        "lotes.consultar", "negociaciones.gestionar", "perfil.editar_propio", "perfil.ver_propio",
        "productores.actualizar", "productores.consultar", "productores.crear",
        "productores.inactivar", "reportes.generar", "ventas.registrar",
    },
    "COMPRADOR": {
        "catalogo.ver_publico", "catalogos_maestros.consultar", "ficha_digital.ver_publica",
        "manifestaciones_interes.crear", "perfil.editar_propio", "perfil.ver_propio",
    },
    "CONSULTA_PUBLICA": {
        "catalogo.ver_publico", "catalogos_maestros.consultar", "ficha_digital.ver_publica",
    },
    "OPERARIO_CAMPO": {
        "catalogos_maestros.consultar", "cosechas.consultar", "cosechas.crear", "lotes.consultar",
        "lotes.crear", "perfil.editar_propio", "perfil.ver_propio", "trazabilidad.registrar_calidad",
        "trazabilidad.registrar_etapa",
    },
    "PRODUCTOR": {
        "busqueda_global.usar", "catalogo.publicar_lote", "catalogo.ver_publico",
        "catalogos_maestros.consultar", "cosechas.consultar", "cosechas.crear",
        "ficha_digital.ver_completa", "ficha_digital.ver_publica", "fincas.actualizar",
        "fincas.consultar", "fincas.crear", "indicadores.ver_dashboard", "lotes.cambiar_estado",
        "lotes.consultar", "lotes.crear", "negociaciones.gestionar", "perfil.editar_propio",
        "perfil.ver_propio", "productores.actualizar", "productores.consultar", "productores.crear",
        "reportes.generar", "trazabilidad.registrar_calidad", "trazabilidad.registrar_etapa",
        "ventas.registrar",
    },
}

ROLES_RESTRINGIDOS = ["PRODUCTOR", "ASOCIACION", "COMPRADOR", "OPERARIO_CAMPO", "CONSULTA_PUBLICA"]

TODOS_LOS_PERMISOS = sorted({permiso for permisos in MATRIZ_RBAC_VIGENTE.values() for permiso in permisos})


def _mockear_matriz_real(mock_rol_permiso, matriz=MATRIZ_RBAC_VIGENTE):
    """
    Hace que `RolPermiso.objects.filter(...).exists()` responda igual
    que lo haría contra la tabla real de Supabase para la `matriz`
    dada, sin tocar ninguna base de datos — permite probar
    `usuario_tiene_permiso()` (y todo lo que depende de ella) de
    extremo a extremo con datos de RBAC realistas.
    """

    def filtro_falso(**kwargs):
        rol_codigo = kwargs.get("rol__codigo")
        codigos_permiso = kwargs.get("permiso__codigo__in", [])
        permisos_del_rol = matriz.get(rol_codigo, set())
        resultado = MagicMock()
        resultado.exists.return_value = any(c in permisos_del_rol for c in codigos_permiso)
        return resultado

    mock_rol_permiso.objects.filter.side_effect = filtro_falso


class MatrizPermisosSecurityTests(TestCase):
    """
    HU04-ST6 (SCRUM-127), parte 1: confirmar que los permisos asignados
    se aplican correctamente a cada perfil (RNF06).

    Recorre TODA la matriz rol × permiso vigente en Supabase (6 roles,
    31 permisos = 186 combinaciones) y verifica que
    `usuario_tiene_permiso()` concede exactamente lo que la matriz real
    concede — ni más (fuga de privilegios) ni menos (una funcionalidad
    legítima bloqueada por error).
    """

    @patch("usuarios.models.RolPermiso")
    def test_usuario_tiene_permiso_coincide_con_la_matriz_real_para_cada_rol_y_permiso(self, mock_rol_permiso):
        from usuarios.permissions import usuario_tiene_permiso

        _mockear_matriz_real(mock_rol_permiso)

        for rol_codigo, permisos_concedidos in MATRIZ_RBAC_VIGENTE.items():
            for permiso_codigo in TODOS_LOS_PERMISOS:
                with self.subTest(rol=rol_codigo, permiso=permiso_codigo):
                    esperado = permiso_codigo in permisos_concedidos
                    self.assertEqual(usuario_tiene_permiso(rol_codigo, permiso_codigo), esperado)

    @patch("usuarios.models.RolPermiso")
    def test_solo_administrador_tiene_usuarios_administrar(self, mock_rol_permiso):
        """
        El permiso que protege todo HU04-ST4/ST5 (gestión de usuarios y
        roles) es, hoy, exclusivo de ADMINISTRADOR. Esta prueba lo deja
        explícito y por separado del recorrido general de arriba,
        porque es justo la condición de la que depende toda la
        prevención de escalamiento de privilegios de esta subtarea.
        """
        from usuarios.permissions import usuario_tiene_permiso

        _mockear_matriz_real(mock_rol_permiso)

        self.assertTrue(usuario_tiene_permiso("ADMINISTRADOR", "usuarios.administrar"))
        for rol_restringido in ROLES_RESTRINGIDOS:
            with self.subTest(rol=rol_restringido):
                self.assertFalse(usuario_tiene_permiso(rol_restringido, "usuarios.administrar"))


class EscalamientoPrivilegiosSecurityTests(TestCase):
    """
    HU04-ST6 (SCRUM-127), parte 2: verificar que un usuario con un rol
    restringido no pueda forzar el acceso a los módulos administrativos
    de HU04-ST4/ST5 (RNF21) — ni por la pantalla web ni por la API —,
    aunque intente pedir directamente el rol de Administrador.
    """

    def _fake_request_sesion(self, rol, path="/admin/usuarios/"):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        request = RequestFactory().get(path)
        request.user = MagicMock(is_authenticated=True)
        request.session = {"rol": rol}
        request._messages = FallbackStorage(request)
        return request

    def _patch_auth_jwt(self, rol_codigo, email="usuario@example.com"):
        fake_user = MagicMock(email=email)
        fake_token = {"role_code": rol_codigo}
        return patch(
            "usuarios.permissions.JWTAuthentication.authenticate",
            return_value=(fake_user, fake_token),
        )

    # --- Pantalla web de HU04-ST4 (panel_administracion_usuarios) ---

    @patch("usuarios.models.RolPermiso")
    def test_rol_restringido_no_accede_al_panel_de_administracion(self, mock_rol_permiso):
        from usuarios.views import panel_administracion_usuarios

        _mockear_matriz_real(mock_rol_permiso)

        for rol_restringido in ROLES_RESTRINGIDOS:
            with self.subTest(rol=rol_restringido):
                request = self._fake_request_sesion(rol_restringido)
                response = panel_administracion_usuarios(request)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse("home"))

    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.models.RolPermiso")
    def test_administrador_si_accede_al_panel_de_administracion(self, mock_rol_permiso, mock_usuario, mock_rol):
        from usuarios.views import panel_administracion_usuarios

        _mockear_matriz_real(mock_rol_permiso)
        lista_vacia = MagicMock()
        lista_vacia.__iter__.return_value = iter([])
        lista_vacia.count.return_value = 0
        mock_usuario.objects.select_related.return_value.order_by.return_value = lista_vacia
        mock_rol.objects.filter.return_value.order_by.return_value = []

        request = self._fake_request_sesion("ADMINISTRADOR")
        with patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso") as mock_check_menu:
            mock_check_menu.side_effect = lambda rol, permiso: rol == "ADMINISTRADOR"
            response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 200)

    # --- Endpoint de API de HU04-ST5 (actualizar_rol_usuario_api) ---

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.models.RolPermiso")
    def test_rol_restringido_no_puede_autoasignarse_administrador_via_api(self, mock_rol_permiso, mock_cambiar_rol):
        """
        El intento de escalamiento más directo: una cuenta con un rol
        restringido llama al endpoint de reasignación pidiendo
        'ADMINISTRADOR'. Debe rechazarse en la capa de autorización,
        antes de que la petición llegue siquiera a mirar el usuario o
        el rol destino — por eso se verifica que `cambiar_rol_usuario`
        nunca se invoca.
        """
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        _mockear_matriz_real(mock_rol_permiso)

        for rol_restringido in ROLES_RESTRINGIDOS:
            with self.subTest(rol=rol_restringido):
                with self._patch_auth_jwt(rol_restringido):
                    request = RequestFactory().put(
                        "/api/users/cualquier-id/role",
                        data=json.dumps({"rol": "ADMINISTRADOR"}),
                        content_type="application/json",
                    )
                    response = actualizar_rol_usuario_api(request, user_id="cualquier-id")

                self.assertEqual(response.status_code, 403)

        mock_cambiar_rol.assert_not_called()

    @patch("usuarios.views.cambiar_rol_usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.models.RolPermiso")
    def test_administrador_si_puede_reasignar_roles_via_api(
        self, mock_rol_permiso, mock_usuario, mock_rol, mock_cambiar_rol
    ):
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        _mockear_matriz_real(mock_rol_permiso)
        usuario_existente = MagicMock(id="u1", correo="otro@example.com")
        usuario_existente.rol.codigo = "COMPRADOR"
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_usuario.objects.filter.return_value.first.return_value = MagicMock()
        mock_rol.objects.filter.return_value.first.return_value = MagicMock(codigo="COMPRADOR")
        mock_cambiar_rol.return_value = (usuario_existente, MagicMock(id=1))

        with self._patch_auth_jwt("ADMINISTRADOR"):
            request = RequestFactory().put(
                "/api/users/u1/role", data=json.dumps({"rol": "COMPRADOR"}), content_type="application/json"
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 200)
        mock_cambiar_rol.assert_called_once()

    @patch("usuarios.models.RolPermiso")
    def test_rol_falsificado_en_el_cuerpo_no_otorga_acceso(self, mock_rol_permiso):
        """
        Defensa en profundidad: la autorización depende exclusivamente
        del claim 'role_code' firmado dentro del JWT (resuelto por
        `permiso_requerido` vía `request.auth`), nunca de nada que
        venga en el cuerpo de la petición. Un cliente con un token de
        COMPRADOR no gana nada incluyendo datos adicionales en el JSON
        — el rechazo ocurre antes de que la vista siquiera lea el
        cuerpo de la petición.
        """
        from django.test import RequestFactory
        from usuarios.views import actualizar_rol_usuario_api

        _mockear_matriz_real(mock_rol_permiso)

        with self._patch_auth_jwt("COMPRADOR"):
            request = RequestFactory().put(
                "/api/users/u1/role",
                data=json.dumps({"rol": "ADMINISTRADOR", "role_code": "ADMINISTRADOR", "es_admin": True}),
                content_type="application/json",
            )
            response = actualizar_rol_usuario_api(request, user_id="u1")

        self.assertEqual(response.status_code, 403)


class RegistroAutorregistroRolesTests(TestCase):
    """
    Según CU10 del documento de Casos de Uso, una Asociación no se
    autorregistra: la crea el Administrador del Sistema junto con su
    propia cuenta administradora (RN02). Antes de este ajuste,
    `_ROLES_NO_AUTORREGISTRABLES` en registro_api() solo excluía a
    ADMINISTRADOR; ahora también excluye a ASOCIACION — el formulario
    público (templates/usuarios/registro.html) ya no ofrece esa opción,
    pero sin este rechazo en el backend cualquiera podría seguir
    autoasignándose el rol llamando directamente al endpoint.
    """

    def _cuerpo_valido(self, rol):
        return json.dumps({
            "correo": "nuevo@example.com",
            "contraseña": "ClaveSegura123",
            "nombres": "Ana",
            "apellidos": "Gómez",
            "tipo_documento": "CC",
            "numero_documento": "123456789",
            "rol": rol,
        })

    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_asociacion_no_puede_autorregistrarse(self, mock_tipo_doc, mock_rol):
        from django.test import RequestFactory
        from usuarios.views import registro_api

        mock_tipo_doc.objects.filter.return_value.first.return_value = MagicMock(codigo="CC")
        mock_rol.objects.filter.return_value.first.return_value = MagicMock(codigo="ASOCIACION")

        request = RequestFactory().post(
            "/api/auth/register", data=self._cuerpo_valido("ASOCIACION"), content_type="application/json"
        )
        response = registro_api(request)

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertIn("rol", body.get("campos", {}))

    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_administrador_sigue_sin_poder_autorregistrarse(self, mock_tipo_doc, mock_rol):
        """Confirma que el ajuste no debilitó la restricción que ya existía para ADMINISTRADOR."""
        from django.test import RequestFactory
        from usuarios.views import registro_api

        mock_tipo_doc.objects.filter.return_value.first.return_value = MagicMock(codigo="CC")
        mock_rol.objects.filter.return_value.first.return_value = MagicMock(codigo="ADMINISTRADOR")

        request = RequestFactory().post(
            "/api/auth/register", data=self._cuerpo_valido("ADMINISTRADOR"), content_type="application/json"
        )
        response = registro_api(request)

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.content)
        self.assertIn("rol", body.get("campos", {}))


def _fake_usuario_registrado(user_id, correo, nombres="Ana", apellidos="Gómez",
                              tipo_documento_codigo="CC", numero_documento="123456789",
                              telefono="3101234567", rol_codigo="PRODUCTOR", activo=True):
    """Doble de `Usuario` tal como quedaría tras el trigger de Supabase (ver registro_api, paso 10)."""
    perfil = MagicMock()
    perfil.id = user_id
    perfil.correo = correo
    perfil.nombres = nombres
    perfil.apellidos = apellidos
    perfil.numero_documento = numero_documento
    perfil.telefono = telefono
    perfil.activo = activo
    perfil.tipo_documento.codigo = tipo_documento_codigo
    perfil.rol.codigo = rol_codigo
    perfil.creado_en = timezone.now()
    return perfil


class RegistroUsuarioApiTests(TestCase):
    """
    HU01-ST6 (SCRUM-63): pruebas unitarias e integrales del flujo de
    registro de usuarios (POST /api/auth/register, ver registro_api()).

    Cubre los criterios de aceptación de HU-01:
      - "Se valida que el correo sea único" -> duplicado en BD propia y
        duplicado detectado por Supabase Auth (condición de carrera).
      - "La contraseña se almacena cifrada" -> por diseño (ver docstring
        de usuarios/views.py) Django nunca guarda la contraseña: se
        reenvía únicamente a Supabase Auth, que la hashea con bcrypt.
        Se verifica aquí que (a) el modelo `Usuario` no tiene ningún
        campo de contraseña y (b) la respuesta de la API nunca la repite.
      - "Se confirma el registro" -> alta exitosa responde 201 con los
        datos reales leídos de vuelta desde `usuarios`.
      - Escenarios fallidos explícitos de la subtarea: correo duplicado,
        campos vacíos, contraseñas débiles.

    Se mockean `Rol`, `TipoDocumento`, `Usuario` y `get_supabase_client`
    porque los tres primeros son modelos `managed = False` (no existen
    en la base de datos de pruebas) y el cuarto es un servicio externo
    real (Supabase Auth) — mismo patrón que `AuthCredentialVerificationTests`
    y `RegistroAutorregistroRolesTests` en este mismo archivo.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse('api_registro')
        self.user_id = "22222222-2222-2222-2222-222222222222"

    def _cuerpo_valido(self, **overrides):
        """
        Payload con los MISMOS nombres de campo que envía el formulario
        real (templates/usuarios/registro.html + static/js/registro.js):
        first_name, last_name, email, phone, role, password — en inglés,
        salvo tipo_documento/numero_documento que sí van en español. Así
        la prueba ejercita de verdad la capa de alias (_ALIAS_CAMPO) que
        conecta el formulario HU01-ST2 con el endpoint HU01-ST3.
        """
        cuerpo = {
            "first_name": "Ana",
            "last_name": "Gómez",
            "email": "ana.gomez@example.com",
            "phone": "3101234567",
            "tipo_documento": "CC",
            "numero_documento": "123456789",
            "role": "PRODUCTOR",
            "password": "ClaveSegura123",
        }
        cuerpo.update(overrides)
        return json.dumps(cuerpo)

    def _mock_catalogos_validos(self, mock_tipo_doc, mock_rol, mock_usuario,
                                 tipo_documento_codigo="CC", rol_codigo="PRODUCTOR"):
        mock_tipo_doc.objects.filter.return_value.first.return_value = MagicMock(
            codigo=tipo_documento_codigo
        )
        mock_rol.objects.filter.return_value.first.return_value = MagicMock(codigo=rol_codigo)
        mock_usuario.objects.filter.return_value.exists.return_value = False

    # ------------------------------------------------------------------
    # Escenario exitoso — "alta de usuario correcta" / "se confirma el registro"
    # ------------------------------------------------------------------

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_exitoso_retorna_201_y_confirma_los_datos(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.return_value = MagicMock(
            user=_fake_auth_user(self.user_id, "ana.gomez@example.com"),
            session=MagicMock(),  # sesión ya activa: no requiere verificación de correo
        )
        mock_usuario.objects.select_related.return_value.get.return_value = (
            _fake_usuario_registrado(self.user_id, "ana.gomez@example.com")
        )

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["usuario"]["correo"], "ana.gomez@example.com")
        self.assertEqual(body["usuario"]["rol"], "PRODUCTOR")
        self.assertEqual(body["usuario"]["tipo_documento"], "CC")
        self.assertFalse(body["requiere_verificacion_correo"])

        # La contraseña viaja a Supabase (quien la hashea), nunca se guarda
        # ni se repite en la respuesta propia.
        mock_get_client.return_value.auth.sign_up.assert_called_once()
        payload_enviado = mock_get_client.return_value.auth.sign_up.call_args[0][0]
        self.assertEqual(payload_enviado["password"], "ClaveSegura123")
        self.assertNotIn("contraseña", body["usuario"])
        self.assertNotIn("password", body["usuario"])

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_exitoso_requiere_verificacion_si_supabase_no_da_sesion(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """Si Supabase exige confirmar el correo, sign_up() responde sin `session`."""
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.return_value = MagicMock(
            user=_fake_auth_user(self.user_id, "ana.gomez@example.com"),
            session=None,
        )
        mock_usuario.objects.select_related.return_value.get.return_value = (
            _fake_usuario_registrado(self.user_id, "ana.gomez@example.com")
        )

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["requiere_verificacion_correo"])

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_acepta_nombres_de_campo_canonicos_en_espanol(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """La API también debe aceptar los nombres de campo canónicos (correo, contraseña, nombres, apellidos, rol)."""
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.return_value = MagicMock(
            user=_fake_auth_user(self.user_id, "canonico@example.com"), session=MagicMock()
        )
        mock_usuario.objects.select_related.return_value.get.return_value = (
            _fake_usuario_registrado(self.user_id, "canonico@example.com")
        )

        cuerpo = json.dumps({
            "correo": "canonico@example.com",
            "contraseña": "ClaveSegura123",
            "nombres": "Ana",
            "apellidos": "Gómez",
            "tipo_documento": "CC",
            "numero_documento": "987654321",
            "rol": "PRODUCTOR",
        })
        response = self.client.post(self.url, data=cuerpo, content_type="application/json")
        self.assertEqual(response.status_code, 201)

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_alias_comercializador_se_mapea_a_productor(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """Compatibilidad hacia atrás: clientes que aún envíen "COMERCIALIZADOR" deben mapearse a PRODUCTOR."""
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.return_value = MagicMock(
            user=_fake_auth_user(self.user_id, "ana.gomez@example.com"), session=MagicMock()
        )
        mock_usuario.objects.select_related.return_value.get.return_value = (
            _fake_usuario_registrado(self.user_id, "ana.gomez@example.com")
        )

        response = self.client.post(
            self.url, data=self._cuerpo_valido(role="COMERCIALIZADOR"), content_type="application/json"
        )

        self.assertEqual(response.status_code, 201)
        # El código de rol consultado en el catálogo debió ser PRODUCTOR, no COMERCIALIZADOR.
        codigos_consultados = [
            llamada.kwargs.get("codigo") for llamada in mock_rol.objects.filter.call_args_list
        ]
        self.assertIn("PRODUCTOR", codigos_consultados)

    # ------------------------------------------------------------------
    # RNF04 — "La contraseña se almacena cifrada"
    # ------------------------------------------------------------------

    def test_modelo_usuario_no_tiene_campo_de_contrasena(self):
        """
        Guarda estructural del criterio de aceptación: Django nunca debe
        llegar a tener un campo propio para la contraseña en texto plano
        ni en ninguna otra forma — se delega por completo a Supabase Auth
        (ver docstring de HU01-ST4 en usuarios/views.py).
        """
        nombres_de_campos = {campo.name for campo in Usuario._meta.get_fields()}
        self.assertNotIn("contraseña", nombres_de_campos)
        self.assertNotIn("password", nombres_de_campos)
        self.assertNotIn("contrasena", nombres_de_campos)

    # ------------------------------------------------------------------
    # "Se valida que el correo sea único"
    # ------------------------------------------------------------------

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_correo_duplicado_en_bd_propia_retorna_409(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        mock_tipo_doc.objects.filter.return_value.first.return_value = MagicMock(codigo="CC")
        mock_rol.objects.filter.return_value.first.return_value = MagicMock(codigo="PRODUCTOR")
        mock_usuario.objects.filter.return_value.exists.return_value = True  # correo ya registrado

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 409)
        self.assertIn("correo", response.json()["error"].lower())
        # No debe llamarse a Supabase si ya se detectó el duplicado localmente.
        mock_get_client.return_value.auth.sign_up.assert_not_called()

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_correo_duplicado_detectado_por_supabase_retorna_409(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """Condición de carrera: pasa la validación local pero Supabase Auth ya tiene ese correo."""
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.side_effect = AuthApiError(
            "User already registered", 422, "user_already_exists"
        )

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 409)
        self.assertIn("correo", response.json()["error"].lower())

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_numero_documento_duplicado_retorna_409(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        mock_tipo_doc.objects.filter.return_value.first.return_value = MagicMock(codigo="CC")
        mock_rol.objects.filter.return_value.first.return_value = MagicMock(codigo="PRODUCTOR")
        # Primera llamada (correo): no existe. Segunda llamada (documento): sí existe.
        mock_usuario.objects.filter.return_value.exists.side_effect = [False, True]

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 409)
        self.assertIn("documento", response.json()["error"].lower())
        mock_get_client.return_value.auth.sign_up.assert_not_called()

    # ------------------------------------------------------------------
    # "Campos vacíos"
    # ------------------------------------------------------------------

    def test_registro_campo_faltante_retorna_400_con_detalle(self):
        """Falta `numero_documento`: debe rechazarse con 400 antes de tocar cualquier modelo o Supabase."""
        cuerpo = json.loads(self._cuerpo_valido())
        del cuerpo["numero_documento"]

        response = self.client.post(self.url, data=json.dumps(cuerpo), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("numero_documento", response.json()["campos"])
        self.assertNotIn("tipo_documento", response.json()["campos"])

    def test_registro_campos_vacios_en_blanco_retorna_400(self):
        """Campos presentes pero en blanco ("") deben tratarse igual que ausentes."""
        response = self.client.post(
            self.url,
            data=self._cuerpo_valido(first_name="", last_name="", email="", password=""),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        campos = response.json()["campos"]
        self.assertIn("nombres", campos)
        self.assertIn("apellidos", campos)
        self.assertIn("correo", campos)
        self.assertIn("contraseña", campos)

    def test_registro_cuerpo_completamente_vacio_retorna_400_con_todos_los_campos(self):
        response = self.client.post(self.url, data=json.dumps({}), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        campos = response.json()["campos"]
        for campo_requerido in ("correo", "contraseña", "nombres", "apellidos", "tipo_documento", "numero_documento", "rol"):
            self.assertIn(campo_requerido, campos)

    def test_registro_cuerpo_no_es_json_valido_retorna_400(self):
        response = self.client.post(self.url, data="esto no es json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_registro_cuerpo_json_no_es_un_objeto_retorna_400(self):
        response = self.client.post(self.url, data=json.dumps(["no", "es", "un", "objeto"]), content_type="application/json")
        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------------
    # "Contraseñas débiles"
    # ------------------------------------------------------------------

    def test_registro_contrasena_corta_rechazada_localmente_retorna_400(self):
        """Política local orientativa: mínimo 6 caracteres (paso 3 de registro_api)."""
        response = self.client.post(
            self.url, data=self._cuerpo_valido(password="abc12"), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("contraseña", response.json()["campos"])

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_contrasena_debil_segun_supabase_retorna_400(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """Cumple el mínimo local (6+) pero Supabase Auth la rechaza por su propia política de seguridad."""
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.side_effect = AuthApiError(
            "Password is too weak", 422, "weak_password"
        )

        response = self.client.post(
            self.url, data=self._cuerpo_valido(password="123456"), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("contraseña", response.json()["campos"])

    # ------------------------------------------------------------------
    # Otras validaciones del flujo (formato, catálogos, método HTTP, disponibilidad)
    # ------------------------------------------------------------------

    def test_registro_correo_con_formato_invalido_retorna_400(self):
        response = self.client.post(
            self.url, data=self._cuerpo_valido(email="no-es-un-correo"), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("correo", response.json()["campos"])

    def test_registro_telefono_con_formato_invalido_retorna_400(self):
        response = self.client.post(
            self.url, data=self._cuerpo_valido(phone="no-es-un-telefono"), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("telefono", response.json()["campos"])

    @patch("usuarios.views.TipoDocumento")
    def test_registro_tipo_documento_inexistente_retorna_400(self, mock_tipo_doc):
        mock_tipo_doc.objects.filter.return_value.first.return_value = None

        response = self.client.post(
            self.url, data=self._cuerpo_valido(tipo_documento="XX"), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tipo_documento", response.json()["campos"])

    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_rol_inexistente_en_catalogo_retorna_400(self, mock_tipo_doc, mock_rol):
        mock_tipo_doc.objects.filter.return_value.first.return_value = MagicMock(codigo="CC")
        mock_rol.objects.filter.return_value.first.return_value = None

        response = self.client.post(
            self.url, data=self._cuerpo_valido(role="ROL_QUE_NO_EXISTE"), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("rol", response.json()["campos"])

    def test_registro_metodo_get_no_permitido(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_con_supabase_no_configurado_retorna_503(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """Si faltan SUPABASE_URL/SUPABASE_ANON_KEY, get_supabase_client() lanza RuntimeError (ver supabase_client.py)."""
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.side_effect = RuntimeError("Faltan credenciales de Supabase")

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 503)

    @patch("usuarios.views.get_supabase_client")
    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.TipoDocumento")
    def test_registro_trigger_de_supabase_no_sincronizo_perfil_retorna_500(
        self, mock_tipo_doc, mock_rol, mock_usuario, mock_get_client
    ):
        """
        Caso borde de HU01-ST5 (manejo de errores): el alta en auth.users
        se completó pero el trigger `on_auth_user_created` no alcanzó a
        crear la fila en `usuarios` (paso 10 de registro_api).
        """
        self._mock_catalogos_validos(mock_tipo_doc, mock_rol, mock_usuario)
        mock_get_client.return_value.auth.sign_up.return_value = MagicMock(
            user=_fake_auth_user(self.user_id, "ana.gomez@example.com"), session=MagicMock()
        )
        mock_usuario.DoesNotExist = Exception
        mock_usuario.objects.select_related.return_value.get.side_effect = mock_usuario.DoesNotExist

        response = self.client.post(self.url, data=self._cuerpo_valido(), content_type="application/json")

        self.assertEqual(response.status_code, 500)


# ==============================================================================
# PRUEBAS HU02-ST6: SEGURIDAD DE SESIÓN Y PERSISTENCIA (QA)
# ==============================================================================

class SessionSecurityAndPersistenceTests(TestCase):
    """
    Pruebas automatizadas de QA y Seguridad para HU02-ST6:
    Seguridad de sesión y persistencia.

    Matriz de Cobertura de Criterios:
    1. Acceso a rutas privadas sin token válido:
       - Rechazo 401 si no hay cabecera Authorization en API protegida.
       - Rechazo 401 con esquema de autenticación distinto a Bearer.
       - Rechazo 401 con token malformado o payload ilegible.
       - Rechazo 401 con token firmado con clave secreta errónea / firma alterada.
       - Rechazo 403 Forbidden cuando el token es válido pero el rol carece del permiso RBAC.
       - Redirección 302 a login al intentar acceder a pantalla web protegida sin sesión.
       - Redirección 302 a home al acceder a pantalla web protegida con rol sin permisos.

    2. Caducidad del token (Expiration):
       - Access token con timestamp 'exp' vencido rechazado con 401.
       - Refresh token con timestamp 'exp' vencido rechazado con 401 ('token_not_valid').
       - Verificación de cumplimiento de tiempos de vida de tokens (ACCESS_TOKEN_LIFETIME = 60 min,
         REFRESH_TOKEN_LIFETIME = 1 día, BLACKLIST_AFTER_ROTATION = True).

    3. Cierre de sesión y persistencia:
       - Cierre de sesión web vía POST /logout/ destruye sesión de Django, limpia cookies
         e impide el acceso posterior a rutas protegidas.
       - Cierre de sesión web vía GET es rechazado de forma segura preservando la sesión (anti-CSRF).
       - Cierre de sesión API vía POST /api/auth/logout/ registra el refresh token en la
         lista negra (BlacklistedToken) e impide volver a refrescar tokens con él.
       - Persistencia de sesión web: verificación de expiración con y sin remember_me.

    4. Respuesta ante credenciales erróneas:
       - Contraseña incorrecta en POST /api/auth/login/ retorna 401 con mensaje genérico y sin tokens.
       - Correo inexistente en POST /api/auth/login/ retorna 401 con respuesta genérica idéntica (anti-enumeración RNF07).
       - Intentos fallidos incrementan progresivamente el registro de persistencia (RegistroIntentoLogin).
       - Quinto intento fallido activa el bloqueo temporal de cuenta (403 con 'locked': True).
       - Solicitud de login con campos vacíos retorna 400 Bad Request sin consultar backend.
    """

    def setUp(self):
        import jwt
        self.jwt = jwt
        self.client = Client()

        # URLs
        self.login_url = reverse("login")
        self.logout_url = reverse("logout")
        self.api_login_url = reverse("api_auth_login")
        self.api_logout_url = reverse("api_auth_logout")
        self.token_obtain_url = reverse("token_obtain_pair")
        self.token_refresh_url = reverse("token_refresh")
        self.admin_usuarios_url = reverse("admin_usuarios")
        self.test_user_id = "11111111-2222-3333-4444-555555555555"
        self.api_role_url = reverse("api_actualizar_rol_usuario", kwargs={"user_id": self.test_user_id})

        # Usuario de prueba en auth_user
        self.username = "seguridad_qa_user"
        self.email = "seguridad.qa@cafepergamo.com"
        self.password = "Pergamo2026*QA_Secure!"
        self.django_user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
            first_name="Validador",
            last_name="Seguridad",
        )

    # --------------------------------------------------------------------------
    # 1. Rutas privadas sin token válido
    # --------------------------------------------------------------------------

    def test_private_api_route_without_authorization_header_returns_401(self):
        """Verifica que invocar una API protegida sin header Authorization devuelva 401 Unauthorized."""
        response = self.client.put(
            self.api_role_url,
            data=json.dumps({"rol": "ADMINISTRADOR"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json().get("error"),
            "Se requiere un token de autenticación válido.",
        )

    def test_private_api_route_with_non_bearer_scheme_returns_401(self):
        """Verifica que un esquema de autenticación no soportado (ej. Basic o Token) sea rechazado con 401."""
        response = self.client.put(
            self.api_role_url,
            data=json.dumps({"rol": "ADMINISTRADOR"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
        )
        self.assertEqual(response.status_code, 401)

    def test_private_api_route_with_malformed_token_returns_401(self):
        """Verifica que un token JWT sintácticamente corrupto o truncado sea rechazado con 401."""
        response = self.client.put(
            self.api_role_url,
            data=json.dumps({"rol": "ADMINISTRADOR"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token.malformado.invalido123",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json().get("error"),
            "Se requiere un token de autenticación válido.",
        )

    def test_private_api_route_with_tampered_signature_returns_401(self):
        """Verifica que un token firmado con una clave secreta ilegítima sea rechazado con 401."""
        import time
        payload = {
            "token_type": "access",
            "user_id": str(self.django_user.id),
            "role_code": "ADMINISTRADOR",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "jti": str(uuid.uuid4()),
        }
        tampered_token = self.jwt.encode(payload, "clave-secreta-totalmente-falsa", algorithm="HS256")
        response = self.client.put(
            self.api_role_url,
            data=json.dumps({"rol": "ADMINISTRADOR"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {tampered_token}",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json().get("error"),
            "Se requiere un token de autenticación válido.",
        )

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_private_api_route_with_valid_token_lacking_rbac_permission_returns_403(self, mock_rbac):
        """Verifica que un token legítimo cuyo rol no posee el permiso exigido retorne 403 Forbidden."""
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(self.django_user)
        token["role_code"] = "PRODUCTOR"
        response = self.client.put(
            self.api_role_url,
            data=json.dumps({"rol": "ADMINISTRADOR"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {str(token)}",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json().get("error"),
            "No tiene permiso para acceder a este recurso.",
        )

    def test_private_web_route_without_session_redirects_to_login(self):
        """Verifica que acceder a una vista web protegida sin sesión activa redirija al login con ?next=."""
        response = self.client.get(self.admin_usuarios_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.login_url, response.url)
        self.assertIn(f"next={self.admin_usuarios_url}", response.url)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_private_web_route_with_session_lacking_permission_redirects_to_home(self, mock_rbac):
        """Verifica que una sesión activa sin el permiso RBAC sea redirigida a home (RNF21)."""
        self.client.force_login(self.django_user)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session.save()

        response = self.client.get(self.admin_usuarios_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    # --------------------------------------------------------------------------
    # 2. Caducidad del token (Expiration)
    # --------------------------------------------------------------------------

    def test_expired_access_token_rejected_on_private_route_returns_401(self):
        """Verifica que un access token expirado sea rechazado inmediatamente con 401 en rutas privadas."""
        import time
        from django.conf import settings
        payload = {
            "token_type": "access",
            "user_id": str(self.django_user.id),
            "role_code": "ADMINISTRADOR",
            "exp": int(time.time()) - 3600,  # Expiró hace 1 hora
            "iat": int(time.time()) - 7200,
            "jti": str(uuid.uuid4()),
        }
        expired_token = self.jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        response = self.client.put(
            self.api_role_url,
            data=json.dumps({"rol": "ADMINISTRADOR"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {expired_token}",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json().get("error"),
            "Se requiere un token de autenticación válido.",
        )

    def test_expired_refresh_token_rejected_on_token_refresh_returns_401(self):
        """Verifica que un refresh token expirado sea rechazado con 401 ('token_not_valid') al intentar refrescar."""
        import time
        from django.conf import settings
        payload = {
            "token_type": "refresh",
            "user_id": str(self.django_user.id),
            "exp": int(time.time()) - 3600,  # Expiró hace 1 hora
            "iat": int(time.time()) - 7200,
            "jti": str(uuid.uuid4()),
        }
        expired_refresh = self.jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        response = self.client.post(
            self.token_refresh_url,
            data=json.dumps({"refresh": expired_refresh}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data.get("code"), "token_not_valid")

    def test_jwt_lifetime_settings_compliance(self):
        """Verifica que la configuración de SimpleJWT cumpla las directivas de seguridad del sistema."""
        from datetime import timedelta
        from django.conf import settings
        simple_jwt = settings.SIMPLE_JWT

        self.assertEqual(simple_jwt["ACCESS_TOKEN_LIFETIME"], timedelta(minutes=60))
        self.assertEqual(simple_jwt["REFRESH_TOKEN_LIFETIME"], timedelta(days=1))
        self.assertTrue(simple_jwt["BLACKLIST_AFTER_ROTATION"])
        self.assertIn("Bearer", simple_jwt["AUTH_HEADER_TYPES"])

    # --------------------------------------------------------------------------
    # 3. Cierre de sesión y persistencia
    # --------------------------------------------------------------------------

    def test_web_logout_destroys_session_and_cleans_cookie(self):
        """Verifica que POST /logout/ destruya la sesión, borre la cookie e impida acceder a rutas privadas."""
        from django.conf import settings
        self.client.force_login(self.django_user)
        session = self.client.session
        session["rol"] = "ADMINISTRADOR"
        session.save()
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.login_url)

        # La sesión queda destruida
        self.assertNotIn("_auth_user_id", self.client.session)

        # La cookie de sesión se elimina o marca para expirar
        cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
        if cookie:
            self.assertEqual(cookie.value, "")

        # Petición posterior a ruta privada es rechazada y redirigida a login
        protected_response = self.client.get(self.admin_usuarios_url)
        self.assertEqual(protected_response.status_code, 302)
        self.assertIn(self.login_url, protected_response.url)

    def test_web_logout_via_get_is_rejected_safely(self):
        """Verifica que una petición GET a /logout/ no cierre la sesión (protección contra ataques CSRF)."""
        self.client.force_login(self.django_user)
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 302)
        # La sesión permanece intacta
        self.assertIn("_auth_user_id", self.client.session)

    def test_api_logout_blacklists_refresh_token_preventing_reuse(self):
        """Verifica que el logout por API persista el refresh token en la lista negra e impida reusarlo."""
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        refresh = RefreshToken.for_user(self.django_user)
        logout_res = self.client.post(
            self.api_logout_url,
            data=json.dumps({"refresh": str(refresh)}),
            content_type="application/json",
        )
        self.assertEqual(logout_res.status_code, 200)
        self.assertEqual(logout_res.json().get("status"), "success")

        # El token queda registrado en la lista negra
        self.assertTrue(
            BlacklistedToken.objects.filter(token__token=str(refresh)).exists()
        )

        # Intentar refrescar tokens con el refresh token revocado es rechazado
        refresh_res = self.client.post(
            self.token_refresh_url,
            data=json.dumps({"refresh": str(refresh)}),
            content_type="application/json",
        )
        self.assertEqual(refresh_res.status_code, 401)
        self.assertEqual(refresh_res.json().get("code"), "token_not_valid")

    @patch("usuarios.views.Usuario")
    @patch("usuarios.views.get_supabase_client")
    def test_session_persistence_remember_me_policies(self, mock_get_client, mock_usuario):
        """Verifica la persistencia de sesión: 2 semanas con remember_me, o borrado al cerrar navegador sin él."""
        mock_get_client.return_value.auth.sign_in_with_password.return_value.user = _fake_auth_user(
            str(self.django_user.id), self.email
        )
        mock_usuario.objects.select_related.return_value.get.return_value = _fake_perfil(
            str(self.django_user.id), self.email, rol_codigo="ADMINISTRADOR"
        )

        # Caso A: con remember_me activado
        client_remember = Client()
        res_remember = client_remember.post(self.login_url, {
            "email": self.email,
            "password": self.password,
            "remember_me": "on",
        })
        self.assertEqual(res_remember.status_code, 302)
        self.assertEqual(client_remember.session.get_expiry_age(), 1209600)

        # Caso B: sin remember_me (cierre de navegador)
        client_normal = Client()
        res_normal = client_normal.post(self.login_url, {
            "email": self.email,
            "password": self.password,
        })
        self.assertEqual(res_normal.status_code, 302)
        self.assertTrue(client_normal.session.get_expire_at_browser_close())

    # --------------------------------------------------------------------------
    # 4. Respuesta ante credenciales erróneas
    # --------------------------------------------------------------------------

    @patch("usuarios.views.get_supabase_client")
    def test_login_wrong_password_returns_401_generic_error_and_no_token(self, mock_get_client):
        """Verifica que una contraseña incorrecta devuelva 401 con mensaje genérico y sin emitir tokens."""
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, "invalid_credentials"
        )
        response = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": "WrongPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(
            data.get("error"),
            "Correo electrónico o contraseña incorrectos. Por favor verifique sus datos.",
        )
        self.assertNotIn("access", data)
        self.assertNotIn("refresh", data)
        self.assertNotIn("_auth_user_id", self.client.session)

    @patch("usuarios.views.get_supabase_client")
    def test_login_nonexistent_email_returns_identical_generic_error_rnf07(self, mock_get_client):
        """Verifica que un correo inexistente retorne el mensaje idéntico para evitar enumeración (RNF07)."""
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, "invalid_credentials"
        )
        res_pwd = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": "BadPassword!"}),
            content_type="application/json",
        )
        res_email = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": "inexistente.total.999@cafepergamo.com", "password": "AnyPassword123!"}),
            content_type="application/json",
        )
        self.assertEqual(res_pwd.status_code, 401)
        self.assertEqual(res_email.status_code, 401)
        self.assertEqual(res_pwd.json()["error"], res_email.json()["error"])
        self.assertIn("incorrectos", res_pwd.json()["error"])

    @patch("usuarios.views.get_supabase_client")
    def test_login_failed_attempts_increment_persistence_and_trigger_lockout(self, mock_get_client):
        """Verifica que intentos fallidos incrementen el registro y al 5to intento se bloquee la cuenta (RN03/EX-3)."""
        from usuarios.models import RegistroIntentoLogin
        mock_get_client.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
            "Invalid login credentials", 400, "invalid_credentials"
        )
        target_email = "lockout.qa@cafepergamo.com"

        for i in range(1, 5):
            res = self.client.post(
                self.api_login_url,
                data=json.dumps({"email": target_email, "password": f"BadPassword_{i}"}),
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 401)
            reg = RegistroIntentoLogin.objects.get(identificador=target_email.lower())
            self.assertEqual(reg.failed_attempts, i)
            self.assertFalse(reg.is_locked)

        # 5to intento consecutivo debe activar el bloqueo
        res_lock = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": target_email, "password": "BadPassword_5"}),
            content_type="application/json",
        )
        self.assertEqual(res_lock.status_code, 403)
        data_lock = res_lock.json()
        self.assertTrue(data_lock.get("locked"))
        self.assertIn("demasiados intentos", data_lock.get("error", ""))

        reg = RegistroIntentoLogin.objects.get(identificador=target_email.lower())
        self.assertEqual(reg.failed_attempts, 5)
        self.assertTrue(reg.is_locked)

    def test_login_empty_credentials_returns_400(self):
        """Verifica que omitir credenciales sea rechazado con 400 Bad Request."""
        res_empty_email = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": "", "password": self.password}),
            content_type="application/json",
        )
        self.assertEqual(res_empty_email.status_code, 400)
        self.assertIn("obligatorios", res_empty_email.json().get("error", ""))

        res_empty_password = self.client.post(
            self.api_login_url,
            data=json.dumps({"email": self.email, "password": ""}),
            content_type="application/json",
        )
        self.assertEqual(res_empty_password.status_code, 400)
        self.assertIn("obligatorios", res_empty_password.json().get("error", ""))


