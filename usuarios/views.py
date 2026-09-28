"""
Vistas del módulo de Usuarios - CAFÉ PÉRGAMO.

Reúne dos subtareas:
  - HU01-ST3 (SCRUM-60): registro de usuarios -> registro_api().
  - HU02-ST2 (SCRUM-76): autenticación / verificación de credenciales -> login_view().

Decisión de arquitectura (ver usuarios/supabase_client.py y
README_HU01-ST1.md), válida para AMBAS subtareas: la autenticación real
—correo, hash de contraseña, verificación de credenciales— la resuelve
Supabase Auth (GoTrue), nunca `django.contrib.auth` directamente contra
la tabla `auth_user`. Esa tabla de Django se sigue usando (queda
instalada, y `login_view` sí crea/actualiza una fila "espejo" ahí) solo
para reutilizar el framework de sesiones de Django (`request.user`,
`@login_required`, mensajes) — jamás guarda ni verifica contraseñas de
usuarios reales; su contraseña queda explícitamente inutilizable
(`set_unusable_password()`). El panel de administración de Django
(`/admin/`) tiene su propio login nativo, completamente aparte de esta
vista, para inspección local (ver usuarios/admin.py).
"""

import json
import logging
import re

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from supabase_auth.errors import AuthApiError

from .models import Rol, TipoDocumento, Usuario
from .supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HU01-ST3 (SCRUM-60): registro de usuarios — POST /api/auth/register
# ---------------------------------------------------------------------------

# Mismo patrón que la restricción CHECK `usuarios_telefono_formato` en
# Supabase (db/001_usuarios_schema.sql) — se valida aquí también para
# devolver un error legible en vez de que la petición falle a mitad de
# camino (usuario ya creado en Auth, pero rechazado al insertar el
# perfil de negocio).
_TELEFONO_REGEX = re.compile(r"^\+?[0-9 ]{7,15}$")

# Roles que un usuario puede elegir al autoregistrarse. ADMINISTRADOR
# queda deliberadamente excluido: un endpoint público de registro nunca
# debe permitir que alguien se autoasigne el rol de administrador. Los
# roles con `requiere_cuenta = False` (p.ej. CONSULTA_PUBLICA) tampoco
# aplican aquí, porque por definición no tienen cuenta/registro.
_ROLES_NO_AUTORREGISTRABLES = {"ADMINISTRADOR"}

# La UI de registro (HU01-ST2, ver templates/usuarios/registro.html)
# ofrece "COMERCIALIZADOR" como opción separada, pero en el catálogo de
# roles (HU04-ST1) "Productor" y "Comercializador" se modelaron como un
# solo rol combinado (`PRODUCTOR`, nombre "Productor / Comercializador").
# Este alias evita que ese detalle de UI rompa el registro.
_ALIAS_ROL = {
    "COMERCIALIZADOR": "PRODUCTOR",
}

REQUIRED_FIELDS = (
    "correo",
    "contraseña",
    "nombres",
    "apellidos",
    "tipo_documento",
    "numero_documento",
    "rol",
)

# Alias en inglés aceptados por campo, para no bloquear la integración
# con el formulario ya construido en HU01-ST2 (usa first_name, last_name,
# email, phone, role, password) mientras se decide si ese formulario se
# actualiza para enviar tipo_documento/numero_documento o si se agrega
# una capa de adaptación en el frontend.
_ALIAS_CAMPO = {
    "correo": ("email",),
    "contraseña": ("password", "contrasena"),
    "nombres": ("first_name", "nombre"),
    "apellidos": ("last_name", "apellido"),
    "telefono": ("phone",),
    "rol": ("role",),
}


def _valor_crudo(data, campo):
    if data.get(campo) not in (None, ""):
        return data[campo]
    for alias in _ALIAS_CAMPO.get(campo, ()):
        if data.get(alias) not in (None, ""):
            return data[alias]
    return None


def _texto(valor):
    """Normaliza un valor de entrada a texto recortado, o None si viene vacío/ausente."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        valor = str(valor)
    valor = valor.strip()
    return valor or None


def _bad_request(campos):
    return JsonResponse({"error": "Datos inválidos.", "campos": campos}, status=400)


@csrf_exempt  # Endpoint público de registro: todavía no existe sesión que proteger.
@require_POST
def registro_api(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "El cuerpo de la petición debe ser JSON válido."}, status=400
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {"error": "El cuerpo de la petición debe ser un objeto JSON."}, status=400
        )

    valores = {campo: _texto(_valor_crudo(data, campo)) for campo in REQUIRED_FIELDS}
    telefono = _texto(_valor_crudo(data, "telefono"))

    # 1. Campos obligatorios presentes.
    faltantes = {c: "Este campo es obligatorio." for c in REQUIRED_FIELDS if not valores.get(c)}
    if faltantes:
        return _bad_request(faltantes)

    correo = valores["correo"]
    contraseña = valores["contraseña"]
    nombres = valores["nombres"]
    apellidos = valores["apellidos"]
    tipo_documento_codigo = valores["tipo_documento"].upper()
    numero_documento = valores["numero_documento"]
    rol_codigo = _ALIAS_ROL.get(valores["rol"].upper(), valores["rol"].upper())

    # 2. Formato de correo.
    try:
        validate_email(correo)
    except ValidationError:
        return _bad_request({"correo": "El correo electrónico no tiene un formato válido."})

    # 3. Contraseña: mínimo orientativo local; la política real la aplica
    #    Supabase Auth y su error se traduce más abajo si no se cumple.
    if len(contraseña) < 6:
        return _bad_request({"contraseña": "Debe tener al menos 6 caracteres."})

    # 4. Teléfono (opcional, pero si viene debe cumplir el mismo formato
    #    que la restricción CHECK de la base de datos).
    if telefono and not _TELEFONO_REGEX.match(telefono):
        return _bad_request(
            {"telefono": "Formato inválido. Use solo dígitos, espacios y un '+' inicial opcional (7 a 15 caracteres)."}
        )

    # 5. Tipo de documento: debe existir y estar activo en el catálogo.
    tipo_documento = TipoDocumento.objects.filter(codigo=tipo_documento_codigo, activo=True).first()
    if tipo_documento is None:
        return _bad_request({"tipo_documento": "Tipo de documento inválido."})

    # 6. Rol: debe existir, estar activo, requerir cuenta, y no estar en
    #    la lista de roles no autoasignables (ADMINISTRADOR).
    rol = Rol.objects.filter(codigo=rol_codigo, activo=True, requiere_cuenta=True).first()
    if rol is None or rol.codigo in _ROLES_NO_AUTORREGISTRABLES:
        return _bad_request({"rol": "Rol inválido para autoregistro."})

    # 7. Correo no debe existir ya en BD (RF de esta historia). Se
    #    consulta la ficha de negocio (public.usuarios); el intento de
    #    sign_up de todas formas vuelve a validar esto contra
    #    auth.users como red de seguridad ante condiciones de carrera.
    if Usuario.objects.filter(correo__iexact=correo).exists():
        return JsonResponse({"error": "El correo ya está registrado."}, status=409)

    # 8. Número de documento no debe repetirse para el mismo tipo
    #    (refleja la restricción UNIQUE(tipo_documento_id, numero_documento)).
    if Usuario.objects.filter(tipo_documento=tipo_documento, numero_documento=numero_documento).exists():
        return JsonResponse(
            {"error": "Ya existe un usuario registrado con ese tipo y número de documento."}, status=409
        )

    # 9. Delegar la creación real del usuario a Supabase Auth. El
    #    trigger on_auth_user_created arma la fila de public.usuarios
    #    con estos metadatos (ver handle_new_user() en
    #    db/001_usuarios_schema.sql).
    try:
        auth_response = get_supabase_client().auth.sign_up(
            {
                "email": correo,
                "password": contraseña,
                "options": {
                    "data": {
                        "tipo_documento": tipo_documento.codigo,
                        "numero_documento": numero_documento,
                        "nombres": nombres,
                        "apellidos": apellidos,
                        "telefono": telefono,
                        "rol": rol.codigo,
                    }
                },
            }
        )
    except AuthApiError as exc:
        logger.warning("Fallo de Supabase Auth en registro (%s): %s", exc.code, exc.message)
        if exc.code in ("email_exists", "user_already_exists"):
            return JsonResponse({"error": "El correo ya está registrado."}, status=409)
        if exc.code == "weak_password":
            return _bad_request({"contraseña": "La contraseña no cumple la política de seguridad."})
        if exc.code == "email_address_invalid":
            return _bad_request({"correo": "El correo electrónico no tiene un formato válido."})
        return JsonResponse(
            {"error": "No se pudo completar el registro. Intente de nuevo más tarde."}, status=502
        )
    except RuntimeError as exc:
        # get_supabase_client() lanza esto si faltan SUPABASE_URL/SUPABASE_ANON_KEY.
        logger.error("Configuración de Supabase incompleta: %s", exc)
        return JsonResponse({"error": "El servicio de registro no está disponible."}, status=503)

    if auth_response.user is None:
        logger.error("sign_up() respondió sin usuario y sin lanzar excepción: %r", auth_response)
        return JsonResponse(
            {"error": "No se pudo completar el registro. Intente de nuevo más tarde."}, status=502
        )

    # 10. Leer de vuelta el perfil que el trigger insertó, para confirmar
    #     que quedó creado y devolver datos reales (no lo que asumimos
    #     que se guardó).
    try:
        usuario = Usuario.objects.select_related("tipo_documento", "rol").get(id=auth_response.user.id)
    except Usuario.DoesNotExist:
        logger.error(
            "auth.users %s se creó pero el trigger no generó la fila en usuarios.",
            auth_response.user.id,
        )
        return JsonResponse(
            {
                "error": "El usuario se creó pero no se pudo sincronizar su perfil. "
                         "Contacte a soporte."
            },
            status=500,
        )

    return JsonResponse(
        {
            "usuario": {
                "id": str(usuario.id),
                "correo": usuario.correo,
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "tipo_documento": usuario.tipo_documento.codigo,
                "numero_documento": usuario.numero_documento,
                "telefono": usuario.telefono,
                "rol": usuario.rol.codigo,
                "activo": usuario.activo,
                "creado_en": usuario.creado_en.isoformat(),
            },
            "requiere_verificacion_correo": auth_response.session is None,
        },
        status=201,
    )


# ---------------------------------------------------------------------------
# HU02-ST2 (SCRUM-76): autenticación y verificación de credenciales.
# ---------------------------------------------------------------------------

# Mensaje genérico contra enumeración de cuentas (RNF de seguridad): nunca
# se distingue entre "correo inexistente" y "contraseña incorrecta".
_LOGIN_ERROR_GENERICO = "Correo electrónico o contraseña incorrectos. Por favor verifique sus datos."


def login_view(request: HttpRequest) -> HttpResponse:
    """
    Controlador de inicio de sesión (HU02-ST2).

    Soporta peticiones GET (interfaz visual) y POST (formulario web y API
    JSON). La verificación de credenciales es exclusivamente contra
    Supabase Auth (`sign_in_with_password`) — nunca contra `auth_user` de
    Django, que no guarda contraseñas de usuarios reales (ver el docstring
    del módulo). Tras un login exitoso, se sincroniza una fila "espejo" en
    `auth_user` únicamente para reutilizar `django.contrib.auth.login()` y
    el resto del framework de sesiones de Django, y se guarda en la sesión
    el `rol` del perfil de negocio (`public.usuarios`) para que el resto
    de la aplicación pueda aplicar el control de acceso basado en roles
    (RBAC, HU04-ST1) sin otra consulta.

    URL Web: /login/
    Alias API: /api/auth/login
    """
    if request.user.is_authenticated and request.method == "GET":
        return redirect("home")

    if request.method == "GET":
        return render(request, "usuarios/login.html")

    if request.method != "POST":
        return HttpResponse("Método no permitido", status=405)

    is_json_request = request.content_type == "application/json"

    if is_json_request:
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {"error": "El cuerpo de la solicitud no contiene un JSON válido."}, status=400
            )
    else:
        data = request.POST

    correo = (data.get("email") or data.get("correo") or "").strip()
    password = data.get("password") or data.get("contraseña") or ""
    remember_me = data.get("remember_me")

    if not correo or not password:
        error_msg = "Todos los campos son obligatorios. Por favor ingrese tanto el correo electrónico como la contraseña."
        if is_json_request:
            return JsonResponse({"error": error_msg}, status=400)
        messages.error(request, error_msg)
        return render(request, "usuarios/login.html", {"email": correo})

    def _fallo_generico(status=401):
        if is_json_request:
            return JsonResponse({"error": _LOGIN_ERROR_GENERICO}, status=status)
        messages.error(request, _LOGIN_ERROR_GENERICO)
        return render(request, "usuarios/login.html", {"email": correo})

    # 1. Verificación de credenciales: solo Supabase Auth.
    try:
        auth_response = get_supabase_client().auth.sign_in_with_password(
            {"email": correo, "password": password}
        )
    except AuthApiError as exc:
        logger.info("Login fallido para %s (%s)", correo, exc.code)
        if exc.code in ("over_request_rate_limit", "too_many_requests"):
            error_msg = "Demasiados intentos. Intente de nuevo en unos minutos."
            if is_json_request:
                return JsonResponse({"error": error_msg}, status=429)
            messages.error(request, error_msg)
            return render(request, "usuarios/login.html", {"email": correo})
        return _fallo_generico()
    except RuntimeError as exc:
        logger.error("Configuración de Supabase incompleta: %s", exc)
        error_msg = "El servicio de inicio de sesión no está disponible."
        if is_json_request:
            return JsonResponse({"error": error_msg}, status=503)
        messages.error(request, error_msg)
        return render(request, "usuarios/login.html", {"email": correo})

    if auth_response.user is None:
        return _fallo_generico()

    # 2. Traer el perfil de negocio (rol, nombres, etc.) de public.usuarios.
    try:
        usuario = Usuario.objects.select_related("rol", "tipo_documento").get(id=auth_response.user.id)
    except Usuario.DoesNotExist:
        logger.error("auth.users %s no tiene perfil en public.usuarios.", auth_response.user.id)
        error_msg = "Su cuenta no tiene un perfil asociado. Contacte a soporte."
        if is_json_request:
            return JsonResponse({"error": error_msg}, status=500)
        messages.error(request, error_msg)
        return render(request, "usuarios/login.html", {"email": correo})

    if not usuario.activo:
        error_msg = "Esta cuenta de usuario se encuentra inactiva. Contacte al administrador."
        if is_json_request:
            return JsonResponse({"error": error_msg}, status=403)
        messages.error(request, error_msg)
        return render(request, "usuarios/login.html", {"email": correo})

    # 3. Sincronizar la fila "espejo" en auth_user (solo para el framework
    #    de sesiones de Django). Se identifica por el UUID de Supabase, no
    #    por el correo, para que sobreviva a un cambio de correo futuro.
    django_user, creado = User.objects.get_or_create(
        username=str(usuario.id),
        defaults={
            "email": usuario.correo,
            "first_name": usuario.nombres,
            "last_name": usuario.apellidos,
        },
    )
    if creado:
        django_user.set_unusable_password()
        django_user.save(update_fields=["password"])
    elif (
        django_user.email != usuario.correo
        or django_user.first_name != usuario.nombres
        or django_user.last_name != usuario.apellidos
    ):
        django_user.email = usuario.correo
        django_user.first_name = usuario.nombres
        django_user.last_name = usuario.apellidos
        django_user.save(update_fields=["email", "first_name", "last_name"])

    login(request, django_user)
    request.session["usuario_id"] = str(usuario.id)
    request.session["rol"] = usuario.rol.codigo

    if remember_me:
        request.session.set_expiry(1209600)  # 2 semanas.
    else:
        request.session.set_expiry(0)  # Expira al cerrar el navegador.

    nombre_mostrar = usuario.nombres or django_user.username
    messages.success(request, f"¡Bienvenido de nuevo, {nombre_mostrar}!")

    if is_json_request:
        return JsonResponse(
            {
                "status": "success",
                "message": f"Autenticación exitosa. ¡Bienvenido, {nombre_mostrar}!",
                "user": {
                    "id": str(usuario.id),
                    "correo": usuario.correo,
                    "nombres": usuario.nombres,
                    "apellidos": usuario.apellidos,
                    "rol": usuario.rol.codigo,
                },
            },
            status=200,
        )

    next_url = request.GET.get("next") or request.POST.get("next") or "home"
    return redirect(next_url)


def logout_view(request: HttpRequest) -> HttpResponse:
    """Controlador para cerrar la sesión HTTP del usuario (HU02-ST4)."""
    logout(request)
    messages.info(request, "Has cerrado sesión correctamente. ¡Hasta pronto!")
    return redirect("login")


def registro_view(request: HttpRequest) -> HttpResponse:
    """Renderiza la pantalla de registro de usuarios (HU01-ST2)."""
    return render(request, "usuarios/registro.html")
