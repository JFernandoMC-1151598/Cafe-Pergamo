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
from django.urls import path
from django.shortcuts import render

from usuarios.views import registro_api

def registro_view(request):
    return render(request, 'usuarios/registro.html')

def login_view(request):
    return render(request, 'usuarios/login.html')

def logout_view(request):
    # Endpoint para HU02-ST4 (Lógica de Cierre de Sesión)
    from django.contrib.auth import logout
    from django.shortcuts import redirect
    logout(request)
    return redirect('login')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('registro/', registro_view, name='registro'), 
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('', login_view, name='home'),

    # HU01-ST3 (SCRUM-60): endpoint de registro de usuarios (backend).
    path('api/auth/register', registro_api, name='api_registro'),
]
