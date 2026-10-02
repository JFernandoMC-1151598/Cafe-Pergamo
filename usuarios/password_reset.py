import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from supabase_auth.errors import AuthApiError

from .supabase_client import get_supabase_client

PASSWORD_RESET_MESSAGE = (
    "Si el correo existe, recibira las instrucciones en su bandeja."
)


@csrf_exempt
@require_POST
def password_reset_request_api(request):
    """Solicita recuperación a Supabase Auth sin revelar si el correo existe."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "JSON invalido."}, status=400)
    else:
        data = request.POST

    email = str(data.get("email") or data.get("correo") or "").strip().lower()
    if not email:
        return JsonResponse({"error": "El correo es obligatorio."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "El correo no tiene un formato valido."}, status=400)

    redirect_url = request.build_absolute_uri(
        reverse("restablecer_contrasena_supabase")
    )

    try:
        get_supabase_client().auth.reset_password_for_email(
            email,
            {"redirect_to": redirect_url},
        )
    except AuthApiError:
        pass
    except RuntimeError:
        return JsonResponse(
            {"error": "El servicio de recuperacion no esta disponible."},
            status=503,
        )

    return JsonResponse({"message": PASSWORD_RESET_MESSAGE}, status=202)


def password_reset_supabase_redirect(request):
    """Renderiza la pantalla destino del enlace generado por Supabase Auth."""
    return render(
        request,
        "usuarios/restablecer_contrasena.html",
        {
            "supabase_url": settings.SUPABASE_URL or "",
            "supabase_anon_key": settings.SUPABASE_ANON_KEY or "",
        },
    )