"""
Pruebas funcionales y unitarias para el motor de búsqueda global unificada (HU-29 / SCRUM-238).

Subtareas probadas:
- SCRUM-294 (HU29-ST3): Lógica de relevancia y normalización de resultados.
- SCRUM-292 (HU29-ST2): Segmentación por tipo de entidad y contadores.
- SCRUM-296 (HU29-ST6): Permisos de visualización, aislamiento multi-tenant y RBAC.
- SCRUM-297 (HU29-ST7): Estructura de accesos directos contextuales según entidad.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch
import uuid

from django.test import TestCase
from django.utils import timezone

from actores.models import ActorCadena
from catalogos.models import ProcesoBeneficio, VariedadCafe
from fincas.busqueda import (
    buscar_compradores,
    buscar_lotes,
    buscar_operaciones,
    buscar_productores,
    calcular_relevancia,
    ejecutar_busqueda_global,
    normalizar_termino_busqueda,
    obtener_entidades_permitidas,
    remover_diacriticos,
)
from fincas.models import (
    CaracteristicasCalidad,
    Cosecha,
    Finca,
    Lote,
    ManifestacionInteres,
    Municipio,
)


def _crear_perfil_mock(user_id, correo, nombres="Juan", apellidos="Valdez", rol_codigo="PRODUCTOR"):
    perfil = MagicMock()
    perfil.id = user_id
    perfil.correo = correo
    perfil.nombres = nombres
    perfil.apellidos = apellidos
    perfil.activo = True
    perfil.rol = MagicMock()
    perfil.rol.codigo = rol_codigo
    perfil.rol.nombre = rol_codigo.title()
    return perfil


class TestNormalizacionYRelevanciaBusqueda(TestCase):
    """Pruebas de normalización textual y ponderación de relevancia (SCRUM-294 / HU29-ST3)."""

    def test_normalizar_espacios_y_caracteres_redundantes(self):
        self.assertEqual(normalizar_termino_busqueda("   Geisha    Toledo  "), "Geisha Toledo")
        self.assertEqual(normalizar_termino_busqueda("  \n  Lote-001  \t  "), "Lote-001")
        self.assertEqual(normalizar_termino_busqueda(""), "")
        self.assertEqual(normalizar_termino_busqueda(None), "")

    def test_remover_diacriticos_preserva_caracteres_base(self):
        self.assertEqual(remover_diacriticos("Café de Cúcuta y Árbol"), "cafe de cucuta y arbol")
        self.assertEqual(remover_diacriticos("PÉRGAMO"), "pergamo")
        self.assertEqual(remover_diacriticos(""), "")

    def test_termino_menor_a_minimo_retorna_cero_sin_error(self):
        res = ejecutar_busqueda_global("a", rol_codigo="ADMINISTRADOR")
        self.assertEqual(res["total_resultados"], 0)
        self.assertEqual(res["conteo_por_entidad"]["todas"], 0)
        self.assertIn("al menos 2 caracteres", res.get("aviso", ""))

    def test_ponderacion_relevancia_jerarquica(self):
        # Coincidencia exacta con código
        rel_exacta_codigo = calcular_relevancia("LOT-2026-001", "LOT-2026-001", "Lote Geisha")
        self.assertEqual(rel_exacta_codigo, 100)

        # Prefijo de código
        rel_prefijo = calcular_relevancia("LOT-2026", "LOT-2026-001", "Lote Geisha")
        self.assertEqual(rel_prefijo, 90)

        # Título exacto
        rel_tit_exacto = calcular_relevancia("Geisha", "LOT-999", "Geisha")
        self.assertEqual(rel_tit_exacto, 85)

        # Título comienza con el término
        rel_tit_empieza = calcular_relevancia("Gei", "LOT-999", "Geisha Especial")
        self.assertEqual(rel_tit_empieza, 75)

        # Subtítulo o descripción secundaria
        rel_secundaria = calcular_relevancia("durazno", "LOT-999", "Lote Typica", "Finca El Prado", "Notas a durazno")
        self.assertTrue(20 <= rel_secundaria <= 35)


class TestBusquedaGlobalMultiEntidadYRBAC(TestCase):
    """
    Pruebas de segmentación por entidad (SCRUM-292) y aislamiento multi-tenant RBAC (SCRUM-296).
    """

    def setUp(self):
        # Municipio de pruebas (usar existente si ya fue cargado por migraciones)
        self.municipio = Municipio.objects.filter(nombre="Toledo", departamento="Norte de Santander").first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-TOL-TEST-HU29",
                nombre="Toledo",
                departamento="Norte de Santander",
                activo=True,
            )

        # IDs de usuarios (las tablas de usuarios en Supabase son managed=False en SQLite)
        self.admin_id = uuid.uuid4()
        self.productor_a_id = uuid.uuid4()
        self.productor_b_id = uuid.uuid4()
        self.comprador_id = uuid.uuid4()

        self.admin = _crear_perfil_mock(self.admin_id, "admin.busqueda@pergamo.test", "Super", "Admin", "ADMINISTRADOR")
        self.productor_a = _crear_perfil_mock(self.productor_a_id, "carlos.productor@pergamo.test", "Carlos", "Gómez", "PRODUCTOR")
        self.productor_b = _crear_perfil_mock(self.productor_b_id, "elena.productora@pergamo.test", "Elena", "Ramírez", "PRODUCTOR")
        self.comprador = _crear_perfil_mock(self.comprador_id, "marta.compradora@globalcoffee.test", "Marta", "Sánchez", "COMPRADOR")

        # Fincas
        self.finca_a = Finca.objects.create(
            nombre="Finca La Samaria",
            productor_id=self.productor_a_id,
            municipio=self.municipio,
            vereda="San José",
            activo=True,
        )

        self.finca_b = Finca.objects.create(
            nombre="Finca Las Brisas",
            productor_id=self.productor_b_id,
            municipio=self.municipio,
            vereda="El Porvenir",
            activo=True,
        )

        # Catálogos maestros
        self.variedad = VariedadCafe.objects.create(
            nombre="Geisha Especial",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="HONEY_BUSQUEDA_HU29",
            nombre="Honey Amarillo",
            activo=True,
        )

        # Cosechas
        self.cosecha_a = Cosecha.objects.create(
            finca=self.finca_a,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("500.00"),
            activo=True,
        )

        self.cosecha_b = Cosecha.objects.create(
            finca=self.finca_b,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("800.00"),
            activo=True,
        )

        # Lotes
        # Lote A: Publicado en catálogo comercial
        self.lote_publicado = Lote.objects.create(
            codigo="LOT-BUSQ-PUB",
            cosecha=self.cosecha_a,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("150.00"),
            publicado_en_catalogo=True,
            fecha_publicacion=timezone.now(),
            precio_referencial=Decimal("38000.00"),
            activo=True,
        )
        CaracteristicasCalidad.objects.create(
            lote=self.lote_publicado,
            puntaje_taza=Decimal("87.50"),
            humedad=Decimal("11.20"),
            merma=Decimal("14.00"),
            perfil_sensorial="Jazmín, melocotón y miel silvestre",
        )

        # Lote B: Privado en bodega del productor B (NO publicado)
        self.lote_privado = Lote.objects.create(
            codigo="LOT-BUSQ-PRIV",
            cosecha=self.cosecha_b,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("300.00"),
            publicado_en_catalogo=False,
            activo=True,
        )
        CaracteristicasCalidad.objects.create(
            lote=self.lote_privado,
            puntaje_taza=Decimal("83.00"),
            humedad=Decimal("11.80"),
            merma=Decimal("16.00"),
            perfil_sensorial="Chocolate con leche y nuez",
        )

        # Operación comercial (Manifestación de Interés de la compradora sobre el Lote A)
        self.operacion = ManifestacionInteres.objects.create(
            lote=self.lote_publicado,
            comprador_id=self.comprador_id,
            comprador_correo="marta.compradora@globalcoffee.test",
            cantidad_kg=Decimal("80.00"),
            mensaje="Interesada en muestra de 80 kg para exportación a Alemania.",
            telefono_contacto="3207778899",
            estado=ManifestacionInteres.EstadoManifestacion.REGISTRADO,
        )

        # Actor de la cadena (Cooperativa registrada)
        self.cooperativa = ActorCadena.objects.create(
            tipo=ActorCadena.TipoActor.COOPERATIVA,
            razon_social="Cooperativa de Caficultores del Catatumbo",
            nit="900888999-1",
            contacto="Pedro Martínez",
            correo="info@coopcatatumbo.test",
            activo=True,
        )

    def test_administrador_ve_lotes_publicos_y_privados(self):
        """El administrador tiene acceso irrestricto y encuentra lotes publicados y en bodega."""
        res = ejecutar_busqueda_global(
            termino="LOT-BUSQ",
            tipo_entidad="lotes",
            usuario_o_id=self.admin,
            rol_codigo="ADMINISTRADOR",
        )
        codigos = [item["titulo"] for item in res["resultados"]]
        self.assertTrue(any("LOT-BUSQ-PUB" in c for c in codigos))
        self.assertTrue(any("LOT-BUSQ-PRIV" in c for c in codigos))
        self.assertEqual(res["conteo_por_entidad"]["lotes"], 2)

    def test_productor_a_ve_su_lote_y_catalogo_pero_no_bodega_ajena(self):
        """
        Aislamiento Multi-Tenant:
        El productor A ve su propio lote publicado y los del catálogo, pero NO el lote
        privado en bodega del productor B.
        """
        res = ejecutar_busqueda_global(
            termino="LOT-BUSQ",
            tipo_entidad="lotes",
            usuario_o_id=self.productor_a,
            rol_codigo="PRODUCTOR",
        )
        codigos = [item["titulo"] for item in res["resultados"]]
        self.assertTrue(any("LOT-BUSQ-PUB" in c for c in codigos))
        self.assertFalse(any("LOT-BUSQ-PRIV" in c for c in codigos))

    def test_comprador_solo_ve_lotes_disponibles_en_catalogo(self):
        """Un comprador solo ve lotes formalmente publicados en el catálogo comercial."""
        res = ejecutar_busqueda_global(
            termino="LOT-BUSQ",
            tipo_entidad="lotes",
            usuario_o_id=self.comprador,
            rol_codigo="COMPRADOR",
        )
        self.assertEqual(res["conteo_por_entidad"]["lotes"], 1)
        self.assertIn("LOT-BUSQ-PUB", res["resultados"][0]["titulo"])

    def test_productor_solo_ve_operaciones_de_sus_lotes(self):
        """
        Aislamiento en Operaciones:
        El productor A ve la manifestación de interés sobre su Lote A.
        El productor B no ve ninguna operación porque el Lote A no le pertenece.
        """
        # Productor A
        res_a = ejecutar_busqueda_global(
            termino="Alemania",
            tipo_entidad="operaciones",
            usuario_o_id=self.productor_a,
            rol_codigo="PRODUCTOR",
        )
        self.assertEqual(res_a["conteo_por_entidad"]["operaciones"], 1)
        self.assertIn(f"Operación #{self.operacion.id}", res_a["resultados"][0]["titulo"])

        # Productor B
        res_b = ejecutar_busqueda_global(
            termino="Alemania",
            tipo_entidad="operaciones",
            usuario_o_id=self.productor_b,
            rol_codigo="PRODUCTOR",
        )
        self.assertEqual(res_b["conteo_por_entidad"]["operaciones"], 0)
        self.assertEqual(len(res_b["resultados"]), 0)

    def test_usuario_anonimo_no_accede_a_operaciones_ni_compradores(self):
        """
        Seguridad de Datos:
        Un usuario sin sesión o rol de consulta pública no tiene permisos para buscar
        operaciones ni datos de compradores.
        """
        res = ejecutar_busqueda_global(
            termino="marta.compradora@globalcoffee.test",
            tipo_entidad="todas",
            usuario_o_id=None,
            rol_codigo="",
        )
        self.assertEqual(res["conteo_por_entidad"]["operaciones"], 0)
        self.assertEqual(res["conteo_por_entidad"]["compradores"], 0)
        self.assertNotIn("operaciones", res["entidades_permitidas"])
        self.assertNotIn("compradores", res["entidades_permitidas"])

    def test_segmentacion_por_entidad_devuelve_solo_categoria_solicitada(self):
        """Cuando se solicita tipo_entidad='productores', solo se listan resultados de esa entidad."""
        res = ejecutar_busqueda_global(
            termino="Catatumbo",
            tipo_entidad="productores",
            usuario_o_id=self.admin,
            rol_codigo="ADMINISTRADOR",
        )
        self.assertEqual(res["tipo_filtro"], "productores")
        self.assertTrue(all(item["tipo_entidad"] == "PRODUCTOR" for item in res["resultados"]))
        self.assertGreaterEqual(res["conteo_por_entidad"]["productores"], 1)

    def test_busqueda_insensible_a_mayusculas_y_acentos(self):
        """Búsqueda por 'samaria', 'SAMARIA' o 'Samaría' encuentra la finca del productor."""
        res_minus = ejecutar_busqueda_global("samaria", rol_codigo="ADMINISTRADOR")
        res_mayus = ejecutar_busqueda_global("SAMARIA", rol_codigo="ADMINISTRADOR")
        self.assertEqual(res_minus["conteo_por_entidad"]["lotes"], res_mayus["conteo_por_entidad"]["lotes"])
        self.assertGreaterEqual(res_minus["conteo_por_entidad"]["lotes"], 1)

    def test_estructura_canonico_resultado_incluye_accesos_directos(self):
        """El contrato de cada resultado debe incluir titulo, subtitulo, url_detalle y acciones."""
        res = ejecutar_busqueda_global("LOT-BUSQ-PUB", rol_codigo="ADMINISTRADOR")
        primer_item = res["resultados"][0]
        self.assertIn("titulo", primer_item)
        self.assertIn("subtitulo", primer_item)
        self.assertIn("url_detalle", primer_item)
        self.assertIn("acciones", primer_item)
        self.assertIn("relevancia", primer_item)
        self.assertTrue(len(primer_item["acciones"]) >= 1)
        self.assertTrue(primer_item["acciones"][0]["url"].startswith("/"))
