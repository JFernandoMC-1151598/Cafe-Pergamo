"""
Módulo de Seguridad y Control de Intentos de Autenticación - CAFÉ PÉRGAMO
Subtarea: SCRUM-79 / HU02-ST5: Control de intentos fallidos y bloqueo de cuenta.

Reglas implementadas:
- RN03 / EX-3: Límite de 5 intentos fallidos consecutivos con bloqueo temporal de 15 minutos.
- RNF07: Prevención de ataques de enumeración y filtración de cuentas.
"""

from datetime import timedelta
from typing import Optional, Tuple
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from .models import RegistroIntentoLogin


# Configuración de límites y tiempos de bloqueo (con fallbacks seguros)
FAILURE_LIMIT = getattr(settings, "LOGIN_FAILURE_LIMIT", 5)
COOLOFF_MINUTES = getattr(settings, "LOGIN_COOLOFF_MINUTES", 15)
RESET_ON_SUCCESS = getattr(settings, "LOGIN_RESET_ON_SUCCESS", True)


def obtener_ip_cliente(request) -> str:
    """Extrae la dirección IP del cliente a partir de los encabezados HTTP."""
    if not request:
        return ""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def resolver_identificador_canonico(username_or_email: str) -> Tuple[str, Optional[User]]:
    """
    Normaliza el identificador de usuario y resuelve el usuario de Django asociado.
    
    Garantiza que intentos realizados por 'email' o por 'username' apunten a la
    misma cuenta de usuario para evitar bypasses de control de intentos.
    """
    identificador_limpio = (username_or_email or "").strip().lower()
    if not identificador_limpio:
        return "", None

    user = None
    if "@" in identificador_limpio:
        user = User.objects.filter(email__iexact=identificador_limpio).first()
    if not user:
        user = User.objects.filter(username__iexact=identificador_limpio).first()

    if user:
        return user.username.lower(), user

    return identificador_limpio, None


def obtener_registro_seguridad(username_or_email: str) -> Optional[RegistroIntentoLogin]:
    """Obtiene el registro de intentos de login existente sin crearlo."""
    canonico, _ = resolver_identificador_canonico(username_or_email)
    if not canonico:
        return None
    return RegistroIntentoLogin.objects.filter(identificador=canonico).first()


def verificar_cuenta_bloqueada(username_or_email: str) -> Tuple[bool, Optional[RegistroIntentoLogin], int]:
    """
    Verifica si una cuenta se encuentra actualmente bloqueada por intentos fallidos.
    
    Si el período de enfriamiento (cooloff) ya transcurrió, desbloquea automáticamente
    la cuenta y reinicia el contador de intentos fallidos.
    
    Retorna: (esta_bloqueada, registro, minutos_restantes)
    """
    registro = obtener_registro_seguridad(username_or_email)
    if not registro:
        return False, None, 0

    # Verificar si el bloqueo ya expiró
    if registro.locked_until:
        if registro.locked_until <= timezone.now():
            registro.failed_attempts = 0
            registro.locked_until = None
            registro.save(update_fields=["failed_attempts", "locked_until", "ultimo_intento"])
            sincronizar_perfil_usuario_supabase(registro.user, 0, None)
            return False, registro, 0
        else:
            return True, registro, registro.tiempo_restante_minutos()

    return False, registro, 0


def registrar_intento_fallido(
    username_or_email: str, 
    request=None
) -> Tuple[bool, RegistroIntentoLogin]:
    """
    Registra un intento de autenticación fallido para el identificador suministrado.
    
    Si el número de intentos fallidos consecutivos alcanza o supera LOGIN_FAILURE_LIMIT,
    la cuenta queda bloqueada hasta `now + LOGIN_COOLOFF_MINUTES`.
    
    Retorna: (quedo_bloqueado, registro)
    """
    canonico, user = resolver_identificador_canonico(username_or_email)
    if not canonico:
        canonico = (username_or_email or "desconocido").strip().lower()

    registro, _ = RegistroIntentoLogin.objects.get_or_create(
        identificador=canonico,
        defaults={"user": user}
    )

    # Si el usuario no estaba enlazado y ahora fue resuelto, vincularlo
    if user and not registro.user:
        registro.user = user

    ahora = timezone.now()

    # Si tenía un bloqueo previo que ya venció, limpiar el contador antes de sumar el nuevo fallo
    if registro.locked_until and registro.locked_until <= ahora:
        registro.failed_attempts = 0
        registro.locked_until = None

    registro.failed_attempts += 1
    if request:
        registro.ip_address = obtener_ip_cliente(request)

    quedo_bloqueado = False
    if registro.failed_attempts >= FAILURE_LIMIT:
        registro.locked_until = ahora + timedelta(minutes=COOLOFF_MINUTES)
        quedo_bloqueado = True

    registro.save()

    # Sincronización opcional con el modelo Usuario de Supabase/PostgreSQL
    sincronizar_perfil_usuario_supabase(user, registro.failed_attempts, registro.locked_until)

    return quedo_bloqueado, registro


def resetear_intentos(username_or_email: str, user=None) -> None:
    """
    Reinicia el contador de intentos fallidos a 0 y retira el bloqueo
    tras una autenticación exitosa (RN03 / AXES_RESET_ON_SUCCESS).
    """
    if not RESET_ON_SUCCESS:
        return

    canonico, resolved_user = resolver_identificador_canonico(username_or_email)
    user_actual = user or resolved_user

    if not canonico:
        return

    registro = RegistroIntentoLogin.objects.filter(identificador=canonico).first()
    if registro:
        if registro.failed_attempts > 0 or registro.locked_until is not None:
            registro.failed_attempts = 0
            registro.locked_until = None
            registro.save(update_fields=["failed_attempts", "locked_until", "ultimo_intento"])

    # Sincronización opcional con el modelo Usuario de Supabase/PostgreSQL
    sincronizar_perfil_usuario_supabase(user_actual, 0, None)


def sincronizar_perfil_usuario_supabase(user, failed_attempts: int, locked_until) -> None:
    """
    Sincroniza los campos de seguridad en el modelo Usuario de Supabase si está disponible.
    Falla de manera silenciosa si las tablas no están presentes en el entorno local.
    """
    if not user:
        return
    try:
        from django.db import connection
        if "usuarios" in connection.introspection.table_names():
            from .models import Usuario
            correo = user.email or user.username
            if correo and "@" in correo:
                Usuario.objects.filter(correo__iexact=correo).update(
                    failed_attempts=failed_attempts,
                    locked_until=locked_until
                )
    except Exception:
        pass

