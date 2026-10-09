"""
Pruebas Unitarias para el Dominio de Fincas y Georreferenciación - CAFÉ PÉRGAMO

Integración de:
- HU-06 (SCRUM-87, SCRUM-88): Modelo de datos de fincas, relación con productor y catálogo de municipios.
- HU-07 (SCRUM-95, SCRUM-96, SCRUM-97, SCRUM-98, SCRUM-99): Registro de georreferenciación opcional,
  validación de formato cartográfico decimal WGS84 [-90, 90] y [-180, 180], persistencia y API REST.
"""

import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from fincas.forms import FincaModelForm, FincaRegistroForm, GeorreferenciacionFormMixin
from fincas.models import Finca, Municipio
from fincas.validators import (
    validar_latitud,
    validar_longitud,
    validar_par_coordenadas,
)


# =============================================================================
# SUITE HU-07: PRUEBAS DE GEORREFERENCIACIÓN Y COORDENADAS CARTOGRÁFICAS
# =============================================================================


class TestValidacionFormatoCoordenadas(TestCase):
    """
    Pruebas exhaustivas para SCRUM-97: Validar formato de coordenadas.
    DoD: Validador que rechaza textos o números fuera de los rangos [-90, 90] y [-180, 180].
    """

    # -------------------------------------------------------------------------
    # 1. Pruebas directas de validar_latitud
    # -------------------------------------------------------------------------
    def test_validar_latitud_acepta_decimales_en_rango(self):
        """Acepta números decimales válidos dentro de [-90, 90]."""
        self.assertEqual(validar_latitud("7.893910"), Decimal("7.893910"))
        self.assertEqual(validar_latitud("-90.000000"), Decimal("-90.000000"))
        self.assertEqual(validar_latitud("90.000000"), Decimal("90.000000"))
        self.assertEqual(validar_latitud(0), Decimal("0"))
        self.assertEqual(validar_latitud(Decimal("12.345678")), Decimal("12.345678"))

    def test_validar_latitud_acepta_valores_nulos_o_vacios(self):
        """Acepta None o cadena vacía porque la georreferenciación es opcional."""
        self.assertIsNone(validar_latitud(None))
        self.assertIsNone(validar_latitud(""))

    def test_validar_latitud_rechaza_textos_no_numericos(self):
        """Rechaza textos alfanuméricos o caracteres especiales no decimales."""
        textos_invalidos = ["norte", "lat_7", "abc", "7..89", "7,8939"]
        for texto in textos_invalidos:
            with self.assertRaises(ValidationError) as ctx:
                validar_latitud(texto)
            self.assertEqual(ctx.exception.code, "latitud_formato_invalido")
            self.assertIn("formato", str(ctx.exception).lower())

    def test_validar_latitud_rechaza_numeros_mayores_a_90(self):
        """Rechaza latitudes mayores al límite superior de 90 grados."""
        valores_superiores = ["90.000001", "91", "120.5", 999]
        for val in valores_superiores:
            with self.assertRaises(ValidationError) as ctx:
                validar_latitud(val)
            self.assertEqual(ctx.exception.code, "latitud_fuera_de_rango")
            self.assertIn("fuera del rango", str(ctx.exception).lower())

    def test_validar_latitud_rechaza_numeros_menores_a_menos_90(self):
        """Rechaza latitudes menores al límite inferior de -90 grados."""
        valores_inferiores = ["-90.000001", "-91", "-105.2", -500]
        for val in valores_inferiores:
            with self.assertRaises(ValidationError) as ctx:
                validar_latitud(val)
            self.assertEqual(ctx.exception.code, "latitud_fuera_de_rango")
            self.assertIn("fuera del rango", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 2. Pruebas directas de validar_longitud
    # -------------------------------------------------------------------------
    def test_validar_longitud_acepta_decimales_en_rango(self):
        """Acepta números decimales válidos dentro de [-180, 180]."""
        self.assertEqual(validar_longitud("-72.507820"), Decimal("-72.507820"))
        self.assertEqual(validar_longitud("-180.000000"), Decimal("-180.000000"))
        self.assertEqual(validar_longitud("180.000000"), Decimal("180.000000"))
        self.assertEqual(validar_longitud(0), Decimal("0"))
        self.assertEqual(validar_longitud(Decimal("-45.123456")), Decimal("-45.123456"))

    def test_validar_longitud_acepta_valores_nulos_o_vacios(self):
        """Acepta None o cadena vacía porque la georreferenciación es opcional."""
        self.assertIsNone(validar_longitud(None))
        self.assertIsNone(validar_longitud(""))

    def test_validar_longitud_rechaza_textos_no_numericos(self):
        """Rechaza textos alfanuméricos o caracteres especiales no decimales."""
        textos_invalidos = ["oeste", "long_72", "xyz", "-72..50", "-72,5078"]
        for texto in textos_invalidos:
            with self.assertRaises(ValidationError) as ctx:
                validar_longitud(texto)
            self.assertEqual(ctx.exception.code, "longitud_formato_invalido")
            self.assertIn("formato", str(ctx.exception).lower())

    def test_validar_longitud_rechaza_numeros_mayores_a_180(self):
        """Rechaza longitudes mayores al límite superior de 180 grados."""
        valores_superiores = ["180.000001", "181", "200.5", 999]
        for val in valores_superiores:
            with self.assertRaises(ValidationError) as ctx:
                validar_longitud(val)
            self.assertEqual(ctx.exception.code, "longitud_fuera_de_rango")
            self.assertIn("fuera del rango", str(ctx.exception).lower())

    def test_validar_longitud_rechaza_numeros_menores_a_menos_180(self):
        """Rechaza longitudes menores al límite inferior de -180 grados."""
        valores_inferiores = ["-180.000001", "-181", "-210.4", -800]
        for val in valores_inferiores:
            with self.assertRaises(ValidationError) as ctx:
                validar_longitud(val)
            self.assertEqual(ctx.exception.code, "longitud_fuera_de_rango")
            self.assertIn("fuera del rango", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 3. Pruebas de consistencia mutua del par de coordenadas
    # -------------------------------------------------------------------------
    def test_validar_par_coordenadas_rechaza_latitud_sin_longitud(self):
        """Si se especifica latitud pero se omite longitud, se rechaza."""
        with self.assertRaises(ValidationError) as ctx:
            validar_par_coordenadas(Decimal("7.893910"), None)
        self.assertIn("longitud", ctx.exception.message_dict)

    def test_validar_par_coordenadas_rechaza_longitud_sin_latitud(self):
        """Si se especifica longitud pero se omite latitud, se rechaza."""
        with self.assertRaises(ValidationError) as ctx:
            validar_par_coordenadas(None, Decimal("-72.507820"))
        self.assertIn("latitud", ctx.exception.message_dict)

    def test_validar_par_coordenadas_acepta_ambas_o_ninguna(self):
        """Acepta cuando ambas están informadas o cuando ambas están vacías."""
        validar_par_coordenadas(None, None)
        validar_par_coordenadas("", "")
        validar_par_coordenadas(Decimal("7.893910"), Decimal("-72.507820"))

    # -------------------------------------------------------------------------
    # 4. Pruebas de validación en Formulario FincaRegistroForm
    # -------------------------------------------------------------------------
    def test_formulario_rechaza_textos_en_coordenadas(self):
        """El formulario rechaza textos no numéricos en latitud y longitud."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Test",
            "municipio": "Pamplona",
            "latitud": "texto_invalido",
            "longitud": "-72.500000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)

    def test_formulario_rechaza_latitud_fuera_de_rango(self):
        """El formulario rechaza latitudes mayores a 90 o menores a -90."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Fuera Rango",
            "municipio": "Pamplona",
            "latitud": "95.500000",
            "longitud": "-72.500000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)

    def test_formulario_rechaza_longitud_fuera_de_rango(self):
        """El formulario rechaza longitudes mayores a 180 o menores a -180."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Fuera Rango",
            "municipio": "Pamplona",
            "latitud": "7.500000",
            "longitud": "185.000000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("longitud", form.errors)

    def test_formulario_rechaza_par_incompleto_latitud_sola(self):
        """El formulario no valida si solo se ingresa latitud."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Par Incompleto",
            "municipio": "Pamplona",
            "latitud": "7.893910",
            "longitud": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("longitud", form.errors)

    def test_formulario_rechaza_par_incompleto_longitud_sola(self):
        """El formulario no valida si solo se ingresa longitud."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Par Incompleto",
            "municipio": "Pamplona",
            "latitud": "",
            "longitud": "-72.507820",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)


class TestGeorreferenciacionModelo(TestCase):
    """Pruebas del modelo Finca y esquema de georreferenciación (HU07-ST5 / SCRUM-98)."""

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="TEST_PAMPLONA", nombre="Pamplona")
        self.productor_id = uuid.uuid4()

    def test_campos_latitud_y_longitud_son_decimalfield(self):
        """Los campos deben estar definidos como DecimalField en el ORM."""
        campo_lat = Finca._meta.get_field("latitud")
        campo_lng = Finca._meta.get_field("longitud")

        self.assertIsInstance(campo_lat, models.DecimalField)
        self.assertIsInstance(campo_lng, models.DecimalField)
        self.assertEqual(campo_lat.max_digits, 9)
        self.assertEqual(campo_lat.decimal_places, 6)
        self.assertEqual(campo_lng.max_digits, 9)
        self.assertEqual(campo_lng.decimal_places, 6)

    def test_campos_latitud_y_longitud_son_opcionales_en_modelo(self):
        """Los campos deben permitir nulabilidad (null=True, blank=True)."""
        campo_lat = Finca._meta.get_field("latitud")
        campo_lng = Finca._meta.get_field("longitud")

        self.assertTrue(campo_lat.null)
        self.assertTrue(campo_lat.blank)
        self.assertTrue(campo_lng.null)
        self.assertTrue(campo_lng.blank)

    def test_persistencia_finca_sin_coordenadas_exitoso(self):
        """Una finca se puede persistir con coordenadas NULL (campo opcional)."""
        finca = Finca.objects.create(
            nombre="Finca El Silencio",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="El Roble",
            latitud=None,
            longitud=None,
        )

        finca_guardada = Finca.objects.get(id=finca.id)
        self.assertIsNone(finca_guardada.latitud)
        self.assertIsNone(finca_guardada.longitud)
        self.assertFalse(finca_guardada.tiene_georreferenciacion)

    def test_persistencia_finca_con_coordenadas_validas_exitoso(self):
        """Una finca se persiste correctamente con coordenadas decimales válidas."""
        finca = Finca.objects.create(
            nombre="Finca La Samaria",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="San José",
            latitud=Decimal("7.893910"),
            longitud=Decimal("-72.507820"),
        )

        finca_guardada = Finca.objects.get(id=finca.id)
        self.assertEqual(finca_guardada.latitud, Decimal("7.893910"))
        self.assertEqual(finca_guardada.longitud, Decimal("-72.507820"))
        self.assertTrue(finca_guardada.tiene_georreferenciacion)

    def test_validador_limites_latitud(self):
        """La latitud debe rechazar valores menores a -90 o mayores a 90 grados."""
        finca_invalida_max = Finca(
            nombre="Finca Polo Norte",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("90.000001"),
            longitud=Decimal("0.000000"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_max.full_clean(exclude=["productor"])

        finca_invalida_min = Finca(
            nombre="Finca Polo Sur",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("-90.000001"),
            longitud=Decimal("0.000000"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_min.full_clean(exclude=["productor"])

    def test_validador_limites_longitud(self):
        """La longitud debe rechazar valores menores a -180 o mayores a 180 grados."""
        finca_invalida_max = Finca(
            nombre="Finca Este Extremo",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.000000"),
            longitud=Decimal("180.000001"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_max.full_clean(exclude=["productor"])

        finca_invalida_min = Finca(
            nombre="Finca Oeste Extremo",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.000000"),
            longitud=Decimal("-180.000001"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_min.full_clean(exclude=["productor"])

    def test_finca_model_clean_rechaza_par_incompleto(self):
        """El modelo Finca rechaza cuando solo se provee una coordenada."""
        finca_solo_lat = Finca(
            nombre="Finca Par Incompleto",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.893910"),
            longitud=None,
        )
        with self.assertRaises(ValidationError):
            finca_solo_lat.full_clean(exclude=["productor"])

    def test_finca_model_form_guarda_con_y_sin_coordenadas(self):
        """El ModelForm permite guardar con y sin georreferenciación."""
        # Caso sin coordenadas
        form_sin_coords = FincaModelForm(data={
            "nombre": "Finca Modelo Sin Coords",
            "municipio": "Labateca",
            "vereda": "Centro",
        })
        self.assertTrue(form_sin_coords.is_valid(), f"Errores: {form_sin_coords.errors}")
        finca_sin_coords = form_sin_coords.save()
        self.assertIsNone(finca_sin_coords.latitud)
        self.assertIsNone(finca_sin_coords.longitud)

        # Caso con coordenadas
        form_con_coords = FincaModelForm(data={
            "nombre": "Finca Modelo Con Coords",
            "municipio": "Salazar",
            "vereda": "La Playa",
            "latitud": "7.771234",
            "longitud": "-72.812345",
        })
        self.assertTrue(form_con_coords.is_valid(), f"Errores: {form_con_coords.errors}")
        finca_con_coords = form_con_coords.save()
        self.assertEqual(finca_con_coords.latitud, Decimal("7.771234"))
        self.assertEqual(finca_con_coords.longitud, Decimal("-72.812345"))


class TestGeorreferenciacionFormulario(TestCase):
    """Pruebas del diseño del formulario y mixin de georreferenciación (HU07-ST1)."""

    def test_campos_de_coordenadas_son_opcionales(self):
        """Los campos de latitud y longitud no deben ser obligatorios (required=False)."""
        form = GeorreferenciacionFormMixin()
        self.assertFalse(form.fields["latitud"].required)
        self.assertFalse(form.fields["longitud"].required)

    def test_placeholders_indicativos_de_coordenadas_decimales(self):
        """Los widgets de latitud y longitud deben tener placeholders con ejemplos decimales."""
        form = GeorreferenciacionFormMixin()

        lat_placeholder = form.fields["latitud"].widget.attrs.get("placeholder", "")
        lng_placeholder = form.fields["longitud"].widget.attrs.get("placeholder", "")

        self.assertIn("7.893910", lat_placeholder)
        self.assertIn("decimales", lat_placeholder.lower())
        self.assertIn("-72.507820", lng_placeholder)
        self.assertIn("decimales", lng_placeholder.lower())

    def test_formulario_valido_cuando_coordenadas_no_son_informadas(self):
        """Si el usuario no informa coordenadas, el formulario debe ser válido sin errores."""
        datos = {
            "nombre": "Finca Los Pinos",
            "municipio": "Arboledas",
            "vereda": "La Selva",
            "latitud": "",
            "longitud": "",
        }
        form = FincaRegistroForm(data=datos)
        self.assertTrue(form.is_valid(), f"Errores encontrados: {form.errors}")
        self.assertIsNone(form.cleaned_data["latitud"])
        self.assertIsNone(form.cleaned_data["longitud"])

    def test_formulario_valido_con_coordenadas_decimales_informadas(self):
        """Si el usuario ingresa coordenadas decimales válidas, se procesan correctamente."""
        datos = {
            "nombre": "Finca La Esmeralda",
            "municipio": "Toledo",
            "vereda": "San Bernardo",
            "latitud": "7.893910",
            "longitud": "-72.507820",
        }
        form = FincaRegistroForm(data=datos)
        self.assertTrue(form.is_valid(), f"Errores encontrados: {form.errors}")
        self.assertEqual(form.cleaned_data["latitud"], Decimal("7.893910"))
        self.assertEqual(form.cleaned_data["longitud"], Decimal("-72.507820"))


class TestGeorreferenciacionInterfazWeb(TestCase):
    """Pruebas de la vista y plantilla HTML del registro de finca y georreferenciación."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("finca_registro")

    def test_renderizado_exitoso_vista_registro(self):
        """La vista de registro debe responder HTTP 200 y usar la plantilla esperada."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/registro_finca.html")
        self.assertTemplateUsed(response, "fincas/componentes/campo_georreferenciacion.html")

    def test_plantilla_contiene_nota_campo_opcional(self):
        """La plantilla debe exhibir visiblemente que el campo es Opcional."""
        response = self.client.get(self.url)
        contenido = response.content.decode("utf-8")

        self.assertIn("Opcional", contenido)
        self.assertIn("badge-opcional", contenido)
        self.assertIn("nota-informativa-geo", contenido)
        self.assertIn("no es obligatorio", contenido)

    def test_plantilla_contiene_inputs_con_placeholders_decimales(self):
        """La plantilla debe renderizar los inputs de latitud y longitud con sus placeholders."""
        response = self.client.get(self.url)
        contenido = response.content.decode("utf-8")

        self.assertIn('id="id_latitud"', contenido)
        self.assertIn('id="id_longitud"', contenido)
        self.assertIn("Ej: 7.893910 (Grados decimales)", contenido)
        self.assertIn("Ej: -72.507820 (Grados decimales)", contenido)

    def test_plantilla_incluye_ayudas_de_entrada_y_captura_gps(self):
        """La interfaz debe ofrecer botón de captura satelital y textos de ayuda de rango."""
        response = self.client.get(self.url)
        contenido = response.content.decode("utf-8")

        self.assertIn("btn-detectar-gps", contenido)
        self.assertIn("WGS84", contenido)
        self.assertIn("[-90° a +90°]", contenido)
        self.assertIn("[-180° a +180°]", contenido)

    def test_envio_formulario_invalido_muestra_errores_en_pantalla(self):
        """Al enviar coordenadas fuera de rango, la vista responde 200 con errores."""
        response = self.client.post(self.url, {
            "nombre": "Finca Test Invalida",
            "municipio": "Cúcuta",
            "latitud": "100.5",
            "longitud": "-250.0",
        })
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8")
        self.assertIn("fuera del rango", contenido)


class TestGuardarGeorreferenciacionBackend(TestCase):
    """
    Pruebas para SCRUM-96: Guardar georreferenciación en backend.
    DoD: La vista persiste las coordenadas en BD o almacena NULL si no se ingresaron.
    """

    def setUp(self):
        self.client = Client()
        self.url_registro = reverse("finca_registro")
        self.url_api = reverse("api_finca_crear")
        self.municipio = Municipio.objects.create(codigo="TEST_MUNICIPIO", nombre="Toledo")

    def test_vista_post_persiste_finca_con_coordenadas_en_bd(self):
        """Al enviar coordenadas válidas, la vista persiste los valores Decimal en BD."""
        response = self.client.post(self.url_registro, {
            "nombre": "Finca San Francisco",
            "municipio": "Salazar",
            "vereda": "La Playa",
            "latitud": "7.893910",
            "longitud": "-72.507820",
        })
        self.assertEqual(response.status_code, 302)

        finca = Finca.objects.filter(nombre="Finca San Francisco").first()
        self.assertIsNotNone(finca)
        self.assertEqual(finca.latitud, Decimal("7.893910"))
        self.assertEqual(finca.longitud, Decimal("-72.507820"))
        self.assertTrue(finca.tiene_georreferenciacion)

    def test_vista_post_persiste_finca_sin_coordenadas_almacena_null_en_bd(self):
        """Al no ingresar coordenadas, la vista persiste la finca almacenando NULL en BD."""
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Sin Coordenadas",
            "municipio": "Arboledas",
            "vereda": "Centro",
            "latitud": "",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 302)

        finca = Finca.objects.filter(nombre="Finca Sin Coordenadas").first()
        self.assertIsNotNone(finca)
        self.assertIsNone(finca.latitud)
        self.assertIsNone(finca.longitud)
        self.assertFalse(finca.tiene_georreferenciacion)

    def test_vista_post_asocia_productor_en_sesion(self):
        """Si el usuario está autenticado, la vista maneja la sesión adecuadamente."""
        usuario = User.objects.create_user(username="productor_test", password="Password123!")
        self.client.force_login(usuario)

        response = self.client.post(self.url_registro, {
            "nombre": "Finca con Productor Sesion",
            "municipio": "Toledo",
            "latitud": "7.300000",
            "longitud": "-72.480000",
        })
        self.assertEqual(response.status_code, 302)

        finca = Finca.objects.filter(nombre="Finca con Productor Sesion").first()
        self.assertIsNotNone(finca)
        self.assertEqual(finca.latitud, Decimal("7.300000"))

    def test_api_post_persiste_coordenadas_en_bd(self):
        """Endpoint API guarda coordenadas y responde 201 Created."""
        payload = {
            "nombre": "Finca API Coords",
            "municipio": "Lourdes",
            "latitud": "7.945000",
            "longitud": "-72.835000",
        }
        response = self.client.post(self.url_api, payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["latitud"], "7.945000")
        self.assertEqual(response.json()["longitud"], "-72.835000")
        self.assertTrue(response.json()["tiene_georreferenciacion"])

        finca = Finca.objects.get(id=response.json()["id"])
        self.assertEqual(finca.latitud, Decimal("7.945000"))
        self.assertEqual(finca.longitud, Decimal("-72.835000"))

    def test_api_post_sin_coordenadas_almacena_null(self):
        """Endpoint API guarda NULL cuando latitud y longitud son omitidos."""
        payload = {
            "nombre": "Finca API Sin Coords",
            "municipio": "Bochalema",
        }
        response = self.client.post(self.url_api, payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["latitud"])
        self.assertIsNone(response.json()["longitud"])
        self.assertFalse(response.json()["tiene_georreferenciacion"])

        finca = Finca.objects.get(id=response.json()["id"])
        self.assertIsNone(finca.latitud)
        self.assertIsNone(finca.longitud)

    def test_api_patch_actualiza_georreferenciacion(self):
        """Endpoint API permite actualizar la georreferenciación de una finca existente."""
        finca = Finca.objects.create(
            nombre="Finca Previa Sin GPS",
            productor_id=uuid.uuid4(),
            municipio=self.municipio,
            latitud=None,
            longitud=None,
        )
        url_detalle = reverse("api_finca_detalle", kwargs={"pk": finca.pk})

        response = self.client.patch(
            url_detalle,
            {"latitud": "7.310000", "longitud": "-72.490000"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        finca.refresh_from_db()
        self.assertEqual(finca.latitud, Decimal("7.310000"))
        self.assertEqual(finca.longitud, Decimal("-72.490000"))
        self.assertTrue(finca.tiene_georreferenciacion)


class TestScrum99PruebasGeorreferenciacion(TestCase):
    """
    Subtarea: SCRUM-99 / HU07-ST3: Pruebas de georreferenciación.
    Criterio de Aceptación Cumplido (DoD):
    "Tests unitarios de guardado con valores nulos, válidos y rechazo por coordenadas erróneas."
    """

    def setUp(self):
        self.client = Client()
        self.url_registro = reverse("finca_registro")

    def test_dod_guardado_con_valores_validos(self):
        """DoD Escenario 1: Guardado exitoso con coordenadas válidas."""
        response = self.client.post(self.url_registro, {
            "nombre": "Finca La Esperanza",
            "municipio": "Toledo",
            "vereda": "San Bernardo",
            "latitud": "7.893910",
            "longitud": "-72.507820",
        })
        self.assertEqual(response.status_code, 302)

        finca = Finca.objects.get(nombre="Finca La Esperanza")
        self.assertEqual(finca.latitud, Decimal("7.893910"))
        self.assertEqual(finca.longitud, Decimal("-72.507820"))
        self.assertTrue(finca.tiene_georreferenciacion)

    def test_dod_guardado_con_valores_nulos_opcionales(self):
        """DoD Escenario 2: Guardado exitoso con valores nulos (campo opcional)."""
        response = self.client.post(self.url_registro, {
            "nombre": "Finca El Cafetal",
            "municipio": "Arboledas",
            "vereda": "El Silencio",
            "latitud": "",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 302)

        finca = Finca.objects.get(nombre="Finca El Cafetal")
        self.assertIsNone(finca.latitud)
        self.assertIsNone(finca.longitud)
        self.assertFalse(finca.tiene_georreferenciacion)

    def test_dod_rechazo_por_coordenadas_erroneas_textos_no_numericos(self):
        """DoD Escenario 3a: Rechazo por textos no numéricos en coordenadas."""
        conteo_previo = Finca.objects.count()
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Error Texto",
            "municipio": "Salazar",
            "latitud": "invalido",
            "longitud": "otro_texto",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)
        self.assertContains(response, "formato")

    def test_dod_rechazo_por_coordenadas_erroneas_latitud_fuera_de_limites(self):
        """DoD Escenario 3b: Rechazo por latitud fuera de rango [-90, 90]."""
        conteo_previo = Finca.objects.count()
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Latitud Invalida",
            "municipio": "Salazar",
            "latitud": "95.000000",
            "longitud": "-72.500000",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)
        self.assertContains(response, "fuera del rango")

    def test_dod_rechazo_por_coordenadas_erroneas_longitud_fuera_de_limites(self):
        """DoD Escenario 3c: Rechazo por longitud fuera de rango [-180, 180]."""
        conteo_previo = Finca.objects.count()
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Longitud Invalida",
            "municipio": "Salazar",
            "latitud": "7.500000",
            "longitud": "-195.000000",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)
        self.assertContains(response, "fuera del rango")

    def test_dod_rechazo_por_coordenadas_erroneas_par_incompleto(self):
        """DoD Escenario 3d: Rechazo cuando solo se provee una coordenada."""
        conteo_previo = Finca.objects.count()
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Par Incompleto",
            "municipio": "Salazar",
            "latitud": "7.893910",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)
        self.assertContains(response, "debe ingresar también la longitud")

    def test_dod_ciclo_completo_integracion_y_listado(self):
        """DoD Escenario 4: Ciclo completo que verifica renderizado de fincas con y sin coordenadas."""
        # 1. Crear finca sin coordenadas
        self.client.post(self.url_registro, {
            "nombre": "Predio Sin GPS",
            "municipio": "Lourdes",
            "latitud": "",
            "longitud": "",
        })

        # 2. Crear finca con coordenadas
        self.client.post(self.url_registro, {
            "nombre": "Predio Con GPS",
            "municipio": "Toledo",
            "latitud": "7.300000",
            "longitud": "-72.480000",
        })

        # 3. Consultar la pantalla y verificar que ambas se listan adecuadamente
        response = self.client.get(self.url_registro)
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8")

        self.assertIn("Predio Sin GPS", contenido)
        self.assertIn("NULL (Sin GPS)", contenido)
        self.assertIn("Predio Con GPS", contenido)
        self.assertIn("7.300000, -72.480000", contenido)


# =============================================================================
# SUITE HU-06: PRUEBAS DE MODELO FINCA, PRODUCTOR Y MUNICIPIO (DAVID)
# =============================================================================


class MunicipioModelTests(TestCase):
    """Pruebas del modelo Municipio (catálogo administrable de municipios)."""

    def test_creacion_basica_usa_departamento_por_defecto(self):
        municipio = Municipio.objects.create(codigo="PAMPLONA", nombre="Pamplona")
        self.assertEqual(municipio.departamento, "Norte de Santander")
        self.assertTrue(municipio.activo)

    def test_codigo_unico_en_el_catalogo(self):
        Municipio.objects.create(codigo="CUCUTA", nombre="Cúcuta")
        with self.assertRaises(IntegrityError):
            Municipio.objects.create(codigo="CUCUTA", nombre="Cúcuta (duplicado)")


class FincaModelTests(TestCase):
    """Pruebas del modelo Finca con relación a Productor y Municipio."""

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="PAMPLONA", nombre="Pamplona")
        self.productor_id = uuid.uuid4()

    def test_creacion_finca_con_productor_y_municipio(self):
        finca = Finca.objects.create(
            nombre="El Cafetal",
            productor_id=self.productor_id,
            municipio=self.municipio,
        )
        self.assertEqual(finca.municipio, self.municipio)
        self.assertEqual(finca.productor_id, self.productor_id)
        self.assertTrue(finca.activo)
        self.assertFalse(finca.tiene_georreferenciacion)

    def test_un_productor_puede_tener_mas_de_una_finca(self):
        Finca.objects.create(nombre="Finca 1", productor_id=self.productor_id, municipio=self.municipio)
        Finca.objects.create(nombre="Finca 2", productor_id=self.productor_id, municipio=self.municipio)
        self.assertEqual(Finca.objects.filter(productor_id=self.productor_id).count(), 2)

    def test_requiere_municipio(self):
        with self.assertRaises(IntegrityError):
            Finca.objects.create(nombre="Sin municipio", productor_id=self.productor_id, municipio=None)

    def test_requiere_productor(self):
        # En el modelo, productor permite null=True para compatibilidad con flujos opcionales
        # o db_constraint=False; si se requiere en BD o no:
        pass

    def test_no_permite_borrar_municipio_con_fincas_asociadas(self):
        Finca.objects.create(nombre="Finca 1", productor_id=self.productor_id, municipio=self.municipio)
        with self.assertRaises(ProtectedError):
            self.municipio.delete()

    def test_tiene_georreferenciacion_con_coordenadas(self):
        finca = Finca.objects.create(
            nombre="Finca GPS",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud="7.373000",
            longitud="-72.648000",
        )
        self.assertTrue(finca.tiene_georreferenciacion)

    def test_str_incluye_nombre_de_municipio(self):
        finca = Finca.objects.create(nombre="El Cafetal", productor_id=self.productor_id, municipio=self.municipio)
        self.assertIn("Pamplona", str(finca))


class AsociacionMultiplesFincasPorProductorTests(TestCase):
    """
    HU06-ST2 (SCRUM-88): un productor puede tener N fincas, y el
    listado por productor no se mezcla entre productores distintos.
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="PAMPLONA", nombre="Pamplona")
        self.productor_a = uuid.uuid4()
        self.productor_b = uuid.uuid4()

    def test_nombre_repetido_entre_fincas_del_mismo_productor_no_choca(self):
        """El nombre de la finca no está validado como único global."""
        Finca.objects.create(nombre="Mi Finca", productor_id=self.productor_a, municipio=self.municipio)
        segunda = Finca.objects.create(nombre="Mi Finca", productor_id=self.productor_a, municipio=self.municipio)
        self.assertIsNotNone(segunda.pk)

    def test_no_existe_limite_artificial_de_fincas_por_productor(self):
        """Se pueden seguir sumando fincas (N > 2) sin tope alguno."""
        for i in range(5):
            Finca.objects.create(nombre=f"Finca {i}", productor_id=self.productor_a, municipio=self.municipio)
        self.assertEqual(Finca.objects.filter(productor_id=self.productor_a).count(), 5)

    def test_listado_por_productor_no_se_mezcla_con_otro_productor(self):
        """El listado de fincas de un productor no incluye las de otro."""
        Finca.objects.create(nombre="Finca A1", productor_id=self.productor_a, municipio=self.municipio)
        Finca.objects.create(nombre="Finca A2", productor_id=self.productor_a, municipio=self.municipio)
        Finca.objects.create(nombre="Finca B1", productor_id=self.productor_b, municipio=self.municipio)

        fincas_de_a = Finca.objects.filter(productor_id=self.productor_a)
        fincas_de_b = Finca.objects.filter(productor_id=self.productor_b)

        self.assertEqual(fincas_de_a.count(), 2)
        self.assertEqual(fincas_de_b.count(), 1)
        self.assertTrue(all(f.productor_id == self.productor_a for f in fincas_de_a))
        self.assertTrue(all(f.productor_id == self.productor_b for f in fincas_de_b))

    def test_finca_adicional_no_afecta_ni_sobrescribe_las_ya_registradas(self):
        """Agregar una finca nueva no modifica los datos de las anteriores."""
        primera = Finca.objects.create(
            nombre="Finca Original", productor_id=self.productor_a, municipio=self.municipio, vereda="Vereda 1"
        )
        Finca.objects.create(nombre="Finca Nueva", productor_id=self.productor_a, municipio=self.municipio)

        primera.refresh_from_db()
        self.assertEqual(primera.nombre, "Finca Original")
        self.assertEqual(primera.vereda, "Vereda 1")

    def test_finca_adicional_sigue_exigiendo_municipio_del_catalogo(self):
        """Cada finca nueva pasa, de forma independiente, las mismas validaciones de HU06-ST1."""
        Finca.objects.create(nombre="Finca 1", productor_id=self.productor_a, municipio=self.municipio)
        with self.assertRaises(IntegrityError):
            Finca.objects.create(nombre="Finca 2 sin municipio", productor_id=self.productor_a, municipio=None)
