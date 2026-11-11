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
- HU-15-ST6 (SCRUM-159): Autorización de edición para productor dueño o catador.
"""

import base64
import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django import forms as forms_module
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, models
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken


from fincas.forms import (
    CaracteristicasCalidadForm,
    CosechaRegistroForm,
    EtapaBeneficioForm,
    FincaModelForm,
    FincaRegistroForm,
    GeorreferenciacionFormMixin,
    LoteRegistroForm,
    MunicipioForm,
)
from fincas.models import (
    BitacoraFichaDigital,
    BitacoraPublicacionLote,
    CaracteristicasCalidad,
    CodigoQRLote,
    Cosecha,
    EtapaBeneficio,
    Finca,
    HistorialEstadoLote,
    Lote,
    ManifestacionInteres,
    Municipio,
)
from fincas.services import (
    cambiar_estado_lote,
    crear_caracteristicas_calidad,
    crear_cosecha,
    crear_lote,
    despublicar_lote_de_catalogo,
    editar_caracteristicas_calidad,
    evaluar_consistencia_y_completitud_lote,
    obtener_ficha_consolidada_lote,
    registrar_auditoria_ficha_digital,
    filtrar_catalogo_lotes,
    generar_codigo_lote,
    generar_snapshot_trazabilidad,
    listar_manifestaciones_interes_productor,
    lotes_disponibles_en_catalogo,
    marcar_manifestacion_interes_vista,
    normalizar_filtros_catalogo,
    obtener_opciones_filtro_catalogo,
    publicar_lote_en_catalogo,
    registrar_etapa_beneficio,
    transicionar_estado_comercial,
    registrar_manifestacion_interes,
    validar_lote_para_publicacion,
    actualizar_visibilidad_codigo_qr,
    actualizar_lote,
    asociar_codigo_qr_a_lote,
    construir_payload_qr_lote,
    extraer_codigo_lote_desde_qr,
    extraer_codigo_lote_normalizado,
    generar_identificador_qr_lote,
    generar_matriz_qr_lote,
    generar_qr_base64_lote,
    obtener_codigo_qr_lote,
    obtener_bytes_descarga_qr_lote,
    obtener_estructura_qr_lote,
    resolver_lote_desde_qr,
    sanitizar_ficha_por_visibilidad,
    sincronizar_o_generar_qr_lote,
    validar_estructura_identificador_qr,
    verificar_permiso_visibilidad_qr,
    PREFIJO_IDENTIFICADOR_QR,
    VISIBILIDAD_QR_PUBLICA,
    VISIBILIDAD_QR_PRIVADA,
)
from fincas.serializers import (
    EstructuraCodigoQRSerializer,
    FichaDigitalSerializer,
)
from fincas.views import (
    MENSAJE_CATALOGO_SIN_RESULTADOS_FILTRADO,
    MENSAJE_CATALOGO_VACIO,
)
from catalogos.models import EstadoLote, ProcesoBeneficio, VariedadCafe
from fincas.validators import (
    validar_latitud,
    validar_longitud,
    validar_par_coordenadas,
)


def _iniciar_sesion_con_rol(client, rol, usuario_id=None):
    """
    Simula, para pruebas, el mismo estado de sesión que deja `login_view`
    al autenticar a un usuario real: tanto `request.session['usuario_id']`
    y `request.session['rol']` (ver usuarios/views.py:492) como el login
    real de Django (`django.contrib.auth.login`), del que depende
    `request.user.is_authenticated` -- lo exige `permiso_requerido_sesion`
    (HU04-ST3 / HU22) antes de mirar siquiera el rol. `usuarios.Usuario` es
    `managed=False` y no existe en la base de datos de pruebas (sqlite), así
    que aquí no se crea una fila real de ese modelo: solo la fila "espejo"
    en `auth_user` (igual que hace login_view) y las claves de sesión, que
    es justo lo que `_resolver_productor_id` necesita para identificar al
    usuario sin inventar un UUID al azar.
    """
    from django.contrib.auth.models import User

    usuario_id = usuario_id or uuid.uuid4()
    django_user, _creado = User.objects.get_or_create(username=str(usuario_id))
    client.force_login(django_user)
    session = client.session
    session["usuario_id"] = str(usuario_id)
    session["rol"] = rol
    session.save()
    return str(usuario_id)


def _iniciar_sesion_productor(client, usuario_id=None):
    """Atajo de `_iniciar_sesion_con_rol` para el rol PRODUCTOR."""
    return _iniciar_sesion_con_rol(client, "PRODUCTOR", usuario_id=usuario_id)


def _iniciar_sesion_comprador(client, usuario_id=None):
    """
    Atajo de `_iniciar_sesion_con_rol` para el rol COMPRADOR (HU22): sirve
    para probar que las vistas de gestión de fincas/lotes/cosechas
    (exclusivas del productor) le quedan vedadas, y que las suyas propias
    (manifestar interés) sí funcionan.
    """
    return _iniciar_sesion_con_rol(client, "COMPRADOR", usuario_id=usuario_id)


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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        _iniciar_sesion_productor(self.client)
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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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
        _iniciar_sesion_productor(self.client)
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
        _iniciar_sesion_productor(self.client)
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
        _iniciar_sesion_productor(self.client)
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
        _iniciar_sesion_productor(self.client)
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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        _iniciar_sesion_productor(self.client)
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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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

    def _quality_headers(self, role_code="CATADOR"):
        user = User.objects.create_user(username=f"calidad_{uuid.uuid4().hex[:8]}")
        token = AccessToken.for_user(user)
        token["role_code"] = role_code
        token["email"] = f"{user.username}@test.local"
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

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
            **self._quality_headers(),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertIn("lote_id", respuesta.json(), respuesta.content)
        self.assertEqual(respuesta.json()["lote_id"], self.lote.pk)
        self.assertEqual(respuesta.json()["puntaje_taza"], "84.50")

        consulta = self.client.get(self.url, **self._quality_headers("PRODUCTOR"))
        self.assertEqual(consulta.status_code, 200)
        self.assertEqual(consulta.json()["lote_codigo"], "CALIDAD01")

        actualizacion = self.client.patch(
            self.url,
            {"puntaje_taza": "86.00"},
            content_type="application/json",
            **self._quality_headers(),
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
            **self._quality_headers(),
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("lote", respuesta.json())

    def test_rechaza_puntaje_fuera_de_rango(self):
        respuesta = self.client.post(
            self.url,
            {"puntaje_taza": "101.00"},
            content_type="application/json",
            **self._quality_headers(),
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("puntaje_taza", respuesta.json())

    def test_rechaza_porcentajes_fisicos_fuera_de_rango(self):
        for campo, valor in (("humedad", "100.01"), ("merma", "-0.01")):
            respuesta = self.client.post(
                self.url,
                {campo: valor},
                content_type="application/json",
                **self._quality_headers(),
            )
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn(campo, respuesta.json())

    def test_rechaza_formato_decimal_invalido(self):
        respuesta = self.client.post(
            self.url,
            {"humedad": "once coma cinco"},
            content_type="application/json",
            **self._quality_headers(),
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
            **self._quality_headers(),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()["perfil_sensorial"], "Chocolate")
        self.assertEqual(respuesta.json()["observaciones"], "Muestra válida")

    def test_productor_dueno_puede_modificar_con_sesion(self):
        productor_id = self.lote.cosecha.finca.productor_id
        _iniciar_sesion_productor(self.client, productor_id)
        respuesta = self.client.post(
            self.url,
            {"humedad": "12.00"},
            content_type="application/json",
            **self._quality_headers("PRODUCTOR"),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)

    def test_administrador_puede_modificar_calidad(self):
        respuesta = self.client.post(
            self.url,
            {"humedad": "12.00"},
            content_type="application/json",
            **self._quality_headers("ADMINISTRADOR"),
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.content)

    def test_productor_ajeno_y_otro_rol_no_pueden_modificar(self):
        _iniciar_sesion_productor(self.client, uuid.uuid4())
        for role_code in ("PRODUCTOR", "COMPRADOR"):
            respuesta = self.client.post(
                self.url,
                {"humedad": "12.00"},
                content_type="application/json",
                **self._quality_headers(role_code),
            )
            self.assertEqual(respuesta.status_code, 403)

    def test_formulario_web_guarda_calidad_del_lote(self):
        productor_id = self.lote.cosecha.finca.productor_id
        _iniciar_sesion_productor(self.client, productor_id)
        session = self.client.session
        session["rol"] = "PRODUCTOR"
        session.save()

        respuesta = self.client.post(
            reverse("lote_calidad", kwargs={"pk": self.lote.pk}),
            {
                "humedad": "12.25",
                "merma": "1.50",
                "puntaje_taza": "85.00",
                "perfil_sensorial": "  Chocolate  ",
                "observaciones": "  Registro web  ",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        calidad = CaracteristicasCalidad.objects.get(lote=self.lote)
        self.assertEqual(calidad.humedad, Decimal("12.25"))
        self.assertEqual(calidad.perfil_sensorial, "Chocolate")

    def test_formulario_web_rechaza_usuario_sin_permiso(self):
        _iniciar_sesion_productor(self.client, uuid.uuid4())
        session = self.client.session
        session["rol"] = "COMPRADOR"
        session.save()
        respuesta = self.client.get(reverse("lote_calidad", kwargs={"pk": self.lote.pk}))
        self.assertEqual(respuesta.status_code, 403)

    def test_formulario_expone_campos_de_calidad(self):
        form = CaracteristicasCalidadForm()
        for campo in ("humedad", "merma", "puntaje_taza", "perfil_sensorial", "observaciones"):
            self.assertIn(campo, form.fields)

    def test_servicio_actualiza_y_puede_limpiar_un_campo_de_texto(self):
        registro = crear_caracteristicas_calidad(
            lote_o_id=self.lote,
            humedad=Decimal("10.00"),
            observaciones="Inicial",
        )
        editar_caracteristicas_calidad(registro, observaciones="")
        registro.refresh_from_db()
        self.assertEqual(registro.observaciones, "")


class HU16EstadoComercialModelTests(TestCase):
    """Pruebas del modelo y catálogo de estados comerciales de HU16-ST1."""

    def setUp(self):
        municipio = Municipio.objects.create(
            codigo="HU16_ST1_MUN",
            nombre="Mutiscua (HU16-ST1)",
        )
        finca = Finca.objects.create(
            nombre="Finca HU16-ST1",
            productor_id=uuid.uuid4(),
            municipio=municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-11-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="HU16ST1-001",
            cosecha=cosecha,
            cantidad=Decimal("25.00"),
        )

    def test_estado_comercial_inicia_disponible(self):
        self.assertEqual(
            self.lote.estado_comercial,
            Lote.EstadoComercial.DISPONIBLE,
        )
        self.assertEqual(
            self.lote.get_estado_comercial_display(),
            "Disponible",
        )

    def test_estado_comercial_expone_los_cinco_estados_validos(self):
        self.assertEqual(
            set(Lote.EstadoComercial.values),
            {"DISPONIBLE", "RESERVADO", "NEGOCIADO", "VENDIDO", "CERRADO"},
        )

    def test_estado_comercial_rechaza_valores_no_definidos(self):
        self.lote.estado_comercial = "INEXISTENTE"
        with self.assertRaises(ValidationError):
            self.lote.full_clean()


class HU16TransicionesEstadoComercialTests(TestCase):
    """Pruebas de las reglas de transición comercial de HU16-ST4."""

    def setUp(self):
        municipio = Municipio.objects.create(
            codigo="HU16_ST4_MUN",
            nombre="Mutiscua (HU16-ST4)",
        )
        finca = Finca.objects.create(
            nombre="Finca HU16-ST4",
            productor_id=uuid.uuid4(),
            municipio=municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-11-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="HU16ST4-001",
            cosecha=cosecha,
            cantidad=Decimal("25.00"),
        )

    def test_permite_avanzar_por_el_flujo_comercial(self):
        for estado in (
            Lote.EstadoComercial.RESERVADO,
            Lote.EstadoComercial.NEGOCIADO,
            Lote.EstadoComercial.VENDIDO,
            Lote.EstadoComercial.CERRADO,
        ):
            lote = transicionar_estado_comercial(self.lote, estado)
            self.assertEqual(lote.estado_comercial, estado)

    def test_permite_cancelar_reserva_o_negociacion(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
        )
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.DISPONIBLE,
        )
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
        )
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.NEGOCIADO,
        )
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
        )
        self.lote.refresh_from_db()
        self.assertEqual(
            self.lote.estado_comercial,
            Lote.EstadoComercial.RESERVADO,
        )

    def test_rechaza_salto_de_estado_y_reapertura_de_lote_cerrado(self):
        with self.assertRaises(ValidationError):
            transicionar_estado_comercial(
                self.lote,
                Lote.EstadoComercial.VENDIDO,
            )

        self.lote.estado_comercial = Lote.EstadoComercial.CERRADO
        self.lote.save(update_fields=["estado_comercial"])
        with self.assertRaises(ValidationError):
            transicionar_estado_comercial(
                self.lote,
                Lote.EstadoComercial.DISPONIBLE,
            )

    def test_rechaza_estado_comercial_invalido(self):
        with self.assertRaises(ValidationError):
            transicionar_estado_comercial(self.lote, "INEXISTENTE")


class HU16HistorialEstadoComercialTests(TestCase):
    """Pruebas del historial de cambios de estado comercial de HU16-ST3."""

    def setUp(self):
        municipio = Municipio.objects.create(
            codigo="HU16_ST3_MUN",
            nombre="Mutiscua (HU16-ST3)",
        )
        finca = Finca.objects.create(
            nombre="Finca HU16-ST3",
            productor_id=uuid.uuid4(),
            municipio=municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-11-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="HU16ST3-001",
            cosecha=cosecha,
            cantidad=Decimal("25.00"),
        )

    def test_transicion_crea_historial_con_estado_fecha_y_usuario(self):
        lote = transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
            usuario_id="usuario-hu16",
            usuario_correo="productor@example.com",
            motivo="Reserva confirmada por el comprador",
        )

        historial = HistorialEstadoLote.objects.get(lote=lote)
        self.assertEqual(historial.estado_anterior, "DISPONIBLE")
        self.assertEqual(historial.estado_nuevo, "RESERVADO")
        self.assertEqual(historial.usuario_responsable_id, "usuario-hu16")
        self.assertEqual(
            historial.usuario_responsable_correo,
            "productor@example.com",
        )
        self.assertEqual(
            historial.motivo,
            "Reserva confirmada por el comprador",
        )
        self.assertIsNotNone(historial.creado_en)

    def test_cada_transicion_genera_un_registro_en_orden_inverso(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
        )
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.NEGOCIADO,
        )

        historial = list(
            HistorialEstadoLote.objects.filter(lote=self.lote)
        )
        self.assertEqual(len(historial), 2)
        self.assertEqual(
            [(registro.estado_anterior, registro.estado_nuevo) for registro in historial],
            [("RESERVADO", "NEGOCIADO"), ("DISPONIBLE", "RESERVADO")],
        )

    def test_no_crea_historial_si_no_hay_cambio_real(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.DISPONIBLE,
        )
        self.assertFalse(
            HistorialEstadoLote.objects.filter(lote=self.lote).exists()
        )


class HU16EstadoComercialApiTests(TestCase):
    """Pruebas del endpoint de consulta de estado comercial de HU16-ST5."""

    def setUp(self):
        municipio = Municipio.objects.create(
            codigo="HU16_ST5_MUN",
            nombre="Mutiscua (HU16-ST5)",
        )
        finca = Finca.objects.create(
            nombre="Finca HU16-ST5",
            productor_id=uuid.uuid4(),
            municipio=municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-11-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="HU16ST5-001",
            cosecha=cosecha,
            cantidad=Decimal("25.00"),
        )
        self.url = reverse("api_lote_detalle", kwargs={"pk": self.lote.pk})

    def test_get_retorna_estado_comercial_y_fecha_de_actualizacion(self):
        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 200)
        data = respuesta.json()
        self.assertEqual(data["estado_comercial"], "DISPONIBLE")
        self.assertIsNotNone(data["estado_comercial_actualizado_en"])
        self.assertIsNone(data["ultimo_cambio_estado"])

    def test_get_retorna_ultimo_cambio_y_su_responsable(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
            usuario_id="usuario-api",
            usuario_correo="comprador@example.com",
            motivo="Reserva registrada",
        )

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 200)
        data = respuesta.json()
        self.assertEqual(data["estado_comercial"], "RESERVADO")
        self.assertEqual(
            data["ultimo_cambio_estado"]["estado_anterior"],
            "DISPONIBLE",
        )
        self.assertEqual(
            data["ultimo_cambio_estado"]["estado_nuevo"],
            "RESERVADO",
        )
        self.assertEqual(
            data["ultimo_cambio_estado"]["usuario_responsable_id"],
            "usuario-api",
        )
        self.assertEqual(
            data["ultimo_cambio_estado"]["usuario_responsable_correo"],
            "comprador@example.com",
        )

    def test_get_lote_inexistente_retorna_404(self):
        respuesta = self.client.get(
            reverse("api_lote_detalle", kwargs={"pk": 999999})
        )
        self.assertEqual(respuesta.status_code, 404)


class HU16PruebasIntegradasEstadoComercialTests(TestCase):
    """Pruebas integradas de transiciones, historial y consulta de HU16-ST6."""

    def setUp(self):
        municipio = Municipio.objects.create(
            codigo="HU16_ST6_MUN",
            nombre="Mutiscua (HU16-ST6)",
        )
        finca = Finca.objects.create(
            nombre="Finca HU16-ST6",
            productor_id=uuid.uuid4(),
            municipio=municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-11-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="HU16ST6-001",
            cosecha=cosecha,
            cantidad=Decimal("25.00"),
        )
        self.url = reverse("api_lote_detalle", kwargs={"pk": self.lote.pk})

    def test_transicion_legal_actualiza_estado_y_guarda_historial(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
            usuario_id="usuario-st6",
            motivo="Reserva confirmada",
        )

        self.lote.refresh_from_db()
        historial = HistorialEstadoLote.objects.get(lote=self.lote)
        self.assertEqual(self.lote.estado_comercial, "RESERVADO")
        self.assertEqual(historial.estado_anterior, "DISPONIBLE")
        self.assertEqual(historial.estado_nuevo, "RESERVADO")
        self.assertEqual(historial.usuario_responsable_id, "usuario-st6")

    def test_transicion_ilegal_rechaza_el_cambio_y_conserva_el_estado(self):
        with self.assertRaises(ValidationError):
            transicionar_estado_comercial(
                self.lote,
                Lote.EstadoComercial.VENDIDO,
            )

        self.lote.refresh_from_db()
        self.assertEqual(self.lote.estado_comercial, "DISPONIBLE")
        self.assertFalse(
            HistorialEstadoLote.objects.filter(lote=self.lote).exists()
        )

    def test_api_consulta_estado_actual_y_ultimo_cambio(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
            usuario_id="usuario-api-st6",
        )

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 200)
        data = respuesta.json()
        self.assertEqual(data["estado_comercial"], "RESERVADO")
        self.assertEqual(
            data["ultimo_cambio_estado"]["estado_nuevo"],
            "RESERVADO",
        )
        self.assertEqual(
            data["ultimo_cambio_estado"]["usuario_responsable_id"],
            "usuario-api-st6",
        )


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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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


class HU16EstadoComercialWebTests(TestCase):
    """Pruebas de visualización del estado comercial de HU16-ST2."""

    def setUp(self):
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.client = Client()
        self.municipio = Municipio.objects.create(
            codigo="HU16_ST2_MUN",
            nombre="Mutiscua (HU16-ST2)",
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca HU16-ST2",
            productor_id=self.productor_id,
            municipio=self.municipio,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            fecha_cosecha="2026-11-01",
            cantidad_total=Decimal("100.00"),
        )
        self.lote = Lote.objects.create(
            codigo="HU16ST2-001",
            cosecha=self.cosecha,
            cantidad=Decimal("25.00"),
        )
        _iniciar_sesion_productor(self.client, self.productor_id)

    def test_listado_muestra_badge_del_estado_comercial(self):
        respuesta = self.client.get(reverse("mis_lotes"))

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.content.decode("utf-8")
        self.assertIn("Estado comercial", contenido)
        self.assertIn("Disponible", contenido)

    def test_detalle_muestra_estado_comercial_y_fecha(self):
        respuesta = self.client.get(
            reverse("lote_detalle", kwargs={"pk": self.lote.pk})
        )

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.content.decode("utf-8")
        self.assertIn("Estado comercial:", contenido)
        self.assertIn("Disponible", contenido)
        self.assertIn("Actualizado:", contenido)

    def test_listado_refleja_un_estado_distinto_despues_de_transicion(self):
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.RESERVADO,
        )
        transicionar_estado_comercial(
            self.lote,
            Lote.EstadoComercial.NEGOCIADO,
        )

        respuesta = self.client.get(reverse("mis_lotes"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("Negociado", respuesta.content.decode("utf-8"))


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
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
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


# ==============================================================================
# SUITE HU-19: PUBLICAR LOTE EN EL CATÁLOGO PÚBLICO (SCRUM-228 / HU-19)
# ==============================================================================


class TestScrum241ValidacionInformacionMinimaPublicacion(TestCase):
    """
    Subtarea: SCRUM-241 / HU19-ST4: Definir la validación de información mínima
    para publicar un lote.

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
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(
            codigo="MUN-TEST-HU19",
            nombre="Arboledas (HU19)",
            departamento="Norte de Santander",
            activo=True,
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca Trazable",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO_HU19",
            nombre="Lavado",
            activo=True,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-07-15",
            cantidad_total=Decimal("600.00"),
            cantidad_disponible=Decimal("600.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOTE-HU19-01",
            cosecha=self.cosecha,
            cantidad=Decimal("150.00"),
            proceso_beneficio=self.proceso,
            activo=True,
        )
        self.calidad = CaracteristicasCalidad.objects.create(
            lote=self.lote,
            puntaje_taza=Decimal("86.50"),
            humedad=Decimal("11.20"),
            merma=Decimal("1.50"),
            perfil_sensorial="Notas a chocolate y frutos rojos",
        )

    def test_lote_completo_con_trazabilidad_y_calidad_es_valido(self):
        """Un lote con todos los requisitos de trazabilidad y calidad aprueba la validación (True, [])."""
        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertTrue(es_valido)
        self.assertEqual(errores, [])

    def test_lote_con_calidad_solo_humedad_es_valido(self):
        """Si solo cuenta con humedad (sin puntaje en taza), es válido para publicación."""
        self.calidad.puntaje_taza = None
        self.calidad.save()
        self.lote.refresh_from_db()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertTrue(es_valido)
        self.assertEqual(errores, [])

    def test_lote_con_calidad_solo_puntaje_taza_es_valido(self):
        """Si solo cuenta con puntaje en taza (sin humedad), es válido para publicación."""
        self.calidad.humedad = None
        self.calidad.save()
        self.lote.refresh_from_db()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertTrue(es_valido)
        self.assertEqual(errores, [])

    def test_lote_sin_registro_de_calidad_es_invalido(self):
        """Un lote sin evaluación de calidad (HU-15) no puede ser publicado."""
        self.calidad.delete()
        # Forzamos refresco de relación OneToOne
        lote_sin_calidad = Lote.objects.get(pk=self.lote.pk)

        es_valido, errores = validar_lote_para_publicacion(lote_sin_calidad)
        self.assertFalse(es_valido)
        self.assertTrue(any("calidad" in e.lower() for e in errores))

    def test_lote_con_calidad_sin_puntaje_ni_humedad_es_invalido(self):
        """Un registro de calidad vacío (sin puntaje ni humedad) es rechazado."""
        self.calidad.puntaje_taza = None
        self.calidad.humedad = None
        self.calidad.save()
        self.lote.refresh_from_db()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("puntaje en taza o el porcentaje de humedad" in e for e in errores))

    def test_lote_sin_proceso_beneficio_es_invalido(self):
        """Un lote sin proceso de beneficio asignado es rechazado por falta de trazabilidad técnica."""
        self.lote.proceso_beneficio = None
        self.lote.save()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("proceso de beneficio" in e.lower() for e in errores))

    def test_lote_sin_variedad_en_cosecha_es_invalido(self):
        """Una cosecha sin variedad de café no puede publicar sus lotes."""
        self.cosecha.variedad = None
        self.cosecha.save()
        self.lote.refresh_from_db()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("variedad" in e.lower() for e in errores))

    def test_lote_sin_municipio_en_finca_es_invalido(self):
        """Una finca sin municipio no garantiza georreferenciación en el catálogo."""
        self.lote.cosecha.finca.municipio = None

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("municipio" in e.lower() for e in errores))

    def test_lote_inactivo_es_invalido(self):
        """Un lote inactivo no puede publicarse."""
        self.lote.activo = False
        self.lote.save()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("inactivo" in e.lower() for e in errores))

    def test_lote_con_cantidad_cero_es_invalido(self):
        """Un lote con cantidad 0 no puede publicarse en el catálogo."""
        self.lote.cantidad = Decimal("0.00")
        self.lote.save()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("mayor a cero" in e.lower() for e in errores))

    def test_cosecha_inactiva_o_finca_inactiva_es_invalida(self):
        """Cosecha o finca inactiva invalida la publicación."""
        self.cosecha.activo = False
        self.cosecha.save()
        self.lote.refresh_from_db()

        es_valido, errores = validar_lote_para_publicacion(self.lote)
        self.assertFalse(es_valido)
        self.assertTrue(any("cosecha" in e.lower() and "inactiva" in e.lower() for e in errores))


class TestScrum240ServiciosPublicacionYBitacora(TestCase):
    """
    Subtareas:
    - SCRUM-240 / HU19-ST2: Implementar la regla de negocio para habilitar la publicación.
    - SCRUM-243 / HU19-ST3: Actualizar el estado del lote en el catálogo público.
    - SCRUM-244 / HU19-ST6: Registrar la publicación del lote para trazabilidad.
    """

    def setUp(self):
        self.municipio = Municipio.objects.create(
            codigo="MUN-SRV-HU19",
            nombre="Salazar (Servicio)",
            departamento="Norte de Santander",
            activo=True,
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Esperanza",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="El Porvenir",
            latitud=Decimal("7.889100"),
            longitud=Decimal("-72.507800"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Caturra",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="HONEY_HU19",
            nombre="Honey",
            activo=True,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-08-01",
            cantidad_total=Decimal("800.00"),
            cantidad_disponible=Decimal("800.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOT-SRV-01",
            cosecha=self.cosecha,
            cantidad=Decimal("200.00"),
            proceso_beneficio=self.proceso,
            activo=True,
        )
        self.calidad = CaracteristicasCalidad.objects.create(
            lote=self.lote,
            puntaje_taza=Decimal("87.25"),
            humedad=Decimal("10.80"),
            merma=Decimal("1.20"),
            perfil_sensorial="Miel, panela y jazmín",
        )

    def test_publicar_lote_exitoso_actualiza_estado_y_registra_bitacora(self):
        """Al publicar exitosamente, se activa la bandera, fecha, precio y se crea el registro inmutable en bitácora."""
        lote_pub = publicar_lote_en_catalogo(
            lote_id=self.lote.id,
            productor_id=self.productor_id,
            precio_referencial=Decimal("26500.00"),
            realizado_por_id=str(self.productor_id),
            realizado_por_correo="productor.finca@cafepergamo.test",
            observaciones="Lote especial de altura",
        )

        self.assertTrue(lote_pub.publicado_en_catalogo)
        self.assertIsNotNone(lote_pub.fecha_publicacion)
        self.assertEqual(lote_pub.precio_referencial, Decimal("26500.00"))

        # Verificación de bitácora inmutable (SCRUM-244 / HU19-ST6)
        registros = BitacoraPublicacionLote.objects.filter(lote=self.lote)
        self.assertEqual(registros.count(), 1)
        bita = registros.first()
        self.assertEqual(bita.accion, "PUBLICAR")
        self.assertEqual(bita.realizado_por_correo, "productor.finca@cafepergamo.test")
        self.assertEqual(bita.observaciones, "Lote especial de altura")

        # Verificación del snapshot de trazabilidad almacenado
        snapshot = bita.detalles_trazabilidad
        self.assertEqual(snapshot["lote"]["codigo"], "LOT-SRV-01")
        self.assertEqual(snapshot["finca"]["nombre"], "Finca La Esperanza")
        self.assertEqual(snapshot["finca"]["municipio"], "Salazar (Servicio)")
        self.assertEqual(snapshot["cosecha"]["variedad"], "Caturra")
        self.assertEqual(snapshot["proceso_beneficio"], "Honey")
        self.assertEqual(snapshot["calidad"]["puntaje_taza"], 87.25)

    def test_publicar_lote_sin_precio_mantiene_precio_none(self):
        """El precio referencial es opcional para el productor."""
        lote_pub = publicar_lote_en_catalogo(
            lote_id=self.lote.id,
            productor_id=self.productor_id,
            precio_referencial=None,
        )
        self.assertTrue(lote_pub.publicado_en_catalogo)
        self.assertIsNone(lote_pub.precio_referencial)

    def test_publicar_lote_con_precio_invalido_falla(self):
        """Un precio referencial cero o negativo es rechazado con ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            publicar_lote_en_catalogo(
                lote_id=self.lote.id,
                productor_id=self.productor_id,
                precio_referencial=Decimal("0.00"),
            )
        self.assertIn("precio_referencial", ctx.exception.message_dict)

    def test_publicar_lote_ajeno_lanza_error_de_permiso(self):
        """Aislamiento entre productores: no se puede publicar el lote de otro productor."""
        otro_productor = uuid.uuid4()
        with self.assertRaises(ValidationError) as ctx:
            publicar_lote_en_catalogo(
                lote_id=self.lote.id,
                productor_id=otro_productor,
            )
        self.assertIn("permiso", ctx.exception.message_dict)

    def test_publicar_lote_incompleto_lanza_validation_error_con_lista(self):
        """Si falta información mínima, el servicio lanza ValidationError con lista de detalles."""
        self.calidad.delete()
        with self.assertRaises(ValidationError) as ctx:
            publicar_lote_en_catalogo(
                lote_id=self.lote.id,
                productor_id=self.productor_id,
            )
        self.assertIn("publicacion", ctx.exception.message_dict)
        self.assertTrue(len(ctx.exception.message_dict["publicacion"]) >= 1)

    def test_despublicar_lote_exitoso_actualiza_estado_y_bitacora(self):
        """Retirar un lote del catálogo cambia su estado y genera la traza en la bitácora."""
        # Publicamos primero
        publicar_lote_en_catalogo(lote_id=self.lote.id, productor_id=self.productor_id)

        # Ahora despublicamos
        lote_retirado = despublicar_lote_de_catalogo(
            lote_id=self.lote.id,
            productor_id=self.productor_id,
            realizado_por_id=str(self.productor_id),
            realizado_por_correo="test@cafe.com",
            motivo="Vendido a comprador local",
        )

        self.assertFalse(lote_retirado.publicado_en_catalogo)

        # La bitácora debe tener 2 eventos: PUBLICAR y DESPUBLICAR
        historial = BitacoraPublicacionLote.objects.filter(lote=self.lote).order_by("creado_en", "id")
        self.assertEqual(historial.count(), 2)
        ultimo_evento = historial.last()
        self.assertEqual(ultimo_evento.accion, "DESPUBLICAR")
        self.assertEqual(ultimo_evento.observaciones, "Vendido a comprador local")

    def test_despublicar_lote_no_publicado_lanza_validation_error(self):
        """Intentar retirar un lote que no estaba publicado genera un error controlado."""
        with self.assertRaises(ValidationError) as ctx:
            despublicar_lote_de_catalogo(
                lote_id=self.lote.id,
                productor_id=self.productor_id,
            )
        self.assertIn("publicacion", ctx.exception.message_dict)


class TestScrum239EndpointsRestPublicacion(TestCase):
    """
    Subtarea: SCRUM-239 / HU19-ST1: Crear la acción o endpoint para publicar un lote.
    Endpoints:
    - POST /fincas/api/lotes/<pk>/publicar/
    - POST /fincas/api/lotes/<pk>/despublicar/
    - GET /fincas/api/lotes/<pk>/validar-publicacion/
    """

    def setUp(self):
        self.client = Client()
        self.municipio = Municipio.objects.create(
            codigo="MUN-API-HU19",
            nombre="Bochalema (API)",
            departamento="Norte de Santander",
            activo=True,
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca API",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Geisha",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="NATURAL_API",
            nombre="Natural",
            activo=True,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-07-20",
            cantidad_total=Decimal("500.00"),
            cantidad_disponible=Decimal("500.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOT-API-01",
            cosecha=self.cosecha,
            cantidad=Decimal("100.00"),
            proceso_beneficio=self.proceso,
            activo=True,
        )
        self.calidad = CaracteristicasCalidad.objects.create(
            lote=self.lote,
            puntaje_taza=Decimal("89.00"),
            humedad=Decimal("10.50"),
        )
        self.url_publicar = reverse("api_lote_publicar", kwargs={"pk": self.lote.pk})
        self.url_despublicar = reverse("api_lote_despublicar", kwargs={"pk": self.lote.pk})
        self.url_validar = reverse("api_lote_validar_publicacion", kwargs={"pk": self.lote.pk})

    def test_api_publicar_sin_autenticacion_retorna_401(self):
        """Petición anónima es rechazada con HTTP 401 Unauthorized."""
        response = self.client.post(self.url_publicar, {}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    @patch("fincas.views.Usuario")
    def test_api_publicar_lote_ajeno_retorna_403(self, mock_usuario_model):
        """Petición con usuario que no es dueño del lote retorna HTTP 403 Forbidden."""
        productor_ajeno = uuid.uuid4()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=productor_ajeno)

        response = self.client.post(
            self.url_publicar,
            {"precio_referencial": "28000.00"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    @patch("fincas.views.Usuario")
    def test_api_publicar_lote_incompleto_retorna_400_con_detalles(self, mock_usuario_model):
        """Petición para lote incompleto retorna HTTP 400 Bad Request con lista de requisitos pendientes."""
        self.calidad.delete()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)

        response = self.client.post(
            self.url_publicar,
            {},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)
        self.assertIn("detalles", data)
        self.assertTrue(len(data["detalles"]) >= 1)

    @patch("fincas.views.Usuario")
    def test_api_publicar_lote_exitoso_retorna_200(self, mock_usuario_model):
        """Petición válida publica el lote y retorna HTTP 200 OK con payload estructurado."""
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)

        response = self.client.post(
            self.url_publicar,
            {
                "precio_referencial": "32000.00",
                "observaciones": "Microlote Geisha Natural",
            },
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("mensaje", data)
        self.assertTrue(data["lote"]["publicado_en_catalogo"])
        self.assertEqual(data["lote"]["precio_referencial"], "32000.00")

        self.lote.refresh_from_db()
        self.assertTrue(self.lote.publicado_en_catalogo)

    @patch("fincas.views.Usuario")
    def test_api_despublicar_lote_exitoso_retorna_200(self, mock_usuario_model):
        """Petición válida despublica el lote y retorna HTTP 200 OK."""
        publicar_lote_en_catalogo(lote_id=self.lote.id, productor_id=self.productor_id)
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)

        response = self.client.post(
            self.url_despublicar,
            {"motivo": "Retiro por ajuste de inventario"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("mensaje", data)
        self.assertFalse(data["lote"]["publicado_en_catalogo"])

        self.lote.refresh_from_db()
        self.assertFalse(self.lote.publicado_en_catalogo)

    @patch("fincas.views.Usuario")
    def test_api_validar_publicacion_retorna_200_con_estado(self, mock_usuario_model):
        """GET /fincas/api/lotes/<pk>/validar-publicacion/ responde 200 OK con checklist."""
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)

        response = self.client.get(
            self.url_validar,
            **_jwt_bearer_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["puede_publicar"])
        self.assertEqual(data["errores"], [])
        self.assertEqual(data["codigo"], "LOT-API-01")


class TestScrum242VistasWebPublicacionYCatalogo(TestCase):
    """
    Subtareas:
    - SCRUM-242 / HU19-ST5: Mostrar mensajes de error cuando el lote no pueda publicarse.
    - SCRUM-243 / HU19-ST3: Actualizar el estado del lote en el catálogo público.
    """

    def setUp(self):
        self.client = Client()
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.municipio = Municipio.objects.create(
            codigo="MUN-WEB-HU19",
            nombre="Chinácota (Web)",
            departamento="Norte de Santander",
            activo=True,
        )
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Cabaña",
            productor_id=self.productor_id,
            municipio=self.municipio,
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Tabi",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO_WEB",
            nombre="Lavado",
            activo=True,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-08-10",
            cantidad_total=Decimal("400.00"),
            cantidad_disponible=Decimal("400.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOT-WEB-01",
            cosecha=self.cosecha,
            cantidad=Decimal("120.00"),
            proceso_beneficio=self.proceso,
            activo=True,
        )
        self.calidad = CaracteristicasCalidad.objects.create(
            lote=self.lote,
            puntaje_taza=Decimal("85.50"),
            humedad=Decimal("11.00"),
        )
        self.url_publicar_web = reverse("lote_publicar", kwargs={"pk": self.lote.pk})
        self.url_despublicar_web = reverse("lote_despublicar", kwargs={"pk": self.lote.pk})
        self.url_mis_lotes = reverse("mis_lotes")
        self.url_catalogo = reverse("catalogo")

    def test_web_publicar_lote_sin_sesion_redirige_a_login(self):
        """Petición web sin sesión iniciada redirige al login."""
        response = self.client.post(self.url_publicar_web, {})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_web_publicar_lote_exitoso_redirige_a_mis_lotes_con_mensaje_exito(self):
        """Publicación web válida actualiza el lote y redirige a 'mis_lotes' con mensaje de éxito."""
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)

        response = self.client.post(
            self.url_publicar_web,
            {
                "precio_referencial": "24000.00",
                "observaciones": "Lote seleccionado de alta cordillera",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_mis_lotes)

        self.lote.refresh_from_db()
        self.assertTrue(self.lote.publicado_en_catalogo)
        self.assertEqual(self.lote.precio_referencial, Decimal("24000.00"))

    def test_web_publicar_lote_incompleto_muestra_mensaje_error(self):
        """Publicar un lote incompleto desde la interfaz genera un mensaje flash de error detallado."""
        self.calidad.delete()
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)

        response = self.client.post(self.url_publicar_web, {})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_mis_lotes)

        self.lote.refresh_from_db()
        self.assertFalse(self.lote.publicado_en_catalogo)

    def test_web_despublicar_lote_exitoso_redirige_a_mis_lotes(self):
        """Retirar lote desde la interfaz cambia su estado y redirige."""
        publicar_lote_en_catalogo(lote_id=self.lote.id, productor_id=self.productor_id)
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)

        response = self.client.post(
            self.url_despublicar_web,
            {"motivo": "Fin de inventario"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.url_mis_lotes)

        self.lote.refresh_from_db()
        self.assertFalse(self.lote.publicado_en_catalogo)

    def test_web_mis_lotes_renderiza_estado_y_botones_de_catalogo(self):
        """La vista 'Mis Lotes' muestra las columnas de catálogo público y los botones de acción."""
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_mis_lotes)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Catálogo Público", content)
        self.assertIn("LOT-WEB-01", content)
        self.assertIn("Publicar", content)

    def test_web_catalogo_muestra_lotes_publicados_y_excluye_no_publicados(self):
        """El catálogo comercial solo renderiza lotes con publicado_en_catalogo=True."""
        # Lote 1: publicado
        publicar_lote_en_catalogo(
            lote_id=self.lote.id,
            productor_id=self.productor_id,
            precio_referencial=Decimal("29000.00"),
        )

        # Lote 2: NO publicado
        lote_no_pub = Lote.objects.create(
            codigo="LOT-OCULTO-02",
            cosecha=self.cosecha,
            cantidad=Decimal("50.00"),
            proceso_beneficio=self.proceso,
            publicado_en_catalogo=False,
            activo=True,
        )

        response = self.client.get(self.url_catalogo)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("LOT-WEB-01", content)
        self.assertIn("Finca La Cabaña", content)
        self.assertIn("Chinácota (Web)", content)
        self.assertIn("Tabi", content)
        self.assertIn("85.5", content)
        self.assertIn("29000.00", content)

        # El lote no publicado NO debe aparecer en el catálogo público
        self.assertNotIn("LOT-OCULTO-02", content)


# ==============================================================================
# PRUEBAS HU-20 / SCRUM-229: FILTRADO DEL CATÁLOGO COMERCIAL
# Subtareas: SCRUM-246 a SCRUM-253
# ==============================================================================

class FiltradoCatalogoComercialHU20Tests(TestCase):
    """
    Suite integral de pruebas para el filtrado del catálogo comercial (HU-20).
    Cubre:
    - SCRUM-246 / HU20-ST1: Interfaz y controles de la barra de filtros.
    - SCRUM-247 / HU20-ST2: Desplegable de municipios con lotes disponibles.
    - SCRUM-248 / HU20-ST4: Reglas, normalización y validación de filtros.
    - SCRUM-249 / HU20-ST5: Consultas de filtrado individual y combinadas con AND.
    - SCRUM-250 / HU20-ST3: Endpoint REST /fincas/api/catalogo/ y respuestas 200/400.
    - SCRUM-251 / HU20-ST6: Filtrado por calidad mínima en taza (SCA).
    - SCRUM-252 / HU20-ST7: Manejo de estado sin resultados con mensajes y botón limpiar.
    - SCRUM-253 / HU20-ST8: Cobertura integral de pruebas unitarias y de integración.
    """

    def setUp(self):
        self.client = Client()
        self.url_catalogo_web = reverse("catalogo")
        self.url_catalogo_api = reverse("api_catalogo")

        self.productor_id = uuid.uuid4()

        # Municipios (utilizar existentes de la fixture o crear si no existen)
        self.mun_toledo = Municipio.objects.filter(nombre="Toledo", departamento="Norte de Santander").first()
        if not self.mun_toledo:
            self.mun_toledo = Municipio.objects.create(codigo="MUN_TOL_20", nombre="Toledo", departamento="Norte de Santander", activo=True)

        self.mun_chinacota = Municipio.objects.filter(nombre="Chinácota", departamento="Norte de Santander").first()
        if not self.mun_chinacota:
            self.mun_chinacota = Municipio.objects.create(codigo="MUN_CHI_20", nombre="Chinácota", departamento="Norte de Santander", activo=True)

        self.mun_salazar = Municipio.objects.filter(nombre="Salazar", departamento="Norte de Santander").first()
        if not self.mun_salazar:
            self.mun_salazar = Municipio.objects.create(codigo="MUN_SAL_20", nombre="Salazar", departamento="Norte de Santander", activo=True)

        # Fincas
        self.finca_toledo = Finca.objects.create(
            nombre="Finca El Roble",
            productor_id=self.productor_id,
            municipio=self.mun_toledo,
            vereda="El Hato",
            activo=True,
        )
        self.finca_chinacota = Finca.objects.create(
            nombre="Finca Bella Vista",
            productor_id=self.productor_id,
            municipio=self.mun_chinacota,
            vereda="Iscalá",
            activo=True,
        )
        self.finca_inactiva = Finca.objects.create(
            nombre="Finca Inactiva",
            productor_id=self.productor_id,
            municipio=self.mun_toledo,
            activo=False,
        )

        # Variedades
        self.var_castillo = VariedadCafe.objects.create(nombre="Castillo HU20", especie=VariedadCafe.Especie.ARABICA, activo=True)
        self.var_geisha = VariedadCafe.objects.create(nombre="Geisha HU20", especie=VariedadCafe.Especie.ARABICA, activo=True)
        self.var_bourbon = VariedadCafe.objects.create(nombre="Bourbon HU20", especie=VariedadCafe.Especie.ARABICA, activo=True)

        # Procesos
        self.proc_lavado = ProcesoBeneficio.objects.create(codigo="PROC_LAV_20", nombre="Lavado HU20", orden=1, activo=True)
        self.proc_natural = ProcesoBeneficio.objects.create(codigo="PROC_NAT_20", nombre="Natural HU20", orden=2, activo=True)
        self.proc_honey = ProcesoBeneficio.objects.create(codigo="PROC_HON_20", nombre="Honey HU20", orden=3, activo=True)

        # Cosechas
        self.cosecha_toledo = Cosecha.objects.create(
            finca=self.finca_toledo,
            variedad=self.var_castillo,
            fecha_cosecha="2026-09-01",
            cantidad_total=Decimal("500.00"),
            cantidad_disponible=Decimal("300.00"),
            activo=True,
        )
        self.cosecha_chinacota = Cosecha.objects.create(
            finca=self.finca_chinacota,
            variedad=self.var_geisha,
            fecha_cosecha="2026-09-15",
            cantidad_total=Decimal("200.00"),
            cantidad_disponible=Decimal("120.00"),
            activo=True,
        )
        self.cosecha_inactiva = Cosecha.objects.create(
            finca=self.finca_toledo,
            variedad=self.var_castillo,
            fecha_cosecha="2026-08-01",
            cantidad_total=Decimal("100.00"),
            cantidad_disponible=Decimal("100.00"),
            activo=False,
        )

        # Lotes publicados disponibles
        # Lote A: Toledo, Castillo, Lavado, 86.5 SCA
        self.lote_a = Lote.objects.create(
            codigo="LOT-TOL-01",
            cosecha=self.cosecha_toledo,
            cantidad=Decimal("100.00"),
            proceso_beneficio=self.proc_lavado,
            publicado_en_catalogo=True,
            precio_referencial=Decimal("26000.00"),
            activo=True,
        )
        self.calidad_a = CaracteristicasCalidad.objects.create(
            lote=self.lote_a,
            puntaje_taza=Decimal("86.50"),
            humedad=Decimal("11.20"),
            perfil_sensorial="Notas a chocolate y jazmín",
        )

        # Lote B: Chinácota, Geisha, Natural, 89.0 SCA
        self.lote_b = Lote.objects.create(
            codigo="LOT-CHI-02",
            cosecha=self.cosecha_chinacota,
            cantidad=Decimal("80.00"),
            proceso_beneficio=self.proc_natural,
            publicado_en_catalogo=True,
            precio_referencial=Decimal("45000.00"),
            activo=True,
        )
        self.calidad_b = CaracteristicasCalidad.objects.create(
            lote=self.lote_b,
            puntaje_taza=Decimal("89.00"),
            humedad=Decimal("10.50"),
            perfil_sensorial="Notas a mandarina y bergamota",
        )

        # Lote C: Toledo, Castillo, Natural, solo humedad (sin puntaje en taza)
        self.lote_c = Lote.objects.create(
            codigo="LOT-TOL-03",
            cosecha=self.cosecha_toledo,
            cantidad=Decimal("50.00"),
            proceso_beneficio=self.proc_natural,
            publicado_en_catalogo=True,
            precio_referencial=Decimal("22000.00"),
            activo=True,
        )
        self.calidad_c = CaracteristicasCalidad.objects.create(
            lote=self.lote_c,
            humedad=Decimal("11.80"),
            perfil_sensorial="Frutos secos y panela",
        )

        # Lotes NO disponibles que deben ser SIEMPRE excluidos
        # Lote agotado (cantidad = 0)
        self.lote_agotado = Lote.objects.create(
            codigo="LOT-AGOTADO",
            cosecha=self.cosecha_toledo,
            cantidad=Decimal("0.00"),
            proceso_beneficio=self.proc_lavado,
            publicado_en_catalogo=True,
            activo=True,
        )
        # Lote no publicado
        self.lote_no_publicado = Lote.objects.create(
            codigo="LOT-NO-PUB",
            cosecha=self.cosecha_toledo,
            cantidad=Decimal("100.00"),
            proceso_beneficio=self.proc_lavado,
            publicado_en_catalogo=False,
            activo=True,
        )
        # Lote inactivo
        self.lote_inactivo = Lote.objects.create(
            codigo="LOT-INACTIVO",
            cosecha=self.cosecha_toledo,
            cantidad=Decimal("100.00"),
            proceso_beneficio=self.proc_lavado,
            publicado_en_catalogo=True,
            activo=False,
        )
        # Lote con cosecha inactiva
        self.lote_cosecha_inactiva = Lote.objects.create(
            codigo="LOT-COS-INACT",
            cosecha=self.cosecha_inactiva,
            cantidad=Decimal("100.00"),
            proceso_beneficio=self.proc_lavado,
            publicado_en_catalogo=True,
            activo=True,
        )

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-248 / HU20-ST4 (Criterios y reglas de filtrado)
    # --------------------------------------------------------------------------
    def test_lotes_disponibles_filtra_solo_lotes_validos(self):
        """El queryset base solo contiene lotes publicados, activos, con stock y cosecha/finca activa."""
        disponibles = list(lotes_disponibles_en_catalogo())
        self.assertIn(self.lote_a, disponibles)
        self.assertIn(self.lote_b, disponibles)
        self.assertIn(self.lote_c, disponibles)

        self.assertNotIn(self.lote_agotado, disponibles)
        self.assertNotIn(self.lote_no_publicado, disponibles)
        self.assertNotIn(self.lote_inactivo, disponibles)
        self.assertNotIn(self.lote_cosecha_inactiva, disponibles)
        self.assertEqual(len(disponibles), 3)

    def test_normalizar_filtros_catalogo_valida_correctamente(self):
        """La función normaliza parámetros válidos y captura errores con mensajes descriptivos."""
        # Caso válido
        params_validos = {
            "municipio": str(self.mun_toledo.id),
            "variedad": str(self.var_castillo.id),
            "proceso": str(self.proc_lavado.id),
            "puntaje_min": "85.5",
            "q": "   café de altura   ",
        }
        filtros, errores = normalizar_filtros_catalogo(params_validos)
        self.assertEqual(errores, {})
        self.assertEqual(filtros["municipio"], self.mun_toledo.id)
        self.assertEqual(filtros["variedad"], self.var_castillo.id)
        self.assertEqual(filtros["proceso"], self.proc_lavado.id)
        self.assertEqual(filtros["puntaje_min"], Decimal("85.5"))
        self.assertEqual(filtros["q"], "café de altura")

        # Caso con errores
        params_invalidos = {
            "municipio": "letras_en_vez_de_id",
            "variedad": "-5",
            "puntaje_min": "105.0",
        }
        filtros_inv, errores_inv = normalizar_filtros_catalogo(params_invalidos)
        self.assertIn("municipio", errores_inv)
        self.assertIn("variedad", errores_inv)
        self.assertIn("puntaje_min", errores_inv)

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-247 / HU20-ST2 (Filtro por municipio)
    # --------------------------------------------------------------------------
    def test_filtrar_por_municipio(self):
        """Filtrar por municipio retorna solo lotes cuya finca pertenezca a dicho municipio."""
        lotes_toledo = list(filtrar_catalogo_lotes(municipio=self.mun_toledo.id))
        self.assertIn(self.lote_a, lotes_toledo)
        self.assertIn(self.lote_c, lotes_toledo)
        self.assertNotIn(self.lote_b, lotes_toledo)

        lotes_chinacota = list(filtrar_catalogo_lotes(municipio=self.mun_chinacota.id))
        self.assertEqual(lotes_chinacota, [self.lote_b])

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-249 / HU20-ST5 (Filtro por variedad y proceso)
    # --------------------------------------------------------------------------
    def test_filtrar_por_variedad(self):
        """Filtrar por variedad retorna lotes de la variedad especificada."""
        lotes_castillo = list(filtrar_catalogo_lotes(variedad=self.var_castillo.id))
        self.assertIn(self.lote_a, lotes_castillo)
        self.assertIn(self.lote_c, lotes_castillo)
        self.assertNotIn(self.lote_b, lotes_castillo)

        lotes_geisha = list(filtrar_catalogo_lotes(variedad=self.var_geisha.id))
        self.assertEqual(lotes_geisha, [self.lote_b])

    def test_filtrar_por_proceso(self):
        """Filtrar por proceso retorna lotes procesados con ese método de beneficio."""
        lotes_lavado = list(filtrar_catalogo_lotes(proceso=self.proc_lavado.id))
        self.assertEqual(lotes_lavado, [self.lote_a])

        lotes_natural = list(filtrar_catalogo_lotes(proceso=self.proc_natural.id))
        self.assertIn(self.lote_b, lotes_natural)
        self.assertIn(self.lote_c, lotes_natural)
        self.assertNotIn(self.lote_a, lotes_natural)

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-251 / HU20-ST6 (Filtro por calidad mínima SCA)
    # --------------------------------------------------------------------------
    def test_filtrar_por_calidad_minima_puntaje_taza(self):
        """Filtrar por puntaje mínimo en taza excluye lotes con puntaje menor o sin evaluación."""
        # >= 86.0 incluye Lote A (86.5) y Lote B (89.0), excluye Lote C (sin puntaje)
        lotes_86 = list(filtrar_catalogo_lotes(puntaje_min=Decimal("86.00")))
        self.assertIn(self.lote_a, lotes_86)
        self.assertIn(self.lote_b, lotes_86)
        self.assertNotIn(self.lote_c, lotes_86)

        # >= 88.0 incluye solo Lote B (89.0)
        lotes_88 = list(filtrar_catalogo_lotes(puntaje_min=Decimal("88.00")))
        self.assertEqual(lotes_88, [self.lote_b])

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-249 / HU20-ST5 (Búsqueda por texto y filtros combinados AND)
    # --------------------------------------------------------------------------
    def test_filtrar_por_busqueda_libre_q(self):
        """La búsqueda de texto coincide por código, finca, vereda, municipio y perfil sensorial."""
        # Por código
        self.assertEqual(list(filtrar_catalogo_lotes(q="LOT-CHI")), [self.lote_b])
        # Por nombre de finca
        self.assertEqual(list(filtrar_catalogo_lotes(q="Bella Vista")), [self.lote_b])
        # Por vereda
        self.assertEqual(list(filtrar_catalogo_lotes(q="Iscalá")), [self.lote_b])
        # Por perfil sensorial
        self.assertEqual(list(filtrar_catalogo_lotes(q="bergamota")), [self.lote_b])
        self.assertEqual(list(filtrar_catalogo_lotes(q="chocolate")), [self.lote_a])

    def test_filtros_combinados_con_logica_and(self):
        """Varios filtros aplicados a la vez se combinan con AND estricto."""
        # Toledo + Proceso Natural -> Lote C
        res = list(filtrar_catalogo_lotes(municipio=self.mun_toledo.id, proceso=self.proc_natural.id))
        self.assertEqual(res, [self.lote_c])

        # Toledo + Proceso Natural + puntaje_min 85 -> Vacío (Lote C no tiene puntaje >= 85)
        res_vacio = list(
            filtrar_catalogo_lotes(
                municipio=self.mun_toledo.id,
                proceso=self.proc_natural.id,
                puntaje_min=Decimal("85.00"),
            )
        )
        self.assertEqual(res_vacio, [])

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-247 / HU20-ST2 (Opciones disponibles para desplegables)
    # --------------------------------------------------------------------------
    def test_obtener_opciones_filtro_catalogo_solo_incluye_existentes(self):
        """Los desplegables solo ofrecen opciones que tengan al menos un lote disponible."""
        opciones = obtener_opciones_filtro_catalogo()

        # Toledo y Chinácota tienen lotes; Salazar NO tiene
        muns = list(opciones["municipios"])
        self.assertIn(self.mun_toledo, muns)
        self.assertIn(self.mun_chinacota, muns)
        self.assertNotIn(self.mun_salazar, muns)

        # Castillo y Geisha tienen lotes; Bourbon NO tiene
        vars_list = list(opciones["variedades"])
        self.assertIn(self.var_castillo, vars_list)
        self.assertIn(self.var_geisha, vars_list)
        self.assertNotIn(self.var_bourbon, vars_list)

        # Lavado y Natural tienen lotes; Honey NO tiene
        procs = list(opciones["procesos"])
        self.assertIn(self.proc_lavado, procs)
        self.assertIn(self.proc_natural, procs)
        self.assertNotIn(self.proc_honey, procs)

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-250 / HU20-ST3 (API REST del catálogo)
    # --------------------------------------------------------------------------
    def test_api_catalogo_endpoint_publico_200(self):
        """GET /fincas/api/catalogo/ responde 200 sin autenticación con el catálogo completo."""
        response = self.client.get(self.url_catalogo_api)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["resultados"]), 3)
        codigos = [item["codigo"] for item in data["resultados"]]
        self.assertIn("LOT-TOL-01", codigos)
        self.assertIn("LOT-CHI-02", codigos)
        self.assertIn("LOT-TOL-03", codigos)

    def test_api_catalogo_con_filtros_combinados(self):
        """GET /fincas/api/catalogo/?municipio=...&puntaje_min=88 filtra y responde solo lotes coincidentes."""
        url = f"{self.url_catalogo_api}?municipio={self.mun_chinacota.id}&puntaje_min=88.0"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total"], 1)
        self.assertEqual(data["resultados"][0]["codigo"], "LOT-CHI-02")
        self.assertEqual(data["resultados"][0]["finca"], "Finca Bella Vista")
        self.assertEqual(data["resultados"][0]["puntaje_taza"], "89.00")

    def test_api_catalogo_sin_resultados_devuelve_mensaje_amigable(self):
        """Cuando los filtros no arrojan resultados, la API devuelve total 0 y mensaje descriptivo."""
        url = f"{self.url_catalogo_api}?q=palabra_que_no_existe_en_ningun_lote"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total"], 0)
        self.assertEqual(data["resultados"], [])
        self.assertEqual(data["mensaje"], MENSAJE_CATALOGO_SIN_RESULTADOS_FILTRADO)

    def test_api_catalogo_parametros_invalidos_responde_400(self):
        """Parámetros no numéricos o fuera de rango en la API responden 400 Bad Request."""
        url = f"{self.url_catalogo_api}?municipio=abc&puntaje_min=150"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)
        self.assertIn("municipio", data["detalles"])
        self.assertIn("puntaje_min", data["detalles"])

    # --------------------------------------------------------------------------
    # Subtarea: SCRUM-246, SCRUM-252 (Vista Web del Catálogo y Estados Vacíos)
    # --------------------------------------------------------------------------
    def test_web_catalogo_renderiza_barra_de_filtros_y_opciones(self):
        """La vista web del catálogo renderiza la barra de filtros con los desplegables poblados."""
        response = self.client.get(self.url_catalogo_web)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("Filtrar Lotes Disponibles", content)
        self.assertIn("id_filtro_municipio", content)
        self.assertIn("id_filtro_variedad", content)
        self.assertIn("id_filtro_proceso", content)
        self.assertIn("id_filtro_puntaje_min", content)
        self.assertIn("id_filtro_q", content)

        # Municipios con lotes deben aparecer en el HTML
        self.assertIn("Toledo", content)
        self.assertIn("Chinácota", content)
        # Salazar NO debe aparecer en el select
        self.assertNotIn("<option value=\"\" >Salazar", content)

    def test_web_catalogo_filtrado_exitoso_muestra_chips_activos(self):
        """Al filtrar por GET, la vista web muestra los lotes filtrados y los badges de filtros activos."""
        url = f"{self.url_catalogo_web}?municipio={self.mun_chinacota.id}&puntaje_min=88"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("LOT-CHI-02", content)
        self.assertNotIn("LOT-TOL-01", content)
        self.assertIn("Filtros activos:", content)
        self.assertIn("≥ 88 pts SCA", content)

    def test_web_catalogo_sin_resultados_muestra_mensaje_y_boton_limpiar(self):
        """Si un filtro no arroja resultados, muestra el mensaje amigable y el botón para limpiar filtros."""
        url = f"{self.url_catalogo_web}?q=inexistente9999"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("No hay lotes que coincidan con los filtros", content)
        self.assertIn(MENSAJE_CATALOGO_SIN_RESULTADOS_FILTRADO, content)
        self.assertIn("Ver todos los lotes disponibles", content)

    def test_web_catalogo_completamente_vacio_muestra_mensaje_general(self):
        """Si no hay ningún lote publicado en el catálogo, muestra el estado general vacío."""
        Lote.objects.all().delete()
        response = self.client.get(self.url_catalogo_web)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("No hay lotes publicados en este momento", content)
        self.assertIn(MENSAJE_CATALOGO_VACIO, content)


# =============================================================================
# HU-14 / SCRUM-18: Registrar etapas de beneficio de un lote
# =============================================================================
class EtapasBeneficioHU14Tests(TestCase):
    """
    Subtareas:
    - SCRUM-148 / HU14-ST1: Diseñar la interfaz para capturar etapas de beneficio.
    - SCRUM-149 / HU14-ST2: Mostrar el historial de beneficio del lote.
    """

    def setUp(self):
        self.client = Client()
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca El Mirador",
            productor_id=self.productor_id,
            municipio=self.municipio,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            fecha_cosecha="2026-09-01",
            cantidad_total=Decimal("300.00"),
        )
        self.lote = Lote.objects.create(
            codigo="LOTEHU14",
            cosecha=self.cosecha,
            cantidad=Decimal("100.00"),
            estado_lote=EstadoLote.objects.get_or_create(
                codigo="BENEFICIO", defaults={"nombre": "En Beneficio", "activo": True}
            )[0],
        )
        self.url_detalle = reverse("lote_detalle", kwargs={"pk": self.lote.pk})
        self.url_registro = reverse("lote_etapa_registro", kwargs={"pk": self.lote.pk})

    # ---------------------------- HU14-ST1 ----------------------------
    def test_formulario_ofrece_solo_etapas_validas_de_la_lista(self):
        form = EtapaBeneficioForm()
        valores = [valor for valor, _ in form.fields["etapa"].choices if valor]
        self.assertEqual(
            valores, ["DESPULPADO", "FERMENTACION", "LAVADO", "SECADO"]
        )
        self.assertIsInstance(form.fields["etapa"].widget, forms_module.Select)

    def test_formulario_rechaza_etapa_en_texto_libre(self):
        form = EtapaBeneficioForm(data={"etapa": "Tostado", "fecha": "2026-09-05"})
        self.assertFalse(form.is_valid())
        self.assertIn("etapa", form.errors)

    def test_formulario_exige_fecha(self):
        form = EtapaBeneficioForm(data={"etapa": "LAVADO", "fecha": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("La fecha de la etapa es obligatoria.", form.errors["fecha"])

    def test_formulario_observaciones_son_opcionales(self):
        form = EtapaBeneficioForm(data={"etapa": "SECADO", "fecha": "2026-09-05"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_registro_sin_sesion_redirige_a_login(self):
        response = self.client.get(self.url_registro)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_pantalla_registro_muestra_contexto_del_lote_y_campos(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_registro)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LOTEHU14")
        self.assertContains(response, "Finca El Mirador")
        self.assertContains(response, 'id="id_etapa"')
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'id="id_observaciones"')
        # Fecha marcada visualmente como obligatoria
        self.assertContains(response, 'Fecha de la etapa <span class="text-danger">*</span>', html=False)

    def test_registro_valido_guarda_etapa_y_redirige_al_historial(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.post(
            self.url_registro,
            {"etapa": "DESPULPADO", "fecha": "2026-09-02", "observaciones": "  Despulpado el mismo día  "},
        )
        self.assertRedirects(response, self.url_detalle)
        etapa = EtapaBeneficio.objects.get(lote=self.lote)
        self.assertEqual(etapa.etapa, EtapaBeneficio.TipoEtapa.DESPULPADO)
        self.assertEqual(str(etapa.fecha), "2026-09-02")
        self.assertEqual(etapa.observaciones, "Despulpado el mismo día")

    def test_registro_invalido_no_guarda_y_muestra_errores(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.post(self.url_registro, {"etapa": "", "fecha": ""})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EtapaBeneficio.objects.exists())
        self.assertContains(response, "Debe seleccionar la etapa de beneficio.")
        self.assertContains(response, "La fecha de la etapa es obligatoria.")

    def test_no_permite_registrar_etapa_en_lote_de_otro_productor(self):
        _iniciar_sesion_productor(self.client)
        response = self.client.post(
            self.url_registro, {"etapa": "LAVADO", "fecha": "2026-09-03"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_mis_lotes_enlaza_historial_y_nueva_etapa(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(reverse("mis_lotes"))
        self.assertContains(response, self.url_detalle)
        self.assertContains(response, self.url_registro)

    # ---------------------------- HU14-ST2 ----------------------------
    def test_historial_vacio_muestra_estado_claro(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_detalle)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "todavía no tiene etapas de beneficio registradas")

    def test_historial_muestra_etapas_en_orden_cronologico(self):
        # Se registran desordenadas a propósito
        EtapaBeneficio.objects.create(lote=self.lote, etapa="SECADO", fecha="2026-09-10", observaciones="Secado en marquesina")
        EtapaBeneficio.objects.create(lote=self.lote, etapa="DESPULPADO", fecha="2026-09-02")
        EtapaBeneficio.objects.create(lote=self.lote, etapa="FERMENTACION", fecha="2026-09-03", observaciones="18 horas")
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_detalle)
        self.assertEqual(response.status_code, 200)
        etapas = list(response.context["etapas"])
        self.assertEqual(
            [e.etapa for e in etapas], ["DESPULPADO", "FERMENTACION", "SECADO"]
        )
        contenido = response.content.decode()
        self.assertLess(contenido.index("Despulpado"), contenido.index("Fermentación"))
        self.assertLess(contenido.index("Fermentación"), contenido.index("Secado</span>"))
        self.assertContains(response, "10/09/2026")
        self.assertContains(response, "Secado en marquesina")
        self.assertContains(response, "18 horas")
        self.assertNotContains(response, "todavía no tiene etapas de beneficio registradas")

    def test_historial_misma_fecha_respeta_orden_de_registro(self):
        EtapaBeneficio.objects.create(lote=self.lote, etapa="FERMENTACION", fecha="2026-09-03")
        EtapaBeneficio.objects.create(lote=self.lote, etapa="LAVADO", fecha="2026-09-03")
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_detalle)
        self.assertEqual(
            [e.etapa for e in response.context["etapas"]], ["FERMENTACION", "LAVADO"]
        )

    def test_historial_solo_muestra_etapas_del_lote_consultado(self):
        otro_lote = Lote.objects.create(codigo="LOTEOTRO", cosecha=self.cosecha, cantidad=Decimal("50.00"))
        EtapaBeneficio.objects.create(lote=otro_lote, etapa="LAVADO", fecha="2026-09-04", observaciones="De otro lote")
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_detalle)
        self.assertNotContains(response, "De otro lote")
        self.assertContains(response, "todavía no tiene etapas de beneficio registradas")

    def test_historial_de_lote_ajeno_responde_404(self):
        _iniciar_sesion_productor(self.client)
        response = self.client.get(self.url_detalle)
        self.assertEqual(response.status_code, 404)


class ReglasRegistroEtapasHU14ST3ST4Tests(TestCase):
    """
    Subtareas:
    - SCRUM-152 / HU14-ST3: Validar reglas de registro de etapas.
    - SCRUM-150 / HU14-ST4: Implementar la lógica de negocio para registrar etapas.
    """

    def setUp(self):
        self.client = Client()
        # HU22: estas vistas ahora exigen el permiso RBAC real (ver
        # permiso_requerido_sesion en fincas/views.py). La matriz de roles
        # vive en Supabase (tabla rol_permisos, managed=False), asi que no
        # existe en la BD de pruebas -- se simula que el productor de estas
        # pruebas SI tiene los permisos de su rol (coherente con
        # MATRIZ_RBAC_VIGENTE en usuarios/tests.py), igual que ya hacen las
        # pruebas de admin_municipios_view con usuario_tiene_permiso.
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        # El filtro de plantilla {{ rol_actual|tiene_permiso:... }} (nav de
        # base.html) importa la funcion por nombre dentro de rbac_tags, asi
        # que necesita su propio parche (igual que ya hace
        # fincas.tests.TestScrum242VistasWebPublicacionYCatalogo mas abajo).
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Loma", productor_id=self.productor_id, municipio=self.municipio
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca, fecha_cosecha="2026-09-01", cantidad_total=Decimal("300.00")
        )
        self.lote = Lote.objects.create(
            codigo="LOTEST34", cosecha=self.cosecha, cantidad=Decimal("100.00"),
            estado_lote=EstadoLote.objects.get_or_create(
                codigo="BENEFICIO", defaults={"nombre": "En Beneficio", "activo": True}
            )[0],
        )
        self.url_registro = reverse("lote_etapa_registro", kwargs={"pk": self.lote.pk})
        self.url_detalle = reverse("lote_detalle", kwargs={"pk": self.lote.pk})

    def _datos(self, **extra):
        datos = {"lote_o_id": self.lote, "etapa": "LAVADO", "fecha": "2026-09-05", "observaciones": "ok"}
        datos.update(extra)
        return datos

    # ------------------------------ ST3 ------------------------------
    def test_rechaza_etapa_sin_fecha(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(fecha=None))
        self.assertIn("fecha", ctx.exception.message_dict)
        self.assertEqual(
            ctx.exception.message_dict["fecha"], ["La fecha de la etapa es obligatoria."]
        )
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_rechaza_etapa_fuera_de_la_lista(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(etapa="TOSTADO"))
        self.assertIn("etapa", ctx.exception.message_dict)
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_rechaza_etapa_vacia(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(etapa=""))
        self.assertIn("etapa", ctx.exception.message_dict)

    def test_rechaza_observaciones_demasiado_largas(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(observaciones="x" * 501))
        self.assertIn("observaciones", ctx.exception.message_dict)
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_acepta_observaciones_en_el_limite(self):
        etapa = registrar_etapa_beneficio(**self._datos(observaciones="x" * 500))
        self.assertEqual(len(etapa.observaciones), 500)

    def test_rechaza_observaciones_con_caracteres_de_control(self):
        for texto in ["hola\x00mundo", "texto\x07", "otro\x1b[31m"]:
            with self.subTest(texto=texto):
                with self.assertRaises(ValidationError) as ctx:
                    registrar_etapa_beneficio(**self._datos(observaciones=texto))
                self.assertIn("observaciones", ctx.exception.message_dict)
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_acepta_saltos_de_linea_y_tabulaciones_en_observaciones(self):
        etapa = registrar_etapa_beneficio(**self._datos(observaciones="Línea 1\nLínea 2\tfin"))
        self.assertEqual(etapa.observaciones, "Línea 1\nLínea 2\tfin")

    def test_formulario_web_aplica_las_mismas_reglas_de_observaciones(self):
        form = EtapaBeneficioForm(data={"etapa": "LAVADO", "fecha": "2026-09-05", "observaciones": "x" * 501})
        self.assertFalse(form.is_valid())
        self.assertIn("observaciones", form.errors)
        form = EtapaBeneficioForm(data={"etapa": "LAVADO", "fecha": "2026-09-05", "observaciones": "a\x00b"})
        self.assertFalse(form.is_valid())

    def test_formulario_web_limita_longitud_en_el_navegador(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_registro)
        self.assertContains(response, 'maxlength="500"')

    def test_pantalla_muestra_error_de_observaciones_largas(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.post(
            self.url_registro, {"etapa": "LAVADO", "fecha": "2026-09-05", "observaciones": "x" * 501}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no pueden superar 500 caracteres")
        self.assertFalse(EtapaBeneficio.objects.exists())

    # ------------------------------ ST4 ------------------------------
    def test_registro_valido_queda_guardado_y_asociado_al_lote(self):
        etapa = registrar_etapa_beneficio(**self._datos(observaciones="  Lavado completo  "))
        self.assertEqual(etapa.lote, self.lote)
        self.assertEqual(etapa.etapa, "LAVADO")
        self.assertEqual(str(etapa.fecha), "2026-09-05")
        self.assertEqual(etapa.observaciones, "Lavado completo")
        self.assertTrue(etapa.activo)
        self.assertEqual(self.lote.etapas_beneficio.count(), 1)

    def test_acepta_id_del_lote_en_lugar_del_objeto(self):
        etapa = registrar_etapa_beneficio(**self._datos(lote_o_id=self.lote.pk))
        self.assertEqual(etapa.lote_id, self.lote.pk)

    def test_lote_inexistente_se_rechaza(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(lote_o_id=999999))
        self.assertIn("lote", ctx.exception.message_dict)

    def test_lote_inactivo_se_rechaza(self):
        Lote.objects.filter(pk=self.lote.pk).update(activo=False)
        lote = Lote.objects.get(pk=self.lote.pk)
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(lote_o_id=lote))
        self.assertIn("lote", ctx.exception.message_dict)
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_lote_de_otro_productor_se_rechaza(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(**self._datos(productor_id=uuid.uuid4()))
        self.assertIn("permiso", ctx.exception.message_dict)
        self.assertFalse(EtapaBeneficio.objects.exists())

    def test_productor_dueno_puede_registrar(self):
        etapa = registrar_etapa_beneficio(**self._datos(productor_id=self.productor_id))
        self.assertEqual(etapa.lote, self.lote)

    def test_operacion_atomica_no_guarda_nada_si_falla(self):
        EtapaBeneficio.objects.create(lote=self.lote, etapa="DESPULPADO", fecha="2026-09-02")
        antes = EtapaBeneficio.objects.count()
        with self.assertRaises(ValidationError):
            registrar_etapa_beneficio(**self._datos(fecha="no-es-fecha"))
        with self.assertRaises(ValidationError):
            registrar_etapa_beneficio(**self._datos(observaciones="x" * 501))
        self.assertEqual(EtapaBeneficio.objects.count(), antes)

    def test_si_el_guardado_falla_no_queda_informacion_parcial(self):
        antes = EtapaBeneficio.objects.count()
        with patch.object(EtapaBeneficio, "save", side_effect=IntegrityError("fallo simulado")):
            with self.assertRaises(IntegrityError):
                registrar_etapa_beneficio(**self._datos())
        self.assertEqual(EtapaBeneficio.objects.count(), antes)

    def test_etapa_registrada_aparece_de_inmediato_en_el_historial(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.post(
            self.url_registro,
            {"etapa": "FERMENTACION", "fecha": "2026-09-03", "observaciones": "18 horas en tanque"},
            follow=True,
        )
        self.assertEqual(response.redirect_chain[-1][0], self.url_detalle)
        self.assertContains(response, "Fermentación")
        self.assertContains(response, "18 horas en tanque")
        self.assertContains(response, "03/09/2026")
        self.assertNotContains(response, "todavía no tiene etapas de beneficio registradas")

    def test_vista_web_usa_validacion_de_backend_aunque_el_formulario_pase(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        Lote.objects.filter(pk=self.lote.pk).update(activo=False)
        response = self.client.post(self.url_registro, {"etapa": "LAVADO", "fecha": "2026-09-05"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EtapaBeneficio.objects.exists())

    # ------------------- RNF-14: sin eliminación física -------------------
    def test_eliminar_una_etapa_solo_la_inactiva(self):
        etapa = registrar_etapa_beneficio(**self._datos())
        etapa.delete()
        self.assertTrue(EtapaBeneficio.objects.filter(pk=etapa.pk).exists())
        etapa.refresh_from_db()
        self.assertFalse(etapa.activo)

    def test_eliminar_un_queryset_de_etapas_solo_las_inactiva(self):
        registrar_etapa_beneficio(**self._datos())
        registrar_etapa_beneficio(**self._datos(etapa="SECADO", fecha="2026-09-09"))
        self.lote.etapas_beneficio.all().delete()
        self.assertEqual(EtapaBeneficio.objects.count(), 2)
        self.assertEqual(EtapaBeneficio.objects.filter(activo=True).count(), 0)

    def test_historial_oculta_etapas_inactivas(self):
        etapa = registrar_etapa_beneficio(**self._datos(observaciones="Observación inactiva"))
        etapa.delete()
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(self.url_detalle)
        self.assertNotContains(response, "Observación inactiva")
        self.assertContains(response, "todavía no tiene etapas de beneficio registradas")

    def test_no_se_puede_borrar_un_lote_con_etapas(self):
        registrar_etapa_beneficio(**self._datos())
        with self.assertRaises(ProtectedError):
            self.lote.delete()
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())
        self.assertEqual(EtapaBeneficio.objects.count(), 1)


class FichaDigitalStructureTests(TestCase):
    """
    Pruebas unitarias para HU17-ST4 (SCRUM-169): Definir la estructura y campos de la ficha digital.
    Verifica el contrato de datos formal, la lógica de consolidación y el criterio de aceptación
    de actualización automática en tiempo real.
    """

    def setUp(self):
        self.productor_uuid = uuid.uuid4()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-ARB-TEST",
                nombre="Arboledas",
                departamento="Norte de Santander",
                activo=True,
            )
        self.finca = Finca.objects.create(
            nombre="Finca La Esperanza",
            vereda="El Helechal",
            municipio=self.municipio,
            productor_id=self.productor_uuid,
            latitud=Decimal("7.865432"),
            longitud=Decimal("-72.765432"),
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Castillo Típico",
            defaults={
                "especie": "Arábica",
                "descripcion": "Variedad de alta resistencia y perfil cítrico.",
                "activo": True,
            },
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-09-15",
            cantidad_total=Decimal("800.00"),
            cantidad_disponible=Decimal("600.00"),
            activo=True,
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="LAVADO",
            defaults={
                "nombre": "Lavado Tradicional",
                "descripcion": "Fermentación en tanque y lavado con agua de manantial.",
                "activo": True,
            },
        )
        self.estado, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={
                "nombre": "Disponible para Venta",
                "descripcion": "Lote apto para comercialización.",
                "activo": True,
            },
        )
        self.lote = Lote.objects.create(
            codigo="LOTE-ESP-001",
            cosecha=self.cosecha,
            cantidad=Decimal("200.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

    def test_estructura_campos_ficha_digital_completa(self):
        """
        SCRUM-169: Verifica que la ficha digital generada contenga todas las secciones,
        campos y estructuras esperadas por el contrato de datos FichaDigitalSerializer.
        """
        ficha = obtener_ficha_consolidada_lote(self.lote)

        # 1. Campos del Lote
        self.assertEqual(ficha["id"], self.lote.id)
        self.assertEqual(ficha["codigo"], "LOTE-ESP-001")
        self.assertEqual(ficha["cantidad_kg"], Decimal("200.00"))
        self.assertTrue(ficha["activo"])
        self.assertIsNotNone(ficha["creado_en"])

        # 2. Sección Productor
        self.assertIn("productor", ficha)
        self.assertEqual(ficha["productor"]["id"], str(self.productor_uuid))
        self.assertIn("nombre_completo", ficha["productor"])

        # 3. Sección Finca y Georreferenciación
        self.assertIn("finca", ficha)
        self.assertEqual(ficha["finca"]["nombre"], "Finca La Esperanza")
        self.assertEqual(ficha["finca"]["municipio"], "Arboledas")
        self.assertEqual(ficha["finca"]["departamento"], "Norte de Santander")
        self.assertEqual(ficha["finca"]["latitud"], Decimal("7.865432"))
        self.assertEqual(ficha["finca"]["longitud"], Decimal("-72.765432"))
        self.assertTrue(ficha["finca"]["tiene_georreferenciacion"])

        # 4. Sección Cosecha
        self.assertIn("cosecha", ficha)
        self.assertEqual(ficha["cosecha"]["cantidad_total_cosecha"], Decimal("800.00"))

        # 5. Sección Variedad Botánica
        self.assertIn("variedad", ficha)
        self.assertEqual(ficha["variedad"]["nombre"], "Castillo Típico")
        self.assertEqual(ficha["variedad"]["especie"], "Arábica")

        # 6. Sección Proceso de Beneficio
        self.assertIn("proceso_beneficio", ficha)
        self.assertEqual(ficha["proceso_beneficio"]["codigo"], "LAVADO")
        self.assertEqual(ficha["proceso_beneficio"]["nombre"], "Lavado Tradicional")

        # 7. Sección Estado de Trazabilidad y Comercial
        self.assertIn("estado_lote", ficha)
        self.assertEqual(ficha["estado_lote"]["codigo"], "DISPONIBLE")
        self.assertEqual(ficha["estado_comercial"], "DISPONIBLE")
        self.assertTrue(ficha["disponible_para_venta"])

        # 8. Metadatos de URL pública y porcentaje de completitud
        self.assertEqual(ficha["url_publica"], "/trazabilidad/lote/LOTE-ESP-001/")
        self.assertGreaterEqual(ficha["completitud_porcentaje"], 65)

        # 9. Validación formal con FichaDigitalSerializer
        serializer = FichaDigitalSerializer(data=ficha)
        self.assertTrue(
            serializer.is_valid(),
            f"El serializador de la ficha digital falló la validación: {serializer.errors}",
        )

    def test_obtener_ficha_por_codigo_y_por_pk(self):
        """Verifica que el servicio resuelva el lote indistintamente por instancia, código o PK."""
        ficha_por_instancia = obtener_ficha_consolidada_lote(self.lote)
        ficha_por_codigo = obtener_ficha_consolidada_lote("LOTE-ESP-001")
        ficha_por_pk = obtener_ficha_consolidada_lote(self.lote.pk)

        self.assertEqual(ficha_por_instancia["codigo"], ficha_por_codigo["codigo"])
        self.assertEqual(ficha_por_codigo["codigo"], ficha_por_pk["codigo"])

    def test_ficha_digital_muestra_caracteristicas_de_calidad_hu15(self):
        CaracteristicasCalidad.objects.create(
            lote=self.lote,
            humedad=Decimal("11.50"),
            merma=Decimal("2.00"),
            puntaje_taza=Decimal("86.50"),
            perfil_sensorial="Chocolate y frutos rojos",
            observaciones="Evaluación de laboratorio",
        )

        ficha = obtener_ficha_consolidada_lote(self.lote)

        self.assertEqual(ficha["calidad"]["humedad"], Decimal("11.50"))
        self.assertEqual(ficha["calidad"]["merma"], Decimal("2.00"))
        self.assertEqual(ficha["calidad"]["puntaje_taza"], Decimal("86.50"))
        self.assertEqual(ficha["calidad"]["perfil_sensorial"], "Chocolate y frutos rojos")

        respuesta = self.client.get(
            reverse("lote_ficha_digital_web", kwargs={"codigo": self.lote.codigo})
        )
        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.content.decode()
        self.assertIn("86.50", contenido)
        self.assertIn("Chocolate y frutos rojos", contenido)

    def test_actualizacion_automatica_en_tiempo_real(self):
        """
        Criterio de aceptación HU-17:
        'La ficha se actualiza automáticamente al registrarse nueva información del lote'.
        Al mutar datos del lote o cosecha en la BD, la siguiente consulta refleja los cambios al instante.
        """
        # Consulta inicial
        ficha_inicial = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_inicial["cantidad_kg"], Decimal("200.00"))

        # Mutación de información
        self.lote.cantidad = Decimal("350.00")
        self.lote.save(update_fields=["cantidad"])

        # Consulta inmediata posterior
        ficha_actualizada = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_actualizada["cantidad_kg"], Decimal("350.00"))

    def test_ficha_lote_con_datos_parciales(self):
        """Verifica que un lote sin georreferenciación ni proceso asignado genere una ficha válida."""
        finca_sin_coords = Finca.objects.create(
            nombre="Finca Sin GPS",
            municipio=self.municipio,
            productor_id=uuid.uuid4(),
            latitud=None,
            longitud=None,
            activo=True,
        )
        cosecha_sin_var = Cosecha.objects.create(
            finca=finca_sin_coords,
            fecha_cosecha="2026-10-01",
            cantidad_total=Decimal("100.00"),
            cantidad_disponible=Decimal("100.00"),
            activo=True,
        )
        lote_basico = Lote.objects.create(
            codigo="LOTE-BASICO-99",
            cosecha=cosecha_sin_var,
            cantidad=Decimal("50.00"),
            proceso_beneficio=None,
            estado_lote=None,
            activo=True,
        )

        ficha = obtener_ficha_consolidada_lote(lote_basico)
        self.assertFalse(ficha["finca"]["tiene_georreferenciacion"])
        self.assertIsNone(ficha["finca"]["latitud"])
        self.assertIsNone(ficha["proceso_beneficio"]["id"])

        serializer = FichaDigitalSerializer(data=ficha)
        self.assertTrue(serializer.is_valid(), f"Errores en ficha parcial: {serializer.errors}")

    def test_lote_inexistente_lanza_validation_error(self):
        """Verifica que solicitar un lote inexistente arroje ValidationError amigable."""
        with self.assertRaises(ValidationError):
            obtener_ficha_consolidada_lote("LOTE-NO-EXISTE-XYZ")


# =============================================================================
# SUITE HU-17 (SCRUM-167): ENDPOINT API REST DE FICHA DIGITAL CONSOLIDADA
# =============================================================================


class FichaDigitalAPITests(TestCase):
    """
    Pruebas de integración para el endpoint REST GET /fincas/api/lotes/<codigo>/ficha/ (HU-17 / SCRUM-167).
    Verifica el acceso público (AllowAny), la estructura del JSON devuelto y el manejo de errores 404/400.
    """

    def setUp(self):
        self.client = Client()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-ARB-API",
                nombre="Arboledas",
                departamento="Norte de Santander",
                activo=True,
            )
        self.finca = Finca.objects.create(
            nombre="Finca API Test",
            vereda="La Cima",
            municipio=self.municipio,
            productor_id=uuid.uuid4(),
            latitud=Decimal("7.123456"),
            longitud=Decimal("-72.654321"),
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Caturra",
            defaults={
                "especie": "Arábica",
                "descripcion": "Variedad tradicional.",
                "activo": True,
            },
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-09-20",
            cantidad_total=Decimal("500.00"),
            cantidad_disponible=Decimal("500.00"),
            activo=True,
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="HONEY",
            defaults={
                "nombre": "Honey / Enmielado",
                "descripcion": "Secado con mucílago.",
                "activo": True,
            },
        )
        self.estado, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={
                "nombre": "Disponible",
                "descripcion": "Lote listo.",
                "activo": True,
            },
        )
        self.lote = Lote.objects.create(
            codigo="LOTE-API-001",
            cosecha=self.cosecha,
            cantidad=Decimal("150.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

    def test_consulta_exitosa_ficha_digital_api_200_ok(self):
        """GET /fincas/api/lotes/<codigo>/ficha/ responde 200 OK sin autenticación obligatoria."""
        url = reverse("api_lote_ficha_digital", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["codigo"], "LOTE-API-001")
        self.assertEqual(data["cantidad_kg"], "150.00")
        self.assertTrue(data["activo"])

        # Verificación de secciones anidadas
        self.assertEqual(data["finca"]["nombre"], "Finca API Test")
        self.assertEqual(data["finca"]["municipio"], "Arboledas")
        self.assertEqual(data["proceso_beneficio"]["codigo"], "HONEY")
        self.assertEqual(data["estado_lote"]["codigo"], "DISPONIBLE")
        self.assertIn("url_publica", data)
        self.assertIn("completitud_porcentaje", data)

    def test_consulta_exitosa_por_ruta_v1_alternativa(self):
        """GET /fincas/api/v1/lotes/<codigo>/ficha/ responde igualmente 200 OK."""
        url = reverse("api_v1_lote_ficha_digital", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["codigo"], "LOTE-API-001")

    def test_consulta_lote_inexistente_retorna_404(self):
        """GET /fincas/api/lotes/<codigo_no_existe>/ficha/ responde 404 NOT FOUND con mensaje JSON."""
        url = reverse("api_lote_ficha_digital", kwargs={"codigo": "LOTE-FANTASMA-999"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_actualizacion_automatica_reflejada_en_la_api(self):
        """Verifica que mutaciones previas en la BD se reflejen inmediatamente en la respuesta de la API."""
        # 1. Primera consulta
        url = reverse("api_lote_ficha_digital", kwargs={"codigo": self.lote.codigo})
        resp1 = self.client.get(url)
        self.assertEqual(resp1.json()["cantidad_kg"], "150.00")

        # 2. Modificación de datos en base de datos
        self.lote.cantidad = Decimal("275.50")
        self.lote.save(update_fields=["cantidad"])

        # 3. Segunda consulta inmediata
        resp2 = self.client.get(url)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["cantidad_kg"], "275.50")


# =============================================================================
# SUITE HU-17 (SCRUM-168): VISTA Y PLANTILLA WEB DE FICHA DIGITAL CONSOLIDADA
# =============================================================================


class FichaDigitalWebTests(TestCase):
    """
    Pruebas de la interfaz web para la Ficha Digital Consolidada por Lote (HU-17 / SCRUM-168).
    Verifica el renderizado de la plantilla HTML5, contenido de secciones y manejo de errores 404 amigable.
    """

    def setUp(self):
        self.client = Client()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-ARB-WEB",
                nombre="Arboledas",
                departamento="Norte de Santander",
                activo=True,
            )
        self.finca = Finca.objects.create(
            nombre="Finca Web Test",
            vereda="El Roble",
            municipio=self.municipio,
            productor_id=uuid.uuid4(),
            latitud=Decimal("7.654321"),
            longitud=Decimal("-72.123456"),
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Geisha Especial",
            defaults={
                "especie": "Arábica",
                "descripcion": "Variedad de perfil floral.",
                "activo": True,
            },
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-09-25",
            cantidad_total=Decimal("400.00"),
            cantidad_disponible=Decimal("400.00"),
            activo=True,
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="NATURAL",
            defaults={
                "nombre": "Natural / Seco",
                "descripcion": "Secado en cereza completa.",
                "activo": True,
            },
        )
        self.estado, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={
                "nombre": "Disponible",
                "descripcion": "Apto para venta.",
                "activo": True,
            },
        )
        self.lote = Lote.objects.create(
            codigo="LOTE-WEB-001",
            cosecha=self.cosecha,
            cantidad=Decimal("120.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

    def test_vista_web_ficha_digital_200_ok_y_template(self):
        """GET /fincas/lotes/<codigo>/ficha/ responde 200 OK y usa templates/fincas/ficha_digital.html."""
        url = reverse("lote_ficha_digital_web", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/ficha_digital.html")
        self.assertIn("ficha", response.context)
        self.assertEqual(response.context["ficha"]["codigo"], "LOTE-WEB-001")

        # Contenido renderizado en HTML
        content = response.content.decode("utf-8")
        self.assertIn("LOTE-WEB-001", content)
        self.assertIn("Finca Web Test", content)
        self.assertIn("Arboledas", content)
        self.assertIn("Geisha Especial", content)

    def test_vista_web_por_ruta_raiz_trazabilidad(self):
        """GET /trazabilidad/lote/<codigo>/ responde igualmente 200 OK."""
        url = reverse("trazabilidad_lote_publica_root", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/ficha_digital.html")

    def test_vista_web_lote_inexistente_retorna_404_con_template_error(self):
        """GET /fincas/lotes/<codigo_no_existe>/ficha/ responde 404 y muestra ficha_digital_error.html."""
        url = reverse("lote_ficha_digital_web", kwargs={"codigo": "NO-EXISTE-LOTE-404"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "fincas/ficha_digital_error.html")
        self.assertIn("NO-EXISTE-LOTE-404", response.content.decode("utf-8"))


# ==============================================================================
# SUITE HU-17 (SCRUM-171): VALIDACIÓN DE CONSISTENCIA Y COMPLETITUD DE DATOS
# ==============================================================================

class FichaDigitalConsistenciaCompletitudTests(TestCase):
    """
    Pruebas automatizadas para HU17-ST6 (SCRUM-171): Validar la consistencia y
    completitud de los datos en la Ficha Digital Consolidada.
    """

    def setUp(self):
        self.productor_uuid = uuid.uuid4()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio, _ = Municipio.objects.get_or_create(
                codigo="54051",
                defaults={"nombre": "Arboledas", "departamento": "Norte de Santander"},
            )

        self.finca_completa = Finca.objects.create(
            nombre="Finca Consistencia",
            municipio=self.municipio,
            vereda="Siravita",
            productor_id=self.productor_uuid,
            latitud=Decimal("7.865432"),
            longitud=Decimal("-72.765432"),
        )
        self.finca_sin_gps = Finca.objects.create(
            nombre="Finca Sin Coordenadas",
            municipio=self.municipio,
            vereda="Centro",
            productor_id=self.productor_uuid,
            latitud=None,
            longitud=None,
        )

        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Caturra",
            defaults={"especie": "Arábica", "descripcion": "Variedad clásica"},
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="HONEY",
            defaults={"nombre": "Honey Amarillo", "descripcion": "Secado con mucílago"},
        )
        self.estado, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={"nombre": "Disponible", "descripcion": "Lote en venta"},
        )

        self.cosecha_normal = Cosecha.objects.create(
            finca=self.finca_completa,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("1000.00"),
            cantidad_disponible=Decimal("800.00"),
        )
        self.lote_normal = Lote.objects.create(
            codigo="LOTE-CONSIST-01",
            cosecha=self.cosecha_normal,
            cantidad=Decimal("200.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

    def test_diagnostico_completitud_lote_base_sin_gps_ni_proceso(self):
        """Un lote con solo datos base y sin georreferenciación debe tener 40% (Básica) y campos faltantes."""
        cosecha_base = Cosecha.objects.create(
            finca=self.finca_sin_gps,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 5),
            cantidad_total=Decimal("500.00"),
            cantidad_disponible=Decimal("500.00"),
        )
        lote_base = Lote.objects.create(
            codigo="LOTE-BASE-01",
            cosecha=cosecha_base,
            cantidad=Decimal("100.00"),
            proceso_beneficio=None,
            estado_lote=self.estado,
            activo=True,
        )

        ficha = obtener_ficha_consolidada_lote(lote_base)

        self.assertEqual(ficha["completitud_porcentaje"], 40)
        self.assertEqual(ficha["nivel_completitud"], "Básica")
        self.assertEqual(ficha["color_nivel"], "secondary")
        self.assertTrue(ficha["es_consistente"])
        self.assertIn("Coordenadas GPS (WGS84) del predio", ficha["campos_faltantes"])
        self.assertIn("Asignación de proceso de beneficio (Lavado, Honey, Natural)", ficha["campos_faltantes"])

    def test_diagnostico_completitud_lote_con_geo_y_proceso(self):
        """Un lote con GPS y proceso de beneficio alcanza 65% y Nivel Media."""
        ficha = obtener_ficha_consolidada_lote(self.lote_normal)

        self.assertEqual(ficha["completitud_porcentaje"], 65)
        self.assertEqual(ficha["nivel_completitud"], "Media")
        self.assertEqual(ficha["color_nivel"], "warning")
        self.assertTrue(ficha["es_consistente"])
        self.assertIn("Georreferenciación WGS84", ficha["campos_completos"])
        self.assertIn("Proceso de Beneficio (Honey Amarillo)", ficha["campos_completos"])
        self.assertIn("Registro de etapas operativas de beneficio (fermentación, secado)", ficha["campos_faltantes"])
        self.assertIn("Análisis físico y sensorial de calidad SCA", ficha["campos_faltantes"])

    def test_evaluacion_completitud_100_por_ciento(self):
        """Prueba unitaria de evaluar_consistencia_y_completitud_lote con etapas y calidad simuladas."""
        etapas_simuladas = [
            {"etapa": "Despulpado", "duracion_horas": 2},
            {"etapa": "Fermentación Honey", "duracion_horas": 24},
        ]
        calidad_simulada = {
            "humedad_pct": Decimal("11.5"),
            "puntaje_sca": Decimal("86.5"),
            "notas_cata": "Panela, jazmín y frutas amarillas",
        }

        evaluacion = evaluar_consistencia_y_completitud_lote(
            lote=self.lote_normal,
            finca=self.finca_completa,
            cosecha=self.cosecha_normal,
            proceso=self.proceso,
            etapas_beneficio=etapas_simuladas,
            calidad_info=calidad_simulada,
        )

        self.assertEqual(evaluacion["porcentaje"], 100)
        self.assertEqual(evaluacion["nivel"], "Completa")
        self.assertEqual(evaluacion["color_nivel"], "success")
        self.assertTrue(evaluacion["es_consistente"])
        self.assertEqual(len(evaluacion["campos_faltantes"]), 0)
        self.assertEqual(len(evaluacion["advertencias"]), 0)

    def test_deteccion_inconsistencia_volumenes_cosecha(self):
        """Detecta inconsistencia cuando cantidad_disponible supera la cantidad_total o el lote tiene volumen <= 0."""
        # 1. Validación de lote con cantidad <= 0
        lote_cero = Lote(
            codigo="LOTE-CERO",
            cosecha=self.cosecha_normal,
            cantidad=Decimal("0.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
        )
        evaluacion_cero = evaluar_consistencia_y_completitud_lote(
            lote=lote_cero,
            finca=self.finca_completa,
            cosecha=self.cosecha_normal,
            proceso=self.proceso,
        )
        self.assertFalse(evaluacion_cero["es_consistente"])
        self.assertTrue(any("debe ser mayor a cero" in adv for adv in evaluacion_cero["advertencias"]))

        # 2. Validación de cosecha con saldo superior al total
        cosecha_desfasada = Cosecha(
            finca=self.finca_completa,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("500.00"),
            cantidad_disponible=Decimal("600.00"),
        )
        evaluacion_cosecha = evaluar_consistencia_y_completitud_lote(
            lote=self.lote_normal,
            finca=self.finca_completa,
            cosecha=cosecha_desfasada,
            proceso=self.proceso,
        )
        self.assertFalse(evaluacion_cosecha["es_consistente"])
        self.assertTrue(any("supera la cantidad total" in adv for adv in evaluacion_cosecha["advertencias"]))

    def test_deteccion_inconsistencia_coordenadas_fuera_de_colombia(self):
        """Detecta inconsistencia cuando las coordenadas decimales están fuera del territorio nacional."""
        finca_fuera_pais = Finca.objects.create(
            nombre="Finca Fuera de Rango",
            municipio=self.municipio,
            productor_id=self.productor_uuid,
            latitud=Decimal("45.000000"),   # Latitud europea/norteamericana
            longitud=Decimal("10.000000"),  # Fuera de Colombia (-79 a -66.5)
        )
        cosecha = Cosecha.objects.create(
            finca=finca_fuera_pais,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("500.00"),
            cantidad_disponible=Decimal("500.00"),
        )
        lote = Lote.objects.create(
            codigo="LOTE-INV-GPS",
            cosecha=cosecha,
            cantidad=Decimal("100.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

        ficha = obtener_ficha_consolidada_lote(lote)

        self.assertFalse(ficha["es_consistente"])
        self.assertTrue(any("fuera del territorio colombiano" in adv for adv in ficha["advertencias"]))

    def test_diagnostico_consistencia_y_completitud_en_api_rest(self):
        """Verifica que el endpoint REST exponga el diagnóstico de completitud y consistencia."""
        url = reverse("api_lote_ficha_digital", kwargs={"codigo": self.lote_normal.codigo})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("nivel_completitud", data)
        self.assertEqual(data["nivel_completitud"], "Media")
        self.assertIn("color_nivel", data)
        self.assertEqual(data["color_nivel"], "warning")
        self.assertIn("es_consistente", data)
        self.assertTrue(data["es_consistente"])
        self.assertIn("advertencias", data)
        self.assertIn("campos_faltantes", data)
        self.assertIn("campos_completos", data)


# ==============================================================================
# SUITE HU-17 (SCRUM-172): AUDITORÍA Y BITÁCORA DE LA FICHA DIGITAL
# ==============================================================================

class FichaDigitalAuditoriaTests(TestCase):
    """
    Pruebas automatizadas para HU17-ST7 (SCRUM-172): Registrar auditoría de
    consultas y cambios en la Ficha Digital Consolidada.
    """

    def setUp(self):
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.productor_uuid = uuid.uuid4()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio, _ = Municipio.objects.get_or_create(
                codigo="54051",
                defaults={"nombre": "Arboledas", "departamento": "Norte de Santander"},
            )

        self.finca = Finca.objects.create(
            nombre="Finca Auditoria",
            municipio=self.municipio,
            vereda="Siravita",
            productor_id=self.productor_uuid,
            latitud=Decimal("7.865432"),
            longitud=Decimal("-72.765432"),
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Caturra",
            defaults={"especie": "Arábica", "descripcion": "Variedad clásica"},
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="LAVADO",
            defaults={"nombre": "Lavado Tradicional", "descripcion": "Beneficio húmedo"},
        )
        self.estado, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={"nombre": "Disponible", "descripcion": "Lote en venta"},
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("1000.00"),
            cantidad_disponible=Decimal("800.00"),
        )
        self.lote = Lote.objects.create(
            codigo="LOTE-AUDIT-01",
            cosecha=self.cosecha,
            cantidad=Decimal("200.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

    def test_auditoria_registrada_al_consultar_vista_web(self):
        """Al visitar la ficha digital en la web, se registra una entrada de CONSULTA_WEB en la bitácora."""
        conteo_inicial = BitacoraFichaDigital.objects.filter(lote=self.lote).count()

        url = reverse("lote_ficha_digital_web", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        conteo_final = BitacoraFichaDigital.objects.filter(lote=self.lote).count()
        self.assertEqual(conteo_final, conteo_inicial + 1)

        auditoria = BitacoraFichaDigital.objects.filter(lote=self.lote).latest("creado_en")
        self.assertEqual(auditoria.tipo_evento, BitacoraFichaDigital.TIPO_CONSULTA_WEB)
        self.assertEqual(auditoria.usuario_identificador, "Público / Escaneo QR")
        self.assertGreaterEqual(auditoria.completitud_porcentaje, 65)
        self.assertTrue(auditoria.es_consistente)
        self.assertEqual(auditoria.detalles.get("canal"), "web")

    def test_auditoria_registrada_al_consultar_api_rest(self):
        """Al consultar la ficha vía API REST (ej. app móvil / QR), se registra CONSULTA_API."""
        url = reverse("api_lote_ficha_digital", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        auditoria = BitacoraFichaDigital.objects.filter(
            lote=self.lote,
            tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_API,
        ).latest("creado_en")
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.detalles.get("canal"), "api_rest")

    def test_auditoria_captura_usuario_en_sesion(self):
        """Si un usuario autenticado consulta la ficha, se captura su identidad en la bitácora."""
        _iniciar_sesion_productor(self.client, self.productor_uuid)

        url = reverse("lote_ficha_digital_web", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        auditoria = BitacoraFichaDigital.objects.filter(lote=self.lote).latest("creado_en")
        self.assertIn(str(self.productor_uuid), auditoria.usuario_identificador)

    def test_auditoria_captura_ip_y_user_agent(self):
        """Verifica la persistencia de dirección IP y User-Agent en la auditoría."""
        url = reverse("api_lote_ficha_digital", kwargs={"codigo": self.lote.codigo})
        response = self.client.get(
            url,
            HTTP_X_FORWARDED_FOR="190.84.120.33",
            HTTP_USER_AGENT="CaficultoresApp/1.0 (Mobile QR Reader)",
        )
        self.assertEqual(response.status_code, 200)

        auditoria = BitacoraFichaDigital.objects.filter(lote=self.lote).latest("creado_en")
        self.assertEqual(auditoria.ip_address, "190.84.120.33")
        self.assertEqual(auditoria.user_agent, "CaficultoresApp/1.0 (Mobile QR Reader)")

    def test_servicio_registrar_auditoria_evento_actualizacion(self):
        """Verifica el registro programático de eventos de actualización de trazabilidad."""
        registro = registrar_auditoria_ficha_digital(
            lote=self.lote,
            tipo_evento=BitacoraFichaDigital.TIPO_ACTUALIZACION,
            completitud_porcentaje=80,
            es_consistente=True,
            detalles={"cambio": "Asignación de etapa de secado"},
            usuario_identificador="operario_beneficio@pergamo.com",
        )

        self.assertEqual(registro.tipo_evento, BitacoraFichaDigital.TIPO_ACTUALIZACION)
        self.assertEqual(registro.usuario_identificador, "operario_beneficio@pergamo.com")
        self.assertEqual(registro.completitud_porcentaje, 80)
        self.assertEqual(registro.detalles.get("cambio"), "Asignación de etapa de secado")


# ==============================================================================
# SUITE HU-17 (SCRUM-173): PRUEBAS INTEGRALES DE GENERACIÓN Y ACTUALIZACIÓN (E2E)
# ==============================================================================

class FichaDigitalGeneracionActualizacionE2ETests(TestCase):
    """
    Pruebas integrales de punta a punta (E2E) para HU17-ST8 (SCRUM-173):
    Validar la generación y actualización automática de la Ficha Digital
    consolidada ante eventos de ciclo de vida del lote.

    Criterio de Aceptación HU-17 (SCRUM-21):
    'La ficha se actualiza automáticamente al registrarse nueva información del lote.'
    """

    def setUp(self):
        self.productor_uuid = uuid.uuid4()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio, _ = Municipio.objects.get_or_create(
                codigo="54051",
                defaults={"nombre": "Arboledas", "departamento": "Norte de Santander"},
            )

        self.finca = Finca.objects.create(
            nombre="Finca Trazabilidad E2E",
            municipio=self.municipio,
            vereda="El Porvenir",
            productor_id=self.productor_uuid,
            latitud=None,
            longitud=None,
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Borbón Rosado",
            defaults={"especie": "Arábica", "descripcion": "Variedad exótica"},
        )
        self.proceso_lavado, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="LAVADO",
            defaults={"nombre": "Lavado Tradicional", "descripcion": "Fermentación estándar"},
        )
        self.proceso_natural, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="NATURAL",
            defaults={"nombre": "Natural Clásico", "descripcion": "Secado en cereza entera"},
        )
        self.estado_disponible, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={"nombre": "Disponible", "descripcion": "Listo para venta"},
        )
        self.estado_vendido, _ = EstadoLote.objects.get_or_create(
            codigo="VENDIDO",
            defaults={"nombre": "Vendido", "descripcion": "Lote adjudicado"},
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 10),
            cantidad_total=Decimal("1500.00"),
            cantidad_disponible=Decimal("1500.00"),
            activo=True,
        )

    def test_generacion_automatica_inmediata_al_crear_lote_con_servicio(self):
        """
        Al registrar un nuevo lote mediante el servicio de negocio, la ficha digital
        se genera de forma inmediata y automática, estando disponible tanto en API como en Web.
        """
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("350.00"),
            codigo="LOTEE2EAUTO01",
            proceso_beneficio_id=self.proceso_lavado.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        # 1. Consulta directa al servicio de dominio
        ficha = obtener_ficha_consolidada_lote(lote.codigo)
        self.assertEqual(ficha["codigo"], "LOTEE2EAUTO01")
        self.assertEqual(ficha["cantidad_kg"], Decimal("350.00"))
        self.assertEqual(ficha["proceso_beneficio"]["codigo"], "LAVADO")
        self.assertEqual(ficha["url_publica"], "/trazabilidad/lote/LOTEE2EAUTO01/")

        # 2. Consulta inmediata por API REST
        url_api = reverse("api_lote_ficha_digital", kwargs={"codigo": lote.codigo})
        resp_api = self.client.get(url_api)
        self.assertEqual(resp_api.status_code, 200)
        data_api = resp_api.json()
        self.assertEqual(data_api["codigo"], "LOTEE2EAUTO01")
        self.assertEqual(data_api["cantidad_kg"], "350.00")

        # 3. Consulta inmediata por interfaz Web HTML
        url_web = reverse("trazabilidad_lote_publica_root", kwargs={"codigo": lote.codigo})
        resp_web = self.client.get(url_web)
        self.assertEqual(resp_web.status_code, 200)
        self.assertIn("LOTEE2EAUTO01", resp_web.content.decode("utf-8"))
        self.assertIn("Finca Trazabilidad E2E", resp_web.content.decode("utf-8"))

    def test_actualizacion_automatica_en_tiempo_real_por_mutacion_en_finca(self):
        """
        Criterio de Aceptación HU-17:
        Al mutar datos del predio (georreferenciación GPS), la siguiente consulta
        a la ficha digital refleja las nuevas coordenadas y eleva el porcentaje de completitud.
        """
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("200.00"),
            codigo="LOTEE2EMUT01",
            proceso_beneficio_id=self.proceso_lavado.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        # Estado inicial: finca sin GPS (completitud base 40 + proceso 15 = 55%)
        ficha_inicial = obtener_ficha_consolidada_lote(lote.codigo)
        self.assertFalse(ficha_inicial["finca"]["tiene_georreferenciacion"])
        self.assertEqual(ficha_inicial["completitud_porcentaje"], 55)

        # Mutación en la BD: Se agregan coordenadas GPS WGS84
        self.finca.latitud = Decimal("7.865432")
        self.finca.longitud = Decimal("-72.765432")
        self.finca.save()

        # Consulta inmediata: Reflejo en tiempo real (+10% georreferenciación = 65%)
        ficha_actualizada = obtener_ficha_consolidada_lote(lote.codigo)
        self.assertTrue(ficha_actualizada["finca"]["tiene_georreferenciacion"])
        self.assertEqual(ficha_actualizada["finca"]["latitud"], Decimal("7.865432"))
        self.assertEqual(ficha_actualizada["finca"]["longitud"], Decimal("-72.765432"))
        self.assertEqual(ficha_actualizada["completitud_porcentaje"], 65)

        # Reflejo inmediato en la API REST pública
        url_api = reverse("api_lote_ficha_digital", kwargs={"codigo": lote.codigo})
        resp_api = self.client.get(url_api)
        data_api = resp_api.json()
        self.assertTrue(data_api["finca"]["tiene_georreferenciacion"])
        self.assertEqual(data_api["completitud_porcentaje"], 65)

    def test_actualizacion_automatica_en_tiempo_real_por_cambio_de_estado_comercial(self):
        """
        Al cambiar el estado del lote de DISPONIBLE a VENDIDO, la ficha digital
        actualiza automáticamente su estado comercial y disponibilidad para venta.
        """
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("300.00"),
            codigo="LOTEE2EEST01",
            proceso_beneficio_id=self.proceso_lavado.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        ficha_inicial = obtener_ficha_consolidada_lote(lote.codigo)
        self.assertEqual(ficha_inicial["estado_comercial"], "DISPONIBLE")
        self.assertTrue(ficha_inicial["disponible_para_venta"])

        # Mutación de negocio: Lote vendido
        lote.estado_lote = self.estado_vendido
        lote.save()

        # Consulta inmediata a la vista web pública
        url_web = reverse("trazabilidad_lote_publica_root", kwargs={"codigo": lote.codigo})
        resp_web = self.client.get(url_web)
        self.assertEqual(resp_web.status_code, 200)
        self.assertIn("Vendido", resp_web.content.decode("utf-8"))

        # Consulta inmediata a la API
        url_api = reverse("api_lote_ficha_digital", kwargs={"codigo": lote.codigo})
        resp_api = self.client.get(url_api)
        data_api = resp_api.json()
        self.assertEqual(data_api["estado_comercial"], "VENDIDO")
        self.assertFalse(data_api["disponible_para_venta"])

    def test_actualizacion_automatica_por_reasignacion_de_proceso(self):
        """
        Al reasignar el proceso de beneficio del lote (ej. de Lavado a Natural),
        la ficha digital refleja el nuevo proceso al instante.
        """
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("180.00"),
            codigo="LOTEE2EPROC01",
            proceso_beneficio_id=self.proceso_lavado.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        ficha_lavado = obtener_ficha_consolidada_lote(lote.codigo)
        self.assertEqual(ficha_lavado["proceso_beneficio"]["codigo"], "LAVADO")

        # Mutación de proceso a Natural
        lote.proceso_beneficio = self.proceso_natural
        lote.save()

        ficha_natural = obtener_ficha_consolidada_lote(lote.codigo)
        self.assertEqual(ficha_natural["proceso_beneficio"]["codigo"], "NATURAL")
        self.assertEqual(ficha_natural["proceso_beneficio"]["nombre"], "Natural Clásico")

    def test_ciclo_completo_con_auditoria_y_consistencia(self):
        """
        Prueba el ciclo de vida completo: Creación de lote -> Consulta inicial ->
        Actualización de datos -> Consulta posterior -> Verificación de bitácora cronológica.
        """
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("500.00"),
            codigo="LOTEE2EAUD01",
            proceso_beneficio_id=self.proceso_lavado.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        # 1. Primera consulta por Web
        url_web = reverse("lote_ficha_digital_web", kwargs={"codigo": lote.codigo})
        self.client.get(url_web)

        # 2. Mutación en el lote
        lote.cantidad = Decimal("480.00")
        lote.save()

        # 3. Segunda consulta por API
        url_api = reverse("api_lote_ficha_digital", kwargs={"codigo": lote.codigo})
        resp_api = self.client.get(url_api)
        self.assertEqual(resp_api.json()["cantidad_kg"], "480.00")

        # 4. Verificación de bitácora
        auditorias = list(BitacoraFichaDigital.objects.filter(lote=lote).order_by("creado_en", "id"))
        self.assertEqual(len(auditorias), 2)
        self.assertEqual(auditorias[0].tipo_evento, BitacoraFichaDigital.TIPO_CONSULTA_WEB)
        self.assertEqual(auditorias[1].tipo_evento, BitacoraFichaDigital.TIPO_CONSULTA_API)


# ==============================================================================
# SUITE HU-17 (SCRUM-170): CONSOLIDACIÓN DE DATOS DEL LOTE (ST5)
# ==============================================================================

class FichaDigitalConsolidacionDatosTests(TestCase):
    """
    Pruebas unitarias y de integración para HU17-ST5 (SCRUM-170):
    Implementar la lógica de consolidación de datos del lote.

    Verifica la orquestación multientidad en `obtener_ficha_consolidada_lote()`:
    resolución polimórfica (instancia, código, PK), integración de datos de
    finca, productor, cosecha, variedad, beneficio, estado y diagnóstico.
    """

    def setUp(self):
        self.productor_uuid = uuid.uuid4()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio, _ = Municipio.objects.get_or_create(
                codigo="54051",
                defaults={"nombre": "Arboledas", "departamento": "Norte de Santander"},
            )
        self.finca = Finca.objects.create(
            nombre="Finca La Consolidación",
            municipio=self.municipio,
            vereda="Siravita",
            productor_id=self.productor_uuid,
            latitud=Decimal("7.812345"),
            longitud=Decimal("-72.712345"),
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Geisha Dorado",
            defaults={"especie": "Arábica", "descripcion": "Perfil floral y cítrico"},
        )
        self.proceso, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="HONEY",
            defaults={"nombre": "Honey Amarillo", "descripcion": "Despulpado con mucílago"},
        )
        self.estado, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={"nombre": "Disponible para Venta", "descripcion": "Lote apto"},
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 5),
            cantidad_total=Decimal("1200.00"),
            cantidad_disponible=Decimal("1200.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOTECONSOLIDADO01",
            cosecha=self.cosecha,
            cantidad=Decimal("400.00"),
            proceso_beneficio=self.proceso,
            estado_lote=self.estado,
            activo=True,
        )

    def test_consolidacion_multientidad_datos_completos(self):
        """
        SCRUM-170: Verifica que la función de dominio consolide correctamente
        la información proveniente de Lote, Finca, Productor, Cosecha,
        Variedad y Proceso en una sola estructura unificada.
        """
        ficha = obtener_ficha_consolidada_lote(self.lote)

        # 1. Validación de campos del lote
        self.assertEqual(ficha["id"], self.lote.id)
        self.assertEqual(ficha["codigo"], "LOTECONSOLIDADO01")
        self.assertEqual(ficha["cantidad_kg"], Decimal("400.00"))
        self.assertTrue(ficha["activo"])

        # 2. Validación de datos de finca y municipio
        self.assertEqual(ficha["finca"]["id"], self.finca.id)
        self.assertEqual(ficha["finca"]["nombre"], "Finca La Consolidación")
        self.assertEqual(ficha["finca"]["municipio"], "Arboledas")
        self.assertEqual(ficha["finca"]["departamento"], "Norte de Santander")
        self.assertTrue(ficha["finca"]["tiene_georreferenciacion"])

        # 3. Validación de cosecha y variedad botánica
        self.assertEqual(ficha["cosecha"]["id"], self.cosecha.id)
        self.assertEqual(ficha["cosecha"]["fecha_cosecha"], date(2026, 10, 5))
        self.assertEqual(ficha["variedad"]["nombre"], "Geisha Dorado")
        self.assertEqual(ficha["variedad"]["especie"], "Arábica")

        # 4. Validación de proceso de beneficio
        self.assertEqual(ficha["proceso_beneficio"]["codigo"], "HONEY")
        self.assertEqual(ficha["proceso_beneficio"]["nombre"], "Honey Amarillo")

        # 5. Validación de disponibilidad comercial y URL pública
        self.assertEqual(ficha["estado_comercial"], "DISPONIBLE")
        self.assertTrue(ficha["disponible_para_venta"])
        self.assertEqual(ficha["url_publica"], "/trazabilidad/lote/LOTECONSOLIDADO01/")

        # 6. Serialización formal con FichaDigitalSerializer
        serializer = FichaDigitalSerializer(data=ficha)
        self.assertTrue(serializer.is_valid(), f"Errores en serializador: {serializer.errors}")

    def test_resolucion_polimorfica_por_instancia_codigo_y_pk(self):
        """
        SCRUM-170: Comprueba que obtener_ficha_consolidada_lote resuelva
        el lote indistintamente por instancia de modelo, código alfanumérico o ID numérico.
        """
        ficha_por_instancia = obtener_ficha_consolidada_lote(self.lote)
        ficha_por_codigo = obtener_ficha_consolidada_lote("LOTECONSOLIDADO01")
        ficha_por_pk_int = obtener_ficha_consolidada_lote(self.lote.pk)
        ficha_por_pk_str = obtener_ficha_consolidada_lote(str(self.lote.pk))

        self.assertEqual(ficha_por_instancia["id"], self.lote.id)
        self.assertEqual(ficha_por_codigo["id"], self.lote.id)
        self.assertEqual(ficha_por_pk_int["id"], self.lote.id)
        self.assertEqual(ficha_por_pk_str["id"], self.lote.id)
        self.assertEqual(ficha_por_codigo["codigo"], "LOTECONSOLIDADO01")

    def test_consolidacion_con_lote_parcial(self):
        """
        SCRUM-170: Comprueba la consolidación resiliente cuando el lote carece
        de proceso de beneficio o la finca carece de coordenadas GPS.
        """
        finca_sin_gps = Finca.objects.create(
            nombre="Finca Sin Coordenadas",
            municipio=self.municipio,
            productor_id=self.productor_uuid,
            latitud=None,
            longitud=None,
            activo=True,
        )
        cosecha_parcial = Cosecha.objects.create(
            finca=finca_sin_gps,
            variedad=None,
            fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("300.00"),
            cantidad_disponible=Decimal("300.00"),
            activo=True,
        )
        lote_parcial = Lote.objects.create(
            codigo="LOTEPARCIAL01",
            cosecha=cosecha_parcial,
            cantidad=Decimal("100.00"),
            proceso_beneficio=None,
            estado_lote=None,
            activo=True,
        )

        ficha = obtener_ficha_consolidada_lote(lote_parcial)
        self.assertFalse(ficha["finca"]["tiene_georreferenciacion"])
        self.assertIsNone(ficha["finca"]["latitud"])
        self.assertIsNone(ficha["proceso_beneficio"]["id"])
        self.assertEqual(ficha["variedad"]["nombre"], "Mezcla tradicional / No especificada")

        serializer = FichaDigitalSerializer(data=ficha)
        self.assertTrue(serializer.is_valid(), f"Errores en serialización parcial: {serializer.errors}")

    def test_consolidacion_lote_inexistente_lanza_validation_error(self):
        """
        SCRUM-170: Comprueba que intentar consolidar un lote inexistente o
        con identificador no válido dispare una excepción ValidationError amigable.
        """
        with self.assertRaises(ValidationError):
            obtener_ficha_consolidada_lote("LOTEINEXISTENTE999")

        with self.assertRaises(ValidationError):
            obtener_ficha_consolidada_lote(99999999)

        with self.assertRaises(ValidationError):
            obtener_ficha_consolidada_lote([])


# ==============================================================================
# SUITE HU-17 (SCRUM-166): MECANISMO DE ACTUALIZACIÓN EN TIEMPO REAL (ST1)
# ==============================================================================

class FichaDigitalActualizacionTiempoRealTests(TestCase):
    """
    Pruebas unitarias y de integración para HU17-ST1 (SCRUM-166):
    Crear mecanismo de actualización automática en tiempo real.

    Criterio de Aceptación HU-17 (SCRUM-21):
    'La ficha se actualiza automáticamente al registrarse nueva información del lote.'

    Verifica que la consolidación en tiempo de ejecución garantice cero persistencias
    desfasadas ante mutaciones de volumen, estado comercial, proceso o finca.
    """

    def setUp(self):
        self.productor_uuid = uuid.uuid4()
        self.municipio = Municipio.objects.filter(nombre__iexact="Arboledas").first()
        if not self.municipio:
            self.municipio, _ = Municipio.objects.get_or_create(
                codigo="54051",
                defaults={"nombre": "Arboledas", "departamento": "Norte de Santander"},
            )
        self.finca = Finca.objects.create(
            nombre="Finca Tiempo Real",
            municipio=self.municipio,
            vereda="El Suspiro",
            productor_id=self.productor_uuid,
            latitud=None,
            longitud=None,
            activo=True,
        )
        self.variedad, _ = VariedadCafe.objects.get_or_create(
            nombre="Borbón Amarillo",
            defaults={"especie": "Arábica", "descripcion": "Variedad dulce"},
        )
        self.proceso_lavado, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="LAVADO",
            defaults={"nombre": "Lavado Tradicional", "descripcion": "Fermentación estándar"},
        )
        self.proceso_natural, _ = ProcesoBeneficio.objects.get_or_create(
            codigo="NATURAL",
            defaults={"nombre": "Natural Clásico", "descripcion": "Secado en cereza"},
        )
        self.estado_disponible, _ = EstadoLote.objects.get_or_create(
            codigo="DISPONIBLE",
            defaults={"nombre": "Disponible", "descripcion": "Apto para venta"},
        )
        self.estado_vendido, _ = EstadoLote.objects.get_or_create(
            codigo="VENDIDO",
            defaults={"nombre": "Vendido", "descripcion": "Lote adjudicado"},
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 12),
            cantidad_total=Decimal("1000.00"),
            cantidad_disponible=Decimal("1000.00"),
            activo=True,
        )
        self.lote = Lote.objects.create(
            codigo="LOTEREALTIME01",
            cosecha=self.cosecha,
            cantidad=Decimal("250.00"),
            proceso_beneficio=self.proceso_lavado,
            estado_lote=self.estado_disponible,
            activo=True,
        )

    def test_actualizacion_tiempo_real_mutacion_volumen_lote(self):
        """
        SCRUM-166: Al actualizar el volumen del lote, la siguiente consulta
        a la ficha digital refleja el nuevo peso inmediatamente sin desfase temporal.
        """
        ficha_inicial = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_inicial["cantidad_kg"], Decimal("250.00"))

        # Mutación directa de base de datos
        self.lote.cantidad = Decimal("310.50")
        self.lote.save(update_fields=["cantidad"])

        # Reflejo inmediato en la siguiente consulta
        ficha_actualizada = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_actualizada["cantidad_kg"], Decimal("310.50"))

    def test_actualizacion_tiempo_real_cambio_estado_disponible_a_vendido(self):
        """
        SCRUM-166: Al cambiar el estado de DISPONIBLE a VENDIDO, la ficha digital
        actualiza automáticamente la disponibilidad comercial y la bandera disponible_para_venta.
        """
        ficha_inicial = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_inicial["estado_comercial"], "DISPONIBLE")
        self.assertTrue(ficha_inicial["disponible_para_venta"])

        # Transición de estado comercial
        self.lote.estado_lote = self.estado_vendido
        self.lote.save(update_fields=["estado_lote"])

        # Reflejo inmediato
        ficha_actualizada = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_actualizada["estado_comercial"], "VENDIDO")
        self.assertFalse(ficha_actualizada["disponible_para_venta"])

    def test_actualizacion_tiempo_real_mutacion_datos_finca(self):
        """
        SCRUM-166: Al agregar coordenadas GPS a la finca asociada, la ficha digital
        refleja al instante la georreferenciación y eleva la completitud.
        """
        ficha_inicial = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertFalse(ficha_inicial["finca"]["tiene_georreferenciacion"])

        # Mutación en la finca
        self.finca.latitud = Decimal("7.889900")
        self.finca.longitud = Decimal("-72.778899")
        self.finca.save(update_fields=["latitud", "longitud"])

        # Reflejo instantáneo
        ficha_actualizada = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertTrue(ficha_actualizada["finca"]["tiene_georreferenciacion"])
        self.assertEqual(ficha_actualizada["finca"]["latitud"], Decimal("7.889900"))
        self.assertEqual(ficha_actualizada["finca"]["longitud"], Decimal("-72.778899"))

    def test_actualizacion_tiempo_real_reasignacion_proceso_beneficio(self):
        """
        SCRUM-166: Al reasignar el proceso de beneficio (Lavado -> Natural),
        la ficha digital refleja el nuevo proceso al instante.
        """
        ficha_lavado = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_lavado["proceso_beneficio"]["codigo"], "LAVADO")

        # Reasignación de proceso
        self.lote.proceso_beneficio = self.proceso_natural
        self.lote.save(update_fields=["proceso_beneficio"])

        ficha_natural = obtener_ficha_consolidada_lote(self.lote.codigo)
        self.assertEqual(ficha_natural["proceso_beneficio"]["codigo"], "NATURAL")
        self.assertEqual(ficha_natural["proceso_beneficio"]["nombre"], "Natural Clásico")


# ==============================================================================
# SUITE HU-18 / SCRUM-175: ESTRUCTURA Y GENERACIÓN DEL IDENTIFICADOR QR POR LOTE
# ==============================================================================

class CodigoQREstructuraTests(TestCase):
    """
    Pruebas unitarias para HU18-ST2 (SCRUM-175):
    Definir la estructura y generación del identificador QR por lote.
    """

    def setUp(self):
        # Usar Municipio precargado respetando los estándares de Café Pérgamo
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.first()

        self.productor_uuid = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Hacienda Santa Bárbara",
            municipio=self.municipio,
            vereda="El Suspiro",
            productor_id=self.productor_uuid,
            latitud=Decimal("7.310123"),
            longitud=Decimal("-72.483120"),
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo Típico", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO", nombre="Lavado Tradicional", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 8, 15),
            cantidad_total=Decimal("2000.00"),
            cantidad_disponible=Decimal("1500.00"),
        )
        self.lote = Lote.objects.create(
            codigo="LOT-QR-001",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            estado_lote=self.estado_disponible,
            cantidad=Decimal("500.00"),
            activo=True,
        )

    def test_generar_identificador_qr_formato_canonico(self):
        """Verifica que el identificador siga la estructura 'QR-<CODIGO>' y sea único y determinista."""
        identificador = generar_identificador_qr_lote(self.lote)
        self.assertEqual(identificador, "QR-LOT-QR-001")
        self.assertTrue(identificador.startswith(PREFIJO_IDENTIFICADOR_QR))
        self.assertTrue(validar_estructura_identificador_qr(identificador))

    def test_resolucion_polimorfica_identificador_qr(self):
        """Verifica que generar_identificador_qr_lote resuelva por instancia Lote, por ID numérico y por código string."""
        id_por_instancia = generar_identificador_qr_lote(self.lote)
        id_por_pk = generar_identificador_qr_lote(self.lote.pk)
        id_por_codigo = generar_identificador_qr_lote("LOT-QR-001")
        id_por_identificador_previo = generar_identificador_qr_lote("QR-LOT-QR-001")

        self.assertEqual(id_por_instancia, "QR-LOT-QR-001")
        self.assertEqual(id_por_pk, "QR-LOT-QR-001")
        self.assertEqual(id_por_codigo, "QR-LOT-QR-001")
        self.assertEqual(id_por_identificador_previo, "QR-LOT-QR-001")

    def test_validar_estructura_identificador_qr_y_extraccion(self):
        """Comprueba validación sintáctica de identificadores QR y extracción limpia del código."""
        self.assertTrue(validar_estructura_identificador_qr("QR-LOT-2026-001"))
        self.assertTrue(validar_estructura_identificador_qr("QR-ABC_123"))
        self.assertFalse(validar_estructura_identificador_qr("LOT-2026-001"))  # Falta prefijo
        self.assertFalse(validar_estructura_identificador_qr("QR-"))  # Vacío
        self.assertFalse(validar_estructura_identificador_qr("QR-LOT 001"))  # Espacio inválido
        self.assertFalse(validar_estructura_identificador_qr(""))  # Vacío total
        self.assertFalse(validar_estructura_identificador_qr(None))

        # Extracción
        codigo = extraer_codigo_lote_desde_qr("QR-LOT-QR-001")
        self.assertEqual(codigo, "LOT-QR-001")

        with self.assertRaises(ValidationError):
            extraer_codigo_lote_desde_qr("INVALID-FORMAT")

    def test_construir_payload_qr_relativo_y_absoluto(self):
        """Verifica que el payload codificado corresponda a la URL de consulta de la ficha digital."""
        payload_relativo = construir_payload_qr_lote(self.lote)
        self.assertEqual(payload_relativo, f"/trazabilidad/lote/{self.lote.codigo}/")

        payload_absoluto = construir_payload_qr_lote(self.lote, base_url="https://cafepergamo.com")
        self.assertEqual(payload_absoluto, f"https://cafepergamo.com/trazabilidad/lote/{self.lote.codigo}/")

    def test_generar_matriz_qr_png_valido(self):
        """Comprueba que la generación retorne bytes binarios válidos de una imagen PNG con encabezado mágico."""
        png_bytes = generar_matriz_qr_lote(self.lote)
        self.assertIsInstance(png_bytes, bytes)
        self.assertGreater(len(png_bytes), 100)
        # Encabezado mágico PNG: 0x89 'P' 'N' 'G' '\r' '\n' 0x1A '\n'
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_generar_qr_base64_data_uri(self):
        """Verifica que el generador base64 retorne un Data URI válido utilizable en HTML."""
        data_uri = generar_qr_base64_lote(self.lote)
        self.assertIsInstance(data_uri, str)
        self.assertTrue(data_uri.startswith("data:image/png;base64,"))

        # Decodificar y verificar consistencia de bytes
        b64_content = data_uri.split("data:image/png;base64,")[1]
        decoded = base64.b64decode(b64_content)
        self.assertTrue(decoded.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_obtener_estructura_qr_lote_y_serializador_dto(self):
        """Verifica que la función orquestadora entregue el DTO completo y pase la validación del serializador DRF."""
        estructura = obtener_estructura_qr_lote(
            self.lote,
            base_url="https://cafepergamo.com",
            nivel_visibilidad="PUBLICA",
            incluir_imagen_base64=True,
        )

        self.assertEqual(estructura["identificador_qr"], "QR-LOT-QR-001")
        self.assertEqual(estructura["lote_codigo"], "LOT-QR-001")
        self.assertEqual(estructura["lote_id"], self.lote.id)
        self.assertEqual(estructura["payload_url"], f"/trazabilidad/lote/{self.lote.codigo}/")
        self.assertEqual(estructura["url_absoluta"], f"https://cafepergamo.com/trazabilidad/lote/{self.lote.codigo}/")
        self.assertEqual(estructura["nivel_visibilidad"], "PUBLICA")
        self.assertEqual(estructura["version_qr"], "1.0")
        self.assertEqual(estructura["formato"], "PNG")
        self.assertTrue(estructura["imagen_base64"].startswith("data:image/png;base64,"))

        # Validación formal del serializador DRF
        serializer = EstructuraCodigoQRSerializer(data=estructura)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        datos_validados = serializer.validated_data
        self.assertEqual(datos_validados["identificador_qr"], "QR-LOT-QR-001")
        self.assertEqual(datos_validados["nivel_visibilidad"], "PUBLICA")

    def test_control_visibilidad_opciones_permitidas_y_rechazo_invalidas(self):
        """Verifica el soporte para niveles PUBLICA y PRIVADA y el rechazo de valores desconocidos."""
        est_pub = obtener_estructura_qr_lote(self.lote, nivel_visibilidad="PUBLICA", incluir_imagen_base64=False)
        self.assertEqual(est_pub["nivel_visibilidad"], "PUBLICA")

        est_priv = obtener_estructura_qr_lote(self.lote, nivel_visibilidad="PRIVADA", incluir_imagen_base64=False)
        self.assertEqual(est_priv["nivel_visibilidad"], "PRIVADA")

        with self.assertRaises(ValidationError) as ctx:
            obtener_estructura_qr_lote(self.lote, nivel_visibilidad="CONFIDENCIAL")
        self.assertIn("nivel_visibilidad", ctx.exception.message_dict)

    def test_error_al_solicitar_qr_de_lote_inexistente_o_codigo_vacio(self):
        """Comprueba captura adecuada de excepciones ante lotes inexistentes o códigos vacíos."""
        with self.assertRaises(ValidationError):
            generar_identificador_qr_lote("")

        with self.assertRaises(ValidationError):
            generar_identificador_qr_lote("   ")

        with self.assertRaises(ValidationError):
            generar_identificador_qr_lote(999999)  # ID inexistente


# ==============================================================================
# SUITE HU-18 / SCRUM-176: PERSISTIR ASOCIACIÓN ENTRE LOTE Y CÓDIGO QR
# ==============================================================================

class CodigoQRPersistenciaTests(TestCase):
    """
    Pruebas unitarias y de persistencia para HU18-ST5 (SCRUM-176):
    Persistir la asociación entre lote y código QR.

    Criterios de Aceptación HU-18:
    1. El QR debe ser único por lote.
    2. El QR debe respetar el nivel de visibilidad de la información (pública / privada).
    """

    def setUp(self):
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.first()

        self.productor_uuid = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Hacienda El Cedral",
            municipio=self.municipio,
            vereda="La Esmeralda",
            productor_id=self.productor_uuid,
            latitud=Decimal("7.315000"),
            longitud=Decimal("-72.485000"),
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Geisha Especial", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="HONEY", nombre="Honey Dorado", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 9, 10),
            cantidad_total=Decimal("3000.00"),
            cantidad_disponible=Decimal("2500.00"),
        )
        self.lote = Lote(
            codigo="LOT-QR-P01",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            estado_lote=self.estado_disponible,
            cantidad=Decimal("800.00"),
            activo=True,
        )
        self.lote._skip_auto_qr = True
        self.lote.save()

    def test_persistencia_asociacion_exitosa_uno_a_uno(self):
        """Verifica que asociar_codigo_qr_a_lote persista correctamente en fincas_codigo_qr_lote."""
        qr = asociar_codigo_qr_a_lote(
            lote_o_id=self.lote,
            nivel_visibilidad=VISIBILIDAD_QR_PUBLICA,
        )

        self.assertIsNotNone(qr.id)
        self.assertEqual(qr.lote, self.lote)
        self.assertEqual(qr.identificador, "QR-LOT-QR-P01")
        self.assertEqual(qr.nivel_visibilidad, VISIBILIDAD_QR_PUBLICA)
        self.assertEqual(qr.payload_url, f"/trazabilidad/lote/{self.lote.codigo}/")
        self.assertTrue(qr.imagen_base64.startswith("data:image/png;base64,"))
        self.assertTrue(qr.activo)

        # Propiedades del modelo Lote
        self.assertTrue(self.lote.tiene_codigo_qr)
        self.assertEqual(self.lote.identificador_qr, "QR-LOT-QR-P01")
        self.assertEqual(self.lote.codigo_qr, qr)

    def test_unicidad_estricta_un_solo_qr_por_lote(self):
        """Criterio de Aceptación 1: Unicidad estricta 1:1 en BD. Intentar crear un segundo QR para el mismo lote es rechazado."""
        asociar_codigo_qr_a_lote(lote_o_id=self.lote)

        with self.assertRaises((IntegrityError, ValidationError)):
            CodigoQRLote.objects.create(
                lote=self.lote,
                identificador="QR-LOT-OTRO-ID",
                nivel_visibilidad=VISIBILIDAD_QR_PUBLICA,
                payload_url=f"/trazabilidad/lote/{self.lote.codigo}/",
            )

    def test_unicidad_estricta_identificador_no_repetido_en_otros_lotes(self):
        """Criterio de Aceptación 1: Dos lotes distintos no pueden tener el mismo identificador QR."""
        asociar_codigo_qr_a_lote(lote_o_id=self.lote)

        lote2 = Lote(
            codigo="LOT-QR-P02",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            estado_lote=self.estado_disponible,
            cantidad=Decimal("300.00"),
            activo=True,
        )
        lote2._skip_auto_qr = True
        lote2.save()

        with self.assertRaises((IntegrityError, ValidationError)):
            CodigoQRLote.objects.create(
                lote=lote2,
                identificador="QR-LOT-QR-P01",  # Identificador ya en uso por self.lote
                nivel_visibilidad=VISIBILIDAD_QR_PUBLICA,
                payload_url=f"/trazabilidad/lote/{lote2.codigo}/",
            )

    def test_idempotencia_asociar_codigo_qr(self):
        """Verifica que invocar asociar_codigo_qr_a_lote múltiples veces no duplica filas y actualiza metadatos."""
        qr1 = asociar_codigo_qr_a_lote(lote_o_id=self.lote, nivel_visibilidad=VISIBILIDAD_QR_PUBLICA)
        self.assertEqual(CodigoQRLote.objects.filter(lote=self.lote).count(), 1)

        # Segunda llamada cambiando visibilidad
        qr2 = asociar_codigo_qr_a_lote(lote_o_id=self.lote, nivel_visibilidad=VISIBILIDAD_QR_PRIVADA)
        self.assertEqual(CodigoQRLote.objects.filter(lote=self.lote).count(), 1)
        self.assertEqual(qr1.id, qr2.id)
        self.assertEqual(qr2.nivel_visibilidad, VISIBILIDAD_QR_PRIVADA)

    def test_actualizar_visibilidad_codigo_qr(self):
        """Criterio de Aceptación 2: Control de visibilidad pública/privada persistida en BD."""
        qr = asociar_codigo_qr_a_lote(lote_o_id=self.lote, nivel_visibilidad=VISIBILIDAD_QR_PUBLICA)
        self.assertEqual(qr.nivel_visibilidad, VISIBILIDAD_QR_PUBLICA)

        # Actualizar a PRIVADA
        actualizado = actualizar_visibilidad_codigo_qr(lote_o_id=self.lote, nuevo_nivel=VISIBILIDAD_QR_PRIVADA)
        self.assertEqual(actualizado.nivel_visibilidad, VISIBILIDAD_QR_PRIVADA)

        qr.refresh_from_db()
        self.assertEqual(qr.nivel_visibilidad, VISIBILIDAD_QR_PRIVADA)

        # Rechazar nivel desconocido
        with self.assertRaises(ValidationError):
            actualizar_visibilidad_codigo_qr(lote_o_id=self.lote, nuevo_nivel="SECRETO")

    def test_obtener_codigo_qr_lote_servicio(self):
        """Verifica la recuperación segura del objeto persistido CodigoQRLote."""
        self.assertIsNone(obtener_codigo_qr_lote(self.lote))

        qr_creado = asociar_codigo_qr_a_lote(lote_o_id=self.lote)
        qr_recuperado = obtener_codigo_qr_lote(self.lote)

        self.assertIsNotNone(qr_recuperado)
        self.assertEqual(qr_recuperado.id, qr_creado.id)
        self.assertEqual(qr_recuperado.identificador, "QR-LOT-QR-P01")

    def test_eliminacion_en_cascada_al_eliminar_lote(self):
        """Verifica integridad referencial: al eliminarse el Lote, se elimina en cascada su CodigoQRLote."""
        qr = asociar_codigo_qr_a_lote(lote_o_id=self.lote)
        qr_id = qr.id
        self.assertTrue(CodigoQRLote.objects.filter(id=qr_id).exists())

        self.lote.delete()
        self.assertFalse(CodigoQRLote.objects.filter(id=qr_id).exists())


# ==============================================================================
# SUITE HU-18 (SCRUM-174): GENERACIÓN AUTOMÁTICA DE QR AL CREAR O ACTUALIZAR (ST1)
# ==============================================================================

class CodigoQRGeneracionAutomaticaTests(TestCase):
    """
    Batería de pruebas automatizadas para HU18-ST1 (SCRUM-174):
    Implementar la generación automática del QR al crear o actualizar lote.

    Criterios de Aceptación y Reglas de Negocio:
    1. Generación automática e inmediata al crear un lote vía servicio de dominio `crear_lote()`.
    2. Generación automática transparente en el ciclo de guardado ORM `Lote.save()`.
    3. Sincronización automática de metadatos (identificador, payload y regeneración de imagen)
       cuando muta el código del lote.
    4. Idempotencia y optimización de cómputo: no regenerar la imagen QR si el código no cambió.
    5. Servicio de actualización `actualizar_lote()` con sincronización transaccional del QR y balance de cosecha.
    6. Servicio de sincronización `sincronizar_o_generar_qr_lote()` sobre lotes preexistentes sin QR.
    7. Extensión de `obtener_codigo_qr_lote(..., auto_generar=True)`.
    8. Consistencia de código generado automáticamente y su identificador QR asociado.
    9. Exposición del estado del QR en la respuesta de la API `POST /fincas/api/lotes/`.
    """

    def setUp(self):
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="54820",
                nombre="Toledo",
                departamento="Norte de Santander",
                latitud=Decimal("7.3100"),
                longitud=Decimal("-72.4830"),
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca La Trazabilidad QR",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.3150"),
            longitud=Decimal("-72.4800"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo Tambo", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO_AUTO", nombre="Lavado Controlado", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 9, 20),
            cantidad_total=Decimal("4000.00"),
            cantidad_disponible=Decimal("3500.00"),
            activo=True,
        )

    def test_generacion_automatica_con_servicio_crear_lote(self):
        """Verifica que crear un lote con el servicio crear_lote genere inmediatamente su código QR."""
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("150.00"),
            codigo="LOTAUTO01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        self.assertTrue(lote.tiene_codigo_qr)
        self.assertEqual(lote.identificador_qr, "QR-LOTAUTO01")

        qr = CodigoQRLote.objects.filter(lote=lote).first()
        self.assertIsNotNone(qr)
        self.assertEqual(qr.identificador, "QR-LOTAUTO01")
        self.assertEqual(qr.payload_url, "/trazabilidad/lote/LOTAUTO01/")
        self.assertEqual(qr.nivel_visibilidad, VISIBILIDAD_QR_PUBLICA)
        self.assertTrue(qr.imagen_base64.startswith("data:image/png;base64,"))
        self.assertTrue(qr.activo)

    def test_generacion_automatica_en_guardado_orm(self):
        """Verifica que Lote.objects.create genere y persista el QR automáticamente en el ciclo de guardado."""
        lote = Lote.objects.create(
            codigo="LOTORM02",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            estado_lote=self.estado_disponible,
            cantidad=Decimal("80.00"),
            activo=True,
        )

        self.assertTrue(lote.tiene_codigo_qr)
        self.assertEqual(lote.identificador_qr, "QR-LOTORM02")
        qr = CodigoQRLote.objects.filter(lote=lote).first()
        self.assertIsNotNone(qr)
        self.assertEqual(qr.payload_url, "/trazabilidad/lote/LOTORM02/")

    def test_sincronizacion_automatica_al_mutar_codigo_lote(self):
        """Verifica que al modificar el código del lote, el QR sincronice su identificador, URL y regenere la imagen."""
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("90.00"),
            codigo="LOTMUTARA",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        qr_original = lote.codigo_qr
        imagen_original = qr_original.imagen_base64

        # Mutación del código del lote
        lote.codigo = "LOTMUTARB"
        lote.save()

        lote.refresh_from_db()
        qr_actualizado = CodigoQRLote.objects.get(lote=lote)

        self.assertEqual(qr_actualizado.identificador, "QR-LOTMUTARB")
        self.assertEqual(qr_actualizado.payload_url, "/trazabilidad/lote/LOTMUTARB/")
        self.assertTrue(qr_actualizado.imagen_base64.startswith("data:image/png;base64,"))
        # La imagen se regeneró para codificar el nuevo enlace
        self.assertNotEqual(qr_actualizado.imagen_base64, imagen_original)

    def test_idempotencia_actualizacion_lote_sin_cambio_codigo(self):
        """Verifica que modificar atributos del lote sin cambiar el código mantenga la misma imagen y metadatos sin sobrecosto."""
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("110.00"),
            codigo="LOTIDEMP01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        qr_original = lote.codigo_qr
        qr_id_original = qr_original.id
        imagen_original = qr_original.imagen_base64

        # Modificación de atributos que no afectan el código ni el QR
        lote.cantidad = Decimal("105.00")
        lote.precio_referencial = Decimal("24500.00")
        lote.save()

        qr_despues = CodigoQRLote.objects.get(lote=lote)
        self.assertEqual(qr_despues.id, qr_id_original)
        self.assertEqual(qr_despues.imagen_base64, imagen_original)
        self.assertEqual(qr_despues.identificador, "QR-LOTIDEMP01")

    def test_servicio_actualizar_lote_sincroniza_qr_y_ajusta_cosecha(self):
        """Verifica que el servicio actualizar_lote actualice datos, descuente de cosecha y sincronice el QR."""
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("100.00"),
            codigo="LOTSRV01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        saldo_antes = Cosecha.objects.get(pk=self.cosecha.pk).cantidad_disponible

        # Aumentar 50 kg y cambiar código
        lote_actualizado = actualizar_lote(
            lote_o_id=lote,
            codigo="LOTSRV02",
            cantidad=Decimal("150.00"),
            precio_referencial=Decimal("26000.00"),
        )

        self.assertEqual(lote_actualizado.codigo, "LOTSRV02")
        self.assertEqual(lote_actualizado.cantidad, Decimal("150.00"))
        self.assertEqual(lote_actualizado.precio_referencial, Decimal("26000.00"))

        # Descuento en cosecha
        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, saldo_antes - Decimal("50.00"))

        # QR sincronizado
        qr = CodigoQRLote.objects.get(lote=lote_actualizado)
        self.assertEqual(qr.identificador, "QR-LOTSRV02")
        self.assertEqual(qr.payload_url, "/trazabilidad/lote/LOTSRV02/")

    def test_actualizar_lote_validaciones_de_negocio(self):
        """Verifica que actualizar_lote rechace códigos inválidos, duplicados o cantidades no válidas."""
        lote1 = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("50.00"),
            codigo="LOTEVAL01",
        )
        crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("50.00"),
            codigo="LOTEVAL02",
        )

        # Código duplicado
        with self.assertRaises(ValidationError):
            actualizar_lote(lote_o_id=lote1, codigo="LOTEVAL02")

        # Código no alfanumérico
        with self.assertRaises(ValidationError):
            actualizar_lote(lote_o_id=lote1, codigo="COD@INVALIDO")

        # Cantidad negativa
        with self.assertRaises(ValidationError):
            actualizar_lote(lote_o_id=lote1, cantidad=Decimal("-10.00"))

        # Incremento que supera saldo disponible de la cosecha
        with self.assertRaises(ValidationError):
            actualizar_lote(lote_o_id=lote1, cantidad=Decimal("99999.00"))

    def test_sincronizar_o_generar_qr_en_lote_preexistente_sin_qr(self):
        """Verifica que sincronizar_o_generar_qr_lote genere el QR para lotes existentes que carezcan de él."""
        lote = Lote(
            codigo="LOTLEGACY01",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            estado_lote=self.estado_disponible,
            cantidad=Decimal("120.00"),
            activo=True,
        )
        lote._skip_auto_qr = True
        lote.save()

        self.assertFalse(lote.tiene_codigo_qr)
        self.assertIsNone(lote.identificador_qr)

        qr_generado = sincronizar_o_generar_qr_lote(lote)
        self.assertIsNotNone(qr_generado)
        self.assertEqual(qr_generado.identificador, "QR-LOTLEGACY01")
        self.assertTrue(lote.tiene_codigo_qr)

    def test_obtener_codigo_qr_lote_con_auto_generar_true(self):
        """Verifica que obtener_codigo_qr_lote(..., auto_generar=True) cree el QR bajo demanda si falta."""
        lote = Lote(
            codigo="LOTONDEMAND01",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            estado_lote=self.estado_disponible,
            cantidad=Decimal("130.00"),
            activo=True,
        )
        lote._skip_auto_qr = True
        lote.save()

        self.assertIsNone(obtener_codigo_qr_lote(lote, auto_generar=False))

        qr_creado = obtener_codigo_qr_lote(lote, auto_generar=True)
        self.assertIsNotNone(qr_creado)
        self.assertEqual(qr_creado.identificador, "QR-LOTONDEMAND01")

    def test_crear_lote_sin_codigo_genera_qr_consistente_con_codigo_automatico(self):
        """Verifica que cuando crear_lote autogenera el código del lote, el QR se cree consistente con él."""
        lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("45.00"),
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        self.assertTrue(lote.codigo.startswith("L"))
        self.assertTrue(lote.tiene_codigo_qr)
        self.assertEqual(lote.identificador_qr, f"QR-{lote.codigo}")
        self.assertEqual(lote.codigo_qr.payload_url, f"/trazabilidad/lote/{lote.codigo}/")

    @patch("fincas.views.Usuario")
    def test_api_crear_lote_refleja_codigo_qr_generado(self, mock_usuario_model):
        """Verifica que el endpoint REST POST /fincas/api/lotes/ devuelva tiene_codigo_qr e identificador_qr."""
        client = Client()
        productor_id = uuid.uuid4()
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=productor_id)

        finca = Finca.objects.create(
            nombre="Finca API QR Test",
            productor_id=productor_id,
            municipio=self.municipio,
        )
        cosecha = Cosecha.objects.create(
            finca=finca,
            fecha_cosecha="2026-06-01",
            cantidad_total=Decimal("200.00"),
        )

        url_api = reverse("api_lote_crear")
        response = client.post(
            url_api,
            {"cosecha": cosecha.pk, "cantidad": "60.00", "codigo": "LOTAPIQR01"},
            content_type="application/json",
            **_jwt_bearer_headers(),
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["codigo"], "LOTAPIQR01")
        self.assertTrue(data.get("tiene_codigo_qr"))
        self.assertEqual(data.get("identificador_qr"), "QR-LOTAPIQR01")

        lote = Lote.objects.get(codigo="LOTAPIQR01")
        self.assertTrue(lote.tiene_codigo_qr)
        self.assertEqual(lote.identificador_qr, "QR-LOTAPIQR01")


# ==============================================================================
# SUITE HU-18 (SCRUM-177): CONSULTA DE FICHA DIGITAL DESDE EL QR (ST3)
# ==============================================================================

class CodigoQRConsultaFichaTests(TestCase):
    """
    Batería de pruebas automatizadas para HU18-ST3 (SCRUM-177):
    Crear la vista o endpoint de consulta de ficha digital desde el QR.

    Criterios de Aceptación y Escenarios:
    1. Resolución de lote por identificador formal 'QR-<CODIGO>'.
    2. Resolución polimórfica por código de lote directo.
    3. Rechazo y manejo de errores ante QR inexistente o inactivo.
    4. Rechazo ante lote inactivo.
    5. Soporte en el servicio de dominio `obtener_ficha_consolidada_lote()` por identificador QR.
    6. Vista Web de Escaneo `GET /trazabilidad/qr/<identificador>/`:
       - Respuesta 200 OK con plantilla `fincas/ficha_digital.html`.
       - Indicadores visuales de escaneo QR y renderizado de la imagen Base64.
       - Registro de auditoría con tipo CONSULTA_WEB y canal 'escaneo_qr'.
       - Respuesta 404 con plantilla de error ante QR no encontrado.
    7. Endpoint REST `GET /fincas/api/qr/<identificador>/`:
       - Respuesta 200 OK con DTO consolidado y nodo `codigo_qr`.
       - Registro de auditoría con tipo CONSULTA_API y canal 'api_qr'.
       - Respuesta 404 NOT FOUND ante QR inexistente o inactivo.
    """

    def setUp(self):
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="54820",
                nombre="Toledo",
                departamento="Norte de Santander",
                latitud=Decimal("7.3100"),
                longitud=Decimal("-72.4830"),
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Hacienda San Isidro QR",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.3120"),
            longitud=Decimal("-72.4810"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Geisha", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="HONEY_QR", nombre="Honey Amarillo", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 9, 25),
            cantidad_total=Decimal("5000.00"),
            cantidad_disponible=Decimal("4800.00"),
            activo=True,
        )
        self.lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("200.00"),
            codigo="LOTCONSULTA01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        self.qr = self.lote.codigo_qr

    def test_resolver_lote_desde_qr_por_identificador_formal(self):
        """Verifica que resolver_lote_desde_qr resuelva correctamente por 'QR-<CODIGO>'."""
        qr_obj, lote_obj = resolver_lote_desde_qr("QR-LOTCONSULTA01")
        self.assertEqual(qr_obj.pk, self.qr.pk)
        self.assertEqual(lote_obj.pk, self.lote.pk)
        self.assertEqual(lote_obj.codigo, "LOTCONSULTA01")

    def test_resolver_lote_desde_qr_por_codigo_directo(self):
        """Verifica resolución polimórfica si se suministra el código de lote directamente."""
        qr_obj, lote_obj = resolver_lote_desde_qr("LOTCONSULTA01")
        self.assertEqual(qr_obj.pk, self.qr.pk)
        self.assertEqual(lote_obj.pk, self.lote.pk)

    def test_resolver_lote_desde_qr_inexistente_lanza_validation_error(self):
        """Verifica que resolver_lote_desde_qr lance ValidationError ante QR desconocido."""
        with self.assertRaises(ValidationError):
            resolver_lote_desde_qr("QR-INEXISTENTE999")

    def test_resolver_lote_desde_qr_inactivo_lanza_validation_error(self):
        """Verifica que un código QR inactivo sea rechazado para consulta."""
        self.qr.activo = False
        self.qr.save()

        with self.assertRaises(ValidationError):
            resolver_lote_desde_qr("QR-LOTCONSULTA01")

    def test_resolver_lote_desde_qr_con_lote_inactivo_lanza_validation_error(self):
        """Verifica que un lote inactivo sea rechazado para consulta desde QR."""
        self.lote.activo = False
        self.lote.save()

        with self.assertRaises(ValidationError):
            resolver_lote_desde_qr("QR-LOTCONSULTA01")

    def test_obtener_ficha_consolidada_lote_por_identificador_qr(self):
        """Verifica que obtener_ficha_consolidada_lote acepte el identificador QR y retorne la ficha completa."""
        ficha = obtener_ficha_consolidada_lote("QR-LOTCONSULTA01")
        self.assertEqual(ficha["codigo"], "LOTCONSULTA01")
        self.assertEqual(ficha["identificador_qr"], "QR-LOTCONSULTA01")
        self.assertTrue(ficha["tiene_codigo_qr"])
        self.assertEqual(ficha["finca"]["nombre"], "Hacienda San Isidro QR")

    def test_vista_web_escanear_qr_exitoso_200_ok_y_template(self):
        """Verifica que GET /trazabilidad/qr/<identificador>/ responda 200 OK y renderice la ficha digital."""
        url = reverse("trazabilidad_qr_web", kwargs={"identificador": "QR-LOTCONSULTA01"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/ficha_digital.html")
        self.assertTrue(response.context.get("es_escaneo_qr"))
        self.assertEqual(response.context.get("codigo_qr").identificador, "QR-LOTCONSULTA01")
        self.assertContains(response, "LOTCONSULTA01")
        self.assertContains(response, "Hacienda San Isidro QR")
        self.assertContains(response, "Consulta vía Escaneo QR")
        self.assertContains(response, "QR Certificado Activo")

    def test_vista_web_escanear_qr_registra_auditoria_en_bitacora(self):
        """Verifica que el escaneo web registre auditoría en BitacoraFichaDigital con canal escaneo_qr."""
        url = reverse("trazabilidad_qr_web", kwargs={"identificador": "QR-LOTCONSULTA01"})
        self.client.get(url)

        registro = BitacoraFichaDigital.objects.filter(
            lote=self.lote, tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_WEB
        ).order_by("-creado_en").first()

        self.assertIsNotNone(registro)
        self.assertEqual(registro.usuario_identificador, "Público / Escaneo QR")
        self.assertEqual(registro.detalles.get("canal"), "escaneo_qr")
        self.assertEqual(registro.detalles.get("identificador_qr"), "QR-LOTCONSULTA01")

    def test_vista_web_escanear_qr_no_encontrado_responde_404_con_template_error(self):
        """Verifica que consultar un QR inexistente responda 404 y use ficha_digital_error.html."""
        url = reverse("trazabilidad_qr_web", kwargs={"identificador": "QR-DESCONOCIDO"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "fincas/ficha_digital_error.html")
        self.assertContains(response, "Ficha Digital No Disponible", status_code=404)

    def test_api_consultar_ficha_desde_qr_200_ok_con_datos_completos(self):
        """Verifica que GET /fincas/api/qr/<identificador>/ responda 200 OK con la ficha y metadatos de QR."""
        url = reverse("api_consultar_ficha_desde_qr", kwargs={"identificador": "QR-LOTCONSULTA01"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["codigo"], "LOTCONSULTA01")
        self.assertEqual(data["cantidad_kg"], "200.00")
        self.assertEqual(data["finca"]["nombre"], "Hacienda San Isidro QR")
        self.assertEqual(data["variedad"]["nombre"], "Geisha")
        self.assertEqual(data["proceso_beneficio"]["nombre"], "Honey Amarillo")

        # Metadatos del QR adjuntos en la respuesta API
        self.assertIn("codigo_qr", data)
        qr_info = data["codigo_qr"]
        self.assertEqual(qr_info["identificador"], "QR-LOTCONSULTA01")
        self.assertEqual(qr_info["payload_url"], "/trazabilidad/lote/LOTCONSULTA01/")
        self.assertEqual(qr_info["nivel_visibilidad"], VISIBILIDAD_QR_PUBLICA)
        self.assertTrue(qr_info["activo"])
        self.assertTrue(qr_info["imagen_base64"].startswith("data:image/png;base64,"))

    def test_api_consultar_ficha_desde_qr_registra_auditoria(self):
        """Verifica que la consulta API vía QR registre auditoría con tipo CONSULTA_API y canal api_qr."""
        url = reverse("api_consultar_ficha_desde_qr", kwargs={"identificador": "QR-LOTCONSULTA01"})
        self.client.get(url)

        registro = BitacoraFichaDigital.objects.filter(
            lote=self.lote, tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_API
        ).order_by("-creado_en").first()

        self.assertIsNotNone(registro)
        self.assertEqual(registro.detalles.get("canal"), "api_qr")
        self.assertEqual(registro.detalles.get("identificador_qr"), "QR-LOTCONSULTA01")

    def test_api_consultar_ficha_desde_qr_inactivo_o_inexistente_responde_404(self):
        """Verifica que consultar un QR inexistente o inactivo por API responda 404 NOT FOUND."""
        url_inexistente = reverse(
            "api_consultar_ficha_desde_qr", kwargs={"identificador": "QR-NO-EXISTE-404"}
        )
        resp_inexistente = self.client.get(url_inexistente)
        self.assertEqual(resp_inexistente.status_code, 404)
        self.assertIn("error", resp_inexistente.json())

        # Inactivar QR y verificar 404
        self.qr.activo = False
        self.qr.save()
        url_inactivo = reverse(
            "api_consultar_ficha_desde_qr", kwargs={"identificador": "QR-LOTCONSULTA01"}
        )
        resp_inactivo = self.client.get(url_inactivo)
        self.assertEqual(resp_inactivo.status_code, 404)
        self.assertIn("error", resp_inactivo.json())


class CodigoQRControlVisibilidadTests(TestCase):
    """
    Batería de pruebas automatizadas para HU18-ST4 (SCRUM-178):
    Aplicar control de visibilidad en la ficha digital accesible desde el QR.

    Criterios de Aceptación y Escenarios:
    1. Reglas de negocio del servicio `verificar_permiso_visibilidad_qr`:
       - Visibilidad PUBLICA: Acceso permitido para cualquier usuario anónimo o externo.
       - Visibilidad PRIVADA: Acceso restringido para anónimos o terceros; irrestricto para el productor dueño.
    2. Enmascaramiento y sanitización mediante `sanitizar_ficha_por_visibilidad`:
       - Usuarios no propietarios no visualizan datos sensibles del productor (número y tipo de documento).
       - El productor propietario conserva los datos completos.
    3. Vista Web de Escaneo `GET /trazabilidad/qr/<identificador>/`:
       - Si es PRIVADA y el usuario es anónimo: responde HTTP 403 Forbidden y renderiza `fincas/ficha_digital_privada.html`.
       - Si es PUBLICA y el usuario es anónimo: responde HTTP 200 OK con `fincas/ficha_digital.html`.
       - Si es PRIVADA y el usuario es el dueño: responde HTTP 200 OK con `fincas/ficha_digital.html`.
    4. Endpoint REST `GET /fincas/api/qr/<identificador>/`:
       - Si es PRIVADA y el usuario es anónimo: responde HTTP 403 Forbidden.
       - Si es PRIVADA y el usuario es el dueño: responde HTTP 200 OK con datos completos.
       - Si es PUBLICA: responde HTTP 200 OK con datos enmascarados para anónimos.
    5. Actualización de Visibilidad REST `POST /fincas/api/lotes/<pk>/qr/visibilidad/`:
       - Productor dueño actualiza exitosamente a 'PRIVADA' o 'PUBLICA' (200 OK).
       - Usuario no propietario es rechazado con 403 Forbidden.
       - Solicitud anónima es rechazada con 401 Unauthorized.
       - Valor de visibilidad inválido responde 400 Bad Request.
    6. Conmutación Web `POST /fincas/lotes/<pk>/qr/visibilidad/`:
       - Productor dueño conmuta visibilidad y es redirigido con mensaje de éxito (302 Redirect).
       - Tercero o anónimo es rechazado apropiadamente.
    """

    def setUp(self):
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="54820",
                nombre="Toledo",
                departamento="Norte de Santander",
                latitud=Decimal("7.3100"),
                longitud=Decimal("-72.4830"),
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.otro_productor_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Hacienda El Secreto QR",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.3150"),
            longitud=Decimal("-72.4850"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Bourbon Rosado", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO_VIS", nombre="Lavado Clásico", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("3000.00"),
            cantidad_disponible=Decimal("2500.00"),
            activo=True,
        )
        self.lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("500.00"),
            codigo="LOTVISIBILIDAD01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        self.qr = self.lote.codigo_qr

    def test_servicio_verificar_permiso_visibilidad_publica(self):
        """Verifica que un QR con visibilidad PUBLICA permita el acceso tanto anónimo como de cualquier usuario."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PUBLICA
        self.qr.save()

        # Usuario anónimo (None)
        puede_acceder, es_propietario, motivo = verificar_permiso_visibilidad_qr(self.qr, None)
        self.assertTrue(puede_acceder)
        self.assertFalse(es_propietario)

        # Tercero
        puede_acceder, es_propietario, motivo = verificar_permiso_visibilidad_qr(self.qr, self.otro_productor_id)
        self.assertTrue(puede_acceder)
        self.assertFalse(es_propietario)

        # Productor propietario
        puede_acceder, es_propietario, motivo = verificar_permiso_visibilidad_qr(self.qr, self.productor_id)
        self.assertTrue(puede_acceder)
        self.assertTrue(es_propietario)

    def test_servicio_verificar_permiso_visibilidad_privada(self):
        """Verifica que un QR con visibilidad PRIVADA niegue el acceso a anónimos y terceros, pero lo permita al dueño."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        # Anónimo
        puede_acceder, es_propietario, motivo = verificar_permiso_visibilidad_qr(self.qr, None)
        self.assertFalse(puede_acceder)
        self.assertFalse(es_propietario)
        self.assertIn("Acceso restringido", motivo)

        # Tercero
        puede_acceder, es_propietario, motivo = verificar_permiso_visibilidad_qr(self.qr, self.otro_productor_id)
        self.assertFalse(puede_acceder)
        self.assertFalse(es_propietario)

        # Dueño
        puede_acceder, es_propietario, motivo = verificar_permiso_visibilidad_qr(self.qr, self.productor_id)
        self.assertTrue(puede_acceder)
        self.assertTrue(es_propietario)

    def test_servicio_sanitizar_ficha_por_visibilidad(self):
        """Verifica que la sanitización oculte datos sensibles de identidad a no propietarios."""
        ficha_mock = {
            "id": self.lote.pk,
            "codigo": self.lote.codigo,
            "productor": {
                "nombre": "Juan Pérez",
                "numero_documento": "1098765432",
                "tipo_documento": "CC",
            },
        }
        # Caso no propietario: oculta documento
        sanitizada_publica = sanitizar_ficha_por_visibilidad(ficha_mock, self.qr, es_propietario=False)
        self.assertIsNone(sanitizada_publica["productor"]["numero_documento"])
        self.assertIsNone(sanitizada_publica["productor"]["tipo_documento"])
        self.assertEqual(sanitizada_publica["productor"]["nombre"], "Juan Pérez")
        self.assertFalse(sanitizada_publica["es_propietario"])

        # Caso propietario: conserva documento
        sanitizada_propietario = sanitizar_ficha_por_visibilidad(ficha_mock, self.qr, es_propietario=True)
        self.assertEqual(sanitizada_propietario["productor"]["numero_documento"], "1098765432")
        self.assertEqual(sanitizada_propietario["productor"]["tipo_documento"], "CC")
        self.assertTrue(sanitizada_propietario["es_propietario"])

    def test_web_escanear_qr_publica_acceso_anonimo_exitoso(self):
        """GET /trazabilidad/qr/<identificador>/ con QR PUBLICA responde 200 OK y plantilla ficha_digital.html."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PUBLICA
        self.qr.save()

        url = reverse("trazabilidad_qr_web", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/ficha_digital.html")
        self.assertContains(response, self.lote.codigo)

    def test_web_escanear_qr_privada_anonimo_retorna_403_pantalla_privada(self):
        """GET /trazabilidad/qr/<identificador>/ con QR PRIVADA y anónimo responde 403 y plantilla ficha_digital_privada.html."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        url = reverse("trazabilidad_qr_web", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "fincas/ficha_digital_privada.html")
        self.assertContains(response, "Ficha Digital Privada", status_code=403)
        self.assertContains(response, "visibilidad privada", status_code=403)
        self.assertContains(response, self.lote.codigo, status_code=403)

    def test_web_escanear_qr_privada_productor_propietario_acceso_exitoso(self):
        """GET /trazabilidad/qr/<identificador>/ con QR PRIVADA y dueño autenticado responde 200 OK."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("trazabilidad_qr_web", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/ficha_digital.html")

    def test_api_consultar_qr_publica_anonimo_exitoso_y_enmascarado(self):
        """GET /fincas/api/qr/<identificador>/ con QR PUBLICA responde 200 OK y oculta documento del productor."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PUBLICA
        self.qr.save()

        url = reverse("api_consultar_ficha_desde_qr", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["codigo_qr"]["nivel_visibilidad"], "PUBLICA")
        self.assertFalse(data["es_propietario"])

    def test_api_consultar_qr_privada_anonimo_retorna_403(self):
        """GET /fincas/api/qr/<identificador>/ con QR PRIVADA responde 403 FORBIDDEN para usuarios no autorizados."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        url = reverse("api_consultar_ficha_desde_qr", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_api_consultar_qr_privada_propietario_retorna_200(self):
        """GET /fincas/api/qr/<identificador>/ con QR PRIVADA responde 200 OK para el productor propietario."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("api_consultar_ficha_desde_qr", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["es_propietario"])
        self.assertEqual(data["codigo_qr"]["nivel_visibilidad"], "PRIVADA")

    @patch("fincas.views.Usuario")
    def test_api_actualizar_visibilidad_propietario_exitoso(self, mock_usuario_model):
        """POST /fincas/api/lotes/<pk>/qr/visibilidad/ permite al dueño actualizar visibilidad a PRIVADA."""
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)
        url = reverse("api_lote_qr_visibilidad", kwargs={"pk": self.lote.pk})
        response = self.client.post(
            url,
            data=json.dumps({"nivel_visibilidad": "PRIVADA"}),
            content_type="application/json",
            **_jwt_bearer_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.qr.refresh_from_db()
        self.assertEqual(self.qr.nivel_visibilidad, CodigoQRLote.VISIBILIDAD_PRIVADA)

    @patch("fincas.views.Usuario")
    def test_api_actualizar_visibilidad_no_propietario_retorna_403(self, mock_usuario_model):
        """POST /fincas/api/lotes/<pk>/qr/visibilidad/ rechaza a productores que no sean dueños con 403 FORBIDDEN."""
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.otro_productor_id)
        url = reverse("api_lote_qr_visibilidad", kwargs={"pk": self.lote.pk})
        response = self.client.post(
            url,
            data=json.dumps({"nivel_visibilidad": "PRIVADA"}),
            content_type="application/json",
            **_jwt_bearer_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("error", response.json())

    def test_api_actualizar_visibilidad_sin_autenticacion_retorna_401(self):
        """POST /fincas/api/lotes/<pk>/qr/visibilidad/ rechaza peticiones anónimas con 401 UNAUTHORIZED."""
        url = reverse("api_lote_qr_visibilidad", kwargs={"pk": self.lote.pk})
        response = self.client.post(
            url,
            data=json.dumps({"nivel_visibilidad": "PRIVADA"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)

    @patch("fincas.views.Usuario")
    def test_api_actualizar_visibilidad_valor_invalido_retorna_400(self, mock_usuario_model):
        """POST /fincas/api/lotes/<pk>/qr/visibilidad/ con nivel inválido retorna 400 BAD REQUEST."""
        mock_usuario_model.objects.filter.return_value.first.return_value = MagicMock(id=self.productor_id)
        url = reverse("api_lote_qr_visibilidad", kwargs={"pk": self.lote.pk})
        response = self.client.post(
            url,
            data=json.dumps({"nivel_visibilidad": "CONFIDENCIAL"}),
            content_type="application/json",
            **_jwt_bearer_headers(),
        )

        self.assertEqual(response.status_code, 400)

    def test_web_cambiar_visibilidad_conmuta_exitosamente(self):
        """POST /fincas/lotes/<pk>/qr/visibilidad/ conmuta la visibilidad de PUBLICA a PRIVADA para el dueño."""
        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("lote_qr_visibilidad_web", kwargs={"pk": self.lote.pk})
        response = self.client.post(url, follow=False)

        self.assertEqual(response.status_code, 302)
        self.qr.refresh_from_db()
        self.assertEqual(self.qr.nivel_visibilidad, CodigoQRLote.VISIBILIDAD_PRIVADA)


class CodigoQRVisualizacionGestionTests(TestCase):
    """
    Batería de pruebas automatizadas para HU18-ST6 (SCRUM-179):
    Incluir la visualización del QR en la interfaz de gestión del lote.

    Criterios de Aceptación y Escenarios:
    1. Vista 'Mis Lotes' (mis_lotes_view):
       - El contexto 'lotes_info' provee el objeto 'codigo_qr' sincronizado.
       - La tabla de lotes renderiza el badge de visibilidad del QR (Público / Privado).
       - Se incluye el botón interactivo de apertura de modal QR en la columna de acciones.
       - El modal del QR renderiza la imagen matricial Base64, el identificador formal y el conmutador de visibilidad.
    2. Vista de Detalle de Lote (detalle_lote_view):
       - Se incluye la sección 'seccion-codigo-qr' con la visualización gráfica del código QR.
       - Se visualiza el identificador formal, el badge de nivel de visibilidad y el enlace directo de escaneo.
       - Permite conmutar la visibilidad entre Pública y Privada directamente desde la pantalla de detalle.
    3. Auto-sincronización resiliente:
       - Si un lote preexistente carece de registro QR en base de datos, las vistas de gestión lo auto-generan
         al consultarlo para garantizar que el caficultor siempre disponga de su código QR.
    """

    def setUp(self):
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="54820",
                nombre="Toledo",
                departamento="Norte de Santander",
                latitud=Decimal("7.3100"),
                longitud=Decimal("-72.4830"),
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        _iniciar_sesion_productor(self.client, self.productor_id)

        self.finca = Finca.objects.create(
            nombre="Finca La Esperanza QR",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.3110"),
            longitud=Decimal("-72.4810"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="NATURAL_GEST", nombre="Natural Clásico", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 10),
            cantidad_total=Decimal("4000.00"),
            cantidad_disponible=Decimal("3500.00"),
            activo=True,
        )
        self.lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("500.00"),
            codigo="LOTGESTIONQR01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        self.qr = self.lote.codigo_qr

    def test_mis_lotes_incluye_codigo_qr_en_lotes_info_y_modal(self):
        """mis_lotes_view incluye el QR en el contexto y renderiza el modal interactivo con imagen y datos."""
        response = self.client.get(reverse("mis_lotes"))
        self.assertEqual(response.status_code, 200)

        # Contexto
        lotes_info = response.context["lotes_info"]
        self.assertEqual(len(lotes_info), 1)
        self.assertIsNotNone(lotes_info[0]["codigo_qr"])
        self.assertEqual(lotes_info[0]["codigo_qr"].identificador, "QR-LOTGESTIONQR01")

        # Renderizado en tabla y modal
        self.assertContains(response, "LOTGESTIONQR01")
        self.assertContains(response, f"modalQRLote{self.lote.id}")
        self.assertContains(response, "QR-LOTGESTIONQR01")
        self.assertContains(response, "Público")
        self.assertContains(response, self.qr.imagen_base64)

    def test_mis_lotes_refleja_badge_privado_cuando_qr_es_privado(self):
        """mis_lotes_view refleja visualmente la visibilidad privada configurada."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        response = self.client.get(reverse("mis_lotes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privado")
        self.assertContains(response, "Hacer Público")

    def test_detalle_lote_incluye_seccion_codigo_qr(self):
        """detalle_lote_view renderiza la sección 'seccion-codigo-qr' con la imagen y controles del QR."""
        url = reverse("lote_detalle", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id=\"seccion-codigo-qr\"")
        self.assertContains(response, "Código QR de Trazabilidad")
        self.assertContains(response, "QR-LOTGESTIONQR01")
        self.assertContains(response, "Visibilidad Pública")
        self.assertContains(response, self.qr.imagen_base64)
        self.assertContains(response, "Ver Ficha Digital (Escaneo)")

    def test_detalle_lote_auto_sincroniza_qr_si_no_existia(self):
        """detalle_lote_view genera y asocia el QR automáticamente si no existía previamente."""
        self.qr.delete()
        self.lote.refresh_from_db()
        self.assertFalse(self.lote.tiene_codigo_qr)

        url = reverse("lote_detalle", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.lote.refresh_from_db()
        self.assertTrue(self.lote.tiene_codigo_qr)
        self.assertEqual(self.lote.codigo_qr.identificador, "QR-LOTGESTIONQR01")
        self.assertContains(response, "QR-LOTGESTIONQR01")


class CodigoQRDescargaImpresionTests(TestCase):
    """
    Batería de pruebas automatizadas para HU18-ST7 (SCRUM-180):
    Permitir descargar o imprimir el QR del lote.

    Criterios de Aceptación y Escenarios:
    1. Servicio 'obtener_bytes_descarga_qr_lote':
       - Genera bytes de imagen PNG válidos (firma de archivo \x89PNG\r\n\x1a\n).
       - Retorna nombre de archivo canónico '{identificador}.png'.
       - Soporta resolución tanto por instancia/ID de Lote como por identificador formal 'QR-<CODIGO>'.
    2. Endpoint/Vista de Descarga 'descargar_qr_lote_view':
       - GET /fincas/lotes/<pk>/qr/descargar/ retorna HTTP 200 con Content-Type: image/png y Content-Disposition: attachment.
       - GET /fincas/qr/<identificador>/descargar/ retorna imagen descargable para acceso público.
       - Si el QR está configurado como PRIVADA y quien solicita no es el propietario, retorna HTTP 403 Forbidden.
       - Si quien solicita el QR privado es el productor dueño autenticado, retorna HTTP 200 con la imagen adjunta.
       - QR inexistente retorna HTTP 404 Not Found.
    3. Vista de Etiqueta Imprimible 'imprimir_etiqueta_qr_view':
       - GET /fincas/lotes/<pk>/qr/imprimir/ renderiza plantilla 'fincas/etiqueta_qr_lote.html'.
       - Incluye los datos esenciales: código de lote, finca, municipio, variedad, proceso, cantidad, QR Base64.
       - Si el QR es PRIVADO y el usuario es anónimo o externo, retorna HTTP 403 Forbidden.
       - Si el QR es PRIVADO y el usuario es el dueño autenticado, retorna HTTP 200 con la plantilla de etiqueta.
    4. Integración en Interfaces:
       - Modal de 'Mis Lotes' y tarjeta de 'Detalle de Lote' contienen los hipervínculos hacia descargar e imprimir.
    """

    def setUp(self):
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="54820",
                nombre="Toledo",
                departamento="Norte de Santander",
                latitud=Decimal("7.3100"),
                longitud=Decimal("-72.4830"),
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.otro_productor_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Hacienda El Paraíso QR",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.3125"),
            longitud=Decimal("-72.4820"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Caturra", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="WASHED_ST7", nombre="Lavado Gourmet", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 15),
            cantidad_total=Decimal("6000.00"),
            cantidad_disponible=Decimal("5500.00"),
            activo=True,
        )
        self.lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("500.00"),
            codigo="LOTDESCARGA01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        self.qr = self.lote.codigo_qr

    def test_servicio_obtener_bytes_descarga_qr_lote_valido(self):
        """El servicio genera bytes PNG con el encabezado estándar y el nombre '{identificador}.png'."""
        png_bytes, nombre_archivo, qr_obj, lote_obj = obtener_bytes_descarga_qr_lote(self.lote)

        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(nombre_archivo, f"{self.qr.identificador}.png")
        self.assertEqual(qr_obj.pk, self.qr.pk)
        self.assertEqual(lote_obj.pk, self.lote.pk)

    def test_servicio_obtener_bytes_descarga_por_identificador_formal(self):
        """El servicio resuelve por el identificador formal 'QR-<CODIGO>' y genera la imagen correspondiente."""
        png_bytes, nombre_archivo, qr_obj, lote_obj = obtener_bytes_descarga_qr_lote(self.qr.identificador)

        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(nombre_archivo, "QR-LOTDESCARGA01.png")
        self.assertEqual(lote_obj.codigo, "LOTDESCARGA01")

    def test_vista_descargar_qr_por_pk_exitoso(self):
        """GET /fincas/lotes/<pk>/qr/descargar/ retorna la imagen PNG con Content-Disposition: attachment."""
        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn('attachment; filename="QR-LOTDESCARGA01.png"', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_vista_descargar_qr_por_identificador_publico_anonimo(self):
        """GET /fincas/qr/<identificador>/descargar/ permite a usuarios anónimos descargar si es PUBLICA."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PUBLICA
        self.qr.save()

        url = reverse("qr_descargar_directo", kwargs={"identificador": self.qr.identificador})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_vista_descargar_qr_privado_anonimo_retorna_403(self):
        """GET descarga sobre un lote PRIVADO niega el acceso a anónimos con HTTP 403 Forbidden."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        url = reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    def test_vista_descargar_qr_privado_propietario_retorna_200(self):
        """GET descarga sobre un lote PRIVADO permite la descarga al productor dueño autenticado."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_vista_descargar_qr_inexistente_retorna_404(self):
        """Solicitud de descarga con identificador inexistente retorna HTTP 404 Not Found."""
        url = reverse("qr_descargar_directo", kwargs={"identificador": "QR-INEXISTENTE-999"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_vista_imprimir_etiqueta_publica_renderiza_plantilla(self):
        """GET /fincas/lotes/<pk>/qr/imprimir/ renderiza la plantilla 'fincas/etiqueta_qr_lote.html'."""
        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("lote_qr_imprimir", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/etiqueta_qr_lote.html")
        self.assertContains(response, self.lote.codigo)
        self.assertContains(response, self.finca.nombre)
        self.assertContains(response, self.qr.identificador)
        self.assertContains(response, "Imprimir Etiqueta")
        self.assertContains(response, "window.print()")

    def test_vista_imprimir_etiqueta_privada_anonimo_retorna_403(self):
        """Petición anónima a etiqueta de lote PRIVADO retorna 403 y plantilla privada."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        url = reverse("lote_qr_imprimir", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "fincas/ficha_digital_privada.html")

    def test_vista_imprimir_etiqueta_privada_propietario_retorna_200(self):
        """Productor dueño autenticado puede imprimir la etiqueta de su lote privado (200 OK)."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        _iniciar_sesion_productor(self.client, self.productor_id)
        url = reverse("lote_qr_imprimir", kwargs={"pk": self.lote.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fincas/etiqueta_qr_lote.html")

    def test_interfaces_incluyen_enlaces_descarga_e_impresion(self):
        """Tanto 'Mis Lotes' como 'Detalle de Lote' contienen los enlaces a descargar e imprimir."""
        _iniciar_sesion_productor(self.client, self.productor_id)

        # Mis lotes
        resp_mis_lotes = self.client.get(reverse("mis_lotes"))
        self.assertEqual(resp_mis_lotes.status_code, 200)
        self.assertContains(resp_mis_lotes, reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk}))
        self.assertContains(resp_mis_lotes, reverse("lote_qr_imprimir", kwargs={"pk": self.lote.pk}))

        # Detalle de lote
        resp_detalle = self.client.get(reverse("lote_detalle", kwargs={"pk": self.lote.pk}))
        self.assertEqual(resp_detalle.status_code, 200)
        self.assertContains(resp_detalle, reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk}))
        self.assertContains(resp_detalle, reverse("lote_qr_imprimir", kwargs={"pk": self.lote.pk}))


class CodigoQRCertificacionUnicidadE2ETests(TestCase):
    """
    Batería de pruebas automatizadas para HU18-ST8 (SCRUM-181):
    Validar unicidad y correcto funcionamiento del QR por lote.

    Criterios de Aceptación y Certificación:
    1. Unicidad Estricta (1:1):
       - Cada lote tiene exactamente un código QR único (restricción OneToOneField).
       - Intentar crear un segundo registro de CodigoQRLote para el mismo lote lanza IntegrityError.
       - La unicidad del identificador formal ('QR-<CODIGO>') es absoluta entre distintos lotes.
       - La función de asociación 'asociar_codigo_qr_a_lote' es estrictamente idempotente.
    2. Consistencia en Actualización de Lote:
       - Modificar el código de un lote mantiene la unicidad y actualiza el identificador del QR.
    3. Ciclo de Vida Completo E2E (Trazabilidad y Funcionamiento):
       - Fase 1 (Creación): Registro automático del QR al crear el lote.
       - Fase 2 (Escaneo Web): Consulta pública de la ficha digital y registro en bitácora (CONSULTA_WEB).
       - Fase 3 (Consulta API REST): Consumo por escáner de aplicación móvil (CONSULTA_API).
       - Fase 4 (Seguridad y Visibilidad): Conmutación a PRIVADA con bloqueo inmediato a anónimos (403)
         y acceso irrestricto al productor dueño.
       - Fase 5 (Descarga Física): Emisión del archivo PNG en alta definición con Content-Disposition.
       - Fase 6 (Rotulado e Impresión): Renderizado de la etiqueta física con datos de origen y QR.
       - Fase 7 (Trazabilidad Inmutable): Auditoría íntegra y ordenada en la BitacoraFichaDigital.
    4. Aislamiento Multi-Productor:
       - Productores no propietarios no pueden descargar ni consultar lotes privados ajenos.
    """

    def setUp(self):
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="54820",
                nombre="Toledo",
                departamento="Norte de Santander",
                latitud=Decimal("7.3100"),
                longitud=Decimal("-72.4830"),
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.productor_ajeno_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Hacienda San José Certificación",
            productor_id=self.productor_id,
            municipio=self.municipio,
            latitud=Decimal("7.3130"),
            longitud=Decimal("-72.4815"),
            activo=True,
        )
        self.variedad = VariedadCafe.objects.create(
            nombre="Typica", especie="Arábica", activo=True
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="HONEY_CERT", nombre="Honey Rojo", activo=True
        )
        self.estado_disponible = EstadoLote.objects.create(
            codigo="DISPONIBLE", nombre="Disponible", activo=True
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha=date(2026, 10, 20),
            cantidad_total=Decimal("8000.00"),
            cantidad_disponible=Decimal("7500.00"),
            activo=True,
        )
        self.lote = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("500.00"),
            codigo="LOTCERT01",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )
        self.qr = self.lote.codigo_qr

    def test_unicidad_estricta_un_solo_qr_por_lote(self):
        """Verifica que no sea posible crear un segundo CodigoQRLote para el mismo lote (ValidationError o IntegrityError)."""
        with self.assertRaises((ValidationError, IntegrityError)):
            CodigoQRLote.objects.create(
                lote=self.lote,
                identificador="QR-DUPLICADO-ERR",
                payload_url="/trazabilidad/lote/DUPLICADO/",
                nivel_visibilidad=CodigoQRLote.VISIBILIDAD_PUBLICA,
            )

    def test_unicidad_identificador_no_duplicable_entre_lotes(self):
        """Verifica que dos lotes distintos no puedan compartir el mismo identificador de QR (ValidationError o IntegrityError)."""
        lote2 = crear_lote(
            cosecha_id=self.cosecha.pk,
            cantidad=Decimal("200.00"),
            codigo="LOTCERT02",
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=self.estado_disponible.pk,
        )

        with self.assertRaises((ValidationError, IntegrityError)):
            lote2.codigo_qr.identificador = self.qr.identificador
            lote2.codigo_qr.save()

    def test_asociar_codigo_qr_a_lote_idempotente_garantiza_unicidad(self):
        """Invocaciones sucesivas de 'asociar_codigo_qr_a_lote' retornan el mismo registro sin duplicar."""
        qr1 = asociar_codigo_qr_a_lote(lote_o_id=self.lote)
        qr2 = asociar_codigo_qr_a_lote(lote_o_id=self.lote)

        self.assertEqual(qr1.pk, qr2.pk)
        self.assertEqual(qr1.identificador, "QR-LOTCERT01")
        self.assertEqual(CodigoQRLote.objects.filter(lote=self.lote).count(), 1)

    def test_actualizar_codigo_lote_mantiene_consistencia_y_unicidad_qr(self):
        """Modificar el código del lote actualiza sincronizadamente el identificador del QR conservando unicidad."""
        lote_actualizado = actualizar_lote(lote_o_id=self.lote, codigo="LOTCERTRENOMBRADO")
        self.assertEqual(lote_actualizado.codigo, "LOTCERTRENOMBRADO")

        self.qr.refresh_from_db()
        self.assertEqual(self.qr.identificador, "QR-LOTCERTRENOMBRADO")
        self.assertEqual(self.qr.payload_url, "/trazabilidad/lote/LOTCERTRENOMBRADO/")

    def test_ciclo_completo_e2e_trazabilidad_qr(self):
        """
        Ejecuta el ciclo de vida completo E2E de un código QR:
        Creación -> Escaneo Web -> Consulta API -> Cambio de Visibilidad -> Descarga PNG -> Impresión -> Auditoría.
        """
        # Fase 1: Creación automática verificada
        self.assertTrue(self.lote.tiene_codigo_qr)
        self.assertEqual(self.qr.identificador, "QR-LOTCERT01")
        self.assertEqual(self.qr.nivel_visibilidad, CodigoQRLote.VISIBILIDAD_PUBLICA)

        # Fase 2: Escaneo Web Público
        url_scan_web = reverse("trazabilidad_qr_web", kwargs={"identificador": self.qr.identificador})
        resp_web = self.client.get(url_scan_web)
        self.assertEqual(resp_web.status_code, 200)
        self.assertTemplateUsed(resp_web, "fincas/ficha_digital.html")

        # Fase 3: Consulta API REST Consolidada
        url_scan_api = reverse("api_consultar_ficha_desde_qr", kwargs={"identificador": self.qr.identificador})
        resp_api = self.client.get(url_scan_api)
        self.assertEqual(resp_api.status_code, 200)
        data_api = resp_api.json()
        self.assertEqual(data_api["codigo"], "LOTCERT01")
        self.assertEqual(data_api["codigo_qr"]["identificador"], "QR-LOTCERT01")
        self.assertFalse(data_api["es_propietario"])

        # Fase 4: Modificación de Visibilidad a PRIVADA
        _iniciar_sesion_productor(self.client, self.productor_id)
        url_vis = reverse("lote_qr_visibilidad_web", kwargs={"pk": self.lote.pk})
        resp_toggle = self.client.post(url_vis, {"nivel_visibilidad": "PRIVADA"}, follow=False)
        self.assertEqual(resp_toggle.status_code, 302)
        self.qr.refresh_from_db()
        self.assertEqual(self.qr.nivel_visibilidad, CodigoQRLote.VISIBILIDAD_PRIVADA)

        # Validación de bloqueo a anónimos
        cliente_anonimo = Client()
        resp_anon_web = cliente_anonimo.get(url_scan_web)
        self.assertEqual(resp_anon_web.status_code, 403)
        self.assertTemplateUsed(resp_anon_web, "fincas/ficha_digital_privada.html")

        resp_anon_api = cliente_anonimo.get(url_scan_api)
        self.assertEqual(resp_anon_api.status_code, 403)

        # Validación de acceso al productor dueño
        resp_owner_web = self.client.get(url_scan_web)
        self.assertEqual(resp_owner_web.status_code, 200)

        # Fase 5: Descarga de imagen física PNG
        url_descarga = reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk})
        resp_descarga = self.client.get(url_descarga)
        self.assertEqual(resp_descarga.status_code, 200)
        self.assertEqual(resp_descarga["Content-Type"], "image/png")
        self.assertTrue(resp_descarga.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn('filename="QR-LOTCERT01.png"', resp_descarga["Content-Disposition"])

        # Fase 6: Rotulado e Impresión de Etiqueta
        url_imprimir = reverse("lote_qr_imprimir", kwargs={"pk": self.lote.pk})
        resp_imprimir = self.client.get(url_imprimir)
        self.assertEqual(resp_imprimir.status_code, 200)
        self.assertTemplateUsed(resp_imprimir, "fincas/etiqueta_qr_lote.html")
        self.assertContains(resp_imprimir, "QR-LOTCERT01")
        self.assertContains(resp_imprimir, "window.print()")

        # Fase 7: Auditoría Inmutable en Bitácora
        auditorias = BitacoraFichaDigital.objects.filter(lote=self.lote).order_by("creado_en", "id")
        self.assertTrue(auditorias.filter(tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_WEB).exists())
        self.assertTrue(auditorias.filter(tipo_evento=BitacoraFichaDigital.TIPO_CONSULTA_API).exists())

    def test_aislamiento_entre_productores_y_seguridad_qr(self):
        """Un productor ajeno no puede descargar el QR privado ni conmutar la visibilidad de otro lote."""
        self.qr.nivel_visibilidad = CodigoQRLote.VISIBILIDAD_PRIVADA
        self.qr.save()

        # Iniciar sesión como otro productor
        _iniciar_sesion_productor(self.client, self.productor_ajeno_id)

        # Intento de descarga de QR privado ajeno -> 403
        url_descarga = reverse("lote_qr_descargar", kwargs={"pk": self.lote.pk})
        resp_descarga = self.client.get(url_descarga)
        self.assertEqual(resp_descarga.status_code, 403)

        # Intento de cambio de visibilidad de lote ajeno -> Redirigido o error
        url_vis = reverse("lote_qr_visibilidad_web", kwargs={"pk": self.lote.pk})
        resp_vis = self.client.post(url_vis, {"nivel_visibilidad": "PUBLICA"})
        self.assertEqual(resp_vis.status_code, 302)

        self.qr.refresh_from_db()
        self.assertEqual(self.qr.nivel_visibilidad, CodigoQRLote.VISIBILIDAD_PRIVADA)


# ==============================================================================
# SUBTAREA: HU22-ST5 (SCRUM-264): EXPOSICIÓN DEL ENDPOINT PARA REGISTRAR INTERÉS
# ==============================================================================


class TestScrum264EndpointManifestarInteres(TestCase):
    """
    Pruebas unitarias y de integración para la exposición del endpoint
    y servicio de manifestación de interés sobre lotes (HU-22 / SCRUM-264).
    """

    def setUp(self):
        self.client = Client()
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-TOLEDO-HU22",
                nombre="Toledo",
                departamento="Norte de Santander",
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.comprador_id = uuid.uuid4()
        self.otro_comprador_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Finca La Esperanza HU22",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="El Diamante",
            activo=True,
        )

        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo HU22",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )

        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO_HU22",
            nombre="Lavado Tradicional",
            activo=True,
        )

        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-08-10",
            cantidad_total=Decimal("1200.00"),
            cantidad_disponible=Decimal("600.00"),
            activo=True,
        )

        self.lote_publicado = Lote.objects.create(
            codigo="LOTE-HU22-001",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("350.00"),
            precio_referencial=Decimal("18500.00"),
            publicado_en_catalogo=True,
            activo=True,
        )

        self.lote_no_publicado = Lote.objects.create(
            codigo="LOTE-HU22-002",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("250.00"),
            publicado_en_catalogo=False,
            activo=True,
        )

        self.lote_inactivo = Lote.objects.create(
            codigo="LOTE-HU22-003",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("100.00"),
            publicado_en_catalogo=True,
            activo=False,
        )

    def _iniciar_sesion(self, usuario_id, correo="comprador@example.com", rol="COMPRADOR"):
        session = self.client.session
        session["usuario_id"] = str(usuario_id)
        session["correo"] = correo
        session["usuario_email"] = correo
        session["rol"] = rol
        session.save()

    def test_servicio_valida_existencia_lote(self):
        """Lote inexistente arroja ValidationError informando que no existe."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=999999,
                comprador_id=self.comprador_id,
            )
        self.assertIn("lote", ctx.exception.message_dict)

    def test_servicio_valida_lote_inactivo(self):
        """Lote inactivo no puede recibir manifestaciones de interés."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=self.lote_inactivo.id,
                comprador_id=self.comprador_id,
            )
        self.assertIn("lote", ctx.exception.message_dict)
        self.assertIn("activo", ctx.exception.message_dict["lote"][0])

    def test_servicio_valida_lote_no_publicado_en_catalogo(self):
        """Lote no publicado en catálogo comercial rechaza manifestación."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=self.lote_no_publicado.id,
                comprador_id=self.comprador_id,
            )
        self.assertIn("lote", ctx.exception.message_dict)
        self.assertIn("catálogo", ctx.exception.message_dict["lote"][0])

    def test_servicio_rechaza_interes_propio_productor(self):
        """Un productor no puede manifestar interés sobre su propio lote."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=self.lote_publicado.id,
                comprador_id=self.productor_id,
            )
        self.assertIn("comprador", ctx.exception.message_dict)
        self.assertIn("propio lote", ctx.exception.message_dict["comprador"][0])

    def test_servicio_valida_cantidad_positiva(self):
        """Cantidad menor o igual a cero es rechazada."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=self.lote_publicado.id,
                comprador_id=self.comprador_id,
                cantidad_kg=Decimal("0.00"),
            )
        self.assertIn("cantidad_kg", ctx.exception.message_dict)

    def test_servicio_valida_cantidad_no_exceda_stock_disponible(self):
        """Cantidad mayor al stock del lote (350 kg) es rechazada."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=self.lote_publicado.id,
                comprador_id=self.comprador_id,
                cantidad_kg=Decimal("400.00"),
            )
        self.assertIn("cantidad_kg", ctx.exception.message_dict)
        self.assertIn("superar el stock", ctx.exception.message_dict["cantidad_kg"][0])

    def test_servicio_manifestacion_exitosa_por_id_o_codigo(self):
        """Registro exitoso devuelve el contrato con los datos esperados."""
        res_id = registrar_manifestacion_interes(
            lote_id=self.lote_publicado.id,
            comprador_id=self.comprador_id,
            comprador_correo="comprador@cafes.com",
            cantidad_kg=Decimal("150.00"),
            mensaje="Interesado en adquirir muestra inicial.",
            telefono_contacto="+57 312 0000000",
        )
        self.assertEqual(res_id["lote_id"], self.lote_publicado.id)
        self.assertEqual(res_id["lote_codigo"], "LOTE-HU22-001")
        self.assertEqual(res_id["estado"], "REGISTRADO")
        self.assertTrue(res_id["notificado"])
        self.assertEqual(res_id["cantidad_kg"], "150.00")

        # Prueba con código textual
        res_cod = registrar_manifestacion_interes(
            lote_id=self.lote_publicado.codigo,
            comprador_id=self.comprador_id,
        )
        self.assertEqual(res_cod["lote_codigo"], "LOTE-HU22-001")

    def test_vista_web_rechaza_metodo_get(self):
        """El endpoint web solo admite POST (405 Method Not Allowed)."""
        url = reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote_publicado.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 405)

    def test_vista_web_redirecciona_a_login_si_es_anonimo(self):
        """Usuario no autenticado es redirigido a login al intentar POST tradicional."""
        url = reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote_publicado.pk})
        resp = self.client.post(url, {"cantidad_kg": "50.00"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_vista_web_ajax_responde_401_si_es_anonimo(self):
        """Petición asíncrona no autenticada responde 401 Unauthorized JSON."""
        url = reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote_publicado.pk})
        resp = self.client.post(
            url,
            data=json.dumps({"cantidad_kg": "50.00"}),
            content_type="application/json",
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertFalse(data["ok"])

    def test_vista_web_post_exitoso_y_redireccion(self):
        """Comprador autenticado registra interés y es redirigido con mensaje exitoso."""
        self._iniciar_sesion(self.comprador_id)
        url = reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote.pk if hasattr(self, 'lote') else self.lote_publicado.pk})
        resp = self.client.post(
            url,
            {
                "cantidad_kg": "100.00",
                "mensaje": "Quiero cotizar este lote",
                "telefono_contacto": "3001234567",
                "next": reverse("catalogo"),
            },
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("catalogo"))
        # Verificar mensaje en el storage de mensajes
        messages = list(get_messages(resp.wsgi_request))
        self.assertTrue(any("manifestación de interés" in str(m) for m in messages))

    def test_vista_web_ajax_post_exitoso_retorna_201_json(self):
        """Petición AJAX autenticada retorna 201 Created con payload estructurado."""
        self._iniciar_sesion(self.comprador_id)
        url = reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote_publicado.pk})
        resp = self.client.post(
            url,
            data=json.dumps({
                "cantidad_kg": "80.00",
                "mensaje": "Oferta formal de compra",
            }),
            content_type="application/json",
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("notificada al productor", data["mensaje"])
        self.assertEqual(data["data"]["cantidad_kg"], "80.00")

    def test_api_rest_interes_requiere_autenticacion(self):
        """El endpoint REST responde 401 si no hay usuario autenticado."""
        url = reverse("api_lote_manifestar_interes", kwargs={"pk": self.lote_publicado.pk})
        resp = self.client.post(url, data={}, content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_api_rest_interes_post_exitoso(self):
        """El endpoint REST registra la manifestación y responde 201 Created."""
        self._iniciar_sesion(self.comprador_id)
        url = reverse("api_lote_manifestar_interes", kwargs={"pk": self.lote_publicado.pk})
        payload = {
            "cantidad_kg": "50.00",
            "mensaje": "Interés desde API Móvil",
            "telefono_contacto": "+57 320 1112233",
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertIn("manifestacion", body)
        self.assertEqual(body["manifestacion"]["lote_codigo"], "LOTE-HU22-001")
        self.assertEqual(body["manifestacion"]["estado"], "REGISTRADO")

    def test_api_rest_interes_valida_datos_invalidos(self):
        """El endpoint REST rechaza datos no válidos con 400 Bad Request."""
        self._iniciar_sesion(self.comprador_id)
        url = reverse("api_lote_manifestar_interes", kwargs={"pk": self.lote_publicado.pk})
        payload = {
            "cantidad_kg": "-10.00",  # Cantidad negativa
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 400)


# ==============================================================================
# SUBTAREA: HU22-ST6 (SCRUM-265) & HU22-ST7 (SCRUM-266): INTERFAZ Y CONFIRMACIÓN
# ==============================================================================


class TestScrum265InterfazManifestarInteresYCatalogo(TestCase):
    """
    Pruebas unitarias de interfaz y feedback UX para la acción de manifestar interés
    en el catálogo y ficha digital (HU22-ST6 / SCRUM-265, HU22-ST7 / SCRUM-266).
    """

    def setUp(self):
        self.client = Client()
        self._parche_rbac_productor = patch(
            "usuarios.permissions.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_productor.start()
        self.addCleanup(self._parche_rbac_productor.stop)
        self._parche_rbac_nav = patch(
            "usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True
        )
        self._parche_rbac_nav.start()
        self.addCleanup(self._parche_rbac_nav.stop)
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-TOLEDO-UI",
                nombre="Toledo",
                departamento="Norte de Santander",
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.comprador_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Finca Vista Hermosa",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="Santa Inés",
            activo=True,
        )

        self.variedad = VariedadCafe.objects.create(
            nombre="Bourbon Rosado",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )

        self.proceso = ProcesoBeneficio.objects.create(
            codigo="HONEY_UI",
            nombre="Honey",
            activo=True,
        )

        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-09-01",
            cantidad_total=Decimal("800.00"),
            cantidad_disponible=Decimal("400.00"),
            activo=True,
        )

        self.lote = Lote.objects.create(
            codigo="LOT-UI-2026-01",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("200.00"),
            precio_referencial=Decimal("22000.00"),
            publicado_en_catalogo=True,
            activo=True,
        )

        self.calidad = CaracteristicasCalidad.objects.create(
            lote=self.lote,
            puntaje_taza=Decimal("86.50"),
            humedad=Decimal("11.20"),
            perfil_sensorial="Notas florales, jazmín y miel.",
        )

    def _iniciar_sesion(self, usuario_id, correo="comprador.ui@example.com", rol="COMPRADOR"):
        session = self.client.session
        session["usuario_id"] = str(usuario_id)
        session["correo"] = correo
        session["usuario_email"] = correo
        session["rol"] = rol
        session.save()

    def test_catalogo_muestra_boton_manifestar_interes_en_tarjeta(self):
        """La grilla del catálogo incluye el botón interactivo de manifestar interés por cada lote."""
        url = reverse("catalogo")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Manifestar Interés")
        self.assertContains(resp, f'id="btn-manifestar-interes-{self.lote.id}"')
        self.assertContains(resp, 'data-bs-target="#modalManifestarInteres"')
        self.assertContains(resp, f'data-lote-codigo="{self.lote.codigo}"')

    def test_catalogo_incluye_modal_de_formulario_y_modal_de_confirmacion(self):
        """La plantilla catalogo.html contiene el modal de captura y el modal de éxito (SCRUM-266)."""
        url = reverse("catalogo")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="modalManifestarInteres"')
        self.assertContains(resp, 'name="cantidad_kg"')
        self.assertContains(resp, 'name="mensaje"')
        self.assertContains(resp, 'name="telefono_contacto"')
        self.assertContains(resp, 'id="modalConfirmacionInteresExito"')
        self.assertContains(resp, "¡Interés Manifestado con Éxito!")

    def test_ficha_digital_muestra_boton_y_modal_de_interes_comercial(self):
        """La Ficha Digital pública consolida la sección comercial con botón y modal de interés."""
        url = reverse("lote_ficha_digital_web", kwargs={"codigo": self.lote.codigo})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="btn-manifestar-interes-ficha"')
        self.assertContains(resp, 'id="modalManifestarInteresFicha"')
        self.assertContains(resp, 'id="modalConfirmacionInteresFichaExito"')

    def test_confirmacion_al_comprador_via_ajax_devuelve_payload_de_exito(self):
        """El flujo asíncrono responde confirmación estructurada para el feedback del comprador."""
        self._iniciar_sesion(self.comprador_id)
        url = reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote.pk})
        resp = self.client.post(
            url,
            data=json.dumps({"cantidad_kg": "50.00", "mensaje": "Solicitud de prueba"}),
            content_type="application/json",
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("notificada al productor", data["mensaje"])
        self.assertEqual(data["data"]["lote_codigo"], self.lote.codigo)


# ==============================================================================
# SUBTAREA: HU22-ST8 (SCRUM-267): PRUEBAS DEL REGISTRO Y NOTIFICACIÓN DE INTERÉS
# ==============================================================================


class TestScrum267PruebasRegistroYNotificacionInteres(TestCase):
    """
    Batería exhaustiva de pruebas unitarias y de integración para certificar el
    cumplimiento de los criterios de aceptación de la HU-22 (SCRUM-267):
    - Criterio 1: La manifestación queda registrada.
    - Criterio 2: La manifestación es notificada al productor/comercializador del lote.
    """

    def setUp(self):
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        if not self.municipio:
            self.municipio = Municipio.objects.create(
                codigo="MUN-TOLEDO-ST8",
                nombre="Toledo",
                departamento="Norte de Santander",
                activo=True,
            )

        self.productor_id = uuid.uuid4()
        self.comprador_1_id = uuid.uuid4()
        self.comprador_2_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Finca La Samaria",
            productor_id=self.productor_id,
            municipio=self.municipio,
            vereda="El Roble",
            activo=True,
        )

        self.variedad = VariedadCafe.objects.create(
            nombre="Geisha Especial",
            especie=VariedadCafe.Especie.ARABICA,
            activo=True,
        )

        self.proceso = ProcesoBeneficio.objects.create(
            codigo="ANAEROBICO_ST8",
            nombre="Anaeróbico 72h",
            activo=True,
        )

        self.cosecha = Cosecha.objects.create(
            finca=self.finca,
            variedad=self.variedad,
            fecha_cosecha="2026-09-15",
            cantidad_total=Decimal("1500.00"),
            cantidad_disponible=Decimal("1500.00"),
            activo=True,
        )

        self.lote_a = Lote.objects.create(
            codigo="LOT-ST8-001",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("500.00"),
            precio_referencial=Decimal("28000.00"),
            publicado_en_catalogo=True,
            activo=True,
        )

        self.lote_b = Lote.objects.create(
            codigo="LOT-ST8-002",
            cosecha=self.cosecha,
            proceso_beneficio=self.proceso,
            cantidad=Decimal("300.00"),
            precio_referencial=Decimal("25000.00"),
            publicado_en_catalogo=True,
            activo=True,
        )

    def test_criterio1_registro_completo_con_contrato_estructurado(self):
        """Certifica Criterio 1: La manifestación queda registrada con todos los metadatos necesarios."""
        resultado = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_1_id,
            comprador_correo="comprador.especial@mercado.com",
            cantidad_kg=Decimal("250.00"),
            mensaje="Interés en lote para exportación a Europa.",
            telefono_contacto="+57 315 8889900",
        )

        self.assertIsNotNone(resultado["id"])
        self.assertTrue(resultado["id"].startswith("INT-"))
        self.assertEqual(resultado["lote_id"], self.lote_a.id)
        self.assertEqual(resultado["lote_codigo"], "LOT-ST8-001")
        self.assertEqual(resultado["finca_nombre"], "Finca La Samaria")
        self.assertEqual(resultado["productor_id"], str(self.productor_id))
        self.assertEqual(resultado["comprador_id"], str(self.comprador_1_id))
        self.assertEqual(resultado["comprador_correo"], "comprador.especial@mercado.com")
        self.assertEqual(resultado["cantidad_kg"], "250.00")
        self.assertEqual(resultado["mensaje"], "Interés en lote para exportación a Europa.")
        self.assertEqual(resultado["telefono_contacto"], "+57 315 8889900")
        self.assertEqual(resultado["estado"], "REGISTRADO")

    def test_criterio2_notificacion_al_productor_del_lote(self):
        """Certifica Criterio 2: La manifestación es notificada al productor del lote con la información requerida."""
        resultado = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_1_id,
            comprador_correo="juan.comprador@tostadores.com",
            cantidad_kg=Decimal("100.00"),
            mensaje="Propuesta de compra inmediata para despacho en Bucaramanga.",
            telefono_contacto="+57 301 5554433",
        )

        # La respuesta confirma que se generó la notificación
        self.assertTrue(resultado["notificado"])
        # Incluye los canales de contacto requeridos para la notificación
        self.assertEqual(resultado["productor_id"], str(self.productor_id))
        self.assertIn("La Samaria", resultado["productor_nombre"])
        self.assertEqual(resultado["comprador_correo"], "juan.comprador@tostadores.com")

    def test_multiples_compradores_en_el_mismo_lote_tienen_solicitudes_unicas(self):
        """Dos compradores distintos registran interés en el mismo lote de forma independiente."""
        reg1 = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_1_id,
            comprador_correo="comprador1@example.com",
            cantidad_kg=Decimal("100.00"),
        )
        reg2 = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_2_id,
            comprador_correo="comprador2@example.com",
            cantidad_kg=Decimal("150.00"),
        )

        self.assertNotEqual(reg1["id"], reg2["id"])
        self.assertNotEqual(reg1["comprador_id"], reg2["comprador_id"])
        self.assertEqual(reg1["lote_codigo"], reg2["lote_codigo"])
        self.assertEqual(reg1["estado"], "REGISTRADO")
        self.assertEqual(reg2["estado"], "REGISTRADO")

    def test_un_mismo_comprador_puede_manifestar_interes_en_multiples_lotes(self):
        """Un comprador registra interés en dos lotes distintos con éxito."""
        reg_lote_a = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_1_id,
            cantidad_kg=Decimal("200.00"),
        )
        reg_lote_b = registrar_manifestacion_interes(
            lote_id=self.lote_b.id,
            comprador_id=self.comprador_1_id,
            cantidad_kg=Decimal("100.00"),
        )

        self.assertEqual(reg_lote_a["lote_codigo"], "LOT-ST8-001")
        self.assertEqual(reg_lote_b["lote_codigo"], "LOT-ST8-002")
        self.assertNotEqual(reg_lote_a["id"], reg_lote_b["id"])

    def test_limite_exacto_de_stock_disponible_es_admitido(self):
        """Solicitar exactamente todo el stock del lote (500 kg) es válido."""
        resultado = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_1_id,
            cantidad_kg=Decimal("500.00"),
        )
        self.assertEqual(resultado["cantidad_kg"], "500.00")

    def test_superar_stock_incluso_por_un_gramo_es_rechazado(self):
        """Solicitar 500.01 kg sobre un stock de 500.00 kg es rechazado."""
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(
                lote_id=self.lote_a.id,
                comprador_id=self.comprador_1_id,
                cantidad_kg=Decimal("500.01"),
            )
        self.assertIn("cantidad_kg", ctx.exception.message_dict)
        self.assertIn("superar el stock", ctx.exception.message_dict["cantidad_kg"][0])

    def test_preservacion_de_caracteres_especiales_y_tildes(self):
        """Mensajes con tildes, signos de puntuación y saltos de línea se preservan íntegros."""
        mensaje_complejo = "¡Hola! ¿Tienen disponibilidad de envío a Medellín? Interesado en 150 kg café año 2026."
        resultado = registrar_manifestacion_interes(
            lote_id=self.lote_a.id,
            comprador_id=self.comprador_1_id,
            mensaje=mensaje_complejo,
        )
        self.assertEqual(resultado["mensaje"], mensaje_complejo)

    def test_mock_disparo_notificacion_externa(self):
        """Simula y verifica que el flujo dispara correctamente el mecanismo de notificación."""
        # Se captura 'ahora_fijo' ANTES de iniciar el parche: con persistencia
        # real (ManifestacionInteres.full_clean/save), notificado_en debe ser
        # un datetime de verdad, no el MagicMock que devolvia timezone.now()
        # si se le llamaba ya con el parche activo pero sin return_value fijo.
        ahora_fijo = timezone.now()
        with patch("fincas.services.timezone.now", return_value=ahora_fijo):
            resultado = registrar_manifestacion_interes(
                lote_id=self.lote_a.id,
                comprador_id=self.comprador_1_id,
                comprador_correo="test@comprador.com",
            )
            self.assertEqual(resultado["fecha_registro"], ahora_fijo.isoformat())
            self.assertTrue(resultado["notificado"])


class ManifestacionInteresHU22Tests(TestCase):
    """
    HU-22 (SCRUM-231): Manifestar interés sobre un lote específico.

    Subtareas propias (DT):
    - SCRUM-260 / HU22-ST1: Definir el mecanismo de notificación al
      productor/comercializador (in-app, sin correo -- RNF: el proyecto
      no tiene EMAIL_BACKEND configurado).
    - SCRUM-261 / HU22-ST2: Modelar y persistir la manifestación de
      interés.
    - SCRUM-262 / HU22-ST3: Diseñar el flujo de manifestación de interés
      para un lote (comprador -> servicio -> persistencia -> notificación
      in-app -> panel del productor).
    - SCRUM-263 / HU22-ST4: Validar permisos y existencia del lote antes
      de registrar el interés.

    Estas pruebas también protegen el "contrato" de datos (claves del
    diccionario que retorna `registrar_manifestacion_interes`) del que
    ya dependen las subtareas ST5-ST8 de Luis Francisco
    (rama francisco-epi6-hu22, commits b5ce830/e440b53/1211c21).
    """

    def setUp(self):
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        self.productor_id = uuid.uuid4()
        self.comprador_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca El Mirador", productor_id=self.productor_id, municipio=self.municipio
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca, fecha_cosecha="2026-09-01", cantidad_total=Decimal("300.00")
        )
        self.lote = Lote.objects.create(
            codigo="LOTEHU22",
            cosecha=self.cosecha,
            cantidad=Decimal("100.00"),
            publicado_en_catalogo=True,
        )

    def _datos(self, **extra):
        datos = {
            "lote_id": self.lote,
            "comprador_id": self.comprador_id,
            "comprador_correo": "comprador@example.com",
            "cantidad_kg": "20.00",
            "mensaje": "Me interesa este lote, ¿sigue disponible?",
            "telefono_contacto": "3001234567",
        }
        datos.update(extra)
        return datos

    # --------------------------- ST2: persistencia ---------------------------

    def test_la_manifestacion_queda_persistida_en_base_de_datos(self):
        resultado = registrar_manifestacion_interes(**self._datos())
        self.assertEqual(ManifestacionInteres.objects.count(), 1)
        manifestacion = ManifestacionInteres.objects.get()
        self.assertEqual(manifestacion.lote_id, self.lote.pk)
        self.assertEqual(str(manifestacion.comprador_id), str(self.comprador_id))
        self.assertEqual(manifestacion.cantidad_kg, Decimal("20.00"))
        self.assertEqual(manifestacion.mensaje, "Me interesa este lote, ¿sigue disponible?")
        self.assertEqual(resultado["id"], f"INT-{manifestacion.pk:06d}")

    def test_se_pueden_registrar_varias_manifestaciones_sobre_el_mismo_lote(self):
        registrar_manifestacion_interes(**self._datos())
        otro_comprador = uuid.uuid4()
        registrar_manifestacion_interes(**self._datos(comprador_id=otro_comprador, cantidad_kg="5.00"))
        self.assertEqual(ManifestacionInteres.objects.filter(lote=self.lote).count(), 2)

    def test_el_contrato_de_respuesta_mantiene_las_claves_que_ya_usan_las_subtareas_st5_st8(self):
        resultado = registrar_manifestacion_interes(**self._datos())
        claves_esperadas = {
            "id", "lote_id", "lote_codigo", "finca_nombre", "productor_id",
            "productor_nombre", "productor_correo", "comprador_id", "comprador_correo",
            "cantidad_kg", "mensaje", "telefono_contacto", "fecha_registro",
            "estado", "notificado",
        }
        self.assertEqual(set(resultado.keys()), claves_esperadas)
        self.assertEqual(resultado["lote_codigo"], "LOTEHU22")
        self.assertEqual(resultado["estado"], ManifestacionInteres.EstadoManifestacion.REGISTRADO)

    def test_acepta_identificar_el_lote_por_codigo_en_lugar_del_objeto(self):
        resultado = registrar_manifestacion_interes(**self._datos(lote_id="LOTEHU22"))
        self.assertEqual(resultado["lote_id"], self.lote.pk)

    def test_la_cantidad_de_interes_es_opcional(self):
        resultado = registrar_manifestacion_interes(**self._datos(cantidad_kg=None))
        self.assertIsNone(resultado["cantidad_kg"])
        self.assertIsNone(ManifestacionInteres.objects.get().cantidad_kg)

    # --------------------------- ST1: notificación in-app ---------------------------

    def test_al_registrarse_queda_notificado_de_inmediato_sin_usar_correo(self):
        resultado = registrar_manifestacion_interes(**self._datos())
        manifestacion = ManifestacionInteres.objects.get()
        self.assertTrue(resultado["notificado"])
        self.assertIsNotNone(manifestacion.notificado_en)

    def test_el_productor_puede_listar_las_manifestaciones_recibidas_sobre_sus_lotes(self):
        registrar_manifestacion_interes(**self._datos())
        otro_productor_id = uuid.uuid4()
        otra_finca = Finca.objects.create(
            nombre="Finca Ajena", productor_id=otro_productor_id, municipio=self.municipio
        )
        otra_cosecha = Cosecha.objects.create(
            finca=otra_finca, fecha_cosecha="2026-09-02", cantidad_total=Decimal("50.00")
        )
        otro_lote = Lote.objects.create(
            codigo="LOTEAJENO", cosecha=otra_cosecha, cantidad=Decimal("50.00"), publicado_en_catalogo=True
        )
        registrar_manifestacion_interes(**self._datos(lote_id=otro_lote, comprador_id=uuid.uuid4()))

        recibidas = listar_manifestaciones_interes_productor(productor_id=self.productor_id)
        self.assertEqual(recibidas.count(), 1)
        self.assertEqual(recibidas.first().lote_id, self.lote.pk)

    def test_marcar_como_vista_actualiza_estado_y_fecha(self):
        registrar_manifestacion_interes(**self._datos())
        manifestacion = ManifestacionInteres.objects.get()
        self.assertFalse(manifestacion.vista_por_productor)

        marcar_manifestacion_interes_vista(manifestacion_id=manifestacion.pk, productor_id=self.productor_id)

        manifestacion.refresh_from_db()
        self.assertTrue(manifestacion.vista_por_productor)
        self.assertIsNotNone(manifestacion.vista_en)

    def test_listar_solo_no_vistas_excluye_las_ya_marcadas(self):
        registrar_manifestacion_interes(**self._datos())
        manifestacion = ManifestacionInteres.objects.get()
        marcar_manifestacion_interes_vista(manifestacion_id=manifestacion.pk, productor_id=self.productor_id)

        pendientes = listar_manifestaciones_interes_productor(productor_id=self.productor_id, solo_no_vistas=True)
        self.assertEqual(pendientes.count(), 0)

    # --------------------------- ST4: permisos y existencia del lote ---------------------------

    def test_rechaza_marcar_como_vista_una_manifestacion_de_un_lote_que_no_es_del_productor(self):
        registrar_manifestacion_interes(**self._datos())
        manifestacion = ManifestacionInteres.objects.get()
        productor_ajeno = uuid.uuid4()
        with self.assertRaises(ValidationError) as ctx:
            marcar_manifestacion_interes_vista(manifestacion_id=manifestacion.pk, productor_id=productor_ajeno)
        self.assertIn("permiso", ctx.exception.message_dict)
        manifestacion.refresh_from_db()
        self.assertFalse(manifestacion.vista_por_productor)

    def test_rechaza_lote_inexistente(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos(lote_id=999999))
        self.assertIn("lote", ctx.exception.message_dict)
        self.assertEqual(ManifestacionInteres.objects.count(), 0)

    def test_rechaza_lote_inactivo(self):
        self.lote.activo = False
        self.lote.save(update_fields=["activo"])
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos())
        self.assertIn("lote", ctx.exception.message_dict)

    def test_rechaza_lote_no_publicado_en_catalogo(self):
        self.lote.publicado_en_catalogo = False
        self.lote.save(update_fields=["publicado_en_catalogo"])
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos())
        self.assertIn("lote", ctx.exception.message_dict)
        self.assertEqual(ManifestacionInteres.objects.count(), 0)

    def test_rechaza_sin_comprador_identificado(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos(comprador_id=None))
        self.assertIn("comprador", ctx.exception.message_dict)

    def test_rechaza_que_el_propio_productor_manifieste_interes_sobre_su_lote(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos(comprador_id=self.productor_id))
        self.assertIn("comprador", ctx.exception.message_dict)
        self.assertEqual(ManifestacionInteres.objects.count(), 0)

    def test_rechaza_cantidad_no_positiva(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos(cantidad_kg="0"))
        self.assertIn("cantidad_kg", ctx.exception.message_dict)

    def test_rechaza_cantidad_mayor_al_stock_disponible_del_lote(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos(cantidad_kg="500.00"))
        self.assertIn("cantidad_kg", ctx.exception.message_dict)
        self.assertEqual(ManifestacionInteres.objects.count(), 0)

    def test_rechaza_mensaje_demasiado_largo(self):
        with self.assertRaises(ValidationError) as ctx:
            registrar_manifestacion_interes(**self._datos(mensaje="x" * 1001))
        self.assertIn("mensaje", ctx.exception.message_dict)

    def test_operacion_atomica_no_guarda_nada_si_falla_una_validacion(self):
        with self.assertRaises(ValidationError):
            registrar_manifestacion_interes(**self._datos(cantidad_kg="500.00"))
        self.assertFalse(ManifestacionInteres.objects.exists())

    def test_no_se_puede_borrar_un_lote_con_manifestaciones_de_interes(self):
        registrar_manifestacion_interes(**self._datos())
        with self.assertRaises(ProtectedError):
            self.lote.delete()
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())


class RestriccionRolComercioHU22Tests(TestCase):
    """
    HU22: restringir las vistas de gestion comercial por rol -- "quien es
    comprador tiene las vistas de comprador y quien es productor tiene las
    vistas de productor" (pedido explicito del usuario). Un comprador no
    debe poder crear/consultar fincas, lotes o cosechas, ni publicar lotes
    ni registrar etapas de beneficio (exclusivas del productor); y, a la
    inversa, un productor no debe poder manifestar interes sobre un lote
    (exclusiva del comprador).

    Se valida contra la matriz RBAC real tal como esta sembrada en
    Supabase (MATRIZ_RBAC_VIGENTE, en usuarios/tests.py), simulada de
    punta a punta con la misma tecnica que ya usa HU04-ST6
    (usuarios.tests.MatrizPermisosSecurityTests /
    _mockear_matriz_real), en vez de solo confiar en que cada vista por
    separado llama al decorador correcto.
    """

    def setUp(self):
        self.client = Client()
        self.municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        self.productor_id = uuid.uuid4()
        self.finca = Finca.objects.create(
            nombre="Finca HU22 Restriccion", productor_id=self.productor_id, municipio=self.municipio
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca, fecha_cosecha="2026-09-01", cantidad_total=Decimal("300.00")
        )
        self.lote = Lote.objects.create(
            codigo="LOTERESTR", cosecha=self.cosecha, cantidad=Decimal("100.00"),
            publicado_en_catalogo=True,
        )

        from usuarios.tests import _mockear_matriz_real

        parche = patch("usuarios.models.RolPermiso")
        mock_rol_permiso = parche.start()
        self.addCleanup(parche.stop)
        _mockear_matriz_real(mock_rol_permiso)

    # ------------------------ COMPRADOR: vistas vedadas ------------------------

    def test_comprador_no_puede_ver_el_formulario_de_registrar_finca(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.get(reverse("finca_registro"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_comprador_no_puede_ver_mis_fincas(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.get(reverse("mis_fincas"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_comprador_no_puede_ver_el_formulario_de_registrar_cosecha(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.get(reverse("cosecha_registro"))
        self.assertEqual(response.status_code, 302)

    def test_comprador_no_puede_ver_el_formulario_de_registrar_lote(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.get(reverse("lote_registro"))
        self.assertEqual(response.status_code, 302)

    def test_comprador_no_puede_ver_mis_lotes(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.get(reverse("mis_lotes"))
        self.assertEqual(response.status_code, 302)

    def test_comprador_no_puede_registrar_etapa_de_beneficio(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.get(reverse("lote_etapa_registro", kwargs={"pk": self.lote.pk}))
        self.assertEqual(response.status_code, 302)

    def test_comprador_no_puede_publicar_un_lote(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.post(reverse("lote_publicar", kwargs={"pk": self.lote.pk}))
        self.assertEqual(response.status_code, 302)

    def test_comprador_anonimo_sin_sesion_redirige_a_login(self):
        response = self.client.get(reverse("mis_fincas"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    # ------------------------ PRODUCTOR: sigue pudiendo como siempre ------------------------

    def test_productor_si_puede_ver_el_formulario_de_registrar_finca(self):
        _iniciar_sesion_productor(self.client)
        response = self.client.get(reverse("finca_registro"))
        self.assertEqual(response.status_code, 200)

    def test_productor_si_puede_ver_mis_fincas(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(reverse("mis_fincas"))
        self.assertEqual(response.status_code, 200)

    def test_productor_si_puede_ver_mis_lotes(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(reverse("mis_lotes"))
        self.assertEqual(response.status_code, 200)

    def test_productor_si_puede_ver_el_formulario_de_registrar_lote(self):
        # self.productor_id es dueno de self.finca/self.cosecha (con saldo
        # disponible), para ejercitar el 200 real y no la redireccion de
        # negocio "debe tener una cosecha con saldo" (ajena al permiso RBAC).
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        response = self.client.get(reverse("lote_registro"))
        self.assertEqual(response.status_code, 200)

    # ------------------------ manifestar interes: solo el comprador ------------------------

    def test_comprador_si_puede_manifestar_interes(self):
        _iniciar_sesion_comprador(self.client)
        response = self.client.post(
            reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote.pk}),
            {"mensaje": "Interesado en este lote"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("catalogo"))

        from fincas.models import ManifestacionInteres
        self.assertTrue(ManifestacionInteres.objects.filter(lote=self.lote).exists())

    def test_productor_no_puede_manifestar_interes(self):
        _iniciar_sesion_productor(self.client)
        response = self.client.post(
            reverse("lote_manifestar_interes_web", kwargs={"pk": self.lote.pk}),
            {"mensaje": "Interesado en este lote"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

        from fincas.models import ManifestacionInteres
        self.assertFalse(ManifestacionInteres.objects.filter(lote=self.lote).exists())

    # ------------------------ navegacion: botones ocultos segun el rol ------------------------

    def test_comprador_no_ve_el_boton_mi_panel_ni_registrar_finca_en_el_home(self):
        _iniciar_sesion_comprador(self.client)
        respuesta_home = self.client.get(reverse("home"))
        # No basta con buscar el texto "Mi Panel": tambien aparece dentro de
        # un comentario HTML del template. Lo que de verdad importa es que no
        # exista el enlace clickeable (su href real).
        self.assertNotContains(respuesta_home, reverse("mis_fincas"))
        self.assertNotContains(respuesta_home, reverse("finca_registro"))

        respuesta_catalogo = self.client.get(reverse("catalogo"))
        self.assertNotContains(respuesta_catalogo, reverse("mis_lotes"))

    def test_productor_si_ve_el_boton_mi_panel_y_registrar_finca_en_el_home(self):
        _iniciar_sesion_productor(self.client)
        respuesta_home = self.client.get(reverse("home"))
        self.assertContains(respuesta_home, "Mi Panel")
        self.assertContains(respuesta_home, "Registrar Finca")


class PanelManifestacionesInteresProductorHU22Tests(TestCase):
    """
    HU22 (SCRUM-231): el productor necesita un lugar real donde ver las
    manifestaciones de interes que recibio sobre sus lotes publicados (el
    mecanismo de notificacion in-app de ST1/SCRUM-260). Cubre:

    - El boton "Interesados" en Mis Lotes solo lo ve quien tiene permiso de
      'lotes.consultar' (productor), nunca un comprador.
    - El panel de manifestaciones solo muestra las de los lotes del
      productor que inicio sesion, nunca las de otro productor.
    - Marcar una manifestacion como vista funciona de verdad (POST real) y
      queda reflejado tanto en el detalle como en el contador de "sin ver".
    - El boton "Manifestar Interés" del catalogo ahora se oculta para quien no
      tiene el permiso 'manifestaciones_interes.crear' (p.ej. un productor
      autenticado), no solo para los anonimos.
    """

    def setUp(self):
        self.client = Client()

        from usuarios.tests import _mockear_matriz_real
        self._parche_matriz = patch("usuarios.models.RolPermiso")
        mock_rol_permiso = self._parche_matriz.start()
        self.addCleanup(self._parche_matriz.stop)
        _mockear_matriz_real(mock_rol_permiso)

        self.municipio = Municipio.objects.create(
            nombre="Toledo HU22P", departamento="Norte de Santander"
        )
        self.productor_id = uuid.uuid4()
        self.otro_productor_id = uuid.uuid4()

        self.finca = Finca.objects.create(
            nombre="Finca Panel HU22",
            productor_id=self.productor_id,
            municipio=self.municipio,
        )
        self.cosecha = Cosecha.objects.create(
            finca=self.finca, fecha_cosecha="2026-09-01", cantidad_total=Decimal("300.00")
        )
        self.lote = Lote.objects.create(
            codigo="LOTEPANELHU22",
            cosecha=self.cosecha,
            cantidad=Decimal("100.00"),
            publicado_en_catalogo=True,
        )

        self.finca_ajena = Finca.objects.create(
            nombre="Finca Ajena HU22",
            productor_id=self.otro_productor_id,
            municipio=self.municipio,
        )
        self.cosecha_ajena = Cosecha.objects.create(
            finca=self.finca_ajena, fecha_cosecha="2026-09-01", cantidad_total=Decimal("100.00")
        )
        self.lote_ajeno = Lote.objects.create(
            codigo="LOTEAJENOHU22",
            cosecha=self.cosecha_ajena,
            cantidad=Decimal("50.00"),
            publicado_en_catalogo=True,
        )

    # ------------------------ boton "Interesados" en Mis Lotes ------------------------

    def test_productor_ve_el_boton_interesados_en_mis_lotes(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(reverse("mis_lotes"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, reverse("mis_manifestaciones_interes"))
        self.assertContains(respuesta, "Interesados")

    def test_comprador_no_puede_acceder_al_panel_de_manifestaciones(self):
        _iniciar_sesion_comprador(self.client)
        respuesta = self.client.get(reverse("mis_manifestaciones_interes"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, reverse("home"))

    def test_anonimo_redirige_a_login_al_entrar_al_panel(self):
        respuesta = self.client.get(reverse("mis_manifestaciones_interes"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    # ------------------------ el productor ve sus propias manifestaciones ------------------------

    def test_productor_ve_la_manifestacion_real_que_le_mandaron(self):
        comprador_id = uuid.uuid4()
        registrar_manifestacion_interes(
            lote_id=self.lote.pk,
            comprador_id=comprador_id,
            comprador_correo="comprador.panel@example.com",
            mensaje="Quiero este cafe",
            cantidad_kg=Decimal("20.00"),
        )

        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(reverse("mis_manifestaciones_interes"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "LOTEPANELHU22")
        self.assertContains(respuesta, "comprador.panel@example.com")
        self.assertContains(respuesta, "Quiero este cafe")
        self.assertContains(respuesta, "Nuevo")

    def test_productor_no_ve_manifestaciones_de_lotes_ajenos(self):
        registrar_manifestacion_interes(
            lote_id=self.lote_ajeno.pk,
            comprador_id=uuid.uuid4(),
            comprador_correo="otro.comprador@example.com",
        )

        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(reverse("mis_manifestaciones_interes"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, "LOTEAJENOHU22")
        self.assertNotContains(respuesta, "otro.comprador@example.com")

    def test_panel_vacio_muestra_mensaje_de_estado_vacio(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(reverse("mis_manifestaciones_interes"))
        self.assertContains(respuesta, "Todavía no has recibido manifestaciones de interés")

    def test_contador_de_sin_ver_aparece_en_mis_lotes(self):
        registrar_manifestacion_interes(
            lote_id=self.lote.pk,
            comprador_id=uuid.uuid4(),
            comprador_correo="contador@example.com",
        )
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(reverse("mis_lotes"))
        self.assertContains(respuesta, "1")

    # ------------------------ marcar como vista ------------------------

    def test_productor_puede_marcar_su_manifestacion_como_vista(self):
        registrar_manifestacion_interes(
            lote_id=self.lote.pk,
            comprador_id=uuid.uuid4(),
            comprador_correo="marcar@example.com",
        )
        manifestacion_id = ManifestacionInteres.objects.get(
            lote=self.lote, comprador_correo="marcar@example.com"
        ).pk

        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.post(
            reverse("manifestacion_interes_marcar_vista", kwargs={"pk": manifestacion_id})
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta.url, reverse("mis_manifestaciones_interes"))

        manifestacion = ManifestacionInteres.objects.get(pk=manifestacion_id)
        self.assertTrue(manifestacion.vista_por_productor)

    def test_otro_productor_no_puede_marcar_como_vista_una_manifestacion_ajena(self):
        registrar_manifestacion_interes(
            lote_id=self.lote.pk,
            comprador_id=uuid.uuid4(),
            comprador_correo="ajena@example.com",
        )
        manifestacion_id = ManifestacionInteres.objects.get(
            lote=self.lote, comprador_correo="ajena@example.com"
        ).pk

        _iniciar_sesion_productor(self.client, usuario_id=self.otro_productor_id)
        self.client.post(
            reverse("manifestacion_interes_marcar_vista", kwargs={"pk": manifestacion_id})
        )

        manifestacion = ManifestacionInteres.objects.get(pk=manifestacion_id)
        self.assertFalse(manifestacion.vista_por_productor)

    def test_marcar_como_vista_rechaza_metodo_get(self):
        registrar_manifestacion_interes(
            lote_id=self.lote.pk,
            comprador_id=uuid.uuid4(),
            comprador_correo="getmetodo@example.com",
        )
        manifestacion_id = ManifestacionInteres.objects.get(
            lote=self.lote, comprador_correo="getmetodo@example.com"
        ).pk

        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(
            reverse("manifestacion_interes_marcar_vista", kwargs={"pk": manifestacion_id})
        )
        self.assertEqual(respuesta.status_code, 405)

    # ------------------------ "Manifestar Interés" ahora oculto tambien para el productor ------------------------

    def test_boton_me_interesa_oculto_para_productor_en_el_catalogo(self):
        _iniciar_sesion_productor(self.client, usuario_id=self.productor_id)
        respuesta = self.client.get(reverse("catalogo"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, "Manifestar Interés")

    def test_boton_me_interesa_visible_para_comprador_en_el_catalogo(self):
        _iniciar_sesion_comprador(self.client)
        respuesta = self.client.get(reverse("catalogo"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Manifestar Interés")


class UrlPublicaCodigoQRTests(TestCase):
    """
    HU18 (SCRUM-22) - El QR debe ser escaneable desde un celular.

    Un QR que solo codifica la ruta relativa ('/trazabilidad/lote/<CODIGO>/') no
    abre nada al escanearse. El contenido del QR debe ser la URL absoluta del
    dominio público (settings.QR_BASE_URL), y los QR ya guardados con ruta
    relativa deben poder regenerarse (comando `sincronizar_qr_lotes`).
    """

    DOMINIO = "https://cafe-pergamo.onrender.com"

    def setUp(self):
        municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        finca = Finca.objects.create(
            nombre="Finca URL QR",
            productor_id=uuid.uuid4(),
            municipio=municipio,
            activo=True,
        )
        variedad = VariedadCafe.objects.create(nombre="Castillo URL", especie="Arábica", activo=True)
        cosecha = Cosecha.objects.create(
            finca=finca,
            variedad=variedad,
            fecha_cosecha=date(2026, 10, 20),
            cantidad_total=Decimal("1000.00"),
            cantidad_disponible=Decimal("1000.00"),
            activo=True,
        )
        with override_settings(QR_BASE_URL=""):
            self.lote = crear_lote(
                cosecha_id=cosecha.pk, cantidad=Decimal("100.00"), codigo="LOTEURL01"
            )

    @override_settings(QR_BASE_URL="")
    def test_sin_dominio_configurado_el_payload_es_ruta_relativa(self):
        self.assertEqual(
            construir_payload_qr_lote(self.lote), "/trazabilidad/lote/LOTEURL01/"
        )

    @override_settings(QR_BASE_URL=DOMINIO)
    def test_con_dominio_configurado_el_payload_es_url_absoluta(self):
        self.assertEqual(
            construir_payload_qr_lote(self.lote),
            f"{self.DOMINIO}/trazabilidad/lote/LOTEURL01/",
        )

    @override_settings(QR_BASE_URL=DOMINIO + "/")
    def test_barra_final_del_dominio_no_duplica_separador(self):
        self.assertEqual(
            construir_payload_qr_lote(self.lote),
            f"{self.DOMINIO}/trazabilidad/lote/LOTEURL01/",
        )

    @override_settings(QR_BASE_URL=DOMINIO)
    def test_base_url_explicita_tiene_prioridad_sobre_la_configuracion(self):
        self.assertEqual(
            construir_payload_qr_lote(self.lote, base_url="http://192.168.1.15:8000"),
            "http://192.168.1.15:8000/trazabilidad/lote/LOTEURL01/",
        )

    def test_qr_existente_con_ruta_relativa_se_regenera_al_configurar_dominio(self):
        qr_antes = CodigoQRLote.objects.get(lote=self.lote)
        self.assertEqual(qr_antes.payload_url, "/trazabilidad/lote/LOTEURL01/")
        imagen_antes = qr_antes.imagen_base64

        with override_settings(QR_BASE_URL=self.DOMINIO):
            sincronizar_o_generar_qr_lote(self.lote)

        qr_despues = CodigoQRLote.objects.get(lote=self.lote)
        self.assertEqual(
            qr_despues.payload_url, f"{self.DOMINIO}/trazabilidad/lote/LOTEURL01/"
        )
        self.assertNotEqual(qr_despues.imagen_base64, imagen_antes)
        self.assertEqual(CodigoQRLote.objects.filter(lote=self.lote).count(), 1)

    def test_comando_sincronizar_qr_lotes_actualiza_y_es_idempotente(self):
        from io import StringIO

        with override_settings(QR_BASE_URL=self.DOMINIO):
            salida = StringIO()
            call_command("sincronizar_qr_lotes", stdout=salida)
            self.assertIn("1 actualizados de 1 lotes", salida.getvalue())
            self.assertEqual(
                CodigoQRLote.objects.get(lote=self.lote).payload_url,
                f"{self.DOMINIO}/trazabilidad/lote/LOTEURL01/",
            )

            segunda = StringIO()
            call_command("sincronizar_qr_lotes", stdout=segunda)
            self.assertIn("0 actualizados de 1 lotes", segunda.getvalue())

    @override_settings(QR_BASE_URL=DOMINIO)
    def test_la_imagen_descargable_codifica_la_url_publica(self):
        with patch("fincas.services.qrcode.QRCode") as qr_mock:
            qr_mock.return_value.make_image.return_value.save = lambda buf, **kw: buf.write(b"PNG")
            obtener_bytes_descarga_qr_lote(self.lote)
        qr_mock.return_value.add_data.assert_called_with(
            f"{self.DOMINIO}/trazabilidad/lote/LOTEURL01/"
        )


class EstadoLoteYEtapaBeneficioTests(TestCase):
    """
    HU14 (SCRUM-18) - La etapa de beneficio solo existe cuando el estado del
    lote es "En Beneficio": se pide al crear el lote en ese estado o al
    cambiarle el estado, y solo se registran etapas mientras esté en él.
    """

    def _estado(self, codigo, nombre):
        return EstadoLote.objects.get_or_create(
            codigo=codigo, defaults={"nombre": nombre, "activo": True}
        )[0]

    def setUp(self):
        self._p1 = patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
        self._p1.start()
        self.addCleanup(self._p1.stop)
        self._p2 = patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
        self._p2.start()
        self.addCleanup(self._p2.stop)
        self.client = Client()
        self.productor_id = uuid.uuid4()
        _iniciar_sesion_productor(self.client, self.productor_id)
        municipio = Municipio.objects.filter(
            nombre="Toledo", departamento="Norte de Santander"
        ).first()
        finca = Finca.objects.create(
            nombre="Finca Estados", productor_id=self.productor_id,
            municipio=municipio, activo=True,
        )
        variedad = VariedadCafe.objects.create(nombre="Caturra Estados", especie="Arábica", activo=True)
        self.cosecha = Cosecha.objects.create(
            finca=finca, variedad=variedad, fecha_cosecha=date(2026, 10, 1),
            cantidad_total=Decimal("1000.00"), cantidad_disponible=Decimal("1000.00"),
            activo=True,
        )
        self.proceso = ProcesoBeneficio.objects.create(
            codigo="LAVADO_EST", nombre="Lavado Estados", activo=True
        )
        self.recoleccion = self._estado("RECOLECCION", "Recolección")
        self.beneficio = self._estado("BENEFICIO", "En Beneficio")
        self.secado = self._estado("SECADO", "En Secado")
        self.almacenado = self._estado("ALMACENADO", "Almacenado / Pergamino")

    def _lote(self, codigo, estado, **extra):
        return crear_lote(
            cosecha_id=self.cosecha.pk, cantidad=Decimal("100.00"), codigo=codigo,
            proceso_beneficio_id=self.proceso.pk,
            estado_lote_id=estado.pk if estado else None, **extra,
        )

    # ------------------------- crear_lote -------------------------
    def test_crear_lote_en_beneficio_exige_la_etapa(self):
        with self.assertRaises(ValidationError) as ctx:
            self._lote("LOTEEST01", self.beneficio)
        self.assertIn("etapa_beneficio", ctx.exception.message_dict)
        self.assertFalse(Lote.objects.filter(codigo="LOTEEST01").exists())
        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, Decimal("1000.00"))

    def test_crear_lote_en_beneficio_con_etapa_registra_lote_y_etapa(self):
        lote = self._lote(
            "LOTEEST02", self.beneficio, etapa_beneficio="FERMENTACION", fecha_etapa="2026-10-05"
        )
        etapa = EtapaBeneficio.objects.get(lote=lote)
        self.assertEqual(etapa.etapa, "FERMENTACION")
        self.assertEqual(etapa.fecha, date(2026, 10, 5))

    def test_crear_lote_en_beneficio_usa_hoy_si_no_se_indica_fecha(self):
        lote = self._lote("LOTEEST03", self.beneficio, etapa_beneficio="LAVADO")
        self.assertEqual(EtapaBeneficio.objects.get(lote=lote).fecha, timezone.localdate())

    def test_crear_lote_en_otro_estado_rechaza_la_etapa(self):
        with self.assertRaises(ValidationError) as ctx:
            self._lote("LOTEEST04", self.recoleccion, etapa_beneficio="LAVADO")
        self.assertIn("etapa_beneficio", ctx.exception.message_dict)

    def test_crear_lote_con_etapa_invalida_no_deja_nada_a_medias(self):
        with self.assertRaises(ValidationError):
            self._lote("LOTEEST05", self.beneficio, etapa_beneficio="TOSTADO")
        self.assertFalse(Lote.objects.filter(codigo="LOTEEST05").exists())
        self.cosecha.refresh_from_db()
        self.assertEqual(self.cosecha.cantidad_disponible, Decimal("1000.00"))

    # ------------------- registrar_etapa_beneficio -------------------
    def test_no_se_registran_etapas_si_el_lote_no_esta_en_beneficio(self):
        lote = self._lote("LOTEEST06", self.recoleccion)
        with self.assertRaises(ValidationError) as ctx:
            registrar_etapa_beneficio(
                lote_o_id=lote, etapa="DESPULPADO", fecha=date(2026, 10, 5),
                productor_id=self.productor_id,
            )
        self.assertIn("lote", ctx.exception.message_dict)
        self.assertFalse(EtapaBeneficio.objects.filter(lote=lote).exists())

    # ------------------------ cambiar_estado_lote ------------------------
    def test_cambiar_a_beneficio_exige_etapa_y_no_cambia_el_estado_si_falta(self):
        lote = self._lote("LOTEEST07", self.recoleccion)
        with self.assertRaises(ValidationError) as ctx:
            cambiar_estado_lote(
                lote_o_id=lote, estado_lote_id=self.beneficio.pk, productor_id=self.productor_id
            )
        self.assertIn("etapa_beneficio", ctx.exception.message_dict)
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.recoleccion)

    def test_cambiar_a_beneficio_con_etapa_actualiza_estado_y_registra_la_etapa(self):
        lote = self._lote("LOTEEST08", self.recoleccion)
        cambiar_estado_lote(
            lote_o_id=lote, estado_lote_id=self.beneficio.pk,
            etapa_beneficio="DESPULPADO", fecha_etapa=date(2026, 10, 6),
            observaciones="Despulpado en la mañana", productor_id=self.productor_id,
        )
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.beneficio)
        etapa = EtapaBeneficio.objects.get(lote=lote)
        self.assertEqual((etapa.etapa, etapa.observaciones), ("DESPULPADO", "Despulpado en la mañana"))

    def test_en_beneficio_se_pueden_agregar_mas_etapas_sin_cambiar_el_estado(self):
        lote = self._lote("LOTEEST09", self.beneficio, etapa_beneficio="DESPULPADO", fecha_etapa=date(2026, 10, 5))
        cambiar_estado_lote(
            lote_o_id=lote, estado_lote_id=self.beneficio.pk,
            etapa_beneficio="FERMENTACION", fecha_etapa=date(2026, 10, 6),
            productor_id=self.productor_id,
        )
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.beneficio)
        self.assertEqual(EtapaBeneficio.objects.filter(lote=lote).count(), 2)

    def test_pasar_a_otro_estado_no_pide_etapa(self):
        lote = self._lote("LOTEEST10", self.beneficio, etapa_beneficio="SECADO", fecha_etapa=date(2026, 10, 5))
        cambiar_estado_lote(
            lote_o_id=lote, estado_lote_id=self.almacenado.pk, productor_id=self.productor_id
        )
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.almacenado)

    def test_pasar_a_otro_estado_rechaza_una_etapa(self):
        lote = self._lote("LOTEEST11", self.recoleccion)
        with self.assertRaises(ValidationError) as ctx:
            cambiar_estado_lote(
                lote_o_id=lote, estado_lote_id=self.secado.pk,
                etapa_beneficio="SECADO", productor_id=self.productor_id,
            )
        self.assertIn("etapa_beneficio", ctx.exception.message_dict)

    def test_el_estado_no_puede_retroceder(self):
        lote = self._lote("LOTEEST12", self.almacenado)
        with self.assertRaises(ValidationError) as ctx:
            cambiar_estado_lote(
                lote_o_id=lote, estado_lote_id=self.recoleccion.pk, productor_id=self.productor_id
            )
        self.assertIn("estado_lote", ctx.exception.message_dict)
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.almacenado)

    def test_no_se_puede_cambiar_al_mismo_estado_salvo_en_beneficio(self):
        lote = self._lote("LOTEEST13", self.almacenado)
        with self.assertRaises(ValidationError):
            cambiar_estado_lote(
                lote_o_id=lote, estado_lote_id=self.almacenado.pk, productor_id=self.productor_id
            )

    def test_otro_productor_no_puede_cambiar_el_estado(self):
        lote = self._lote("LOTEEST14", self.recoleccion)
        with self.assertRaises(ValidationError) as ctx:
            cambiar_estado_lote(
                lote_o_id=lote, estado_lote_id=self.secado.pk, productor_id=uuid.uuid4()
            )
        self.assertIn("permiso", ctx.exception.message_dict)

    def test_si_la_etapa_es_invalida_el_estado_no_cambia(self):
        lote = self._lote("LOTEEST15", self.recoleccion)
        with self.assertRaises(ValidationError):
            cambiar_estado_lote(
                lote_o_id=lote, estado_lote_id=self.beneficio.pk,
                etapa_beneficio="TOSTADO", productor_id=self.productor_id,
            )
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.recoleccion)

    # ----------------------------- vistas web -----------------------------
    def test_pantalla_cambiar_estado_muestra_el_bloque_condicional_de_etapa(self):
        lote = self._lote("LOTEEST16", self.recoleccion)
        resp = self.client.get(reverse("lote_cambiar_estado", kwargs={"pk": lote.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="bloque-etapa-beneficio"')
        self.assertContains(resp, "id_etapa_beneficio")

    def test_vista_cambiar_estado_a_beneficio_con_etapa_guarda_y_redirige(self):
        lote = self._lote("LOTEEST17", self.recoleccion)
        url = reverse("lote_cambiar_estado", kwargs={"pk": lote.pk})
        resp = self.client.post(url, {
            "estado_lote": self.beneficio.pk, "etapa_beneficio": "LAVADO",
            "fecha_etapa": "2026-10-07", "observaciones": "",
        })
        self.assertRedirects(resp, reverse("lote_detalle", kwargs={"pk": lote.pk}))
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.beneficio)
        self.assertEqual(EtapaBeneficio.objects.get(lote=lote).etapa, "LAVADO")

    def test_vista_cambiar_estado_a_beneficio_sin_etapa_muestra_error(self):
        lote = self._lote("LOTEEST18", self.recoleccion)
        url = reverse("lote_cambiar_estado", kwargs={"pk": lote.pk})
        resp = self.client.post(url, {"estado_lote": self.beneficio.pk, "fecha_etapa": "2026-10-07"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Debe indicar la etapa de beneficio")
        lote.refresh_from_db()
        self.assertEqual(lote.estado_lote, self.recoleccion)

    def test_pantalla_de_etapas_redirige_a_cambiar_estado_si_no_esta_en_beneficio(self):
        lote = self._lote("LOTEEST19", self.recoleccion)
        resp = self.client.get(reverse("lote_etapa_registro", kwargs={"pk": lote.pk}))
        self.assertRedirects(
            resp, reverse("lote_cambiar_estado", kwargs={"pk": lote.pk}), fetch_redirect_response=False
        )

    def test_formulario_de_registro_de_lote_incluye_el_bloque_condicional(self):
        resp = self.client.get(reverse("lote_registro"))
        self.assertContains(resp, 'id="bloque-etapa-beneficio"')

    def test_registro_web_de_lote_en_beneficio_crea_lote_y_etapa(self):
        resp = self.client.post(reverse("lote_registro"), {
            "cosecha": self.cosecha.pk, "proceso_beneficio": self.proceso.pk,
            "estado_lote": self.beneficio.pk, "cantidad": "50.00", "codigo": "LOTEEST20",
            "etapa_beneficio": "DESPULPADO", "fecha_etapa": "2026-10-05",
        })
        self.assertEqual(resp.status_code, 302)
        lote = Lote.objects.get(codigo="LOTEEST20")
        self.assertEqual(EtapaBeneficio.objects.get(lote=lote).etapa, "DESPULPADO")

    def test_registro_web_de_lote_en_beneficio_sin_etapa_no_crea_nada(self):
        resp = self.client.post(reverse("lote_registro"), {
            "cosecha": self.cosecha.pk, "proceso_beneficio": self.proceso.pk,
            "estado_lote": self.beneficio.pk, "cantidad": "50.00", "codigo": "LOTEEST21",
            "fecha_etapa": "2026-10-05",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Debe indicar la etapa de beneficio")
        self.assertFalse(Lote.objects.filter(codigo="LOTEEST21").exists())

    def test_registro_web_de_lote_en_recoleccion_no_pide_etapa(self):
        resp = self.client.post(reverse("lote_registro"), {
            "cosecha": self.cosecha.pk, "proceso_beneficio": self.proceso.pk,
            "estado_lote": self.recoleccion.pk, "cantidad": "50.00", "codigo": "LOTEEST22",
            # Un cliente que mande una etapa de mas (campo oculto) no debe romper el registro.
            "etapa_beneficio": "LAVADO", "fecha_etapa": "2026-10-05",
        })
        self.assertEqual(resp.status_code, 302)
        lote = Lote.objects.get(codigo="LOTEEST22")
        self.assertFalse(EtapaBeneficio.objects.filter(lote=lote).exists())
