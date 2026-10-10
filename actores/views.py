"""Vistas protegidas para la gestión de actores de la cadena (HU08)."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from usuarios.permissions import permiso_requerido_sesion


@permiso_requerido_sesion(
    "asociaciones.gestionar",
    forbidden_on_denied=True,
)
def registro_actor_view(request: HttpRequest) -> HttpResponse:
    """Muestra el formulario de registro únicamente a administradores."""
    return render(request, "actores/registro_actor.html")
