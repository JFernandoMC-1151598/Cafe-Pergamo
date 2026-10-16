"""
Servicios de dominio para el módulo de Fincas y Catálogos - CAFÉ PÉRGAMO
Subtarea: SCRUM-112 / HU09-ST3: Implementar servicios y API para crear municipios.
"""

from typing import Optional
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Municipio


def generar_codigo_municipio_sugerido(nombre: str, departamento: str) -> str:
    """
    Genera un código único sugerido cuando no se proporciona un código DANE explícito.
    Formato: prefijo del departamento + nombre normalizado (máximo 20 caracteres).
    Si existe colisión, añade un correlativo numérico.
    """
    prefijo = "".join(palabra[0] for palabra in departamento.split() if palabra).upper()[:3] or "MUN"
    sufijo = "".join(caracter for caracter in nombre.upper() if caracter.isalnum())[:12]
    base = f"{prefijo}-{sufijo}"
    codigo = base[:20]

    contador = 1
    while Municipio.objects.filter(codigo=codigo).exists():
        sufijo_num = f"-{contador}"
        codigo = f"{base[:20 - len(sufijo_num)]}{sufijo_num}"
        contador += 1

    return codigo


def crear_municipio(
    *,
    nombre: str,
    departamento: str = "Norte de Santander",
    codigo: Optional[str] = None,
    activo: bool = True,
) -> Municipio:
    """
    Crea y persiste un nuevo municipio en el catálogo con validación de reglas de negocio (SCRUM-112).

    Reglas aplicadas:
    1. El nombre y departamento son obligatorios y no pueden ser cadenas vacías.
    2. Bloqueo de nombres de municipios duplicados en el mismo departamento (case-insensitive).
    3. Asignación automática de código sugerido si no se suministra.
    4. Validación a nivel de modelo mediante `full_clean()`.
    """
    nombre_limpio = (nombre or "").strip()
    departamento_limpio = (departamento or "").strip()

    if not nombre_limpio:
        raise ValidationError({"nombre": "El nombre del municipio no puede estar vacío."})

    if not departamento_limpio:
        raise ValidationError({"departamento": "El departamento no puede estar vacío."})

    if not codigo or not str(codigo).strip():
        codigo_final = generar_codigo_municipio_sugerido(nombre_limpio, departamento_limpio)
    else:
        codigo_final = str(codigo).strip().upper()

    municipio = Municipio(
        codigo=codigo_final,
        nombre=nombre_limpio,
        departamento=departamento_limpio,
        activo=activo,
    )
    municipio.full_clean()
    municipio.save()
    return municipio


def editar_municipio(
    municipio_o_id,
    *,
    nombre: Optional[str] = None,
    departamento: Optional[str] = None,
    codigo: Optional[str] = None,
    activo: Optional[bool] = None,
) -> Municipio:
    """
    Actualiza los datos de un municipio existente en el catálogo (SCRUM-110 / HU09-ST1).

    Reglas aplicadas:
    1. Si se actualiza el nombre o departamento, no pueden ser cadenas vacías.
    2. Bloqueo de duplicados en el mismo departamento (excluyendo el registro actual).
    3. Si se actualiza el código, debe ser único en el sistema.
    4. Validación integral de modelo mediante `full_clean()`.
    """
    if isinstance(municipio_o_id, Municipio):
        municipio = municipio_o_id
    else:
        try:
            municipio = Municipio.objects.get(pk=municipio_o_id)
        except Municipio.DoesNotExist:
            raise ValidationError({"id": "Municipio no encontrado."})

    if nombre is not None:
        nombre_limpio = str(nombre).strip()
        if not nombre_limpio:
            raise ValidationError({"nombre": "El nombre del municipio no puede estar vacío."})
        municipio.nombre = nombre_limpio

    if departamento is not None:
        dep_limpio = str(departamento).strip()
        if not dep_limpio:
            raise ValidationError({"departamento": "El departamento no puede estar vacío."})
        municipio.departamento = dep_limpio

    if codigo is not None:
        cod_limpio = str(codigo).strip().upper()
        if not cod_limpio:
            raise ValidationError({"codigo": "El código del municipio no puede estar vacío."})
        municipio.codigo = cod_limpio

    if activo is not None:
        municipio.activo = bool(activo)

    municipio.full_clean()
    municipio.save()
    return municipio


def inactivar_municipio(municipio_o_id):
    """
    Realiza la inactivación lógica (activo = False) de un municipio (SCRUM-113 / HU09-ST4).
    Preserva intacta la integridad referencial histórica con las fincas ya registradas.
    """
    if isinstance(municipio_o_id, Municipio):
        municipio = municipio_o_id
    else:
        try:
            municipio = Municipio.objects.get(pk=municipio_o_id)
        except Municipio.DoesNotExist:
            raise ValidationError({"id": "Municipio no encontrado."})

    municipio.activo = False
    municipio.save()

    total_fincas = municipio.total_fincas_asociadas
    if total_fincas > 0:
        mensaje = (
            f"Municipio '{municipio.nombre}' inactivado lógicamente. "
            f"Se preserva la integridad referencial con {total_fincas} finca(s) histórica(s) asociada(s)."
        )
    else:
        mensaje = f"Municipio '{municipio.nombre}' inactivado exitosamente."

    return municipio, mensaje


def reactivar_municipio(municipio_o_id):
    """
    Reactiva un municipio previamente inactivado (activo = True).
    """
    if isinstance(municipio_o_id, Municipio):
        municipio = municipio_o_id
    else:
        try:
            municipio = Municipio.objects.get(pk=municipio_o_id)
        except Municipio.DoesNotExist:
            raise ValidationError({"id": "Municipio no encontrado."})

    municipio.activo = True
    municipio.save()
    mensaje = f"Municipio '{municipio.nombre}' reactivado exitosamente."
    return municipio, mensaje


def toggle_estado_municipio(municipio_o_id):
    """
    Alterna el estado activo/inactivo de un municipio (SCRUM-113).
    """
    if isinstance(municipio_o_id, Municipio):
        municipio = municipio_o_id
    else:
        try:
            municipio = Municipio.objects.get(pk=municipio_o_id)
        except Municipio.DoesNotExist:
            raise ValidationError({"id": "Municipio no encontrado."})

    if municipio.activo:
        return inactivar_municipio(municipio)
    return reactivar_municipio(municipio)
