"""
Motor de Búsqueda Global Unificada — CAFÉ PÉRGAMO
Épica E6 / Sprint 4
Historia de Usuario: HU-29 (SCRUM-238): Realizar búsquedas globales de productores,
lotes, compradores y operaciones.

Subtareas implementadas en este módulo:
- SCRUM-294 (HU29-ST3): Crear la lógica de relevancia y normalización de resultados.
- SCRUM-292 (HU29-ST2): Agregar filtros o segmentación por tipo de entidad (Todas,
  Lotes, Productores, Compradores, Operaciones).
- SCRUM-296 (HU29-ST6): Validar permisos de visualización en resultados de búsqueda
  (aislamiento multi-tenant estricto y matriz RBAC).
- SCRUM-297 (HU29-ST7): Accesos directos contextuales según entidad y rol.
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import unicodedata

from django.db.models import Q, QuerySet
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from actores.models import ActorCadena
from fincas.models import Finca, Lote, ManifestacionInteres
from fincas.services import lotes_disponibles_en_catalogo
from usuarios.models import Rol, Usuario
from usuarios.permissions import usuario_tiene_permiso


# -----------------------------------------------------------------------------
# Constantes del Dominio de Búsqueda
# -----------------------------------------------------------------------------
ENTIDADES_VALIDAS = {"todas", "lotes", "productores", "compradores", "operaciones"}

MIN_CARACTERES_BUSQUEDA = 2


# -----------------------------------------------------------------------------
# Estructuras de Datos Normalizadas (HU29-ST3 / SCRUM-294)
# -----------------------------------------------------------------------------
@dataclass
class AccionAccesoDirecto:
    """Acceso directo contextual hacia un módulo o vista específica (HU29-ST7)."""
    etiqueta: str
    url: str
    icono: str = "bi-arrow-right-circle"
    clase_btn: str = "btn-outline-primary"
    tooltip: str = ""

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class ResultadoBusqueda:
    """Contrato canónico de resultado unificado para todas las entidades."""
    id: Any
    tipo_entidad: str                  # 'LOTE', 'PRODUCTOR', 'COMPRADOR', 'OPERACION'
    tipo_entidad_display: str          # 'Lote', 'Productor', 'Comprador', 'Operación'
    titulo: str
    subtitulo: str
    icono: str
    badge_clase: str
    badge_texto: str
    url_detalle: str
    relevancia: int = 50
    detalles: Dict[str, Any] = field(default_factory=dict)
    acciones: List[Dict[str, str]] = field(default_factory=list)
    fecha: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tipo_entidad": self.tipo_entidad,
            "tipo_entidad_display": self.tipo_entidad_display,
            "titulo": self.titulo,
            "subtitulo": self.subtitulo,
            "icono": self.icono,
            "badge_clase": self.badge_clase,
            "badge_texto": self.badge_texto,
            "url_detalle": self.url_detalle,
            "relevancia": self.relevancia,
            "detalles": self.detalles,
            "acciones": self.acciones,
            "fecha": self.fecha,
        }


# -----------------------------------------------------------------------------
# Utilidades de Normalización y Relevancia (HU29-ST3 / SCRUM-294)
# -----------------------------------------------------------------------------
def normalizar_termino_busqueda(termino: Optional[str]) -> str:
    """
    Limpia, recorta y normaliza el término de búsqueda ingresado por el usuario.
    Remueve espacios múltiples, saltos de línea y caracteres de control invisibles.
    """
    if not termino:
        return ""
    limpio = re.sub(r"\s+", " ", str(termino).strip())
    return limpio


def remover_diacriticos(texto: Optional[str]) -> str:
    """Elimina tildes y diacríticos manteniendo caracteres base para comparación."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def calcular_relevancia(
    termino: str,
    campo_clave: str,
    titulo: str,
    subtitulo: str = "",
    contenido_secundario: str = "",
) -> int:
    """
    Calcula una puntuación de 0 a 100 según la cercanía y exactitud del término.
    - Coincidencia exacta con código o identificador: 100
    - Código comienza con el término: 90
    - Título coincide exactamente: 85
    - Título comienza con el término: 75
    - Título contiene la palabra: 60
    - Subtítulo contiene la palabra: 40
    - Contenido secundario contiene la palabra: 20
    """
    t_norm = remover_diacriticos(termino)
    c_norm = remover_diacriticos(campo_clave)
    tit_norm = remover_diacriticos(titulo)
    sub_norm = remover_diacriticos(subtitulo)
    sec_norm = remover_diacriticos(contenido_secundario)

    if not t_norm:
        return 0

    if c_norm == t_norm:
        return 100
    if c_norm.startswith(t_norm):
        return 90
    if tit_norm == t_norm:
        return 85
    if tit_norm.startswith(t_norm):
        return 75
    if t_norm in tit_norm:
        return 60
    if sub_norm and t_norm in sub_norm:
        return 40
    if sec_norm and t_norm in sec_norm:
        return 25

    return 15


def resolver_usuario_y_rol(
    usuario_o_id: Any = None,
    rol_codigo: str = "",
) -> Tuple[Optional[Usuario], str]:
    """
    Resuelve la instancia del modelo de negocio Usuario y su rol activo.
    Acepta un Usuario, un User de Django (cuyo username es el UUID del perfil),
    un mock de perfil, un UUID string, o None.
    """
    usuario: Optional[Usuario] = None

    if isinstance(usuario_o_id, Usuario) or hasattr(usuario_o_id, "rol"):
        usuario = usuario_o_id
    elif usuario_o_id is not None:
        user_id_str = getattr(usuario_o_id, "username", None) or str(usuario_o_id)
        try:
            usuario = (
                Usuario.objects.select_related("rol", "tipo_documento")
                .filter(id=user_id_str)
                .first()
            )
        except Exception:
            usuario = None

    rol_final = (rol_codigo or "").strip().upper()
    if not rol_final and usuario and getattr(usuario, "rol", None):
        rol_final = getattr(usuario.rol, "codigo", "").upper()

    return usuario, rol_final


# -----------------------------------------------------------------------------
# Reglas de Acceso y Permisos RBAC (HU29-ST6 / SCRUM-296)
# -----------------------------------------------------------------------------
def obtener_entidades_permitidas(
    usuario: Optional[Usuario],
    rol_codigo: str,
) -> Set[str]:
    """
    Determina qué entidades puede buscar el usuario según su rol y permisos RBAC:
    - ADMINISTRADOR: Lotes, Productores, Compradores, Operaciones (total).
    - ASOCIACION: Lotes, Productores, Compradores, Operaciones.
    - PRODUCTOR: Lotes (propios + catálogo), Productores (directorio),
                 Compradores (con interés en sus lotes), Operaciones (sobre sus lotes).
    - COMPRADOR: Lotes (catálogo disponible), Productores (asociados al catálogo),
                 Compradores (su propio perfil), Operaciones (sus manifestaciones).
    - OPERARIO_CAMPO: Lotes (fincas asignadas + catálogo).
    - CONSULTA_PUBLICA / Anónimo: Lotes (catálogo público) y Productores (directorio público).
    """
    permitidas: Set[str] = set()

    if rol_codigo == "ADMINISTRADOR":
        return {"lotes", "productores", "compradores", "operaciones"}

    if rol_codigo == "ASOCIACION":
        return {"lotes", "productores", "compradores", "operaciones"}

    if rol_codigo == "PRODUCTOR":
        permitidas.add("lotes")
        permitidas.add("productores")
        permitidas.add("compradores")
        permitidas.add("operaciones")
        return permitidas

    if rol_codigo == "COMPRADOR":
        permitidas.add("lotes")
        permitidas.add("productores")
        permitidas.add("compradores")
        permitidas.add("operaciones")
        return permitidas

    if rol_codigo == "OPERARIO_CAMPO":
        permitidas.add("lotes")
        return permitidas

    # Público general / no autenticado / Consulta pública
    permitidas.add("lotes")
    permitidas.add("productores")
    return permitidas


# -----------------------------------------------------------------------------
# Motores de Búsqueda Especializados por Entidad (HU29-ST2 / SCRUM-292)
# -----------------------------------------------------------------------------

def buscar_lotes(
    termino: str,
    usuario: Optional[Usuario] = None,
    rol_codigo: str = "",
    limite: int = 25,
) -> List[ResultadoBusqueda]:
    """
    Búsqueda segmentada de lotes de café con aislamiento multi-tenant:
    - Administrador: consulta sobre todos los lotes del sistema.
    - Productor: sus propios lotes (publicados o no) + lotes disponibles en catálogo de otros.
    - Comprador / Público: exclusivamente lotes publicados y disponibles en catálogo.
    """
    if not termino or len(termino) < MIN_CARACTERES_BUSQUEDA:
        return []

    # 1. Definir Queryset Base según RBAC
    if rol_codigo == "ADMINISTRADOR":
        base_qs = Lote.objects.all()
    elif rol_codigo == "PRODUCTOR" and usuario:
        # Lotes propios O lotes publicados disponibles de otros
        filtro_propio = Q(cosecha__finca__productor_id=usuario.id)
        filtro_catalogo = Q(
            publicado_en_catalogo=True,
            activo=True,
            cantidad__gt=Decimal("0.00"),
            cosecha__activo=True,
            cosecha__finca__activo=True,
        )
        base_qs = Lote.objects.filter(filtro_propio | filtro_catalogo)
    elif rol_codigo == "ASOCIACION":
        base_qs = Lote.objects.filter(
            Q(activo=True) | Q(publicado_en_catalogo=True)
        )
    else:
        # Comprador, Operario o Visitante anónimo -> regla de oro del catálogo
        base_qs = lotes_disponibles_en_catalogo()

    base_qs = base_qs.select_related(
        "cosecha__finca__municipio",
        "cosecha__variedad",
        "proceso_beneficio",
        "caracteristicas_calidad",
    ).distinct()

    # 2. Cláusulas de Búsqueda Textual Multicampo
    q_filter = (
        Q(codigo__icontains=termino)
        | Q(cosecha__finca__nombre__icontains=termino)
        | Q(cosecha__finca__vereda__icontains=termino)
        | Q(cosecha__finca__municipio__nombre__icontains=termino)
        | Q(cosecha__variedad__nombre__icontains=termino)
        | Q(proceso_beneficio__nombre__icontains=termino)
        | Q(caracteristicas_calidad__perfil_sensorial__icontains=termino)
        | Q(caracteristicas_calidad__observaciones__icontains=termino)
    )

    lotes = list(base_qs.filter(q_filter)[:limite])
    resultados: List[ResultadoBusqueda] = []

    for lote in lotes:
        finca = getattr(lote.cosecha, "finca", None)
        municipio = getattr(finca, "municipio", None)
        variedad = getattr(lote.cosecha, "variedad", None)
        proceso = getattr(lote, "proceso_beneficio", None)
        calidad = getattr(lote, "caracteristicas_calidad", None)

        nombre_finca = finca.nombre if finca else "Finca sin asignar"
        nombre_muni = municipio.nombre if municipio else "Norte de Santander"
        nombre_var = variedad.nombre if variedad else "Variedad tradicional"
        nombre_proc = proceso.nombre if proceso else "Sin proceso"

        # URLs y accesos directos según rol
        es_dueno = bool(
            usuario and finca and str(finca.productor_id) == str(usuario.id)
        )
        es_admin = rol_codigo == "ADMINISTRADOR"

        url_detalle = f"/trazabilidad/lote/{lote.codigo}/"
        acciones: List[Dict[str, str]] = [
            AccionAccesoDirecto(
                etiqueta="Ficha Trazabilidad",
                url=url_detalle,
                icono="bi-qr-code",
                clase_btn="btn-outline-success",
            ).to_dict()
        ]

        if es_dueno or es_admin:
            url_gestion = f"/fincas/lotes/{lote.id}/"
            acciones.append(
                AccionAccesoDirecto(
                    etiqueta="Gestionar Lote",
                    url=url_gestion,
                    icono="bi-gear",
                    clase_btn="btn-outline-primary",
                ).to_dict()
            )
        elif lote.publicado_en_catalogo:
            url_catalogo = f"/catalogo/?q={lote.codigo}"
            acciones.append(
                AccionAccesoDirecto(
                    etiqueta="Ver en Catálogo",
                    url=url_catalogo,
                    icono="bi-shop",
                    clase_btn="btn-outline-dark",
                ).to_dict()
            )

        # Detalles adicionales
        detalles_map = {
            "Variedad": nombre_var,
            "Beneficio": nombre_proc,
            "Stock": f"{lote.cantidad} kg",
        }
        if calidad and calidad.puntaje_taza:
            detalles_map["Puntaje SCA"] = f"{calidad.puntaje_taza} pts"
        if lote.precio_referencial:
            detalles_map["Precio ref."] = f"${lote.precio_referencial:,.0f} COP/kg"

        # Relevancia
        perfil_txt = calidad.perfil_sensorial if calidad else ""
        rel = calcular_relevancia(
            termino=termino,
            campo_clave=lote.codigo,
            titulo=f"Lote {lote.codigo} ({nombre_var})",
            subtitulo=f"{nombre_finca} · {nombre_muni}",
            contenido_secundario=f"{nombre_proc} {perfil_txt}",
        )

        badge_txt = "En Catálogo" if lote.publicado_en_catalogo else "Bodega"
        badge_cls = "bg-success" if lote.publicado_en_catalogo else "bg-secondary"

        resultados.append(
            ResultadoBusqueda(
                id=lote.id,
                tipo_entidad="LOTE",
                tipo_entidad_display="Lote",
                titulo=f"Lote {lote.codigo} — {nombre_var}",
                subtitulo=f"Finca {nombre_finca} · {nombre_muni}, N. de S.",
                icono="bi-box-seam",
                badge_clase=badge_cls,
                badge_texto=badge_txt,
                url_detalle=url_detalle,
                relevancia=rel,
                detalles=detalles_map,
                acciones=acciones,
                fecha=lote.creado_en.strftime("%d/%m/%Y") if lote.creado_en else None,
            )
        )

    return resultados


def buscar_productores(
    termino: str,
    usuario: Optional[Usuario] = None,
    rol_codigo: str = "",
    limite: int = 25,
) -> List[ResultadoBusqueda]:
    """
    Búsqueda segmentada de productores y organizaciones cafeteras:
    - Administrador / Asociación / Productor: directorio completo de productores y cooperativas.
    - Comprador / Público: productores con fincas registradas o lotes en oferta.
    """
    if not termino or len(termino) < MIN_CARACTERES_BUSQUEDA:
        return []

    resultados: List[ResultadoBusqueda] = []

    # 1. Productores en public.usuarios
    usuarios_prod: List[Any] = []
    try:
        prod_qs = (
            Usuario.objects.filter(
                rol__codigo__in=["PRODUCTOR", "ASOCIACION"],
                activo=True,
            )
            .prefetch_related("fincas__municipio")
            .distinct()
        )

        q_user = (
            Q(nombres__icontains=termino)
            | Q(apellidos__icontains=termino)
            | Q(correo__icontains=termino)
            | Q(numero_documento__icontains=termino)
            | Q(telefono__icontains=termino)
            | Q(fincas__nombre__icontains=termino)
            | Q(fincas__municipio__nombre__icontains=termino)
        )

        usuarios_prod = list(prod_qs.filter(q_user)[:limite])
    except Exception:
        usuarios_prod = []

    for u in usuarios_prod:
        nombre_completo = f"{u.nombres} {u.apellidos}".strip() or u.correo
        fincas_nombres = [f.nombre for f in u.fincas.all() if f.activo]
        municipios = list(
            {f.municipio.nombre for f in u.fincas.all() if f.municipio}
        )

        sub_txt = (
            f"Fincas: {', '.join(fincas_nombres[:2])}"
            if fincas_nombres
            else "Caficultor registrado"
        )
        if municipios:
            sub_txt += f" · {', '.join(municipios[:2])}"

        detalles_map = {
            "Rol": u.rol.nombre if u.rol else "Productor",
            "Fincas activas": len(fincas_nombres),
        }
        if municipios:
            detalles_map["Municipios"] = ", ".join(municipios[:2])

        # Privacidad de contacto: el teléfono solo se expone a usuarios autenticados
        if usuario and u.telefono:
            detalles_map["Teléfono"] = u.telefono

        rel = calcular_relevancia(
            termino=termino,
            campo_clave=u.numero_documento or u.correo,
            titulo=nombre_completo,
            subtitulo=sub_txt,
            contenido_secundario=" ".join(fincas_nombres + municipios),
        )

        acciones: List[Dict[str, str]] = [
            AccionAccesoDirecto(
                etiqueta="Ver en Catálogo",
                url=f"/catalogo/?q={u.nombres}",
                icono="bi-shop",
                clase_btn="btn-outline-dark",
            ).to_dict()
        ]

        if rol_codigo == "ADMINISTRADOR":
            acciones.append(
                AccionAccesoDirecto(
                    etiqueta="Ver Perfil Admin",
                    url="/admin/usuarios/",
                    icono="bi-person-gear",
                    clase_btn="btn-outline-primary",
                ).to_dict()
            )

        resultados.append(
            ResultadoBusqueda(
                id=str(u.id),
                tipo_entidad="PRODUCTOR",
                tipo_entidad_display="Productor",
                titulo=nombre_completo,
                subtitulo=sub_txt,
                icono="bi-person-badge",
                badge_clase="bg-info text-dark",
                badge_texto="Caficultor",
                url_detalle=f"/catalogo/?q={u.nombres}",
                relevancia=rel,
                detalles=detalles_map,
                acciones=acciones,
                fecha=u.creado_en.strftime("%d/%m/%Y") if u.creado_en else None,
            )
        )

    # 2. Actores de la Cadena (Cooperativas y Asociaciones)
    actores_qs = ActorCadena.objects.filter(
        tipo__in=[
            ActorCadena.TipoActor.COOPERATIVA,
            ActorCadena.TipoActor.ASOCIACION,
        ],
        activo=True,
    )
    q_actor = (
        Q(razon_social__icontains=termino)
        | Q(nit__icontains=termino)
        | Q(contacto__icontains=termino)
        | Q(correo__icontains=termino)
    )
    actores = list(actores_qs.filter(q_actor)[:limite])

    for act in actores:
        rel_act = calcular_relevancia(
            termino=termino,
            campo_clave=act.nit,
            titulo=act.razon_social,
            subtitulo=f"{act.get_tipo_display()} · Contacto: {act.contacto}",
        )
        resultados.append(
            ResultadoBusqueda(
                id=act.id,
                tipo_entidad="PRODUCTOR",
                tipo_entidad_display="Organización",
                titulo=act.razon_social,
                subtitulo=f"{act.get_tipo_display()} · NIT: {act.nit}",
                icono="bi-building",
                badge_clase="bg-primary",
                badge_texto=act.get_tipo_display(),
                url_detalle="/actores/registro/",
                relevancia=rel_act,
                detalles={
                    "Contacto": act.contacto,
                    "Correo": act.correo,
                },
                acciones=[
                    AccionAccesoDirecto(
                        etiqueta="Registro de Actores",
                        url="/actores/registro/",
                        icono="bi-card-list",
                    ).to_dict()
                ],
                fecha=act.creado_en.strftime("%d/%m/%Y") if act.creado_en else None,
            )
        )

    return resultados[:limite]


def buscar_compradores(
    termino: str,
    usuario: Optional[Usuario] = None,
    rol_codigo: str = "",
    limite: int = 25,
) -> List[ResultadoBusqueda]:
    """
    Búsqueda segmentada de compradores con aislamiento multi-tenant estricto:
    - Administrador / Asociación: ve todos los compradores y empresas comercializadoras.
    - Productor: SOLO puede ver compradores que hayan manifestado interés sobre sus lotes.
    - Comprador: solo puede verse a sí mismo.
    - Anónimo / Operario: 0 resultados (protección estricta de privacidad comercial).
    """
    if not termino or len(termino) < MIN_CARACTERES_BUSQUEDA:
        return []

    # Control de acceso estricto RBAC
    if rol_codigo not in ["ADMINISTRADOR", "ASOCIACION", "PRODUCTOR", "COMPRADOR"]:
        return []

    resultados: List[ResultadoBusqueda] = []

    # 1. Filtro base de compradores según rol
    compradores: List[Any] = []
    try:
        comp_qs = Usuario.objects.filter(rol__codigo="COMPRADOR", activo=True)

        if rol_codigo == "PRODUCTOR" and usuario:
            # Aislamiento: solo compradores que manifestaron interés en lotes de este productor
            lotes_ids = Lote.objects.filter(
                cosecha__finca__productor_id=getattr(usuario, "id", None)
            ).values_list("id", flat=True)
            comp_qs = comp_qs.filter(manifestaciones_interes__lote_id__in=lotes_ids).distinct()

        elif rol_codigo == "COMPRADOR" and usuario:
            # El comprador solo puede verse a sí mismo
            comp_qs = comp_qs.filter(id=getattr(usuario, "id", None))

        q_comp = (
            Q(nombres__icontains=termino)
            | Q(apellidos__icontains=termino)
            | Q(correo__icontains=termino)
            | Q(numero_documento__icontains=termino)
            | Q(telefono__icontains=termino)
        )

        compradores = list(comp_qs.filter(q_comp)[:limite])
    except Exception:
        compradores = []

    for c in compradores:
        nombre_completo = f"{c.nombres} {c.apellidos}".strip() or c.correo
        total_intereses = c.manifestaciones_interes.count()

        rel = calcular_relevancia(
            termino=termino,
            campo_clave=c.correo or c.numero_documento,
            titulo=nombre_completo,
            subtitulo=f"Comprador registrado · {c.correo}",
        )

        detalles_map = {
            "Correo": c.correo,
            "Operaciones / Intereses": total_intereses,
        }
        if c.telefono:
            detalles_map["Teléfono"] = c.telefono

        acciones = [
            AccionAccesoDirecto(
                etiqueta="Ver Negociaciones",
                url="/fincas/mis-lotes/interes/",
                icono="bi-chat-dots",
                clase_btn="btn-outline-primary",
            ).to_dict()
        ]

        resultados.append(
            ResultadoBusqueda(
                id=str(c.id),
                tipo_entidad="COMPRADOR",
                tipo_entidad_display="Comprador",
                titulo=nombre_completo,
                subtitulo=f"Comprador · {c.correo}",
                icono="bi-bag-check",
                badge_clase="bg-warning text-dark",
                badge_texto="Comprador",
                url_detalle="/fincas/mis-lotes/interes/",
                relevancia=rel,
                detalles=detalles_map,
                acciones=acciones,
                fecha=c.creado_en.strftime("%d/%m/%Y") if c.creado_en else None,
            )
        )

    # 2. Empresas Comercializadoras (ActorCadena) para Admin y Asociación
    if rol_codigo in ["ADMINISTRADOR", "ASOCIACION"]:
        act_comerciales = ActorCadena.objects.filter(
            tipo=ActorCadena.TipoActor.COMERCIALIZADOR,
            activo=True,
        )
        q_act = (
            Q(razon_social__icontains=termino)
            | Q(nit__icontains=termino)
            | Q(contacto__icontains=termino)
            | Q(correo__icontains=termino)
        )
        for act in list(act_comerciales.filter(q_act)[:limite]):
            rel_c = calcular_relevancia(
                termino=termino,
                campo_clave=act.nit,
                titulo=act.razon_social,
                subtitulo=f"Empresa Comercializadora · NIT: {act.nit}",
            )
            resultados.append(
                ResultadoBusqueda(
                    id=act.id,
                    tipo_entidad="COMPRADOR",
                    tipo_entidad_display="Comercializador",
                    titulo=act.razon_social,
                    subtitulo=f"Comercializador de Café · Contacto: {act.contacto}",
                    icono="bi-briefcase",
                    badge_clase="bg-dark text-white",
                    badge_texto="Comercializador",
                    url_detalle="/actores/registro/",
                    relevancia=rel_c,
                    detalles={
                        "NIT": act.nit,
                        "Correo": act.correo,
                        "Contacto": act.contacto,
                    },
                    acciones=[
                        AccionAccesoDirecto(
                            etiqueta="Ficha Actor",
                            url="/actores/registro/",
                            icono="bi-building",
                        ).to_dict()
                    ],
                    fecha=act.creado_en.strftime("%d/%m/%Y") if act.creado_en else None,
                )
            )

    return resultados[:limite]


def buscar_operaciones(
    termino: str,
    usuario: Optional[Usuario] = None,
    rol_codigo: str = "",
    limite: int = 25,
) -> List[ResultadoBusqueda]:
    """
    Búsqueda segmentada de operaciones comerciales (Manifestaciones de Interés):
    - Administrador: consulta todas las operaciones registradas.
    - Productor: ve únicamente operaciones dirigidas a lotes de sus fincas.
    - Comprador: ve únicamente sus propias operaciones / solicitudes enviadas.
    - Otros roles / Anónimos: 0 resultados (información transaccional privada).
    """
    if not termino or len(termino) < MIN_CARACTERES_BUSQUEDA:
        return []

    if rol_codigo not in ["ADMINISTRADOR", "ASOCIACION", "PRODUCTOR", "COMPRADOR"]:
        return []

    # 1. Queryset base con aislamiento estricto
    op_qs = ManifestacionInteres.objects.select_related(
        "lote__cosecha__finca",
        "lote__cosecha__variedad",
    )

    if rol_codigo == "PRODUCTOR" and usuario:
        op_qs = op_qs.filter(lote__cosecha__finca__productor_id=getattr(usuario, "id", None))
    elif rol_codigo == "COMPRADOR" and usuario:
        op_qs = op_qs.filter(comprador_id=getattr(usuario, "id", None))
    elif rol_codigo in ["ADMINISTRADOR", "ASOCIACION"]:
        pass  # Visibilidad institucional
    else:
        return []

    # 2. Cláusulas de búsqueda
    q_op = (
        Q(lote__codigo__icontains=termino)
        | Q(comprador_correo__icontains=termino)
        | Q(telefono_contacto__icontains=termino)
        | Q(mensaje__icontains=termino)
        | Q(estado__icontains=termino)
    )

    operaciones = list(op_qs.filter(q_op)[:limite])
    resultados: List[ResultadoBusqueda] = []

    for op in operaciones:
        lote = getattr(op, "lote", None)
        nombre_comp = ""
        try:
            comp = getattr(op, "comprador", None)
            if comp:
                nombre_comp = f"{getattr(comp, 'nombres', '')} {getattr(comp, 'apellidos', '')}".strip()
        except Exception:
            nombre_comp = ""

        if not nombre_comp:
            nombre_comp = op.comprador_correo or "Comprador interesado"

        codigo_lote = lote.codigo if lote else "LOTE-N/A"

        cant_txt = f"{op.cantidad_kg} kg" if op.cantidad_kg else "A convenir"
        sub_txt = f"Lote {codigo_lote} · Solicitado por: {nombre_comp} ({cant_txt})"

        rel = calcular_relevancia(
            termino=termino,
            campo_clave=f"OP-{op.id} {codigo_lote}",
            titulo=f"Operación #{op.id} — Interés en {codigo_lote}",
            subtitulo=sub_txt,
            contenido_secundario=op.mensaje or "",
        )

        detalles_map = {
            "Lote": codigo_lote,
            "Comprador": nombre_comp,
            "Cantidad solicitada": cant_txt,
            "Estado": op.get_estado_display(),
        }
        if op.telefono_contacto and usuario:
            detalles_map["Contacto"] = op.telefono_contacto

        url_op = "/fincas/mis-lotes/interes/"
        acciones = [
            AccionAccesoDirecto(
                etiqueta="Ver Notificación",
                url=url_op,
                icono="bi-chat-left-dots",
                clase_btn="btn-outline-success",
            ).to_dict()
        ]

        badge_cls = "bg-primary"
        if op.vista_por_productor:
            badge_cls = "bg-secondary"

        resultados.append(
            ResultadoBusqueda(
                id=op.id,
                tipo_entidad="OPERACION",
                tipo_entidad_display="Operación",
                titulo=f"Operación #{op.id} — Interés en {codigo_lote}",
                subtitulo=sub_txt,
                icono="bi-receipt",
                badge_clase=badge_cls,
                badge_texto=op.get_estado_display(),
                url_detalle=url_op,
                relevancia=rel,
                detalles=detalles_map,
                acciones=acciones,
                fecha=op.creado_en.strftime("%d/%m/%Y %H:%M") if op.creado_en else None,
            )
        )

    return resultados


# -----------------------------------------------------------------------------
# Orquestador Principal de Búsqueda Global (HU29-ST3 / HU29-ST2 / HU29-ST6)
# -----------------------------------------------------------------------------

def ejecutar_busqueda_global(
    termino: str,
    tipo_entidad: str = "todas",
    usuario_o_id: Any = None,
    rol_codigo: str = "",
    limite_por_entidad: int = 25,
) -> Dict[str, Any]:
    """
    Punto de entrada unificado para búsquedas globales en Café Pérgamo.
    
    Parámetros:
    - termino: texto de búsqueda ingresado por el usuario.
    - tipo_entidad: 'todas', 'lotes', 'productores', 'compradores', 'operaciones'.
    - usuario_o_id: perfil de negocio (Usuario), User de Django o UUID.
    - rol_codigo: código del rol activo en la sesión (ej. 'ADMINISTRADOR', 'PRODUCTOR').
    - limite_por_entidad: cantidad máxima de resultados por entidad.

    Retorna:
    Diccionario estructurado con conteos por categoría, entidades permitidas por RBAC,
    y lista unificada de resultados ordenados por relevancia.
    """
    inicio_ms = time.time()
    t_limpio = normalizar_termino_busqueda(termino)
    tipo_solicitado = (tipo_entidad or "todas").lower().strip()
    if tipo_solicitado not in ENTIDADES_VALIDAS:
        tipo_solicitado = "todas"

    usuario, rol_activo = resolver_usuario_y_rol(usuario_o_id, rol_codigo)
    entidades_permitidas = obtener_entidades_permitidas(usuario, rol_activo)

    conteo_map: Dict[str, int] = {
        "todas": 0,
        "lotes": 0,
        "productores": 0,
        "compradores": 0,
        "operaciones": 0,
    }
    resultados_por_entidad: Dict[str, List[Dict[str, Any]]] = {
        "lotes": [],
        "productores": [],
        "compradores": [],
        "operaciones": [],
    }

    # Si el término no cumple longitud mínima, se devuelven conteos en 0 sin error
    if len(t_limpio) < MIN_CARACTERES_BUSQUEDA:
        tiempo_total = round((time.time() - inicio_ms) * 1000, 2)
        return {
            "termino": t_limpio,
            "tipo_filtro": tipo_solicitado,
            "total_resultados": 0,
            "conteo_por_entidad": conteo_map,
            "entidades_permitidas": list(entidades_permitidas),
            "resultados": [],
            "resultados_por_entidad": resultados_por_entidad,
            "tiempo_ms": tiempo_total,
            "aviso": (
                f"Ingresa al menos {MIN_CARACTERES_BUSQUEDA} caracteres para realizar la búsqueda."
                if t_limpio
                else ""
            ),
        }

    # 1. Búsqueda de Lotes (si está permitida)
    if "lotes" in entidades_permitidas:
        res_lotes = buscar_lotes(
            termino=t_limpio,
            usuario=usuario,
            rol_codigo=rol_activo,
            limite=limite_por_entidad,
        )
        conteo_map["lotes"] = len(res_lotes)
        resultados_por_entidad["lotes"] = [r.to_dict() for r in res_lotes]

    # 2. Búsqueda de Productores (si está permitida)
    if "productores" in entidades_permitidas:
        res_prod = buscar_productores(
            termino=t_limpio,
            usuario=usuario,
            rol_codigo=rol_activo,
            limite=limite_por_entidad,
        )
        conteo_map["productores"] = len(res_prod)
        resultados_por_entidad["productores"] = [r.to_dict() for r in res_prod]

    # 3. Búsqueda de Compradores (si está permitida)
    if "compradores" in entidades_permitidas:
        res_comp = buscar_compradores(
            termino=t_limpio,
            usuario=usuario,
            rol_codigo=rol_activo,
            limite=limite_por_entidad,
        )
        conteo_map["compradores"] = len(res_comp)
        resultados_por_entidad["compradores"] = [r.to_dict() for r in res_comp]

    # 4. Búsqueda de Operaciones (si está permitida)
    if "operaciones" in entidades_permitidas:
        res_oper = buscar_operaciones(
            termino=t_limpio,
            usuario=usuario,
            rol_codigo=rol_activo,
            limite=limite_por_entidad,
        )
        conteo_map["operaciones"] = len(res_oper)
        resultados_por_entidad["operaciones"] = [r.to_dict() for r in res_oper]

    # Conteo total general
    conteo_map["todas"] = (
        conteo_map["lotes"]
        + conteo_map["productores"]
        + conteo_map["compradores"]
        + conteo_map["operaciones"]
    )

    # Filtrar según la pestaña/entidad seleccionada
    lista_final: List[Dict[str, Any]] = []
    if tipo_solicitado == "todas":
        for cat_list in resultados_por_entidad.values():
            lista_final.extend(cat_list)
    elif tipo_solicitado in resultados_por_entidad:
        lista_final = list(resultados_por_entidad[tipo_solicitado])

    # Ordenar por mayor relevancia descendente
    lista_final.sort(key=lambda item: item.get("relevancia", 0), reverse=True)

    tiempo_total = round((time.time() - inicio_ms) * 1000, 2)

    return {
        "termino": t_limpio,
        "tipo_filtro": tipo_solicitado,
        "total_resultados": len(lista_final),
        "conteo_por_entidad": conteo_map,
        "entidades_permitidas": list(entidades_permitidas),
        "resultados": lista_final,
        "resultados_por_entidad": resultados_por_entidad,
        "tiempo_ms": tiempo_total,
    }
