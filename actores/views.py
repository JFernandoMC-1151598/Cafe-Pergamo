"""Vistas protegidas para la gestión de actores de la cadena (HU08)."""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import ActorCadenaForm
from usuarios.permissions import permiso_requerido_sesion


@permiso_requerido_sesion(
    "asociaciones.gestionar",
    forbidden_on_denied=True,
)
def registro_actor_view(request: HttpRequest) -> HttpResponse:
    """Muestra y procesa el formulario de registro de actores."""
    if request.method == "POST":
        form = ActorCadenaForm(request.POST)
        if form.is_valid():
            actor = form.save()
            messages.success(
                request,
                f"El actor «{actor.razon_social}» fue registrado exitosamente.",
            )
            return redirect("registro_actor")

        messages.error(
            request,
            "Por favor revise los errores señalados en el formulario.",
        )
    else:
        form = ActorCadenaForm()

    return render(request, "actores/registro_actor.html", {"form": form})
