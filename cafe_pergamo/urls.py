"""
URL configuration for cafe_pergamo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from fincas.views import (
    api_busqueda_global_view,
    api_consultar_ficha_desde_qr_view,
    api_dashboard_indicadores_view,
    api_detalle_venta_view,
    api_opciones_filtro_dashboard_view,
    api_registrar_venta_view,
    busqueda_global_view,
    dashboard_indicadores_web_view,
    escanear_qr_web_view,
    ficha_digital_web_view,
)

urlpatterns = [
    path('', include('usuarios.urls')),
    path('fincas/', include('fincas.urls')),
    path('actores/', include('actores.urls')),
    path('catalogos/', include('catalogos.urls')),
    path('buscar/', busqueda_global_view, name='busqueda_global'),
    path('api/buscar/', api_busqueda_global_view, name='api_busqueda_global_root'),
    path('api/v1/buscar/', api_busqueda_global_view, name='api_v1_busqueda_global_root'),
    path('dashboard/', dashboard_indicadores_web_view, name='dashboard_indicadores_root'),
    path('indicadores/dashboard/', dashboard_indicadores_web_view, name='dashboard_indicadores_alias'),
    path('trazabilidad/lote/<str:codigo>/', ficha_digital_web_view, name='trazabilidad_lote_publica_root'),
    path('trazabilidad/qr/<str:identificador>/', escanear_qr_web_view, name='trazabilidad_qr_publica_root'),
    path('api/v1/qr/<str:identificador>/', api_consultar_ficha_desde_qr_view, name='api_v1_qr_root'),
    path('api/v1/ventas/', api_registrar_venta_view, name='api_v1_ventas_root'),
    path('api/v1/ventas/<str:codigo_comprobante>/', api_detalle_venta_view, name='api_v1_venta_detalle_root'),
    path('api/v1/indicadores/dashboard/', api_dashboard_indicadores_view, name='api_v1_dashboard_indicadores_root'),
    path('api/v1/indicadores/opciones-filtro/', api_opciones_filtro_dashboard_view, name='api_v1_opciones_filtro_dashboard_root'),
    path('admin/', admin.site.urls),
]
