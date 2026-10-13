"""Modelos de catálogos maestros (HU10)."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class VariedadCafe(models.Model):
    """Variedad de café disponible para asociarse a fincas y cosechas."""

    class Especie(models.TextChoices):
        ARABICA = "ARABICA", "Arábica"
        ROBUSTA = "ROBUSTA", "Robusta"

    nombre = models.CharField(
        max_length=100,
        verbose_name="Nombre de la variedad",
    )
    especie = models.CharField(
        max_length=20,
        choices=Especie.choices,
        verbose_name="Especie",
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Variedad activa",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "variedades_cafe"
        ordering = ["nombre"]
        verbose_name = "Variedad de café"
        verbose_name_plural = "Variedades de café"
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                name="variedad_cafe_nombre_ci_unico",
            ),
        ]

    def clean(self):
        """Valida y normaliza las reglas básicas del catálogo."""
        super().clean()
        self.nombre = self.nombre.strip() if self.nombre else ""
        self.descripcion = self.descripcion.strip() if self.descripcion else ""

        errores = {}
        if not self.nombre:
            errores["nombre"] = "El nombre de la variedad es obligatorio."
        if self.especie not in self.Especie.values:
            errores["especie"] = "Seleccione una especie válida."

        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"{self.nombre} ({self.get_especie_display()})"
