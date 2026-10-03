"""
Lógica de negocio para la reasignación de roles de usuario - CAFÉ PÉRGAMO
Subtarea: SCRUM-120 / HU04-ST5: Actualización de Roles y auditoría (RF28).

HU04-ST4 (SCRUM-119) ya construyó la pantalla web de administración de
usuarios con un cambio de rol provisional, dejando pendiente a
propósito dos cosas para esta subtarea: la restricción de no dejar el
sistema sin administradores activos, y el registro en la bitácora de
auditoría (RF28). Esta pieza centraliza ambas reglas en una sola
función (`cambiar_rol_usuario`), para que tanto el endpoint de API
(HU04-ST5, `/api/users/<id>/role`) como la pantalla web (HU04-ST4) las
apliquen exactamente igual en vez de duplicar la lógica en dos lugares
que con el tiempo podrían desincronizarse.
"""

from typing import Optional, Tuple

from .models import BitacoraCambioRol, Rol, Usuario

CODIGO_ADMINISTRADOR = "ADMINISTRADOR"


class CambioRolInvalido(Exception):
    """Un cambio de rol que no puede aplicarse por una regla de negocio (RF28)."""


def _es_el_ultimo_administrador_activo(usuario: Usuario) -> bool:
    """
    True si `usuario` es hoy ADMINISTRADOR activo y no queda ningún
    otro administrador activo además de él — es decir, si se le
    reasigna el rol el sistema se queda sin nadie que pueda
    administrarlo.

    Un administrador ya inactivo no cuenta para esta regla (una cuenta
    inactiva no puede operar como administrador de todas formas), así
    que cambiarle el rol a una cuenta inactiva nunca queda bloqueado
    por esto.
    """
    if usuario.rol.codigo != CODIGO_ADMINISTRADOR or not usuario.activo:
        return False

    otros_administradores_activos = Usuario.objects.filter(
        rol__codigo=CODIGO_ADMINISTRADOR, activo=True
    ).exclude(id=usuario.id)
    return not otros_administradores_activos.exists()


def cambiar_rol_usuario(
    usuario: Usuario,
    nuevo_rol: Rol,
    realizado_por: Optional[Usuario] = None,
    ip_address: Optional[str] = None,
) -> Tuple[Usuario, Optional[BitacoraCambioRol]]:
    """
    Reasigna el rol de `usuario` a `nuevo_rol`.

    Aplica la restricción de seguridad de RF28 (no dejar el sistema sin
    administradores) y, si el cambio procede, deja constancia en la
    bitácora de auditoría. Si `nuevo_rol` es el mismo que ya tiene el
    usuario, no se considera un cambio real: no se toca la base de
    datos ni se crea una entrada de bitácora.

    Lanza `CambioRolInvalido` cuando la reasignación dejaría el sistema
    sin ningún administrador activo — la vista que llame a esta función
    es responsable de traducir esa excepción a la respuesta adecuada
    (mensaje flash y redirección en la pantalla web, JSON 409 en la API).

    Retorna `(usuario, entrada_bitacora)`; `entrada_bitacora` es `None`
    cuando no hubo un cambio real que registrar.
    """
    if usuario.rol_id == nuevo_rol.id:
        return usuario, None

    if _es_el_ultimo_administrador_activo(usuario):
        raise CambioRolInvalido(
            "No es posible reasignar este rol: el sistema se quedaría sin ningún "
            "administrador activo. Asigne el rol de Administrador a otra cuenta antes "
            "de continuar."
        )

    rol_anterior_codigo = usuario.rol.codigo
    usuario.rol = nuevo_rol
    usuario.save(update_fields=["rol"])

    entrada_bitacora = BitacoraCambioRol.objects.create(
        usuario_id=usuario.id,
        usuario_correo=usuario.correo,
        rol_anterior=rol_anterior_codigo,
        rol_nuevo=nuevo_rol.codigo,
        realizado_por_id=realizado_por.id if realizado_por else None,
        realizado_por_correo=realizado_por.correo if realizado_por else None,
        ip_address=ip_address,
    )

    return usuario, entrada_bitacora
