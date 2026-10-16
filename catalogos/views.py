"""Vistas del catálogo maestro de variedades de café (HU10)."""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from usuarios.permissions import permiso_requerido_sesion

from .forms import VariedadCafeForm
from .models import EstadoLote, ProcesoBeneficio, VariedadCafe
from .api_permissions import CatalogosTrazabilidadPermission
from .serializers import EstadoLoteSerializer, ProcesoBeneficioSerializer


@api_view(["GET", "POST"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([CatalogosTrazabilidadPermission])
def api_procesos_beneficio_view(request: HttpRequest) -> Response:
    """Lista o crea procesos de beneficio."""
    if request.method == "GET":
        queryset = ProcesoBeneficio.objects.all()
        activo = request.query_params.get("activo")
        if activo in {"true", "1"}:
            queryset = queryset.filter(activo=True)
        elif activo in {"false", "0"}:
            queryset = queryset.filter(activo=False)
        return Response(ProcesoBeneficioSerializer(queryset, many=True).data)

    serializer = ProcesoBeneficioSerializer(data=request.data)
    if serializer.is_valid():
        return Response(
            ProcesoBeneficioSerializer(serializer.save()).data,
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "PATCH"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([CatalogosTrazabilidadPermission])
def api_proceso_beneficio_detalle_view(
    request: HttpRequest,
    pk: int,
) -> Response:
    """Consulta o actualiza un proceso de beneficio."""
    proceso = get_object_or_404(ProcesoBeneficio, pk=pk)
    if request.method == "GET":
        return Response(ProcesoBeneficioSerializer(proceso).data)

    serializer = ProcesoBeneficioSerializer(
        proceso,
        data=request.data,
        partial=request.method == "PATCH",
    )
    if serializer.is_valid():
        return Response(ProcesoBeneficioSerializer(serializer.save()).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([CatalogosTrazabilidadPermission])
def api_proceso_beneficio_toggle_view(request: HttpRequest, pk: int) -> Response:
    """Activa o inactiva un proceso sin eliminarlo."""
    proceso = get_object_or_404(ProcesoBeneficio, pk=pk)
    proceso.activo = not proceso.activo
    proceso.save(update_fields=["activo", "actualizado_en"])
    return Response(ProcesoBeneficioSerializer(proceso).data)


@api_view(["GET", "POST"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([CatalogosTrazabilidadPermission])
def api_estados_lote_view(request: HttpRequest) -> Response:
    """Lista o crea estados del lote."""
    if request.method == "GET":
        queryset = EstadoLote.objects.all()
        activo = request.query_params.get("activo")
        if activo in {"true", "1"}:
            queryset = queryset.filter(activo=True)
        elif activo in {"false", "0"}:
            queryset = queryset.filter(activo=False)
        return Response(EstadoLoteSerializer(queryset, many=True).data)

    serializer = EstadoLoteSerializer(data=request.data)
    if serializer.is_valid():
        return Response(
            EstadoLoteSerializer(serializer.save()).data,
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "PATCH"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([CatalogosTrazabilidadPermission])
def api_estado_lote_detalle_view(request: HttpRequest, pk: int) -> Response:
    """Consulta o actualiza un estado del lote."""
    estado = get_object_or_404(EstadoLote, pk=pk)
    if request.method == "GET":
        return Response(EstadoLoteSerializer(estado).data)

    serializer = EstadoLoteSerializer(
        estado,
        data=request.data,
        partial=request.method == "PATCH",
    )
    if serializer.is_valid():
        return Response(EstadoLoteSerializer(serializer.save()).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([CatalogosTrazabilidadPermission])
def api_estado_lote_toggle_view(request: HttpRequest, pk: int) -> Response:
    """Activa o inactiva un estado sin eliminarlo."""
    estado = get_object_or_404(EstadoLote, pk=pk)
    estado.activo = not estado.activo
    estado.save(update_fields=["activo", "actualizado_en"])
    return Response(EstadoLoteSerializer(estado).data)


@permiso_requerido_sesion(
    "catalogos_maestros.consultar",
    forbidden_on_denied=True,
)
def administrar_trazabilidad_view(request: HttpRequest) -> HttpResponse:
    """Muestra los catálogos de procesos y estados en pestañas independientes."""
    pestaña = request.GET.get("pestana", "procesos").strip().lower()
    if pestaña not in {"procesos", "estados"}:
        pestaña = "procesos"

    estado = request.GET.get("estado", "").strip().lower()
    filtros_estado = {
        "activos": True,
        "inactivos": False,
    }

    procesos = ProcesoBeneficio.objects.all()
    estados = EstadoLote.objects.all()
    if estado in filtros_estado:
        if pestaña == "procesos":
            procesos = procesos.filter(activo=filtros_estado[estado])
        else:
            estados = estados.filter(activo=filtros_estado[estado])
    else:
        estado = ""

    return render(
        request,
        "catalogos/administrar_trazabilidad.html",
        {
            "procesos": procesos,
            "estados_lote": estados,
            "pestana_activa": pestaña,
            "estado_filtro": estado,
            "metricas": {
                "procesos_total": ProcesoBeneficio.objects.count(),
                "procesos_activos": ProcesoBeneficio.objects.filter(
                    activo=True
                ).count(),
                "estados_total": EstadoLote.objects.count(),
                "estados_activos": EstadoLote.objects.filter(
                    activo=True
                ).count(),
            },
        },
    )


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


@permiso_requerido_sesion(
    "catalogos_maestros.administrar",
    forbidden_on_denied=True,
)
def crear_variedad_view(request: HttpRequest) -> HttpResponse:
    """Muestra y procesa el formulario de creación de variedades."""
    if request.method == "POST":
        form = VariedadCafeForm(request.POST)
        if form.is_valid():
            variedad = form.save()
            messages.success(
                request,
                f"La variedad «{variedad.nombre}» fue registrada exitosamente.",
            )
            return redirect("lista_variedades")

        messages.error(
            request,
            "Por favor revise los errores señalados en el formulario.",
        )
    else:
        form = VariedadCafeForm()

    return render(request, "catalogos/crear_variedad.html", {"form": form})


@permiso_requerido_sesion(
    "catalogos_maestros.administrar",
    forbidden_on_denied=True,
)
def editar_variedad_view(
    request: HttpRequest,
    variedad_id: int,
) -> HttpResponse:
    """Muestra y procesa la edición de una variedad existente."""
    variedad = get_object_or_404(VariedadCafe, pk=variedad_id)

    if request.method == "POST":
        form = VariedadCafeForm(request.POST, instance=variedad)
        if form.is_valid():
            variedad = form.save()
            messages.success(
                request,
                f"La variedad «{variedad.nombre}» fue actualizada exitosamente.",
            )
            return redirect("lista_variedades")

        messages.error(
            request,
            "Por favor revise los errores señalados en el formulario.",
        )
    else:
        form = VariedadCafeForm(instance=variedad)

    return render(
        request,
        "catalogos/crear_variedad.html",
        {
            "form": form,
            "modo_edicion": True,
            "variedad": variedad,
        },
    )


@permiso_requerido_sesion(
    "catalogos_maestros.administrar",
    forbidden_on_denied=True,
)
def alternar_estado_variedad_view(
    request: HttpRequest,
    variedad_id: int,
) -> HttpResponse:
    """Activa o inactiva una variedad sin eliminarla físicamente."""
    if request.method != "POST":
        return HttpResponse("Método no permitido.", status=405)

    variedad = get_object_or_404(VariedadCafe, pk=variedad_id)
    variedad.activo = not variedad.activo
    variedad.save(update_fields=["activo", "actualizado_en"])

    estado = "activada" if variedad.activo else "inactivada"
    messages.success(
        request,
        f"La variedad «{variedad.nombre}» fue {estado} correctamente.",
    )
    return redirect("lista_variedades")
