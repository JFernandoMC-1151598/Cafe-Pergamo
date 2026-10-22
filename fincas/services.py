"""
Servicios de dominio para el módulo de Fincas y Catálogos - CAFÉ PÉRGAMO
Subtarea: SCRUM-112 / HU09-ST3: Implementar servicios y API para crear municipios.
Subtarea: SCRUM-142 / HU13-ST2: Implementar lógica de negocio para registrar lotes.
Subtarea: SCRUM-145 / HU013-ST4: Validar cantidad disponible antes de crear el lote.
Subtarea: SCRUM-146 / HU013-ST5: Actualizar trazabilidad de la cosecha al crear lotes.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Cosecha, Finca, Lote, Municipio
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


# =============================================================================
# SERVICIO DE CONSOLIDACIÓN DE FICHA DIGITAL POR LOTE (HU-17 / SCRUM-170 / SCRUM-169)
# =============================================================================

def obtener_ficha_consolidada_lote(lote_identificador: Union[Lote, int, str]) -> Dict[str, Any]:
    """
    Consolida en tiempo real toda la trazabilidad y datos de origen de un Lote de café.
    (HU-17 / SCRUM-169 y SCRUM-170).

    Criterio de aceptación:
    La ficha se genera y actualiza automáticamente al consultar la base de datos relacional,
    garantizando que cualquier mutación previa (en finca, cosecha, estado o beneficio)
    se refleje al instante.

    Parámetros:
    - lote_identificador: Instancia de Lote, id numérico (PK) o código alfanumérico (ej: 'LOTE-001').

    Retorna:
    - Diccionario con la estructura requerida por `FichaDigitalSerializer`.
    """
    if isinstance(lote_identificador, Lote):
        lote = lote_identificador
        # Si no están cargadas las relaciones, aseguramos la consulta optimizada
        if not hasattr(lote, "_cosecha_cache"):
            lote = (
                Lote.objects.select_related(
                    "cosecha__finca__municipio",
                    "cosecha__variedad",
                    "proceso_beneficio",
                    "estado_lote",
                ).get(pk=lote.pk)
            )
    elif isinstance(lote_identificador, int) or (isinstance(lote_identificador, str) and lote_identificador.isdigit()):
        try:
            lote = (
                Lote.objects.select_related(
                    "cosecha__finca__municipio",
                    "cosecha__variedad",
                    "proceso_beneficio",
                    "estado_lote",
                ).get(pk=int(lote_identificador))
            )
        except Lote.DoesNotExist:
            raise ValidationError({"lote": f"No se encontró ningún lote con el ID '{lote_identificador}'."})
    elif isinstance(lote_identificador, str):
        codigo_limpio = lote_identificador.strip().upper()
        try:
            lote = (
                Lote.objects.select_related(
                    "cosecha__finca__municipio",
                    "cosecha__variedad",
                    "proceso_beneficio",
                    "estado_lote",
                ).get(codigo__iexact=codigo_limpio)
            )
        except Lote.DoesNotExist:
            raise ValidationError({"lote": f"No se encontró ningún lote con el código '{codigo_limpio}'."})
    else:
        raise ValidationError({"lote": "Identificador de lote no válido."})

    cosecha = lote.cosecha
    finca = cosecha.finca
    municipio = finca.municipio
    variedad = cosecha.variedad
    proceso = lote.proceso_beneficio
    estado = lote.estado_lote

    # 1. Extracción segura del Productor
    productor_info = {
        "id": str(finca.productor_id) if finca.productor_id else None,
        "nombre_completo": "Productor de Café",
        "correo": None,
        "telefono": None,
        "tipo_documento": None,
        "numero_documento": None,
    }
    try:
        p = finca.productor
        if p:
            nombres = getattr(p, "nombres", "") or ""
            apellidos = getattr(p, "apellidos", "") or ""
            nombre_str = f"{nombres} {apellidos}".strip()
            productor_info["nombre_completo"] = nombre_str or getattr(p, "correo", "Productor Registrado")
            productor_info["correo"] = getattr(p, "correo", None)
            productor_info["telefono"] = getattr(p, "telefono", None)
            productor_info["numero_documento"] = getattr(p, "numero_documento", None)
            tipo_doc = getattr(p, "tipo_documento", None)
            productor_info["tipo_documento"] = getattr(tipo_doc, "codigo", None) if tipo_doc else None
    except Exception:
        # En caso de entornos de prueba donde el modelo Usuario (managed=False) no esté presente en la BD local
        pass

    # 2. Extracción de Finca y Georreferenciación
    finca_info = {
        "id": finca.id,
        "nombre": finca.nombre,
        "vereda": finca.vereda or "",
        "municipio": municipio.nombre if municipio else "No asignado",
        "departamento": municipio.departamento if municipio else "Norte de Santander",
        "latitud": finca.latitud,
        "longitud": finca.longitud,
        "tiene_georreferenciacion": finca.tiene_georreferenciacion,
    }

    # 3. Extracción de Cosecha
    cosecha_info = {
        "id": cosecha.id,
        "fecha_cosecha": cosecha.fecha_cosecha,
        "cantidad_total_cosecha": cosecha.cantidad_total,
        "cantidad_disponible_cosecha": cosecha.cantidad_disponible,
    }

    # 4. Extracción de Variedad Botánica
    variedad_info = {
        "id": variedad.id if variedad else None,
        "nombre": variedad.nombre if variedad else "Mezcla tradicional / No especificada",
        "especie": variedad.especie if variedad else "Arábica",
        "descripcion": variedad.descripcion if variedad else "",
    }

    # 5. Extracción de Proceso de Beneficio
    proceso_info = {
        "id": proceso.id if proceso else None,
        "codigo": proceso.codigo if proceso else None,
        "nombre": proceso.nombre if proceso else "Sin proceso asignado",
        "descripcion": proceso.descripcion if proceso else "",
    }

    # 6. Extracción de Estado del Lote
    estado_info = {
        "id": estado.id if estado else None,
        "codigo": estado.codigo if estado else "REGISTRADO",
        "nombre": estado.nombre if estado else "Registrado",
        "descripcion": estado.descripcion if estado else "",
    }

    # 7. Módulo extensible para HU-14 (Etapas de Beneficio - David Torres)
    etapas_beneficio: List[Dict[str, Any]] = []
    if hasattr(lote, "etapas") and hasattr(lote.etapas, "all"):
        for etapa in lote.etapas.all():
            etapas_beneficio.append({
                "id": getattr(etapa, "id", None),
                "etapa": getattr(etapa, "nombre", str(etapa)),
                "fecha_inicio": getattr(etapa, "fecha_inicio", None),
                "fecha_fin": getattr(etapa, "fecha_fin", None),
                "duracion_horas": getattr(etapa, "duracion_horas", None),
                "temperatura": getattr(etapa, "temperatura", None),
            })

    # 8. Módulo extensible para HU-15 (Calidad Sensorial y Física - Alessandro Reyes)
    calidad_info = None
    if hasattr(lote, "calidad") and getattr(lote, "calidad", None):
        c = lote.calidad
        calidad_info = {
            "humedad_pct": getattr(c, "humedad_pct", None),
            "factor_rendimiento": getattr(c, "factor_rendimiento", None),
            "defectos_totales": getattr(c, "defectos_totales", None),
            "puntaje_sca": getattr(c, "puntaje_sca", None),
            "notas_cata": getattr(c, "notas_cata", None),
            "perfil_taza": getattr(c, "perfil_taza", None),
        }

    # 9. Cálculo de porcentaje de completitud de la trazabilidad
    completitud = 40  # Base: Finca + Cosecha + Lote
    if finca.tiene_georreferenciacion:
        completitud += 10
    if proceso is not None:
        completitud += 15
    if etapas_beneficio:
        completitud += 15
    if calidad_info is not None:
        completitud += 20
    completitud = min(completitud, 100)

    # 10. URL canónica de consulta pública (HU-18 / QR)
    url_publica = f"/trazabilidad/lote/{lote.codigo}/"

    # 11. Estado comercial (HU-16)
    codigo_estado = (estado.codigo.upper() if estado and estado.codigo else "DISPONIBLE")
    disponible_venta = lote.activo and (codigo_estado in ["DISPONIBLE", "EN_VENTA", "REGISTRADO"])

    return {
        "id": lote.id,
        "codigo": lote.codigo,
        "cantidad_kg": lote.cantidad,
        "activo": lote.activo,
        "creado_en": lote.creado_en,
        "productor": productor_info,
        "finca": finca_info,
        "cosecha": cosecha_info,
        "variedad": variedad_info,
        "proceso_beneficio": proceso_info,
        "estado_lote": estado_info,
        "etapas_beneficio": etapas_beneficio,
        "calidad": calidad_info,
        "estado_comercial": codigo_estado,
        "disponible_para_venta": disponible_venta,
        "url_publica": url_publica,
        "completitud_porcentaje": completitud,
    }
