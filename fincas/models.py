"""
Modelos para el dominio de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1: Definir modelo de datos para fincas y relación con productor y municipio.
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.
Subtarea: SCRUM-97: Validar formato de coordenadas.
Subtarea: SCRUM-141 / HU13-ST1: Definir modelo de datos y relación Cosecha-Lote.
Subtarea: SCRUM-157 / HU15-ST5: Diseñar el modelo de datos para características
físicas y de calidad del lote.
Subtarea: SCRUM-148 / HU14-ST1 y SCRUM-149 / HU14-ST2: modelo de etapas de
beneficio del lote (requerido por el formulario de captura y el historial).
Subtarea: SCRUM-152 / HU14-ST3 y SCRUM-150 / HU14-ST4: validaciones del modelo y
sin eliminación física de etapas (RNF-14).

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
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from catalogos.models import EstadoLote, ProcesoBeneficio, VariedadCafe
from usuarios.models import Usuario
from .validators import (
    OBSERVACIONES_ETAPA_MAX,
    validar_latitud,
    validar_longitud,
    validar_observaciones_etapa,
    validar_par_coordenadas,
)


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

    def clean(self):
        super().clean()
        if self.cantidad_total is not None and self.cantidad_total <= Decimal("0.00"):
            raise ValidationError({"cantidad_total": "La cantidad total cosechada debe ser mayor a cero."})
        if self.cantidad_disponible is not None and self.cantidad_total is not None:
            if self.cantidad_disponible > self.cantidad_total:
                raise ValidationError({"cantidad_disponible": "La cantidad disponible no puede superar la cantidad total cosechada."})
            if self.cantidad_disponible < Decimal("0.00"):
                raise ValidationError({"cantidad_disponible": "La cantidad disponible no puede ser negativa."})
        if hasattr(self, "finca") and self.finca_id:
            if not self.finca.activo:
                raise ValidationError({"finca": "No se pueden registrar cosechas para una finca inactiva."})
        if hasattr(self, "variedad") and self.variedad_id:
            if not self.variedad.activo:
                raise ValidationError({"variedad": "La variedad de café seleccionada se encuentra inactiva en el catálogo."})

    def save(self, *args, **kwargs):
        """
        Al crear la cosecha, si no se indicó `cantidad_disponible`,
        se inicializa igual a `cantidad_total` (criterio de aceptación HU-12).
        """
        if self.cantidad_disponible is None and self.cantidad_total is not None:
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

    proceso_beneficio = models.ForeignKey(
        ProcesoBeneficio,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lotes",
        verbose_name="Proceso de beneficio",
    )

    estado_lote = models.ForeignKey(
        EstadoLote,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lotes",
        verbose_name="Estado del lote",
    )

    class EstadoComercial(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        RESERVADO = "RESERVADO", "Reservado"
        NEGOCIADO = "NEGOCIADO", "Negociado"
        VENDIDO = "VENDIDO", "Vendido"
        CERRADO = "CERRADO", "Cerrado"

    estado_comercial = models.CharField(
        max_length=20,
        choices=EstadoComercial.choices,
        default=EstadoComercial.DISPONIBLE,
        verbose_name="Estado comercial",
        help_text="Estado actual del lote dentro del proceso de comercialización.",
    )
    estado_comercial_actualizado_en = models.DateTimeField(
        default=timezone.now,
        verbose_name="Última actualización del estado comercial",
    )

    cantidad = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Cantidad del lote (kg)",
        help_text="Cantidad asignada a este lote; no puede superar el saldo disponible de la cosecha.",
    )

    publicado_en_catalogo = models.BooleanField(
        default=False,
        verbose_name="Publicado en catálogo comercial",
        help_text="Indica si el lote se encuentra visible y disponible para compradores en el catálogo público (HU-19 / SCRUM-243).",
    )
    fecha_publicacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de publicación en catálogo",
    )
    precio_referencial = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Precio referencial por kg (COP)",
        help_text="Precio orientativo por kilogramo para compradores en el catálogo comercial.",
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
        estado_cat = " [Publicado]" if self.publicado_en_catalogo else ""
        return f"Lote {self.codigo} ({self.cantidad} kg){estado_cat} de {self.cosecha}"

    def save(self, *args, **kwargs):
        """
        Ciclo de guardado de Lote con generación y sincronización automática del
        código QR asociado (HU18-ST1 / SCRUM-174).
        """
        sincronizar_qr = kwargs.pop("sincronizar_qr", True)
        es_creacion = self.pk is None
        codigo_previo = None
        if not es_creacion and self.pk:
            codigo_previo = (
                Lote.objects.filter(pk=self.pk).values_list("codigo", flat=True).first()
            )

        super().save(*args, **kwargs)

        if sincronizar_qr and not getattr(self, "_skip_auto_qr", False):
            from .services import sincronizar_o_generar_qr_lote
            try:
                hubo_cambio_codigo = bool(codigo_previo and codigo_previo != self.codigo)
                sincronizar_o_generar_qr_lote(self, forzar_regeneracion=hubo_cambio_codigo)
            except Exception:
                pass

    @property
    def tiene_codigo_qr(self) -> bool:
        """Indica si el lote tiene un registro de código QR asociado (HU-18 / SCRUM-176)."""
        return hasattr(self, "codigo_qr") and self.codigo_qr is not None

    @property
    def identificador_qr(self) -> Optional[str]:
        """Retorna el identificador QR persistido o None."""
        try:
            return self.codigo_qr.identificador
        except (ObjectDoesNotExist, AttributeError):
            return None



class HistorialEstadoLote(models.Model):
    """Auditoría de cambios del estado comercial de un lote (HU16-ST3)."""

    lote = models.ForeignKey(
        Lote,
        on_delete=models.CASCADE,
        related_name="historial_estados_comerciales",
        verbose_name="Lote",
    )
    estado_anterior = models.CharField(
        max_length=20,
        choices=Lote.EstadoComercial.choices,
        verbose_name="Estado comercial anterior",
    )
    estado_nuevo = models.CharField(
        max_length=20,
        choices=Lote.EstadoComercial.choices,
        verbose_name="Estado comercial nuevo",
    )
    usuario_responsable_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="ID del usuario responsable",
    )
    usuario_responsable_correo = models.EmailField(
        null=True,
        blank=True,
        verbose_name="Correo del usuario responsable",
    )
    motivo = models.TextField(
        blank=True,
        default="",
        verbose_name="Motivo del cambio",
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha del cambio",
    )

    class Meta:
        managed = True
        db_table = "fincas_historial_estado_lote"
        ordering = ["-creado_en", "-id"]
        indexes = [
            models.Index(
                fields=["lote", "-creado_en"],
                name="idx_hist_estado_lote_fecha",
            ),
        ]

    def __str__(self):
        return (
            f"{self.lote.codigo}: {self.estado_anterior} -> "
            f"{self.estado_nuevo} ({self.creado_en})"
        )


class CaracteristicasCalidad(models.Model):
    """
    Características físicas y sensoriales asociadas a un lote (HU15-ST5).

    Un lote puede tener como máximo un registro de calidad. Los campos
    numéricos son opcionales para permitir que la captura se complete por
    etapas; sus rangos básicos se aplican desde el modelo.
    """

    lote = models.OneToOneField(
        Lote,
        on_delete=models.CASCADE,
        related_name="caracteristicas_calidad",
        verbose_name="Lote",
        help_text="Lote al que pertenece esta evaluación de calidad.",
    )

    humedad = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        verbose_name="Humedad (%)",
        help_text="Porcentaje de humedad del café.",
    )

    merma = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        verbose_name="Merma (%)",
        help_text="Porcentaje de merma identificado en el lote.",
    )

    puntaje_taza = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
        verbose_name="Puntaje en taza",
        help_text="Puntaje sensorial de taza en una escala de 0 a 100.",
    )

    perfil_sensorial = models.TextField(
        blank=True,
        verbose_name="Perfil sensorial",
        help_text="Descripción de las notas y atributos sensoriales del lote.",
    )

    observaciones = models.TextField(
        blank=True,
        verbose_name="Observaciones",
        help_text="Observaciones adicionales de la evaluación de calidad.",
    )

    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = True
        db_table = "caracteristicas_calidad"
        verbose_name = "Característica de calidad"
        verbose_name_plural = "Características de calidad"
        ordering = ["-actualizado_en"]

    def __str__(self):
        return f"Calidad del lote {self.lote.codigo}"


class EtapaBeneficioQuerySet(models.QuerySet):
    """
    Sin eliminación física (RNF-14): `delete()` solo marca las etapas como
    inactivas. `hard_delete()` existe únicamente para herramientas de
    desarrollo (p. ej. el comando de datos de demostración).
    """

    def delete(self):
        return self.update(activo=False)

    delete.alters_data = True
    delete.queryset_only = True

    def hard_delete(self):
        return super().delete()

    hard_delete.alters_data = True

    def vigentes(self):
        return self.filter(activo=True)


class EtapaBeneficio(models.Model):
    """
    Etapa del proceso de beneficio registrada sobre un lote (HU-14 / RF13).

    La etapa se elige de una lista fija (`TipoEtapa`), nunca como texto
    libre (criterio de aceptación de HU14-ST1). No se confunde con el
    catálogo `ProcesoBeneficio` del lote, que describe el método general
    (Lavado, Honey, Natural...): aquí se documenta cada paso concreto
    que se le hizo al lote, con su fecha y observaciones, para construir
    el historial cronológico de HU14-ST2.

    Las reglas de HU14-ST3 viven aquí (validadores y `clean`), de modo que
    se aplican igual desde el formulario web y desde el servicio de
    registro (`services.registrar_etapa_beneficio`, HU14-ST4, RNF-09).
    """

    class TipoEtapa(models.TextChoices):
        DESPULPADO = "DESPULPADO", "Despulpado"
        FERMENTACION = "FERMENTACION", "Fermentación"
        LAVADO = "LAVADO", "Lavado"
        SECADO = "SECADO", "Secado"

    lote = models.ForeignKey(
        Lote,
        # PROTECT: un lote con etapas no puede borrarse físicamente y
        # arrastrar su historial (RNF-14).
        on_delete=models.PROTECT,
        related_name="etapas_beneficio",
        verbose_name="Lote",
        help_text="Lote al que se le registra la etapa de beneficio.",
    )

    etapa = models.CharField(
        max_length=20,
        choices=TipoEtapa.choices,
        verbose_name="Etapa de beneficio",
        help_text="Etapa del proceso de beneficio (lista fija, no texto libre).",
        error_messages={
            "blank": "Debe seleccionar la etapa de beneficio.",
            "null": "Debe seleccionar la etapa de beneficio.",
            "invalid_choice": "La etapa seleccionada no es una etapa de beneficio válida.",
        },
    )

    fecha = models.DateField(
        verbose_name="Fecha de la etapa",
        help_text="Fecha en que se realizó la etapa sobre el lote.",
        error_messages={
            "blank": "La fecha de la etapa es obligatoria.",
            "null": "La fecha de la etapa es obligatoria.",
            "invalid": "Ingrese una fecha válida.",
        },
    )

    observaciones = models.TextField(
        blank=True,
        default="",
        validators=[validar_observaciones_etapa],
        verbose_name="Observaciones",
        help_text=f"Notas libres sobre la etapa (máximo {OBSERVACIONES_ETAPA_MAX} caracteres).",
    )

    activo = models.BooleanField(
        default=True,
        verbose_name="Etapa vigente",
        help_text="Inactivación lógica: las etapas nunca se eliminan físicamente (RNF-14).",
    )
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")

    objects = EtapaBeneficioQuerySet.as_manager()

    class Meta:
        managed = True
        db_table = "etapas_beneficio"
        verbose_name = "Etapa de beneficio"
        verbose_name_plural = "Etapas de beneficio"
        # Orden cronológico del historial (HU14-ST2): primero por la fecha
        # de la etapa y, a igual fecha, por el orden en que se registró.
        ordering = ["fecha", "creado_en", "id"]

    def __str__(self):
        return f"{self.get_etapa_display()} - Lote {self.lote.codigo} ({self.fecha})"

    def clean(self):
        super().clean()
        if self.observaciones:
            self.observaciones = self.observaciones.strip()

    def delete(self, using=None, keep_parents=False):
        """Inactivación lógica en lugar de borrado físico (RNF-14)."""
        self.activo = False
        self.save(update_fields=["activo"])
        return 0, {}

    delete.alters_data = True


class BitacoraPublicacionLote(models.Model):
    """
    Registro inmutable de trazabilidad para eventos de publicación y
    despublicación de lotes en el catálogo comercial (HU19-ST6 / SCRUM-244).
    """

    ACCION_CHOICES = [
        ("PUBLICAR", "Publicar en catálogo"),
        ("DESPUBLICAR", "Retirar de catálogo"),
        ("ACTUALIZAR", "Actualizar publicación"),
    ]

    lote = models.ForeignKey(
        Lote,
        on_delete=models.CASCADE,
        related_name="historial_publicaciones",
        verbose_name="Lote",
    )
    accion = models.CharField(
        max_length=20,
        choices=ACCION_CHOICES,
        verbose_name="Acción realizada",
    )
    realizado_por_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="ID de usuario que realizó la acción",
    )
    realizado_por_correo = models.EmailField(
        null=True,
        blank=True,
        verbose_name="Correo de usuario que realizó la acción",
    )
    detalles_trazabilidad = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Snapshot de trazabilidad y calidad al momento de publicar",
    )
    observaciones = models.TextField(
        blank=True,
        default="",
        verbose_name="Observaciones o motivo",
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro",
    )

    class Meta:
        managed = True
        db_table = "fincas_bitacora_publicacion_lote"
        verbose_name = "Registro de publicación de lote"
        verbose_name_plural = "Bitácora de publicaciones de lotes"
        ordering = ["-creado_en", "-id"]

    def __str__(self):
        return f"{self.accion} - Lote {self.lote.codigo} ({self.creado_en})"


class ManifestacionInteres(models.Model):
    """
    Manifestación de interés de un Comprador sobre un Lote publicado en el
    catálogo comercial (HU-22 / SCRUM-231).

    HU22-ST2 (SCRUM-261): persistencia real de la manifestación. Antes de
    esta subtarea, `fincas.services.registrar_manifestacion_interes()`
    (HU22-ST5 / SCRUM-264, rama francisco-epi6-hu22) devolvía un
    diccionario en memoria con un id simulado (uuid) y nunca lo guardaba
    en base de datos -- su propia prueba `test_mock_disparo_notificacion_externa`
    así lo admite. Este modelo es lo que ese servicio usa ahora para
    persistir de verdad, manteniendo exactamente el mismo "contrato" de
    datos que ST5/ST6/ST7/ST8 ya esperan (ver registrar_manifestacion_interes).

    HU22-ST1 (SCRUM-260): el mecanismo de notificación al productor es
    in-app, no por correo -- este proyecto no tiene ningún backend de
    correo (EMAIL_BACKEND) configurado en cafe_pergamo/settings.py. La
    manifestación queda disponible de inmediato (`notificado_en`) para
    que el productor la vea desde su panel de "Mis Lotes", y se marca
    como vista (`vista_por_productor` / `vista_en`) cuando la abre.

    No se usa eliminación física (consistente con RNF-14 en el resto del
    dominio de fincas): el campo `lote` usa on_delete=PROTECT, así que un
    lote con manifestaciones de interés no puede borrarse.
    """

    class EstadoManifestacion(models.TextChoices):
        REGISTRADO = "REGISTRADO", "Registrado"

    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="manifestaciones_interes",
        verbose_name="Lote",
        help_text="Lote comercial sobre el que se manifiesta interés.",
    )

    comprador = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        db_constraint=False,
        related_name="manifestaciones_interes",
        verbose_name="Comprador interesado",
        help_text="Perfil de negocio (usuarios.Usuario, rol COMPRADOR) que manifiesta el interés.",
    )

    comprador_correo = models.EmailField(
        blank=True,
        default="",
        verbose_name="Correo de contacto del comprador",
    )

    cantidad_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Cantidad de interés (kg)",
        help_text="Cantidad orientativa de interés, en kilogramos (opcional; no puede superar el stock del lote).",
    )

    mensaje = models.TextField(
        blank=True,
        default="",
        verbose_name="Mensaje del comprador",
        help_text="Mensaje libre del comprador para el productor (máximo 1000 caracteres).",
    )

    telefono_contacto = models.CharField(
        max_length=30,
        blank=True,
        default="",
        verbose_name="Teléfono de contacto",
    )

    estado = models.CharField(
        max_length=20,
        choices=EstadoManifestacion.choices,
        default=EstadoManifestacion.REGISTRADO,
        verbose_name="Estado de la manifestación",
    )

    # ------------------------------------------------------------------
    # HU22-ST1 (SCRUM-260): mecanismo de notificación in-app.
    # ------------------------------------------------------------------
    notificado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Notificado al productor en",
        help_text="Momento en que la notificación quedó disponible para el productor del lote.",
    )
    vista_por_productor = models.BooleanField(
        default=False,
        verbose_name="Vista por el productor",
    )
    vista_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Vista por el productor en",
    )

    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")

    class Meta:
        managed = True
        db_table = "fincas_manifestacion_interes"
        verbose_name = "Manifestación de interés"
        verbose_name_plural = "Manifestaciones de interés"
        ordering = ["-creado_en", "-id"]

    def __str__(self):
        return f"Interés de {self.comprador_id} en lote {self.lote.codigo} ({self.creado_en})"

    def marcar_vista_por_productor(self):
        """HU22-ST1: marca la notificación como vista/leída por el productor."""
        if not self.vista_por_productor:
            self.vista_por_productor = True
            self.vista_en = timezone.now()
            self.save(update_fields=["vista_por_productor", "vista_en"])
class BitacoraFichaDigital(models.Model):
    """
    Registro inmutable de auditoría para la Ficha Digital Consolidada
    (HU-17 / ST7 - SCRUM-172).
    Registra consultas públicas (Web y API/QR) y eventos de actualización
    de trazabilidad del lote.
    """

    TIPO_CONSULTA_WEB = "CONSULTA_WEB"
    TIPO_CONSULTA_API = "CONSULTA_API"
    TIPO_ACTUALIZACION = "ACTUALIZACION"

    TIPOS_EVENTO = [
        (TIPO_CONSULTA_WEB, "Consulta Web de Ficha Digital"),
        (TIPO_CONSULTA_API, "Consulta API REST / Escaneo QR"),
        (TIPO_ACTUALIZACION, "Actualización de Datos de Trazabilidad"),
    ]

    lote = models.ForeignKey(
        Lote,
        on_delete=models.CASCADE,
        related_name="auditorias_ficha",
        verbose_name="Lote auditado",
    )
    tipo_evento = models.CharField(
        max_length=30,
        choices=TIPOS_EVENTO,
        default=TIPO_CONSULTA_WEB,
        verbose_name="Tipo de evento",
    )
    completitud_porcentaje = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Completitud al momento del evento (%)",
    )
    es_consistente = models.BooleanField(
        default=True,
        verbose_name="Estado de consistencia de datos",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="Dirección IP",
    )
    user_agent = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Agente de usuario / Navegador",
    )
    usuario_identificador = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        verbose_name="Usuario / Actor",
        help_text="Identificador o correo del usuario, o 'Público / Escaneo QR' si fue acceso público.",
    )
    detalles = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Detalles contextuales del evento",
    )
    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora del registro",
    )

    class Meta:
        managed = True
        db_table = "fincas_bitacora_ficha_digital"
        verbose_name = "Auditoría de Ficha Digital"
        verbose_name_plural = "Bitácora de Fichas Digitales"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["lote", "-creado_en"], name="idx_bitacora_lote_fecha"),
            models.Index(fields=["tipo_evento"], name="idx_bitacora_tipo_evento"),
        ]

    def __str__(self):
        return f"{self.tipo_evento} - Lote {self.lote.codigo} ({self.creado_en:%Y-%m-%d %H:%M})"


# ==============================================================================
# MODELO DE ASOCIACIÓN Y PERSISTENCIA LOTE - CÓDIGO QR (HU-18 / SCRUM-176)
# ==============================================================================

class CodigoQRLote(models.Model):
    """
    Persistencia de la asociación entre lote y código QR (HU-18 / SCRUM-176 / SCRUM-22).

    Criterios de Aceptación:
    1. Unicidad: Cada lote tiene a lo sumo un registro de Código QR único (OneToOneField + unique).
    2. Nivel de Visibilidad: Define si la ficha accesible es pública o privada (PUBLICA / PRIVADA).
    """

    VISIBILIDAD_PUBLICA = "PUBLICA"
    VISIBILIDAD_PRIVADA = "PRIVADA"
    OPCIONES_VISIBILIDAD = (
        (VISIBILIDAD_PUBLICA, "Pública (Acceso libre a compradores)"),
        (VISIBILIDAD_PRIVADA, "Privada (Restringida al productor)"),
    )

    lote = models.OneToOneField(
        Lote,
        on_delete=models.CASCADE,
        related_name="codigo_qr",
        verbose_name="Lote de café asociado",
        help_text="Lote único al que pertenece este código QR (criterio de aceptación: 1 QR por lote).",
    )

    identificador = models.CharField(
        max_length=60,
        unique=True,
        db_index=True,
        verbose_name="Identificador único del QR",
        help_text="Identificador único formal del QR (formato canónico: 'QR-<CODIGO_LOTE>').",
    )

    nivel_visibilidad = models.CharField(
        max_length=15,
        choices=OPCIONES_VISIBILIDAD,
        default=VISIBILIDAD_PUBLICA,
        verbose_name="Nivel de visibilidad",
        help_text="Controla el nivel de acceso a la ficha digital: pública o privada (HU-18).",
    )

    payload_url = models.CharField(
        max_length=255,
        verbose_name="URL codificada en el QR",
        help_text="Ruta canónica o URL pública codificada dentro de la matriz del QR.",
    )

    imagen_base64 = models.TextField(
        blank=True,
        default="",
        verbose_name="Imagen QR (Data URI Base64)",
        help_text="Representación gráfica matricial en Data URI para renderizado directo.",
    )

    activo = models.BooleanField(
        default=True,
        verbose_name="QR activo",
        help_text="Indica si el QR está activo para consultas y escaneo.",
    )

    creado_en = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de generación",
    )

    actualizado_en = models.DateTimeField(
        auto_now=True,
        verbose_name="Última actualización",
    )

    class Meta:
        managed = True
        db_table = "fincas_codigo_qr_lote"
        verbose_name = "Código QR de Lote"
        verbose_name_plural = "Códigos QR de Lotes"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["identificador"], name="idx_qr_identificador"),
            models.Index(fields=["lote", "activo"], name="idx_qr_lote_activo"),
        ]

    def __str__(self):
        return f"{self.identificador} -> Lote {self.lote.codigo} [{self.nivel_visibilidad}]"

    def clean(self):
        super().clean()
        if not self.identificador and hasattr(self, "lote") and self.lote:
            from .services import generar_identificador_qr_lote
            self.identificador = generar_identificador_qr_lote(self.lote)
        if self.nivel_visibilidad not in [self.VISIBILIDAD_PUBLICA, self.VISIBILIDAD_PRIVADA]:
            raise ValidationError({
                "nivel_visibilidad": f"Nivel de visibilidad '{self.nivel_visibilidad}' no válido."
            })

    def save(self, *args, **kwargs):
        if not self.identificador and hasattr(self, "lote") and self.lote:
            from .services import generar_identificador_qr_lote
            self.identificador = generar_identificador_qr_lote(self.lote)
        if not self.payload_url and hasattr(self, "lote") and self.lote:
            from .services import construir_payload_qr_lote
            self.payload_url = construir_payload_qr_lote(self.lote)
        self.full_clean()
        super().save(*args, **kwargs)

