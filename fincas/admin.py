"""
Configuración del panel de administración para Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1 (Fincas y Municipios).
Subtarea: SCRUM-98 / HU07-ST5 (Georreferenciación).
"""

from django.contrib import admin
from .models import Finca, Municipio


@admin.register(Municipio)
class MunicipioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "departamento", "codigo", "activo")
    list_filter = ("departamento", "activo")
    search_fields = ("nombre", "codigo")
    ordering = ("nombre",)


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
