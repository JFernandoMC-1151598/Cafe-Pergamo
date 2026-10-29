"""
Servicios de dominio para el módulo de Fincas y Catálogos - CAFÉ PÉRGAMO
Subtarea: SCRUM-112 / HU09-ST3: Implementar servicios y API para crear municipios.
Subtarea: SCRUM-142 / HU13-ST2: Implementar lógica de negocio para registrar lotes.
Subtarea: SCRUM-145 / HU013-ST4: Validar cantidad disponible antes de crear el lote.
Subtarea: SCRUM-146 / HU013-ST5: Actualizar trazabilidad de la cosecha al crear lotes.
Subtarea: SCRUM-155 / HU15-ST1: Implementar persistencia de características
físicas y de calidad del lote.
Subtarea: SCRUM-248 / HU20-ST4: Definir criterios y reglas de filtrado del catálogo.
Subtarea: SCRUM-249 / HU20-ST5: Implementar consulta de filtrado para lotes disponibles.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    BitacoraFichaDigital,
    BitacoraPublicacionLote,
    CaracteristicasCalidad,
    Cosecha,
    EtapaBeneficio,
    Finca,
    Lote,
    Municipio,
)
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


def evaluar_consistencia_y_completitud_lote(
    *,
    lote: Lote,
    finca: Finca,
    cosecha: Cosecha,
    proceso: Optional[ProcesoBeneficio] = None,
    etapas_beneficio: Optional[List[Dict[str, Any]]] = None,
    calidad_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evalúa la completitud y valida la consistencia de los datos del lote
    para la ficha digital consolidada (HU-17 / ST6 - SCRUM-171).

    Reglas de Completitud (Ponderación 100%):
      - 40%: Identificación base (Finca, Productor, Cosecha y Lote)
      - 10%: Georreferenciación WGS84 válida
      - 15%: Proceso de beneficio asignado
      - 15%: Etapas de beneficio registradas (HU-14)
      - 20%: Análisis de calidad física y sensorial SCA (HU-15)

    Reglas de Consistencia (Validación de Integridad y Alertas):
      - Cantidad disponible de cosecha no debe superar la cantidad total.
      - Cantidad de lote debe ser mayor a cero.
      - Coordenadas geográficas dentro del rango válido de Colombia (-4.5 a 13.5 Lat, -79.0 a -66.5 Lng).
      - Fecha de cosecha no debe ser una fecha futura.
      - Porcentaje de humedad en café dentro del rango estándar técnico (10% - 12%).
    """
    etapas = etapas_beneficio or []
    campos_faltantes: List[str] = []
    campos_completos: List[str] = ["Identificación de Finca y Productor", "Registro de Lote y Cosecha"]
    advertencias: List[str] = []

    # 1. Ponderación de Completitud Progresiva
    porcentaje = 40  # Base mínima

    if finca.tiene_georreferenciacion:
        porcentaje += 10
        campos_completos.append("Georreferenciación WGS84")
    else:
        campos_faltantes.append("Coordenadas GPS (WGS84) del predio")

    if proceso is not None:
        porcentaje += 15
        campos_completos.append(f"Proceso de Beneficio ({proceso.nombre})")
    else:
        campos_faltantes.append("Asignación de proceso de beneficio (Lavado, Honey, Natural)")

    if etapas:
        porcentaje += 15
        campos_completos.append(f"Etapas de Beneficio ({len(etapas)} registradas)")
    else:
        campos_faltantes.append("Registro de etapas operativas de beneficio (fermentación, secado)")

    if calidad_info is not None:
        porcentaje += 20
        campos_completos.append("Análisis de Calidad y Catación SCA")
    else:
        campos_faltantes.append("Análisis físico y sensorial de calidad SCA")

    porcentaje = min(max(porcentaje, 0), 100)

    # 2. Asignación de Nivel y Color de Semáforo
    if porcentaje < 50:
        nivel = "Básica"
        color_nivel = "secondary"
    elif porcentaje < 80:
        nivel = "Media"
        color_nivel = "warning"
    elif porcentaje < 100:
        nivel = "Avanzada"
        color_nivel = "info"
    else:
        nivel = "Completa"
        color_nivel = "success"

    # 3. Validación de Consistencia Lógica
    if cosecha.cantidad_disponible is not None and cosecha.cantidad_total is not None:
        if cosecha.cantidad_disponible > cosecha.cantidad_total:
            advertencias.append(
                f"La cantidad disponible ({cosecha.cantidad_disponible} kg) supera la cantidad total recolectada ({cosecha.cantidad_total} kg)."
            )

    if lote.cantidad is not None and lote.cantidad <= 0:
        advertencias.append(f"El volumen del lote ({lote.cantidad} kg) debe ser mayor a cero.")

    if finca.latitud is not None or finca.longitud is not None:
        lat = float(finca.latitud) if finca.latitud is not None else None
        lng = float(finca.longitud) if finca.longitud is not None else None
        if lat is not None and not (-4.5 <= lat <= 13.5):
            advertencias.append(f"La latitud registrada ({lat}) se encuentra fuera del territorio colombiano (-4.5 a 13.5).")
        if lng is not None and not (-79.0 <= lng <= -66.5):
            advertencias.append(f"La longitud registrada ({lng}) se encuentra fuera del territorio colombiano (-79.0 a -66.5).")

    if cosecha.fecha_cosecha:
        hoy = date.today()
        fecha_cos = None
        if isinstance(cosecha.fecha_cosecha, date):
            fecha_cos = cosecha.fecha_cosecha
        elif isinstance(cosecha.fecha_cosecha, str):
            try:
                fecha_cos = date.fromisoformat(cosecha.fecha_cosecha[:10])
            except (ValueError, TypeError):
                pass
        elif hasattr(cosecha.fecha_cosecha, "date"):
            fecha_cos = cosecha.fecha_cosecha.date()

        if fecha_cos and fecha_cos > hoy:
            advertencias.append(f"La fecha de cosecha ({fecha_cos}) es posterior a la fecha actual del sistema.")

    if calidad_info and calidad_info.get("humedad_pct") is not None:
        try:
            humedad = float(calidad_info["humedad_pct"])
            if humedad < 9.0 or humedad > 13.0:
                advertencias.append(f"El porcentaje de humedad ({humedad}%) se sale del estándar técnico óptimo (10% - 12%).")
        except (ValueError, TypeError):
            pass

    es_consistente = (len(advertencias) == 0)

    return {
        "porcentaje": porcentaje,
        "nivel": nivel,
        "color_nivel": color_nivel,
        "es_consistente": es_consistente,
        "advertencias": advertencias,
        "campos_completos": campos_completos,
        "campos_faltantes": campos_faltantes,
    }


def obtener_ficha_consolidada_lote(lote_identificador: Union[Lote, int, str]) -> Dict[str, Any]:
    """
    Servicio de dominio para consolidar toda la información de trazabilidad de un lote
    (HU-17 / SCRUM-169, SCRUM-170 y SCRUM-171).
    """
    if isinstance(lote_identificador, Lote):
        lote = lote_identificador
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

    # 8. Características físicas y sensoriales de HU-15
    calidad_info = None
    try:
        c = lote.caracteristicas_calidad
    except CaracteristicasCalidad.DoesNotExist:
        c = None
    if c:
        calidad_info = {
            "humedad": c.humedad,
            "merma": c.merma,
            "puntaje_taza": c.puntaje_taza,
            "perfil_sensorial": c.perfil_sensorial,
            "observaciones": c.observaciones,
            # Aliases conservados para consumidores anteriores de la ficha.
            "humedad_pct": c.humedad,
            "puntaje_sca": c.puntaje_taza,
            "perfil_taza": c.perfil_sensorial,
        }

    # 9. Evaluación de Consistencia y Completitud (HU-17 / ST6 - SCRUM-171)
    evaluacion = evaluar_consistencia_y_completitud_lote(
        lote=lote,
        finca=finca,
        cosecha=cosecha,
        proceso=proceso,
        etapas_beneficio=etapas_beneficio,
        calidad_info=calidad_info,
    )

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
        "completitud_porcentaje": evaluacion["porcentaje"],
        "nivel_completitud": evaluacion["nivel"],
        "color_nivel": evaluacion["color_nivel"],
        "es_consistente": evaluacion["es_consistente"],
        "advertencias": evaluacion["advertencias"],
        "campos_completos": evaluacion["campos_completos"],
        "campos_faltantes": evaluacion["campos_faltantes"],
    }


def registrar_auditoria_ficha_digital(
    *,
    lote: Lote,
    tipo_evento: str,
    request: Optional[Any] = None,
    completitud_porcentaje: Optional[int] = None,
    es_consistente: bool = True,
    detalles: Optional[Dict[str, Any]] = None,
    usuario_identificador: Optional[str] = None,
) -> BitacoraFichaDigital:
    """
    Registra una entrada inmutable de auditoría para la ficha digital de un lote
    (HU-17 / ST7 - SCRUM-172).

    Captura de forma segura:
      - Tipo de evento (CONSULTA_WEB, CONSULTA_API, ACTUALIZACION).
      - Identificador del actor (usuario logueado o 'Público / Escaneo QR').
      - Dirección IP y User-Agent.
      - Porcentaje de completitud y estado de consistencia en el momento de la consulta.
      - Detalles adicionales contextuales (JSON).
    """
    ip_address = None
    user_agent = None
    actor = usuario_identificador

    if request:
        # Extraer IP remota respetando proxies reversos
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.META.get("REMOTE_ADDR") or None

        # Extraer User-Agent
        ua = request.META.get("HTTP_USER_AGENT", "")
        user_agent = ua[:255] if ua else None

        # Resolver actor si no se pasó explícito
        if not actor:
            user = getattr(request, "user", None)
            if user and getattr(user, "is_authenticated", False):
                actor = getattr(user, "email", "") or getattr(user, "username", "") or str(user.pk)
            elif hasattr(request, "session") and request.session.get("usuario_id"):
                actor = f"Usuario Sesión {request.session.get('usuario_id')}"
            else:
                actor = "Público / Escaneo QR"

    if not actor:
        actor = "Sistema / Automático"

    return BitacoraFichaDigital.objects.create(
        lote=lote,
        tipo_evento=tipo_evento,
        completitud_porcentaje=completitud_porcentaje or 0,
        es_consistente=es_consistente,
        ip_address=ip_address,
        user_agent=user_agent,
        usuario_identificador=actor,
        detalles=detalles or {},
    )


def validar_lote_para_publicacion(lote: Lote) -> tuple[bool, list[str]]:
    """
    Evalúa si un lote cumple con la información mínima requerida para ser
    publicado en el catálogo público comercial (HU-19 / SCRUM-241).

    Criterios de Aceptación (DoD):
    1. Solo se publican lotes con información mínima completa.
    2. La información mínima requerida incluye trazabilidad y calidad:
       - Lote activo y con cantidad mayor a 0 kg.
       - Cosecha asociada activa.
       - Finca asociada activa con municipio asignado (trazabilidad de origen).
       - Variedad de café asignada a la cosecha.
       - Proceso de beneficio asignado al lote (Lavado, Honey, Natural, etc.).
       - Registro de características de calidad asociado, con al menos puntaje
         en taza (SCA) o porcentaje de humedad reportado.

    Retorna:
        tuple[bool, list[str]]: (es_valido, lista_de_mensajes_de_error).
    """
    errores: list[str] = []

    if not lote.activo:
        errores.append("El lote se encuentra inactivo y no puede ser publicado en el catálogo.")

    if lote.cantidad is None or lote.cantidad <= Decimal("0.00"):
        errores.append("El lote debe tener una cantidad disponible mayor a cero (0 kg).")

    cosecha = getattr(lote, "cosecha", None)
    if not cosecha:
        errores.append("El lote debe tener una cosecha asociada para garantizar su trazabilidad.")
    else:
        if not cosecha.activo:
            errores.append("La cosecha asociada al lote se encuentra inactiva.")

        if not cosecha.variedad:
            errores.append("La cosecha debe tener una variedad de café asignada para trazabilidad.")

        finca = getattr(cosecha, "finca", None)
        if not finca:
            errores.append("La cosecha debe estar vinculada a una finca registrada.")
        else:
            if not finca.activo:
                errores.append("La finca de origen se encuentra inactiva.")

            municipio = None
            try:
                municipio = finca.municipio
            except ObjectDoesNotExist:
                municipio = None

            if not municipio:
                errores.append("La finca debe tener un municipio registrado para su georreferenciación en el catálogo.")

    if not lote.proceso_beneficio:
        errores.append("El lote debe tener asignado un proceso de beneficio (Lavado, Natural, Honey, etc.).")

    # Validación de calidad (HU-15)
    calidad = getattr(lote, "caracteristicas_calidad", None)
    if not calidad:
        errores.append("El lote debe contar con registro de características físicas y de calidad antes de publicarse.")
    else:
        tiene_puntaje = calidad.puntaje_taza is not None
        tiene_humedad = calidad.humedad is not None
        if not (tiene_puntaje or tiene_humedad):
            errores.append(
                "La evaluación de calidad debe incluir al menos el puntaje en taza o el porcentaje de humedad."
            )

    return (len(errores) == 0, errores)


def generar_snapshot_trazabilidad(lote: Lote) -> dict:
    """
    Construye una instantánea (snapshot) estructurada de la trazabilidad completa
    y calidad del lote al momento de su publicación (HU19-ST6 / SCRUM-244).
    Este JSON se almacena inmutablemente en la BitacoraPublicacionLote.
    """
    cosecha = getattr(lote, "cosecha", None)
    finca = getattr(cosecha, "finca", None) if cosecha else None
    municipio = None
    if finca:
        try:
            municipio = finca.municipio
        except ObjectDoesNotExist:
            municipio = None
    variedad = getattr(cosecha, "variedad", None) if cosecha else None
    proceso = getattr(lote, "proceso_beneficio", None)
    calidad = getattr(lote, "caracteristicas_calidad", None)

    return {
        "lote": {
            "id": lote.id,
            "codigo": lote.codigo,
            "cantidad_kg": float(lote.cantidad) if lote.cantidad is not None else 0.0,
            "precio_referencial": (
                float(lote.precio_referencial) if lote.precio_referencial is not None else None
            ),
            "publicado_en_catalogo": lote.publicado_en_catalogo,
            "fecha_publicacion": (
                lote.fecha_publicacion.isoformat() if lote.fecha_publicacion else None
            ),
        },
        "finca": {
            "id": finca.id if finca else None,
            "nombre": finca.nombre if finca else "",
            "vereda": (finca.vereda or "") if finca else "",
            "municipio": municipio.nombre if municipio else "",
            "departamento": municipio.departamento if municipio else "",
            "latitud": str(finca.latitud) if finca and finca.latitud is not None else None,
            "longitud": str(finca.longitud) if finca and finca.longitud is not None else None,
        },
        "cosecha": {
            "id": cosecha.id if cosecha else None,
            "fecha_cosecha": str(cosecha.fecha_cosecha) if cosecha and cosecha.fecha_cosecha else "",
            "variedad": variedad.nombre if variedad else "",
        },
        "proceso_beneficio": proceso.nombre if proceso else "",
        "calidad": {
            "puntaje_taza": (
                float(calidad.puntaje_taza) if calidad and calidad.puntaje_taza is not None else None
            ),
            "humedad": (
                float(calidad.humedad) if calidad and calidad.humedad is not None else None
            ),
            "merma": (
                float(calidad.merma) if calidad and calidad.merma is not None else None
            ),
            "perfil_sensorial": calidad.perfil_sensorial if calidad else "",
            "observaciones": calidad.observaciones if calidad else "",
        },
    }


def publicar_lote_en_catalogo(
    *,
    lote_id: int,
    productor_id: Optional[str] = None,
    precio_referencial: Optional[Decimal] = None,
    realizado_por_id: Optional[str] = None,
    realizado_por_correo: Optional[str] = None,
    observaciones: str = "",
) -> Lote:
    """
    Aplica las reglas de negocio para publicar un lote en el catálogo
    público comercial (HU-19 / SCRUM-240 / SCRUM-243 / SCRUM-244).

    Validaciones:
    - Existencia del lote.
    - Pertenencia al productor autenticado (aislamiento entre productores).
    - Validación completa de información mínima (trazabilidad y calidad).
    - Validación de precio referencial si es suministrado (> 0).

    Acciones atómicas:
    - Actualiza `publicado_en_catalogo = True`.
    - Asigna `fecha_publicacion = now()`.
    - Actualiza `precio_referencial` si se indicó.
    - Registra el evento en `BitacoraPublicacionLote` con snapshot de trazabilidad.
    """
    try:
        lote = (
            Lote.objects.select_related(
                "cosecha__finca__municipio",
                "cosecha__variedad",
                "proceso_beneficio",
                "caracteristicas_calidad",
            )
            .get(pk=lote_id)
        )
    except Lote.DoesNotExist:
        raise ValidationError({"lote": "El lote especificado no existe."})

    # Aislamiento entre productores
    if productor_id is not None:
        finca = getattr(getattr(lote, "cosecha", None), "finca", None)
        if not finca or str(finca.productor_id) != str(productor_id):
            raise ValidationError(
                {"permiso": "No tiene permisos para publicar este lote porque no pertenece a sus fincas."}
            )

    # Validación de precio referencial opcional
    if precio_referencial is not None:
        try:
            precio_dec = Decimal(str(precio_referencial))
            if precio_dec <= Decimal("0.00"):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(
                {"precio_referencial": "El precio referencial debe ser un monto mayor a 0."}
            )
    else:
        precio_dec = None

    # Regla de negocio: información mínima requerida (DoD 1 y 2)
    es_valido, errores = validar_lote_para_publicacion(lote)
    if not es_valido:
        raise ValidationError({"publicacion": errores})

    with transaction.atomic():
        lote.publicado_en_catalogo = True
        lote.fecha_publicacion = timezone.now()
        if precio_dec is not None:
            lote.precio_referencial = precio_dec

        update_fields = ["publicado_en_catalogo", "fecha_publicacion"]
        if precio_dec is not None:
            update_fields.append("precio_referencial")
        lote.save(update_fields=update_fields)

        snapshot = generar_snapshot_trazabilidad(lote)
        BitacoraPublicacionLote.objects.create(
            lote=lote,
            accion="PUBLICAR",
            realizado_por_id=str(realizado_por_id) if realizado_por_id else None,
            realizado_por_correo=str(realizado_por_correo) if realizado_por_correo else None,
            detalles_trazabilidad=snapshot,
            observaciones=str(observaciones).strip(),
        )

    return lote


def despublicar_lote_de_catalogo(
    *,
    lote_id: int,
    productor_id: Optional[str] = None,
    realizado_por_id: Optional[str] = None,
    realizado_por_correo: Optional[str] = None,
    motivo: str = "",
) -> Lote:
    """
    Retira un lote del catálogo público comercial (HU-19 / SCRUM-243 / SCRUM-244).
    Cambia `publicado_en_catalogo` a False y genera la traza en la bitácora.
    """
    try:
        lote = (
            Lote.objects.select_related(
                "cosecha__finca__municipio",
                "cosecha__variedad",
                "proceso_beneficio",
                "caracteristicas_calidad",
            )
            .get(pk=lote_id)
        )
    except Lote.DoesNotExist:
        raise ValidationError({"lote": "El lote especificado no existe."})

    if productor_id is not None:
        finca = getattr(getattr(lote, "cosecha", None), "finca", None)
        if not finca or str(finca.productor_id) != str(productor_id):
            raise ValidationError(
                {"permiso": "No tiene permisos para modificar este lote porque no pertenece a sus fincas."}
            )

    if not lote.publicado_en_catalogo:
        raise ValidationError({"publicacion": "El lote ya se encuentra fuera del catálogo público."})

    with transaction.atomic():
        lote.publicado_en_catalogo = False
        lote.save(update_fields=["publicado_en_catalogo"])

        snapshot = generar_snapshot_trazabilidad(lote)
        BitacoraPublicacionLote.objects.create(
            lote=lote,
            accion="DESPUBLICAR",
            realizado_por_id=str(realizado_por_id) if realizado_por_id else None,
            realizado_por_correo=str(realizado_por_correo) if realizado_por_correo else None,
            detalles_trazabilidad=snapshot,
            observaciones=str(motivo).strip(),
        )

    return lote


# ==============================================================================
# HU-20 (SCRUM-229): FILTRADO DEL CATÁLOGO COMERCIAL
# ==============================================================================

# SCRUM-248 / HU20-ST4: Opciones de calidad mínima ofrecidas en la interfaz
# (escala SCA). 80+ es el umbral convencional de "café de especialidad".
OPCIONES_PUNTAJE_MINIMO_CATALOGO = (80, 84, 86, 88)

# Parámetros GET aceptados por la vista web y la API del catálogo.
PARAMETROS_FILTRO_CATALOGO = ("municipio", "variedad", "proceso", "puntaje_min", "q")


def lotes_disponibles_en_catalogo():
    """
    Queryset base de lotes "disponibles" en el catálogo público
    (SCRUM-248 / HU20-ST4). El criterio de aceptación de la HU-20 exige que
    los filtros devuelvan *solo lotes disponibles*, así que cualquier filtro
    se aplica SIEMPRE encima de esta base, nunca sobre `Lote.objects.all()`:

    - Publicado en el catálogo (HU-19) y lote activo.
    - Cantidad mayor a 0 kg.
    - Cosecha y finca de origen activas (un lote publicado cuya finca se
      inactivó después no debe seguir ofreciéndose).
    """
    return (
        Lote.objects.filter(
            publicado_en_catalogo=True,
            activo=True,
            cantidad__gt=Decimal("0.00"),
            cosecha__activo=True,
            cosecha__finca__activo=True,
        )
        .select_related(
            "cosecha__finca__municipio",
            "cosecha__variedad",
            "proceso_beneficio",
            "caracteristicas_calidad",
        )
        .order_by("-fecha_publicacion", "-creado_en")
    )


def _normalizar_id_filtro(valor, campo: str, errores: dict) -> Optional[int]:
    """Convierte un id de filtro a entero positivo; registra el error si no es válido."""
    if valor is None or str(valor).strip() == "":
        return None
    try:
        valor_int = int(str(valor).strip())
    except (TypeError, ValueError):
        errores[campo] = f"El filtro '{campo}' debe ser un identificador numérico válido."
        return None
    if valor_int <= 0:
        errores[campo] = f"El filtro '{campo}' debe ser un identificador numérico válido."
        return None
    return valor_int


def normalizar_filtros_catalogo(parametros) -> tuple[dict, dict]:
    """
    Valida y normaliza los parámetros de filtro del catálogo
    (SCRUM-248 / HU20-ST4). Acepta un `QueryDict` (request.GET) o un dict.

    Reglas:
    - `municipio`, `variedad`, `proceso`: id numérico positivo.
    - `puntaje_min`: decimal entre 0 y 100 (escala SCA de puntaje en taza).
    - `q`: texto libre, se recorta y se limita a 100 caracteres.
    - Valores vacíos se ignoran (equivalen a "sin filtro").

    Retorna:
        (filtros_validos, errores): los filtros válidos se pueden aplicar
        aunque otros parámetros vengan mal; la vista decide si muestra una
        advertencia (web) o responde 400 (API).
    """
    parametros = parametros or {}
    errores: dict = {}
    filtros: dict = {}

    for campo in ("municipio", "variedad", "proceso"):
        valor = _normalizar_id_filtro(parametros.get(campo), campo, errores)
        if valor is not None:
            filtros[campo] = valor

    puntaje_raw = parametros.get("puntaje_min")
    if puntaje_raw is not None and str(puntaje_raw).strip() != "":
        try:
            puntaje = Decimal(str(puntaje_raw).strip())
            if not puntaje.is_finite():
                raise ValueError()
        except (ArithmeticError, TypeError, ValueError):
            errores["puntaje_min"] = "El puntaje mínimo de calidad debe ser un número."
        else:
            if puntaje < Decimal("0") or puntaje > Decimal("100"):
                errores["puntaje_min"] = "El puntaje mínimo de calidad debe estar entre 0 y 100."
            else:
                filtros["puntaje_min"] = puntaje

    q = str(parametros.get("q") or "").strip()[:100]
    if q:
        filtros["q"] = q

    return filtros, errores


def filtrar_catalogo_lotes(
    *,
    municipio: Optional[int] = None,
    variedad: Optional[int] = None,
    proceso: Optional[int] = None,
    puntaje_min: Optional[Decimal] = None,
    q: Optional[str] = None,
):
    """
    Consulta filtrada de lotes disponibles en el catálogo
    (SCRUM-249 / HU20-ST5, SCRUM-251 / HU20-ST6).

    Filtros combinados: cada criterio indicado se suma con AND sobre la base
    de `lotes_disponibles_en_catalogo()`, de modo que el resultado solo
    contiene lotes disponibles que cumplen TODOS los criterios a la vez.
    Un criterio en None/vacío no restringe nada.

    - puntaje_min: exige evaluación de calidad con puntaje en taza >= valor.
      Los lotes publicados solo con humedad (sin puntaje) quedan fuera
      cuando se filtra por calidad, porque no se puede afirmar que lo cumplan.
    - q: búsqueda de texto en código del lote, finca, vereda, municipio y
      perfil sensorial.
    """
    lotes = lotes_disponibles_en_catalogo()

    if municipio:
        lotes = lotes.filter(cosecha__finca__municipio_id=municipio)
    if variedad:
        lotes = lotes.filter(cosecha__variedad_id=variedad)
    if proceso:
        lotes = lotes.filter(proceso_beneficio_id=proceso)
    if puntaje_min is not None:
        lotes = lotes.filter(caracteristicas_calidad__puntaje_taza__gte=puntaje_min)
    if q:
        lotes = lotes.filter(
            Q(codigo__icontains=q)
            | Q(cosecha__finca__nombre__icontains=q)
            | Q(cosecha__finca__vereda__icontains=q)
            | Q(cosecha__finca__municipio__nombre__icontains=q)
            | Q(caracteristicas_calidad__perfil_sensorial__icontains=q)
        )

    return lotes


def obtener_opciones_filtro_catalogo() -> dict:
    """
    Opciones para los controles de filtro de la interfaz (SCRUM-246 / HU20-ST1).

    Solo se ofrecen municipios, variedades y procesos que tienen al menos un
    lote disponible en el catálogo: así el comprador nunca elige una opción
    que por construcción devolvería cero resultados.
    """
    base = lotes_disponibles_en_catalogo()
    return {
        "municipios": Municipio.objects.filter(
            pk__in=base.values("cosecha__finca__municipio_id")
        ).order_by("nombre"),
        "variedades": VariedadCafe.objects.filter(
            pk__in=base.values("cosecha__variedad_id")
        ).order_by("nombre"),
        "procesos": ProcesoBeneficio.objects.filter(
            pk__in=base.values("proceso_beneficio_id")
        ).order_by("orden", "nombre"),
        "puntajes_minimos": OPCIONES_PUNTAJE_MINIMO_CATALOGO,
    }


# ==============================================================================
# ETAPAS DE BENEFICIO DEL LOTE (HU-14 / SCRUM-18)
# ==============================================================================

def registrar_etapa_beneficio(
    *,
    lote_o_id,
    etapa,
    fecha,
    observaciones="",
    productor_id=None,
) -> EtapaBeneficio:
    """
    Registra una etapa de beneficio sobre un lote (HU14-ST4 / SCRUM-150).

    - Valida SIEMPRE en backend (RNF-09), sin depender del formulario: fecha
      obligatoria, etapa de la lista válida y observaciones consistentes
      (reglas de HU14-ST3, definidas en el modelo `EtapaBeneficio`).
    - Operación atómica: si algo falla no queda información parcial.
    - Si se indica `productor_id`, el lote debe pertenecer a una finca de
      ese productor.
    - Solo permite lotes activos. La etapa nunca se elimina físicamente
      (RNF-14): queda disponible de inmediato en el historial del lote.

    Lanza `ValidationError` con errores por campo (`etapa`, `fecha`,
    `observaciones`) o `lote` / `permiso` para errores de contexto.
    """
    with transaction.atomic():
        lote = _resolver_lote(lote_o_id)

        if productor_id is not None and str(lote.cosecha.finca.productor_id) != str(productor_id):
            raise ValidationError({"permiso": "No tiene permiso para registrar etapas en este lote."})

        if not lote.activo:
            raise ValidationError({"lote": "No se pueden registrar etapas en un lote inactivo."})

        nueva = EtapaBeneficio(
            lote=lote,
            etapa=etapa,
            fecha=fecha,
            observaciones=observaciones or "",
        )
        nueva.full_clean(exclude=["activo"])
        nueva.save()
        return nueva
