"""
Vistas del módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
"""

import uuid

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .forms import FincaRegistroForm, FincaModelForm
from .models import Finca, Municipio
from .serializers import FincaGeorreferenciacionSerializer
from usuarios.models import Usuario


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
            municipio_val = form.cleaned_data["municipio"]
            if isinstance(municipio_val, Municipio):
                municipio_obj = municipio_val
            else:
                municipio_nombre = str(municipio_val).strip()
                municipio_obj, _ = Municipio.objects.get_or_create(
                    nombre__iexact=municipio_nombre,
                    defaults={
                        "nombre": municipio_nombre,
                        "codigo": municipio_nombre.upper()[:20],
                        "departamento": "Norte de Santander",
                    },
                )

            vereda = form.cleaned_data.get("vereda")
            vereda = vereda.strip() if vereda else ""
            latitud = form.cleaned_data.get("latitud")
            longitud = form.cleaned_data.get("longitud")

            if request.user.is_authenticated and isinstance(request.user, Usuario):
                productor_id = request.user.id
            elif request.user.is_authenticated and hasattr(request.user, "pk"):
                productor_id = getattr(request.user, "id", None) or uuid.uuid4()
            else:
                productor_id = uuid.uuid4()

            # Persistencia en base de datos (SCRUM-96)
            finca = Finca.objects.create(
                nombre=nombre,
                municipio=municipio_obj,
                vereda=vereda,
                latitud=latitud,      # Decimal o None (NULL en BD)
                longitud=longitud,    # Decimal o None (NULL en BD)
                productor_id=productor_id,
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
        if request.user.is_authenticated and isinstance(request.user, Usuario):
            productor_id = request.user.id
        elif request.user.is_authenticated and hasattr(request.user, "pk"):
            productor_id = getattr(request.user, "id", None) or uuid.uuid4()
        else:
            productor_id = uuid.uuid4()

        finca = serializer.save(productor_id=productor_id)
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
