"""
Configuración del panel de administración para Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.
"""

from django.contrib import admin
from .models import Finca


@admin.register(Finca)
class FincaAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'municipio',
        'vereda',
        'productor',
        'latitud',
        'longitud',
        'tiene_georreferenciacion',
        'activo',
        'creado_en',
    )
    list_filter = ('municipio', 'activo', 'creado_en')
    search_fields = ('nombre', 'municipio', 'vereda', 'productor__username', 'productor__email')
    ordering = ('-creado_en',)

    @admin.display(boolean=True, description="¿Georreferenciada?")
    def tiene_georreferenciacion(self, obj):
        return obj.tiene_georreferenciacion
