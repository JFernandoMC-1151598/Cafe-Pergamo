"""
Rutas URL del módulo de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
Subtarea: SCRUM-92 / HU06-ST6: Listar fincas registradas por productor.
Subtarea: SCRUM-142 / HU13-ST2: Implementar servicio/API para registrar lotes.
Subtarea: SCRUM-144 / HU13: Crear formulario o pantalla de registro de lotes
(incluye también la ruta de registro de cosechas, complemento necesario).
Subtarea: SCRUM-155 / HU15-ST1: Implementar persistencia de características
físicas y de calidad del lote.
Subtarea: SCRUM-148 / HU14-ST1 y SCRUM-149 / HU14-ST2: registro e historial
de etapas de beneficio del lote.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Interfaz Web de Fincas (HU-06 / HU-07)
    path('registro/', views.registrar_finca_view, name='finca_registro'),
    path('mis-fincas/', views.mis_fincas_view, name='mis_fincas'),

    # Interfaz Web de Cosechas y Lotes (HU-13 / HU-14 / HU-17 / HU-19)
    path('cosechas/registro/', views.registrar_cosecha_view, name='cosecha_registro'),
    path('lotes/registro/', views.registrar_lote_view, name='lote_registro'),
    path('mis-lotes/', views.mis_lotes_view, name='mis_lotes'),
    path('lotes/<int:pk>/', views.detalle_lote_view, name='lote_detalle'),
    path('lotes/<int:pk>/etapas/nueva/', views.registrar_etapa_beneficio_view, name='lote_etapa_registro'),
    path('lotes/<int:pk>/publicar/', views.publicar_lote_web_view, name='lote_publicar'),
    path('lotes/<int:pk>/despublicar/', views.despublicar_lote_web_view, name='lote_despublicar'),
    path('lotes/<str:codigo>/ficha/', views.ficha_digital_web_view, name='lote_ficha_digital_web'),
    path('trazabilidad/lote/<str:codigo>/', views.ficha_digital_web_view, name='trazabilidad_lote_publica'),

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

    # API REST de Cosechas (HU-12 / SCRUM-137)
    path('api/cosechas/', views.api_crear_cosecha_view, name='api_cosecha_crear'),

    # API REST de Lotes (HU-13 / SCRUM-142, HU-15 / SCRUM-155, HU-19 / SCRUM-239)
    path('api/lotes/', views.api_crear_lote_view, name='api_lote_crear'),
    path(
        'api/lotes/<int:lote_id>/calidad/',
        views.api_caracteristicas_calidad_view,
        name='api_lote_calidad',
    ),
    path(
        'api/lotes/<int:pk>/publicar/',
        views.api_publicar_lote_view,
        name='api_lote_publicar',
    ),
    path(
        'api/lotes/<int:pk>/despublicar/',
        views.api_despublicar_lote_view,
        name='api_lote_despublicar',
    ),
    path(
        'api/lotes/<int:pk>/validar-publicacion/',
        views.api_validar_publicacion_lote_view,
        name='api_lote_validar_publicacion',
    ),

    # API REST de Ficha Digital Consolidada por Lote (HU-17 / SCRUM-167)
    path('api/lotes/<str:codigo>/ficha/', views.api_consultar_ficha_digital_view, name='api_lote_ficha_digital'),
    path('api/v1/lotes/<str:codigo>/ficha/', views.api_consultar_ficha_digital_view, name='api_v1_lote_ficha_digital'),

    # API REST pública del catálogo con filtros combinados (HU-20 / SCRUM-250)
    path('api/catalogo/', views.api_catalogo_view, name='api_catalogo'),
]

