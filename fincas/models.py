"""
Modelos para el dominio de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.

Criterios de Aceptación Cumplidos:
- Campos `latitud` y `longitud` tipo DecimalField opcionales (null=True, blank=True) en el modelo Finca.
- Rango de validación geográfica: Latitud [-90, 90] y Longitud [-180, 180].
- Soporte para precisión de hasta 6 decimales estándar en geolocalización satelital (WGS84).
- Nulabilidad explícita para garantizar persistencia sin coordenadas cuando el campo no es informado.
"""

from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Finca(models.Model):
    """
    Modelo representativo de un predio o finca cafetera.
    
    Permite registrar la información predial básica y georreferenciación satelital
    opcional para garantizar la trazabilidad de origen de cosechas y lotes.
    """

    nombre = models.CharField(
        max_length=150,
        verbose_name="Nombre de la finca",
        help_text="Nombre distintivo del predio cafetero.",
    )

    productor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fincas",
        null=True,
        blank=True,
        verbose_name="Productor asignado",
        help_text="Usuario propietario o responsable de la finca.",
    )

    municipio = models.CharField(
        max_length=100,
        verbose_name="Municipio",
        help_text="Municipio donde está ubicada la finca (Norte de Santander).",
    )

    vereda = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        verbose_name="Vereda / Sector",
        help_text="Vereda o sector opcional de ubicación predial.",
    )

    # =========================================================================
    # CAMPOS DE GEORREFERENCIACIÓN (HU-07 / SCRUM-98 / HU07-ST5)
    # =========================================================================
    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-90.000000")),
            MaxValueValidator(Decimal("90.000000")),
        ],
        verbose_name="Latitud geográfica",
        help_text="Coordenada decimal de latitud [-90.000000, 90.000000]. Campo opcional.",
    )

    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-180.000000")),
            MaxValueValidator(Decimal("180.000000")),
        ],
        verbose_name="Longitud geográfica",
        help_text="Coordenada decimal de longitud [-180.000000, 180.000000]. Campo opcional.",
    )

    activo = models.BooleanField(
        default=True,
        verbose_name="Finca activa",
        help_text="Indica si la finca se encuentra operativa en el sistema.",
    )

    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro",
    )

    actualizado_en = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    class Meta:
        db_table = "fincas"
        verbose_name = "Finca"
        verbose_name_plural = "Fincas"
        ordering = ["-creado_en"]

    def __str__(self):
        coords = f" [{self.latitud}, {self.longitud}]" if self.tiene_georreferenciacion else " [Sin GPS]"
        return f"{self.nombre} ({self.municipio}){coords}"

    @property
    def tiene_georreferenciacion(self) -> bool:
        """Indica si la finca tiene ambas coordenadas satelitales registradas."""
        return self.latitud is not None and self.longitud is not None
