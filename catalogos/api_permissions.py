"""Permisos DRF para el mantenimiento de catálogos de trazabilidad."""

from rest_framework.permissions import BasePermission

from usuarios.permissions import usuario_tiene_permiso


class CatalogosTrazabilidadPermission(BasePermission):
    """Autoriza consulta o mantenimiento según el método HTTP."""

    message = "No tiene permiso para acceder a este recurso."

    def has_permission(self, request, view):
        token = getattr(request, "auth", None)
        role_code = token.get("role_code", "") if token else ""
        if not role_code and hasattr(request, "session"):
            role_code = request.session.get("rol", "")

        permiso = (
            "catalogos_maestros.consultar"
            if request.method == "GET"
            else "catalogos_maestros.administrar"
        )
        return bool(
            getattr(request.user, "is_authenticated", False)
            and role_code
            and usuario_tiene_permiso(role_code, permiso)
        )
