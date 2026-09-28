"""
Rutas URL del módulo de Usuarios - CAFÉ PÉRGAMO
Subtarea: SCRUM-76 / HU02-ST2: Autenticación y verificación de credenciales.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Vistas de interfaz Web
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registro/', views.registro_view, name='registro'),

    # Endpoints y alias API (HU02-ST2: POST /api/auth/login)
    path('api/auth/login', views.login_view, name='api_auth_login_raw'),
    path('api/auth/login/', views.login_view, name='api_auth_login'),
]
