"""
Modelos para el dominio de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1: Definir modelo de datos para fincas y relación con productor y municipio.
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.
Subtarea: SCRUM-97: Validar formato de coordenadas.
Subtarea: SCRUM-141 / HU13-ST1: Definir modelo de datos y relación Cosecha-Lote.

Cubre:
- RF06: registrar fincas asociadas a cada productor (perfil usuarios.Usuario).
- RF07: almacenar el municipio de cada finca referenciando el catálogo administrable Municipio.
- RF08 / HU07: campos opcionales de georreferenciación (latitud y longitud WGS84) con validación cartográfica.
- HU-13: lotes de café trazables individualmente, creados a partir de una cosecha existente.

Nota sobre `Cosecha` (HU13-ST1): en todo el repositorio (main y cada rama
de los demás integrantes) no existe todavia una historia de usuario que
modele "Cosecha" -- sin embargo la matriz de permisos de usuarios/tests.py
ya anticipa los codigos "cosechas.crear"/"cosechas.consultar", y HU13
("Crear lotes de café") depende explicitamente de que un Lote se cree "a
partir de una cosecha existente" y no supere su "saldo disponible". Por
eso este archivo agrega un modelo Cosecha MINIMO (finca, variedad, fecha,
cantidad total y saldo disponible) -- lo estrictamente indispensable para
que Lote pueda relacionarse y validar cantidades. No reemplaza una futura
historia de usuario completa de Cosechas (pantallas propias, reglas de
negocio adicionales, etc.), que queda pendiente en el backlog del equipo.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from catalogos.models import VariedadCafe
from usuarios.models import Usuario
from .validators import validar_latitud, validar_longitud, validar_par_coordenadas


class Municipio(models.Model):
    """
    Catálogo administrable de municipios donde pueden ubicarse las fincas.
    (RF07; RNF20 -- catálogos administrables sin tocar código fuente).
    Subtarea: SCRUM-114 / HU09-ST5: Diseñar el modelo de datos del catálogo de municipios.
    Subtarea: SCRUM-115 / HU09-ST6: Agregar validaciones y reglas de negocio del catálogo.
    """

    id = models.SmallAutoField(primary_key=True)
    codigo = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        verbose_name="Código DANE / Identificador",
        help_text="Código corto o DANE del municipio (p. ej. 'PAMPLONA').",
    )
    nombre = models.CharField(
        max_length=100,
        verbose_name="Nombre del municipio",
        help_text="Nombre oficial del municipio.",
    )
    departamento = models.CharField(
        max_length=100,
        default="Norte de Santander",
        verbose_name="Departamento / Región",
        help_text="Departamento o región a la que pertenece el municipio.",
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Estado activo",
        help_text="Indica si el municipio está activo en el catálogo (inactivación lógica).",
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
        managed = True
        db_table = "municipios"
        verbose_name = "Municipio"
        verbose_name_plural = "Municipios"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["departamento", "nombre"],
                name="municipios_departamento_nombre_unico",
            )
        ]

    def __str__(self):
        estado = "Activo" if self.activo else "Inactivo"
        return f"{self.nombre} ({self.departamento}) - {estado}"

    @property
    def tiene_fincas_asociadas(self) -> bool:
        """Indica si el municipio tiene fincas asociadas en el sistema."""
        return self.fincas.exists()

    @property
    def total_fincas_asociadas(self) -> int:
        """Cantidad de fincas asociadas a este municipio."""
        return self.fincas.count()

    def clean(self):
        """
        Validaciones y reglas de negocio del catálogo de municipios (SCRUM-115).
        - Obligatoriedad y saneamiento de nombre y departamento.
        - Bloqueo de nombres de municipios duplicados en el mismo departamento (case-insensitive).
        """
        super().clean()
        if self.nombre:
            self.nombre = self.nombre.strip()
            if len(self.nombre) < 2:
                raise ValidationError({"nombre": "El nombre del municipio debe tener al menos 2 caracteres."})
        else:
            raise ValidationError({"nombre": "El nombre del municipio es obligatorio."})

        if self.departamento:
            self.departamento = self.departamento.strip()
            if len(self.departamento) < 2:
                raise ValidationError({"departamento": "El departamento o región debe tener al menos 2 caracteres."})
        else:
            raise ValidationError({"departamento": "El departamento es obligatorio."})

        # Bloqueo de nombres de municipios duplicados en el mismo departamento (case-insensitive)
        duplicado = Municipio.objects.filter(
            departamento__iexact=self.departamento,
            nombre__iexact=self.nombre,
        )
        if self.pk:
            duplicado = duplicado.exclude(pk=self.pk)

        if duplicado.exists():
            raise ValidationError({
                "nombre": f"Ya existe un municipio con el nombre '{self.nombre}' en el departamento '{self.departamento}'."
            })

    def save(self, *args, **kwargs):
        """Asegura código único por defecto si no es provisto explícitamente y ejecuta validaciones."""
        if not self.codigo and self.nombre:
            base_code = self.nombre.strip().upper().replace(" ", "_")[:20]
            self.codigo = base_code
        self.clean()
        super().save(*args, **kwargs)




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


class Cosecha(models.Model):
    """
    Cosecha de café de una finca (modelo mínimo -- ver nota en el
    docstring del módulo). Guarda cuánto se cosechó en total
    (`cantidad_total`) y cuánto queda todavía sin asignar a ningún lote
    (`cantidad_disponible`), que es lo que HU13-ST2 necesita para poder
    rechazar un lote que exceda el saldo.
    """

    finca = models.ForeignKey(
        Finca,
        on_delete=models.PROTECT,
        related_name="cosechas",
        verbose_name="Finca",
        help_text="Finca de la que proviene la cosecha.",
    )

    variedad = models.ForeignKey(
        VariedadCafe,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cosechas",
        verbose_name="Variedad de café",
        help_text="Variedad cosechada, del catálogo de HU10 (opcional).",
    )

    fecha_cosecha = models.DateField(
        verbose_name="Fecha de la cosecha",
        help_text="Fecha en que se realizó la cosecha.",
    )

    cantidad_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Cantidad total cosechada (kg)",
        help_text="Cantidad total cosechada, en kilogramos.",
    )

    cantidad_disponible = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Cantidad disponible (kg)",
        help_text="Saldo sin asignar a ningún lote todavía. Se descuenta automáticamente al crear lotes (HU13-ST2).",
    )

    activo = models.BooleanField(default=True, verbose_name="Cosecha activa")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = True
        db_table = "cosechas"
        verbose_name = "Cosecha"
        verbose_name_plural = "Cosechas"
        ordering = ["-fecha_cosecha", "-creado_en"]
        constraints = [
            models.CheckConstraint(
                # Django 6.0 renombró `check` a `condition` en CheckConstraint
                # (este proyecto corre Django 6.1.1): con `check=` directamente
                # lanza `TypeError: unexpected keyword argument 'check'`.
                condition=models.Q(cantidad_disponible__lte=models.F("cantidad_total")),
                name="cosecha_disponible_no_supera_total",
            ),
        ]

    def __str__(self):
        return (
            f"Cosecha {self.finca.nombre} ({self.fecha_cosecha}) "
            f"- {self.cantidad_disponible}/{self.cantidad_total} kg disponibles"
        )

    def save(self, *args, **kwargs):
        """Al crear la cosecha, si no se indicó `cantidad_disponible`, arranca igual a `cantidad_total`."""
        if self._state.adding and self.cantidad_disponible is None:
            self.cantidad_disponible = self.cantidad_total
        super().save(*args, **kwargs)


class Lote(models.Model):
    """
    Lote de café creado a partir de una cosecha existente (HU-13 /
    SCRUM-141 / SCRUM-142), para trazabilidad individual de porciones de
    una misma cosecha.
    """

    codigo = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Código del lote",
        help_text="Código único alfanumérico del lote (criterio de aceptación HU13).",
    )

    cosecha = models.ForeignKey(
        Cosecha,
        on_delete=models.PROTECT,
        related_name="lotes",
        verbose_name="Cosecha de origen",
        help_text="Cosecha existente a partir de la cual se crea el lote.",
    )

    cantidad = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Cantidad del lote (kg)",
        help_text="Cantidad asignada a este lote; no puede superar el saldo disponible de la cosecha.",
    )

    activo = models.BooleanField(default=True, verbose_name="Lote activo")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")

    class Meta:
        managed = True
        db_table = "lotes"
        verbose_name = "Lote"
        verbose_name_plural = "Lotes"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"Lote {self.codigo} ({self.cantidad} kg) de {self.cosecha}"
