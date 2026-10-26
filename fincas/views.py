"""
Vistas del módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
Subtarea: SCRUM-91 / HU06-ST3: Crear formulario de registro de finca(s) en la interfaz.
Subtarea: SCRUM-89 / HU06-ST4: Validar campos obligatorios y consistencia de datos del registro.
Subtarea: SCRUM-90 / HU06-ST5: Implementar servicio/API para registrar fincas.
Subtarea: SCRUM-92 / HU06-ST6: Listar fincas registradas por productor.
Subtarea: SCRUM-142 / HU13-ST2: Implementar servicio/API para registrar lotes.
Subtarea: SCRUM-144 / HU13: Crear formulario o pantalla de registro de lotes.
Subtarea: SCRUM-145 / HU013-ST4: Validar cantidad disponible antes de crear el lote
(aplicada en services.crear_lote(), usada tanto por la vista web como por la API).
Subtarea: SCRUM-146 / HU013-ST5: Actualizar trazabilidad de la cosecha al crear lotes
(idem, el descuento del saldo vive en services.crear_lote()).
Nota: incluye también una vista de registro de cosechas, complemento necesario para
poder usar el formulario de lotes de principio a fin (ver nota en fincas/forms.py).
Nota: incluye además una vista de listado "Mis Lotes" con filtro por finca -- pedida
directamente por el productor al revisar HU-13 en local: HU-14 (etapas de beneficio)
mostrará el historial de beneficio más adelante, pero un lote ya registrado debía
poder consultarse ahora, no solo en el siguiente sprint.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseNotAllowed, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .forms import CosechaRegistroForm, FincaRegistroForm, FincaModelForm, LoteRegistroForm, MunicipioForm
from .models import BitacoraFichaDigital, Cosecha, Finca, Lote, Municipio
from .permissions import rol_puede_administrar_catalogos
from .serializers import (
    CosechaCreateSerializer,
    CosechaSerializer,
    FichaDigitalSerializer,
    FincaGeorreferenciacionSerializer,
    LoteSerializer,
    MunicipioSerializer,
)
from .services import (
    crear_cosecha,
    crear_lote,
    crear_municipio,
    editar_municipio,
    inactivar_municipio,
    obtener_ficha_consolidada_lote,
    reactivar_municipio,
    registrar_auditoria_ficha_digital,
    toggle_estado_municipio,
)
from usuarios.models import Usuario
from usuarios.permissions import permiso_requerido_sesion


def _resolver_productor_id(request):
    """
    Resuelve el id real (UUID) del perfil de negocio (usuarios.Usuario) de
    quien hace la petición, sin importar si llegó autenticado por sesión
    de Django (flujo web normal -- ver usuarios/views.py:492, el mismo
    patrón que usuarios/permissions.py) o por JWT (API -- ver
    usuarios/serializers.py: CustomTokenObtainPairSerializer, que incluye
    el claim 'email' en el token).

    Nunca inventa un UUID al azar: si no puede identificar a nadie,
    devuelve None para que la vista decida qué hacer. Antes, el código de
    esta vista hacía `isinstance(request.user, Usuario)` -- una condición
    que nunca es verdadera, porque `request.user` siempre es la fila
    "espejo" de `auth_user`, no el perfil de negocio -- y cuando eso
    fallaba, caía a `uuid.uuid4()`: un productor inventado que la
    restricción FK real `fincas_productor_id_fkey` en Supabase rechaza.
    """
    usuario_id = request.session.get("usuario_id")
    if usuario_id:
        return str(usuario_id)

    token = getattr(request, "auth", None)
    correo = None
    if token is not None:
        try:
            correo = token.get("email")
        except AttributeError:
            correo = None

    if correo:
        usuario = Usuario.objects.filter(correo=correo).first()
        if usuario:
            return str(usuario.id)

    return None


def registrar_finca_view(request):
    """
    Vista web para captura y persistencia de fincas (SCRUM-96 / HU06-ST3).

    Criterios de Aceptación (DoD):
    - La vista persiste las coordenadas en BD o almacena NULL si no se ingresaron.
    - El municipio se selecciona del catálogo (HU06-ST3); si no hay uno
      válido seleccionado, el formulario lo rechaza (HU06-ST4 / SCRUM-89).
    - La finca se asocia al productor realmente autenticado en sesión --
      nunca a un UUID inventado.
    """
    if request.method == "POST":
        form = FincaRegistroForm(request.POST)
        if form.is_valid():
            productor_id = _resolver_productor_id(request)
            if not productor_id:
                messages.error(
                    request,
                    "Debe iniciar sesión con su cuenta de productor para registrar una finca."
                )
                return redirect(f"{reverse('login')}?next={request.path}")

            nombre = form.cleaned_data["nombre"].strip()
            municipio_obj = form.cleaned_data["municipio"]
            vereda = form.cleaned_data.get("vereda")
            vereda = vereda.strip() if vereda else ""
            latitud = form.cleaned_data.get("latitud")
            longitud = form.cleaned_data.get("longitud")

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
def api_crear_finca_view(request):
    """
    Endpoint REST para registrar fincas con georreferenciación
    (SCRUM-96 / SCRUM-90 / HU06-ST5).
    POST /fincas/api/

    Criterio de Aceptación de HU06-ST5: "Controlador POST que asigna
    automáticamente request.user y guarda la finca" -- por eso el
    productor NUNCA se toma de un campo del body que el cliente podría
    falsificar: `_resolver_productor_id(request)` lo deduce del usuario
    realmente autenticado (sesión o JWT) y se lo pasa a `serializer.save()`
    como `productor_id`, igual que `registrar_finca_view` hace para la
    versión web del mismo flujo.

    Hereda la autenticación/autorización por defecto del proyecto
    (JWTAuthentication + IsAuthenticated, ver settings.REST_FRAMEWORK) en
    vez del `@permission_classes([AllowAny])` original: antes cualquiera,
    sin identificarse, podía registrar fincas -- y el productor se
    resolvía con un UUID aleatorio que la restricción FK real de Supabase
    (`fincas_productor_id_fkey`) habría rechazado en producción.
    """
    serializer = FincaGeorreferenciacionSerializer(data=request.data)
    if serializer.is_valid():
        productor_id = _resolver_productor_id(request)
        if not productor_id:
            return Response(
                {"error": "No se pudo identificar al productor autenticado."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        finca = serializer.save(productor_id=productor_id)
        return Response(
            FincaGeorreferenciacionSerializer(finca).data,
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
def api_detalle_finca_view(request, pk):
    """
    Endpoint REST para consultar o actualizar la georreferenciación de una finca.
    GET / PATCH /fincas/api/<pk>/

    Igual que `api_crear_finca_view`, ya no es `AllowAny`: requiere un
    JWT válido (autenticación por defecto del proyecto).
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


def mis_fincas_view(request):
    """
    Vista web "Mis Fincas" (SCRUM-92 / HU06-ST6).

    Criterio de Aceptación (DoD): "Implementar la consulta o vista que
    permita visualizar las fincas ya asociadas a cada productor."

    Punto clave de seguridad (también cubre el criterio de "aislamiento
    entre usuarios" de SCRUM-93 / HU06-ST7): el listado SIEMPRE se filtra
    por el productor realmente autenticado (`_resolver_productor_id`), que
    es el mismo helper que ya usan `registrar_finca_view` y
    `api_crear_finca_view`. Nunca se expone aquí el catálogo completo de
    fincas de todos los productores -- cada quien ve únicamente las suyas.
    """
    productor_id = _resolver_productor_id(request)
    if not productor_id:
        messages.error(
            request,
            "Debe iniciar sesión con su cuenta de productor para ver sus fincas."
        )
        return redirect(f"{reverse('login')}?next={request.path}")

    fincas = (
        Finca.objects.filter(productor_id=productor_id, activo=True)
        .select_related("municipio")
        .order_by("-creado_en")
    )

    # Subconjunto georreferenciado, serializado para el mapa (fincas sin
    # coordenadas simplemente no se pintan como marcador, pero sí aparecen
    # en el listado de tarjetas de la plantilla).
    fincas_geo = [
        {
            "nombre": finca.nombre,
            "municipio": finca.municipio.nombre,
            "vereda": finca.vereda or "",
            "lat": finca.latitud,
            "lng": finca.longitud,
        }
        for finca in fincas
        if finca.tiene_georreferenciacion
    ]

    return render(
        request,
        "fincas/mis_fincas.html",
        {"fincas": fincas, "fincas_geo": fincas_geo},
    )


@api_view(["POST"])
def api_crear_cosecha_view(request):
    """
    Endpoint REST para registrar cosechas de café (HU-12 / SCRUM-137).
    POST /fincas/api/cosechas/
    Body: {
        "finca": <id>,
        "variedad": <id opcional>,
        "fecha_cosecha": "YYYY-MM-DD",
        "cantidad_total": <decimal>
    }

    Criterios de aceptación aplicados:
    1. La finca y la variedad deben ser válidas (SCRUM-140):
       - Identifica al productor autenticado (_resolver_productor_id).
       - Verifica que la finca pertenezca a su cuenta (aislamiento).
       - Valida existencia y estado activo de finca y variedad.
    2. Las cantidades deben ser mayores a cero (cantidad_total > 0).
    3. Se inicializa cantidad_disponible = cantidad_total (vía crear_cosecha).
    """
    productor_id = _resolver_productor_id(request)
    if not productor_id:
        return Response(
            {"error": "No se pudo identificar al productor autenticado."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    serializer = CosechaCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    finca_id = serializer.validated_data["finca"]
    variedad_id = serializer.validated_data.get("variedad")
    fecha_cosecha = serializer.validated_data["fecha_cosecha"]
    cantidad_total = serializer.validated_data["cantidad_total"]

    try:
        finca = Finca.objects.get(pk=finca_id)
    except (Finca.DoesNotExist, ValueError, TypeError):
        return Response(
            {"finca": ["La finca indicada no existe."]},
            status=status.HTTP_404_NOT_FOUND,
        )

    if str(finca.productor_id) != str(productor_id):
        return Response(
            {"error": "La finca indicada no pertenece a su cuenta de productor."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        cosecha = crear_cosecha(
            finca_id=finca_id,
            fecha_cosecha=fecha_cosecha,
            cantidad_total=cantidad_total,
            variedad_id=variedad_id,
            productor_id=productor_id,
        )
    except ValidationError as exc:
        detalle = exc.message_dict if hasattr(exc, "message_dict") else {"error": exc.messages}
        return Response(detalle, status=status.HTTP_400_BAD_REQUEST)

    return Response(CosechaSerializer(cosecha).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def api_crear_lote_view(request):
    """
    Endpoint REST para registrar lotes de café a partir de una cosecha
    existente (HU13-ST2 / SCRUM-142).
    POST /fincas/api/lotes/
    Body: {"cosecha": <id>, "cantidad": <decimal>, "codigo": <str opcional>}

    Igual que `api_crear_finca_view`, el productor se resuelve del
    usuario realmente autenticado (`_resolver_productor_id`), nunca de un
    campo del body. Además se verifica que la cosecha indicada pertenezca
    a una finca de ESE productor (aislamiento entre usuarios, mismo
    criterio que ya se exige en HU06-ST6/ST7): nadie puede crear lotes a
    partir de la cosecha de otro productor.

    Toda la lógica de negocio (código único, cantidad vs. saldo
    disponible, descuento transaccional) vive en `services.crear_lote`;
    esta vista solo identifica al productor, autoriza y traduce el
    resultado a una respuesta HTTP.
    """
    productor_id = _resolver_productor_id(request)
    if not productor_id:
        return Response(
            {"error": "No se pudo identificar al productor autenticado."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    cosecha_id = request.data.get("cosecha") or request.data.get("cosecha_id")
    if not cosecha_id:
        return Response(
            {"cosecha": ["Este campo es obligatorio."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        cosecha = Cosecha.objects.select_related("finca").get(pk=cosecha_id)
    except (Cosecha.DoesNotExist, ValueError, TypeError):
        return Response(
            {"cosecha": ["La cosecha indicada no existe."]},
            status=status.HTTP_404_NOT_FOUND,
        )

    if str(cosecha.finca.productor_id) != str(productor_id):
        return Response(
            {"error": "La cosecha indicada no pertenece a su cuenta de productor."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        lote = crear_lote(
            cosecha_id=cosecha_id,
            cantidad=request.data.get("cantidad"),
            codigo=request.data.get("codigo"),
            proceso_beneficio_id=request.data.get("proceso_beneficio_id"),
            estado_lote_id=request.data.get("estado_lote_id"),
        )
    except ValidationError as exc:
        detalle = exc.message_dict if hasattr(exc, "message_dict") else {"error": exc.messages}
        return Response(detalle, status=status.HTTP_400_BAD_REQUEST)

    return Response(LoteSerializer(lote).data, status=status.HTTP_201_CREATED)


def registrar_cosecha_view(request):
    """
    Vista web de registro de cosechas (complemento de HU-13, ver nota en
    el docstring del módulo y en `fincas/forms.py`). El productor solo
    puede registrar cosechas de SUS PROPIAS fincas -- el queryset del
    formulario ya viene limitado por `productor_id`, y `clean_finca()`
    lo vuelve a verificar por si el POST fue manipulado.
    """
    productor_id = _resolver_productor_id(request)
    if not productor_id:
        messages.error(
            request,
            "Debe iniciar sesión con su cuenta de productor para registrar una cosecha."
        )
        return redirect(f"{reverse('login')}?next={request.path}")

    tiene_fincas = Finca.objects.filter(productor_id=productor_id, activo=True).exists()
    if not tiene_fincas:
        messages.warning(
            request,
            "Debe registrar al menos una finca antes de poder registrar una cosecha."
        )
        return redirect("mis_fincas")

    if request.method == "POST":
        form = CosechaRegistroForm(request.POST, productor_id=productor_id)
        if form.is_valid():
            cosecha = form.save()
            messages.success(
                request,
                f"Cosecha registrada exitosamente para la finca '{cosecha.finca.nombre}' "
                f"({cosecha.cantidad_total} kg)."
            )
            return redirect("cosecha_registro")
        else:
            messages.error(
                request,
                "Por favor revise los errores señalados en el formulario antes de continuar."
            )
    else:
        form = CosechaRegistroForm(productor_id=productor_id)

    ultimas_cosechas = (
        Cosecha.objects.filter(finca__productor_id=productor_id)
        .select_related("finca", "variedad")
        .order_by("-creado_en")[:5]
    )

    return render(
        request,
        "fincas/registro_cosecha.html",
        {"form": form, "ultimas_cosechas": ultimas_cosechas},
    )


def registrar_lote_view(request):
    """
    Vista web de registro de lotes (HU13-ST4 / SCRUM-144): formulario
    para que el productor seleccione una de sus cosechas con saldo
    disponible, ingrese el código del lote (opcional) y la cantidad.

    Toda la lógica de negocio (código único, cantidad vs. saldo
    disponible, descuento transaccional automático) vive en
    `services.crear_lote` -- la misma función que usa
    `api_crear_lote_view` -- así que el flujo web y el flujo API nunca
    pueden quedar desincronizados en las reglas que aplican.
    """
    productor_id = _resolver_productor_id(request)
    if not productor_id:
        messages.error(
            request,
            "Debe iniciar sesión con su cuenta de productor para registrar un lote."
        )
        return redirect(f"{reverse('login')}?next={request.path}")

    tiene_cosechas_con_saldo = Cosecha.objects.filter(
        finca__productor_id=productor_id, activo=True, cantidad_disponible__gt=0
    ).exists()
    if not tiene_cosechas_con_saldo:
        messages.warning(
            request,
            "Debe registrar una cosecha con saldo disponible antes de poder crear lotes."
        )
        return redirect("cosecha_registro")

    if request.method == "POST":
        form = LoteRegistroForm(request.POST, productor_id=productor_id)
        if form.is_valid():
            cosecha = form.cleaned_data["cosecha"]
            try:
                lote = crear_lote(
                    cosecha_id=cosecha.pk,
                    cantidad=form.cleaned_data["cantidad"],
                    codigo=form.cleaned_data.get("codigo") or None,
                    proceso_beneficio_id=form.cleaned_data[
                        "proceso_beneficio"
                    ].pk,
                    estado_lote_id=form.cleaned_data["estado_lote"].pk,
                )
            except ValidationError as exc:
                # Traduce los errores de negocio de crear_lote() (que no
                # conoce nada de formularios web) a errores de campo del
                # formulario, para que se muestren igual que cualquier
                # otro error de validación.
                errores = exc.message_dict if hasattr(exc, "message_dict") else {"__all__": exc.messages}
                for campo, lista_errores in errores.items():
                    destino = campo if campo in form.fields else None
                    for error in lista_errores:
                        form.add_error(destino, error)
                messages.error(
                    request,
                    "Por favor revise los errores señalados en el formulario antes de continuar."
                )
            else:
                messages.success(
                    request,
                    f"Lote '{lote.codigo}' registrado exitosamente ({lote.cantidad} kg)."
                )
                return redirect("lote_registro")
        else:
            messages.error(
                request,
                "Por favor revise los errores señalados en el formulario antes de continuar."
            )
    else:
        form = LoteRegistroForm(productor_id=productor_id)

    ultimos_lotes = (
        Lote.objects.filter(cosecha__finca__productor_id=productor_id)
        .select_related("cosecha", "cosecha__finca")
        .order_by("-creado_en")[:5]
    )

    return render(
        request,
        "fincas/registro_lote.html",
        {"form": form, "ultimos_lotes": ultimos_lotes},
    )


def mis_lotes_view(request):
    """
    Vista web de listado de lotes del productor autenticado, con filtro
    opcional por finca vía `?finca=<id>` (petición directa del usuario al
    revisar HU-13 en local: no hay todavía ninguna pantalla para consultar
    los lotes que ya se registraron, aunque las "etapas de beneficio" -- el
    historial de qué pasa después del lote -- quedaron para otro sprint).

    Aislamiento entre productores: el queryset base ya está filtrado por
    `cosecha__finca__productor_id=productor_id`, así que un `?finca=<id>`
    que apunte a la finca de OTRO productor nunca puede filtrar lotes
    ajenos -- el AND de ambos filtros simplemente no devuelve nada, sin
    necesidad de un chequeo de error aparte.
    """
    productor_id = _resolver_productor_id(request)
    if not productor_id:
        messages.error(
            request,
            "Debe iniciar sesión con su cuenta de productor para ver sus lotes."
        )
        return redirect(f"{reverse('login')}?next={request.path}")

    lotes = (
        Lote.objects.filter(cosecha__finca__productor_id=productor_id)
        .select_related("cosecha", "cosecha__finca")
        .order_by("-creado_en")
    )

    fincas_productor = Finca.objects.filter(
        productor_id=productor_id, activo=True
    ).order_by("nombre")

    finca_id_raw = request.GET.get("finca", "").strip()
    finca_seleccionada = None
    if finca_id_raw:
        try:
            finca_id = int(finca_id_raw)
        except (TypeError, ValueError):
            messages.warning(request, "El filtro de finca no es válido; se muestran todos los lotes.")
        else:
            lotes = lotes.filter(cosecha__finca_id=finca_id)
            finca_seleccionada = fincas_productor.filter(pk=finca_id).first()

    return render(
        request,
        "fincas/mis_lotes.html",
        {
            "lotes": lotes,
            "fincas": fincas_productor,
            "finca_seleccionada": finca_seleccionada,
            "finca_id_filtro": finca_id_raw,
        },
    )


# =============================================================================
# API REST FICHA DIGITAL CONSOLIDADA POR LOTE (HU-17 / SCRUM-167)
# =============================================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def api_consultar_ficha_digital_view(request, codigo=None):
    """
    Endpoint REST para consultar la ficha digital consolidada de un lote (HU-17 / SCRUM-167).
    GET /fincas/api/lotes/<str:codigo>/ficha/
    GET /fincas/api/v1/lotes/<str:codigo>/ficha/

    Permite consulta pública/semipública sin requerir token obligatorio,
    habilitando el escaneo directo vía Código QR (HU-18) o catálogo público (HU-19).
    """
    if not codigo or not str(codigo).strip():
        return Response(
            {"error": "Debe especificar un código o identificador de lote válido."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    codigo_limpio = str(codigo).strip()
    try:
        ficha_data = obtener_ficha_consolidada_lote(codigo_limpio)
    except ValidationError as exc:
        msg = (
            exc.message_dict.get("lote", ["Lote no encontrado"])[0]
            if hasattr(exc, "message_dict") and "lote" in exc.message_dict
            else str(exc)
        )
        return Response({"error": msg}, status=status.HTTP_404_NOT_FOUND)
    except Exception as exc:
        return Response(
            {"error": f"Error al procesar la ficha digital: {str(exc)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    serializer = FichaDigitalSerializer(data=ficha_data)
    if not serializer.is_valid():
        return Response(
            {
                "error": "Inconsistencia interna en los datos de la ficha consolidada.",
                "detalles": serializer.errors,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Registrar auditoría de consulta API / QR (HU-17 / ST7 - SCRUM-172)
    try:
        lote_obj = Lote.objects.filter(id=ficha_data["id"]).first()
        if lote_obj:
            registrar_auditoria_ficha_digital(
                lote=lote_obj,
                tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_API,
                request=request,
                completitud_porcentaje=ficha_data.get("completitud_porcentaje", 0),
                es_consistente=ficha_data.get("es_consistente", True),
                detalles={"canal": "api_rest", "ruta": request.path},
            )
    except Exception:
        pass

    return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# VISTA WEB FICHA DIGITAL CONSOLIDADA POR LOTE (HU-17 / SCRUM-168)
# =============================================================================

def ficha_digital_web_view(request, codigo=None):
    """
    Vista web pública / interactiva para visualizar la Ficha Digital Consolidada por Lote
    (HU-17 / SCRUM-168).
    Permite acceso abierto a cualquier interesado (con o sin sesión) que consulte
    mediante enlace directo, navegación de catálogo (HU-19) o escaneo de Código QR (HU-18).
    """
    if not codigo or not str(codigo).strip():
        return render(request, "fincas/ficha_digital_error.html", {"codigo": ""}, status=400)

    codigo_limpio = str(codigo).strip()
    try:
        ficha = obtener_ficha_consolidada_lote(codigo_limpio)
    except ValidationError:
        return render(request, "fincas/ficha_digital_error.html", {"codigo": codigo_limpio}, status=404)
    except Exception as exc:
        return render(
            request,
            "fincas/ficha_digital_error.html",
            {"codigo": codigo_limpio, "error_detalle": str(exc)},
            status=500,
        )

    # Registrar auditoría de consulta Web / QR (HU-17 / ST7 - SCRUM-172)
    try:
        lote_obj = Lote.objects.filter(id=ficha["id"]).first()
        if lote_obj:
            registrar_auditoria_ficha_digital(
                lote=lote_obj,
                tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_WEB,
                request=request,
                completitud_porcentaje=ficha.get("completitud_porcentaje", 0),
                es_consistente=ficha.get("es_consistente", True),
                detalles={"canal": "web", "ruta": request.path},
            )
    except Exception:
        pass

    return render(request, "fincas/ficha_digital.html", {"ficha": ficha})
