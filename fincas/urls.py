"""
Rutas URL del módulo de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
"""

from django.urls import path
from . import views

urlpatterns = [
    path('registro/', views.registrar_finca_view, name='finca_registro'),
]
