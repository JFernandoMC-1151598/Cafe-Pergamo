from django.contrib import admin

from .models import BitacoraCatalogoTrazabilidad


@admin.register(BitacoraCatalogoTrazabilidad)
class BitacoraCatalogoTrazabilidadAdmin(admin.ModelAdmin):
    list_display = (
        "catalogo",
        "registro_codigo",
        "accion",
        "realizado_por_correo",
        "creado_en",
    )
    list_filter = ("catalogo", "accion", "creado_en")
    search_fields = (
        "registro_codigo",
        "registro_nombre",
        "realizado_por_correo",
    )
    readonly_fields = (
        "catalogo",
        "registro_id",
        "registro_codigo",
        "registro_nombre",
        "accion",
        "valores_anteriores",
        "valores_nuevos",
        "realizado_por_id",
        "realizado_por_correo",
        "ip_address",
        "creado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
