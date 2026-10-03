"""
Template tags para renderizado condicional por Rol - CAFÉ PÉRGAMO
Subtarea: SCRUM-109 / HU04-ST3: Control de rutas y menú según Rol (RNF21).

Filtro de plantilla `tiene_permiso`, para ocultar o mostrar botones de
acción y opciones de menú según la matriz RBAC, sin duplicar en las
plantillas la lógica de consulta que ya vive en
`usuarios/permissions.py` (usuario_tiene_permiso).

Uso en una plantilla, combinado con `rol_actual` (ver
usuarios/context_processors.py, registrado para todas las plantillas):

    {% load rbac_tags %}
    {% if rol_actual|tiene_permiso:"usuarios.administrar" %}
        <a href="{% url 'admin_usuarios' %}">Administrar usuarios</a>
    {% endif %}
"""

from django import template

from usuarios.permissions import usuario_tiene_permiso

register = template.Library()


@register.filter(name="tiene_permiso")
def tiene_permiso(role_code, permiso_codigo):
    return usuario_tiene_permiso(role_code, permiso_codigo)
