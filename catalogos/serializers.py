"""Serializadores REST para los catálogos de trazabilidad."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import EstadoLote, ProcesoBeneficio


class CatalogoTrazabilidadSerializer(serializers.ModelSerializer):
    """Valida y serializa procesos de beneficio y estados del lote."""

    class Meta:
        fields = (
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "activo",
            "orden",
            "creado_en",
            "actualizado_en",
        )
        read_only_fields = ("id", "creado_en", "actualizado_en")

    def validate(self, attrs):
        instance = self.instance
        codigo = attrs.get("codigo", instance.codigo if instance else "")
        nombre = attrs.get("nombre", instance.nombre if instance else "")
        codigo = codigo.strip().upper() if codigo else ""
        nombre = nombre.strip() if nombre else ""

        errores = {}
        if not codigo:
            errores["codigo"] = "El código es obligatorio."
        if not nombre:
            errores["nombre"] = "El nombre es obligatorio."

        queryset = self.Meta.model.objects.all()
        if instance:
            queryset = queryset.exclude(pk=instance.pk)
        if codigo and queryset.filter(codigo__iexact=codigo).exists():
            errores["codigo"] = "Ya existe un registro con ese código."
        if nombre and queryset.filter(nombre__iexact=nombre).exists():
            errores["nombre"] = "Ya existe un registro con ese nombre."

        if errores:
            raise serializers.ValidationError(errores)

        attrs["codigo"] = codigo
        attrs["nombre"] = nombre
        if "descripcion" in attrs:
            attrs["descripcion"] = (attrs["descripcion"] or "").strip()
        return attrs

    def create(self, validated_data):
        try:
            instance = self.Meta.model(**validated_data)
            instance.full_clean()
            instance.save()
            return instance
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        try:
            instance.full_clean()
            instance.save()
            return instance
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)


class ProcesoBeneficioSerializer(CatalogoTrazabilidadSerializer):
    class Meta(CatalogoTrazabilidadSerializer.Meta):
        model = ProcesoBeneficio


class EstadoLoteSerializer(CatalogoTrazabilidadSerializer):
    class Meta(CatalogoTrazabilidadSerializer.Meta):
        model = EstadoLote
