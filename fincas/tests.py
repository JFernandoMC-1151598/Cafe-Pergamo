"""
Pruebas Unitarias para HU-07: Registro de Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.

Criterios de Aceptación Verificados:
- Campos `latitud` y `longitud` tipo DecimalField opcionales en el modelo Finca.
- Nulabilidad a nivel de base de datos (null=True, blank=True).
- Validación de rango [-90, 90] para latitud y [-180, 180] para longitud.
- Persistencia de fincas tanto con coordenadas válidas como sin coordenadas (NULL).
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase, Client
from django.urls import reverse

from fincas.models import Finca
from fincas.forms import FincaRegistroForm, FincaModelForm, GeorreferenciacionFormMixin


class TestGeorreferenciacionModelo(TestCase):
    """Pruebas del modelo Finca y esquema de georreferenciación (HU07-ST5 / SCRUM-98)."""

    def test_campos_latitud_y_longitud_son_decimalfield(self):
        """Los campos deben estar definidos como DecimalField en el ORM."""
        campo_lat = Finca._meta.get_field('latitud')
        campo_lng = Finca._meta.get_field('longitud')

        self.assertIsInstance(campo_lat, models.DecimalField)
        self.assertIsInstance(campo_lng, models.DecimalField)
        self.assertEqual(campo_lat.max_digits, 9)
        self.assertEqual(campo_lat.decimal_places, 6)
        self.assertEqual(campo_lng.max_digits, 9)
        self.assertEqual(campo_lng.decimal_places, 6)

    def test_campos_latitud_y_longitud_son_opcionales_en_modelo(self):
        """Los campos deben permitir nulabilidad (null=True, blank=True)."""
        campo_lat = Finca._meta.get_field('latitud')
        campo_lng = Finca._meta.get_field('longitud')

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

    def test_finca_model_form_guarda_con_y_sin_coordenadas(self):
        """El ModelForm permite guardar con y sin georreferenciación."""
        # Caso sin coordenadas
        form_sin_coords = FincaModelForm(data={
            'nombre': 'Finca Modelo Sin Coords',
            'municipio': 'Labateca',
            'vereda': 'Centro',
        })
        self.assertTrue(form_sin_coords.is_valid(), f"Errores: {form_sin_coords.errors}")
        finca_sin_coords = form_sin_coords.save()
        self.assertIsNone(finca_sin_coords.latitud)
        self.assertIsNone(finca_sin_coords.longitud)

        # Caso con coordenadas
        form_con_coords = FincaModelForm(data={
            'nombre': 'Finca Modelo Con Coords',
            'municipio': 'Salazar',
            'vereda': 'La Playa',
            'latitud': '7.771234',
            'longitud': '-72.812345',
        })
        self.assertTrue(form_con_coords.is_valid(), f"Errores: {form_con_coords.errors}")
        finca_con_coords = form_con_coords.save()
        self.assertEqual(finca_con_coords.latitud, Decimal('7.771234'))
        self.assertEqual(finca_con_coords.longitud, Decimal('-72.812345'))


class TestGeorreferenciacionFormulario(TestCase):
    """Pruebas del diseño del formulario y mixin de georreferenciación (HU07-ST1)."""

    def test_campos_de_coordenadas_son_opcionales(self):
        """Los campos de latitud y longitud no deben ser obligatorios (required=False)."""
        form = GeorreferenciacionFormMixin()
        self.assertFalse(form.fields['latitud'].required)
        self.assertFalse(form.fields['longitud'].required)

    def test_placeholders_indicativos_de_coordenadas_decimales(self):
        """Los widgets de latitud y longitud deben tener placeholders con ejemplos decimales."""
        form = GeorreferenciacionFormMixin()
        
        lat_placeholder = form.fields['latitud'].widget.attrs.get('placeholder', '')
        lng_placeholder = form.fields['longitud'].widget.attrs.get('placeholder', '')

        self.assertIn("7.893910", lat_placeholder)
        self.assertIn("decimales", lat_placeholder.lower())
        self.assertIn("-72.507820", lng_placeholder)
        self.assertIn("decimales", lng_placeholder.lower())

    def test_formulario_valido_cuando_coordenadas_no_son_informadas(self):
        """Si el usuario no informa coordenadas, el formulario debe ser válido sin errores."""
        datos = {
            'nombre': 'Finca Los Pinos',
            'municipio': 'Arboledas',
            'vereda': 'La Selva',
            'latitud': '',
            'longitud': '',
        }
        form = FincaRegistroForm(data=datos)
        self.assertTrue(form.is_valid(), f"Errores encontrados: {form.errors}")
        self.assertIsNone(form.cleaned_data['latitud'])
        self.assertIsNone(form.cleaned_data['longitud'])

    def test_formulario_valido_con_coordenadas_decimales_informadas(self):
        """Si el usuario ingresa coordenadas decimales válidas, se procesan correctamente."""
        datos = {
            'nombre': 'Finca La Esmeralda',
            'municipio': 'Toledo',
            'vereda': 'San Bernardo',
            'latitud': '7.893910',
            'longitud': '-72.507820',
        }
        form = FincaRegistroForm(data=datos)
        self.assertTrue(form.is_valid(), f"Errores encontrados: {form.errors}")
        self.assertEqual(form.cleaned_data['latitud'], Decimal('7.893910'))
        self.assertEqual(form.cleaned_data['longitud'], Decimal('-72.507820'))


class TestGeorreferenciacionInterfazWeb(TestCase):
    """Pruebas de la vista y plantilla HTML del registro de finca y georreferenciación."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('finca_registro')

    def test_renderizado_exitoso_vista_registro(self):
        """La vista de registro debe responder HTTP 200 y usar la plantilla esperada."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'fincas/registro_finca.html')
        self.assertTemplateUsed(response, 'fincas/componentes/campo_georreferenciacion.html')

    def test_plantilla_contiene_nota_campo_opcional(self):
        """La plantilla debe exhibir visiblemente que el campo es Opcional."""
        response = self.client.get(self.url)
        contenido = response.content.decode('utf-8')

        self.assertIn('Opcional', contenido)
        self.assertIn('badge-opcional', contenido)
        self.assertIn('nota-informativa-geo', contenido)
        self.assertIn('no es obligatorio', contenido)

    def test_plantilla_contiene_inputs_con_placeholders_decimales(self):
        """La plantilla debe renderizar los inputs de latitud y longitud con sus placeholders."""
        response = self.client.get(self.url)
        contenido = response.content.decode('utf-8')

        self.assertIn('id="id_latitud"', contenido)
        self.assertIn('id="id_longitud"', contenido)
        self.assertIn('Ej: 7.893910 (Grados decimales)', contenido)
        self.assertIn('Ej: -72.507820 (Grados decimales)', contenido)

    def test_plantilla_incluye_ayudas_de_entrada_y_captura_gps(self):
        """La interfaz debe ofrecer botón de captura satelital y textos de ayuda de rango."""
        response = self.client.get(self.url)
        contenido = response.content.decode('utf-8')

        self.assertIn('btn-detectar-gps', contenido)
        self.assertIn('WGS84', contenido)
        self.assertIn('[-90° a +90°]', contenido)
        self.assertIn('[-180° a +180°]', contenido)
