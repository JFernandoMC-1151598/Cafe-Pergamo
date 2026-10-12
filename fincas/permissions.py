"""
Permisos y autorización RBAC para el módulo de Fincas y Catálogos - CAFÉ PÉRGAMO
Subtarea: SCRUM-116 / HU09-ST8: Configurar permisos para la gestión del catálogo (RNF06 / RNF21).

Este módulo define las constantes, verificadores y decoradores de autorización RBAC
para asegurar que la gestión (creación, edición e inactivación) de municipios y
catálogos maestros quede restringida a los roles con privilegios suficientes:
- ASOCIACIÓN
- ADMINISTRADOR

Y denegada para roles no autorizados (PRODUCTOR, COMPRADOR, OPERARIO_CAMPO,
CONSULTA_PUBLICA) y usuarios anónimos.
"""

from functools import wraps
from typing import Any, Optional, Union

from django.http import HttpRequest
from rest_framework.permissions import BasePermission

from usuarios.permissions import (
    TienePermisoRBAC,
    permiso_requerido,
    permiso_requerido_sesion,
    usuario_tiene_permiso,
)

# Constantes de permisos de catálogos y municipios (matriz RBAC)
PERMISO_CATALOGO_ADMINISTRAR = "catalogos_maestros.administrar"
PERMISO_CATALOGO_CONSULTAR = "catalogos_maestros.consultar"
PERMISO_MUNICIPIOS_ADMINISTRAR = "municipios.administrar"

# Conjunto de permisos aceptados para administrar el catálogo de municipios
PERMISOS_GESTION_MUNICIPIOS = (
    PERMISO_CATALOGO_ADMINISTRAR,
    PERMISO_MUNICIPIOS_ADMINISTRAR,
)


def rol_puede_administrar_catalogos(rol_codigo: Optional[str]) -> bool:
    """
    Verifica si un código de rol cuenta con permisos para administrar catálogos.
    Consulta la matriz RBAC vigente a través de `usuario_tiene_permiso`.
    """
    if not rol_codigo:
        return False
    return usuario_tiene_permiso(rol_codigo, PERMISOS_GESTION_MUNICIPIOS)


def request_puede_administrar_catalogos(request: HttpRequest) -> bool:
    """
    Comprueba si la solicitud actual (por sesión o token autenticado)
    pertenece a un rol con autorización para administrar catálogos.
    """
    if not request or not getattr(request, "user", None):
        return False

    # 1. Sesión web de Django
    rol_sesion = getattr(request, "session", {}).get("rol", "")
    if rol_sesion and rol_puede_administrar_catalogos(rol_sesion):
        return True

    # 2. Token JWT autenticado en DRF
    token = getattr(request, "auth", None)
    if token is not None:
        try:
            rol_token = token.get("role_code", "")
            if rol_token and rol_puede_administrar_catalogos(rol_token):
                return True
        except AttributeError:
            pass

    # 3. Superusuario de Django (acceso administrativo de emergencia/consola)
    if getattr(request.user, "is_superuser", False):
        return True

    return False


def permiso_administrar_catalogo_sesion(
    vista=None,
    *,
    forbidden_on_denied: bool = True,
):
    """
    Decorador para vistas web de administración del catálogo de municipios.
    Aplica protección de sesión RBAC:
    - Redirige a login si la sesión no está autenticada.
    - Si está autenticada pero carece de permisos:
      * Responde HTTP 403 Forbidden si `forbidden_on_denied=True` (comportamiento por defecto seguro).
      * O redirige al home con mensaje si `forbidden_on_denied=False`.
    """
    def decorador_real(fn):
        decorada = permiso_requerido_sesion(
            PERMISOS_GESTION_MUNICIPIOS,
            forbidden_on_denied=forbidden_on_denied,
        )(fn)
        return decorada

    if vista is not None:
        return decorador_real(vista)
    return decorador_real


def permiso_administrar_catalogo_api(vista=None):
    """
    Decorador para endpoints REST basados en función que gestionan municipios.
    Valida el token Bearer JWT y restringe a roles con permiso en catálogos.
    Responde 401 si no hay token o 403 si el rol no tiene permisos.
    """
    def decorador_real(fn):
        return permiso_requerido(PERMISOS_GESTION_MUNICIPIOS)(fn)

    if vista is not None:
        return decorador_real(vista)
    return decorador_real


class TienePermisoAdministrarCatalogo(TienePermisoRBAC):
    """
    Permission class de DRF para vistas basadas en clase (CBV) o ViewSets
    que administran el catálogo de municipios.
    """
    def has_permission(self, request, view) -> bool:
        permiso_codigo = getattr(view, "required_permission", None)
        if not permiso_codigo:
            permiso_codigo = PERMISOS_GESTION_MUNICIPIOS

        role_code = self._extraer_role_code(request)
        if not role_code:
            return False

        if permiso_codigo == PERMISOS_GESTION_MUNICIPIOS:
            return rol_puede_administrar_catalogos(role_code)

        return usuario_tiene_permiso(role_code, permiso_codigo)
