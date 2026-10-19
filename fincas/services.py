"""
Servicios de dominio para el módulo de Fincas y Catálogos - CAFÉ PÉRGAMO
Subtarea: SCRUM-112 / HU09-ST3: Implementar servicios y API para crear municipios.
Subtarea: SCRUM-142 / HU13-ST2: Implementar lógica de negocio para registrar lotes.
Subtarea: SCRUM-145 / HU013-ST4: Validar cantidad disponible antes de crear el lote.
Subtarea: SCRUM-146 / HU013-ST5: Actualizar trazabilidad de la cosecha al crear lotes.
"""

from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Cosecha, Lote, Municipio
from catalogos.models import EstadoLote, ProcesoBeneficio


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


def generar_codigo_lote(cosecha: Cosecha) -> str:
    """
    Genera un código único alfanumérico para un lote cuando no se
    proporciona uno explícito (HU13: "el lote debe tener un código único
    alfanumérico"). Formato: LOTE + id de la cosecha + correlativo de 4
    dígitos, p. ej. "LOTE30001".
    """
    prefijo = f"LOTE{cosecha.pk}"
    contador = Lote.objects.filter(cosecha=cosecha).count() + 1
    codigo = f"{prefijo}{contador:04d}"
    while Lote.objects.filter(codigo__iexact=codigo).exists():
        contador += 1
        codigo = f"{prefijo}{contador:04d}"
    return codigo


def crear_lote(
    *,
    cosecha_id,
    cantidad,
    codigo: Optional[str] = None,
    proceso_beneficio_id=None,
    estado_lote_id=None,
) -> Lote:
    """
    Crea un lote de café a partir de una cosecha existente, descontando
    la cantidad del saldo disponible de la cosecha de forma
    transaccional y automática (HU13-ST2 / SCRUM-142).

    Criterios de aceptación aplicados:
    1. "El lote debe tener un código único alfanumérico": si no se
       proporciona uno, se genera automáticamente (`generar_codigo_lote`);
       si se proporciona, se valida que sea alfanumérico y único.
    2. "La cantidad del lote no debe superar el saldo disponible de la
       cosecha": se rechaza con ValidationError si lo supera.
    3. "El descuento debe hacerse de forma transaccional automática": se
       usa `transaction.atomic()` + `select_for_update()` sobre la fila
       de la cosecha, así que dos lotes creados al mismo tiempo contra la
       misma cosecha nunca pueden, juntos, superar su saldo (se procesan
       uno a la vez, nunca leen un saldo "desactualizado").
    """
    if cantidad is None:
        raise ValidationError({"cantidad": "La cantidad del lote es obligatoria."})
    try:
        cantidad = Decimal(str(cantidad))
    except Exception:
        raise ValidationError({"cantidad": "La cantidad del lote debe ser un valor numérico."})
    if cantidad <= 0:
        raise ValidationError({"cantidad": "La cantidad del lote debe ser mayor a cero."})

    proceso = None
    if proceso_beneficio_id is not None:
        proceso = ProcesoBeneficio.objects.filter(
            pk=proceso_beneficio_id, activo=True
        ).first()
        if proceso is None:
            raise ValidationError(
                {"proceso_beneficio": "El proceso seleccionado no está activo o no existe."}
            )

    estado = None
    if estado_lote_id is not None:
        estado = EstadoLote.objects.filter(
            pk=estado_lote_id, activo=True
        ).first()
        if estado is None:
            raise ValidationError(
                {"estado_lote": "El estado seleccionado no está activo o no existe."}
            )

    with transaction.atomic():
        try:
            # select_for_update() bloquea la fila hasta que termine esta
            # transacción: una segunda creación concurrente contra la
            # misma cosecha espera a que esta termine, en vez de leer un
            # saldo que ya está desactualizado.
            cosecha = Cosecha.objects.select_for_update().get(pk=cosecha_id)
        except Cosecha.DoesNotExist:
            raise ValidationError({"cosecha": "La cosecha indicada no existe."})

        if not cosecha.activo:
            raise ValidationError({"cosecha": "No se pueden crear lotes de una cosecha inactiva."})

        # SCRUM-145 / HU013-ST4: "Verificar que la cantidad ingresada para el
        # lote no supere la cantidad disponible en la cosecha asociada y
        # mostrar un error cuando no cumpla la regla." -- el ValidationError
        # de abajo es exactamente ese error (la vista web lo muestra como
        # error de campo y la API lo traduce a 400).
        if cantidad > cosecha.cantidad_disponible:
            raise ValidationError({
                "cantidad": (
                    f"La cantidad del lote ({cantidad} kg) supera el saldo disponible "
                    f"de la cosecha ({cosecha.cantidad_disponible} kg)."
                )
            })

        codigo_limpio = str(codigo).strip().upper() if codigo else ""
        if codigo_limpio:
            if not codigo_limpio.isalnum():
                raise ValidationError({"codigo": "El código del lote debe ser alfanumérico."})
            if Lote.objects.filter(codigo__iexact=codigo_limpio).exists():
                raise ValidationError({"codigo": f"Ya existe un lote con el código '{codigo_limpio}'."})
            codigo_final = codigo_limpio
        else:
            codigo_final = generar_codigo_lote(cosecha)

        lote = Lote.objects.create(
            codigo=codigo_final,
            cosecha=cosecha,
            cantidad=cantidad,
            proceso_beneficio=proceso,
            estado_lote=estado,
        )

        # SCRUM-146 / HU013-ST5: "Descontar o reflejar la cantidad utilizada
        # en la cosecha al crear un lote para mantener la trazabilidad y
        # disponibilidad correcta." Este descuento ocurre DENTRO del mismo
        # `transaction.atomic()` / `select_for_update()` de arriba, así que
        # queda tan "transaccional y automático" como la creación del lote
        # misma -- nunca puede quedar un lote creado sin que su cosecha
        # refleje el nuevo saldo (o viceversa).
        cosecha.cantidad_disponible = cosecha.cantidad_disponible - cantidad
        cosecha.save(update_fields=["cantidad_disponible", "actualizado_en"])

    return lote
