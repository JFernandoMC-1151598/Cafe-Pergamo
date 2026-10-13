"""Rutas web del catálogo maestro de variedades de café (HU10)."""

from django.urls import path

from . import views


urlpatterns = [
    path("variedades/", views.lista_variedades_view, name="lista_variedades"),
]
