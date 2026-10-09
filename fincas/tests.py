"""
Pruebas Unitarias para HU-07: Registro de Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.
Subtarea: SCRUM-97: Validar formato de coordenadas.

Criterios de Aceptación Verificados:
- Validador que rechaza textos o números fuera de los rangos [-90, 90] y [-180, 180].
- Validación de consistencia mutua del par de coordenadas cartográficas.
- Rechazo en formularios y modelo con mensajes amigables y descriptivos.
- Persistencia de fincas con y sin coordenadas (opcionales).
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase, Client
from django.urls import reverse

from fincas.models import Finca
from fincas.forms import FincaRegistroForm, FincaModelForm, GeorreferenciacionFormMixin
from fincas.validators import (
    validar_latitud,
    validar_longitud,
    validar_par_coordenadas,
)


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
        # Ambas vacías
        validar_par_coordenadas(None, None)
        validar_par_coordenadas("", "")
        # Ambas informadas
        validar_par_coordenadas(Decimal("7.893910"), Decimal("-72.507820"))

    # -------------------------------------------------------------------------
    # 4. Pruebas de validación en Formulario FincaRegistroForm
    # -------------------------------------------------------------------------
    def test_formulario_rechaza_textos_en_coordenadas(self):
        """El formulario rechaza textos no numéricos en latitud y longitud."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Error Texto",
            "municipio": "Pamplona",
            "latitud": "texto_invalido",
            "longitud": "otro_texto",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)
        self.assertIn("longitud", form.errors)

    def test_formulario_rechaza_coordenadas_fuera_de_rango(self):
        """El formulario rechaza números que excedan los rangos [-90, 90] y [-180, 180]."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Fuera de Rango",
            "municipio": "Bochalema",
            "latitud": "95.500000",
            "longitud": "-195.800000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)
        self.assertIn("longitud", form.errors)

    def test_formulario_rechaza_par_incompleto(self):
        """El formulario rechaza cuando solo se llena uno de los dos campos."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Coordenada Incompleta",
            "municipio": "Chinacota",
            "latitud": "7.893910",
            "longitud": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("longitud", form.errors)


class TestGeorreferenciacionModelo(TestCase):
    """Pruebas del modelo Finca y esquema de georreferenciación (HU07-ST5 / SCRUM-98)."""

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
            municipio="Toledo",
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
            municipio="Arboledas",
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
            municipio="Cúcuta",
            latitud=Decimal("90.000001"),
            longitud=Decimal("0.000000"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_max.full_clean()

        finca_invalida_min = Finca(
            nombre="Finca Polo Sur",
            municipio="Cúcuta",
            latitud=Decimal("-90.000001"),
            longitud=Decimal("0.000000"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_min.full_clean()

    def test_validador_limites_longitud(self):
        """La longitud debe rechazar valores menores a -180 o mayores a 180 grados."""
        finca_invalida_max = Finca(
            nombre="Finca Este Extremo",
            municipio="Cúcuta",
            latitud=Decimal("7.000000"),
            longitud=Decimal("180.000001"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_max.full_clean()

        finca_invalida_min = Finca(
            nombre="Finca Oeste Extremo",
            municipio="Cúcuta",
            latitud=Decimal("7.000000"),
            longitud=Decimal("-180.000001"),
        )
        with self.assertRaises(ValidationError):
            finca_invalida_min.full_clean()

    def test_finca_model_clean_rechaza_par_incompleto(self):
        """El modelo Finca rechaza cuando solo se provee una coordenada."""
        finca_solo_lat = Finca(
            nombre="Finca Par Incompleto",
            municipio="Toledo",
            latitud=Decimal("7.893910"),
            longitud=None,
        )
        with self.assertRaises(ValidationError):
            finca_solo_lat.full_clean()

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
        """Si el usuario está autenticado, la vista asocia request.user como productor."""
        from django.contrib.auth.models import User
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
        self.assertEqual(finca.productor, usuario)

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
            municipio="Toledo",
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
