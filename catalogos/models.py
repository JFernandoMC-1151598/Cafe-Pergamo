"""Modelos de catálogos maestros (HU10)."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class VariedadCafe(models.Model):
    """Variedad de café disponible para asociarse a fincas y cosechas."""

    class Especie(models.TextChoices):
        ARABICA = "ARABICA", "Arábica"
        ROBUSTA = "ROBUSTA", "Robusta"
        LIBERICA = "LIBERICA", "Libérica"
        EXCELSA = "EXCELSA", "Excelsa"

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


class CatalogoTrazabilidadBase(models.Model):
    """Campos compartidos por los catálogos configurables de trazabilidad."""

    codigo = models.CharField(
        max_length=30,
        verbose_name="Código",
    )
    nombre = models.CharField(
        max_length=100,
        verbose_name="Nombre",
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Registro activo",
    )
    orden = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden de visualización",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["orden", "nombre"]

    def clean(self):
        super().clean()
        self.codigo = self.codigo.strip().upper() if self.codigo else ""
        self.nombre = self.nombre.strip() if self.nombre else ""
        self.descripcion = self.descripcion.strip() if self.descripcion else ""

        errores = {}
        if not self.codigo:
            errores["codigo"] = "El código es obligatorio."
        if not self.nombre:
            errores["nombre"] = "El nombre es obligatorio."

        if errores:
            raise ValidationError(errores)


class ProcesoBeneficio(CatalogoTrazabilidadBase):
    """Proceso de beneficio aplicable a un lote de café."""

    class Meta(CatalogoTrazabilidadBase.Meta):
        db_table = "procesos_beneficio"
        verbose_name = "Proceso de beneficio"
        verbose_name_plural = "Procesos de beneficio"
        constraints = [
            models.UniqueConstraint(
                Lower("codigo"),
                name="proceso_beneficio_codigo_ci_unico",
            ),
            models.UniqueConstraint(
                Lower("nombre"),
                name="proceso_beneficio_nombre_ci_unico",
            ),
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class EstadoLote(CatalogoTrazabilidadBase):
    """Estado configurable dentro del ciclo de vida de un lote."""

    class Meta(CatalogoTrazabilidadBase.Meta):
        db_table = "estados_lote"
        verbose_name = "Estado de lote"
        verbose_name_plural = "Estados de lote"
        constraints = [
            models.UniqueConstraint(
                Lower("codigo"),
                name="estado_lote_codigo_ci_unico",
            ),
            models.UniqueConstraint(
                Lower("nombre"),
                name="estado_lote_nombre_ci_unico",
            ),
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"
