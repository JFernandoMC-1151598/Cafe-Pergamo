"""
Autorización RBAC por claims de JWT - CAFÉ PÉRGAMO
Subtarea: SCRUM-108 / HU04-ST2: Autorización y Validación de JWT (RNF06).

HU04-ST1 (SCRUM-101) ya construyó el esquema de tablas y la matriz RBAC
(`usuarios/models.py`: Rol, Permiso, RolPermiso) y la sembró en Supabase.
Esta subtarea construye la pieza que falta: el componente que, en cada
petición autenticada con JWT, lee el claim de rol del token y decide si
ese rol tiene el permiso necesario para consumir el endpoint solicitado,
consultando esa misma matriz.

Esta pieza NO reinventa el catálogo de permisos ni asigna permisos a
roles "a mano" en Python — eso ya vive en la base de datos (tabla
`rol_permisos`) y se administra ahí. Aquí solo se consulta.

Se ofrecen dos formas de uso, para cubrir tanto vistas basadas en clase
(DRF, como CustomTokenObtainPairView) como vistas basadas en función
(el estilo que usa el resto de `usuarios/views.py`):

1. `TienePermisoRBAC` — permission_class de Django REST Framework para
   vistas basadas en clase:

       class AlgunaVistaAdmin(APIView):
           permission_classes = [TienePermisoRBAC]
           required_permission = "usuarios.administrar"
           ...

2. `permiso_requerido(codigo_permiso)` — decorador para vistas basadas
   en función (requiere JWT en el header Authorization: Bearer <token>,
   igual que las vistas de DRF; no reemplaza la sesión web de Django):

       @permiso_requerido("usuarios.administrar")
       def alguna_vista_admin(request):
           ...

Ambos caminos terminan en `usuario_tiene_permiso()`, que es la única
función que realmente consulta la matriz RolPermiso — así la regla de
autorización se evalúa siempre de la misma forma sin importar por
dónde entró la petición.
"""

from functools import wraps
from typing import Iterable, Union

from django.http import JsonResponse
from rest_framework.permissions import BasePermission
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

CodigoPermiso = Union[str, Iterable[str]]


def usuario_tiene_permiso(role_code: str, permiso_codigo: CodigoPermiso) -> bool:
    """
    Verifica, contra la matriz RBAC (tabla `rol_permisos`), si el rol
    identificado por `role_code` (ej. "PRODUCTOR") tiene concedido el
    permiso `permiso_codigo` (ej. "usuarios.administrar").

    `permiso_codigo` puede ser un único código, o una lista de códigos
    — en ese caso basta con que el rol tenga CUALQUIERA de ellos (OR),
    útil para endpoints a los que pueden entrar varios roles distintos
    con intenciones equivalentes (ej. "ver" algo).

    Por seguridad (RNF06), cualquier entrada vacía o inválida devuelve
    False: esta función nunca concede acceso "por accidente". Solo
    cuentan los permisos cuyo rol Y permiso están activos
    (`activo = True`), igual que ya exige el resto del sistema (ver
    `registro_api` en views.py, que ya filtra roles por `activo=True`).
    """
    if not role_code:
        return False

    if isinstance(permiso_codigo, str):
        codigos = [permiso_codigo]
    else:
        codigos = [c for c in permiso_codigo if c]

    if not codigos:
        return False

    from .models import RolPermiso

    return RolPermiso.objects.filter(
        rol__codigo=role_code,
        rol__activo=True,
        permiso__codigo__in=codigos,
        permiso__activo=True,
    ).exists()


class TienePermisoRBAC(BasePermission):
    """
    Permission class de DRF: autoriza la petición solo si el claim
    'role_code' del JWT (ver CustomTokenObtainPairSerializer en
    serializers.py) tiene, según la matriz RBAC, el permiso declarado
    en `required_permission` de la vista.

    Se usa junto a la autenticación JWT ya configurada por defecto en
    todo el proyecto (settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']),
    así que normalmente no hace falta nada más que declarar
    `permission_classes = [TienePermisoRBAC]` y `required_permission`
    en la vista.

    Diseño "fail-closed" (deniega por defecto), consistente con RNF06:
      - Si la vista no declara `required_permission`, se deniega (es un
        error de configuración del desarrollador, no un "permiso libre").
      - Si no hay token JWT validado (`request.auth` vacío, por ejemplo
        porque la petición solo trae sesión de Django, no JWT), se
        deniega.
      - Si el token no trae claim 'role_code' (tokens emitidos antes de
        esta subtarea, o de otro flujo), se deniega.
    """

    message = "No tiene permiso para acceder a este recurso."

    def has_permission(self, request, view) -> bool:
        permiso_codigo = getattr(view, "required_permission", None)
        if not permiso_codigo:
            return False

        role_code = self._extraer_role_code(request)
        if not role_code:
            return False

        return usuario_tiene_permiso(role_code, permiso_codigo)

    @staticmethod
    def _extraer_role_code(request) -> str:
        """Lee el claim 'role_code' del token JWT validado por DRF."""
        token = getattr(request, "auth", None)
        if token is None:
            return ""
        try:
            return token.get("role_code", "") or ""
        except AttributeError:
            return ""


def permiso_requerido(permiso_codigo: CodigoPermiso):
    """
    Decorador de autorización RBAC para vistas basadas en función
    (el estilo que usa el resto de usuarios/views.py).

    Valida el JWT del header 'Authorization: Bearer <token>' igual que
    lo haría DRF, lee su claim 'role_code' y lo verifica contra la
    matriz RBAC para `permiso_codigo`. Responde JSON siempre (estas
    vistas son endpoints de API, no páginas HTML):
      - 401 si no hay token válido.
      - 403 si el token es válido pero el rol no tiene el permiso.

    Ejemplo:
        @permiso_requerido("usuarios.administrar")
        def admin_listar_usuarios(request):
            ...
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            auth = JWTAuthentication()
            try:
                resultado = auth.authenticate(request)
            except (InvalidToken, TokenError):
                resultado = None

            if resultado is None:
                return JsonResponse(
                    {"error": "Se requiere un token de autenticación válido."},
                    status=401,
                )

            usuario_django, token = resultado
            role_code = ""
            try:
                role_code = token.get("role_code", "") or ""
            except AttributeError:
                pass

            if not role_code or not usuario_tiene_permiso(role_code, permiso_codigo):
                return JsonResponse(
                    {"error": "No tiene permiso para acceder a este recurso."},
                    status=403,
                )

            request.user = usuario_django
            request.auth = token
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador
