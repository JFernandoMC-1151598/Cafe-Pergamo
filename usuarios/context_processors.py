"""
Context processor para control de menú por Rol - CAFÉ PÉRGAMO
Subtarea: SCRUM-109 / HU04-ST3: Control de rutas y menú según Rol (RNF21).

Expone el código de rol de la sesión actual (el mismo que ya deja
`login_view` en `request.session['rol']`) como `rol_actual` en el
contexto de TODAS las plantillas del sitio, para que el menú y los
botones de acción puedan mostrarse u ocultarse según el rol sin que
cada vista tenga que pasarlo explícitamente.

Se usa junto al filtro `tiene_permiso` de
`usuarios/templatetags/rbac_tags.py`, que consulta la misma matriz RBAC
que ya usan los guards de HU04-ST2/ST3 en el servidor — así la UI nunca
muestra una opción que el servidor igual rechazaría.
"""


def rol_actual(request):
    rol = ""
    if hasattr(request, "session"):
        rol = request.session.get("rol", "") or ""
    return {"rol_actual": rol}
