"""
Módulo de Generación y Exportación de Reportes — CAFÉ PÉRGAMO
Épica E8 / Sprint 4
Historia de Usuario: HU-27 (SCRUM-236): Exportar reportes en PDF o Excel.

Subtareas:
- SCRUM-304 (HU27-ST1): Diseñar la experiencia de exportación de reportes.
- SCRUM-305 (HU27-ST2): Definir el formato y estructura del reporte exportado.
- SCRUM-306 (HU27-ST3): Asegurar que la exportación respete los filtros activos.
- SCRUM-307 (HU27-ST4): Implementar la generación de reportes en Excel.
- SCRUM-308 (HU27-ST5): Implementar la generación de reportes en PDF.
- SCRUM-309 (HU27-ST6): Validar permisos y disponibilidad de exportación.
- SCRUM-310 (HU27-ST7): Probar la exportación de reportes en distintos escenarios.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import io
import re
from typing import Any, Dict, List, Optional
import unicodedata

from django.db.models import Avg, Q, QuerySet, Sum
from django.utils import timezone

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from catalogos.models import ProcesoBeneficio, VariedadCafe
from fincas.models import Finca, Lote, Municipio
from usuarios.models import Usuario


# ==============================================================================
# 1. Definición del Formato y Estructura del Reporte (SCRUM-305 / HU27-ST2)
# ==============================================================================

@dataclass
class ColumnaReporte:
    """Especificación canónica de cada columna en el reporte consolidado."""
    clave: str
    encabezado: str
    ancho_excel: int
    ancho_pdf: float  # En puntos tipográficos
    alineacion: str = "left"  # left, center, right
    formato_excel: Optional[str] = None


COLUMNAS_REPORTE_LOTES: List[ColumnaReporte] = [
    ColumnaReporte("indice", "N°", 5, 25, "center"),
    ColumnaReporte("codigo", "Código Lote", 16, 65, "center"),
    ColumnaReporte("finca_nombre", "Finca / Predio", 22, 90, "left"),
    ColumnaReporte("vereda", "Vereda", 16, 60, "left"),
    ColumnaReporte("municipio", "Municipio", 16, 60, "left"),
    ColumnaReporte("variedad", "Variedad", 16, 65, "left"),
    ColumnaReporte("proceso", "Beneficio", 18, 65, "left"),
    ColumnaReporte("cantidad_kg", "Cantidad (kg)", 15, 60, "right", "#,##0.00"),
    ColumnaReporte("puntaje_taza", "SCA (pts)", 12, 50, "right", "0.00"),
    ColumnaReporte("humedad", "Humedad", 12, 50, "right", "0.0%"),
    ColumnaReporte("estado_display", "Estado Comercial", 18, 65, "center"),
    ColumnaReporte("precio_referencial", "Precio ($/kg)", 16, 65, "right", "$#,##0"),
    ColumnaReporte("fecha", "Fecha", 12, 50, "center"),
]


@dataclass
class FilaReporteLote:
    """Fila estructurada de datos de un lote para el reporte."""
    indice: int
    codigo: str
    finca_nombre: str
    vereda: str
    municipio: str
    variedad: str
    proceso: str
    cantidad_kg: Decimal
    puntaje_taza: Optional[Decimal]
    humedad: Optional[Decimal]
    estado_display: str
    precio_referencial: Optional[Decimal]
    fecha: str
    caficultor: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "indice": self.indice,
            "codigo": self.codigo,
            "finca_nombre": self.finca_nombre,
            "vereda": self.vereda,
            "municipio": self.municipio,
            "variedad": self.variedad,
            "proceso": self.proceso,
            "cantidad_kg": self.cantidad_kg,
            "puntaje_taza": self.puntaje_taza,
            "humedad": self.humedad,
            "estado_display": self.estado_display,
            "precio_referencial": self.precio_referencial,
            "fecha": self.fecha,
            "caficultor": self.caficultor,
        }


# ==============================================================================
# 2. Extractor y Filtros de Datos (SCRUM-306 / HU27-ST3 / SCRUM-309)
# ==============================================================================

def obtener_datos_reporte_lotes(
    usuario: Optional[Any] = None,
    rol_codigo: str = "",
    filtros: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extrae, valida y estructura la información de lotes respetando el aislamiento
    multi-tenant RBAC y los filtros activos en pantalla (SCRUM-306).
    """
    filtros = filtros or {}
    rol = (rol_codigo or "").upper().strip()

    # 1. Base Queryset según aislamiento multi-tenant
    if rol == "ADMINISTRADOR":
        base_qs = Lote.objects.all()
    elif rol == "PRODUCTOR" and usuario:
        productor_id = getattr(usuario, "id", None) or usuario
        base_qs = Lote.objects.filter(cosecha__finca__productor_id=productor_id)
    elif rol == "ASOCIACION":
        base_qs = Lote.objects.filter(activo=True)
    else:
        # Visitante / Comprador / Rol no privilegiado: catálogo público
        base_qs = Lote.objects.filter(
            publicado_en_catalogo=True,
            activo=True,
            cantidad__gt=Decimal("0.00"),
            cosecha__activo=True,
            cosecha__finca__activo=True,
        )

    base_qs = base_qs.select_related(
        "cosecha__finca__municipio",
        "cosecha__variedad",
        "proceso_beneficio",
        "estado_lote",
        "caracteristicas_calidad",
    ).order_by("-fecha_publicacion", "-id")

    # 2. Aplicación de filtros activos
    textos_filtros: List[str] = []

    finca_id = filtros.get("finca") or filtros.get("finca_id")
    if finca_id:
        try:
            base_qs = base_qs.filter(cosecha__finca_id=int(finca_id))
            finca_obj = Finca.objects.filter(id=int(finca_id)).first()
            if finca_obj:
                textos_filtros.append(f"Finca: {finca_obj.nombre}")
        except (ValueError, TypeError):
            pass

    municipio_id = filtros.get("municipio") or filtros.get("municipio_id")
    if municipio_id:
        try:
            base_qs = base_qs.filter(cosecha__finca__municipio_id=int(municipio_id))
            mun_obj = Municipio.objects.filter(id=int(municipio_id)).first()
            if mun_obj:
                textos_filtros.append(f"Municipio: {mun_obj.nombre}")
        except (ValueError, TypeError):
            pass

    variedad_id = filtros.get("variedad") or filtros.get("variedad_id")
    if variedad_id:
        try:
            base_qs = base_qs.filter(cosecha__variedad_id=int(variedad_id))
            var_obj = VariedadCafe.objects.filter(id=int(variedad_id)).first()
            if var_obj:
                textos_filtros.append(f"Variedad: {var_obj.nombre}")
        except (ValueError, TypeError):
            pass

    proceso_id = filtros.get("proceso") or filtros.get("proceso_id")
    if proceso_id:
        try:
            base_qs = base_qs.filter(proceso_beneficio_id=int(proceso_id))
            proc_obj = ProcesoBeneficio.objects.filter(id=int(proceso_id)).first()
            if proc_obj:
                textos_filtros.append(f"Proceso: {proc_obj.nombre}")
        except (ValueError, TypeError):
            pass

    puntaje_min = filtros.get("puntaje_min")
    if puntaje_min:
        try:
            val_pts = Decimal(str(puntaje_min))
            base_qs = base_qs.filter(caracteristicas_calidad__puntaje_taza__gte=val_pts)
            textos_filtros.append(f"Puntaje SCA ≥ {val_pts} pts")
        except Exception:
            pass

    estado_filtro = filtros.get("estado")
    if estado_filtro:
        base_qs = base_qs.filter(
            Q(estado_comercial__iexact=str(estado_filtro))
            | Q(estado_lote__codigo__iexact=str(estado_filtro))
            | Q(estado_lote__nombre__iexact=str(estado_filtro))
        )
        textos_filtros.append(f"Estado: {estado_filtro}")

    publicado_filtro = filtros.get("publicado")
    if publicado_filtro in (True, "true", "1", "True"):
        base_qs = base_qs.filter(publicado_en_catalogo=True)
        textos_filtros.append("Solo publicados en catálogo")
    elif publicado_filtro in (False, "false", "0", "False"):
        base_qs = base_qs.filter(publicado_en_catalogo=False)
        textos_filtros.append("Solo no publicados (bodega)")

    query_q = filtros.get("q")
    if query_q:
        q_limpio = str(query_q).strip()
        if q_limpio:
            base_qs = base_qs.filter(
                Q(codigo__icontains=q_limpio)
                | Q(cosecha__finca__nombre__icontains=q_limpio)
                | Q(cosecha__finca__vereda__icontains=q_limpio)
                | Q(cosecha__finca__municipio__nombre__icontains=q_limpio)
                | Q(cosecha__variedad__nombre__icontains=q_limpio)
                | Q(proceso_beneficio__nombre__icontains=q_limpio)
                | Q(caracteristicas_calidad__perfil_sensorial__icontains=q_limpio)
            )
            textos_filtros.append(f'Búsqueda libre: "{q_limpio}"')

    # Filtros de fecha (SCRUM-306)
    fecha_inicio = filtros.get("fecha_inicio") or filtros.get("desde")
    if fecha_inicio:
        try:
            base_qs = base_qs.filter(
                Q(fecha_publicacion__date__gte=fecha_inicio)
                | Q(cosecha__fecha_cosecha__gte=fecha_inicio)
            )
            textos_filtros.append(f"Desde: {fecha_inicio}")
        except Exception:
            pass

    fecha_fin = filtros.get("fecha_fin") or filtros.get("hasta")
    if fecha_fin:
        try:
            base_qs = base_qs.filter(
                Q(fecha_publicacion__date__lte=fecha_fin)
                | Q(cosecha__fecha_cosecha__lte=fecha_fin)
            )
            textos_filtros.append(f"Hasta: {fecha_fin}")
        except Exception:
            pass

    # Ordenamiento respetado desde la UI (SCRUM-306)
    orden = filtros.get("orden") or filtros.get("ordering")
    if orden == "puntaje_desc":
        base_qs = base_qs.order_by("-caracteristicas_calidad__puntaje_taza", "-id")
        textos_filtros.append("Orden: Mayor puntaje SCA")
    elif orden == "puntaje_asc":
        base_qs = base_qs.order_by("caracteristicas_calidad__puntaje_taza", "-id")
        textos_filtros.append("Orden: Menor puntaje SCA")
    elif orden == "precio_desc":
        base_qs = base_qs.order_by("-precio_referencial", "-id")
        textos_filtros.append("Orden: Mayor precio")
    elif orden == "precio_asc":
        base_qs = base_qs.order_by("precio_referencial", "-id")
        textos_filtros.append("Orden: Menor precio")
    elif orden == "cantidad_desc":
        base_qs = base_qs.order_by("-cantidad", "-id")
        textos_filtros.append("Orden: Mayor cantidad")
    elif orden == "fecha_asc":
        base_qs = base_qs.order_by("fecha_publicacion", "id")
        textos_filtros.append("Orden: Más antiguos primero")

    # 3. Construcción de filas tabulares
    lotes_list = list(base_qs)
    filas: List[FilaReporteLote] = []

    suma_kilos = Decimal("0.00")
    suma_puntaje = Decimal("0.00")
    conteo_con_puntaje = 0
    suma_precio = Decimal("0.00")
    conteo_con_precio = 0

    for idx, lote in enumerate(lotes_list, start=1):
        finca = getattr(lote.cosecha, "finca", None)
        municipio = getattr(finca, "municipio", None)
        variedad = getattr(lote.cosecha, "variedad", None)
        proceso = getattr(lote, "proceso_beneficio", None)
        calidad = getattr(lote, "caracteristicas_calidad", None)

        cantidad_kg = lote.cantidad or Decimal("0.00")
        suma_kilos += cantidad_kg

        puntaje_taza = calidad.puntaje_taza if calidad else None
        if puntaje_taza is not None:
            suma_puntaje += puntaje_taza
            conteo_con_puntaje += 1

        humedad = calidad.humedad if calidad else None

        precio_ref = lote.precio_referencial
        if precio_ref is not None:
            suma_precio += precio_ref
            conteo_con_precio += 1

        # Estado legible
        if lote.publicado_en_catalogo:
            estado_txt = "En Catálogo"
        elif lote.estado_comercial and lote.estado_comercial != "DISPONIBLE":
            estado_txt = lote.get_estado_comercial_display()
        elif lote.estado_lote:
            estado_txt = lote.estado_lote.nombre
        else:
            estado_txt = "En Bodega"

        # Fecha
        fecha_lote = lote.fecha_publicacion or getattr(lote.cosecha, "fecha_cosecha", None)
        fecha_str = fecha_lote.strftime("%d/%m/%Y") if fecha_lote else "-"

        # Caficultor
        caficultor = "Productor registrado"
        if finca and finca.productor_id:
            caficultor = str(finca.productor_id)[:8]
            try:
                productor_obj = Usuario.objects.filter(id=finca.productor_id).first()
                if productor_obj:
                    nom = f"{productor_obj.nombre} {productor_obj.apellido}".strip()
                    caficultor = nom if nom else productor_obj.correo
            except Exception:
                pass

        filas.append(
            FilaReporteLote(
                indice=idx,
                codigo=lote.codigo,
                finca_nombre=finca.nombre if finca else "Sin finca",
                vereda=finca.vereda if finca else "-",
                municipio=municipio.nombre if municipio else "Norte de Santander",
                variedad=variedad.nombre if variedad else "Tradicional",
                proceso=proceso.nombre if proceso else "Sin proceso",
                cantidad_kg=cantidad_kg,
                puntaje_taza=puntaje_taza,
                humedad=humedad,
                estado_display=estado_txt,
                precio_referencial=precio_ref,
                fecha=fecha_str,
                caficultor=caficultor,
            )
        )

    # 4. Totales y promedios
    total_lotes = len(filas)
    prom_puntaje = round(suma_puntaje / conteo_con_puntaje, 2) if conteo_con_puntaje > 0 else None
    prom_precio = round(suma_precio / conteo_con_precio, 2) if conteo_con_precio > 0 else None

    # Metadatos del emisor
    nombre_usuario = "Usuario Autorizado"
    if usuario:
        if hasattr(usuario, "get_full_name") and usuario.get_full_name():
            nombre_usuario = usuario.get_full_name()
        elif hasattr(usuario, "username") and usuario.username:
            nombre_usuario = usuario.username
        else:
            nombre_usuario = str(usuario)
            try:
                u_obj = Usuario.objects.filter(id=usuario).first()
                if u_obj:
                    nom = f"{u_obj.nombre} {u_obj.apellido}".strip()
                    nombre_usuario = nom if nom else u_obj.correo
            except Exception:
                pass

    filtros_resumen = " | ".join(textos_filtros) if textos_filtros else "Ninguno (Consolidado completo)"

    return {
        "metadata": {
            "titulo": "CAFÉ PÉRGAMO — Sistema de Trazabilidad y Comercialización",
            "subtitulo": "Reporte Consolidado de Lotes de Café de Origen",
            "departamento": "Norte de Santander, Colombia",
            "institucion": "Universidad Francisco de Paula Santander (UFPS)",
            "fecha_generacion": timezone.localtime().strftime("%d/%m/%Y %H:%M:%S"),
            "generado_por": nombre_usuario,
            "rol": rol or "Público",
            "filtros_texto": filtros_resumen,
            "total_registros": total_lotes,
        },
        "columnas": COLUMNAS_REPORTE_LOTES,
        "filas": filas,
        "totales": {
            "total_lotes": total_lotes,
            "total_kilos": suma_kilos,
            "promedio_puntaje_taza": prom_puntaje,
            "promedio_precio": prom_precio,
        },
    }


# ==============================================================================
# 3. Generación Binaria en Excel (SCRUM-307 / HU27-ST4)
# ==============================================================================

def generar_reporte_lotes_excel(datos_reporte: Dict[str, Any]) -> bytes:
    """
    Construye una hoja de cálculo Excel estilizada conforme a los estándares de Café Pérgamo:
    - Paleta institucional (#2B1810, #4A2C2A, #1B381E).
    - Encabezado con metadatos y filtros activos.
    - Celdas con formato de moneda, porcentaje y decimales.
    - Fila de totales y autoajuste de columnas.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lotes de Café"
    ws.views.sheetView[0].showGridLines = True

    # Paleta de colores institucional
    color_header_fill = "4A2C2A"
    color_sub_fill = "2B1810"
    color_zebra = "FBF9F8"
    color_total_fill = "EDE6E3"

    fill_header = PatternFill(start_color=color_header_fill, end_color=color_header_fill, fill_type="solid")
    fill_zebra = PatternFill(start_color=color_zebra, end_color=color_zebra, fill_type="solid")
    fill_totales = PatternFill(start_color=color_total_fill, end_color=color_total_fill, fill_type="solid")

    font_titulo = Font(name="Calibri", size=15, bold=True, color="2B1810")
    font_subtitulo = Font(name="Calibri", size=11, bold=True, color="4A2C2A")
    font_meta = Font(name="Calibri", size=9, italic=True, color="555555")
    font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Calibri", size=10, color="000000")
    font_total = Font(name="Calibri", size=10, bold=True, color="2B1810")

    border_thin = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )
    border_total = Border(
        top=Side(style="thin", color="4A2C2A"),
        bottom=Side(style="double", color="4A2C2A"),
    )

    metadata = datos_reporte["metadata"]
    columnas = datos_reporte["columnas"]
    filas = datos_reporte["filas"]
    totales = datos_reporte["totales"]

    # Fila 1: Título Institucional
    ws.merge_cells("A1:M1")
    ws["A1"] = metadata["titulo"]
    ws["A1"].font = font_titulo
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26

    # Fila 2: Subtítulo
    ws.merge_cells("A2:M2")
    ws["A2"] = f"{metadata['subtitulo']} — {metadata['departamento']}"
    ws["A2"].font = font_subtitulo
    ws.row_dimensions[2].height = 18

    # Fila 3 y 4: Metadatos y filtros
    ws.merge_cells("A3:M3")
    ws["A3"] = f"Generado el: {metadata['fecha_generacion']} | Emisor: {metadata['generado_por']} ({metadata['rol']}) | Entidad: {metadata['institucion']}"
    ws["A3"].font = font_meta

    ws.merge_cells("A4:M4")
    ws["A4"] = f"Filtros aplicados: {metadata['filtros_texto']} | Total registros: {metadata['total_registros']}"
    ws["A4"].font = font_meta
    ws.row_dimensions[4].height = 18

    # Fila 6: Encabezados de la tabla
    row_num = 6
    ws.row_dimensions[row_num].height = 24
    for col_idx, col in enumerate(columnas, start=1):
        cell = ws.cell(row=row_num, column=col_idx, value=col.encabezado)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Filas de datos
    for r_idx, fila in enumerate(filas, start=7):
        ws.row_dimensions[r_idx].height = 20
        d_map = fila.to_dict()
        is_even = (r_idx % 2 == 0)

        for c_idx, col in enumerate(columnas, start=1):
            val = d_map.get(col.clave)
            cell = ws.cell(row=r_idx, column=c_idx)

            # Formateo de tipos
            if col.clave == "cantidad_kg":
                cell.value = float(val) if val is not None else 0.0
                cell.number_format = "#,##0.00"
            elif col.clave == "puntaje_taza":
                cell.value = float(val) if val is not None else ""
                cell.number_format = "0.00"
            elif col.clave == "humedad":
                cell.value = (float(val) / 100.0) if val is not None else ""
                cell.number_format = "0.0%"
            elif col.clave == "precio_referencial":
                cell.value = float(val) if val is not None else ""
                cell.number_format = "$#,##0"
            else:
                cell.value = str(val) if val is not None else ""

            cell.font = font_data
            cell.border = border_thin
            cell.alignment = Alignment(horizontal=col.alineacion, vertical="center")
            if is_even:
                cell.fill = fill_zebra

    # Fila de Totales
    total_row = 7 + len(filas)
    ws.row_dimensions[total_row].height = 22

    ws.cell(row=total_row, column=1, value="")
    ws.cell(row=total_row, column=2, value="TOTALES / PROMEDIOS").font = font_total
    ws.cell(row=total_row, column=8, value=float(totales["total_kilos"])).number_format = "#,##0.00"
    ws.cell(row=total_row, column=8).font = font_total

    if totales["promedio_puntaje_taza"] is not None:
        ws.cell(row=total_row, column=9, value=float(totales["promedio_puntaje_taza"])).number_format = "0.00"
        ws.cell(row=total_row, column=9).font = font_total

    if totales["promedio_precio"] is not None:
        ws.cell(row=total_row, column=12, value=float(totales["promedio_precio"])).number_format = "$#,##0"
        ws.cell(row=total_row, column=12).font = font_total

    for c_idx in range(1, len(columnas) + 1):
        c = ws.cell(row=total_row, column=c_idx)
        c.fill = fill_totales
        c.border = border_total

    # Congelamiento de paneles bajo la cabecera (SCRUM-307)
    ws.freeze_panes = "A7"

    # Configuración de página e impresión apaisada (Landscape)
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # Autoajuste dinámico de anchos de columna según contenido
    for c_idx, col in enumerate(columnas, start=1):
        col_letter = get_column_letter(c_idx)
        max_len = len(str(col.encabezado or ""))
        for r_idx in range(7, 7 + len(filas)):
            cell_val = ws.cell(row=r_idx, column=c_idx).value
            if cell_val is not None:
                max_len = max(max_len, len(str(cell_val)))
        ancho_optimo = max(col.ancho_excel, min(max_len + 3, 38))
        ws.column_dimensions[col_letter].width = ancho_optimo

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


# ==============================================================================
# 4. Generación Binaria en PDF (SCRUM-308 / HU27-ST5)
# ==============================================================================

class NumberedCanvas(canvas.Canvas):
    """
    Canvas especializado de ReportLab con técnica de dos pasadas (two-pass)
    para calcular el total exacto de páginas y estampar pie institucional
    y numeración 'Página X de Y' en todas las hojas.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#666666"))

        # Línea divisoria tenue
        self.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.setLineWidth(0.5)
        self.line(30, 26, 792 - 30, 26)

        texto_izq = "Café Pérgamo — Sistema de Trazabilidad y Comercialización | UFPS Norte de Santander"
        texto_der = f"Página {self._pageNumber} de {page_count}"

        self.drawString(30, 16, texto_izq)
        self.drawRightString(792 - 30, 16, texto_der)
        self.restoreState()


def generar_reporte_lotes_pdf(datos_reporte: Dict[str, Any]) -> bytes:
    """
    Construye un documento PDF vectorial apaisado (landscape) con Platypus:
    - Encabezado institucional UFPS / Café Pérgamo.
    - Bloque de filtros activos y metadatos del emisor.
    - Tabla estructurada con anchos proporcionales, colores alternos y paginación.
    - Paginación dinámica de dos pasadas ('Página X de Y') con NumberedCanvas.
    - Resumen numérico y pie de página legal.
    """
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    # Estilos tipográficos
    style_titulo = ParagraphStyle(
        "TituloReporte",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#2B1810"),
    )
    style_sub = ParagraphStyle(
        "SubReporte",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#4A2C2A"),
    )
    style_meta = ParagraphStyle(
        "MetaReporte",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#555555"),
    )
    style_th = ParagraphStyle(
        "TH",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.white,
        alignment=1,  # Center
    )
    style_td = ParagraphStyle(
        "TD",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        textColor=colors.black,
    )
    style_td_center = ParagraphStyle(
        "TDCenter",
        parent=style_td,
        alignment=1,
    )
    style_td_right = ParagraphStyle(
        "TDRight",
        parent=style_td,
        alignment=2,
    )
    style_td_total = ParagraphStyle(
        "TDTotal",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#2B1810"),
        alignment=2,
    )

    metadata = datos_reporte["metadata"]
    columnas = datos_reporte["columnas"]
    filas = datos_reporte["filas"]
    totales = datos_reporte["totales"]

    story: List[Any] = []

    # 1. Encabezado institucional
    story.append(Paragraph(metadata["titulo"], style_titulo))
    story.append(Paragraph(f"{metadata['subtitulo']} — {metadata['departamento']}", style_sub))
    story.append(Spacer(1, 4))

    meta_txt = (
        f"<b>Fecha de emisión:</b> {metadata['fecha_generacion']} | "
        f"<b>Generado por:</b> {metadata['generado_por']} ({metadata['rol']}) | "
        f"<b>Entidad:</b> {metadata['institucion']}<br/>"
        f"<b>Filtros aplicados:</b> {metadata['filtros_texto']} | "
        f"<b>Total registros:</b> {metadata['total_registros']}"
    )
    story.append(Paragraph(meta_txt, style_meta))
    story.append(Spacer(1, 10))

    # 2. Tabla de Datos
    col_widths = [c.ancho_pdf for c in columnas]

    table_data = []
    # Encabezados
    headers_row = [Paragraph(c.encabezado, style_th) for c in columnas]
    table_data.append(headers_row)

    # Filas
    for f in filas:
        d = f.to_dict()
        row_cells = []
        for c in columnas:
            val = d.get(c.clave)
            if c.clave == "cantidad_kg":
                t = f"{val:,.2f} kg" if val is not None else "-"
                row_cells.append(Paragraph(t, style_td_right))
            elif c.clave == "puntaje_taza":
                t = f"{val:.2f}" if val is not None else "-"
                row_cells.append(Paragraph(t, style_td_right))
            elif c.clave == "humedad":
                t = f"{val:.1f}%" if val is not None else "-"
                row_cells.append(Paragraph(t, style_td_right))
            elif c.clave == "precio_referencial":
                t = f"${val:,.0f}" if val is not None else "-"
                row_cells.append(Paragraph(t, style_td_right))
            elif c.alineacion == "center":
                row_cells.append(Paragraph(str(val or "-"), style_td_center))
            else:
                row_cells.append(Paragraph(str(val or "-"), style_td))
        table_data.append(row_cells)

    # Fila de totales
    tot_row = [
        Paragraph("", style_td),
        Paragraph("<b>TOTALES</b>", style_td_center),
        Paragraph("", style_td),
        Paragraph("", style_td),
        Paragraph("", style_td),
        Paragraph("", style_td),
        Paragraph("", style_td),
        Paragraph(f"<b>{totales['total_kilos']:,.2f} kg</b>", style_td_total),
        Paragraph(f"<b>{totales['promedio_puntaje_taza'] or '-'}" + (" pts</b>" if totales['promedio_puntaje_taza'] else "</b>"), style_td_total),
        Paragraph("", style_td),
        Paragraph("", style_td),
        Paragraph(f"<b>${totales['promedio_precio']:,.0f}</b>" if totales['promedio_precio'] else "<b>-</b>", style_td_total),
        Paragraph("", style_td),
    ]
    table_data.append(tot_row)

    tabla = Table(table_data, colWidths=col_widths, repeatRows=1)
    tabla.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4A2C2A")),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F9F7F5")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDE6E3")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#4A2C2A")),
            ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.HexColor("#4A2C2A")),
        ])
    )
    story.append(tabla)
    story.append(Spacer(1, 10))

    # Nota legal de pie
    nota_legal = (
        "Documento emitido electrónicamente por el Sistema Café Pérgamo — Universidad Francisco de Paula Santander (UFPS). "
        "La información de trazabilidad física y sensorial aquí consignada es certificada conforme al régimen estatutario de datos (Ley 1581 de 2012)."
    )
    story.append(Paragraph(nota_legal, style_meta))

    doc.build(story, canvasmaker=NumberedCanvas)
    return output.getvalue()
