"""Rutas web del catálogo maestro de variedades de café (HU10)."""

from django.urls import path

from . import views


urlpatterns = [
    path(
        "api/procesos-beneficio/",
        views.api_procesos_beneficio_view,
        name="api_procesos_beneficio",
    ),
    path(
        "api/procesos-beneficio/<int:pk>/",
        views.api_proceso_beneficio_detalle_view,
        name="api_proceso_beneficio_detalle",
    ),
    path(
        "api/procesos-beneficio/<int:pk>/toggle-activo/",
        views.api_proceso_beneficio_toggle_view,
        name="api_proceso_beneficio_toggle",
    ),
    path(
        "api/estados-lote/",
        views.api_estados_lote_view,
        name="api_estados_lote",
    ),
    path(
        "api/estados-lote/<int:pk>/",
        views.api_estado_lote_detalle_view,
        name="api_estado_lote_detalle",
    ),
    path(
        "api/estados-lote/<int:pk>/toggle-activo/",
        views.api_estado_lote_toggle_view,
        name="api_estado_lote_toggle",
    ),
    path(
        "trazabilidad/",
        views.administrar_trazabilidad_view,
        name="administrar_trazabilidad",
    ),
    path(
        "trazabilidad/procesos/crear/",
        views.crear_proceso_beneficio_view,
        name="crear_proceso_beneficio",
    ),
    path(
        "trazabilidad/procesos/<int:pk>/editar/",
        views.editar_proceso_beneficio_view,
        name="editar_proceso_beneficio",
    ),
    path(
        "trazabilidad/procesos/<int:pk>/estado/",
        views.alternar_proceso_beneficio_view,
        name="alternar_proceso_beneficio",
    ),
    path(
        "trazabilidad/estados/crear/",
        views.crear_estado_lote_view,
        name="crear_estado_lote",
    ),
    path(
        "trazabilidad/estados/<int:pk>/editar/",
        views.editar_estado_lote_view,
        name="editar_estado_lote",
    ),
    path(
        "trazabilidad/estados/<int:pk>/estado/",
        views.alternar_estado_lote_view,
        name="alternar_estado_lote",
    ),
    path("variedades/", views.lista_variedades_view, name="lista_variedades"),
    path(
        "variedades/crear/",
        views.crear_variedad_view,
        name="crear_variedad",
    ),
    path(
        "variedades/<int:variedad_id>/editar/",
        views.editar_variedad_view,
        name="editar_variedad",
    ),
    path(
        "variedades/<int:variedad_id>/estado/",
        views.alternar_estado_variedad_view,
        name="alternar_estado_variedad",
    ),
]
