"""Vistas del catálogo maestro de variedades de café (HU10)."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from usuarios.permissions import permiso_requerido_sesion

from .models import VariedadCafe


@permiso_requerido_sesion(
    "catalogos_maestros.consultar",
    forbidden_on_denied=True,
)
def lista_variedades_view(request: HttpRequest) -> HttpResponse:
    """Lista variedades activas e inactivas, con filtro opcional por estado."""
    estado = request.GET.get("estado", "").strip().lower()
    variedades = VariedadCafe.objects.all()

    if estado == "activas":
        variedades = variedades.filter(activo=True)
    elif estado == "inactivas":
        variedades = variedades.filter(activo=False)
    else:
        estado = ""

    return render(
        request,
        "catalogos/lista_variedades.html",
        {
            "variedades": variedades,
            "estado_filtro": estado,
        },
    )
