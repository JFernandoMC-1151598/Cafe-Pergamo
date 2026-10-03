"""
Rutas URL del módulo de Usuarios - CAFÉ PÉRGAMO
Subtarea: SCRUM-76 / HU02-ST2: Autenticación y verificación de credenciales.
Subtarea: SCRUM-60 / HU01-ST3: Registro de usuarios.
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views
from .password_reset import password_reset_request_api, password_reset_supabase_redirect

urlpatterns = [
    # Vistas de interfaz Web principales
    path('', views.home_view, name='home'),
    path('catalogo/', views.catalogo_view, name='catalogo'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro/', views.registro_view, name='registro'),
    # NOTA (merge franciscogallo -> david, 2026-10-01): franciscogallo
    # traía estas 2 rutas apuntando a funciones que no existían en
    # views.py (AttributeError al arrancar el proyecto). Se agregaron
    # vistas mínimas (solo renderizan la plantilla, ver sus docstrings)
    # para que login.html (que enlaza a 'recuperar_contrasena') y estas
    # rutas no rompan el sitio; la lógica real de recuperación de
    # contraseña queda pendiente como funcionalidad aparte.
    path('recuperar-contrasena/', views.recuperar_contrasena_view, name='recuperar_contrasena'),
    path('restablecer-contrasena/', password_reset_supabase_redirect, name='restablecer_contrasena_supabase'),
    path('restablecer-contrasena/<str:token>/', views.restablecer_contrasena_view, name='restablecer_contrasena'),
    path('api/auth/password-reset/request/', password_reset_request_api, name='password_reset_request'),

    # Endpoints y alias API (HU02-ST2: POST /api/auth/login)
    path('api/auth/login', views.login_view, name='api_auth_login_raw'),
    path('api/auth/login/', views.login_view, name='api_auth_login'),

    # Endpoints de revocación y cierre de sesión API (HU02-ST4)
    path('api/auth/logout', views.api_logout_view, name='api_auth_logout_raw'),
    path('api/auth/logout/', views.api_logout_view, name='api_auth_logout'),

    # Endpoints de generación y refresco de Tokens JWT (HU02-ST3)
    path('api/auth/token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # HU01-ST3 (SCRUM-60): endpoint de registro de usuarios (backend).
    # Esta ruta venía en david pero se perdió en el merge con
    # franciscogallo (su urls.py no la tenía); se restaura aquí porque
    # templates/usuarios/registro.html depende de ella (api_registro).
    path('api/auth/register', views.registro_api, name='api_registro'),

    # HU04-ST4 (SCRUM-119): panel de administración de usuarios y roles.
    path('admin/usuarios/', views.panel_administracion_usuarios, name='admin_usuarios'),

    # HU04-ST5 (SCRUM-120): endpoint de API para reasignar el rol de un
    # usuario, con auditoría (RF28).
    path('api/users/<uuid:user_id>/role', views.actualizar_rol_usuario_api, name='api_actualizar_rol_usuario_raw'),
    path('api/users/<uuid:user_id>/role/', views.actualizar_rol_usuario_api, name='api_actualizar_rol_usuario'),
]


