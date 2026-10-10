"""Rutas web protegidas para actores de la cadena (HU08)."""

from django.urls import path

from . import views


urlpatterns = [
    path("registro/", views.registro_actor_view, name="registro_actor"),
]
