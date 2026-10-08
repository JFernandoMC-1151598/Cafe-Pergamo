"""
Modelos para el dominio de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1: Definir modelo de datos para fincas y
relación con productor y municipio.

La Finca es la Entidad Raíz del dominio (Modelo de Dominio, Capa 1):
"la unidad productiva y geográfica sobre la que ocurre todo el ciclo del
café: siembra, cosecha y beneficio; es el punto de partida de toda la
trazabilidad de un lote."

Cubre:
- RF06: registrar fincas asociadas a cada productor.
- RF07: almacenar el municipio de cada finca, referenciando un catálogo
  administrable de municipios (no texto libre).
- Deja preparado el terreno para RF08 (campos opcionales de
  georreferenciación -- latitud/longitud -- que trabaja HU07).

A diferencia de usuarios/models.py, estas tablas SÍ son gestionadas por
Django (Meta.managed = True): son nuevas para el proyecto y no existían
antes en Supabase, así que `python manage.py migrate` es quien las crea.

Nota sobre `productor`: referencia a `usuarios.Usuario` (el perfil de
negocio real, no el usuario interno de Django) para mantener coherencia
con el resto del sistema -- el dueño de una finca es el mismo perfil que
tiene un rol (PRODUCTOR/ASOCIACION) en el RBAC de HU04. Como `Usuario` es
`managed = False` (vive en Supabase, Django no la recrea en la base de
datos de pruebas), esta FK usa `db_constraint=False`: Django sigue
dando toda la semántica de relación en el ORM (`finca.productor`,
`usuario.fincas.all()`, joins, etc.) pero no intenta crear la restricción
de llave foránea a nivel de base de datos en la migración -- si no, la
migración fallaría en cualquier base de datos de pruebas donde
`usuarios` no exista. La restricción real a nivel de Postgres se agrega
aparte, directamente en Supabase, una sola vez. La validación de que el
usuario asignado efectivamente tenga rol PRODUCTOR/ASOCIACION es
responsabilidad de la capa de formulario/API (HU06-ST2 en adelante), no
de este modelo.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from usuarios.models import Usuario


class Municipio(models.Model):
    """
    Catálogo administrable de municipios donde pueden ubicarse las fincas
    (RF07; RNF20 -- catálogos administrables sin tocar código fuente).

    A diferencia de los catálogos de usuarios/models.py (Rol,
    TipoDocumento), que ya existían en el esquema de Supabase, este
    catálogo es nuevo para HU06 y Django sí gestiona su esquema aquí
    (Meta.managed = True).
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
    """Predio o finca cafetera: entidad raíz de la trazabilidad (RF06, RF07)."""

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
    # Georreferenciación opcional (RF08 / HU07) -- campos ya preparados
    # aquí para que HU07 no tenga que volver a tocar el modelo de Finca.
    # ------------------------------------------------------------------
    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("-90.000000")), MaxValueValidator(Decimal("90.000000"))],
        verbose_name="Latitud geográfica",
        help_text="Coordenada decimal de latitud [-90, 90]. Campo opcional (RF08).",
    )
    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("-180.000000")), MaxValueValidator(Decimal("180.000000"))],
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
        coords = f" [{self.latitud}, {self.longitud}]" if self.tiene_georreferenciacion else " [Sin GPS]"
        return f"{self.nombre} ({self.municipio.nombre}){coords}"

    @property
    def tiene_georreferenciacion(self) -> bool:
        """Indica si la finca tiene ambas coordenadas satelitales registradas."""
        return self.latitud is not None and self.longitud is not None
