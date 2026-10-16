"""Rutas web del catálogo maestro de variedades de café (HU10)."""

from django.urls import path

from . import views


urlpatterns = [
    path(
        "trazabilidad/",
        views.administrar_trazabilidad_view,
        name="administrar_trazabilidad",
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
