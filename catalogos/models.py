"""Modelos de catálogos maestros (HU10)."""

from django.core.exceptions import FieldDoesNotExist, ValidationError
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
        if self.esta_inactivando and self.tiene_lotes_activos:
            errores["activo"] = (
                "No se puede inactivar este registro porque está vinculado "
                "a lotes activos."
            )

        if errores:
            raise ValidationError(errores)

    @property
    def esta_inactivando(self):
        """Indica si la operación actual cambia el registro a inactivo."""
        if not self.pk or self.activo:
            return False

        estado_actual = type(self).objects.filter(pk=self.pk).values(
            "activo"
        ).first()
        return bool(estado_actual and estado_actual["activo"])

    @property
    def tiene_lotes_activos(self):
        """Indica si un modelo de lotes relacionado conserva registros activos."""
        if not self.pk:
            return False

        for relation in self._meta.related_objects:
            related_model = relation.related_model
            model_name = related_model._meta.model_name.lower()
            table_name = related_model._meta.db_table.lower()
            if "lote" not in model_name and "lote" not in table_name:
                continue

            try:
                activo_field = related_model._meta.get_field("activo")
            except FieldDoesNotExist:
                continue
            manager = getattr(self, relation.get_accessor_name(), None)
            if manager is not None and manager.filter(
                **{f"{activo_field.name}": True}
            ).exists():
                return True

        return False

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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


class BitacoraCatalogoTrazabilidad(models.Model):
    """Historial inmutable de operaciones sobre los catálogos de trazabilidad."""

    catalogo = models.CharField(max_length=50)
    registro_id = models.PositiveBigIntegerField()
    registro_codigo = models.CharField(max_length=30)
    registro_nombre = models.CharField(max_length=100)
    accion = models.CharField(max_length=20)
    valores_anteriores = models.JSONField(default=dict)
    valores_nuevos = models.JSONField(default=dict)
    realizado_por_id = models.CharField(max_length=100, null=True, blank=True)
    realizado_por_correo = models.EmailField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalogos_bitacora_trazabilidad"
        ordering = ["-creado_en"]
        verbose_name = "Entrada de bitácora de catálogo"
        verbose_name_plural = "Bitácora de catálogos"

    def __str__(self):
        return f"{self.catalogo} {self.accion} {self.registro_codigo}"
