"""
Vistas y Handlers del módulo de Usuarios - CAFÉ PÉRGAMO
Subtarea: SCRUM-76 / HU02-ST2: Autenticación y verificación de credenciales.
"""

import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt


def login_view(request: HttpRequest) -> HttpResponse:
    """
    Controlador para autenticación y verificación de credenciales (HU02-ST2).
    
    Soporta peticiones GET (interfaz visual) y POST (formulario web y API JSON).
    Cumple con el requisito no funcional de seguridad RNF04 mediante la función
    nativa `authenticate()`, verificando hashes seguros (PBKDF2/Bcrypt) sin
    exponer contraseñas en texto plano ni consultar directamente la base de datos.
    
    URL Web: /login/
    Alias API: /api/auth/login
    """
    # Si el usuario ya cuenta con una sesión activa, redirigir al inicio
    if request.user.is_authenticated and request.method == "GET":
        return redirect("home")

    # Petición GET: Renderizar la pantalla de inicio de sesión
    if request.method == "GET":
        return render(request, "usuarios/login.html")

    # Petición POST: Procesar credenciales
    if request.method == "POST":
        is_json_request = request.content_type == "application/json"
        
        # 1. Extracción de credenciales según el tipo de contenido
        if is_json_request:
            try:
                data = json.loads(request.body.decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse(
                    {"error": "El cuerpo de la solicitud no contiene un JSON válido."}, 
                    status=400
                )
        else:
            data = request.POST

        # El identificador de usuario puede enviarse como 'email' o 'username'
        username_or_email = (data.get("email") or data.get("username") or "").strip()
        password = data.get("password") or ""
        remember_me = data.get("remember_me")

        # 2. Validación de presencia de datos (no vacíos ni nulos)
        if not username_or_email or not password:
            error_msg = "Todos los campos son obligatorios. Por favor ingrese tanto el correo electrónico como la contraseña."
            if is_json_request:
                return JsonResponse({"error": error_msg}, status=400)
            
            messages.error(request, error_msg)
            return render(request, "usuarios/login.html", {"email": username_or_email})

        # 3. Verificación de credenciales (RNF04 - Comparación segura de Hash)
        # Primero intentamos autenticar directamente por username
        user = authenticate(request, username=username_or_email, password=password)

        # Si el usuario no fue autenticado por username, buscar si corresponde al email del usuario Django
        if user is None:
            try:
                user_obj = User.objects.filter(email__iexact=username_or_email).first()
                if user_obj:
                    # authenticate() compara el hash de password de forma segura contra la base de datos
                    user = authenticate(request, username=user_obj.username, password=password)
            except Exception:
                pass

        # Integración opcional con Supabase Auth si está configurado en el entorno
        if user is None and getattr(settings, "SUPABASE_URL", None) and getattr(settings, "SUPABASE_ANON_KEY", None):
            try:
                from .supabase_client import get_supabase_client
                supabase = get_supabase_client()
                auth_resp = supabase.auth.sign_in_with_password({
                    "email": username_or_email,
                    "password": password
                })
                if auth_resp and auth_resp.user:
                    # Sincronizar o crear el usuario local de sesión Django
                    user, _ = User.objects.get_or_create(
                        username=auth_resp.user.email,
                        defaults={
                            "email": auth_resp.user.email,
                            "first_name": (auth_resp.user.user_metadata or {}).get("nombres", ""),
                            "last_name": (auth_resp.user.user_metadata or {}).get("apellidos", ""),
                        }
                    )
            except Exception:
                pass

        # 4. Procesamiento del resultado de la autenticación
        if user is not None:
            if not user.is_active:
                error_msg = "Esta cuenta de usuario se encuentra inactiva. Contacte al administrador."
                if is_json_request:
                    return JsonResponse({"error": error_msg}, status=403)
                messages.error(request, error_msg)
                return render(request, "usuarios/login.html", {"email": username_or_email})

            # Iniciar sesión HTTP de Django
            login(request, user)

            # Gestión de duración de sesión (Recordarme)
            if remember_me:
                # Sesión persistente por 2 semanas (1209600 segundos)
                request.session.set_expiry(1209600)
            else:
                # La cookie expira al cerrar el navegador
                request.session.set_expiry(0)

            # Mensaje de bienvenida dinámico
            nombre_mostrar = user.first_name if user.first_name else user.username
            messages.success(request, f"¡Bienvenido de nuevo, {nombre_mostrar}!")

            # Respuesta para peticiones API
            if is_json_request:
                return JsonResponse({
                    "status": "success",
                    "message": f"Autenticación exitosa. ¡Bienvenido, {nombre_mostrar}!",
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                    }
                }, status=200)

            # Redirección para formulario web
            next_url = request.GET.get("next") or request.POST.get("next") or "home"
            return redirect(next_url)

        # 5. Autenticación fallida: Mensaje genérico para evitar enumeración de cuentas
        generic_error = "Correo electrónico o contraseña incorrectos. Por favor verifique sus datos."
        if is_json_request:
            return JsonResponse({"error": generic_error}, status=401)

        messages.error(request, generic_error)
        return render(request, "usuarios/login.html", {"email": username_or_email})

    return HttpResponse("Método no permitido", status=405)


def logout_view(request: HttpRequest) -> HttpResponse:
    """
    Controlador para cerrar la sesión HTTP del usuario (HU02-ST4).
    """
    logout(request)
    messages.info(request, "Has cerrado sesión correctamente. ¡Hasta pronto!")
    return redirect("login")


def registro_view(request: HttpRequest) -> HttpResponse:
    """
    Controlador temporal para renderizar la pantalla de registro de usuarios (HU-01).
    """
    return render(request, "usuarios/registro.html")


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

