"""
Cliente de Supabase para este backend Django.

Decisión de arquitectura (ver README_HU01-ST1.md): la autenticación real
—correo, hash de contraseña, recuperación segura— la resuelve Supabase
Auth (GoTrue), no Django. `django.contrib.auth` sigue instalado solo
para que funcione el admin de Django en local; el modelo `Usuario` de
esta app (`usuarios/models.py`) es un perfil de negocio 1:1 con
`auth.users`, no el sistema de autenticación en sí.

Por eso el endpoint de registro de HU01-ST3 (`POST /api/auth/register`)
NO debe crear la contraseña ni el usuario "a mano" con SQL: debe llamar
a `supabase.auth.sign_up(...)` a través de este cliente. Ese único
llamado:
  1. crea la fila en `auth.users` con el correo y la contraseña cifrada,
  2. dispara el trigger `on_auth_user_created` en Supabase, que arma
     automáticamente la fila correspondiente en `public.usuarios` con
     los metadatos que se envíen (tipo_documento, numero_documento,
     nombres, apellidos, telefono, rol).

La app solo necesita la URL del proyecto y la publishable/anon key
(ambas seguras de exponer: la protección real la da Row Level Security
en Supabase, no el secreto de esta key). Nunca uses aquí la
service_role key — esa se salta RLS por completo y no la necesita este
flujo.
"""

from functools import lru_cache

from django.conf import settings
from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """
    Devuelve un cliente de Supabase reutilizable (cacheado por proceso).

    Requiere SUPABASE_URL y SUPABASE_ANON_KEY en el entorno (ver
    .env.example). Lanza RuntimeError con un mensaje claro si faltan,
    en vez de fallar más abajo con un error críptico del SDK.
    """
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_ANON_KEY
    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL y/o SUPABASE_ANON_KEY en el .env. "
            "Copia .env.example a .env y complétalas con los valores "
            "del proyecto Supabase de Café Pérgamo (Project Settings → API)."
        )
    return create_client(url, key)
