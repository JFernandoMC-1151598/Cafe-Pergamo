"""
Modelos para el dominio de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1: Definir modelo de datos para fincas y relación con productor y municipio.
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.
Subtarea: SCRUM-97: Validar formato de coordenadas.

Cubre:
- RF06: registrar fincas asociadas a cada productor (perfil usuarios.Usuario).
- RF07: almacenar el municipio de cada finca referenciando el catálogo administrable Municipio.
- RF08 / HU07: campos opcionales de georreferenciación (latitud y longitud WGS84) con validación cartográfica.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from usuarios.models import Usuario
from .validators import validar_latitud, validar_longitud, validar_par_coordenadas


class Municipio(models.Model):
    """
    Catálogo administrable de municipios donde pueden ubicarse las fincas
    (RF07; RNF20 -- catálogos administrables sin tocar código fuente).
    """

    id = models.SmallAutoField(primary_key=True)
    codigo = models.CharField(
        max_length=20,
        unique=True,
        help_text="Código corto o DANE del municipio (p. ej. 'PAMPLONA').",
    )
    nombre = models.CharField(max_length=100)
    departamento = models.CharField(max_length=100, default="Norte de Santander")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "municipios"
        verbose_name = "Municipio"
        verbose_name_plural = "Municipios"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.departamento})"


class Finca(models.Model):
    """Predio o finca cafetera: entidad raíz de la trazabilidad (RF06, RF07, RF08)."""

    nombre = models.CharField(
        max_length=150,
        verbose_name="Nombre de la finca",
        help_text="Nombre distintivo del predio cafetero.",
    )

    productor = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        db_constraint=False,
        related_name="fincas",
        verbose_name="Productor",
        help_text="Perfil de negocio (usuarios.Usuario) dueño/responsable de la finca (RF06).",
    )

    municipio = models.ForeignKey(
        Municipio,
        on_delete=models.PROTECT,
        related_name="fincas",
        verbose_name="Municipio",
        help_text="Municipio del catálogo donde está ubicada la finca (RF07).",
    )

    vereda = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        verbose_name="Vereda / Sector",
        help_text="Vereda o sector opcional de ubicación predial.",
    )

    # ------------------------------------------------------------------
    # Georreferenciación opcional (RF08 / HU07 / SCRUM-98 / SCRUM-97)
    # ------------------------------------------------------------------
    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-90.000000")),
            MaxValueValidator(Decimal("90.000000")),
            validar_latitud,
        ],
        verbose_name="Latitud geográfica",
        help_text="Coordenada decimal de latitud [-90, 90]. Campo opcional (RF08).",
    )

    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-180.000000")),
            MaxValueValidator(Decimal("180.000000")),
            validar_longitud,
        ],
        verbose_name="Longitud geográfica",
        help_text="Coordenada decimal de longitud [-180, 180]. Campo opcional (RF08).",
    )

    activo = models.BooleanField(default=True, verbose_name="Finca activa")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = True
        db_table = "fincas"
        verbose_name = "Finca"
        verbose_name_plural = "Fincas"
        ordering = ["-creado_en"]

    def __str__(self):
        municipio_str = self.municipio.nombre if self.municipio else "Sin municipio"
        coords = f" [{self.latitud}, {self.longitud}]" if self.tiene_georreferenciacion else " [Sin GPS]"
        return f"{self.nombre} ({municipio_str}){coords}"

    @property
    def tiene_georreferenciacion(self) -> bool:
        """Indica si la finca tiene ambas coordenadas satelitales registradas."""
        return self.latitud is not None and self.longitud is not None

    def clean(self):
        """Valida la consistencia cartográfica a nivel de modelo (SCRUM-97)."""
        super().clean()
        validar_par_coordenadas(self.latitud, self.longitud)
