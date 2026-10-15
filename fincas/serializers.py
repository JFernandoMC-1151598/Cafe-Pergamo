"""
Serializadores DRF para Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-96: Guardar georreferenciación en backend.
"""

from rest_framework import serializers
from .models import Finca, Municipio
from .validators import validar_latitud, validar_longitud, validar_par_coordenadas


class MunicipioRelatedField(serializers.RelatedField):
    """
    Campo que permite asociar un municipio por su nombre o ID,
    y lo serializa como su nombre (RF07).
    """

    def to_representation(self, value):
        return value.nombre if value else ""

    def to_internal_value(self, data):
        if isinstance(data, Municipio):
            return data
        if isinstance(data, int) or (isinstance(data, str) and data.isdigit()):
            try:
                return Municipio.objects.get(pk=int(data))
            except Municipio.DoesNotExist:
                raise serializers.ValidationError("Municipio no encontrado.")
        if isinstance(data, str):
            nombre = data.strip()
            if not nombre:
                raise serializers.ValidationError("El municipio no puede estar vacío.")
            mun, _ = Municipio.objects.get_or_create(
                nombre__iexact=nombre,
                defaults={
                    "nombre": nombre,
                    "codigo": nombre.upper()[:20],
                    "departamento": "Norte de Santander",
                },
            )
            return mun
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

        nombre = (attrs.get("nombre") or "").strip()
        departamento = (attrs.get("departamento") or "Norte de Santander").strip()

        if not nombre:
            raise serializers.ValidationError({"nombre": "El nombre del municipio no puede estar vacío."})
        if not departamento:
            raise serializers.ValidationError({"departamento": "El departamento no puede estar vacío."})

        # Bloqueo de duplicados en el mismo departamento (case-insensitive)
        queryset = Municipio.objects.filter(
            departamento__iexact=departamento,
            nombre__iexact=nombre,
        )
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError({
                "nombre": f"Ya existe un municipio con el nombre '{nombre}' en el departamento '{departamento}'."
            })

        attrs["nombre"] = nombre
        attrs["departamento"] = departamento
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
