"""
Registro en el admin de Django, solo para inspección/depuración local
del esquema RBAC — no es el flujo normal de alta de usuarios (eso pasa
por Supabase Auth, ver `usuarios/supabase_client.py`).
"""

from django.contrib import admin

from .models import Permiso, Rol, RolPermiso, TipoDocumento, Usuario

# NOTA: `RolPermiso` (la matriz RBAC) NO se registra en el admin. Su
# llave primaria es compuesta (rol_id, permiso_id) vía
# `models.CompositePrimaryKey`, y el admin de Django (a la fecha, 6.1)
# todavía no soporta registrar modelos con PK compuesta — lanza
# `ImproperlyConfigured` al arrancar. La matriz se consulta/edita por
# SQL en Supabase (ver db/002_rbac_roles_permisos.sql) o, si se
# necesita en el admin, expuesta como inline de solo lectura desde
# `RolAdmin` en vez de un ModelAdmin propio.


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo")
    search_fields = ("codigo", "nombre")


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "requiere_cuenta", "activo")
    search_fields = ("codigo", "nombre")
    list_filter = ("requiere_cuenta", "activo")


@admin.register(Permiso)
class PermisoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "modulo", "activo")
    list_filter = ("modulo", "activo")
    search_fields = ("codigo", "nombre")


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("correo", "nombres", "apellidos", "rol", "activo", "failed_attempts", "locked_until", "creado_en")
    list_filter = ("rol", "tipo_documento", "activo")
    search_fields = ("correo", "nombres", "apellidos", "numero_documento")
    # El correo/contraseña reales viven en Supabase Auth: este admin es
    # solo lectura de la ficha de negocio, no un formulario de alta.
    readonly_fields = ("id", "correo", "creado_en", "actualizado_en")


from .models import RegistroIntentoLogin


@admin.register(RegistroIntentoLogin)
class RegistroIntentoLoginAdmin(admin.ModelAdmin):
    list_display = ("identificador", "user", "failed_attempts", "locked_until", "is_locked_display", "ip_address", "ultimo_intento")
    search_fields = ("identificador", "user__username", "user__email", "ip_address")
    list_filter = ("failed_attempts",)
    readonly_fields = ("ultimo_intento",)
    actions = ["desbloquear_cuentas"]

    @admin.display(boolean=True, description="¿Bloqueado?")
    def is_locked_display(self, obj):
        return obj.is_locked

    @admin.action(description="Desbloquear cuentas seleccionadas (Reiniciar contador)")
    def desbloquear_cuentas(self, request, queryset):
        filas = queryset.update(failed_attempts=0, locked_until=None)
        self.message_user(request, f"Se han desbloqueado {filas} cuenta(s) exitosamente.")

