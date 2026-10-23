"""
Pruebas Unitarias para el Dominio de Fincas y Georreferenciación - CAFÉ PÉRGAMO

Integración de:
- HU-06 (SCRUM-87, SCRUM-88): Modelo de datos de fincas, relación con productor y catálogo de municipios.
- HU-07 (SCRUM-95, SCRUM-96, SCRUM-97, SCRUM-98, SCRUM-99): Registro de georreferenciación opcional,
  validación de formato cartográfico decimal WGS84 [-90, 90] y [-180, 180], persistencia y API REST.
- HU-13 (SCRUM-141 a SCRUM-147): Modelo de datos Cosecha-Lote; registro de lotes de café a partir de
  una cosecha (código único, cantidad vs. saldo disponible, descuento transaccional); validación de
  código único de lote a nivel de aplicación y de persistencia (ST3 / SCRUM-143); validación de que la
  cantidad del lote no supere el saldo disponible (ST4 / SCRUM-145); descuento del saldo de la cosecha
  al crear el lote para mantener su trazabilidad (ST5 / SCRUM-146); formularios web de registro de
  cosechas (complemento) y de lotes (SCRUM-144); y cobertura de pruebas de código único, restricción de
  cantidad y flujo exitoso de registro (ST6 / SCRUM-147).
- HU-15-ST1 (SCRUM-155): Persistencia API de características físicas y de calidad del lote.
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, models
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken


from fincas.forms import (
    CosechaRegistroForm,
    FincaModelForm,
    FincaRegistroForm,
    GeorreferenciacionFormMixin,
    LoteRegistroForm,
    MunicipioForm,
)
from fincas.models import CaracteristicasCalidad, Cosecha, Finca, Lote, Municipio
from fincas.services import (
    crear_caracteristicas_calidad,
    crear_cosecha,
    crear_lote,
    editar_caracteristicas_calidad,
    generar_codigo_lote,
)
from catalogos.models import EstadoLote, ProcesoBeneficio, VariedadCafe
from fincas.validators import (
    validar_latitud,
    validar_longitud,
    validar_par_coordenadas,
)


def _iniciar_sesion_productor(client, usuario_id=None):
    """
    Simula, para pruebas, el mismo estado de sesión que deja `login_view`
    al autenticar a un productor real (`request.session['usuario_id']` --
    ver usuarios/views.py:492). `usuarios.Usuario` es `managed=False` y no
    existe en la base de datos de pruebas (sqlite), así que aquí no se
    crea una fila real: basta con la clave de sesión, que es justo lo que
    `_resolver_productor_id` (fincas/views.py) necesita para identificar
    al productor sin inventar un UUID al azar.
    """
    usuario_id = usuario_id or uuid.uuid4()
    session = client.session
    session["usuario_id"] = str(usuario_id)
    session.save()
    return str(usuario_id)


def _jwt_bearer_headers(correo="productor.prueba@cafepergamo.test"):
    """
    Emite un JWT real válido para las pruebas de la API de fincas, con el
    mismo claim 'email' que `CustomTokenObtainPairSerializer.get_token()`
    agrega en producción (usuarios/serializers.py). No requiere una fila
    real de `Usuario` (managed=False, inexistente en sqlite) porque
    `AccessToken.for_user()` solo necesita un `auth_user` de Django.
    """
    user = User.objects.create_user(
        username=f"jwt_test_{uuid.uuid4().hex[:12]}", password="Password123!"
    )
    token = AccessToken.for_user(user)
    token["email"] = correo
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


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
            "municipio": Municipio.objects.get(codigo="PAMPLONA").pk,
            "latitud": "texto_invalido",
            "longitud": "-72.500000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)

    def test_formulario_rechaza_latitud_fuera_de_rango(self):
        """El formulario rechaza latitudes mayores a 90 o menores a -90."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Fuera Rango",
            "municipio": Municipio.objects.get(codigo="PAMPLONA").pk,
            "latitud": "95.500000",
            "longitud": "-72.500000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)

    def test_formulario_rechaza_longitud_fuera_de_rango(self):
        """El formulario rechaza longitudes mayores a 180 o menores a -180."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Fuera Rango",
            "municipio": Municipio.objects.get(codigo="PAMPLONA").pk,
            "latitud": "7.500000",
            "longitud": "185.000000",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("longitud", form.errors)

    def test_formulario_rechaza_par_incompleto_latitud_sola(self):
        """El formulario no valida si solo se ingresa latitud."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Par Incompleto",
            "municipio": Municipio.objects.get(codigo="PAMPLONA").pk,
            "latitud": "7.893910",
            "longitud": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("longitud", form.errors)

    def test_formulario_rechaza_par_incompleto_longitud_sola(self):
        """El formulario no valida si solo se ingresa longitud."""
        form = FincaRegistroForm(data={
            "nombre": "Finca Par Incompleto",
            "municipio": Municipio.objects.get(codigo="PAMPLONA").pk,
            "latitud": "",
            "longitud": "-72.507820",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("latitud", form.errors)


class TestGeorreferenciacionModelo(TestCase):
    """Pruebas del modelo Finca y esquema de georreferenciación (HU07-ST5 / SCRUM-98)."""

    def setUp(self):
        self.municipio = Municipio.objects.filter(nombre="Pamplona").first() or Municipio.objects.create(
            codigo="TEST_PAMPLONA", nombre="Pamplona"
        )
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
            "municipio": Municipio.objects.get(codigo="LABATECA").pk,
            "vereda": "Centro",
        })
        self.assertTrue(form_sin_coords.is_valid(), f"Errores: {form_sin_coords.errors}")
        # FincaModelForm.save() ahora exige un productor_id real (ya no
        # inventa un UUID de respaldo como hacía antes) -- se lo pasamos
        # explícitamente, como haría la vista tras resolver la sesión.
        finca_sin_coords = form_sin_coords.save(productor_id=uuid.uuid4())
        self.assertIsNone(finca_sin_coords.latitud)
        self.assertIsNone(finca_sin_coords.longitud)

        # Caso con coordenadas
        form_con_coords = FincaModelForm(data={
            "nombre": "Finca Modelo Con Coords",
            "municipio": Municipio.objects.get(codigo="SALAZAR_PALMAS").pk,
            "vereda": "La Playa",
            "latitud": "7.771234",
            "longitud": "-72.812345",
        })
        self.assertTrue(form_con_coords.is_valid(), f"Errores: {form_con_coords.errors}")
        finca_con_coords = form_con_coords.save(productor_id=uuid.uuid4())
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
            "municipio": Municipio.objects.get(codigo="ARBOLEDAS").pk,
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
            "municipio": Municipio.objects.get(codigo="TOLEDO").pk,
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
            "municipio": Municipio.objects.get(codigo="CUCUTA").pk,
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
        self.municipio = Municipio.objects.filter(nombre="Toledo").first() or Municipio.objects.create(
            codigo="TEST_MUNICIPIO", nombre="Toledo"
        )

    def test_vista_post_persiste_finca_con_coordenadas_en_bd(self):
        """Al enviar coordenadas válidas, la vista persiste los valores Decimal en BD."""
        _iniciar_sesion_productor(self.client)
        response = self.client.post(self.url_registro, {
            "nombre": "Finca San Francisco",
            "municipio": Municipio.objects.get(codigo="SALAZAR_PALMAS").pk,
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
        _iniciar_sesion_productor(self.client)
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Sin Coordenadas",
            "municipio": Municipio.objects.get(codigo="ARBOLEDAS").pk,
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
        """
        Si hay un productor real identificado en sesión
        (`request.session['usuario_id']`, el mismo patrón que deja
        `login_view` -- ver usuarios/views.py:492), la finca queda
        asociada a ESE productor, no a un UUID inventado.
        """
        productor_id = _iniciar_sesion_productor(self.client)

        response = self.client.post(self.url_registro, {
            "nombre": "Finca con Productor Sesion",
            "municipio": Municipio.objects.get(codigo="TOLEDO").pk,
            "latitud": "7.300000",
            "longitud": "-72.480000",
        })
        self.assertEqual(response.status_code, 302)

        finca = Finca.objects.get(nombre="Finca con Productor Sesion")
        self.assertEqual(str(finca.productor_id), productor_id)

        finca = Finca.objects.filter(nombre="Finca con Productor Sesion").first()
        self.assertIsNotNone(finca)
        self.assertEqual(finca.latitud, Decimal("7.300000"))

    @patch("fincas.views.Usuario")
    def test_api_post_persiste_coordenadas_en_bd(self, mock_usuario_model):
        """Endpoint API guarda coordenadas y responde 201 Created."""
        # `usuarios.Usuario` es managed=False (no existe en la BD de pruebas),
        # así que se mockea igual que en usuarios/tests.py: solo hace falta
        # que `_resolver_productor_id` encuentre un id al buscar por correo.
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(
            id=uuid.uuid4()
        )
        payload = {
            "nombre": "Finca API Coords",
            "municipio": "Lourdes",
            "latitud": "7.945000",
            "longitud": "-72.835000",
        }
        response = self.client.post(
            self.url_api, payload, content_type="application/json", **_jwt_bearer_headers()
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["latitud"], "7.945000")
        self.assertEqual(response.json()["longitud"], "-72.835000")
        self.assertTrue(response.json()["tiene_georreferenciacion"])

        finca = Finca.objects.get(id=response.json()["id"])
        self.assertEqual(finca.latitud, Decimal("7.945000"))
        self.assertEqual(finca.longitud, Decimal("-72.835000"))

    @patch("fincas.views.Usuario")
    def test_api_post_sin_coordenadas_almacena_null(self, mock_usuario_model):
        """Endpoint API guarda NULL cuando latitud y longitud son omitidos."""
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(
            id=uuid.uuid4()
        )
        payload = {
            "nombre": "Finca API Sin Coords",
            "municipio": "Bochalema",
        }
        response = self.client.post(
            self.url_api, payload, content_type="application/json", **_jwt_bearer_headers()
        )
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
            **_jwt_bearer_headers(),
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
        _iniciar_sesion_productor(self.client)
        response = self.client.post(self.url_registro, {
            "nombre": "Finca La Esperanza",
            "municipio": Municipio.objects.get(codigo="TOLEDO").pk,
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
        _iniciar_sesion_productor(self.client)
        response = self.client.post(self.url_registro, {
            "nombre": "Finca El Cafetal",
            "municipio": Municipio.objects.get(codigo="ARBOLEDAS").pk,
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
            "municipio": Municipio.objects.get(codigo="SALAZAR_PALMAS").pk,
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
            "municipio": Municipio.objects.get(codigo="SALAZAR_PALMAS").pk,
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
            "municipio": Municipio.objects.get(codigo="SALAZAR_PALMAS").pk,
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
            "municipio": Municipio.objects.get(codigo="SALAZAR_PALMAS").pk,
            "latitud": "7.893910",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)
        self.assertContains(response, "debe ingresar también la longitud")

    def test_dod_ciclo_completo_integracion_y_listado(self):
        """DoD Escenario 4: Ciclo completo que verifica renderizado de fincas con y sin coordenadas."""
        _iniciar_sesion_productor(self.client)
        # 1. Crear finca sin coordenadas
        self.client.post(self.url_registro, {
            "nombre": "Predio Sin GPS",
            "municipio": Municipio.objects.get(codigo="LOURDES").pk,
            "latitud": "",
            "longitud": "",
        })

        # 2. Crear finca con coordenadas
        self.client.post(self.url_registro, {
            "nombre": "Predio Con GPS",
            "municipio": Municipio.objects.get(codigo="TOLEDO").pk,
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
        municipio = Municipio.objects.create(codigo="TEST_PAMPLONA_MOD", nombre="Pamplona (prueba)")
        self.assertEqual(municipio.departamento, "Norte de Santander")
        self.assertTrue(municipio.activo)

    def test_codigo_unico_en_el_catalogo(self):
        Municipio.objects.create(codigo="TEST_CUCUTA_UNICO", nombre="Cúcuta (prueba)")
        with self.assertRaises(IntegrityError):
            Municipio.objects.create(codigo="TEST_CUCUTA_UNICO", nombre="Cúcuta (duplicado)")


class FincaModelTests(TestCase):
    """Pruebas del modelo Finca con relación a Productor y Municipio."""

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="TEST_PAMPLONA_FINCA", nombre="Pamplona (prueba)")
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
        self.municipio = Municipio.objects.create(codigo="TEST_PAMPLONA_ASOC", nombre="Pamplona (prueba)")
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


class ValidacionCamposObligatoriosRegistroTests(TestCase):
    """
    HU06-ST4 (SCRUM-89): Validar campos obligatorios y consistencia de
    datos del registro.

    Criterio de aceptación: "Rechazo en backend si falta el nombre o el
    municipio seleccionado no es válido." Estas pruebas verifican ambas
    mitades del criterio, en la vista web y en el endpoint de la API,
    y confirman que un municipio inválido no se "resuelve" creando uno
    nuevo (ese era, precisamente, el defecto que corrigió HU06-ST3).
    """

    def setUp(self):
        self.client = Client()
        self.url_registro = reverse("finca_registro")
        self.url_api = reverse("api_finca_crear")
        self.municipio_valido = Municipio.objects.get(codigo="TOLEDO")

    # -------------------------------------------------------------------
    # Falta el nombre
    # -------------------------------------------------------------------
    def test_vista_rechaza_registro_sin_nombre(self):
        """La vista no crea la finca si el nombre viene vacío."""
        conteo_previo = Finca.objects.count()
        response = self.client.post(self.url_registro, {
            "nombre": "",
            "municipio": self.municipio_valido.pk,
            "latitud": "",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)

    @patch("fincas.views.Usuario")
    def test_api_rechaza_registro_sin_nombre(self, mock_usuario_model):
        """El endpoint API responde 400 si falta el nombre."""
        payload = {
            "municipio": self.municipio_valido.pk,
        }
        response = self.client.post(
            self.url_api, payload, content_type="application/json", **_jwt_bearer_headers()
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre", response.json())
        # El rechazo ocurre en la validación del serializer, antes de
        # intentar resolver el productor.
        mock_usuario_model.objects.filter.assert_not_called()

    # -------------------------------------------------------------------
    # Municipio faltante o inválido (no se "resuelve" creando uno nuevo)
    # -------------------------------------------------------------------
    def test_vista_rechaza_registro_sin_municipio_seleccionado(self):
        """La vista no crea la finca si no se selecciona ningún municipio."""
        conteo_previo = Finca.objects.count()
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Sin Municipio",
            "municipio": "",
            "latitud": "",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)

    def test_vista_rechaza_municipio_que_no_existe_en_el_catalogo(self):
        """
        Un id de municipio que no existe en el catálogo (por ejemplo, un
        valor manipulado fuera del <select>) se rechaza; ya NO se crea
        un municipio nuevo "al vuelo" como antes de HU06-ST3.
        """
        conteo_previo = Finca.objects.count()
        id_inexistente = Municipio.objects.order_by("-pk").first().pk + 1000
        response = self.client.post(self.url_registro, {
            "nombre": "Finca Municipio Inventado",
            "municipio": id_inexistente,
            "latitud": "",
            "longitud": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Finca.objects.count(), conteo_previo)
        self.assertEqual(Municipio.objects.filter(pk=id_inexistente).count(), 0)

    def test_api_rechaza_municipio_que_no_existe_en_el_catalogo(self):
        """
        El endpoint API responde 400 ante un nombre de municipio que no
        existe, y NO crea un municipio nuevo a partir de ese texto.
        """
        conteo_municipios_previo = Municipio.objects.count()
        payload = {
            "nombre": "Finca Municipio Inventado API",
            "municipio": "Municipio Que No Existe",
        }
        response = self.client.post(
            self.url_api, payload, content_type="application/json", **_jwt_bearer_headers()
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("municipio", response.json())
        self.assertEqual(Municipio.objects.count(), conteo_municipios_previo)


# =============================================================================
# SUITE HU06-ST6 (SCRUM-92): LISTADO "MIS FINCAS" POR PRODUCTOR
# =============================================================================

class ListadoMisFincasTests(TestCase):
    """
    HU06-ST6 (SCRUM-92): Listar fincas registradas por productor.
    Criterio de aceptación: "Implementar la consulta o vista que permita
    visualizar las fincas ya asociadas a cada productor."

    También verifica el criterio de "aislamiento entre usuarios" que pide
    SCRUM-93 / HU06-ST7: un productor jamás debe ver las fincas de otro.
    """

    def setUp(self):
        self.client = Client()
        self.url_mis_fincas = reverse("mis_fincas")
        self.municipio = Municipio.objects.create(
            codigo="TEST_MISFINCAS", nombre="Toledo (prueba mis fincas)"
        )

    def test_redirige_a_login_si_no_hay_sesion(self):
        """Un visitante anónimo no puede ver el listado: se le redirige a login."""
        response = self.client.get(self.url_mis_fincas)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_solo_muestra_fincas_del_productor_autenticado(self):
        """
        Aislamiento entre usuarios: el productor A nunca debe ver, en su
        propio listado, las fincas registradas por el productor B.
        """
        productor_a = uuid.uuid4()
        productor_b = uuid.uuid4()

        Finca.objects.create(nombre="Finca de A", productor_id=productor_a, municipio=self.municipio)
        Finca.objects.create(nombre="Otra finca de A", productor_id=productor_a, municipio=self.municipio)
        Finca.objects.create(nombre="Finca de B", productor_id=productor_b, municipio=self.municipio)

        _iniciar_sesion_productor(self.client, usuario_id=productor_a)
        response = self.client.get(self.url_mis_fincas)

        self.assertEqual(response.status_code, 200)
        nombres_mostrados = {finca.nombre for finca in response.context["fincas"]}
        self.assertEqual(nombres_mostrados, {"Finca de A", "Otra finca de A"})
        self.assertNotIn("Finca de B", nombres_mostrados)

    def test_muestra_estado_vacio_si_el_productor_no_tiene_fincas(self):
        """Un productor sin fincas registradas ve la página (200), con el listado vacío."""
        _iniciar_sesion_productor(self.client)
        response = self.client.get(self.url_mis_fincas)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["fincas"]), [])

    def test_fincas_inactivas_no_aparecen_en_el_listado(self):
        """Una finca dada de baja (activo=False) no debe listarse."""
        productor_id = _iniciar_sesion_productor(self.client)
        Finca.objects.create(
            nombre="Finca Activa", productor_id=productor_id, municipio=self.municipio
        )
        Finca.objects.create(
            nombre="Finca Inactiva", productor_id=productor_id, municipio=self.municipio, activo=False
        )

        response = self.client.get(self.url_mis_fincas)
        nombres_mostrados = {finca.nombre for finca in response.context["fincas"]}
        self.assertEqual(nombres_mostrados, {"Finca Activa"})

    def test_fincas_con_coordenadas_se_incluyen_en_los_datos_del_mapa(self):
        """Las fincas georreferenciadas sí deben aparecer en `fincas_geo` (datos del mapa)."""
        productor_id = _iniciar_sesion_productor(self.client)
        Finca.objects.create(
            nombre="Finca Con GPS",
            productor_id=productor_id,
            municipio=self.municipio,
            latitud="7.373000",
            longitud="-72.648000",
        )

        response = self.client.get(self.url_mis_fincas)
        fincas_geo = response.context["fincas_geo"]
        self.assertEqual(len(fincas_geo), 1)
        self.assertEqual(fincas_geo[0]["nombre"], "Finca Con GPS")
        self.assertEqual(fincas_geo[0]["municipio"], self.municipio.nombre)

    def test_fincas_sin_coordenadas_se_excluyen_de_los_datos_del_mapa(self):
        """
        Una finca sin georreferenciación debe seguir apareciendo en
        `fincas` (listado de tarjetas) pero NO en `fincas_geo` (no hay
        coordenada que pintar como marcador).
        """
        productor_id = _iniciar_sesion_productor(self.client)
        Finca.objects.create(
            nombre="Finca Sin GPS", productor_id=productor_id, municipio=self.municipio
        )

        response = self.client.get(self.url_mis_fincas)
        self.assertEqual(len(response.context["fincas"]), 1)
        self.assertEqual(response.context["fincas_geo"], [])


# =============================================================================
# SUITE HU-09: PARAMETRIZACIÓN DEL CATÁLOGO DE MUNICIPIOS (SCRUM-114)
# =============================================================================


class TestScrum114ModeloCatalogoMunicipios(TestCase):
    """
    Subtarea: SCRUM-114 / HU09-ST5: Diseñar el modelo de datos del catálogo de municipios.
    DoD:
    - Modelo Municipio con nombre, departamento y booleano activo=True.
    - Auditoría básica (creado_en y actualizado_en).
    - Soporte para inactivación lógica (activo=False).
    - Normalización y generación por defecto de código identificador.
    """

    def setUp(self):
        Municipio.objects.all().delete()

    def test_dod_municipio_con_nombre_departamento_y_activo_true_por_defecto(self):
        """DoD: Municipio con nombre, departamento y booleano activo=True."""
        muni = Municipio.objects.create(
            nombre="Toledo",
            departamento="Norte de Santander",
        )
        self.assertEqual(muni.nombre, "Toledo")
        self.assertEqual(muni.departamento, "Norte de Santander")
        self.assertTrue(muni.activo)
        self.assertIsNotNone(muni.creado_en)
        self.assertIsNotNone(muni.actualizado_en)

    def test_municipio_departamento_usa_valor_por_defecto(self):
        """El departamento por defecto debe ser 'Norte de Santander'."""
        muni = Municipio.objects.create(nombre="Salazar")
        self.assertEqual(muni.departamento, "Norte de Santander")
        self.assertTrue(muni.activo)

    def test_municipio_permite_inactivacion_logica(self):
        """El campo activo permite inactivación lógica sin borrar el registro."""
        muni = Municipio.objects.create(nombre="Bochalema", activo=False)
        self.assertFalse(muni.activo)
        # Sigue existiendo en la base de datos (inactivación lógica)
        self.assertTrue(Municipio.objects.filter(nombre="Bochalema").exists())

    def test_municipio_auditoria_actualizado_en_cambia_al_modificar(self):
        """El campo actualizado_en se actualiza automáticamente al modificar el modelo."""
        muni = Municipio.objects.create(nombre="Arboledas")
        fecha_creacion = muni.actualizado_en
        muni.nombre = "Arboledas Modificado"
        muni.save()
        muni.refresh_from_db()
        self.assertGreaterEqual(muni.actualizado_en, fecha_creacion)

    def test_municipio_genera_codigo_automatico_si_no_se_provee(self):
        """Si no se ingresa un código, se autogenera a partir del nombre."""
        muni = Municipio.objects.create(nombre="San Cayetano")
        self.assertEqual(muni.codigo, "SAN_CAYETANO")

    def test_municipio_str_incluye_nombre_departamento_y_estado(self):
        """El método __str__ muestra el nombre, departamento y si está Activo/Inactivo."""
        muni_activo = Municipio.objects.create(nombre="Lourdes", activo=True)
        self.assertIn("Lourdes", str(muni_activo))
        self.assertIn("Activo", str(muni_activo))

        muni_inactivo = Municipio.objects.create(nombre="Gramalote", activo=False)
        self.assertIn("Gramalote", str(muni_inactivo))
        self.assertIn("Inactivo", str(muni_inactivo))


class TestScrum117PrepararDatosInicialesMunicipios(TestCase):
    """
    Subtarea: SCRUM-117 / HU09-ST7: Preparar datos iniciales del catálogo de municipios.
    DoD: Fixture o comando de carga inicial con los municipios cafeteros de Norte de Santander.
    """

    def setUp(self):
        Municipio.objects.all().delete()

    def test_comando_cargar_municipios_inserta_40_municipios(self):
        """El comando de gestión inserta los 40 municipios de Norte de Santander."""
        Municipio.objects.all().delete()
        call_command("cargar_municipios")
        self.assertEqual(Municipio.objects.count(), 40)
        self.assertTrue(all(m.departamento == "Norte de Santander" for m in Municipio.objects.all()))
        self.assertTrue(all(m.activo for m in Municipio.objects.all()))

    def test_comando_cargar_municipios_es_idempotente(self):
        """Ejecutar el comando dos veces consecutivas no duplica municipios."""
        call_command("cargar_municipios")
        conteo_inicial = Municipio.objects.count()
        call_command("cargar_municipios")
        self.assertEqual(Municipio.objects.count(), conteo_inicial)

    def test_comando_reactivar_municipio_inactivado(self):
        """Con la bandera --reactivar, se activan los municipios previamente inactivados."""
        call_command("cargar_municipios")
        toledo = Municipio.objects.get(nombre="Toledo")
        toledo.activo = False
        toledo.save()
        self.assertFalse(Municipio.objects.get(nombre="Toledo").activo)

        call_command("cargar_municipios", reactivar=True)
        toledo.refresh_from_db()
        self.assertTrue(toledo.activo)

    def test_fixture_municipios_norte_de_santander_carga_exitosamente(self):
        """El fixture JSON de Django carga los 40 municipios canónicos."""
        Municipio.objects.all().delete()
        call_command("loaddata", "municipios_norte_de_santander")
        self.assertEqual(Municipio.objects.count(), 40)

    def test_municipios_cafeteros_clave_presentes_con_codigo_dane(self):
        """Verifica que municipios de tradición cafetera tienen sus códigos DANE correctos."""
        call_command("cargar_municipios")
        municipios_clave = {
            "Toledo": "54820",
            "Labateca": "54377",
            "Arboledas": "54051",
            "Salazar de Las Palmas": "54660",
            "Pamplona": "54518",
            "Convención": "54206",
            "Bochalema": "54099",
            "Lourdes": "54418",
            "Gramalote": "54313",
            "Cúcuta": "54001",
        }
        for nombre, codigo in municipios_clave.items():
            muni = Municipio.objects.filter(nombre=nombre).first()
            self.assertIsNotNone(muni, f"El municipio {nombre} no fue encontrado en el catálogo.")
            self.assertEqual(muni.codigo, codigo)
            self.assertTrue(muni.activo)


class TestScrum115ValidacionesCatalogoMunicipios(TestCase):
    """
    Subtarea: SCRUM-115 / HU09-ST6: Agregar validaciones y reglas de negocio del catálogo.
    DoD: Bloqueo de nombres de municipios duplicados en el mismo departamento.
    """

    def setUp(self):
        Municipio.objects.all().delete()
        self.municipio_base = Municipio.objects.create(
            codigo="54518",
            nombre="Pamplona",
            departamento="Norte de Santander",
            activo=True,
        )

    def test_dod_bloqueo_nombres_duplicados_mismo_departamento_clean(self):
        """DoD: Rechaza la creación de un municipio con el mismo nombre y departamento en clean()."""
        muni_duplicado = Municipio(
            codigo="54999",
            nombre="Pamplona",
            departamento="Norte de Santander",
        )
        with self.assertRaises(ValidationError) as ctx:
            muni_duplicado.clean()

        self.assertIn("nombre", ctx.exception.message_dict)
        self.assertIn("Ya existe un municipio con el nombre 'Pamplona'", ctx.exception.message_dict["nombre"][0])

    def test_bloqueo_nombres_duplicados_case_insensitive_y_espacios(self):
        """Bloquea nombres duplicados sin importar mayúsculas/minúsculas ni espacios iniciales/finales."""
        muni_duplicado = Municipio(
            codigo="54998",
            nombre="   pamplona   ",
            departamento="norte de santander",
        )
        with self.assertRaises(ValidationError) as ctx:
            muni_duplicado.clean()

        self.assertIn("nombre", ctx.exception.message_dict)

    def test_permite_mismo_nombre_en_distintos_departamentos(self):
        """Permite que un municipio tenga el mismo nombre si pertenece a otro departamento."""
        muni_otro_departamento = Municipio.objects.create(
            codigo="68518",
            nombre="Pamplona",
            departamento="Santander",
        )
        self.assertEqual(muni_otro_departamento.nombre, "Pamplona")
        self.assertEqual(muni_otro_departamento.departamento, "Santander")

    def test_bloqueo_duplicados_nivel_base_de_datos_integrity_error(self):
        """Verifica que el constraint de base de datos lanza IntegrityError ante duplicados."""
        with self.assertRaises(IntegrityError):
            Municipio.objects.bulk_create([
                Municipio(
                    codigo="54997",
                    nombre="Pamplona",
                    departamento="Norte de Santander",
                )
            ])

    def test_nombre_municipio_es_obligatorio_y_no_vacio(self):
        """El nombre del municipio no puede ser nulo, vacío ni consistir solo en espacios."""
        muni_vacio = Municipio(nombre="   ", departamento="Norte de Santander")
        with self.assertRaises(ValidationError) as ctx:
            muni_vacio.clean()
        self.assertIn("nombre", ctx.exception.message_dict)

    def test_departamento_es_obligatorio_y_no_vacio(self):
        """El departamento no puede ser nulo, vacío ni consistir solo en espacios."""
        muni_dep_vacio = Municipio(nombre="Toledo", departamento="   ")
        with self.assertRaises(ValidationError) as ctx:
            muni_dep_vacio.clean()
        self.assertIn("departamento", ctx.exception.message_dict)

    def test_municipio_form_rechaza_duplicados_con_mensaje_amigable(self):
        """MunicipioForm valida y rechaza duplicados en el mismo departamento con mensaje amigable."""
        form = MunicipioForm(data={
            "codigo": "54519",
            "nombre": "Pamplona",
            "departamento": "Norte de Santander",
            "activo": True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("nombre", form.errors)
        self.assertIn("Ya existe un municipio con el nombre", form.errors["nombre"][0])

    def test_municipio_form_acepta_municipio_nuevo_valido(self):
        """MunicipioForm acepta un municipio nuevo que no esté duplicado."""
        form = MunicipioForm(data={
            "codigo": "54820",
            "nombre": "Toledo",
            "departamento": "Norte de Santander",
            "activo": True,
        })
        self.assertTrue(form.is_valid(), f"Errores encontrados: {form.errors}")
        muni = form.save()
        self.assertEqual(muni.nombre, "Toledo")

    def test_municipio_en_uso_puede_inactivarse_logicamente_manteniendo_integridad(self):
        """
        Regla de negocio: si un municipio tiene fincas asociadas,
        puede inactivarse lógicamente (activo=False) sin perder la relación histórica.
        """
        finca = Finca.objects.create(
            nombre="Finca Los Alpes",
            productor_id=uuid.uuid4(),
            municipio=self.municipio_base,
        )
        self.assertTrue(self.municipio_base.tiene_fincas_asociadas)
        self.assertEqual(self.municipio_base.total_fincas_asociadas, 1)

        # Inactivación lógica del municipio
        self.municipio_base.activo = False
        self.municipio_base.save()

        self.municipio_base.refresh_from_db()
        finca.refresh_from_db()
        self.assertFalse(self.municipio_base.activo)
        self.assertEqual(finca.municipio, self.municipio_base)
        self.assertTrue(self.municipio_base.tiene_fincas_asociadas)


# =============================================================================
# SUITE HU-09: SCRUM-116 (HU09-ST8) - PERMISOS PARA LA GESTIÓN DEL CATÁLOGO (RBAC)
# =============================================================================


class TestScrum116PermisosCatalogoMunicipios(SimpleTestCase):
    """
    Subtarea: SCRUM-116 / HU09-ST8: Configurar permisos para la gestión del catálogo (RBAC).

    Criterios de Aceptación (DoD):
    1. Restricción exclusiva de gestión (crear, editar, inactivar) a roles autorizados:
       - ADMINISTRADOR
       - ASOCIACION
    2. Bloqueo de acceso (403 Forbidden o redirección al login según corresponda) a:
       - PRODUCTOR
       - COMPRADOR
       - OPERARIO_CAMPO
       - CONSULTA_PUBLICA
       - Usuarios no autenticados (anónimos)
    3. Soporte para vistas basadas en sesión web y endpoints API REST (fail-closed).
    """

    def setUp(self):
        self.rf = RequestFactory()

    def _crear_request_web(self, autenticado: bool = True, rol: str = "", path: str = "/fincas/municipios/"):
        request = self.rf.get(path)
        request.user = type(
            "UserMock",
            (),
            {"is_authenticated": autenticado, "is_superuser": False, "username": "test_user"},
        )()
        request.session = {"rol": rol} if rol else {}
        request._messages = FallbackStorage(request)
        return request

    # -------------------------------------------------------------------------
    # 1. Pruebas directas de rol_puede_administrar_catalogos
    # -------------------------------------------------------------------------

    @patch("fincas.permissions.usuario_tiene_permiso")
    def test_roles_autorizados_pueden_administrar_catalogos(self, mock_tiene_permiso):
        """Los roles ADMINISTRADOR y ASOCIACION tienen permiso concedido en la matriz."""
        from fincas.permissions import rol_puede_administrar_catalogos

        mock_tiene_permiso.side_effect = lambda rol, perms: rol in ("ADMINISTRADOR", "ASOCIACION")

        self.assertTrue(rol_puede_administrar_catalogos("ADMINISTRADOR"))
        self.assertTrue(rol_puede_administrar_catalogos("ASOCIACION"))

    @patch("fincas.permissions.usuario_tiene_permiso")
    def test_roles_no_autorizados_son_rechazados(self, mock_tiene_permiso):
        """Roles como PRODUCTOR, COMPRADOR, OPERARIO_CAMPO o CONSULTA_PUBLICA no pueden administrar catálogos."""
        from fincas.permissions import rol_puede_administrar_catalogos

        mock_tiene_permiso.side_effect = lambda rol, perms: rol in ("ADMINISTRADOR", "ASOCIACION")

        roles_denegados = ["PRODUCTOR", "COMPRADOR", "OPERARIO_CAMPO", "CONSULTA_PUBLICA", "INVITADO"]
        for rol in roles_denegados:
            with self.subTest(rol=rol):
                self.assertFalse(rol_puede_administrar_catalogos(rol))

    def test_rol_vacio_o_nulo_devuelve_false(self):
        """Si el rol es None o string vacío, la verificación es fail-closed."""
        from fincas.permissions import rol_puede_administrar_catalogos

        self.assertFalse(rol_puede_administrar_catalogos(""))
        self.assertFalse(rol_puede_administrar_catalogos(None))

    # -------------------------------------------------------------------------
    # 2. Pruebas del decorador web de sesión (permiso_administrar_catalogo_sesion)
    # -------------------------------------------------------------------------

    def test_sesion_no_autenticada_redirige_a_login(self):
        """Un usuario sin iniciar sesión es redirigido al login con el parámetro ?next=."""
        from fincas.permissions import permiso_administrar_catalogo_sesion

        @permiso_administrar_catalogo_sesion
        def dummy_vista(request):
            return HttpResponse("OK")

        req = self._crear_request_web(autenticado=False, path="/fincas/municipios/crear/")
        resp = dummy_vista(req)

        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)
        self.assertIn("next=/fincas/municipios/crear/", resp.url)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_sesion_con_rol_autorizado_accede_exitosamente(self, _mock_perm):
        """Una sesión con rol autorizado ejecuta la vista normalmente (HTTP 200)."""
        from fincas.permissions import permiso_administrar_catalogo_sesion

        @permiso_administrar_catalogo_sesion
        def dummy_vista(request):
            return HttpResponse("Vista permitida")

        for rol in ("ADMINISTRADOR", "ASOCIACION"):
            with self.subTest(rol=rol):
                req = self._crear_request_web(autenticado=True, rol=rol)
                resp = dummy_vista(req)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.content.decode(), "Vista permitida")

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_sesion_con_rol_no_autorizado_recibe_403_forbidden(self, _mock_perm):
        """Un rol no autorizado (ej. Productor) recibe 403 Forbidden por defecto."""
        from fincas.permissions import permiso_administrar_catalogo_sesion

        @permiso_administrar_catalogo_sesion
        def dummy_vista(request):
            return HttpResponse("No debería verse")

        for rol in ("PRODUCTOR", "COMPRADOR", "OPERARIO_CAMPO", "CONSULTA_PUBLICA"):
            with self.subTest(rol=rol):
                req = self._crear_request_web(autenticado=True, rol=rol)
                resp = dummy_vista(req)
                self.assertEqual(resp.status_code, 403)
                self.assertIn("No tiene permiso para acceder a esta sección.", resp.content.decode())

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_sesion_con_forbidden_false_redirige_a_home(self, _mock_perm):
        """Si forbidden_on_denied=False, redirige a 'home' con mensaje flash de error."""
        from fincas.permissions import permiso_administrar_catalogo_sesion

        @permiso_administrar_catalogo_sesion(forbidden_on_denied=False)
        def dummy_vista(request):
            return HttpResponse("OK")

        req = self._crear_request_web(autenticado=True, rol="PRODUCTOR")
        resp = dummy_vista(req)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("home"))

    # -------------------------------------------------------------------------
    # 3. Pruebas de helper request_puede_administrar_catalogos
    # -------------------------------------------------------------------------

    @patch("fincas.permissions.rol_puede_administrar_catalogos")
    def test_request_puede_administrar_catalogos_con_superuser(self, mock_rol):
        """Superusuario de Django tiene acceso garantizado."""
        from fincas.permissions import request_puede_administrar_catalogos

        req = self._crear_request_web(autenticado=True)
        req.user.is_superuser = True
        self.assertTrue(request_puede_administrar_catalogos(req))

    @patch("fincas.permissions.rol_puede_administrar_catalogos", return_value=True)
    def test_request_puede_administrar_catalogos_con_rol_sesion(self, mock_rol):
        """Request con rol válido en sesión retorna True."""
        from fincas.permissions import request_puede_administrar_catalogos

        req = self._crear_request_web(autenticado=True, rol="ASOCIACION")
        self.assertTrue(request_puede_administrar_catalogos(req))

    def test_request_puede_administrar_catalogos_con_request_nula_o_anonima(self):
        """Request nula o sin usuario autenticado devuelve False."""
        from fincas.permissions import request_puede_administrar_catalogos

        self.assertFalse(request_puede_administrar_catalogos(None))
        req = self._crear_request_web(autenticado=False)
        self.assertFalse(request_puede_administrar_catalogos(req))

    # -------------------------------------------------------------------------
    # 4. Pruebas de DRF Permission Class (TienePermisoAdministrarCatalogo)
    # -------------------------------------------------------------------------

    @patch("fincas.permissions.rol_puede_administrar_catalogos")
    def test_tiene_permiso_drf_concede_a_token_con_rol_autorizado(self, mock_rol_check):
        """TienePermisoAdministrarCatalogo concede si el token JWT contiene un rol válido."""
        from fincas.permissions import TienePermisoAdministrarCatalogo

        mock_rol_check.return_value = True
        import json
        perm = TienePermisoAdministrarCatalogo()

        request = self.rf.get("/fincas/api/municipios/")
        request.auth = {"role_code": "ASOCIACION"}
        view = type("ViewMock", (), {})()

        self.assertTrue(perm.has_permission(request, view))
        mock_rol_check.assert_called_with("ASOCIACION")

    @patch("fincas.permissions.rol_puede_administrar_catalogos")
    def test_tiene_permiso_drf_deniega_a_token_con_rol_no_autorizado(self, mock_rol_check):
        """TienePermisoAdministrarCatalogo deniega si el token tiene rol no autorizado."""
        from fincas.permissions import TienePermisoAdministrarCatalogo

        mock_rol_check.return_value = False
        perm = TienePermisoAdministrarCatalogo()

        request = self.rf.get("/fincas/api/municipios/")
        request.auth = {"role_code": "PRODUCTOR"}
        view = type("ViewMock", (), {})()

        self.assertFalse(perm.has_permission(request, view))

    def test_tiene_permiso_drf_deniega_sin_token(self):
        """TienePermisoAdministrarCatalogo deniega peticiones sin token JWT."""
        from fincas.permissions import TienePermisoAdministrarCatalogo

        perm = TienePermisoAdministrarCatalogo()
        request = self.rf.get("/fincas/api/municipios/")
        request.auth = None
        view = type("ViewMock", (), {})()

        self.assertFalse(perm.has_permission(request, view))

    # -------------------------------------------------------------------------
    # 5. Pruebas del decorador API (permiso_administrar_catalogo_api)
    # -------------------------------------------------------------------------

    def test_decorador_api_rechaza_peticion_sin_token_con_401(self):
        """Endpoint de API rechaza peticiones sin token con HTTP 401."""
        import json
        from fincas.permissions import permiso_administrar_catalogo_api

        @permiso_administrar_catalogo_api
        def dummy_api(request):
            return JsonResponse({"status": "ok"})

        request = self.rf.post("/fincas/api/municipios/")
        response = dummy_api(request)

        self.assertEqual(response.status_code, 401)
        data = json.loads(response.content.decode("utf-8"))
        self.assertIn("error", data)


# =============================================================================
# SUITE HU-09: SCRUM-112 (HU09-ST3) - SERVICIOS Y API PARA CREAR MUNICIPIOS
# =============================================================================


class TestScrum112CrearMunicipioServicioYApi(TestCase):
    """
    Subtarea: SCRUM-112 / HU09-ST3: Implementar servicios y API para crear municipios.

    Criterios de Aceptación (DoD):
    1. Servicio de dominio `crear_municipio` que persiste municipios validando unicidad
       por departamento, nombres no vacíos y códigos sugeridos automáticos.
    2. Endpoint REST `POST /fincas/api/municipios/` protegido con RBAC:
       - 201 Created para roles autorizados (ASOCIACION, ADMINISTRADOR).
       - 401 Unauthorized para peticiones anónimas sin token.
       - 403 Forbidden para roles no autorizados (PRODUCTOR, COMPRADOR, etc.).
       - 400 Bad Request ante duplicados en el mismo departamento o datos inválidos.
    3. Endpoint REST `GET /fincas/api/municipios/` para listar el catálogo con filtros (?q, ?departamento, ?activo).
    """

    def setUp(self):
        Municipio.objects.all().delete()
        self.client = Client()
        self.url_municipios = reverse("api_municipios_coleccion")
        self.municipio_existente = Municipio.objects.create(
            codigo="54001",
            nombre="Cúcuta",
            departamento="Norte de Santander",
            activo=True,
        )

    # -------------------------------------------------------------------------
    # 1. Pruebas de la Capa de Servicio (crear_municipio)
    # -------------------------------------------------------------------------

    def test_servicio_crear_municipio_con_datos_completos(self):
        """El servicio crea y persiste un municipio con todos los atributos válidos."""
        from fincas.services import crear_municipio

        muni = crear_municipio(
            nombre="Salazar de Las Palmas",
            departamento="Norte de Santander",
            codigo="54660",
            activo=True,
        )
        self.assertIsNotNone(muni.id)
        self.assertEqual(muni.nombre, "Salazar de Las Palmas")
        self.assertEqual(muni.codigo, "54660")
        self.assertTrue(muni.activo)
        self.assertEqual(muni.departamento, "Norte de Santander")

    def test_servicio_crear_municipio_genera_codigo_sugerido_si_se_omite(self):
        """Si no se proporciona código, el servicio genera uno sugerido no nulo y único."""
        from fincas.services import crear_municipio

        muni = crear_municipio(
            nombre="Gramalote",
            departamento="Norte de Santander",
        )
        self.assertIsNotNone(muni.codigo)
        self.assertTrue(muni.codigo.startswith("NDS-") or muni.codigo.startswith("NOR-"))
        self.assertIn("GRAMALOTE", muni.codigo)
        self.assertEqual(muni.nombre, "Gramalote")

    def test_servicio_crear_municipio_rechaza_nombre_vacio(self):
        """El servicio valida y rechaza nombres nulos o consistentes en solo espacios."""
        from fincas.services import crear_municipio

        with self.assertRaises(ValidationError) as ctx:
            crear_municipio(nombre="   ", departamento="Norte de Santander")
        self.assertIn("nombre", ctx.exception.message_dict)

    def test_servicio_crear_municipio_rechaza_departamento_vacio(self):
        """El servicio valida y rechaza departamentos vacíos."""
        from fincas.services import crear_municipio

        with self.assertRaises(ValidationError) as ctx:
            crear_municipio(nombre="Pamplonita", departamento="   ")
        self.assertIn("departamento", ctx.exception.message_dict)

    def test_servicio_crear_municipio_bloquea_duplicados_mismo_departamento(self):
        """El servicio rechaza la creación si ya existe un municipio con el mismo nombre en el departamento."""
        from fincas.services import crear_municipio

        with self.assertRaises(ValidationError) as ctx:
            crear_municipio(nombre="  cúcuta  ", departamento="Norte de Santander")
        self.assertIn("nombre", ctx.exception.message_dict)

    def test_servicio_crear_municipio_permite_mismo_nombre_otro_departamento(self):
        """El servicio permite un municipio con el mismo nombre si pertenece a otro departamento."""
        from fincas.services import crear_municipio

        muni_valle = crear_municipio(
            nombre="Cúcuta",
            departamento="Valle del Cauca",
            codigo="76001",
        )
        self.assertEqual(muni_valle.nombre, "Cúcuta")
        self.assertEqual(muni_valle.departamento, "Valle del Cauca")

    # -------------------------------------------------------------------------
    # 2. Pruebas de la API REST - Listado y Filtros (GET)
    # -------------------------------------------------------------------------

    def test_api_get_municipios_lista_catalogo_exitosamente(self):
        """GET /fincas/api/municipios/ responde 200 OK con la lista de municipios."""
        response = self.client.get(self.url_municipios)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        nombres = [m["nombre"] for m in data]
        self.assertIn("Cúcuta", nombres)

    def test_api_get_municipios_filtra_por_busqueda_q(self):
        """GET /fincas/api/municipios/?q=cuc filtra por coincidencia parcial en nombre."""
        Municipio.objects.create(codigo="54820", nombre="Toledo", departamento="Norte de Santander")

        response = self.client.get(self.url_municipios, {"q": "cúc"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        nombres = [m["nombre"] for m in data]
        self.assertIn("Cúcuta", nombres)
        self.assertNotIn("Toledo", nombres)

    def test_api_get_municipios_filtra_por_activo(self):
        """GET /fincas/api/municipios/?activo=false filtra correctamente por estado."""
        Municipio.objects.create(
            codigo="54999",
            nombre="Municipio Inactivo",
            departamento="Norte de Santander",
            activo=False,
        )
        resp_activos = self.client.get(self.url_municipios, {"activo": "true"})
        nombres_activos = [m["nombre"] for m in resp_activos.json()]
        self.assertNotIn("Municipio Inactivo", nombres_activos)

        resp_inactivos = self.client.get(self.url_municipios, {"activo": "false"})
        nombres_inactivos = [m["nombre"] for m in resp_inactivos.json()]
        self.assertIn("Municipio Inactivo", nombres_inactivos)

    # -------------------------------------------------------------------------
    # 3. Pruebas de la API REST - Creación y Control de Acceso RBAC (POST)
    # -------------------------------------------------------------------------

    def _auth_headers(self, user, role_code="ASOCIACION"):
        """Genera encabezados de autorización Bearer JWT con el role_code indicado."""
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(user)
        token["role_code"] = role_code
        return {"HTTP_AUTHORIZATION": f"Bearer {str(token)}"}

    def test_api_post_sin_autenticacion_retorna_401(self):
        """Petición POST anónima sin token JWT es rechazada con HTTP 401."""
        response = self.client.post(
            self.url_municipios,
            {"nombre": "Arboledas", "departamento": "Norte de Santander"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=False)
    def test_api_post_con_rol_no_autorizado_retorna_403(self, _mock_rol):
        """Petición POST con rol sin permisos (ej. PRODUCTOR) es rechazada con HTTP 403."""
        user = User.objects.create_user(username="productor_user", password="Password123!")
        headers = self._auth_headers(user, role_code="PRODUCTOR")

        response = self.client.post(
            self.url_municipios,
            {"nombre": "Arboledas", "departamento": "Norte de Santander"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_post_con_rol_autorizado_crea_municipio_exitosamente_201(self, _mock_rol):
        """Petición POST con rol autorizado (ASOCIACION / ADMIN) crea el municipio y responde 201 Created."""
        user = User.objects.create_user(username="asociacion_user", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        payload = {
            "codigo": "54051",
            "nombre": "Arboledas",
            "departamento": "Norte de Santander",
            "activo": True,
        }
        response = self.client.post(
            self.url_municipios,
            payload,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["nombre"], "Arboledas")
        self.assertEqual(data["codigo"], "54051")
        self.assertTrue(data["activo"])
        self.assertIn("id", data)

        self.assertTrue(Municipio.objects.filter(nombre="Arboledas").exists())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_post_con_duplicado_mismo_departamento_retorna_400(self, _mock_rol):
        """Petición POST con nombre duplicado en el mismo departamento retorna HTTP 400 Bad Request."""
        user = User.objects.create_user(username="admin_user", password="Password123!")
        headers = self._auth_headers(user, role_code="ADMINISTRADOR")

        payload = {
            "nombre": "cúcuta",
            "departamento": "Norte de Santander",
        }
        response = self.client.post(
            self.url_municipios,
            payload,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_post_con_nombre_vacio_retorna_400(self, _mock_rol):
        """Petición POST con nombre vacío retorna HTTP 400 Bad Request."""
        user = User.objects.create_user(username="asoc_user2", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        payload = {
            "nombre": "   ",
            "departamento": "Norte de Santander",
        }
        response = self.client.post(
            self.url_municipios,
            payload,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre", response.json())


# =============================================================================
# SUITE HU-09: SCRUM-110 (HU09-ST1) - SERVICIOS Y API PARA EDITAR MUNICIPIOS
# =============================================================================


class TestScrum110EditarMunicipioServicioYApi(TestCase):
    """
    Subtarea: SCRUM-110 / HU09-ST1: Implementar servicios y API para editar municipios.

    Criterios de Aceptación (DoD):
    1. Servicio de dominio `editar_municipio`:
       - Permite actualizar nombre, departamento, código y estado activo.
       - Permite guardar cambios manteniendo el mismo nombre (sin auto-bloqueo por unicidad).
       - Bloquea duplicados si el nuevo nombre colisiona con otro municipio en el mismo departamento.
       - Valida que nombre o departamento no queden vacíos.
    2. Endpoint REST `GET /fincas/api/municipios/<pk>/`:
       - Retorna 200 OK con los datos del municipio.
       - Retorna 404 Not Found si no existe.
    3. Endpoint REST `PUT / PATCH /fincas/api/municipios/<pk>/`:
       - Retorna 200 OK y datos actualizados para roles autorizados (ASOCIACION / ADMINISTRADOR).
       - Retorna 401 Unauthorized para peticiones anónimas sin token.
       - Retorna 403 Forbidden para roles no autorizados (PRODUCTOR, COMPRADOR, etc.).
       - Retorna 400 Bad Request ante duplicados en el mismo departamento o datos inválidos.
       - Retorna 404 Not Found si el ID no existe.
    """

    def setUp(self):
        Municipio.objects.all().delete()
        self.client = Client()
        self.muni_pamplona = Municipio.objects.create(
            codigo="54518",
            nombre="Pamplona",
            departamento="Norte de Santander",
            activo=True,
        )
        self.muni_cucuta = Municipio.objects.create(
            codigo="54001",
            nombre="Cúcuta",
            departamento="Norte de Santander",
            activo=True,
        )
        self.url_detalle = reverse("api_municipio_detalle", kwargs={"pk": self.muni_pamplona.pk})

    def _auth_headers(self, user, role_code="ASOCIACION"):
        """Genera encabezados de autorización Bearer JWT con el role_code indicado."""
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(user)
        token["role_code"] = role_code
        return {"HTTP_AUTHORIZATION": f"Bearer {str(token)}"}

    # -------------------------------------------------------------------------
    # 1. Pruebas de la Capa de Servicio (editar_municipio)
    # -------------------------------------------------------------------------

    def test_servicio_editar_municipio_actualiza_campos_exitosamente(self):
        """El servicio actualiza el nombre y código correctamente."""
        from fincas.services import editar_municipio

        muni_editado = editar_municipio(
            self.muni_pamplona,
            nombre="Nueva Pamplona",
            codigo="54519",
        )
        self.assertEqual(muni_editado.nombre, "Nueva Pamplona")
        self.assertEqual(muni_editado.codigo, "54519")

        self.muni_pamplona.refresh_from_db()
        self.assertEqual(self.muni_pamplona.nombre, "Nueva Pamplona")
        self.assertEqual(self.muni_pamplona.codigo, "54519")

    def test_servicio_editar_municipio_por_id_exitoso(self):
        """El servicio acepta tanto una instancia de modelo como un ID numérico."""
        from fincas.services import editar_municipio

        muni_editado = editar_municipio(
            self.muni_pamplona.pk,
            activo=False,
        )
        self.assertFalse(muni_editado.activo)
        self.muni_pamplona.refresh_from_db()
        self.assertFalse(self.muni_pamplona.activo)

    def test_servicio_editar_municipio_permite_mantener_el_mismo_nombre(self):
        """No debe bloquearse a sí mismo cuando se guardan cambios manteniendo el mismo nombre."""
        from fincas.services import editar_municipio

        muni_editado = editar_municipio(
            self.muni_pamplona,
            nombre="Pamplona",
            activo=True,
        )
        self.assertEqual(muni_editado.nombre, "Pamplona")

    def test_servicio_editar_municipio_bloquea_duplicado_con_otro_municipio(self):
        """Rechaza la edición si el nuevo nombre ya pertenece a otro municipio en el departamento."""
        from fincas.services import editar_municipio

        with self.assertRaises(ValidationError) as ctx:
            editar_municipio(self.muni_pamplona, nombre="Cúcuta")
        self.assertIn("nombre", ctx.exception.message_dict)

    def test_servicio_editar_municipio_rechaza_nombre_vacio(self):
        """El servicio rechaza la actualización con nombre vacío."""
        from fincas.services import editar_municipio

        with self.assertRaises(ValidationError) as ctx:
            editar_municipio(self.muni_pamplona, nombre="   ")
        self.assertIn("nombre", ctx.exception.message_dict)

    def test_servicio_editar_municipio_inexistente_lanza_error(self):
        """El servicio lanza ValidationError si el ID no corresponde a ningún municipio."""
        from fincas.services import editar_municipio

        with self.assertRaises(ValidationError):
            editar_municipio(99999, nombre="Inexistente")

    # -------------------------------------------------------------------------
    # 2. Pruebas de la API REST - Consulta de Detalle (GET)
    # -------------------------------------------------------------------------

    def test_api_get_detalle_municipio_existente_retorna_200(self):
        """GET /fincas/api/municipios/<pk>/ retorna 200 OK con la información completa."""
        response = self.client.get(self.url_detalle)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], self.muni_pamplona.id)
        self.assertEqual(data["nombre"], "Pamplona")
        self.assertEqual(data["codigo"], "54518")

    def test_api_get_detalle_municipio_inexistente_retorna_404(self):
        """GET /fincas/api/municipios/99999/ retorna 404 Not Found."""
        url_inexistente = reverse("api_municipio_detalle", kwargs={"pk": 99999})
        response = self.client.get(url_inexistente)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    # -------------------------------------------------------------------------
    # 3. Pruebas de la API REST - Edición y Control RBAC (PUT / PATCH)
    # -------------------------------------------------------------------------

    def test_api_patch_sin_autenticacion_retorna_401(self):
        """Petición PATCH anónima sin token retorna HTTP 401 Unauthorized."""
        response = self.client.patch(
            self.url_detalle,
            {"nombre": "Pamplona Renombrada"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=False)
    def test_api_patch_con_rol_no_autorizado_retorna_403(self, _mock_rol):
        """Petición PATCH con rol no autorizado (ej. PRODUCTOR) retorna HTTP 403 Forbidden."""
        user = User.objects.create_user(username="productor_edit", password="Password123!")
        headers = self._auth_headers(user, role_code="PRODUCTOR")

        response = self.client.patch(
            self.url_detalle,
            {"nombre": "Pamplona Renombrada"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_patch_con_rol_autorizado_actualiza_exitosamente_200(self, _mock_rol):
        """Petición PATCH con rol autorizado (ASOCIACION / ADMIN) actualiza y retorna 200 OK."""
        user = User.objects.create_user(username="asoc_edit", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        response = self.client.patch(
            self.url_detalle,
            {"nombre": "Pamplona Alta", "codigo": "54519"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["nombre"], "Pamplona Alta")
        self.assertEqual(data["codigo"], "54519")

        self.muni_pamplona.refresh_from_db()
        self.assertEqual(self.muni_pamplona.nombre, "Pamplona Alta")
        self.assertEqual(self.muni_pamplona.codigo, "54519")

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_put_con_rol_autorizado_actualiza_todos_los_campos_200(self, _mock_rol):
        """Petición PUT con rol autorizado actualiza el municipio completo."""
        user = User.objects.create_user(username="admin_edit", password="Password123!")
        headers = self._auth_headers(user, role_code="ADMINISTRADOR")

        payload = {
            "codigo": "54520",
            "nombre": "Ciudad Mitrada",
            "departamento": "Norte de Santander",
            "activo": False,
        }
        response = self.client.put(
            self.url_detalle,
            payload,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["nombre"], "Ciudad Mitrada")
        self.assertFalse(data["activo"])

        self.muni_pamplona.refresh_from_db()
        self.assertEqual(self.muni_pamplona.nombre, "Ciudad Mitrada")
        self.assertFalse(self.muni_pamplona.activo)

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_patch_con_duplicado_mismo_departamento_retorna_400(self, _mock_rol):
        """Petición PATCH intentando renombrar al nombre de otro municipio existente retorna HTTP 400."""
        user = User.objects.create_user(username="asoc_edit2", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        response = self.client.patch(
            self.url_detalle,
            {"nombre": "cúcuta"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_patch_inexistente_retorna_404(self, _mock_rol):
        """Petición PATCH hacia un ID inexistente retorna HTTP 404 Not Found."""
        user = User.objects.create_user(username="asoc_edit3", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        url_inexistente = reverse("api_municipio_detalle", kwargs={"pk": 88888})
        response = self.client.patch(
            url_inexistente,
            {"nombre": "No Existe"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 404)


# =============================================================================
# SUITE HU-09: SCRUM-113 (HU09-ST4) - INACTIVACIÓN LÓGICA DE MUNICIPIOS
# =============================================================================


class TestScrum113InactivacionLogicaMunicipios(TestCase):
    """
    Subtarea: SCRUM-113 / HU09-ST4: Implementar inactivación lógica de municipios.

    Criterios de Aceptación (DoD):
    1. Inactivación exclusivamente lógica (`activo = False`) que preserva la integridad
       referencial histórica con las fincas ya asociadas.
    2. Los municipios inactivos no pueden asignarse a nuevas fincas.
    3. Servicios de dominio: `inactivar_municipio`, `reactivar_municipio`, `toggle_estado_municipio`.
    4. Endpoints REST `POST /fincas/api/municipios/<pk>/inactivar/` y `/toggle-activo/` protegidos con RBAC:
       - 200 OK para roles autorizados (ASOCIACION, ADMINISTRADOR) con mensaje informativo.
       - 401 Unauthorized para peticiones anónimas.
       - 403 Forbidden para roles sin permisos (PRODUCTOR, COMPRADOR, etc.).
       - 404 Not Found si el municipio no existe.
    """

    def setUp(self):
        Municipio.objects.all().delete()
        self.client = Client()
        self.municipio = Municipio.objects.create(
            codigo="54820",
            nombre="Toledo",
            departamento="Norte de Santander",
            activo=True,
        )
        self.url_inactivar = reverse("api_municipio_inactivar", kwargs={"pk": self.municipio.pk})
        self.url_toggle = reverse("api_municipio_toggle_activo", kwargs={"pk": self.municipio.pk})

    def _auth_headers(self, user, role_code="ASOCIACION"):
        """Genera encabezados de autorización Bearer JWT con el role_code indicado."""
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(user)
        token["role_code"] = role_code
        return {"HTTP_AUTHORIZATION": f"Bearer {str(token)}"}

    # -------------------------------------------------------------------------
    # 1. Pruebas de la Capa de Servicio
    # -------------------------------------------------------------------------

    def test_servicio_inactivar_municipio_preserva_fincas_asociadas(self):
        """Inactivar lógicamente un municipio con fincas no rompe la relación y genera mensaje explicativo."""
        from fincas.services import inactivar_municipio

        finca1 = Finca.objects.create(
            nombre="Finca Samaria",
            productor_id=uuid.uuid4(),
            municipio=self.municipio,
        )
        finca2 = Finca.objects.create(
            nombre="Finca La Vega",
            productor_id=uuid.uuid4(),
            municipio=self.municipio,
        )

        muni_inactivo, mensaje = inactivar_municipio(self.municipio)
        self.assertFalse(muni_inactivo.activo)
        self.assertIn("2 finca(s) histórica(s)", mensaje)

        self.municipio.refresh_from_db()
        finca1.refresh_from_db()
        finca2.refresh_from_db()

        self.assertFalse(self.municipio.activo)
        self.assertEqual(finca1.municipio, self.municipio)
        self.assertEqual(finca2.municipio, self.municipio)
        self.assertTrue(self.municipio.tiene_fincas_asociadas)

    def test_servicio_reactivar_municipio(self):
        """Reactivar un municipio previamente inactivo cambia activo a True."""
        from fincas.services import reactivar_municipio

        self.municipio.activo = False
        self.municipio.save()

        muni_activo, mensaje = reactivar_municipio(self.municipio)
        self.assertTrue(muni_activo.activo)
        self.assertIn("reactivado exitosamente", mensaje)

    def test_servicio_toggle_estado_municipio(self):
        """Alternar estado invierte de True a False y viceversa."""
        from fincas.services import toggle_estado_municipio

        muni, msg1 = toggle_estado_municipio(self.municipio)
        self.assertFalse(muni.activo)

        muni, msg2 = toggle_estado_municipio(muni)
        self.assertTrue(muni.activo)

    # -------------------------------------------------------------------------
    # 2. Regla de Negocio: Municipios Inactivos No Admiten Nuevas Fincas
    # -------------------------------------------------------------------------

    def test_model_form_bloquea_registro_con_municipio_inactivo(self):
        """FincaModelForm rechaza la creación de una finca en un municipio inactivo."""
        self.municipio.activo = False
        self.municipio.save()

        form = FincaModelForm(data={
            "nombre": "Nueva Finca Inválida",
            "municipio": "Toledo",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("municipio", form.errors)
        self.assertIn("inactivo", form.errors["municipio"][0])

    def test_serializer_bloquea_registro_con_municipio_inactivo(self):
        """FincaGeorreferenciacionSerializer rechaza asociar un municipio inactivo a una finca."""
        from fincas.serializers import FincaGeorreferenciacionSerializer

        self.municipio.activo = False
        self.municipio.save()

        serializer = FincaGeorreferenciacionSerializer(data={
            "nombre": "Finca API Bloqueada",
            "municipio": self.municipio.pk,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("municipio", serializer.errors)
        self.assertIn("inactivo", str(serializer.errors["municipio"]))

    # -------------------------------------------------------------------------
    # 3. Pruebas de la API REST y Control RBAC
    # -------------------------------------------------------------------------

    def test_api_inactivar_sin_autenticacion_retorna_401(self):
        """Petición anónima a /inactivar/ retorna HTTP 401 Unauthorized."""
        response = self.client.post(self.url_inactivar)
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=False)
    def test_api_inactivar_con_rol_no_autorizado_retorna_403(self, _mock_rol):
        """Petición de usuario con rol no autorizado (ej. PRODUCTOR) retorna HTTP 403 Forbidden."""
        user = User.objects.create_user(username="prod_inac", password="Password123!")
        headers = self._auth_headers(user, role_code="PRODUCTOR")

        response = self.client.post(self.url_inactivar, **headers)
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_inactivar_con_rol_autorizado_retorna_200(self, _mock_rol):
        """Petición con rol autorizado (ASOCIACION / ADMIN) inactiva lógicamente el municipio."""
        user = User.objects.create_user(username="asoc_inac", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        response = self.client.post(self.url_inactivar, **headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["activo"])
        self.assertIn("mensaje", data)

        self.municipio.refresh_from_db()
        self.assertFalse(self.municipio.activo)

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_toggle_activo_con_rol_autorizado_retorna_200(self, _mock_rol):
        """Petición a /toggle-activo/ invierte el estado correctamente."""
        user = User.objects.create_user(username="asoc_toggle", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        # Inactiva
        resp1 = self.client.post(self.url_toggle, **headers)
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(resp1.json()["activo"])

        # Reactiva
        resp2 = self.client.post(self.url_toggle, **headers)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["activo"])

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_api_inactivar_inexistente_retorna_404(self, _mock_rol):
        """Petición sobre un ID inexistente retorna HTTP 404 Not Found."""
        user = User.objects.create_user(username="asoc_404", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        url_inexistente = reverse("api_municipio_inactivar", kwargs={"pk": 99999})
        response = self.client.post(url_inexistente, **headers)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


# ==============================================================================
# SUITE HU-09: SCRUM-111 (HU09-ST2) - PANTALLA DE ADMINISTRACIÓN DEL CATÁLOGO
# ==============================================================================

@patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
class TestScrum111PantallaAdminMunicipios(TestCase):
    """
    Pruebas funcionales y de integración para la pantalla de administración del catálogo de municipios (SCRUM-111 / HU09-ST2).
    Cubre:
    - Control de acceso RBAC por sesión (anónimo redirige a login, rol sin permiso recibe 403).
    - Vistas de listado con filtros combinados (búsqueda q, departamento, estado activo/inactivo).
    - Métricas clave en interfaz (total municipios, activos, inactivos, fincas vinculadas).
    - Creación web de municipios con validaciones y feedback vía mensajes flash.
    - Edición web de municipios preservando o actualizando datos.
    - Inactivación y activación lógica web con confirmación y preservación de fincas asociadas.
    """

    def setUp(self):
        Municipio.objects.all().delete()
        self.factory = RequestFactory()
        self.url_admin = reverse("admin_municipios")
        self.url_crear = reverse("crear_municipio_web")

        self.m1 = Municipio.objects.create(
            codigo="54001",
            nombre="Cúcuta",
            departamento="Norte de Santander",
            activo=True,
        )
        self.m2 = Municipio.objects.create(
            codigo="54518",
            nombre="Pamplona",
            departamento="Norte de Santander",
            activo=True,
        )
        self.m3 = Municipio.objects.create(
            codigo="54810",
            nombre="Tibú",
            departamento="Norte de Santander",
            activo=False,
        )
        self.m4 = Municipio.objects.create(
            codigo="68001",
            nombre="Bucaramanga",
            departamento="Santander",
            activo=True,
        )

        # Asociar una finca a Cúcuta para probar métricas y avisos
        self.finca_cucuta = Finca.objects.create(
            nombre="Finca El Paraíso",
            municipio=self.m1,
            productor_id=uuid.uuid4(),
            latitud=Decimal("7.893910"),
            longitud=Decimal("-72.507820"),
        )

    def _crear_request(self, path, method="get", authenticated=True, role="ADMINISTRADOR", data=None):
        if method.lower() == "post":
            request = self.factory.post(path, data=data or {})
        else:
            request = self.factory.get(path)

        request.user = type(
            "UserMock",
            (),
            {
                "is_authenticated": authenticated,
                "username": "admin@cafepergamo.co",
                "first_name": "Administrador",
            },
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    # --------------------------------------------------------------------------
    # 1. Autorización y Acceso RBAC
    # --------------------------------------------------------------------------

    def test_admin_municipios_anonimo_redirige_a_login(self, _mock_tag):
        """Petición anónima es redirigida a la pantalla de login."""
        request = self._crear_request(self.url_admin, authenticated=False)
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_admin_municipios_sin_permiso_retorna_403(self, _mock_permiso, _mock_tag):
        """Usuario autenticado pero sin permiso recibe 403 Forbidden."""
        request = self._crear_request(self.url_admin, authenticated=True, role="COMPRADOR")
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 403)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_admin_municipios_con_permiso_consultar_muestra_catalogo_sin_acciones(self, _mock_perm, _mock_tag):
        """Usuario con permiso de consulta puede ver la pantalla en modo solo lectura."""
        _mock_tag.return_value = False  # Para rbac_tags en el template
        request = self._crear_request(self.url_admin, authenticated=True, role="PRODUCTOR")
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Catálogo Maestro de Municipios")
        self.assertContains(response, "54001")
        self.assertContains(response, "54518")
        # No ve botón de nuevo municipio ni acciones de administración
        self.assertNotContains(response, 'data-bs-target="#modalCrearMunicipio"')

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_admin_municipios_con_permiso_administrar_muestra_acciones_y_metricas(self, _mock_perm, _mock_tag):
        """Usuario con permiso de administración ve métricas, botón crear y botones de acción."""
        _mock_tag.return_value = True
        request = self._crear_request(self.url_admin, authenticated=True, role="ADMINISTRADOR")
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nuevo Municipio')
        self.assertContains(response, 'Total Municipios')
        self.assertContains(response, 'Editar')
        self.assertContains(response, 'Inactivar')

    # --------------------------------------------------------------------------
    # 2. Filtros y Búsqueda
    # --------------------------------------------------------------------------

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_admin_municipios_filtro_busqueda_q(self, _mock_perm, _mock_tag):
        """Búsqueda por texto filtra municipios por nombre o código."""
        request = self._crear_request(f"{self.url_admin}?q=Pamplona")
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "54518")
        self.assertNotContains(response, "54001")
        self.assertNotContains(response, "Bucaramanga")

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_admin_municipios_filtro_por_departamento(self, _mock_perm, _mock_tag):
        """Filtro por departamento muestra solo los pertenecientes a esa región."""
        request = self._crear_request(f"{self.url_admin}?departamento=Santander")
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bucaramanga")
        self.assertNotContains(response, "54001")

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_admin_municipios_filtro_por_estado_inactivos(self, _mock_perm, _mock_tag):
        """Filtro de estado 'inactivos' muestra solo los que tienen activo=False."""
        request = self._crear_request(f"{self.url_admin}?estado=inactivos")
        from fincas.views import admin_municipios_view
        response = admin_municipios_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tibú")
        self.assertNotContains(response, "54001")

    # --------------------------------------------------------------------------
    # 3. Creación Web de Municipios
    # --------------------------------------------------------------------------

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_crear_municipio_web_get_renderiza_formulario(self, _mock_perm, _mock_tag):
        """Petición GET a la vista de creación muestra el formulario."""
        request = self._crear_request(self.url_crear, method="get")
        from fincas.views import crear_municipio_web_view
        response = crear_municipio_web_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registrar Nuevo Municipio")
        self.assertContains(response, "id_nombre")

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_crear_municipio_web_post_valido_persiste_y_redirige(self, _mock_perm, _mock_tag):
        """Petición POST con datos válidos persiste y redirige al listado."""
        datos = {
            "nombre": "Chinácota",
            "departamento": "Norte de Santander",
            "codigo": "54206",
            "activo": True,
        }
        request = self._crear_request(self.url_crear, method="post", data=datos)
        from fincas.views import crear_municipio_web_view
        response = crear_municipio_web_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_admin)

        municipio_creado = Municipio.objects.filter(nombre="Chinácota").first()
        self.assertIsNotNone(municipio_creado)
        self.assertEqual(municipio_creado.codigo, "54206")
        self.assertTrue(municipio_creado.activo)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_crear_municipio_web_post_invalido_duplicado_muestra_error(self, _mock_perm, _mock_tag):
        """Petición POST duplicada en el mismo departamento no persiste y muestra error."""
        datos = {
            "nombre": "cúcuta",  # Duplicado
            "departamento": "Norte de Santander",
            "codigo": "",
            "activo": True,
        }
        request = self._crear_request(self.url_crear, method="post", data=datos)
        from fincas.views import crear_municipio_web_view
        response = crear_municipio_web_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ya existe un municipio")

    # --------------------------------------------------------------------------
    # 4. Edición Web de Municipios
    # --------------------------------------------------------------------------

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_editar_municipio_web_get_muestra_datos(self, _mock_perm, _mock_tag):
        """GET a editar municipio carga los valores actuales del modelo."""
        url_editar = reverse("editar_municipio_web", kwargs={"pk": self.m2.pk})
        request = self._crear_request(url_editar, method="get")
        from fincas.views import editar_municipio_web_view
        response = editar_municipio_web_view(request, pk=self.m2.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pamplona")
        self.assertContains(response, "54518")

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_editar_municipio_web_post_valido_actualiza_y_redirige(self, _mock_perm, _mock_tag):
        """POST válido a edición actualiza el registro y redirige."""
        url_editar = reverse("editar_municipio_web", kwargs={"pk": self.m2.pk})
        datos = {
            "nombre": "Pamplona Ciudad Mitrada",
            "departamento": "Norte de Santander",
            "codigo": "54518",
            "activo": True,
        }
        request = self._crear_request(url_editar, method="post", data=datos)
        from fincas.views import editar_municipio_web_view
        response = editar_municipio_web_view(request, pk=self.m2.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_admin)

        self.m2.refresh_from_db()
        self.assertEqual(self.m2.nombre, "Pamplona Ciudad Mitrada")

    # --------------------------------------------------------------------------
    # 5. Inactivación y Reactivación Web (Alternar Estado)
    # --------------------------------------------------------------------------

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_alternar_estado_municipio_web_inactiva_y_preserva_fincas(self, _mock_perm, _mock_tag):
        """POST a alternar estado inactiva el municipio y preserva fincas asociadas."""
        url_toggle = reverse("alternar_estado_municipio_web", kwargs={"pk": self.m1.pk})
        request = self._crear_request(url_toggle, method="post")
        from fincas.views import alternar_estado_municipio_web_view
        response = alternar_estado_municipio_web_view(request, pk=self.m1.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_admin)

        self.m1.refresh_from_db()
        self.assertFalse(self.m1.activo)

        # La finca sigue intacta asociada a Cúcuta
        self.finca_cucuta.refresh_from_db()
        self.assertEqual(self.finca_cucuta.municipio, self.m1)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_alternar_estado_municipio_web_reactiva(self, _mock_perm, _mock_tag):
        """POST a alternar estado sobre municipio inactivo lo reactiva."""
        url_toggle = reverse("alternar_estado_municipio_web", kwargs={"pk": self.m3.pk})
        request = self._crear_request(url_toggle, method="post")
        from fincas.views import alternar_estado_municipio_web_view
        response = alternar_estado_municipio_web_view(request, pk=self.m3.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_admin)

        self.m3.refresh_from_db()
        self.assertTrue(self.m3.activo)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_alternar_estado_municipio_web_rechaza_get(self, _mock_perm, _mock_tag):
        """GET a alternar estado responde HTTP 405 Method Not Allowed."""
        url_toggle = reverse("alternar_estado_municipio_web", kwargs={"pk": self.m1.pk})
        request = self._crear_request(url_toggle, method="get")
        from fincas.views import alternar_estado_municipio_web_view
        response = alternar_estado_municipio_web_view(request, pk=self.m1.pk)
        self.assertEqual(response.status_code, 405)


# ==============================================================================
# SUITE HU-09: SCRUM-118 (HU09-ST9) - PRUEBAS DE PARAMETRIZACIÓN DE MUNICIPIOS
# ==============================================================================

@patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
class TestScrum118ParametrizacionMunicipiosIntegral(TestCase):
    """
    Suite Integral de Pruebas de Calidad (DoD) para la Historia de Usuario HU-09:
    'Parametrización del catálogo de municipios' (SCRUM-13 / SCRUM-118 / HU09-ST9).

    Valida todos los Criterios de Aceptación de la HU:
    - CA1 (Funcionalidad): Crear, editar e inactivar municipios desde la interfaz sin código.
    - CA2 (Inactivación): Inactivación lógica y preservación histórica de fincas asociadas.
    - CA3 (Precarga): Fixture y comando con los 40 municipios cafeteros de Norte de Santander (DANE).
    - CA4 (Reglas y consistencia): Control de duplicados insensible a mayúsculas y autogeneración de códigos.
    - CA5 (Seguridad RBAC): Matriz de permisos por rol para API y Web.
    """

    def setUp(self):
        Municipio.objects.all().delete()
        self.client = Client()
        self.factory = RequestFactory()

    def _auth_headers(self, user, role_code="ASOCIACION"):
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(user)
        token["role_code"] = role_code
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    # --------------------------------------------------------------------------
    # CA1: Funcionalidad de parametrización de municipios (Servicios y Negocio)
    # --------------------------------------------------------------------------

    def test_ca1_ciclo_completo_parametrizacion_sin_codigo(self, _mock_tag):
        """
        CA1: Valida el ciclo de vida de un municipio nuevo: creación, edición,
        inactivación lógica y reactivación sin alterar código de la aplicación.
        """
        from fincas.services import (
            crear_municipio,
            editar_municipio,
            inactivar_municipio,
            reactivar_municipio,
        )

        # 1. Crear nuevo municipio parametrizable
        municipio = crear_municipio(
            nombre="Gramalote",
            departamento="Norte de Santander",
            codigo="54315",
            activo=True,
        )
        self.assertIsNotNone(municipio.pk)
        self.assertEqual(municipio.nombre, "Gramalote")
        self.assertEqual(municipio.codigo, "54315")
        self.assertTrue(municipio.activo)

        # 2. Editar información del municipio
        municipio_editado = editar_municipio(
            municipio,
            nombre="Nuevo Gramalote",
            codigo="54315-REV",
        )
        self.assertEqual(municipio_editado.nombre, "Nuevo Gramalote")
        self.assertEqual(municipio_editado.codigo, "54315-REV")

        # 3. Inactivación lógica
        municipio_inactivo, msg_inactivo = inactivar_municipio(municipio_editado)
        self.assertFalse(municipio_inactivo.activo)
        self.assertIn("inactivado exitosamente", msg_inactivo)

        # 4. Reactivación
        municipio_activo, msg_activo = reactivar_municipio(municipio_inactivo)
        self.assertTrue(municipio_activo.activo)
        self.assertIn("reactivado exitosamente", msg_activo)

    # --------------------------------------------------------------------------
    # CA2: Inactivación lógica y preservación histórica de fincas asociadas
    # --------------------------------------------------------------------------

    def test_ca2_inactivacion_logica_proteccion_contra_delete_fisico(self, _mock_tag):
        """
        CA2: Un municipio con fincas asociadas NO admite borrado físico (ProtectedError),
        garantizando que la única vía válida sea la inactivación lógica.
        """
        municipio = Municipio.objects.create(
            codigo="54418",
            nombre="Lourdes",
            departamento="Norte de Santander",
            activo=True,
        )

        finca = Finca.objects.create(
            nombre="Finca La Esperanza",
            municipio=municipio,
            productor_id=uuid.uuid4(),
            latitud=Decimal("7.940000"),
            longitud=Decimal("-72.830000"),
        )

        # Intento de borrado físico debe ser bloqueado por django.db.models.PROTECT
        with self.assertRaises(ProtectedError):
            municipio.delete()

        # Debe permanecer en BD
        self.assertTrue(Municipio.objects.filter(pk=municipio.pk).exists())
        self.assertEqual(municipio.total_fincas_asociadas, 1)

    def test_ca2_fincas_historicas_se_preservan_tras_inactivacion_logica(self, _mock_tag):
        """
        CA2: Al inactivar lógicamente un municipio, sus fincas históricas asociadas
        permanecen intactas y consultables en el sistema.
        """
        from fincas.services import inactivar_municipio

        municipio = Municipio.objects.create(
            codigo="54660",
            nombre="Salazar de las Palmas",
            departamento="Norte de Santander",
            activo=True,
        )

        finca1 = Finca.objects.create(
            nombre="Finca Café Real",
            municipio=municipio,
            productor_id=uuid.uuid4(),
        )
        finca2 = Finca.objects.create(
            nombre="Finca El Edén",
            municipio=municipio,
            productor_id=uuid.uuid4(),
        )

        # Inactivar municipio con fincas
        municipio_inactivo, mensaje = inactivar_municipio(municipio)
        self.assertFalse(municipio_inactivo.activo)
        self.assertIn("Se preserva la integridad referencial con 2 finca(s)", mensaje)

        # Las fincas conservan su FK sin alteraciones
        finca1.refresh_from_db()
        finca2.refresh_from_db()
        self.assertEqual(finca1.municipio_id, municipio.id)
        self.assertEqual(finca2.municipio_id, municipio.id)

    # --------------------------------------------------------------------------
    # CA3: Precarga con municipios de Norte de Santander (Fixture y DANE)
    # --------------------------------------------------------------------------

    def test_ca3_precarga_catalogo_40_municipios_dane(self, _mock_tag):
        """
        CA3: El fixture o comando de carga inicial contiene los 40 municipios
        oficiales de Norte de Santander con códigos DANE válidos (prefijo 54xxx).
        """
        call_command("cargar_municipios")

        total_nds = Municipio.objects.filter(departamento="Norte de Santander").count()
        self.assertEqual(total_nds, 40)

        # Verificar presencia de municipios cafeteros icónicos
        municipios_cafeteros_esperados = [
            ("54518", "Pamplona"),
            ("54820", "Toledo"),
            ("54660", "Salazar"),
            ("54051", "Arboledas"),
            ("54206", "Convención"),
            ("54377", "Labateca"),
            ("54385", "La Esperanza"),
            ("54099", "Bochalema"),
            ("54174", "Chitagá"),
            ("54245", "El Carmen"),
            ("54418", "Lourdes"),
        ]

        for codigo, nombre in municipios_cafeteros_esperados:
            m = Municipio.objects.filter(codigo=codigo).first()
            self.assertIsNotNone(m, f"Municipio con código DANE {codigo} ({nombre}) no fue encontrado en la precarga.")
            self.assertIn(nombre.upper(), m.nombre.upper())
            self.assertTrue(m.activo)

    def test_ca3_idempotencia_comando_carga_municipios(self, _mock_tag):
        """
        CA3: La carga inicial es totalmente idempotente; ejecutarla varias veces
        no crea duplicados ni altera la integridad de los 40 municipios.
        """
        # Primera carga
        call_command("cargar_municipios")
        conteo_1 = Municipio.objects.filter(departamento="Norte de Santander").count()
        self.assertEqual(conteo_1, 40)

        # Segunda carga
        call_command("cargar_municipios")
        conteo_2 = Municipio.objects.filter(departamento="Norte de Santander").count()
        self.assertEqual(conteo_2, 40)

        # Tercera carga
        call_command("cargar_municipios")
        conteo_3 = Municipio.objects.filter(departamento="Norte de Santander").count()
        self.assertEqual(conteo_3, 40)

    # --------------------------------------------------------------------------
    # CA4: Reglas de negocio, unicidad insensible y autogeneración de códigos
    # --------------------------------------------------------------------------

    def test_ca4_bloqueo_duplicados_case_insensitive_mismo_departamento(self, _mock_tag):
        """
        CA4: Regla de negocio que bloquea nombres duplicados en el mismo departamento
        independientemente de mayúsculas/minúsculas y espacios.
        """
        from fincas.services import crear_municipio

        crear_municipio(nombre="Mutiscua", departamento="Norte de Santander", codigo="54480")

        # Intento con mayúsculas/minúsculas diferentes
        with self.assertRaises(ValidationError):
            crear_municipio(nombre="  MUTISCUA  ", departamento="Norte de Santander")

        with self.assertRaises(ValidationError):
            crear_municipio(nombre="mutiscua", departamento="norte de santander")

    def test_ca4_permite_mismo_nombre_en_distintos_departamentos(self, _mock_tag):
        """
        CA4: Permite municipios homónimos si pertenecen a departamentos diferentes.
        """
        from fincas.services import crear_municipio

        m_nds = crear_municipio(nombre="San Cayetano", departamento="Norte de Santander", codigo="54673")
        m_cun = crear_municipio(nombre="San Cayetano", departamento="Cundinamarca", codigo="25662")

        self.assertIsNotNone(m_nds.pk)
        self.assertIsNotNone(m_cun.pk)
        self.assertNotEqual(m_nds.departamento, m_cun.departamento)

    def test_ca4_autogeneracion_codigos_sugeridos_y_resolucion_colisiones(self, _mock_tag):
        """
        CA4: Genera códigos únicos sugeridos si no se proporciona código DANE
        y resuelve colisiones añadiendo sufijo correlativo numérico.
        """
        from fincas.services import generar_codigo_municipio_sugerido, crear_municipio

        m1 = crear_municipio(nombre="Herrán", departamento="Norte de Santander")
        self.assertTrue(m1.codigo.startswith("NDS-HERR"))

        # Municipio con nombre y departamento idéntico pero forzado a código sugerido
        codigo_sugerido_colision = generar_codigo_municipio_sugerido("Herrán", "Norte de Santander")
        self.assertTrue(codigo_sugerido_colision.startswith("NDS-HERR"))
        self.assertIn("-", codigo_sugerido_colision)

    # --------------------------------------------------------------------------
    # CA5: Seguridad RBAC Integral (API y Sesión Web)
    # --------------------------------------------------------------------------

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_ca5_rbac_productor_y_comprador_no_pueden_administrar_municipios(self, _mock_perm, _mock_tag):
        """
        CA5: Los roles PRODUCTOR y COMPRADOR tienen denegado el acceso a la
        creación, edición y cambio de estado del catálogo (403 Forbidden).
        """
        from fincas.views import crear_municipio_web_view, alternar_estado_municipio_web_view

        municipio = Municipio.objects.create(codigo="54720", nombre="Sardinata", activo=True)

        # Probar en web (sesión)
        req_crear = self.factory.post(reverse("crear_municipio_web"), data={"nombre": "Nuevo"})
        req_crear.user = type("U", (), {"is_authenticated": True})()
        req_crear.session = {"rol": "PRODUCTOR"}
        req_crear._messages = FallbackStorage(req_crear)

        resp_crear = crear_municipio_web_view(req_crear)
        self.assertEqual(resp_crear.status_code, 403)

        req_toggle = self.factory.post(reverse("alternar_estado_municipio_web", kwargs={"pk": municipio.pk}))
        req_toggle.user = type("U", (), {"is_authenticated": True})()
        req_toggle.session = {"rol": "COMPRADOR"}
        req_toggle._messages = FallbackStorage(req_toggle)

        resp_toggle = alternar_estado_municipio_web_view(req_toggle, pk=municipio.pk)
        self.assertEqual(resp_toggle.status_code, 403)

    @patch("fincas.views.rol_puede_administrar_catalogos", return_value=True)
    def test_ca5_rbac_asociacion_puede_administrar_municipios_por_api(self, _mock_rol, _mock_tag):
        """
        CA5: El rol ASOCIACION cuenta con autorización plena para crear y editar municipios por API REST.
        """
        user = User.objects.create_user(username="asoc_integral", password="Password123!")
        headers = self._auth_headers(user, role_code="ASOCIACION")

        # Crear por API
        data_crear = {
            "nombre": "Cachira",
            "departamento": "Norte de Santander",
            "codigo": "54128",
            "activo": True,
        }
        resp_post = self.client.post(
            reverse("api_municipios_coleccion"),
            data=data_crear,
            content_type="application/json",
            **headers,
        )
        self.assertEqual(resp_post.status_code, 201)
        municipio_id = resp_post.json()["id"]

        # Inactivar por API
        resp_inactivar = self.client.post(
            reverse("api_municipio_inactivar", kwargs={"pk": municipio_id}),
            **headers,
        )
        self.assertEqual(resp_inactivar.status_code, 200)
        self.assertFalse(resp_inactivar.json()["activo"])


# =============================================================================
# SUITE HU-13: MODELO COSECHA-LOTE Y CREACIÓN DE LOTES DE CAFÉ
# (SCRUM-141 / HU13-ST1, SCRUM-142 / HU13-ST2)
# =============================================================================


class CosechaModeloTests(TestCase):
    """
    Pruebas del modelo mínimo Cosecha (HU13-ST1 / SCRUM-141): la
    estructura de persistencia que sirve de base para los lotes, con su
    saldo disponible y la restricción de que nunca puede ser mayor que
    el total cosechado.
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="TEST_COSECHA_MUN", nombre="Chinácota (prueba)")
        self.finca = Finca.objects.create(
            nombre="Finca Las Delicias",
            productor_id=uuid.uuid4(),
            municipio=self.municipio,
        )

    def test_cantidad_disponible_toma_el_total_por_defecto_al_crear(self):
        """Si no se indica `cantidad_disponible` al crear, arranca igual a `cantidad_total`."""
        cosecha = Cosecha.objects.create(
            finca=self.finca,
            fecha_cosecha="2026-03-01",
            cantidad_total=Decimal("500.00"),
        )
        self.assertEqual(cosecha.cantidad_disponible, Decimal("500.00"))

    def test_variedad_es_opcional(self):
        """La variedad de café (catálogo HU10) es opcional en la cosecha mínima."""
        cosecha = Cosecha.objects.create(
            finca=self.finca,
            fecha_cosecha="2026-03-01",
            cantidad_total=Decimal("120.00"),
        )
        self.assertIsNone(cosecha.variedad)

    def test_no_permite_cantidad_disponible_mayor_al_total(self):
        """
        La restricción `cosecha_disponible_no_supera_total` (CheckConstraint)
        rechaza a nivel de base de datos un saldo disponible mayor al total
        cosechado, incluso si algún código intentara forzarlo.
        """
        cosecha = Cosecha(
            finca=self.finca,
            fecha_cosecha="2026-03-01",
            cantidad_total=Decimal("100.00"),
            cantidad_disponible=Decimal("150.00"),
        )
        with self.assertRaises(IntegrityError):
            cosecha.save()

    def test_str_incluye_finca_y_saldo(self):
        cosecha = Cosecha.objects.create(
            finca=self.finca,
            fecha_cosecha="2026-03-01",
            cantidad_total=Decimal("80.00"),
        )
        self.assertIn("Las Delicias", str(cosecha))
        self.assertIn("80.00", str(cosecha))


class CrearLoteServicioTests(TestCase):
    """
    Pruebas del servicio `crear_lote` (HU13-ST2 / SCRUM-142), que aplica
    las tres reglas de negocio pedidas por Jira: código único
    alfanumérico, cantidad del lote no mayor al saldo disponible de la
    cosecha, y descuento transaccional automático de ese saldo.

    También satisface, a nivel de servicio, SCRUM-147 / HU013-ST6
    ("Cubrir con pruebas la creación de lotes, validando el código
    único, la restricción de cantidad y el flujo exitoso de registro"):
    cada una de esas tres cosas tiene su propio test en esta clase.
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="TEST_LOTE_SERV_MUN", nombre="Salazar (prueba)")
        self.finca = Finca.objects.create(
            nombre="Finca El Progreso",
            productor_id=uuid.uuid4(),
            municipio=self.municipio,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            fecha_cosecha="2026-04-10",
            cantidad_total=Decimal("1000.00"),
        )

    def test_crea_lote_con_codigo_explicito_y_descuenta_saldo(self):
        """SCRUM-146 / HU013-ST5: el saldo de la cosecha refleja la cantidad usada por el lote."""
        lote = crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("300.00"), codigo="L0001")
        self.assertEqual(lote.codigo, "L0001")
        self.assertEqual(lote.cantidad, Decimal("300.00"))

        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, Decimal("700.00"))

    def test_genera_codigo_automaticamente_si_no_se_proporciona(self):
        lote = crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("50.00"))
        self.assertTrue(lote.codigo.isalnum())
        self.assertTrue(lote.codigo.startswith(f"LOTE{self.cosecha.pk}"))

    def test_generar_codigo_lote_coincide_con_el_que_usa_crear_lote(self):
        """`generar_codigo_lote` es la misma función que `crear_lote` usa internamente."""
        codigo_esperado = generar_codigo_lote(self.cosecha)
        lote = crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("50.00"))
        self.assertEqual(lote.codigo, codigo_esperado)

    def test_rechaza_codigo_no_alfanumerico(self):
        with self.assertRaises(ValidationError) as ctx:
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("10.00"), codigo="L-0001!!")
        self.assertIn("codigo", ctx.exception.message_dict)

    def test_rechaza_codigo_duplicado(self):
        """
        HU013-ST3 / SCRUM-143: validación de unicidad a nivel de
        APLICACIÓN -- `crear_lote` rechaza el duplicado (incluso con
        distinto uso de mayúsculas/minúsculas) antes de intentar
        persistirlo, con un ValidationError claro en vez de dejar que
        la base de datos reviente con un IntegrityError genérico.
        """
        crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("10.00"), codigo="UNICO123")
        with self.assertRaises(ValidationError) as ctx:
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("10.00"), codigo="unico123")
        self.assertIn("codigo", ctx.exception.message_dict)

    def test_codigo_unico_tambien_se_exige_a_nivel_de_persistencia(self):
        """
        HU013-ST3 / SCRUM-143: validación de unicidad a nivel de
        PERSISTENCIA -- el campo `Lote.codigo` tiene `unique=True` en el
        modelo (y en la migración 0005), así que aunque algún código
        futuro cree un `Lote` directamente por fuera de `crear_lote()`
        (saltándose la validación de aplicación), la base de datos
        sigue rechazando el duplicado exacto.
        """
        Lote.objects.create(codigo="DBUNICO001", cosecha=self.cosecha, cantidad=Decimal("5.00"))
        with self.assertRaises(IntegrityError):
            Lote.objects.create(codigo="DBUNICO001", cosecha=self.cosecha, cantidad=Decimal("5.00"))

    def test_rechaza_cantidad_que_supera_el_saldo_disponible(self):
        """
        SCRUM-145 / HU013-ST4: "Verificar que la cantidad ingresada para el
        lote no supere la cantidad disponible en la cosecha asociada y
        mostrar un error cuando no cumpla la regla."
        """
        with self.assertRaises(ValidationError) as ctx:
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("1500.00"))
        self.assertIn("cantidad", ctx.exception.message_dict)

        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, Decimal("1000.00"))

    def test_rechaza_cantidad_cero_o_negativa(self):
        with self.assertRaises(ValidationError):
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("-5.00"))

    def test_rechaza_cantidad_no_numerica(self):
        with self.assertRaises(ValidationError) as ctx:
            crear_lote(cosecha_id=self.cosecha.pk, cantidad="no-es-un-numero")
        self.assertIn("cantidad", ctx.exception.message_dict)

    def test_rechaza_cosecha_inexistente(self):
        with self.assertRaises(ValidationError) as ctx:
            crear_lote(cosecha_id=999999, cantidad=Decimal("10.00"))
        self.assertIn("cosecha", ctx.exception.message_dict)

    def test_rechaza_cosecha_inactiva(self):
        self.cosecha.activo = False
        self.cosecha.save(update_fields=["activo"])
        with self.assertRaises(ValidationError) as ctx:
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("10.00"))
        self.assertIn("cosecha", ctx.exception.message_dict)

    def test_descuento_es_acumulativo_y_automatico_en_varios_lotes_sucesivos(self):
        """
        SCRUM-146 / HU013-ST5: "Descontar o reflejar la cantidad utilizada
        en la cosecha al crear un lote para mantener la trazabilidad y
        disponibilidad correcta." El descuento se aplica en cada creación,
        así que varios lotes sucesivos contra la misma cosecha siguen
        respetando el saldo restante, nunca el total original.
        """
        crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("400.00"))
        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, Decimal("600.00"))

        crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("600.00"))
        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, Decimal("0.00"))

        # Ya no queda saldo: un tercer lote, aunque sea mínimo, debe rechazarse.
        with self.assertRaises(ValidationError):
            crear_lote(cosecha_id=self.cosecha.pk, cantidad=Decimal("0.01"))


class ApiCrearLoteViewTests(TestCase):
    """
    Pruebas del endpoint `POST /fincas/api/lotes/` (HU13-ST2 / SCRUM-142):
    identificación del productor, aislamiento entre cuentas (una cosecha
    de otro productor nunca es visible) y traducción de las reglas de
    negocio de `crear_lote` a códigos de estado HTTP.

    También satisface, a nivel de API, SCRUM-147 / HU013-ST6: código
    único, restricción de cantidad y flujo exitoso de registro, cada uno
    con su propio test en esta clase.
    """

    def setUp(self):
        self.client = Client()
        self.url_api = reverse("api_lote_crear")
        self.municipio = Municipio.objects.create(codigo="TEST_LOTE_API_MUN", nombre="Herrán (prueba)")

    def _crear_finca_y_cosecha(self, productor_id, cantidad_total="200.00"):
        finca = Finca.objects.create(
            nombre="Finca API Lotes",
            productor_id=productor_id,
            municipio=self.municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-05-01",
            cantidad_total=Decimal(cantidad_total),
        )
        return finca, cosecha

    def test_sin_autenticacion_responde_401(self):
        response = self.client.post(
            self.url_api, {"cosecha": 1, "cantidad": "10.00"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)

    @patch("fincas.views.Usuario")
    def test_falta_cosecha_responde_400(self, mock_usuario_model):
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
        response = self.client.post(
            self.url_api, {"cantidad": "10.00"}, content_type="application/json", **_jwt_bearer_headers()
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cosecha", response.json())

    @patch("fincas.views.Usuario")
    def test_cosecha_inexistente_responde_404(self, mock_usuario_model):
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=uuid.uuid4())
        response = self.client.post(
            self.url_api,
            {"cosecha": 999999, "cantidad": "10.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 404)

    @patch("fincas.views.Usuario")
    def test_cosecha_de_otro_productor_responde_403(self, mock_usuario_model):
        """
        Aislamiento entre cuentas: un productor no puede crear lotes a
        partir de la cosecha de otro productor, aunque conozca su id.
        """
        productor_autenticado = uuid.uuid4()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=productor_autenticado)

        _, cosecha_de_otro = self._crear_finca_y_cosecha(productor_id=uuid.uuid4())

        response = self.client.post(
            self.url_api,
            {"cosecha": cosecha_de_otro.pk, "cantidad": "10.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 403)

    @patch("fincas.views.Usuario")
    def test_cantidad_supera_saldo_responde_400(self, mock_usuario_model):
        """SCRUM-145 / HU013-ST4, a nivel de API: error 400 (no 500) con el detalle del campo "cantidad"."""
        productor_autenticado = uuid.uuid4()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=productor_autenticado)

        _, cosecha = self._crear_finca_y_cosecha(productor_id=productor_autenticado, cantidad_total="50.00")

        response = self.client.post(
            self.url_api,
            {"cosecha": cosecha.pk, "cantidad": "999.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cantidad", response.json())

    @patch("fincas.views.Usuario")
    def test_creacion_exitosa_responde_201_y_descuenta_saldo(self, mock_usuario_model):
        """SCRUM-146 / HU013-ST5, a nivel de API: la respuesta y la BD reflejan el saldo ya descontado."""
        productor_autenticado = uuid.uuid4()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=productor_autenticado)

        finca, cosecha = self._crear_finca_y_cosecha(productor_id=productor_autenticado, cantidad_total="300.00")

        response = self.client.post(
            self.url_api,
            {"cosecha": cosecha.pk, "cantidad": "120.00", "codigo": "APILOTE01"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 201)
        cuerpo = response.json()
        self.assertEqual(cuerpo["codigo"], "APILOTE01")
        self.assertEqual(cuerpo["cantidad"], "120.00")
        self.assertEqual(cuerpo["finca"], finca.nombre)
        self.assertEqual(cuerpo["cantidad_disponible_cosecha"], "180.00")

        cosecha.refresh_from_db()
        self.assertEqual(cosecha.cantidad_disponible, Decimal("180.00"))


class CaracteristicasCalidadApiTests(TestCase):
    """Pruebas CRUD de HU15-ST1 y validaciones de HU15-ST4."""

    def setUp(self):
        municipio = Municipio.objects.create(codigo="TEST_CALIDAD_MUN", nombre="Mutiscua (prueba)")
        finca = Finca.objects.create(
            nombre="Finca Calidad",
            productor_id=uuid.uuid4(),
            municipio=municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-05-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="CALIDAD01",
            cosecha=cosecha,
            cantidad=Decimal("50.00"),
        )
        self.url = reverse("api_lote_calidad", kwargs={"lote_id": self.lote.pk})
        self.client = Client()

    def test_crea_consulta_y_actualiza_caracteristicas(self):
        datos = {
            "humedad": "11.50",
            "merma": "2.00",
            "puntaje_taza": "84.50",
            "perfil_sensorial": "Chocolate y caramelo",
            "observaciones": "Muestra de laboratorio",
        }
        respuesta = self.client.post(
            self.url,
            datos,
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertIn("lote_id", respuesta.json(), respuesta.content)
        self.assertEqual(respuesta.json()["lote_id"], self.lote.pk)
        self.assertEqual(respuesta.json()["puntaje_taza"], "84.50")

        consulta = self.client.get(self.url, **_jwt_bearer_headers())
        self.assertEqual(consulta.status_code, 200)
        self.assertEqual(consulta.json()["lote_codigo"], "CALIDAD01")

        actualizacion = self.client.patch(
            self.url,
            {"puntaje_taza": "86.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(actualizacion.status_code, 200)
        self.assertEqual(actualizacion.json()["puntaje_taza"], "86.00")
        self.assertEqual(CaracteristicasCalidad.objects.get(lote=self.lote).humedad, Decimal("11.50"))

    def test_no_permite_dos_registros_para_el_mismo_lote(self):
        crear_caracteristicas_calidad(lote_o_id=self.lote, humedad=Decimal("10.00"))
        respuesta = self.client.post(
            self.url,
            {"humedad": "12.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("lote", respuesta.json())

    def test_rechaza_puntaje_fuera_de_rango(self):
        respuesta = self.client.post(
            self.url,
            {"puntaje_taza": "101.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("puntaje_taza", respuesta.json())

    def test_rechaza_porcentajes_fisicos_fuera_de_rango(self):
        for campo, valor in (("humedad", "100.01"), ("merma", "-0.01")):
            respuesta = self.client.post(
                self.url,
                {campo: valor},
                content_type="application/json",
                **_jwt_bearer_headers(),
            )
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn(campo, respuesta.json())

    def test_rechaza_formato_decimal_invalido(self):
        respuesta = self.client.post(
            self.url,
            {"humedad": "once coma cinco"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("humedad", respuesta.json())

    def test_acepta_limites_validos_y_normaliza_textos(self):
        respuesta = self.client.post(
            self.url,
            {
                "humedad": "0.00",
                "merma": "100.00",
                "puntaje_taza": "100.00",
                "perfil_sensorial": "  Chocolate  ",
                "observaciones": "  Muestra válida  ",
            },
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()["perfil_sensorial"], "Chocolate")
        self.assertEqual(respuesta.json()["observaciones"], "Muestra válida")

    def test_servicio_actualiza_y_puede_limpiar_un_campo_de_texto(self):
        registro = crear_caracteristicas_calidad(
            lote_o_id=self.lote,
            humedad=Decimal("10.00"),
            observaciones="Inicial",
        )
        editar_caracteristicas_calidad(registro, observaciones="")
        registro.refresh_from_db()
        self.assertEqual(registro.observaciones, "")


# =============================================================================
# SUITE HU-13: FORMULARIOS WEB DE REGISTRO DE COSECHAS Y LOTES
# (SCRUM-144 / "Crear formulario o pantalla de registro de lotes";
#  el registro de cosechas es un complemento necesario, ver nota en
#  fincas/forms.py y fincas/views.py)
# =============================================================================


class RegistrarCosechaViewTests(TestCase):
    """Pruebas de la vista web `registrar_cosecha_view`."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("cosecha_registro")
        self.municipio = Municipio.objects.create(codigo="TEST_COSECHA_VW_MUN", nombre="Toledo (prueba)")

    def test_redirige_a_login_si_no_hay_sesion(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_redirige_a_mis_fincas_si_el_productor_no_tiene_fincas(self):
        _iniciar_sesion_productor(self.client)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("mis_fincas"))

    def test_formulario_solo_ofrece_fincas_del_productor_autenticado(self):
        productor_id = _iniciar_sesion_productor(self.client)
        finca_propia = Finca.objects.create(nombre="Finca Propia", productor_id=productor_id, municipio=self.municipio)
        Finca.objects.create(nombre="Finca Ajena", productor_id=uuid.uuid4(), municipio=self.municipio)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        fincas_en_form = list(response.context["form"].fields["finca"].queryset)
        self.assertEqual(fincas_en_form, [finca_propia])

    def test_post_crea_cosecha_exitosamente_para_finca_propia(self):
        productor_id = _iniciar_sesion_productor(self.client)
        finca = Finca.objects.create(nombre="Finca Cosechera", productor_id=productor_id, municipio=self.municipio)

        response = self.client.post(self.url, {
            "finca": finca.pk,
            "fecha_cosecha": "2026-06-01",
            "cantidad_total": "450.00",
        })
        self.assertEqual(response.status_code, 302)

        cosecha = Cosecha.objects.filter(finca=finca).first()
        self.assertIsNotNone(cosecha)
        self.assertEqual(cosecha.cantidad_total, Decimal("450.00"))
        self.assertEqual(cosecha.cantidad_disponible, Decimal("450.00"))

    def test_no_permite_registrar_cosecha_sobre_finca_ajena(self):
        """
        Aislamiento entre productores: aunque el atacante conozca el id de
        una finca de otro productor y lo mande manualmente en el POST,
        `clean_finca()` la rechaza porque el queryset ya la excluye.
        """
        productor_id = _iniciar_sesion_productor(self.client)
        Finca.objects.create(nombre="Finca Propia", productor_id=productor_id, municipio=self.municipio)
        finca_ajena = Finca.objects.create(nombre="Finca Ajena", productor_id=uuid.uuid4(), municipio=self.municipio)

        response = self.client.post(self.url, {
            "finca": finca_ajena.pk,
            "fecha_cosecha": "2026-06-01",
            "cantidad_total": "100.00",
        })
        self.assertEqual(response.status_code, 200)  # Vuelve a mostrar el formulario con el error
        self.assertFalse(Cosecha.objects.filter(finca=finca_ajena).exists())

    def test_rechaza_cantidad_total_cero_o_negativa(self):
        productor_id = _iniciar_sesion_productor(self.client)
        finca = Finca.objects.create(nombre="Finca X", productor_id=productor_id, municipio=self.municipio)

        response = self.client.post(self.url, {
            "finca": finca.pk,
            "fecha_cosecha": "2026-06-01",
            "cantidad_total": "0",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Cosecha.objects.filter(finca=finca).exists())


class RegistrarLoteViewTests(TestCase):
    """
    Pruebas de la vista web `registrar_lote_view` (SCRUM-144).

    También satisface, a nivel de formulario web, SCRUM-147 / HU013-ST6:
    código único, restricción de cantidad y flujo exitoso de registro,
    cada uno con su propio test en esta clase.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse("lote_registro")
        self.municipio = Municipio.objects.create(codigo="TEST_LOTE_VIEW_MUN", nombre="Herrán (prueba)")
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO", nombre="Lavado", orden=1
        )
        self.estado = EstadoLote.objects.create(
            codigo="RECIBIDO", nombre="Recibido", orden=1
        )

    def _crear_finca_y_cosecha(self, productor_id, cantidad_total="300.00"):
        finca = Finca.objects.create(nombre="Finca con Cosecha", productor_id=productor_id, municipio=self.municipio)
        cosecha = Cosecha.objects.create(
            finca=finca, fecha_cosecha="2026-06-10", cantidad_total=Decimal(cantidad_total)
        )
        return finca, cosecha

    def test_redirige_a_login_si_no_hay_sesion(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_redirige_a_registro_de_cosecha_si_no_hay_cosechas_con_saldo(self):
        productor_id = _iniciar_sesion_productor(self.client)
        Finca.objects.create(nombre="Finca Sin Cosechas", productor_id=productor_id, municipio=self.municipio)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("cosecha_registro"))

    def test_formulario_solo_ofrece_cosechas_propias_con_saldo_disponible(self):
        productor_id = _iniciar_sesion_productor(self.client)
        _, cosecha_propia = self._crear_finca_y_cosecha(productor_id)
        _, cosecha_ajena = self._crear_finca_y_cosecha(uuid.uuid4())

        # Cosecha propia pero sin saldo disponible: tampoco debe aparecer.
        finca_sin_saldo = Finca.objects.create(nombre="Finca Sin Saldo", productor_id=productor_id, municipio=self.municipio)
        cosecha_sin_saldo = Cosecha.objects.create(
            finca=finca_sin_saldo, fecha_cosecha="2026-06-10", cantidad_total=Decimal("50.00")
        )
        cosecha_sin_saldo.cantidad_disponible = Decimal("0.00")
        cosecha_sin_saldo.save(update_fields=["cantidad_disponible"])

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        cosechas_en_form = list(response.context["form"].fields["cosecha"].queryset)
        self.assertEqual(cosechas_en_form, [cosecha_propia])
        self.assertNotIn(cosecha_ajena, cosechas_en_form)
        self.assertNotIn(cosecha_sin_saldo, cosechas_en_form)

    def test_formulario_solo_ofrece_catalogos_activos(self):
        productor_id = _iniciar_sesion_productor(self.client)
        self._crear_finca_y_cosecha(productor_id)
        proceso_inactivo = ProcesoBeneficio.objects.create(
            codigo="SECADO", nombre="Secado", activo=False, orden=2
        )
        estado_inactivo = EstadoLote.objects.create(
            codigo="VENDIDO", nombre="Vendido", activo=False, orden=2
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.proceso, response.context["form"].fields["proceso_beneficio"].queryset)
        self.assertNotIn(
            proceso_inactivo,
            response.context["form"].fields["proceso_beneficio"].queryset,
        )
        self.assertIn(self.estado, response.context["form"].fields["estado_lote"].queryset)
        self.assertNotIn(
            estado_inactivo,
            response.context["form"].fields["estado_lote"].queryset,
        )

    def test_post_rechaza_catalogo_inactivo_manipulado(self):
        productor_id = _iniciar_sesion_productor(self.client)
        _, cosecha = self._crear_finca_y_cosecha(productor_id)
        proceso_inactivo = ProcesoBeneficio.objects.create(
            codigo="SECADO", nombre="Secado", activo=False
        )

        response = self.client.post(self.url, {
            "cosecha": cosecha.pk,
            "proceso_beneficio": proceso_inactivo.pk,
            "estado_lote": self.estado.pk,
            "cantidad": "50.00",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lote.objects.filter(cosecha=cosecha).exists())
        self.assertIn("proceso_beneficio", response.context["form"].errors)

    def test_post_crea_lote_exitosamente_y_descuenta_saldo(self):
        """SCRUM-146 / HU013-ST5, a nivel de formulario web: flujo exitoso de registro con saldo actualizado."""
        productor_id = _iniciar_sesion_productor(self.client)
        _, cosecha = self._crear_finca_y_cosecha(productor_id)

        response = self.client.post(self.url, {
            "cosecha": cosecha.pk,
            "proceso_beneficio": self.proceso.pk,
            "estado_lote": self.estado.pk,
            "codigo": "WEBLOTE01",
            "cantidad": "100.00",
        })
        self.assertEqual(response.status_code, 302)

        lote = Lote.objects.filter(codigo="WEBLOTE01").first()
        self.assertIsNotNone(lote)
        self.assertEqual(lote.cosecha, cosecha)
        self.assertEqual(lote.cantidad, Decimal("100.00"))

        cosecha.refresh_from_db()
        self.assertEqual(cosecha.cantidad_disponible, Decimal("200.00"))

    def test_post_sin_codigo_genera_uno_automaticamente(self):
        productor_id = _iniciar_sesion_productor(self.client)
        _, cosecha = self._crear_finca_y_cosecha(productor_id)

        response = self.client.post(self.url, {
            "cosecha": cosecha.pk,
            "proceso_beneficio": self.proceso.pk,
            "estado_lote": self.estado.pk,
            "cantidad": "50.00",
        })
        self.assertEqual(response.status_code, 302)

        lote = Lote.objects.filter(cosecha=cosecha).first()
        self.assertIsNotNone(lote)
        self.assertTrue(lote.codigo.isalnum())

    def test_cantidad_que_supera_el_saldo_se_muestra_como_error_de_formulario(self):
        """
        SCRUM-145 / HU013-ST4, a nivel de formulario web: el formulario
        reutiliza `crear_lote()`, así que un error de negocio (cantidad >
        saldo) se traduce a un error de campo visible para el usuario, no
        a una excepción sin manejar ni a un error 500.
        """
        productor_id = _iniciar_sesion_productor(self.client)
        _, cosecha = self._crear_finca_y_cosecha(productor_id, cantidad_total="50.00")

        response = self.client.post(self.url, {"cosecha": cosecha.pk, "cantidad": "999.00"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lote.objects.filter(cosecha=cosecha).exists())
        self.assertTrue(response.context["form"].errors)

    def test_codigo_no_alfanumerico_se_rechaza_en_el_formulario(self):
        productor_id = _iniciar_sesion_productor(self.client)
        _, cosecha = self._crear_finca_y_cosecha(productor_id)

        response = self.client.post(self.url, {
            "cosecha": cosecha.pk,
            "codigo": "no valido!!",
            "cantidad": "10.00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lote.objects.filter(cosecha=cosecha).exists())
        self.assertIn("codigo", response.context["form"].errors)


class MisLotesViewTests(TestCase):
    """
    Pruebas de la vista web `mis_lotes_view`.

    Nota: esta vista no corresponde a ninguna subtarea de Jira existente --
    fue pedida directamente por el productor al revisar HU-13 en local
    ("si yo lo registré... me gustaría poder ver los lotes que tengo por
    cada finca"), distinta de HU-14 (etapas de beneficio / historial de
    beneficio), que queda para otro sprint. Aun así se prueba con el mismo
    rigor que el resto de las vistas: redirección sin sesión, aislamiento
    estricto entre productores (incluso al intentar filtrar por una finca
    ajena) y manejo correcto de un filtro inválido.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse("mis_lotes")
        self.municipio = Municipio.objects.create(codigo="TEST_MISLOTES_MUN", nombre="Chinácota (prueba)")

    def _crear_finca_cosecha_lote(self, productor_id, finca_nombre="Finca Propia", cantidad_total="100.00", cantidad_lote="40.00", codigo=None):
        finca = Finca.objects.create(nombre=finca_nombre, productor_id=productor_id, municipio=self.municipio)
        cosecha = Cosecha.objects.create(
            finca=finca, fecha_cosecha="2026-05-01", cantidad_total=Decimal(cantidad_total)
        )
        # crear_lote() ya genera un código automáticamente cuando no se
        # proporciona uno explícito, así que no hace falta llamar aquí a
        # generar_codigo_lote() por separado (esa función exige la instancia
        # de Cosecha como argumento -- ver fincas/services.py).
        lote = crear_lote(cosecha_id=cosecha.pk, cantidad=Decimal(cantidad_lote), codigo=codigo)
        return finca, cosecha, lote

    def test_redirige_a_login_si_no_hay_sesion(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_sin_lotes_muestra_pagina_vacia_sin_error(self):
        _iniciar_sesion_productor(self.client)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["lotes"]), [])

    def test_solo_muestra_los_lotes_del_productor_autenticado(self):
        productor_id = _iniciar_sesion_productor(self.client)
        _, _, lote_propio = self._crear_finca_cosecha_lote(productor_id, finca_nombre="Finca Propia")
        _, _, lote_ajeno = self._crear_finca_cosecha_lote(uuid.uuid4(), finca_nombre="Finca Ajena")

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        lotes_mostrados = list(response.context["lotes"])
        self.assertIn(lote_propio, lotes_mostrados)
        self.assertNotIn(lote_ajeno, lotes_mostrados)

    def test_filtro_por_finca_propia_muestra_solo_sus_lotes(self):
        productor_id = _iniciar_sesion_productor(self.client)
        finca_a, _, lote_a = self._crear_finca_cosecha_lote(productor_id, finca_nombre="Finca A")
        finca_b, _, lote_b = self._crear_finca_cosecha_lote(productor_id, finca_nombre="Finca B")

        response = self.client.get(self.url, {"finca": finca_a.pk})
        self.assertEqual(response.status_code, 200)
        lotes_mostrados = list(response.context["lotes"])
        self.assertIn(lote_a, lotes_mostrados)
        self.assertNotIn(lote_b, lotes_mostrados)
        self.assertEqual(response.context["finca_seleccionada"], finca_a)

    def test_filtro_por_finca_de_otro_productor_no_devuelve_lotes_ajenos(self):
        """
        Aislamiento entre productores incluso ante manipulación del parámetro
        `?finca=<id>`: filtrar por el id de la finca de OTRO productor nunca
        debe devolver los lotes de ese productor, ni lanzar un error -- el
        queryset base ya está restringido a `productor_id`, así que el AND
        de ambos filtros simplemente no devuelve nada.
        """
        productor_id = _iniciar_sesion_productor(self.client)
        self._crear_finca_cosecha_lote(productor_id, finca_nombre="Finca Propia")
        finca_ajena, _, lote_ajeno = self._crear_finca_cosecha_lote(uuid.uuid4(), finca_nombre="Finca Ajena")

        response = self.client.get(self.url, {"finca": finca_ajena.pk})
        self.assertEqual(response.status_code, 200)
        lotes_mostrados = list(response.context["lotes"])
        self.assertNotIn(lote_ajeno, lotes_mostrados)
        self.assertEqual(lotes_mostrados, [])

    def test_filtro_no_numerico_se_ignora_sin_error_y_muestra_advertencia(self):
        productor_id = _iniciar_sesion_productor(self.client)
        _, _, lote_propio = self._crear_finca_cosecha_lote(productor_id)

        response = self.client.get(self.url, {"finca": "no-es-un-id"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(lote_propio, list(response.context["lotes"]))
        mensajes = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("filtro de finca" in m.lower() for m in mensajes))


# ==============================================================================
# HU-12 (SCRUM-16): Registro de Cosechas para controlar la producción de café
# Subtareas:
# - SCRUM-136: Crear el modelo y la persistencia de cosechas
# - SCRUM-137: Desarrollar el servicio o endpoint para registrar cosechas
# - SCRUM-138: Diseñar el formulario de registro de cosechas
# - SCRUM-139: Agregar pruebas del registro de cosechas
# - SCRUM-140: Implementar la validación de finca y variedad contra el catálogo
# Criterios de Aceptación:
# 1. La finca y la variedad deben ser válidas.
# 2. Las cantidades deben ser mayores a cero.
# 3. Se debe inicializar cantidad_disponible = cantidad_total.
# ==============================================================================


class CosechaModelTests(TestCase):
    """
    SCRUM-136 & SCRUM-140: Pruebas unitarias del modelo y persistencia de Cosecha.
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(
            codigo="MUN-COSECHA-TEST",
            nombre="Municipio Cosecha Test",
            departamento="Norte de Santander",
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Esperanza",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo Test",
            activo=True,
        )

    def test_crear_cosecha_inicializa_cantidad_disponible_igual_a_total(self):
        """Criterio: Se debe inicializar cantidad_disponible = cantidad_total."""
        cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-05-10",
            cantidad_total=Decimal("250.50"),
        )
        self.assertEqual(cosecha.cantidad_disponible, Decimal("250.50"))
        self.assertTrue(cosecha.activo)

    def test_cantidad_total_menor_o_igual_a_cero_lanza_validation_error(self):
        """Criterio: Las cantidades deben ser mayores a cero."""
        cosecha_cero = Cosecha(
            finca=self.finca,
            fecha_cosecha="2026-05-10",
            cantidad_total=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            cosecha_cero.clean()
        self.assertIn("cantidad_total", ctx.exception.message_dict)

        cosecha_negativa = Cosecha(
            finca=self.finca,
            fecha_cosecha="2026-05-10",
            cantidad_total=Decimal("-10.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            cosecha_negativa.clean()
        self.assertIn("cantidad_total", ctx.exception.message_dict)

    def test_cantidad_disponible_no_supera_total(self):
        """Restricción: cantidad_disponible <= cantidad_total."""
        cosecha = Cosecha(
            finca=self.finca,
            fecha_cosecha="2026-05-10",
            cantidad_total=Decimal("100.00"),
            cantidad_disponible=Decimal("150.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            cosecha.clean()
        self.assertIn("cantidad_disponible", ctx.exception.message_dict)

    def test_rechaza_cosecha_con_finca_inactiva(self):
        """Criterio SCRUM-140: La finca debe ser válida y estar activa."""
        finca_inactiva = Finca.objects.create(
            nombre="Finca Inactiva Test",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=False,
        )
        cosecha = Cosecha(
            finca=finca_inactiva,
            fecha_cosecha="2026-05-10",
            cantidad_total=Decimal("100.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            cosecha.clean()
        self.assertIn("finca", ctx.exception.message_dict)

    def test_rechaza_cosecha_con_variedad_inactiva(self):
        """Criterio SCRUM-140: La variedad debe ser válida contra el catálogo y estar activa."""
        variedad_inactiva = VariedadCafe.objects.create(
            nombre="Variedad Inactiva Test",
            activo=False,
        )
        cosecha = Cosecha(
            finca=self.finca,
            variedad=variedad_inactiva,
            fecha_cosecha="2026-05-10",
            cantidad_total=Decimal("100.00"),
        )
        with self.assertRaises(ValidationError) as ctx:
            cosecha.clean()
        self.assertIn("variedad", ctx.exception.message_dict)


class CrearCosechaServiceTests(TestCase):
    """
    SCRUM-137 & SCRUM-140: Pruebas unitarias del servicio de dominio `crear_cosecha`.
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(
            codigo="MUN-SERV-TEST",
            nombre="Municipio Servicio Test",
            departamento="Norte de Santander",
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca Buena Vista",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Caturra Test",
            activo=True,
        )

    def test_crear_cosecha_servicio_exitoso(self):
        cosecha = crear_cosecha(
            finca_id=self.finca.pk,
            fecha_cosecha="2026-06-15",
            cantidad_total=Decimal("300.00"),
            variedad_id=self.variedad.pk,
            productor_id=self.productor_id,
        )
        self.assertIsNotNone(cosecha.pk)
        self.assertEqual(cosecha.cantidad_total, Decimal("300.00"))
        self.assertEqual(cosecha.cantidad_disponible, Decimal("300.00"))
        self.assertEqual(cosecha.finca, self.finca)
        self.assertEqual(cosecha.variedad, self.variedad)

    def test_crear_cosecha_servicio_sin_variedad_es_valido(self):
        cosecha = crear_cosecha(
            finca_id=self.finca.pk,
            fecha_cosecha="2026-06-15",
            cantidad_total="150.00",
            variedad_id=None,
            productor_id=self.productor_id,
        )
        self.assertIsNone(cosecha.variedad)
        self.assertEqual(cosecha.cantidad_disponible, Decimal("150.00"))

    def test_crear_cosecha_servicio_con_cantidad_cero_o_negativa_falla(self):
        with self.assertRaises(ValidationError) as ctx:
            crear_cosecha(
                finca_id=self.finca.pk,
                fecha_cosecha="2026-06-15",
                cantidad_total=Decimal("0.00"),
            )
        self.assertIn("cantidad_total", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            crear_cosecha(
                finca_id=self.finca.pk,
                fecha_cosecha="2026-06-15",
                cantidad_total=Decimal("-50.00"),
            )
        self.assertIn("cantidad_total", ctx.exception.message_dict)

    def test_crear_cosecha_servicio_con_finca_inexistente_o_inactiva_falla(self):
        with self.assertRaises(ValidationError) as ctx:
            crear_cosecha(
                finca_id=999999,
                fecha_cosecha="2026-06-15",
                cantidad_total=Decimal("100.00"),
            )
        self.assertIn("finca", ctx.exception.message_dict)

        self.finca.activo = False
        self.finca.save()
        with self.assertRaises(ValidationError) as ctx:
            crear_cosecha(
                finca_id=self.finca.pk,
                fecha_cosecha="2026-06-15",
                cantidad_total=Decimal("100.00"),
            )
        self.assertIn("finca", ctx.exception.message_dict)

    def test_crear_cosecha_servicio_con_finca_ajena_a_productor_falla(self):
        otro_productor = uuid.uuid4()
        with self.assertRaises(ValidationError) as ctx:
            crear_cosecha(
                finca_id=self.finca.pk,
                fecha_cosecha="2026-06-15",
                cantidad_total=Decimal("100.00"),
                productor_id=otro_productor,
            )
        self.assertIn("finca", ctx.exception.message_dict)

    def test_crear_cosecha_servicio_con_variedad_inactiva_falla(self):
        variedad_inactiva = VariedadCafe.objects.create(
            nombre="Geisha Inactiva",
            activo=False,
        )
        with self.assertRaises(ValidationError) as ctx:
            crear_cosecha(
                finca_id=self.finca.pk,
                fecha_cosecha="2026-06-15",
                cantidad_total=Decimal("100.00"),
                variedad_id=variedad_inactiva.pk,
            )
        self.assertIn("variedad", ctx.exception.message_dict)


class CosechaApiTests(TestCase):
    """
    SCRUM-137: Pruebas del endpoint REST POST /fincas/api/cosechas/.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse("api_cosecha_crear")
        self.municipio = Municipio.objects.create(
            codigo="MUN-API-TEST",
            nombre="Municipio API Test",
            departamento="Norte de Santander",
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca API Cafe",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Bourbon Test",
            activo=True,
        )

    def test_api_crear_cosecha_requiere_autenticacion(self):
        response = self.client.post(
            self.url,
            {
                "finca": self.finca.pk,
                "fecha_cosecha": "2026-07-01",
                "cantidad_total": "120.00",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    @patch("fincas.views.Usuario")
    def test_api_crear_cosecha_exitoso(self, mock_usuario_model):
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)
        response = self.client.post(
            self.url,
            {
                "finca": self.finca.pk,
                "variedad": self.variedad.pk,
                "fecha_cosecha": "2026-07-01",
                "cantidad_total": "120.50",
            },
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["finca_id"], self.finca.pk)
        self.assertEqual(data["variedad_id"], self.variedad.pk)
        self.assertEqual(Decimal(str(data["cantidad_total"])), Decimal("120.50"))
        self.assertEqual(Decimal(str(data["cantidad_disponible"])), Decimal("120.50"))

    @patch("fincas.views.Usuario")
    def test_api_crear_cosecha_datos_invalidos_retorna_400(self, mock_usuario_model):
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)
        response = self.client.post(
            self.url,
            {
                "finca": self.finca.pk,
                "fecha_cosecha": "2026-07-01",
                "cantidad_total": "0.00",
            },
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 400)

    @patch("fincas.views.Usuario")
    def test_api_crear_cosecha_finca_inexistente_retorna_404(self, mock_usuario_model):
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)
        response = self.client.post(
            self.url,
            {
                "finca": 999999,
                "fecha_cosecha": "2026-07-01",
                "cantidad_total": "50.00",
            },
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 404)

    @patch("fincas.views.Usuario")
    def test_api_crear_cosecha_finca_ajena_retorna_403(self, mock_usuario_model):
        otro_productor = uuid.uuid4()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=otro_productor)
        response = self.client.post(
            self.url,
            {
                "finca": self.finca.pk,
                "fecha_cosecha": "2026-07-01",
                "cantidad_total": "50.00",
            },
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 403)


class CosechaWebFormViewTests(TestCase):
    """
    SCRUM-138: Pruebas del formulario y vista web de registro de cosechas.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse("cosecha_registro")
        self.municipio = Municipio.objects.create(
            codigo="MUN-WEB-TEST",
            nombre="Municipio Web Test",
            departamento="Norte de Santander",
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Pradera",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Colombia Test",
            activo=True,
        )

    def test_vista_registro_cosecha_requiere_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_vista_registro_cosecha_sin_fincas_redirige_a_mis_fincas(self):
        productor_sin_fincas = uuid.uuid4()
        _iniciar_sesion_productor(self.client, usuario_id=productor_sin_fincas)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("mis_fincas"))

    def test_vista_registro_cosecha_get_renderiza_formulario(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)
        self.assertTemplateUsed(response, "fincas/registro_cosecha.html")

    def test_vista_registro_cosecha_post_exitoso(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.post(
            self.url,
            {
                "finca": self.finca.pk,
                "variedad": self.variedad.pk,
                "fecha_cosecha": "2026-08-01",
                "cantidad_total": "400.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("cosecha_registro"))
        cosecha = Cosecha.objects.filter(finca=self.finca).first()
        self.assertIsNotNone(cosecha)
        self.assertEqual(cosecha.cantidad_total, Decimal("400.00"))
        self.assertEqual(cosecha.cantidad_disponible, Decimal("400.00"))

    def test_vista_registro_cosecha_post_cantidad_invalida_muestra_error(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.post(
            self.url,
            {
                "finca": self.finca.pk,
                "fecha_cosecha": "2026-08-01",
                "cantidad_total": "0.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Cosecha.objects.filter(finca=self.finca).exists())
        self.assertTrue(response.context["form"].errors)

    def test_formulario_rechaza_finca_ajena_y_variedad_inactiva(self):
        finca_ajena = Finca.objects.create(
            nombre="Finca Ajena",
            productor_id=uuid.uuid4(),
            municipio=self.municipio,
            activo=True,
        )
        variedad_inactiva = VariedadCafe.objects.create(
            nombre="Variedad Inactiva",
            activo=False,
        )
        form = CosechaRegistroForm(
            data={
                "finca": finca_ajena.pk,
                "variedad": variedad_inactiva.pk,
                "fecha_cosecha": "2026-08-01",
                "cantidad_total": "100.00",
            },
            productor_id=self.productor_id,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("finca", form.errors)
        self.assertIn("variedad", form.errors)
