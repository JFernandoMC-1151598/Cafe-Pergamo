from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    """
    App de dominio "Usuarios" del proyecto CAFÉ PÉRGAMO.

    IMPORTANTE: esta app NO gestiona su propio esquema de base de datos.
    Todas las tablas que mapea (roles, tipos_documento, usuarios,
    permisos, rol_permisos) ya existen en el proyecto Supabase del
    equipo — se crearon y versionan con migraciones SQL directas sobre
    Supabase (ver carpeta db/ en el repo, subtareas HU01-ST1 y
    HU04-ST1), no con `python manage.py migrate` de Django.

    Por eso todos los modelos de esta app declaran `Meta.managed = False`:
    Django los usa para leer/escribir datos vía el ORM, pero nunca
    intentará crear, alterar ni borrar estas tablas.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "usuarios"
    verbose_name = "Usuarios y RBAC"
