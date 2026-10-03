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

HU01-ST4 (SCRUM-61) - Cifrado/hash de contraseñas (RNF04):
Esta subtarea pedía "integrar una librería de encriptación segura (ej.
Bcrypt o Argon2) para encriptar la contraseña antes de guardarla en la
base de datos, garantizando que nunca se almacene en texto plano".

Por la decisión de arquitectura de arriba, esto ya está cubierto por
diseño y no requiere una librería adicional en este proyecto:

  1. Ni `registro_api()` ni `login_view()` escriben la contraseña en
     ninguna tabla propia. El modelo `Usuario` (usuarios/models.py) ni
     siquiera tiene un campo de contraseña.
  2. La contraseña en texto plano solo viaja, por HTTPS, hacia
     Supabase Auth (`auth.sign_up()` / `auth.sign_in_with_password()`
     en supabase_client.py). Supabase Auth (GoTrue) es quien la
     hashea con bcrypt internamente antes de persistirla en
     `auth.users` — una tabla que este proyecto ni siquiera modela ni
     puede leer directamente desde Django.
  3. La única contraseña que toca una tabla de Django es la fila
     "espejo" en `auth_user` (ver punto anterior), y esa se crea
     explícitamente con `set_unusable_password()`: no es un hash de la
     contraseña real, es un valor que Django reconoce como "sin
     contraseña utilizable" y que nunca se compara contra nada.

En otras palabras: no existe ningún punto del código de este proyecto
donde una contraseña en texto plano llegue a guardarse en una base de
datos — ni sin cifrar ni cifrada por nosotros mismos — porque nunca la
guardamos nosotros; se la delegamos por completo a un proveedor de
autenticación especializado. Agregar Bcrypt/Argon2 en Django aquí
sería cifrar un dato que Django nunca posee, y crear una segunda
fuente de verdad de contraseñas que contradice la arquitectura ya
usada en HU01-ST3/HU02-ST2. Ver también la sección "Seguridad de
contraseñas (RNF04 / HU01-ST4)" en README.md.
"""

import json
import logging
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from supabase_auth.errors import AuthApiError

from .gestion_roles import CambioRolInvalido, cambiar_rol_usuario
from .models import Rol, TipoDocumento, Usuario
from .permissions import permiso_requerido, permiso_requerido_sesion
from .security import obtener_ip_cliente
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
# debe permitir que alguien se autoasigne el rol de administrador.
# ASOCIACION también queda excluido (CU10 del documento de Casos de
# Uso): una asociación no se autorregistra, la da de alta el
# Administrador del Sistema junto con la cuenta de su propio
# administrador (ver RN02 de CU10). Esta restricción es la que de
# verdad protege el registro — que el formulario ya no ofrezca
# "Asociación" como opción (ver templates/usuarios/registro.html) es
# solo la otra mitad; sin esto, cualquiera podría seguir
# autoasignándose ese rol llamando directamente a este endpoint. Los
# roles con `requiere_cuenta = False` (p.ej. CONSULTA_PUBLICA) tampoco
# aplican aquí, porque por definición no tienen cuenta/registro.
_ROLES_NO_AUTORREGISTRABLES = {"ADMINISTRADOR", "ASOCIACION"}

# La UI de registro (HU01-ST2, ver templates/usuarios/registro.html)
# históricamente ofrecía "COMERCIALIZADOR" como opción separada, pero
# en el catálogo de roles (HU04-ST1) "Productor" y "Comercializador" se
# modelaron siempre como un solo rol combinado (`PRODUCTOR`, nombre
# "Productor / Comercializador") — el formulario ya se actualizó para
# mostrar una sola opción, pero este alias se deja para no romper
# ningún cliente de la API que todavía envíe "COMERCIALIZADOR".
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

    from .security import (
        verificar_cuenta_bloqueada,
        registrar_intento_fallido,
        resetear_intentos,
    )

    # 1. Verificación de Bloqueo Temporal previo (SCRUM-79 / HU02-ST5)
    bloqueada, reg_bloqueo, minutos_restantes = verificar_cuenta_bloqueada(correo)
    if bloqueada:
        msg_bloqueo = "Cuenta bloqueada temporalmente por demasiados intentos fallidos. Intente de nuevo más tarde."
        if is_json_request:
            return JsonResponse({
                "error": msg_bloqueo,
                "locked": True,
                "minutos_restantes": minutos_restantes,
            }, status=403)
        messages.error(request, msg_bloqueo)
        return render(request, "usuarios/login.html", {"email": correo})

    # 2. Verificación de credenciales: solo Supabase Auth.
    try:
        auth_response = get_supabase_client().auth.sign_in_with_password(
            {"email": correo, "password": password}
        )
    except AuthApiError as exc:
        logger.info("Login fallido para %s (%s)", correo, exc.code)
        
        # Registrar intento fallido
        quedo_bloqueado, reg_fallo = registrar_intento_fallido(correo, request=request)
        if quedo_bloqueado:
            msg_bloqueo = "Cuenta bloqueada temporalmente por demasiados intentos fallidos. Intente de nuevo más tarde."
            if is_json_request:
                return JsonResponse({
                    "error": msg_bloqueo,
                    "locked": True,
                    "minutos_restantes": reg_fallo.tiempo_restante_minutos(),
                }, status=403)
            messages.error(request, msg_bloqueo)
            return render(request, "usuarios/login.html", {"email": correo})

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
        quedo_bloqueado, reg_fallo = registrar_intento_fallido(correo, request=request)
        return _fallo_generico()
        
    # Reiniciar contador de intentos fallidos tras login exitoso
    resetear_intentos(correo)

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
    """
    Controlador para cerrar la sesión HTTP y revocar tokens (HU02-ST4).
    
    Por razones de seguridad contra ataques CSRF (Django 5+ / OWASP),
    el cierre de sesión web debe ejecutarse mediante método POST con {% csrf_token %}.
    Si se recibe una petición GET, se redirige de forma segura.
    
    Flujo:
    1. Si se proporciona un refresh_token (JSON o POST), se invalida incluyéndolo
       en la lista negra de SimpleJWT (BlacklistedToken).
    2. Destruye la sesión HTTP del usuario mediante logout(request).
    3. Elimina las cookies de sesión del navegador.
    4. Inyecta notificación informativa con messages.info().
    5. Redirige a la vista de login.
    """
    if request.method != "POST":
        messages.warning(request, "Para cerrar sesión de forma segura, utilice el botón correspondiente.")
        return redirect("home" if request.user.is_authenticated else "login")

    # 1. Revocación de token JWT si se proporciona
    from rest_framework_simplejwt.tokens import RefreshToken, TokenError
    refresh_token = request.POST.get("refresh_token") or request.POST.get("refresh")
    if not refresh_token and request.content_type == "application/json":
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
            refresh_token = body.get("refresh_token") or body.get("refresh")
        except Exception:
            pass

    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except (TokenError, Exception):
            pass

    # 2. Destrucción de la sesión HTTP en Django
    logout(request)

    # 3. Respuesta para solicitudes API / JSON
    if request.content_type == "application/json" or request.path.startswith("/api/"):
        response = JsonResponse({
            "status": "success",
            "message": "Has cerrado sesión exitosamente."
        }, status=200)
        response.delete_cookie(settings.SESSION_COOKIE_NAME)
        return response

    # 4. Respuesta para formulario Web
    messages.info(request, "Has cerrado sesión exitosamente. ¡Hasta pronto!")
    response = redirect("login")
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response


@csrf_exempt
def api_logout_view(request: HttpRequest) -> JsonResponse:
    """
    Endpoint API REST para revocación de JWT y cierre de sesión (/api/auth/logout/).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido. Utilice POST."}, status=405)

    from rest_framework_simplejwt.tokens import RefreshToken, TokenError
    refresh_token = None
    if request.content_type == "application/json":
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
            refresh_token = body.get("refresh_token") or body.get("refresh")
        except Exception:
            pass
    else:
        refresh_token = request.POST.get("refresh_token") or request.POST.get("refresh")

    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return JsonResponse({"error": "El token de refresco es inválido o ya expiró."}, status=400)
        except Exception as e:
            return JsonResponse({"error": f"Error al revocar el token: {str(e)}"}, status=400)

    logout(request)
    response = JsonResponse({
        "status": "success",
        "message": "Has cerrado sesión exitosamente. Token revocado."
    }, status=200)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response



def home_view(request: HttpRequest) -> HttpResponse:
    """
    Renderiza la página de inicio principal (HOME) de Café Pérgamo.
    Presenta la propuesta de valor, hero section y pilares del sistema.
    """
    return render(request, "home.html")


def catalogo_view(request: HttpRequest) -> HttpResponse:
    """
    Renderiza la vitrina comercial y catálogo público de lotes de café (HU04).
    Muestra los lotes disponibles o redirige con notificación informativa
    mientras se despliegan los lotes de la cosecha activa.
    """
    messages.info(
        request,
        "El Catálogo Comercial de Lotes de Norte de Santander se encuentra en actualización con los lotes de la cosecha activa."
    )
    return redirect("/#pilares")


def registro_view(request: HttpRequest) -> HttpResponse:
    """Renderiza la pantalla de registro de usuarios (HU01-ST2)."""
    return render(request, "usuarios/registro.html")


def recuperar_contrasena_view(request: HttpRequest) -> HttpResponse:
    """
    Renderiza la pantalla de "olvidé mi contraseña".

    NOTA: esta vista solo pinta la plantilla por ahora. La lógica de
    envío del correo (usuarios/email_service.py ya existe, pero todavía
    no está conectada aquí) y la generación/validación del token de
    restablecimiento contra Supabase Auth quedan pendientes como parte
    de la funcionalidad de recuperación de contraseña (fuera de las
    subtareas HU01-ST3/ST4/ST5 y HU02-ST2/ST5 ya cubiertas en este
    archivo). Se agrega como stub para que la ruta 'recuperar_contrasena'
    que referencia templates/usuarios/login.html no rompa el sitio.
    """
    return render(request, "usuarios/recuperar_contrasena.html")


def restablecer_contrasena_view(request: HttpRequest, token: str) -> HttpResponse:
    """
    Renderiza la pantalla para definir una nueva contraseña a partir de un
    token de recuperación.

    NOTA: ver docstring de recuperar_contrasena_view — la validación real
    del token contra Supabase Auth y el cambio de contraseña todavía no
    están implementados; esto solo evita que la ruta correspondiente
    rompa el sitio mientras esa funcionalidad se termina.
    """
    return render(request, "usuarios/restablecer_contrasena.html", {"token": token})


# ---------------------------------------------------------------------------
# HU04-ST4 (SCRUM-119): Administración de Usuarios y Roles — Frontend.
# ---------------------------------------------------------------------------

@permiso_requerido_sesion("usuarios.administrar")
def panel_administracion_usuarios(request: HttpRequest) -> HttpResponse:
    """
    Pantalla de administración de usuarios (HU04-ST4): lista los usuarios
    del sistema, permite filtrarlos por rol y por estado, y ofrece un
    formulario para reasignar el rol de una cuenta.

    El guard `permiso_requerido_sesion` ya exige el permiso
    "usuarios.administrar" (hoy solo lo tiene ADMINISTRADOR en la matriz
    RBAC sembrada en HU04-ST1), así que esta vista no vuelve a repetir esa
    verificación.

    El cambio de rol que procesa el POST delega en
    `gestion_roles.cambiar_rol_usuario` (HU04-ST5 / SCRUM-120), que es
    quien aplica la restricción de no dejar el sistema sin
    administradores y quien deja constancia del cambio en la bitácora
    de auditoría (RF28) — la misma función que usa el endpoint de API
    `/api/users/<id>/role`, para que ambos caminos respeten la regla
    igual.
    """
    if request.method == "POST":
        usuario_id = request.POST.get("usuario_id")
        nuevo_rol_codigo = request.POST.get("nuevo_rol")

        usuario = Usuario.objects.filter(id=usuario_id).select_related("rol").first()
        nuevo_rol = Rol.objects.filter(codigo=nuevo_rol_codigo, activo=True, requiere_cuenta=True).first()

        if usuario is None or nuevo_rol is None:
            messages.error(request, "No se pudo actualizar el rol: usuario o rol inválido.")
            return redirect("admin_usuarios")

        # Quién hace el cambio, para la bitácora — el mismo perfil que
        # login_view ya deja identificado en la sesión.
        realizado_por = Usuario.objects.filter(id=request.session.get("usuario_id")).first()

        try:
            usuario, entrada_bitacora = cambiar_rol_usuario(
                usuario, nuevo_rol, realizado_por=realizado_por, ip_address=obtener_ip_cliente(request)
            )
        except CambioRolInvalido as exc:
            messages.error(request, str(exc))
            return redirect("admin_usuarios")

        if entrada_bitacora is None:
            messages.info(request, f"{usuario.nombres} ya tenía asignado el rol {nuevo_rol.nombre}.")
        else:
            messages.success(
                request,
                f"Rol de {usuario.nombres} {usuario.apellidos} actualizado a {nuevo_rol.nombre}.",
            )

        return redirect("admin_usuarios")

    rol_filtro = request.GET.get("rol", "")
    estado_filtro = request.GET.get("estado", "")

    usuarios = Usuario.objects.select_related("rol", "tipo_documento").order_by("nombres", "apellidos")
    if rol_filtro:
        usuarios = usuarios.filter(rol__codigo=rol_filtro)
    if estado_filtro == "activo":
        usuarios = usuarios.filter(activo=True)
    elif estado_filtro == "inactivo":
        usuarios = usuarios.filter(activo=False)

    # Solo roles que admiten cuenta (RF del catálogo de HU04-ST1) tiene
    # sentido ofrecerlos como destino de una reasignación.
    roles_asignables = Rol.objects.filter(activo=True, requiere_cuenta=True).order_by("nombre")

    return render(
        request,
        "usuarios/admin_usuarios.html",
        {
            "usuarios": usuarios,
            "roles_asignables": roles_asignables,
            "rol_filtro": rol_filtro,
            "estado_filtro": estado_filtro,
        },
    )


# ---------------------------------------------------------------------------
# HU04-ST5 (SCRUM-120): Actualización de Roles y auditoría — Backend.
# ---------------------------------------------------------------------------

@csrf_exempt  # Endpoint de API autenticado por JWT, no por sesión/cookie.
@require_http_methods(["PUT", "PATCH"])
@permiso_requerido("usuarios.administrar")
def actualizar_rol_usuario_api(request: HttpRequest, user_id) -> JsonResponse:
    """
    Endpoint de API para reasignar el rol de un usuario: PUT/PATCH
    /api/users/<id>/role (HU04-ST5).

    Cuerpo esperado: {"rol": "CODIGO_DEL_ROL"} (también acepta "role"
    como alias en inglés). Toda la regla de negocio — no dejar el
    sistema sin administradores (RF28) — y el registro en la bitácora
    de auditoría viven en `gestion_roles.cambiar_rol_usuario`, la misma
    función que usa la pantalla web de HU04-ST4; este endpoint solo se
    encarga de la autenticación/autorización (vía `permiso_requerido`,
    que ya exige el permiso "usuarios.administrar") y de traducir el
    resultado a una respuesta JSON.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "El cuerpo de la petición debe ser JSON válido."}, status=400)

    nuevo_rol_codigo = ((data.get("rol") or data.get("role") or "")).strip().upper()
    if not nuevo_rol_codigo:
        return JsonResponse({"error": "Debe indicar el campo 'rol'."}, status=400)

    usuario = Usuario.objects.filter(id=user_id).select_related("rol").first()
    if usuario is None:
        return JsonResponse({"error": "No existe un usuario con ese id."}, status=404)

    nuevo_rol = Rol.objects.filter(codigo=nuevo_rol_codigo, activo=True, requiere_cuenta=True).first()
    if nuevo_rol is None:
        return JsonResponse({"error": "Rol inválido para asignar."}, status=400)

    # El decorador permiso_requerido ya dejó request.user con el usuario
    # Django "espejo" de quien hace la petición; se resuelve su perfil
    # de negocio (igual que obtener_rol_usuario en serializers.py) solo
    # para dejar constancia de quién ejecutó el cambio en la bitácora.
    realizado_por = Usuario.objects.filter(correo__iexact=request.user.email).first()

    try:
        usuario, entrada_bitacora = cambiar_rol_usuario(
            usuario, nuevo_rol, realizado_por=realizado_por, ip_address=obtener_ip_cliente(request)
        )
    except CambioRolInvalido as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    usuario_payload = {"id": str(usuario.id), "correo": usuario.correo, "rol": usuario.rol.codigo}

    if entrada_bitacora is None:
        return JsonResponse(
            {"mensaje": f"El usuario ya tenía asignado el rol {nuevo_rol.codigo}.", "usuario": usuario_payload},
            status=200,
        )

    return JsonResponse(
        {
            "mensaje": f"Rol actualizado a {nuevo_rol.codigo}.",
            "usuario": usuario_payload,
            "auditoria_id": entrada_bitacora.id,
        },
        status=200,
    )


# ==============================================================================
# VISTAS DE TOKENS JWT (HU02-ST3)
# ==============================================================================
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import CustomTokenObtainPairSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Vista personalizada para la emisión de tokens JWT (HU02-ST3).
    
    Utiliza CustomTokenObtainPairSerializer para incrustar los claims del
    rol y metadatos de usuario en el payload del access token, retornando
    tanto el token de acceso como el de refresco en formato JSON.
    """
    serializer_class = CustomTokenObtainPairSerializer

