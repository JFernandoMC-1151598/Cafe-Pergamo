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
from django.http import JsonResponse
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

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_rol_actualiza_y_redirige(self, mock_usuario, mock_rol, _mock_check):
        from usuarios.views import panel_administracion_usuarios

        usuario_existente = MagicMock(id="u1", rol_id=1, nombres="Ana", apellidos="Gómez")
        nuevo_rol = MagicMock(id=2, nombre="Administrador")
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_rol.objects.filter.return_value.first.return_value = nuevo_rol

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "u1", "nuevo_rol": "ADMINISTRADOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_usuarios"))
        self.assertEqual(usuario_existente.rol, nuevo_rol)
        usuario_existente.save.assert_called_once_with(update_fields=["rol"])

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_al_mismo_rol_no_guarda_de_nuevo(self, mock_usuario, mock_rol, _mock_check):
        from usuarios.views import panel_administracion_usuarios

        usuario_existente = MagicMock(id="u1", rol_id=1, nombres="Ana", apellidos="Gómez")
        rol_sin_cambios = MagicMock(id=1, nombre="Productor")
        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = usuario_existente
        mock_rol.objects.filter.return_value.first.return_value = rol_sin_cambios

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "u1", "nuevo_rol": "PRODUCTOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)
        usuario_existente.save.assert_not_called()

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.views.Rol")
    @patch("usuarios.views.Usuario")
    def test_reasignar_con_usuario_o_rol_invalido_no_rompe(self, mock_usuario, mock_rol, _mock_check):
        from usuarios.views import panel_administracion_usuarios

        mock_usuario.objects.filter.return_value.select_related.return_value.first.return_value = None
        mock_rol.objects.filter.return_value.first.return_value = MagicMock()

        request = self._fake_request_autenticado(
            method="post", data={"usuario_id": "no-existe", "nuevo_rol": "ADMINISTRADOR"}
        )
        response = panel_administracion_usuarios(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_usuarios"))



