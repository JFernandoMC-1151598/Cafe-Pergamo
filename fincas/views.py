"""
Vistas del módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
Subtarea: SCRUM-91 / HU06-ST3: Crear formulario de registro de finca(s) en la interfaz.
Subtarea: SCRUM-89 / HU06-ST4: Validar campos obligatorios y consistencia de datos del registro.
Subtarea: SCRUM-90 / HU06-ST5: Implementar servicio/API para registrar fincas.
Subtarea: SCRUM-92 / HU06-ST6: Listar fincas registradas por productor.
"""

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .forms import FincaRegistroForm
from .models import Finca
from .serializers import FincaGeorreferenciacionSerializer
from usuarios.models import Usuario


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
