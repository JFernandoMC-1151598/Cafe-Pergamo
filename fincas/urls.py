"""
Rutas URL del módulo de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
Subtarea: SCRUM-92 / HU06-ST6: Listar fincas registradas por productor.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Interfaz Web
    path('registro/', views.registrar_finca_view, name='finca_registro'),
    path('mis-fincas/', views.mis_fincas_view, name='mis_fincas'),

    # API REST de Fincas y Georreferenciación (SCRUM-96)
    path('api/', views.api_crear_finca_view, name='api_finca_crear'),
    path('api/<int:pk>/', views.api_detalle_finca_view, name='api_finca_detalle'),
]
