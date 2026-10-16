"""Vistas del catálogo maestro de variedades de café (HU10)."""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from usuarios.permissions import permiso_requerido_sesion

from .forms import VariedadCafeForm
from .models import EstadoLote, ProcesoBeneficio, VariedadCafe


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
