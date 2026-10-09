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
