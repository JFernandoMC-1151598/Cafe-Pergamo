"""
Servicios de dominio para el módulo de Fincas y Catálogos - CAFÉ PÉRGAMO
Subtarea: SCRUM-112 / HU09-ST3: Implementar servicios y API para crear municipios.
Subtarea: SCRUM-142 / HU13-ST2: Implementar lógica de negocio para registrar lotes.
Subtarea: SCRUM-145 / HU013-ST4: Validar cantidad disponible antes de crear el lote.
Subtarea: SCRUM-146 / HU013-ST5: Actualizar trazabilidad de la cosecha al crear lotes.
Subtarea: SCRUM-155 / HU15-ST1: Implementar persistencia de características
físicas y de calidad del lote.
"""

from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CaracteristicasCalidad, Cosecha, Finca, Lote, Municipio
from catalogos.models import EstadoLote, ProcesoBeneficio, VariedadCafe


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


def _resolver_lote(lote_o_id):
    if isinstance(lote_o_id, Lote):
        return lote_o_id
    try:
        return Lote.objects.get(pk=lote_o_id)
    except (Lote.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"lote": "El lote indicado no existe."})


def crear_caracteristicas_calidad(*, lote_o_id, **datos) -> CaracteristicasCalidad:
    """
    Crea el registro único de calidad asociado a un lote (HU15-ST1).
    """
    lote = _resolver_lote(lote_o_id)
    if CaracteristicasCalidad.objects.filter(lote=lote).exists():
        raise ValidationError({"lote": "El lote ya tiene características de calidad registradas."})

    caracteristicas = CaracteristicasCalidad(lote=lote, **datos)
    caracteristicas.full_clean()
    caracteristicas.save()
    return caracteristicas


_NO_ACTUALIZAR = object()


def editar_caracteristicas_calidad(
    caracteristicas_o_id,
    *,
    humedad=_NO_ACTUALIZAR,
    merma=_NO_ACTUALIZAR,
    puntaje_taza=_NO_ACTUALIZAR,
    perfil_sensorial=_NO_ACTUALIZAR,
    observaciones=_NO_ACTUALIZAR,
) -> CaracteristicasCalidad:
    """
    Actualiza un registro existente y conserva los valores omitidos.
    """
    if isinstance(caracteristicas_o_id, CaracteristicasCalidad):
        caracteristicas = caracteristicas_o_id
    else:
        try:
            caracteristicas = CaracteristicasCalidad.objects.get(pk=caracteristicas_o_id)
        except (CaracteristicasCalidad.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"id": "Las características de calidad no existen."})

    valores = {
        "humedad": humedad,
        "merma": merma,
        "puntaje_taza": puntaje_taza,
        "perfil_sensorial": perfil_sensorial,
        "observaciones": observaciones,
    }
    for campo, valor in valores.items():
        if valor is not _NO_ACTUALIZAR:
            setattr(caracteristicas, campo, valor)

    caracteristicas.full_clean()
    caracteristicas.save()
    return caracteristicas


def crear_cosecha(
    *,
    finca_id,
    fecha_cosecha,
    cantidad_total,
    variedad_id=None,
    productor_id=None,
) -> Cosecha:
    """
    Registra y persiste una nueva cosecha para una finca determinada (HU-12 / SCRUM-137).

    Criterios de aceptación aplicados:
    1. "La finca y la variedad deben ser válidas" (SCRUM-140):
       - La finca debe existir y estar activa en el sistema.
       - Si se suministra productor_id, se valida que la finca pertenezca a dicho productor.
       - Si se suministra variedad_id, se valida contra el catálogo de VariedadCafe y que esté activa.
    2. "Las cantidades deben ser mayores a cero":
       - Se valida que cantidad_total sea numérica y estrictamente mayor que cero (> 0).
    3. "Se debe inicializar cantidad_disponible = cantidad_total":
       - Se inicializa el saldo disponible igual a la cantidad total cosechada.
    """
    if finca_id is None:
        raise ValidationError({"finca": "Debe seleccionar la finca de donde proviene la cosecha."})

    try:
        finca = Finca.objects.get(pk=finca_id)
    except Finca.DoesNotExist:
        raise ValidationError({"finca": "La finca indicada no existe."})

    if not finca.activo:
        raise ValidationError({"finca": "No se pueden registrar cosechas para una finca inactiva."})

    if productor_id is not None:
        if str(finca.productor_id) != str(productor_id):
            raise ValidationError({"finca": "No tiene permisos para registrar cosechas en una finca ajena."})

    variedad = None
    if variedad_id:
        try:
            variedad = VariedadCafe.objects.get(pk=variedad_id)
        except VariedadCafe.DoesNotExist:
            raise ValidationError({"variedad": "La variedad de café indicada no existe en el catálogo."})

        if not variedad.activo:
            raise ValidationError({"variedad": "La variedad de café seleccionada se encuentra inactiva en el catálogo."})

    if not fecha_cosecha:
        raise ValidationError({"fecha_cosecha": "La fecha de la cosecha es obligatoria."})

    if cantidad_total is None:
        raise ValidationError({"cantidad_total": "La cantidad total cosechada es obligatoria."})

    try:
        cantidad_total = Decimal(str(cantidad_total))
    except Exception:
        raise ValidationError({"cantidad_total": "La cantidad total cosechada debe ser un valor numérico."})

    if cantidad_total <= Decimal("0.00"):
        raise ValidationError({"cantidad_total": "La cantidad total debe ser mayor a cero."})

    with transaction.atomic():
        cosecha = Cosecha(
            finca=finca,
            variedad=variedad,
            fecha_cosecha=fecha_cosecha,
            cantidad_total=cantidad_total,
            cantidad_disponible=cantidad_total,
            activo=True,
        )
        cosecha.full_clean()
        cosecha.save()

    return cosecha


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
