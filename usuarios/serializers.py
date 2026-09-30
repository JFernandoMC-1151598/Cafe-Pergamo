"""
Serializadores para el módulo de Usuarios y Autenticación JWT - CAFÉ PÉRGAMO
Subtarea: SCRUM-77 / HU02-ST3: Generación de Tokens de Sesión (JWT).
"""

from typing import Any, Dict
from django.contrib.auth.models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import Token


def obtener_rol_usuario(user: User) -> str:
    """
    Determina el rol principal de negocio asignado al usuario.
    
    Prioridad:
    1. Si es superusuario de Django -> 'Administrador'.
    2. Perfil de negocio 'Usuario' (RBAC de Café Pérgamo en PostgreSQL/Supabase).
    3. Grupo de usuarios de Django ('Administrador', 'Productor', 'Comprador', etc.).
    4. Valor predeterminado de seguridad ('Usuario').
    """
    if user.is_superuser:
        return "Administrador"

    # Consulta del rol en el modelo de dominio Usuario (RBAC)
    try:
        from .models import Usuario
        perfil = (
            Usuario.objects.filter(correo__iexact=user.email)
            .select_related("rol")
            .first()
        )
        if perfil and perfil.rol:
            return perfil.rol.nombre
    except Exception:
        # En caso de fallo transitorio o tablas no sincronizadas
        pass

    # Consulta a grupos estándar de Django
    primer_grupo = user.groups.first()
    if primer_grupo:
        return primer_grupo.name

    return "Usuario"


def obtener_nombre_completo(user: User) -> str:
    """Obtiene el nombre completo formateado del usuario o su username como fallback."""
    nombre_completo = f"{user.first_name} {user.last_name}".strip()
    if nombre_completo:
        return nombre_completo

    # Intentar obtener del perfil Usuario
    try:
        from .models import Usuario
        perfil = Usuario.objects.filter(correo__iexact=user.email).first()
        if perfil:
            perfil_nombre = f"{perfil.nombres} {perfil.apellidos}".strip()
            if perfil_nombre:
                return perfil_nombre
    except Exception:
        pass

    return user.username


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Serializador personalizado de emisión de tokens JWT.
    
    Extiende TokenObtainPairSerializer para:
    1. Incrustar Claims Personalizados (Custom Claims) en el payload del token (access):
       - 'role': Rol asignado en la plataforma (Administrador, Productor, Comprador, etc.).
       - 'email': Correo electrónico verificado.
       - 'full_name': Nombre completo del usuario.
       - 'username': Nombre de usuario registrado.
    2. Soportar inicio de sesión mediante 'email' o 'username'.
    3. Enriquecer la respuesta JSON con la información estructurada del usuario.
    """

    @classmethod
    def get_token(cls, user: User) -> Token:
        """
        Genera el token e incrusta los claims personalizados en su payload.
        """
        token = super().get_token(user)

        # Resolver claims de identidad y rol
        rol_usuario = obtener_rol_usuario(user)
        nombre_completo = obtener_nombre_completo(user)
        correo_usuario = user.email or user.username

        # Incrustar claims personalizados en el payload del token JWT
        token["role"] = rol_usuario
        token["email"] = correo_usuario
        token["full_name"] = nombre_completo
        token["username"] = user.username

        return token

    def to_internal_value(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Permite que el cliente envíe 'email' o 'username' indistintamente."""
        if isinstance(data, dict):
            email_val = data.get("email")
            if email_val and not data.get(self.username_field):
                data = data.copy()
                data[self.username_field] = email_val
        return super().to_internal_value(data)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida las credenciales recibidas y enriquece la respuesta con metadatos.
        """
        identificador = attrs.get(self.username_field)

        # Si el identificador provisto contiene formato de correo, resolver el username de Django
        if identificador and "@" in identificador:
            try:
                usuario_obj = User.objects.filter(email__iexact=identificador).first()
                if usuario_obj:
                    attrs[self.username_field] = usuario_obj.username
            except Exception:
                pass

        # Ejecuta la validación nativa de credenciales y contraseña segura (RNF04)
        data = super().validate(attrs)

        # Enriquecer la respuesta HTTP con metadatos del usuario autenticado
        rol_usuario = obtener_rol_usuario(self.user)
        nombre_completo = obtener_nombre_completo(self.user)
        correo_usuario = self.user.email or self.user.username

        data["user"] = {
            "id": self.user.id,
            "username": self.user.username,
            "email": correo_usuario,
            "full_name": nombre_completo,
            "role": rol_usuario,
        }

        return data
