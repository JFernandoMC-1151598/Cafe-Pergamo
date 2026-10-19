"""Registro centralizado de cambios en los catálogos de trazabilidad."""

from .models import EstadoLote, ProcesoBeneficio


def snapshot_catalogo(instance):
    return {
        "codigo": instance.codigo,
        "nombre": instance.nombre,
        "descripcion": instance.descripcion,
        "activo": instance.activo,
        "orden": instance.orden,
    }


def registrar_cambio_catalogo(request, instance, accion, valores_anteriores=None):
    from .models import BitacoraCatalogoTrazabilidad

    usuario = getattr(request, "user", None)
    correo = getattr(usuario, "email", "") or getattr(usuario, "username", "")
    usuario_id = str(getattr(usuario, "pk", "")) if usuario else ""
    catalogo = (
        "procesos_beneficio"
        if isinstance(instance, ProcesoBeneficio)
        else "estados_lote"
    )
    BitacoraCatalogoTrazabilidad.objects.create(
        catalogo=catalogo,
        registro_id=instance.pk,
        registro_codigo=instance.codigo,
        registro_nombre=instance.nombre,
        accion=accion,
        valores_anteriores=valores_anteriores or {},
        valores_nuevos=snapshot_catalogo(instance),
        realizado_por_id=usuario_id or None,
        realizado_por_correo=correo or None,
        ip_address=_obtener_ip(request),
    )


def _obtener_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None
