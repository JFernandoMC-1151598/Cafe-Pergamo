"""
Vistas del módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
"""

import uuid

from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseNotAllowed, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .forms import FincaRegistroForm, FincaModelForm, MunicipioForm
from .models import Finca, Municipio
from .permissions import rol_puede_administrar_catalogos
from .serializers import FincaGeorreferenciacionSerializer, MunicipioSerializer
from .services import (
    crear_municipio,
    editar_municipio,
    inactivar_municipio,
    reactivar_municipio,
    toggle_estado_municipio,
)
from usuarios.models import Usuario
from usuarios.permissions import permiso_requerido_sesion


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


@api_view(["GET", "POST"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([AllowAny])
def api_municipios_coleccion_view(request):
    """
    Endpoint REST para listar y crear municipios del catálogo (SCRUM-112).
    - GET: Lista municipios. Filtros opcionales: ?q=... (búsqueda), ?departamento=..., ?activo=true/false.
    - POST: Crea un nuevo municipio. Requiere rol autorizado (ADMINISTRADOR o ASOCIACION).
    """
    if request.method == "GET":
        queryset = Municipio.objects.all().order_by("departamento", "nombre")

        q = request.query_params.get("q", "").strip()
        if q:
            queryset = queryset.filter(nombre__icontains=q)

        departamento = request.query_params.get("departamento", "").strip()
        if departamento:
            queryset = queryset.filter(departamento__icontains=departamento)

        activo_param = request.query_params.get("activo")
        if activo_param is not None:
            if activo_param.lower() in ("true", "1"):
                queryset = queryset.filter(activo=True)
            elif activo_param.lower() in ("false", "0"):
                queryset = queryset.filter(activo=False)

        serializer = MunicipioSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # POST: Crear municipio
    auth = JWTAuthentication()
    token = getattr(request, "auth", None)
    user_auth = None
    if token is None:
        try:
            res = auth.authenticate(request)
            if res is not None:
                user_auth, token = res
                request.user = user_auth
                request.auth = token
        except (InvalidToken, TokenError):
            pass

    # Determinar si el usuario está autenticado (vía JWT, sesión o superuser)
    usuario_autenticado = getattr(request.user, "is_authenticated", False) or (token is not None)
    if not usuario_autenticado:
        return Response(
            {"error": "Se requiere un token de autenticación válido."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Determinar código de rol
    role_code = ""
    if token and hasattr(token, "get"):
        role_code = token.get("role_code", "") or ""
    if not role_code and hasattr(request, "session"):
        role_code = request.session.get("rol", "")
    if not role_code and hasattr(request.user, "rol") and hasattr(request.user.rol, "codigo"):
        role_code = request.user.rol.codigo

    es_super = getattr(request.user, "is_superuser", False)

    if not es_super and (not role_code or not rol_puede_administrar_catalogos(role_code)):
        return Response(
            {"error": "No tiene permiso para acceder a este recurso."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = MunicipioSerializer(data=request.data)
    if serializer.is_valid():
        municipio = serializer.save()
        return Response(MunicipioSerializer(municipio).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "PATCH"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([AllowAny])
def api_municipio_detalle_view(request, pk):
    """
    Endpoint REST para consultar y editar municipios del catálogo (SCRUM-110).
    - GET: Obtiene la información detallada de un municipio (200 OK o 404 Not Found).
    - PUT / PATCH: Actualiza los campos de un municipio. Requiere rol autorizado (ADMINISTRADOR o ASOCIACION).
      Valida reglas de negocio (unicidad en departamento, campos no vacíos).
      Retorna 200 OK con los datos actualizados, 401 si no hay token, 403 si el rol no tiene permisos,
      404 si el municipio no existe o 400 Bad Request si los datos son inválidos.
    """
    try:
        municipio = Municipio.objects.get(pk=pk)
    except Municipio.DoesNotExist:
        return Response(
            {"error": "Municipio no encontrado."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        serializer = MunicipioSerializer(municipio)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # PUT / PATCH: Editar municipio
    auth = JWTAuthentication()
    token = getattr(request, "auth", None)
    if token is None:
        try:
            res = auth.authenticate(request)
            if res is not None:
                user_auth, token = res
                request.user = user_auth
                request.auth = token
        except (InvalidToken, TokenError):
            pass

    usuario_autenticado = getattr(request.user, "is_authenticated", False) or (token is not None)
    if not usuario_autenticado:
        return Response(
            {"error": "Se requiere un token de autenticación válido."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    role_code = ""
    if token and hasattr(token, "get"):
        role_code = token.get("role_code", "") or ""
    if not role_code and hasattr(request, "session"):
        role_code = request.session.get("rol", "")
    if not role_code and hasattr(request.user, "rol") and hasattr(request.user.rol, "codigo"):
        role_code = request.user.rol.codigo

    es_super = getattr(request.user, "is_superuser", False)

    if not es_super and (not role_code or not rol_puede_administrar_catalogos(role_code)):
        return Response(
            {"error": "No tiene permiso para acceder a este recurso."},
            status=status.HTTP_403_FORBIDDEN,
        )

    partial = (request.method == "PATCH")
    serializer = MunicipioSerializer(municipio, data=request.data, partial=partial)
    if serializer.is_valid():
        municipio_actualizado = serializer.save()
        return Response(MunicipioSerializer(municipio_actualizado).data, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([JWTAuthentication, SessionAuthentication])
@permission_classes([AllowAny])
def api_municipio_toggle_activo_view(request, pk):
    """
    Endpoint REST para inactivar o reactivar lógicamente un municipio (SCRUM-113 / HU09-ST4).
    POST /fincas/api/municipios/<pk>/toggle-activo/
    POST /fincas/api/municipios/<pk>/inactivar/

    Requiere rol autorizado (ADMINISTRADOR o ASOCIACION).
    Garantiza la preservación de fincas asociadas (integridad referencial histórica).
    """
    try:
        municipio = Municipio.objects.get(pk=pk)
    except Municipio.DoesNotExist:
        return Response(
            {"error": "Municipio no encontrado."},
            status=status.HTTP_404_NOT_FOUND,
        )

    auth = JWTAuthentication()
    token = getattr(request, "auth", None)
    if token is None:
        try:
            res = auth.authenticate(request)
            if res is not None:
                user_auth, token = res
                request.user = user_auth
                request.auth = token
        except (InvalidToken, TokenError):
            pass

    usuario_autenticado = getattr(request.user, "is_authenticated", False) or (token is not None)
    if not usuario_autenticado:
        return Response(
            {"error": "Se requiere un token de autenticación válido."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    role_code = ""
    if token and hasattr(token, "get"):
        role_code = token.get("role_code", "") or ""
    if not role_code and hasattr(request, "session"):
        role_code = request.session.get("rol", "")
    if not role_code and hasattr(request.user, "rol") and hasattr(request.user.rol, "codigo"):
        role_code = request.user.rol.codigo

    es_super = getattr(request.user, "is_superuser", False)

    if not es_super and (not role_code or not rol_puede_administrar_catalogos(role_code)):
        return Response(
            {"error": "No tiene permiso para acceder a este recurso."},
            status=status.HTTP_403_FORBIDDEN,
        )

    from .services import toggle_estado_municipio, inactivar_municipio, reactivar_municipio

    activo_deseado = request.data.get("activo") if hasattr(request, "data") and isinstance(request.data, dict) else None
    if activo_deseado is not None:
        if bool(activo_deseado):
            municipio_res, mensaje = reactivar_municipio(municipio)
        else:
            municipio_res, mensaje = inactivar_municipio(municipio)
    else:
        municipio_res, mensaje = toggle_estado_municipio(municipio)

    data = MunicipioSerializer(municipio_res).data
    data["mensaje"] = mensaje
    return Response(data, status=status.HTTP_200_OK)


# ==============================================================================
# Vistas Web de Administración del Catálogo de Municipios (HU-09 / SCRUM-111)
# ==============================================================================

@permiso_requerido_sesion(
    "catalogos_maestros.consultar",
    forbidden_on_denied=True,
)
def admin_municipios_view(request):
    """
    Pantalla web principal de administración del catálogo de municipios (SCRUM-111).
    - Permite consultar municipios con filtros combinados por búsqueda de texto, departamento y estado.
    - Presenta métricas clave del catálogo y fincas vinculadas.
    - Ofrece acciones para crear, editar e inactivar/activar territorios según permisos RBAC.
    """
    queryset = Municipio.objects.annotate(total_fincas=Count("fincas")).order_by("departamento", "nombre")

    q = request.GET.get("q", "").strip()
    if q:
        queryset = queryset.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))

    filtro_dep = request.GET.get("departamento", "").strip()
    if filtro_dep:
        queryset = queryset.filter(departamento__iexact=filtro_dep)

    filtro_estado = request.GET.get("estado", "").strip().lower()
    if filtro_estado in ("activos", "activas"):
        queryset = queryset.filter(activo=True)
    elif filtro_estado in ("inactivos", "inactivas"):
        queryset = queryset.filter(activo=False)
    else:
        filtro_estado = ""

    total_municipios = Municipio.objects.count()
    activos = Municipio.objects.filter(activo=True).count()
    inactivos = Municipio.objects.filter(activo=False).count()
    total_fincas = Finca.objects.filter(municipio__isnull=False).count()

    departamentos = (
        Municipio.objects.values_list("departamento", flat=True)
        .distinct()
        .order_by("departamento")
    )

    form_crear = MunicipioForm()

    return render(
        request,
        "fincas/admin_municipios.html",
        {
            "municipios": queryset,
            "total_municipios": total_municipios,
            "metricas": {
                "total": total_municipios,
                "activos": activos,
                "inactivos": inactivos,
                "total_fincas": total_fincas,
            },
            "departamentos": departamentos,
            "query_q": q,
            "filtro_dep": filtro_dep,
            "filtro_estado": filtro_estado,
            "form_crear": form_crear,
        },
    )


@permiso_requerido_sesion(
    "catalogos_maestros.administrar",
    forbidden_on_denied=True,
)
def crear_municipio_web_view(request):
    """
    Procesa la creación web de un nuevo municipio en el catálogo (SCRUM-111 / SCRUM-112).
    Aplica Service Layer con validación completa y feedback mediante messages.
    """
    if request.method == "POST":
        form = MunicipioForm(request.POST)
        if form.is_valid():
            nombre = form.cleaned_data["nombre"]
            departamento = form.cleaned_data["departamento"]
            codigo = form.cleaned_data.get("codigo")
            activo = form.cleaned_data.get("activo", True)

            try:
                municipio = crear_municipio(
                    nombre=nombre,
                    departamento=departamento,
                    codigo=codigo,
                    activo=activo,
                )
                messages.success(
                    request,
                    f"Municipio «{municipio.nombre}» registrado exitosamente con código {municipio.codigo}.",
                )
                return redirect("admin_municipios")
            except Exception as e:
                messages.error(request, f"Error al registrar el municipio: {e}")
        else:
            messages.error(request, "Por favor revise los errores señalados en el formulario.")
    else:
        form = MunicipioForm()

    return render(request, "fincas/crear_municipio.html", {"form": form})


@permiso_requerido_sesion(
    "catalogos_maestros.administrar",
    forbidden_on_denied=True,
)
def editar_municipio_web_view(request, pk):
    """
    Muestra y procesa el formulario de edición de un municipio existente (SCRUM-111 / SCRUM-110).
    """
    municipio = get_object_or_404(Municipio, pk=pk)

    if request.method == "POST":
        form = MunicipioForm(request.POST, instance=municipio)
        if form.is_valid():
            try:
                municipio_actualizado = editar_municipio(
                    municipio,
                    nombre=form.cleaned_data["nombre"],
                    departamento=form.cleaned_data["departamento"],
                    codigo=form.cleaned_data.get("codigo"),
                    activo=form.cleaned_data.get("activo"),
                )
                messages.success(
                    request,
                    f"Municipio «{municipio_actualizado.nombre}» actualizado exitosamente.",
                )
                return redirect("admin_municipios")
            except Exception as e:
                messages.error(request, f"Error al actualizar el municipio: {e}")
        else:
            messages.error(request, "Por favor revise los errores señalados en el formulario.")
    else:
        form = MunicipioForm(instance=municipio)

    total_fincas = municipio.total_fincas_asociadas

    return render(
        request,
        "fincas/editar_municipio.html",
        {
            "form": form,
            "municipio": municipio,
            "total_fincas": total_fincas,
        },
    )


@permiso_requerido_sesion(
    "catalogos_maestros.administrar",
    forbidden_on_denied=True,
)
def alternar_estado_municipio_web_view(request, pk):
    """
    Activa o inactiva lógicamente un municipio desde la interfaz web (SCRUM-111 / SCRUM-113).
    Preserva intacta la integridad referencial con fincas asociadas.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    municipio = get_object_or_404(Municipio, pk=pk)
    municipio_res, mensaje = toggle_estado_municipio(municipio)

    messages.success(request, mensaje)
    return redirect("admin_municipios")

