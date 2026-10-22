"""
Configuración del panel de administración para Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1 (Fincas y Municipios).
Subtarea: SCRUM-98 / HU07-ST5 (Georreferenciación).
"""

from django.contrib import admin
from .models import CaracteristicasCalidad, Cosecha, Finca, Lote, Municipio


@admin.register(Municipio)
class MunicipioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "departamento", "codigo", "activo", "actualizado_en")
    list_filter = ("departamento", "activo")
    search_fields = ("nombre", "codigo")
    ordering = ("nombre",)
    readonly_fields = ("creado_en", "actualizado_en")


@admin.register(Finca)
class FincaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "municipio",
        "vereda",
        "productor",
        "latitud",
        "longitud",
        "tiene_georreferenciacion",
        "activo",
        "creado_en",
    )
    list_filter = ("municipio", "activo", "creado_en")
    search_fields = (
        "nombre",
        "vereda",
        "municipio__nombre",
        "productor__correo",
        "productor__nombres",
        "productor__apellidos",
    )
    ordering = ("-creado_en",)

    @admin.display(boolean=True, description="¿Georreferenciada?")
    def tiene_georreferenciacion(self, obj):
        return obj.tiene_georreferenciacion


@admin.register(Cosecha)
class CosechaAdmin(admin.ModelAdmin):
    list_display = ("finca", "variedad", "fecha_cosecha", "cantidad_total", "cantidad_disponible", "activo")
    list_filter = ("activo", "fecha_cosecha", "variedad")
    search_fields = ("finca__nombre",)
    ordering = ("-fecha_cosecha",)
    readonly_fields = ("creado_en", "actualizado_en")


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cosecha", "cantidad", "activo", "creado_en")
    list_filter = ("activo", "creado_en")
    search_fields = ("codigo", "cosecha__finca__nombre")
    ordering = ("-creado_en",)
    readonly_fields = ("creado_en",)


@admin.register(CaracteristicasCalidad)
class CaracteristicasCalidadAdmin(admin.ModelAdmin):
    list_display = ("lote", "humedad", "merma", "puntaje_taza", "actualizado_en")
    search_fields = ("lote__codigo",)
    ordering = ("-actualizado_en",)
    readonly_fields = ("creado_en", "actualizado_en")
