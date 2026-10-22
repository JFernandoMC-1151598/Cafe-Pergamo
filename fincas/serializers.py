"""
Serializadores DRF para Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
Subtarea: SCRUM-142 / HU13-ST2: Implementar servicio/API para registrar lotes.
"""

from decimal import Decimal
from rest_framework import serializers
from .models import Cosecha, Finca, Lote, Municipio
from .validators import validar_latitud, validar_longitud, validar_par_coordenadas


class MunicipioRelatedField(serializers.RelatedField):
    """
    Campo que permite asociar un municipio por su nombre o ID,
    y lo serializa como su nombre (RF07).
    """

    def to_representation(self, value):
        return value.nombre if value else ""

    def to_internal_value(self, data):
        """
        Resuelve el municipio por id o por nombre exacto (sin distinguir
        mayúsculas/acentos de caja), siempre contra el catálogo YA
        existente. Antes, un nombre que no calzaba con ningún municipio
        se "arreglaba" creando uno nuevo con `get_or_create` -- eso hacía
        imposible rechazar un municipio inválido, que es justo el
        criterio de aceptación de SCRUM-89 (HU06-ST4).
        """
        if isinstance(data, Municipio):
            if not data.activo:
                raise serializers.ValidationError("El municipio seleccionado se encuentra inactivo y no admite nuevos registros de fincas.")
            return data
        if isinstance(data, int) or (isinstance(data, str) and data.isdigit()):
            try:
                mun = Municipio.objects.get(pk=int(data))
                if not mun.activo:
                    raise serializers.ValidationError("El municipio seleccionado se encuentra inactivo y no admite nuevos registros de fincas.")
                return mun
            except Municipio.DoesNotExist:
                raise serializers.ValidationError("Municipio no encontrado.")
        if isinstance(data, str):
            nombre = data.strip()
            if not nombre:
                raise serializers.ValidationError("El municipio no puede estar vacío.")
            mun = Municipio.objects.filter(nombre__iexact=nombre).first()
            if mun:
                if not mun.activo:
                    raise serializers.ValidationError(f"El municipio '{mun.nombre}' se encuentra inactivo y no admite nuevos registros de fincas.")
                return mun
            raise serializers.ValidationError(
                "El municipio seleccionado no es válido. Debe elegirlo del catálogo existente."
            )
        raise serializers.ValidationError("Formato de municipio inválido.")


class FincaGeorreferenciacionSerializer(serializers.ModelSerializer):
    """
    Serializador para la creación y actualización de fincas con georreferenciación.
    Persiste coordenadas decimales o almacena NULL si no fueron suministradas.
    """

    municipio = MunicipioRelatedField(queryset=Municipio.objects.all(), required=True)


    latitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
        validators=[validar_latitud],
    )

    longitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
        validators=[validar_longitud],
    )

    tiene_georreferenciacion = serializers.BooleanField(read_only=True)

    class Meta:
        model = Finca
        fields = [
            "id",
            "nombre",
            "municipio",
            "vereda",
            "latitud",
            "longitud",
            "tiene_georreferenciacion",
            "activo",
            "creado_en",
        ]
        read_only_fields = ["id", "tiene_georreferenciacion", "creado_en"]

    def validate(self, attrs):
        lat = attrs.get("latitud")
        lng = attrs.get("longitud")
        validar_par_coordenadas(lat, lng)
        return attrs


class MunicipioSerializer(serializers.ModelSerializer):
    """
    Serializador DRF para el catálogo de municipios (SCRUM-112).
    Permite serializar, validar y crear municipios con reglas de negocio.
    """

    codigo = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
    )
    nombre = serializers.CharField(max_length=100, required=True)
    departamento = serializers.CharField(
        max_length=100,
        required=False,
        default="Norte de Santander",
    )
    activo = serializers.BooleanField(required=False, default=True)
    total_fincas_asociadas = serializers.IntegerField(read_only=True)
    tiene_fincas_asociadas = serializers.BooleanField(read_only=True)

    class Meta:
        model = Municipio
        fields = [
            "id",
            "codigo",
            "nombre",
            "departamento",
            "activo",
            "total_fincas_asociadas",
            "tiene_fincas_asociadas",
            "creado_en",
            "actualizado_en",
        ]
        read_only_fields = [
            "id",
            "creado_en",
            "actualizado_en",
            "total_fincas_asociadas",
            "tiene_fincas_asociadas",
        ]

    def validate(self, attrs):
        from django.core.exceptions import ValidationError as DjangoValidationError

        nombre = attrs.get("nombre")
        departamento = attrs.get("departamento")

        if self.instance:
            if nombre is None:
                nombre = self.instance.nombre
            if departamento is None:
                departamento = self.instance.departamento
        else:
            if departamento is None:
                departamento = "Norte de Santander"

        nombre_limpio = (nombre or "").strip()
        dep_limpio = (departamento or "").strip()

        if not self.instance or "nombre" in attrs:
            if not nombre_limpio:
                raise serializers.ValidationError({"nombre": "El nombre del municipio no puede estar vacío."})

        if not self.instance or "departamento" in attrs:
            if not dep_limpio:
                raise serializers.ValidationError({"departamento": "El departamento no puede estar vacío."})

        # Bloqueo de duplicados en el mismo departamento (case-insensitive)
        queryset = Municipio.objects.filter(
            departamento__iexact=dep_limpio,
            nombre__iexact=nombre_limpio,
        )
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError({
                "nombre": f"Ya existe un municipio con el nombre '{nombre_limpio}' en el departamento '{dep_limpio}'."
            })

        if "nombre" in attrs:
            attrs["nombre"] = nombre_limpio
        if "departamento" in attrs:
            attrs["departamento"] = dep_limpio
        return attrs

    def create(self, validated_data):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from .services import crear_municipio

        try:
            return crear_municipio(**validated_data)
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages)

    def update(self, instance, validated_data):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from .services import editar_municipio

        try:
            return editar_municipio(instance, **validated_data)
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages)


class LoteSerializer(serializers.ModelSerializer):
    """
    Serializador de solo lectura para representar un Lote en las
    respuestas de la API (HU13-ST2 / SCRUM-142). La creación real pasa
    por `fincas.services.crear_lote`, que es quien aplica las reglas de
    negocio (código único, cantidad vs. saldo disponible, descuento
    transaccional) -- este serializador solo da forma a la salida.
    """

    cosecha_id = serializers.IntegerField(source="cosecha.id", read_only=True)
    finca = serializers.CharField(source="cosecha.finca.nombre", read_only=True)
    cantidad_disponible_cosecha = serializers.DecimalField(
        source="cosecha.cantidad_disponible", max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Lote
        fields = [
            "id",
            "codigo",
            "cosecha_id",
            "finca",
            "cantidad",
            "cantidad_disponible_cosecha",
            "activo",
            "proceso_beneficio",
            "estado_lote",
            "creado_en",
        ]
        read_only_fields = fields


class CosechaSerializer(serializers.ModelSerializer):
    """
    Serializador para representar una Cosecha en las respuestas de la API (HU-12 / SCRUM-137).
    """

    finca_id = serializers.IntegerField(source="finca.id", read_only=True)
    finca_nombre = serializers.CharField(source="finca.nombre", read_only=True)
    variedad_id = serializers.IntegerField(source="variedad.id", read_only=True, allow_null=True)
    variedad_nombre = serializers.CharField(source="variedad.nombre", read_only=True, allow_null=True)

    class Meta:
        model = Cosecha
        fields = [
            "id",
            "finca_id",
            "finca_nombre",
            "variedad_id",
            "variedad_nombre",
            "fecha_cosecha",
            "cantidad_total",
            "cantidad_disponible",
            "activo",
            "creado_en",
            "actualizado_en",
        ]
        read_only_fields = fields


class CosechaCreateSerializer(serializers.Serializer):
    """
    Serializador de entrada para el registro de cosechas vía API (HU-12 / SCRUM-137).
    """

    finca = serializers.IntegerField(required=True)
    variedad = serializers.IntegerField(required=False, allow_null=True)
    fecha_cosecha = serializers.DateField(required=True)
    cantidad_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=True
    )


# =============================================================================
# SERIALIZADORES PARA FICHA DIGITAL CONSOLIDADA POR LOTE (HU-17 / SCRUM-169)
# =============================================================================

class FichaDigitalProductorSerializer(serializers.Serializer):
    """Estructura serializada del productor de la finca en la ficha digital."""
    id = serializers.CharField(allow_null=True, required=False)
    nombre_completo = serializers.CharField()
    correo = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    telefono = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    tipo_documento = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    numero_documento = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class FichaDigitalFincaSerializer(serializers.Serializer):
    """Estructura serializada de la finca y georreferenciación en la ficha digital."""
    id = serializers.IntegerField()
    nombre = serializers.CharField()
    vereda = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    municipio = serializers.CharField()
    departamento = serializers.CharField()
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True, required=False)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6, allow_null=True, required=False)
    tiene_georreferenciacion = serializers.BooleanField()


class FichaDigitalCosechaSerializer(serializers.Serializer):
    """Estructura serializada del origen agronómico y cosecha."""
    id = serializers.IntegerField()
    fecha_cosecha = serializers.DateField()
    cantidad_total_cosecha = serializers.DecimalField(max_digits=10, decimal_places=2)
    cantidad_disponible_cosecha = serializers.DecimalField(max_digits=10, decimal_places=2)


class FichaDigitalVariedadSerializer(serializers.Serializer):
    """Estructura serializada de la variedad botánica de café."""
    id = serializers.IntegerField(allow_null=True, required=False)
    nombre = serializers.CharField(allow_null=True, required=False)
    especie = serializers.CharField(allow_null=True, required=False)
    descripcion = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class FichaDigitalProcesoSerializer(serializers.Serializer):
    """Estructura serializada del proceso de beneficio del café."""
    id = serializers.IntegerField(allow_null=True, required=False)
    codigo = serializers.CharField(allow_null=True, required=False)
    nombre = serializers.CharField(allow_null=True, required=False)
    descripcion = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class FichaDigitalEstadoSerializer(serializers.Serializer):
    """Estructura serializada del estado de trazabilidad del lote."""
    id = serializers.IntegerField(allow_null=True, required=False)
    codigo = serializers.CharField(allow_null=True, required=False)
    nombre = serializers.CharField(allow_null=True, required=False)
    descripcion = serializers.CharField(allow_null=True, required=False, allow_blank=True)


class FichaDigitalSerializer(serializers.Serializer):
    """
    Estructura consolidada de la Ficha Digital por Lote (HU-17 / SCRUM-169).
    Define el contrato formal de datos para la visualización pública, consumo vía API
    y enlace con el generador de Códigos QR (HU-18).
    """
    # Identificación del Lote
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    cantidad_kg = serializers.DecimalField(max_digits=10, decimal_places=2)
    activo = serializers.BooleanField()
    creado_en = serializers.DateTimeField()

    # Módulos relacionales consolidados
    productor = FichaDigitalProductorSerializer()
    finca = FichaDigitalFincaSerializer()
    cosecha = FichaDigitalCosechaSerializer()
    variedad = FichaDigitalVariedadSerializer()
    proceso_beneficio = FichaDigitalProcesoSerializer()
    estado_lote = FichaDigitalEstadoSerializer()

    # Secciones modulares y extensibles para HU-14 (Beneficio) y HU-15 (Calidad)
    etapas_beneficio = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    calidad = serializers.DictField(allow_null=True, required=False, default=None)
    estado_comercial = serializers.CharField(default="DISPONIBLE", required=False)
    disponible_para_venta = serializers.BooleanField(default=True, required=False)

    # Metadatos de navegación y trazabilidad
    url_publica = serializers.CharField(required=False)
    completitud_porcentaje = serializers.IntegerField(required=False, default=50)
