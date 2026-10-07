"""
Vistas del módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
"""

from django.shortcuts import render
from django.contrib import messages
from .forms import FincaRegistroForm


def registrar_finca_view(request):
    """
    Vista para renderizar y procesar la experiencia de captura de datos de Finca,
    con soporte para el campo opcional de georreferenciación (HU-07).
    """
    if request.method == "POST":
        form = FincaRegistroForm(request.POST)
        if form.is_valid():
            latitud = form.cleaned_data.get("latitud")
            longitud = form.cleaned_data.get("longitud")
            nombre = form.cleaned_data.get("nombre")

            if latitud is not None and longitud is not None:
                messages.success(
                    request,
                    f"Finca '{nombre}' registrada exitosamente con georreferenciación: ({latitud}, {longitud})."
                )
            else:
                messages.success(
                    request,
                    f"Finca '{nombre}' registrada exitosamente sin coordenadas de georreferenciación (campo opcional)."
                )
            form = FincaRegistroForm()
    else:
        form = FincaRegistroForm()

    return render(request, "fincas/registro_finca.html", {"form": form})
