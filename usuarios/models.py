"""
Modelos Django para el dominio "Usuarios y RBAC" de CAFÉ PÉRGAMO.

Todas las tablas de este archivo YA EXISTEN en el proyecto Supabase del
equipo (creadas con migraciones SQL directas — ver README_HU01-ST1.md y
README_HU04-ST1.md en la carpeta db/ del repo). Por eso cada modelo
tiene `Meta.managed = False`: Django los usa únicamente para
leer/escribir datos por el ORM, nunca para crear, alterar o borrar el
esquema — eso lo controla Supabase.

Ejecutar `python manage.py migrate` en un checkout nuevo NO toca estas
tablas (no generan migraciones); solo aplica las migraciones propias
de Django (auth, admin, sessions, contenttypes), que sí gestionan su
propio esquema en la misma base de datos sin chocar con estas.
"""

from django.db import models
from django.db.models.functions import Now


class TipoDocumento(models.Model):
    """Catálogo administrable de tipos de documento (CC, CE, TI, PA, NIT)."""

    id = models.SmallAutoField(primary_key=True)
    codigo = models.TextField(unique=True)
    nombre = models.TextField()
    activo = models.BooleanField(db_default=True)

    class Meta:
        managed = False
        db_table = "tipos_documento"
        verbose_name = "Tipo de documento"
        verbose_name_plural = "Tipos de documento"

    def __str__(self):
        return f"{self.codigo} — {self.nombre}"


class Rol(models.Model):
    """Catálogo administrable de roles (RF03): Administrador, Productor/
    Comercializador, Asociación, Operario de Campo, Comprador y
    Consulta pública."""

    id = models.SmallAutoField(primary_key=True)
    codigo = models.TextField(unique=True)
    nombre = models.TextField()
    descripcion = models.TextField(null=True, blank=True)
    activo = models.BooleanField(db_default=True)
    requiere_cuenta = models.BooleanField(
        db_default=True,
        help_text="false = rol sin cuenta/registro (p.ej. Consulta pública vía QR); "
                  "nunca debe asignarse a una fila real de usuarios.",
    )
    creado_en = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "roles"
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.nombre


class Usuario(models.Model):
    """
    Ficha de perfil de negocio de cada usuario (HU01-ST1).

    OJO — el correo y la contraseña "reales" (hash con bcrypt, tokens de
    recuperación, etc.) NO viven aquí: viven en `auth.users`, la tabla
    que gestiona Supabase Auth (GoTrue). Este modelo no declara esa
    tabla porque Django no la administra ni debe tocarla directamente.

    `id` es el MISMO UUID que `auth.users.id` — nunca se genera en
    Django. Una fila de `usuarios` solo debe crearse:
      a) automáticamente, por el trigger `on_auth_user_created` de
         Supabase cuando alguien se registra con `supabase.auth.sign_up()`
         (flujo normal, ver `usuarios/supabase_client.py`), o
      b) explícitamente con `Usuario.objects.create(id=<uuid de auth.users>, ...)`
         si el registro ya se hizo contra Supabase Auth y solo falta
         sincronizar/leer el perfil.
    Nunca instancies `Usuario()` sin un `id` real de `auth.users` — la
    restricción de llave foránea de la base de datos lo rechazará.
    """

    id = models.UUIDField(primary_key=True, editable=False)
    correo = models.EmailField(unique=True)
    tipo_documento = models.ForeignKey(
        TipoDocumento,
        on_delete=models.DO_NOTHING,
        db_column="tipo_documento_id",
        related_name="usuarios",
    )
    numero_documento = models.TextField()
    nombres = models.TextField()
    apellidos = models.TextField()
    telefono = models.TextField(null=True, blank=True)
    rol = models.ForeignKey(
        Rol,
        on_delete=models.DO_NOTHING,
        db_column="rol_id",
        related_name="usuarios",
    )
    activo = models.BooleanField(db_default=True)
    failed_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Contador de intentos de autenticación fallidos consecutivos (RN03)",
    )
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Marca temporal hasta la cual la cuenta permanece bloqueada (EX-3)",
    )
    creado_en = models.DateTimeField(db_default=Now())
    actualizado_en = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "usuarios"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_documento", "numero_documento"],
                name="usuarios_numero_documento_unico",
            ),
        ]

    def __str__(self):
        return f"{self.nombres} {self.apellidos} <{self.correo}>"

    @property
    def is_locked(self) -> bool:
        """Determina si el perfil de negocio se encuentra actualmente bloqueado."""
        if not self.locked_until:
            return False
        from django.utils import timezone
        return self.locked_until > timezone.now()


class Permiso(models.Model):
    """Catálogo de permisos del sistema (RNF06), uno por función concreta,
    trazable a un RF del SRS y a un caso de uso del EP3."""

    id = models.SmallAutoField(primary_key=True)
    codigo = models.TextField(unique=True)
    nombre = models.TextField()
    descripcion = models.TextField(null=True, blank=True)
    modulo = models.TextField()
    activo = models.BooleanField(db_default=True)
    creado_en = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "permisos"
        verbose_name = "Permiso"
        verbose_name_plural = "Permisos"

    def __str__(self):
        return self.codigo


class RolPermiso(models.Model):
    """La matriz RBAC en sí: qué permisos tiene cada rol (RNF06).

    Tabla intermedia con llave primaria COMPUESTA (rol_id, permiso_id) —
    no tiene una columna `id` propia. Se modela con
    `models.CompositePrimaryKey` (Django 5.2+) en vez de dejar que
    Django agregue un `id` autoincremental que no existe en la tabla
    real.
    """

    rol = models.ForeignKey(
        Rol,
        on_delete=models.DO_NOTHING,
        db_column="rol_id",
        related_name="rol_permisos",
    )
    permiso = models.ForeignKey(
        Permiso,
        on_delete=models.DO_NOTHING,
        db_column="permiso_id",
        related_name="rol_permisos",
    )
    pk = models.CompositePrimaryKey("rol_id", "permiso_id")
    otorgado_en = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "rol_permisos"
        verbose_name = "Permiso de rol"
        verbose_name_plural = "Matriz de permisos por rol (RBAC)"

    def __str__(self):
        return f"{self.rol.codigo} → {self.permiso.codigo}"


# ==============================================================================
# AUDITORÍA DE SEGURIDAD Y CONTROL DE BLOQUEO (SCRUM-79 / HU02-ST5)
# ==============================================================================
from django.contrib.auth.models import User


class RegistroIntentoLogin(models.Model):
    """
    Registro y control de intentos fallidos de autenticación (SCRUM-79 / HU02-ST5).
    Implementa RN03 (Límite de intentos) y EX-3 (Bloqueo temporal de cuenta).
    Tabla gestionada por Django para persistencia independiente y auditoría.
    """

    identificador = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Identificador único (correo o username en minúsculas).",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="intentos_login",
        help_text="Usuario de Django asociado si existe en la plataforma.",
    )
    failed_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Número consecutivo de intentos fallidos registrados.",
    )
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Marca temporal hasta la cual la cuenta permanece bloqueada.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Dirección IP de origen del último intento.",
    )
    ultimo_intento = models.DateTimeField(
        auto_now=True,
        help_text="Fecha y hora del intento más reciente.",
    )

    class Meta:
        managed = True
        db_table = "usuarios_registro_intentos"
        verbose_name = "Registro de intento de login"
        verbose_name_plural = "Registros de intentos de login"

    def __str__(self):
        estado = "BLOQUEADO" if self.is_locked else "ACTIVO"
        return f"{self.identificador} [{estado}] - Intentos fallidos: {self.failed_attempts}"

    @property
    def is_locked(self) -> bool:
        """Determina si la cuenta está actualmente bloqueada."""
        if not self.locked_until:
            return False
        from django.utils import timezone
        return self.locked_until > timezone.now()

    def tiempo_restante_minutos(self) -> int:
        """Calcula los minutos restantes de bloqueo temporal."""
        if not self.is_locked:
            return 0
        from django.utils import timezone
        delta = self.locked_until - timezone.now()
        return max(1, int(delta.total_seconds() / 60) + 1)



