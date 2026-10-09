"""
Validadores de dominio para Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-97: Validar formato de coordenadas.

Criterios de Aceptación Cumplidos:
- Validador que rechaza textos o valores no numéricos.
- Validador que rechaza números fuera de los rangos [-90, 90] y [-180, 180].
- Validación de consistencia mutua (par completo de coordenadas o ambas nulas).
"""

from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError


LATITUD_MIN = Decimal("-90.000000")
LATITUD_MAX = Decimal("90.000000")
LONGITUD_MIN = Decimal("-180.000000")
LONGITUD_MAX = Decimal("180.000000")


def validar_latitud(valor):
    """
    Valida que la latitud sea un número decimal válido dentro del rango [-90, 90].
    Si el valor es None o cadena vacía, se permite (campo opcional).
    Rechaza textos no numéricos o números fuera de límites.
    """
    if valor is None or valor == "":
        return None

    try:
        val_dec = Decimal(str(valor).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            "El formato de latitud es inválido. Debe ingresar un valor numérico decimal.",
            code="latitud_formato_invalido",
        )

    if val_dec < LATITUD_MIN or val_dec > LATITUD_MAX:
        raise ValidationError(
            f"La latitud {val_dec} está fuera del rango permitido. Debe estar entre -90.000000 y 90.000000 grados.",
            code="latitud_fuera_de_rango",
        )

    return val_dec


def validar_longitud(valor):
    """
    Valida que la longitud sea un número decimal válido dentro del rango [-180, 180].
    Si el valor es None o cadena vacía, se permite (campo opcional).
    Rechaza textos no numéricos o números fuera de límites.
    """
    if valor is None or valor == "":
        return None

    try:
        val_dec = Decimal(str(valor).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            "El formato de longitud es inválido. Debe ingresar un valor numérico decimal.",
            code="longitud_formato_invalido",
        )

    if val_dec < LONGITUD_MIN or val_dec > LONGITUD_MAX:
        raise ValidationError(
            f"La longitud {val_dec} está fuera del rango permitido. Debe estar entre -180.000000 y 180.000000 grados.",
            code="longitud_fuera_de_rango",
        )

    return val_dec


def validar_par_coordenadas(latitud, longitud):
    """
    Valida la coherencia de georreferenciación completa:
    Si se proporciona una coordenada, debe suministrarse obligatoriamente la otra
    para formar un punto cartográfico unívoco. Si ambas están ausentes, se acepta (opcional).
    """
    tiene_lat = latitud is not None and latitud != ""
    tiene_lng = longitud is not None and longitud != ""

    errores = {}

    if tiene_lat and not tiene_lng:
        errores["longitud"] = ValidationError(
            "Si proporciona la latitud, debe ingresar también la longitud de la finca.",
            code="longitud_requerida_con_latitud",
        )

    if tiene_lng and not tiene_lat:
        errores["latitud"] = ValidationError(
            "Si proporciona la longitud, debe ingresar también la latitud de la finca.",
            code="latitud_requerida_con_longitud",
        )

    if errores:
        raise ValidationError(errores)
