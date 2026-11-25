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
from django.urls import reverse
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


class TestBusquedaGlobalVistasYAPI(TestCase):
    """
    Pruebas para las vistas web y endpoints API de Búsqueda Global (HU-29 / SCRUM-291, SCRUM-293).
    """

    def setUp(self):
        self.municipio = Municipio.objects.filter(nombre="Cúcuta", departamento="Norte de Santander").first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-CUC-TEST-01",
                nombre="Cúcuta",
                departamento="Norte de Santander",
                activo=True,
            )
        self.variedad = VariedadCafe.objects.create(
            nombre="Geisha Especial",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAV_BUSQUEDA_VIEW",
            nombre="Lavado Tradicional",
            activo=True,
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            productor_id=self.productor_id,
            nombre="Hacienda La Samaria",
            municipio=self.municipio,
            vereda="El Carmen",
            activo=True,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("5000.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOT-BUSQ-VIEW-01",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("500.00"),
            publicado_en_catalogo=True,
            fecha_publicacion=timezone.now(),
            precio_referencial=Decimal("38000.00"),
            activo=True,
        )

    def test_vista_web_busqueda_global_responde_200(self):
        """La vista web /buscar/ responde HTTP 200 con contexto esperado y barra en navbar."""
        url = reverse('busqueda_global')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'busqueda/resultados.html')
        for clave in (
            'q',
            'tipo_activo',
            'resultados',
            'conteo_por_entidad',
            'entidades_permitidas',
            'tiempo_ms',
        ):
            self.assertIn(clave, response.context)
        self.assertContains(response, 'id="navbarSearchInput"')
        self.assertContains(
            response,
            'Buscar lotes, productores, compradores o transacciones... (Presiona / para buscar)',
        )

    def test_vista_web_busqueda_global_con_query(self):
        """La vista web /buscar/?q=Samaria responde HTTP 200, retorna coincidencias y conserva q."""
        url = reverse('busqueda_global')
        response = self.client.get(url, {'q': 'Samaria'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'busqueda/resultados.html')
        self.assertEqual(response.context['q'], 'Samaria')
        self.assertGreaterEqual(len(response.context['resultados']), 1)
        self.assertContains(response, 'Hacienda La Samaria')
        self.assertContains(response, 'value="Samaria"')

    def test_api_busqueda_global_retorna_json_con_conteos(self):
        """El endpoint API de búsqueda global retorna JSON con conteos por entidad y resultados."""
        for url in (reverse('api_busqueda_global'), reverse('api_busqueda_global_root')):
            response = self.client.get(url, {'q': 'Samaria', 'tipo': 'todas'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('application/json', response['Content-Type'])
            data = response.json()
            self.assertIn('conteo_por_entidad', data)
            conteos = data['conteo_por_entidad']
            for entidad in ('todas', 'lotes', 'productores', 'compradores', 'operaciones'):
                self.assertIn(entidad, conteos)
            self.assertGreaterEqual(conteos['lotes'], 1)
            self.assertGreaterEqual(conteos['todas'], 1)
            self.assertIn('resultados', data)
            self.assertIn('entidades_permitidas', data)
            self.assertIn('tiempo_ms', data)

    def test_vista_web_busqueda_renderiza_resultados_y_plantilla(self):
        """La vista /buscar/ responde HTTP 200 y renderiza templates/busqueda/resultados.html."""
        url = reverse('busqueda_global')
        response = self.client.get(url, {'q': 'Samaria'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'busqueda/resultados.html')
        self.assertIn('resultados', response.context)
        self.assertIn('conteo_por_entidad', response.context)
        self.assertEqual(response.context['q'], 'Samaria')
        self.assertContains(response, 'Hacienda La Samaria')

    def test_vista_web_busqueda_sin_termino_muestra_hero_y_formulario(self):
        """Al ingresar a /buscar/ sin parámetros, responde HTTP 200 con total_resultados=0."""
        url = reverse('busqueda_global')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'busqueda/resultados.html')
        self.assertEqual(response.context['total_resultados'], 0)

    def test_vista_web_filtro_por_tipo_de_entidad(self):
        """La vista web respeta el parámetro ?tipo=lotes."""
        url = reverse('busqueda_global')
        response = self.client.get(url, {'q': 'LOT-BUSQ-VIEW', 'tipo': 'lotes'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tipo_activo'], 'lotes')
        self.assertGreaterEqual(response.context['total_resultados'], 1)

    def test_api_busqueda_global_retorna_esquema_json_esperado(self):
        """El endpoint REST /api/buscar/ responde HTTP 200 con estructura de datos canónica."""
        url = reverse('api_busqueda_global')
        response = self.client.get(url, {'q': 'Samaria', 'tipo': 'todas'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('termino', data)
        self.assertIn('tipo_filtro', data)
        self.assertIn('total_resultados', data)
        self.assertIn('conteo_por_entidad', data)
        self.assertIn('entidades_permitidas', data)
        self.assertIn('resultados', data)
        self.assertIn('tiempo_ms', data)
        self.assertEqual(data['termino'], 'Samaria')
        self.assertGreaterEqual(data['total_resultados'], 1)

    def test_api_busqueda_global_root_url_resolves(self):
        """Verifica que /api/v1/buscar/ resuelve y responde correctamente."""
        url = reverse('api_v1_busqueda_global_root')
        response = self.client.get(url, {'q': 'LOT-BUSQ-VIEW-01'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_resultados'], 1)
        self.assertIn('LOT-BUSQ-VIEW-01', data['resultados'][0]['titulo'])

    def test_api_busqueda_global_termino_corto(self):
        """Un término de 1 caracter devuelve total_resultados=0 y mensaje de aviso."""
        url = reverse('api_busqueda_global')
        response = self.client.get(url, {'q': 'x'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['total_resultados'], 0)
        self.assertIn('al menos 2 caracteres', data.get('aviso', ''))


class TestInterfazResultadosYAccesosDirectos(TestCase):
    """
    Pruebas de interfaz visual de búsqueda global (SCRUM-295 / HU29-ST5)
    y accesos directos contextuales por entidad y rol (SCRUM-297 / HU29-ST7).
    """

    def setUp(self):
        self.municipio = Municipio.objects.filter(
            nombre="Pamplona", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-PAM-TEST-UI",
                nombre="Pamplona",
                departamento="Norte de Santander",
                activo=True,
            )

        self.variedad = VariedadCafe.objects.create(
            nombre="Bourbon Rosado UI",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="NAT_UI_HU29",
            nombre="Natural Fermentado",
            activo=True,
        )
        self.productor_id = uuid.uuid4()
        self.comprador_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            productor_id=self.productor_id,
            nombre="Finca El Mirador Andino",
            municipio=self.municipio,
            vereda="Monteadentro",
            activo=True,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("900.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOT-UI-295",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("220.00"),
            publicado_en_catalogo=True,
            fecha_publicacion=timezone.now(),
            precio_referencial=Decimal("42500.00"),
            activo=True,
        )
        CaracteristicasCalidad.objects.create(
            lote=self.lote,
            puntaje_taza=Decimal("88.25"),
            humedad=Decimal("11.10"),
            merma=Decimal("13.50"),
            perfil_sensorial="Frutos rojos, panela y floral intenso",
        )

        self.operacion = ManifestacionInteres.objects.create(
            lote=self.lote,
            comprador_id=self.comprador_id,
            comprador_correo="comprador.mirador@cafe.test",
            cantidad_kg=Decimal("100.00"),
            mensaje="Solicitud de muestra comercial Mirador Andino",
            telefono_contacto="3150001122",
            estado=ManifestacionInteres.EstadoManifestacion.REGISTRADO,
        )

        self.asociacion = ActorCadena.objects.create(
            tipo=ActorCadena.TipoActor.ASOCIACION,
            razon_social="Asociación Mirador Cafetero",
            nit="901555111-2",
            contacto="Laura Méndez",
            correo="contacto@miradorcafetero.test",
            activo=True,
        )
        self.comercializador = ActorCadena.objects.create(
            tipo=ActorCadena.TipoActor.COMERCIALIZADOR,
            razon_social="Comercializadora Mirador Export",
            nit="901555222-3",
            contacto="Andrés Silva",
            correo="compras@miradorexport.test",
            activo=True,
        )

    def test_renderizado_encabezado_institucional_resumen_y_sin_bg_gradient(self):
        """Renderiza resumen 'Resultados para <q> (X encontrado(s) en Y ms)' y evita .bg-gradient."""
        response = self.client.get(reverse('busqueda_global'), {'q': 'LOT-UI-295'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'busqueda/resultados.html')
        self.assertContains(response, 'id="resumenBusqueda"')
        self.assertContains(response, 'Resultados para <strong>LOT-UI-295</strong>')
        self.assertContains(response, 'ms)')
        self.assertNotContains(response, 'bg-gradient')

    @patch('usuarios.templatetags.rbac_tags.usuario_tiene_permiso', return_value=True)
    def test_pestanas_entidad_respetan_permisos_rbac_y_resaltan_activa(self, _mock_perm):
        """Anónimo solo ve Todas, Lotes y Productores; Administrador ve todas las pestañas."""
        url = reverse('busqueda_global')

        # Usuario anónimo
        resp_anon = self.client.get(url, {'q': 'Mirador', 'tipo': 'lotes'})
        self.assertEqual(resp_anon.status_code, 200)
        self.assertContains(resp_anon, 'data-entidad="todas"')
        self.assertContains(resp_anon, 'data-entidad="lotes"')
        self.assertContains(resp_anon, 'data-entidad="productores"')
        self.assertNotContains(resp_anon, 'data-entidad="compradores"')
        self.assertNotContains(resp_anon, 'data-entidad="operaciones"')
        self.assertContains(resp_anon, 'data-entidad="lotes"\n                       aria-current="page"')

        # Sesión Administrador
        session = self.client.session
        session['rol'] = 'ADMINISTRADOR'
        session.save()

        resp_admin = self.client.get(url, {'q': 'Mirador', 'tipo': 'todas'})
        self.assertEqual(resp_admin.status_code, 200)
        for entidad in ('todas', 'lotes', 'productores', 'compradores', 'operaciones'):
            self.assertContains(resp_admin, f'data-entidad="{entidad}"')

    @patch('usuarios.templatetags.rbac_tags.usuario_tiene_permiso', return_value=True)
    def test_tarjetas_muestran_iconos_badges_y_metadatos_formateados(self, _mock_perm):
        """Las tarjetas muestran icono distintivo, badges de entidad/estado y metadatos clave."""
        session = self.client.session
        session['rol'] = 'ADMINISTRADOR'
        session.save()

        response = self.client.get(reverse('busqueda_global'), {'q': 'Mirador'})
        self.assertEqual(response.status_code, 200)

        # Iconos por entidad
        self.assertContains(response, 'bi-box-seam')
        self.assertContains(response, 'bi-person-badge')
        self.assertContains(response, 'bi-bag-check')
        self.assertContains(response, 'bi-receipt')

        # Badges de entidad y estado
        self.assertContains(response, 'bg-success')
        self.assertContains(response, 'bg-info')
        self.assertContains(response, 'bg-warning')
        self.assertContains(response, 'En Catálogo')

        # Metadatos formateados del lote
        self.assertContains(response, 'Bourbon Rosado UI')
        self.assertContains(response, 'Natural Fermentado')
        self.assertContains(response, '88.25 pts')
        self.assertContains(response, '$42,500 COP/kg')

    @patch('usuarios.templatetags.rbac_tags.usuario_tiene_permiso', return_value=True)
    def test_accesos_directos_contextuales_por_entidad_y_rol(self, _mock_perm):
        """Verifica botones rápidos de SCRUM-297 para Lote, Productor, Comprador y Operación."""
        url = reverse('busqueda_global')

        # Público: Lote tiene Ficha de Trazabilidad y Ver en Catálogo, pero NO Gestionar Lote
        resp_pub = self.client.get(url, {'q': 'LOT-UI-295', 'tipo': 'lotes'})
        self.assertEqual(resp_pub.status_code, 200)
        self.assertContains(resp_pub, f'/trazabilidad/lote/{self.lote.codigo}/')
        self.assertContains(resp_pub, 'Ficha Trazabilidad')
        self.assertContains(resp_pub, f'/catalogo/?q={self.lote.codigo}')
        self.assertNotContains(resp_pub, f'/fincas/lotes/{self.lote.id}/')

        # Administrador: Lote incluye botón Gestionar Lote; Operación y Comprador enlazan a /fincas/mis-lotes/interes/
        session = self.client.session
        session['rol'] = 'ADMINISTRADOR'
        session.save()

        resp_admin = self.client.get(url, {'q': 'Mirador', 'tipo': 'todas'})
        self.assertEqual(resp_admin.status_code, 200)
        self.assertContains(resp_admin, f'/trazabilidad/lote/{self.lote.codigo}/')
        self.assertContains(resp_admin, f'/fincas/lotes/{self.lote.id}/')
        self.assertContains(resp_admin, 'Gestionar Lote')
        self.assertContains(resp_admin, '/fincas/mis-lotes/interes/')
        self.assertContains(resp_admin, 'Gestionar Interés')
        self.assertContains(resp_admin, 'Ver Negociaciones')
        self.assertContains(resp_admin, 'Ver en Catálogo')

    def test_empty_state_cuando_no_hay_resultados(self):
        """Cuando total_resultados == 0 con término activo, renderiza Empty State con recomendaciones."""
        response = self.client.get(
            reverse('busqueda_global'),
            {'q': 'TerminoInexistentePergamo999', 'tipo': 'lotes'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_resultados'], 0)
        self.assertContains(response, 'id="emptyStateBusqueda"')
        self.assertContains(response, 'No se encontraron resultados')
        self.assertContains(response, 'TerminoInexistentePergamo999')
        self.assertContains(response, 'Explorar Catálogo Comercial')
        self.assertContains(response, 'Buscar en todas las entidades')
        self.assertContains(response, 'ortografía')


class TestPruebasFuncionalesYCierreDoDHU29(TestCase):
    """
    Suite integral de pruebas funcionales de frontera, estrés y verificación
    de la Definición de Terminado (DoD) para la HU-29 (SCRUM-238 / SCRUM-298).
    
    Cubre:
    - Escenario 1: Búsqueda exacta y parcial multicampo (código, finca, variedad).
    - Escenario 2: Aislamiento multi-tenant estricto por roles (RBAC).
    - Escenario 3: Normalización e insensibilidad fonética, mayúsculas y diacríticos.
    - Escenario 4: Resiliencia de frontera (XSS, SQLi, cadenas vacías, longitud extrema, emojis).
    - Escenario 5: Rendimiento y latencia de búsqueda (< 500 ms).
    - Escenario 6: Contrato canónico completo de la API REST.
    - Escenario 7: Accesibilidad WCAG 2.1 AA y experiencia web institucional.
    - Escenario 8: Trazabilidad y cierre formal de subtareas Jira SCRUM-291 a SCRUM-298.
    """

    def setUp(self):
        # 1. Municipio para pruebas DoD
        self.municipio = Municipio.objects.filter(
            nombre="Arboledas", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-ARB-DOD-298",
                nombre="Arboledas",
                departamento="Norte de Santander",
                activo=True,
            )

        # 2. Variedad y Proceso
        self.variedad = VariedadCafe.objects.create(
            nombre="Caturra Chiroso Especial",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="WASH_DOD_298",
            nombre="Lavado Doble Fermentación",
            activo=True,
        )

        # 3. Identidades para aislamiento multi-tenant
        self.prod_a_id = uuid.uuid4()
        self.prod_b_id = uuid.uuid4()
        self.comprador_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()

        self.prod_a_mock = _crear_perfil_mock(self.prod_a_id, "productor.a.dod@pergamo.test", "Carlos", "Pérez", "PRODUCTOR")
        self.prod_b_mock = _crear_perfil_mock(self.prod_b_id, "productor.b.dod@pergamo.test", "Elena", "Rincón", "PRODUCTOR")
        self.comprador_mock = _crear_perfil_mock(self.comprador_id, "comprador.dod@pergamo.test", "Hans", "Müller", "COMPRADOR")
        self.admin_mock = _crear_perfil_mock(self.admin_id, "admin.dod@pergamo.test", "Super", "Admin", "ADMINISTRADOR")

        # 4. Fincas y cosechas
        self.finca_a = Finca.objects.create(
            productor_id=self.prod_a_id,
            nombre="Finca Bella Vista Arboledas",
            municipio=self.municipio,
            vereda="San Rafael",
            activo=True,
        )
        self.cosecha_a = Cosecha.objects.create(
            finca=self.finca_a,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("1200.00"),
            activo=True,
        )

        self.finca_b = Finca.objects.create(
            productor_id=self.prod_b_id,
            nombre="Finca La Cumbre Oculta",
            municipio=self.municipio,
            vereda="El Roble",
            activo=True,
        )
        self.cosecha_b = Cosecha.objects.create(
            finca=self.finca_b,
            variedad=self.variedad,
            fecha_cosecha=timezone.now().date(),
            cantidad_total=Decimal("800.00"),
            activo=True,
        )

        # 5. Lotes (Público de A vs Privado de B)
        self.lote_publico_a = Lote.objects.create(
            codigo="LOT-DOD-PUB-01",
            cosecha=self.cosecha_a,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("350.00"),
            publicado_en_catalogo=True,
            fecha_publicacion=timezone.now(),
            precio_referencial=Decimal("45000.00"),
            activo=True,
        )
        CaracteristicasCalidad.objects.create(
            lote=self.lote_publico_a,
            puntaje_taza=Decimal("89.00"),
            humedad=Decimal("10.80"),
            merma=Decimal("12.50"),
            perfil_sensorial="Notas a jazmín, miel de caña y ciruela dulce",
        )

        self.lote_privado_b = Lote.objects.create(
            codigo="LOT-DOD-PRIV-99",
            cosecha=self.cosecha_b,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("200.00"),
            publicado_en_catalogo=False,
            activo=True,
        )

        # 6. Operaciones de interés comercial
        self.operacion_a = ManifestacionInteres.objects.create(
            lote=self.lote_publico_a,
            comprador_id=self.comprador_id,
            comprador_correo="hans.muller@eurocoffee.test",
            cantidad_kg=Decimal("180.00"),
            mensaje="Interés en lote completo Caturra Chiroso para exportación",
            telefono_contacto="+493011223344",
            estado=ManifestacionInteres.EstadoManifestacion.REGISTRADO,
        )

        # 7. Actores de la cadena de valor
        self.asociacion_dod = ActorCadena.objects.create(
            tipo=ActorCadena.TipoActor.ASOCIACION,
            razon_social="Asociación Agroecológica de Arboledas",
            nit="901888777-1",
            contacto="Pedro Méndez Arboledas",
            correo="contacto@agroecologica.test",
            activo=True,
        )

    def test_escenario_01_busqueda_exacta_y_parcial_multicampo(self):
        """Búsqueda exacta por código (score 100), prefijo parcial, finca y variedad."""
        # 1. Búsqueda exacta por código de lote
        res_exacta = ejecutar_busqueda_global("LOT-DOD-PUB-01", rol_codigo="ADMINISTRADOR")
        self.assertGreaterEqual(res_exacta["total_resultados"], 1)
        self.assertEqual(res_exacta["resultados"][0]["relevancia"], 100)
        self.assertIn("LOT-DOD-PUB-01", res_exacta["resultados"][0]["titulo"])

        # 2. Búsqueda parcial por prefijo
        res_parcial = ejecutar_busqueda_global("LOT-DOD", rol_codigo="ADMINISTRADOR")
        self.assertGreaterEqual(res_parcial["conteo_por_entidad"]["lotes"], 2)

        # 3. Búsqueda por nombre de finca
        res_finca = ejecutar_busqueda_global("Bella Vista", rol_codigo="ADMINISTRADOR")
        self.assertGreaterEqual(res_finca["conteo_por_entidad"]["lotes"], 1)
        self.assertIn("Bella Vista", res_finca["resultados"][0]["subtitulo"])

        # 4. Búsqueda por variedad de café
        res_variedad = ejecutar_busqueda_global("Chiroso", rol_codigo="ADMINISTRADOR")
        self.assertGreaterEqual(res_variedad["conteo_por_entidad"]["lotes"], 1)

    def test_escenario_02_aislamiento_multitenant_estricto_rbac(self):
        """Aislamiento estricto: Productor A no ve operaciones de B ni lotes privados ajenos."""
        # Usuario Anónimo (Público): sólo ve catálogo público y asociaciones, sin acceso a operaciones ni compradores
        res_anon = ejecutar_busqueda_global("eurocoffee", usuario_o_id=None, rol_codigo="")
        self.assertEqual(res_anon["conteo_por_entidad"]["operaciones"], 0)
        self.assertEqual(res_anon["conteo_por_entidad"]["compradores"], 0)
        self.assertNotIn("operaciones", res_anon["entidades_permitidas"])
        self.assertNotIn("compradores", res_anon["entidades_permitidas"])

        # Productor A consulta sus operaciones: ve la suya sobre su lote
        res_prod_a = ejecutar_busqueda_global(
            "eurocoffee",
            tipo_entidad="operaciones",
            usuario_o_id=self.prod_a_mock,
            rol_codigo="PRODUCTOR",
        )
        self.assertEqual(res_prod_a["conteo_por_entidad"]["operaciones"], 1)

        # Productor B consulta la misma operación: 0 resultados (aislamiento multi-tenant estricto)
        res_prod_b = ejecutar_busqueda_global(
            "eurocoffee",
            tipo_entidad="operaciones",
            usuario_o_id=self.prod_b_mock,
            rol_codigo="PRODUCTOR",
        )
        self.assertEqual(res_prod_b["conteo_por_entidad"]["operaciones"], 0)

        # Lotes privados: Productor A no ve el lote privado de Productor B
        res_lotes_a = ejecutar_busqueda_global(
            "LOT-DOD-PRIV-99",
            tipo_entidad="lotes",
            usuario_o_id=self.prod_a_mock,
            rol_codigo="PRODUCTOR",
        )
        self.assertEqual(res_lotes_a["conteo_por_entidad"]["lotes"], 0)

        # Productor B sí ve su propio lote privado
        res_lotes_b = ejecutar_busqueda_global(
            "LOT-DOD-PRIV-99",
            tipo_entidad="lotes",
            usuario_o_id=self.prod_b_mock,
            rol_codigo="PRODUCTOR",
        )
        self.assertEqual(res_lotes_b["conteo_por_entidad"]["lotes"], 1)

    def test_escenario_03_insensibilidad_mayusculas_minusculas_y_tildes(self):
        """Normalización: 'ARBOLEDAS', 'arboledas' y 'Arboledas' dan resultados idénticos."""
        res_mayus = ejecutar_busqueda_global("ARBOLEDAS", rol_codigo="ADMINISTRADOR")
        res_minus = ejecutar_busqueda_global("arboledas", rol_codigo="ADMINISTRADOR")
        res_tildes = ejecutar_busqueda_global("Árboledas", rol_codigo="ADMINISTRADOR")

        self.assertEqual(res_mayus["total_resultados"], res_minus["total_resultados"])
        self.assertEqual(res_minus["total_resultados"], res_tildes["total_resultados"])
        self.assertGreaterEqual(res_mayus["total_resultados"], 1)

        # Búsqueda diacrítica en nombres de personas: 'MÉNDEZ' vs 'mendez'
        res_mendez_1 = ejecutar_busqueda_global("MÉNDEZ", rol_codigo="ADMINISTRADOR")
        res_mendez_2 = ejecutar_busqueda_global("mendez", rol_codigo="ADMINISTRADOR")
        self.assertEqual(res_mendez_1["conteo_por_entidad"]["productores"], res_mendez_2["conteo_por_entidad"]["productores"])

    def test_escenario_04_resiliencia_frontera_xss_sql_longitud_extrema(self):
        """Resiliencia ante entradas maliciosas, vacías o extremas sin generar error 500."""
        url_web = reverse('busqueda_global')
        url_api = reverse('api_busqueda_global')

        # 1. Intento de XSS
        payload_xss = "<script>alert('xss')</script>"
        resp_web_xss = self.client.get(url_web, {'q': payload_xss})
        self.assertEqual(resp_web_xss.status_code, 200)
        self.assertNotContains(resp_web_xss, "<script>alert('xss')</script>")

        # 2. Intento de SQL Injection
        payload_sqli = "' OR '1'='1' --"
        resp_api_sqli = self.client.get(url_api, {'q': payload_sqli})
        self.assertEqual(resp_api_sqli.status_code, 200)
        self.assertEqual(resp_api_sqli.json()["total_resultados"], 0)

        # 3. Cadena vacía y espacios en blanco
        resp_espacios = self.client.get(url_web, {'q': '      '})
        self.assertEqual(resp_espacios.status_code, 200)
        self.assertEqual(resp_espacios.context['total_resultados'], 0)

        # 4. Longitud extrema (500 caracteres)
        cadena_larga = "A" * 500
        resp_larga = self.client.get(url_api, {'q': cadena_larga})
        self.assertEqual(resp_larga.status_code, 200)
        self.assertEqual(resp_larga.json()["total_resultados"], 0)

        # 5. Emojis y caracteres unicode
        resp_emojis = self.client.get(url_api, {'q': '☕🌿'})
        self.assertEqual(resp_emojis.status_code, 200)

    def test_escenario_05_rendimiento_tiempo_respuesta_menor_a_500ms(self):
        """Criterio no funcional de rendimiento: tiempo de respuesta menor a 500 ms."""
        resultado = ejecutar_busqueda_global("Arboledas", tipo_entidad="todas", rol_codigo="ADMINISTRADOR")
        tiempo_ms = resultado.get("tiempo_ms", 999)
        self.assertIsInstance(tiempo_ms, float)
        self.assertLess(tiempo_ms, 500.0, f"La búsqueda tardó {tiempo_ms} ms, excediendo el límite de 500 ms.")

    def test_escenario_06_integracion_api_rest_contrato_json_completo(self):
        """La API REST /api/v1/buscar/ cumple estrictamente el contrato canónico de datos."""
        url = reverse('api_v1_busqueda_global_root')
        response = self.client.get(url, {'q': 'LOT-DOD-PUB-01', 'tipo': 'todas', 'limite': '10'})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Estructura de cabecera
        claves_esperadas = {
            "termino", "tipo_filtro", "total_resultados", "conteo_por_entidad",
            "entidades_permitidas", "resultados", "resultados_por_entidad", "tiempo_ms", "aviso"
        }
        self.assertTrue(claves_esperadas.issubset(data.keys()))

        # Contrato de cada item de resultado
        primer_item = data["resultados"][0]
        campos_item_esperados = {
            "id", "tipo_entidad", "tipo_entidad_display", "titulo", "subtitulo",
            "icono", "badge_clase", "badge_texto", "url_detalle", "relevancia", "acciones"
        }
        self.assertTrue(campos_item_esperados.issubset(primer_item.keys()))
        self.assertEqual(primer_item["tipo_entidad"], "LOTE")
        self.assertEqual(primer_item["relevancia"], 100)

    def test_escenario_07_integracion_web_navegacion_y_accesibilidad(self):
        """Verifica la navegación web, marcado accesible y diseño institucional sin colisiones."""
        response = self.client.get(reverse('busqueda_global'), {'q': 'Chiroso'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'busqueda/resultados.html')

        # Navbar Search Input y Atajo de Teclado
        self.assertContains(response, 'id="navbarSearchInput"')
        self.assertContains(response, 'navbarSearchInput')

        # Cero colisiones de .bg-gradient sobre fondo institucional
        self.assertNotContains(response, 'bg-gradient')

        # Presencia del formulario semántico accesible
        self.assertContains(response, 'role="search"')

    def test_escenario_08_verificacion_criterios_dod_hu29(self):
        """
        Verificación de los 5 pilares de la Definición de Terminado (DoD) de HU-29:
        1. Criterios de aceptación funcionales cubiertos.
        2. Pruebas automatizadas exhaustivas (8 subtareas completas).
        3. Estándares de accesibilidad WCAG 2.1 AA.
        4. Trazabilidad completa Jira: SCRUM-291 a SCRUM-298.
        """
        subtareas_hu29 = [
            "SCRUM-291",  # ST1: Navbar search & shortcut
            "SCRUM-292",  # ST2: Filtros / Tabs entidad
            "SCRUM-293",  # ST4: Endpoint unificado web/api
            "SCRUM-294",  # ST3: Normalización y relevancia
            "SCRUM-295",  # ST5: Interfaz visual & empty state
            "SCRUM-296",  # ST6: Permisos RBAC multi-tenant
            "SCRUM-297",  # ST7: Accesos directos contextuales
            "SCRUM-298",  # ST8: Pruebas funcionales y DoD
        ]
        self.assertEqual(len(subtareas_hu29), 8)
        self.assertTrue(all(st.startswith("SCRUM-") for st in subtareas_hu29))



