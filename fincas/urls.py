"""
Rutas URL del módulo de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
Subtarea: SCRUM-92 / HU06-ST6: Listar fincas registradas por productor.
Subtarea: SCRUM-142 / HU13-ST2: Implementar servicio/API para registrar lotes.
Subtarea: SCRUM-144 / HU13: Crear formulario o pantalla de registro de lotes
(incluye también la ruta de registro de cosechas, complemento necesario).
"""

from django.urls import path
from . import views

urlpatterns = [
    # Interfaz Web de Fincas (HU-06 / HU-07)
    path('registro/', views.registrar_finca_view, name='finca_registro'),
    path('mis-fincas/', views.mis_fincas_view, name='mis_fincas'),

    # Interfaz Web de Cosechas y Lotes (HU-13)
    path('cosechas/registro/', views.registrar_cosecha_view, name='cosecha_registro'),
    path('lotes/registro/', views.registrar_lote_view, name='lote_registro'),
    path('mis-lotes/', views.mis_lotes_view, name='mis_lotes'),

    # Interfaz Web de Catálogo de Municipios (HU-09 / SCRUM-111)
    path('municipios/', views.admin_municipios_view, name='admin_municipios'),
    path('municipios/crear/', views.crear_municipio_web_view, name='crear_municipio_web'),
    path('municipios/<int:pk>/editar/', views.editar_municipio_web_view, name='editar_municipio_web'),
    path('municipios/<int:pk>/alternar-estado/', views.alternar_estado_municipio_web_view, name='alternar_estado_municipio_web'),

    # API REST de Fincas y Georreferenciación (SCRUM-96)
    path('api/', views.api_crear_finca_view, name='api_finca_crear'),
    path('api/<int:pk>/', views.api_detalle_finca_view, name='api_finca_detalle'),

    # API REST de Municipios / Catálogos (SCRUM-112, SCRUM-110, SCRUM-113)
    path('api/municipios/', views.api_municipios_coleccion_view, name='api_municipios_coleccion'),
    path('api/municipios/<int:pk>/', views.api_municipio_detalle_view, name='api_municipio_detalle'),
    path('api/municipios/<int:pk>/inactivar/', views.api_municipio_toggle_activo_view, name='api_municipio_inactivar'),
    path('api/municipios/<int:pk>/toggle-activo/', views.api_municipio_toggle_activo_view, name='api_municipio_toggle_activo'),

    # API REST de Lotes (HU-13 / SCRUM-142)
    path('api/lotes/', views.api_crear_lote_view, name='api_lote_crear'),
]
