"""
Suite de pruebas automatizadas para la exportación de reportes en PDF y Excel (HU-27 / SCRUM-236).

Subtareas verificadas:
- SCRUM-304 (HU27-ST1): Diseñar la experiencia de exportación de reportes (UI, dropdowns, WCAG 2.1 AA).
- SCRUM-305 (HU27-ST2): Definir el formato y estructura canónica del reporte exportado (metadatos, columnas, totales).
- SCRUM-306 (HU27-ST3): Asegurar que la exportación respete los filtros activos.
- SCRUM-307 (HU27-ST4): Generación binaria y validación de hojas de cálculo Excel (.xlsx con openpyxl).
- SCRUM-308 (HU27-ST5): Generación binaria y validación de documentos PDF (.pdf con ReportLab).
- SCRUM-309 (HU27-ST6): Validar permisos RBAC ('reportes.generar') y aislamiento multi-tenant.
- SCRUM-310 (HU27-ST7): Batería completa de pruebas funcionales y de integración.
"""

from decimal import Decimal
import io
from unittest.mock import MagicMock, patch
import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

import openpyxl

from catalogos.models import ProcesoBeneficio, VariedadCafe
from fincas.models import (
    CaracteristicasCalidad,
    Cosecha,
    Finca,
    Lote,
    Municipio,
)
from fincas.reportes import (
    COLUMNAS_REPORTE_LOTES,
    generar_reporte_lotes_excel,
    generar_reporte_lotes_pdf,
    obtener_datos_reporte_lotes,
)
from usuarios.tests import MATRIZ_RBAC_VIGENTE, _mockear_matriz_real


def _obtener_o_crear_municipio(nombre, codigo=""):
    mun = Municipio.objects.filter(nombre__iexact=nombre, departamento="Norte de Santander").first()
    if not mun:
        mun = Municipio.objects.create(
            nombre=nombre,
            departamento="Norte de Santander",
            codigo=codigo or f"MUN-{nombre.upper()[:4]}",
            activo=True,
        )
    return mun


class TestReportesEstructuraYGeneradoresUnitarios(TestCase):
    """Pruebas unitarias para la especificación canónica y generadores binarios (SCRUM-305, 307, 308)."""

    def setUp(self):
        self.municipio = _obtener_o_crear_municipio("Toledo", "54820")
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Esperanza",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="Román",
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Castillo Tambo",
            defaults={"especie": VariedadCafe.Especie.ARABICA, "activo": True},
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="LAVADO_EXP_HU27",
            defaults={"nombre": "Lavado Tradicional", "activo": True},
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("600.00"),
            activo=True,
        )
        self.lote1 = Lote.objects.create(
            codigo="LOT-EXP-001",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("250.00"),
            publicado_en_catalogo=True,
            fecha_publicacion=timezone.now(),
            precio_referencial=Decimal("42000.00"),
            activo=True,
        )
        CaracteristicasCalidad.objects.create(
            lote=self.lote1,
            puntaje_taza=Decimal("86.75"),
            humedad=Decimal("10.80"),
        )

        self.lote2 = Lote.objects.create(
            codigo="LOT-EXP-002",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("150.00"),
            publicado_en_catalogo=False,
            fecha_publicacion=None,
            precio_referencial=Decimal("35000.00"),
            activo=True,
        )
        CaracteristicasCalidad.objects.create(
            lote=self.lote2,
            puntaje_taza=Decimal("84.50"),
            humedad=Decimal("11.50"),
        )

    def test_especificacion_columnas_canonicas_13_columnas(self):
        """Verifica que la especificación canónica contenga exactamente las 13 columnas requeridas."""
        self.assertEqual(len(COLUMNAS_REPORTE_LOTES), 13)
        claves_esperadas = [
            "indice", "codigo", "finca_nombre", "vereda", "municipio",
            "variedad", "proceso", "cantidad_kg", "puntaje_taza", "humedad",
            "estado_display", "precio_referencial", "fecha",
        ]
        claves_reales = [c.clave for c in COLUMNAS_REPORTE_LOTES]
        self.assertEqual(claves_reales, claves_esperadas)

        for col in COLUMNAS_REPORTE_LOTES:
            self.assertTrue(col.encabezado)
            self.assertGreater(col.ancho_excel, 0)
            self.assertGreater(col.ancho_pdf, 0)
            self.assertIn(col.alineacion, ("left", "center", "right"))

    def test_extractor_datos_reporte_con_lotes(self):
        """Verifica que el extractor compile filas, metadatos y totales correctamente."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_id,
            rol_codigo="PRODUCTOR",
        )
        metadata = datos["metadata"]
        filas = datos["filas"]
        totales = datos["totales"]

        self.assertEqual(len(filas), 2)
        self.assertEqual(totales["total_lotes"], 2)
        self.assertEqual(totales["total_kilos"], Decimal("400.00"))
        # Promedio SCA: (86.75 + 84.50) / 2 = 85.625
        self.assertIn(totales["promedio_puntaje_taza"], (Decimal("85.62"), Decimal("85.63")))
        self.assertIn("CAFÉ PÉRGAMO", metadata["titulo"])
        self.assertEqual(metadata["total_registros"], 2)

    def test_extractor_datos_reporte_vacio(self):
        """Verifica que un reporte sin resultados maneje ceros sin errores de división."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_id,
            rol_codigo="PRODUCTOR",
            filtros={"finca": 999999},
        )
        self.assertEqual(len(datos["filas"]), 0)
        self.assertEqual(datos["totales"]["total_lotes"], 0)
        self.assertEqual(datos["totales"]["total_kilos"], Decimal("0.00"))
        self.assertIsNone(datos["totales"]["promedio_puntaje_taza"])
        self.assertIsNone(datos["totales"]["promedio_precio"])

    def test_generador_excel_genera_workbook_valido(self):
        """Verifica que generar_reporte_lotes_excel devuelva un archivo binario .xlsx válido."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_id,
            rol_codigo="PRODUCTOR",
        )
        xlsx_bytes = generar_reporte_lotes_excel(datos)
        self.assertIsInstance(xlsx_bytes, bytes)
        self.assertGreater(len(xlsx_bytes), 1000)

        # Cargar con openpyxl para verificar integridad
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        self.assertIn("Lotes de Café", wb.sheetnames)
        ws = wb["Lotes de Café"]

        # Encabezados en fila 6
        self.assertEqual(ws.cell(row=6, column=2).value, "Código Lote")
        self.assertEqual(ws.cell(row=6, column=8).value, "Cantidad (kg)")

        # Datos en fila 7 y 8
        self.assertEqual(ws.cell(row=7, column=2).value, "LOT-EXP-001")
        self.assertEqual(ws.cell(row=8, column=2).value, "LOT-EXP-002")

        # Fila de totales en fila 9
        self.assertEqual(ws.cell(row=9, column=2).value, "TOTALES / PROMEDIOS")
        self.assertEqual(ws.cell(row=9, column=8).value, 400.0)

    def test_generador_pdf_genera_documento_valido(self):
        """Verifica que generar_reporte_lotes_pdf devuelva un archivo PDF válido con cabeceras estándar."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_id,
            rol_codigo="PRODUCTOR",
        )
        pdf_bytes = generar_reporte_lotes_pdf(datos)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_excel_freeze_panes_y_propiedades_avanzadas(self):
        """Verifica que el archivo Excel generado tenga freeze panes en A7 y orientación horizontal."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_id,
            rol_codigo="PRODUCTOR",
        )
        xlsx_bytes = generar_reporte_lotes_excel(datos)
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        ws = wb["Lotes de Café"]

        self.assertEqual(ws.freeze_panes, "A7")
        self.assertEqual(ws.page_setup.orientation, ws.ORIENTATION_LANDSCAPE)
        self.assertEqual(str(ws.page_setup.paperSize), str(ws.PAPERSIZE_LETTER))

    def test_pdf_multipage_con_numbered_canvas(self):
        """Verifica que la generación de reportes extensos use NumberedCanvas para paginación dinámica."""
        # Crear 25 lotes adicionales para provocar múltiples páginas
        for i in range(10, 35):
            l = Lote.objects.create(
                codigo=f"LOT-MP-{i:03d}",
                cosecha=self.cosecha,
                proceso_beneficio=self.proceso,
                cantidad=Decimal("100.00"),
                activo=True,
            )
            CaracteristicasCalidad.objects.create(lote=l, puntaje_taza=Decimal("85.00"), humedad=Decimal("11.0"))

        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_id,
            rol_codigo="PRODUCTOR",
        )
        pdf_bytes = generar_reporte_lotes_pdf(datos)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 3000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))


class TestFiltrosYAislamientoMultiTenantReportes(TestCase):
    """Pruebas para el respeto de filtros activos y aislamiento multi-tenant (SCRUM-306, SCRUM-309)."""

    def setUp(self):
        self.mun_toledo = _obtener_o_crear_municipio("Toledo", "54820")
        self.mun_arboledas = _obtener_o_crear_municipio("Arboledas", "54051")

        self.productor_a = uuid.uuid4()
        self.productor_b = uuid.uuid4()

        self.finca_a1 = Finca.objects.create(nombre="Finca La Esperanza", productor_id=self.productor_a, municipio=self.mun_toledo, vereda="Román", activo=True)
        self.finca_a2 = Finca.objects.create(nombre="Finca El Edén", productor_id=self.productor_a, municipio=self.mun_arboledas, vereda="Siravita", activo=True)
        self.finca_b = Finca.objects.create(nombre="Finca San Pedro", productor_id=self.productor_b, municipio=self.mun_toledo, vereda="Castro", activo=True)

        self.var_castillo, _ = VariedadCafe.objects.get_or_create(nombre="Castillo Tambo", defaults={"especie": VariedadCafe.Especie.ARABICA, "activo": True})
        self.var_geisha, _ = VariedadCafe.objects.get_or_create(nombre="Geisha", defaults={"especie": VariedadCafe.Especie.ARABICA, "activo": True})

        self.proc_lavado, _ = ProcesoBeneficio.objects.get_or_create(codigo="LAV_H27", defaults={"nombre": "Lavado", "activo": True})
        self.proc_natural, _ = ProcesoBeneficio.objects.get_or_create(codigo="NAT_H27", defaults={"nombre": "Natural", "activo": True})

        self.cosecha_a1 = Cosecha.objects.create(finca=self.finca_a1, variedad=self.var_castillo, fecha_cosecha=timezone.now().date(), cantidad_total=Decimal("500"), activo=True)
        self.cosecha_a2 = Cosecha.objects.create(finca=self.finca_a2, variedad=self.var_geisha, fecha_cosecha=timezone.now().date(), cantidad_total=Decimal("300"), activo=True)
        self.cosecha_b = Cosecha.objects.create(finca=self.finca_b, variedad=self.var_castillo, fecha_cosecha=timezone.now().date(), cantidad_total=Decimal("700"), activo=True)

        self.lote_a1 = Lote.objects.create(
            codigo="LOT-FLT-A1", cosecha=self.cosecha_a1, proceso_beneficio=self.proc_lavado,
            cantidad=Decimal("200.00"), publicado_en_catalogo=True, activo=True, precio_referencial=Decimal("40000"),
        )
        CaracteristicasCalidad.objects.create(lote=self.lote_a1, puntaje_taza=Decimal("87.00"), humedad=Decimal("11.0"))

        self.lote_a2 = Lote.objects.create(
            codigo="LOT-FLT-A2", cosecha=self.cosecha_a2, proceso_beneficio=self.proc_natural,
            cantidad=Decimal("150.00"), publicado_en_catalogo=False, activo=True, precio_referencial=Decimal("48000"),
        )
        CaracteristicasCalidad.objects.create(lote=self.lote_a2, puntaje_taza=Decimal("89.50"), humedad=Decimal("10.5"))

        self.lote_b = Lote.objects.create(
            codigo="LOT-FLT-B1", cosecha=self.cosecha_b, proceso_beneficio=self.proc_lavado,
            cantidad=Decimal("300.00"), publicado_en_catalogo=True, activo=True, precio_referencial=Decimal("36000"),
        )
        CaracteristicasCalidad.objects.create(lote=self.lote_b, puntaje_taza=Decimal("84.00"), humedad=Decimal("11.8"))

    def test_aislamiento_multitenant_productor_a(self):
        """El Productor A solo ve sus propios lotes (A1 y A2) y nunca los de otros productores (B1)."""
        datos = obtener_datos_reporte_lotes(usuario=self.productor_a, rol_codigo="PRODUCTOR")
        codigos = [f.codigo for f in datos["filas"]]
        self.assertIn("LOT-FLT-A1", codigos)
        self.assertIn("LOT-FLT-A2", codigos)
        self.assertNotIn("LOT-FLT-B1", codigos)

    def test_aislamiento_multitenant_productor_b(self):
        """El Productor B solo ve su lote B1."""
        datos = obtener_datos_reporte_lotes(usuario=self.productor_b, rol_codigo="PRODUCTOR")
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-B1"])

    def test_administrador_accede_a_todos_los_lotes(self):
        """El Administrador puede ver el consolidado total de todos los productores."""
        datos = obtener_datos_reporte_lotes(rol_codigo="ADMINISTRADOR")
        codigos = [f.codigo for f in datos["filas"]]
        self.assertIn("LOT-FLT-A1", codigos)
        self.assertIn("LOT-FLT-A2", codigos)
        self.assertIn("LOT-FLT-B1", codigos)

    def test_filtro_por_finca(self):
        """El filtro finca limita las filas exclusivamente a los lotes de dicho predio."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_a,
            rol_codigo="PRODUCTOR",
            filtros={"finca": self.finca_a1.id},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A1"])

    def test_filtro_por_municipio(self):
        """El filtro municipio filtra adecuadamente lotes por ubicación geográfica."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"municipio": self.mun_arboledas.id},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A2"])

    def test_filtro_por_variedad(self):
        """El filtro variedad restringe el reporte a la variedad de café seleccionada."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"variedad": self.var_geisha.id},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A2"])

    def test_filtro_por_proceso(self):
        """El filtro proceso limita el reporte al método de beneficio especificado."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"proceso": self.proc_natural.id},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A2"])

    def test_filtro_por_puntaje_sca_minimo(self):
        """El filtro puntaje_min descarta lotes con calidad sensorial inferior."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"puntaje_min": "88.0"},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A2"])

    def test_filtro_solo_publicados_en_catalogo(self):
        """El filtro publicado=True incluye solo lotes activos en vitrina comercial."""
        datos = obtener_datos_reporte_lotes(
            usuario=self.productor_a,
            rol_codigo="PRODUCTOR",
            filtros={"publicado": True},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A1"])

    def test_filtro_por_busqueda_libre_q(self):
        """El filtro q busca por subcadena insensible a mayúsculas en código o finca."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"q": "Edén"},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A2"])

    def test_filtro_por_busqueda_en_perfil_sensorial(self):
        """El filtro q busca también dentro del perfil sensorial del lote."""
        self.lote_a1.caracteristicas_calidad.perfil_sensorial = "Notas a chocolate oscuro y avellanas tostadas"
        self.lote_a1.caracteristicas_calidad.save()

        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"q": "avellanas"},
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A1"])

    def test_filtros_combinados_multicriterio(self):
        """Múltiples filtros aplicados en conjunto operan con lógica AND (SCRUM-306)."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={
                "municipio": self.mun_arboledas.id,
                "variedad": self.var_geisha.id,
                "proceso": self.proc_natural.id,
                "puntaje_min": "88.0",
            },
        )
        codigos = [f.codigo for f in datos["filas"]]
        self.assertEqual(codigos, ["LOT-FLT-A2"])
        self.assertIn("Municipio: Arboledas", datos["metadata"]["filtros_texto"])
        self.assertIn("Variedad: Geisha", datos["metadata"]["filtros_texto"])

    def test_filtro_por_ordenamiento_puntaje_desc(self):
        """El parámetro orden='puntaje_desc' sitúa al lote con mayor SCA en primer lugar."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"orden": "puntaje_desc"},
        )
        codigos = [f.codigo for f in datos["filas"]]
        # LOT-FLT-A2 (89.50) > LOT-FLT-A1 (87.00) > LOT-FLT-B1 (84.00)
        self.assertEqual(codigos[0], "LOT-FLT-A2")
        self.assertEqual(codigos[-1], "LOT-FLT-B1")

    def test_filtro_por_ordenamiento_precio_asc(self):
        """El parámetro orden='precio_asc' sitúa al lote más económico en primer lugar."""
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"orden": "precio_asc"},
        )
        codigos = [f.codigo for f in datos["filas"]]
        # LOT-FLT-B1 ($36.000) < LOT-FLT-A1 ($40.000) < LOT-FLT-A2 ($48.000)
        self.assertEqual(codigos[0], "LOT-FLT-B1")
        self.assertEqual(codigos[-1], "LOT-FLT-A2")

    def test_filtro_por_rango_fechas(self):
        """Filtra lotes dentro de un rango de fechas (desde / hasta)."""
        hoy_str = timezone.now().date().isoformat()
        datos = obtener_datos_reporte_lotes(
            rol_codigo="ADMINISTRADOR",
            filtros={"desde": hoy_str, "hasta": hoy_str},
        )
        self.assertEqual(len(datos["filas"]), 3)
        self.assertIn(f"Desde: {hoy_str}", datos["metadata"]["filtros_texto"])


@patch("usuarios.models.RolPermiso")
class TestVistasExportacionReportesHTTP(TestCase):
    """Pruebas de integración HTTP para los endpoints de exportación (SCRUM-304, 307, 308, 309)."""

    def setUp(self):
        self.user_productor = User.objects.create_user(
            username="productor_export_test",
            email="productor.export@pergamo.test",
            password="TestPassword123*",
        )
        self.productor_id = uuid.uuid4()

        self.municipio = _obtener_o_crear_municipio("Toledo", "54820")
        self.finca = Finca.objects.create(nombre="Finca La María", productor_id=self.productor_id, municipio=self.municipio, vereda="San José", activo=True)
        self.variedad, _ = VariedadCafe.objects.get_or_create(nombre="Caturra", defaults={"especie": VariedadCafe.Especie.ARABICA, "activo": True})
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(codigo="WASH_HU27", defaults={"nombre": "Lavado", "activo": True})
        self.cosecha = Cosecha.objects.create(finca=self.finca, variedad=self.variedad, fecha_cosecha=timezone.now().date(), cantidad_total=Decimal("400"), activo=True)

        self.lote = Lote.objects.create(
            codigo="LOT-HTTP-001", cosecha=self.cosecha, proceso_beneficio=self.proceso,
            cantidad=Decimal("200.00"), publicado_en_catalogo=True, activo=True, precio_referencial=Decimal("39000"),
        )
        CaracteristicasCalidad.objects.create(lote=self.lote, puntaje_taza=Decimal("86.00"), humedad=Decimal("11.0"))

    def test_exportar_lotes_excel_http_200_y_headers(self, mock_rol_permiso):
        """GET /fincas/reportes/lotes/excel/ genera archivo .xlsx válido con HTTP 200."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(self.productor_id)
        session.save()

        url = reverse("exportar_lotes_excel")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertIn(".xlsx", response["Content-Disposition"])

        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        self.assertIn("Lotes de Café", wb.sheetnames)

    def test_exportar_lotes_pdf_http_200_y_headers(self, mock_rol_permiso):
        """GET /fincas/reportes/lotes/pdf/ genera documento .pdf válido con HTTP 200."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(self.productor_id)
        session.save()

        url = reverse("exportar_lotes_pdf")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline; filename=", response["Content-Disposition"])
        self.assertIn(".pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_exportar_catalogo_excel_http_200(self, mock_rol_permiso):
        """GET /fincas/reportes/catalogo/excel/ genera hoja Excel del catálogo con HTTP 200."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(self.productor_id)
        session.save()

        url = reverse("exportar_catalogo_excel")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("catalogo_lotes_pergamo_", response["Content-Disposition"])

    def test_exportar_catalogo_pdf_http_200(self, mock_rol_permiso):
        """GET /fincas/reportes/catalogo/pdf/ genera documento PDF del catálogo con HTTP 200."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(self.productor_id)
        session.save()

        url = reverse("exportar_catalogo_pdf")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_exportar_lotes_emite_log_auditoria(self, mock_rol_permiso):
        """La generación de reportes emite logs de auditoría estructurados (SCRUM-309)."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(self.productor_id)
        session.save()

        with self.assertLogs("fincas.views", level="INFO") as cm:
            resp = self.client.get(reverse("exportar_lotes_excel"))
            self.assertEqual(resp.status_code, 200)

        self.assertTrue(any("Exportación exitosa: tipo=lotes, formato=excel" in msg for msg in cm.output))


@patch("usuarios.models.RolPermiso")
class TestSeguridadControlAccesoRBACExportacion(TestCase):
    """Pruebas de seguridad para validar el permiso 'reportes.generar' (SCRUM-309 / RNF06)."""

    def setUp(self):
        self.user_comprador = User.objects.create_user(
            username="comprador_export_test",
            email="comprador@globaltrade.test",
            password="TestPassword123*",
        )

    def test_usuario_anonimo_redirige_a_login(self, mock_rol_permiso):
        """Una petición no autenticada redirige a la vista de login con ?next=."""
        _mockear_matriz_real(mock_rol_permiso)
        url = reverse("exportar_lotes_excel")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertIn(url, response.url)

    def test_rol_comprador_sin_permiso_es_denegado(self, mock_rol_permiso):
        """El rol COMPRADOR (sin permiso 'reportes.generar') es redirigido a home con mensaje de error."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_comprador)
        session = self.client.session
        session["rol"] = "COMPRADOR"
        session.save()

        url = reverse("exportar_lotes_excel")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_rol_productor_con_permiso_es_autorizado(self, mock_rol_permiso):
        """El rol PRODUCTOR posee 'reportes.generar' y recibe HTTP 200."""
        _mockear_matriz_real(mock_rol_permiso)
        user_prod = User.objects.create_user(username="prod_ok", password="pwd")
        self.client.force_login(user_prod)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session.save()

        url = reverse("exportar_lotes_excel")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


@patch("usuarios.models.RolPermiso")
class TestExperienciaUIExportacionWCAG(TestCase):
    """Pruebas de renderizado de la UI de exportación y accesibilidad WCAG 2.1 AA (SCRUM-304)."""

    def setUp(self):
        self.user_productor = User.objects.create_user(
            username="productor_ui_test",
            email="productor.ui@pergamo.test",
            password="TestPassword123*",
        )
        self.user_comprador = User.objects.create_user(
            username="comprador_ui_test",
            email="comprador.ui@pergamo.test",
            password="TestPassword123*",
        )

    def test_mis_lotes_muestra_boton_exportar_para_productor(self, mock_rol_permiso):
        """En Mis Lotes, el menú desplegable Exportar se renderiza con WCAG 2.1 AA para productores."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(uuid.uuid4())
        session.save()

        response = self.client.get(reverse("mis_lotes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dropdownExportarLotes"')
        self.assertContains(response, 'id="btnExportarExcel"')
        self.assertContains(response, 'id="btnExportarPdf"')
        self.assertContains(response, 'aria-label="Exportar reporte de mis lotes"')
        self.assertContains(response, 'Descargar en Excel')
        self.assertContains(response, 'Descargar en PDF')

    def test_catalogo_muestra_boton_exportar_para_productor(self, mock_rol_permiso):
        """En Catálogo Comercial, el botón Exportar se renderiza para roles autorizados."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(uuid.uuid4())
        session.save()

        response = self.client.get(reverse("catalogo"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="dropdownExportarCatalogo"')
        self.assertContains(response, 'id="btnExportarCatalogoExcel"')
        self.assertContains(response, 'id="btnExportarCatalogoPdf"')
        self.assertContains(response, 'aria-label="Exportar catálogo de lotes"')

    def test_catalogo_oculta_boton_exportar_para_comprador(self, mock_rol_permiso):
        """En Catálogo Comercial, el botón Exportar se oculta para roles sin permiso 'reportes.generar'."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_comprador)
        session = self.client.session
        session["rol"] = "COMPRADOR"
        session["usuario_id"] = str(uuid.uuid4())
        session.save()

        response = self.client.get(reverse("catalogo"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="dropdownExportarCatalogo"')
        self.assertNotContains(response, 'id="btnExportarCatalogoExcel"')

    def test_mis_lotes_preserva_filtros_query_params(self, mock_rol_permiso):
        """Los enlaces de exportación en Mis Lotes preservan todos los query params activos en URL."""
        _mockear_matriz_real(mock_rol_permiso)
        self.client.force_login(self.user_productor)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session["usuario_id"] = str(uuid.uuid4())
        session.save()

        response = self.client.get(reverse("mis_lotes") + "?finca=99&q=geisha")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/fincas/reportes/lotes/excel/?finca=99&amp;q=geisha"')
        self.assertContains(response, 'href="/fincas/reportes/lotes/pdf/?finca=99&amp;q=geisha"')
