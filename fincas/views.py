"""
Vistas del módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .forms import FincaRegistroForm, FincaModelForm
from .models import Finca
from .serializers import FincaGeorreferenciacionSerializer


def registrar_finca_view(request):
    """
    Vista web para captura y persistencia de fincas (SCRUM-96).
    
    Criterios de Aceptación (DoD):
    - La vista persiste las coordenadas en BD o almacena NULL si no se ingresaron.
    - Soporte para productor en sesión (si está autenticado).
    - Retroalimentación informativa al usuario mediante mensajes flash.
    """
    if request.method == "POST":
        form = FincaRegistroForm(request.POST)
        if form.is_valid():
            nombre = form.cleaned_data["nombre"].strip()
            municipio = form.cleaned_data["municipio"].strip()
            vereda = form.cleaned_data.get("vereda")
            vereda = vereda.strip() if vereda else ""
            latitud = form.cleaned_data.get("latitud")
            longitud = form.cleaned_data.get("longitud")

            productor = request.user if request.user.is_authenticated else None

            # Persistencia en base de datos (SCRUM-96)
            finca = Finca.objects.create(
                nombre=nombre,
                municipio=municipio,
                vereda=vereda,
                latitud=latitud,      # Decimal o None (NULL en BD)
                longitud=longitud,    # Decimal o None (NULL en BD)
                productor=productor,
            )

            if finca.tiene_georreferenciacion:
                messages.success(
                    request,
                    f"Finca '{finca.nombre}' registrada exitosamente con georreferenciación: ({finca.latitud}, {finca.longitud})."
                )
            else:
                messages.success(
                    request,
                    f"Finca '{finca.nombre}' registrada exitosamente sin coordenadas de georreferenciación (almacenadas como NULL)."
                )

            return redirect("finca_registro")
        else:
            messages.error(
                request,
                "Por favor revise los errores señalados en el formulario antes de continuar."
            )
    else:
        form = FincaRegistroForm()

    # Listado de últimas fincas registradas para retroalimentación visual en la vista
    ultimas_fincas = Finca.objects.all().order_by("-creado_en")[:5]

    return render(
        request,
        "fincas/registro_finca.html",
        {"form": form, "ultimas_fincas": ultimas_fincas},
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def api_crear_finca_view(request):
    """
    Endpoint REST para registrar fincas con georreferenciación (SCRUM-96).
    POST /fincas/api/
    
    Persiste coordenadas decimales o almacena NULL si no fueron suministradas.
    """
    serializer = FincaGeorreferenciacionSerializer(data=request.data)
    if serializer.is_valid():
        productor = request.user if request.user.is_authenticated else None
        finca = serializer.save(productor=productor)
        return Response(
            FincaGeorreferenciacionSerializer(finca).data,
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
def api_detalle_finca_view(request, pk):
    """
    Endpoint REST para consultar o actualizar la georreferenciación de una finca.
    GET / PATCH /fincas/api/<pk>/
    """
    finca = get_object_or_404(Finca, pk=pk)

    if request.method == "GET":
        return Response(FincaGeorreferenciacionSerializer(finca).data)

    serializer = FincaGeorreferenciacionSerializer(finca, data=request.data, partial=True)
    if serializer.is_valid():
        finca_actualizada = serializer.save()
        return Response(FincaGeorreferenciacionSerializer(finca_actualizada).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
