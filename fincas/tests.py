"""
Pruebas Unitarias para HU-07: Registro de Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.

Criterios de Aceptación Verificados:
- Campos de latitud y longitud son opcionales en el formulario.
- Inputs poseen placeholders indicativos de coordenadas decimales.
- El formulario acepta envíos sin coordenadas (comportamiento cuando el campo no es informado).
- La plantilla renderiza la nota de opcionalidad y las ayudas de entrada.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from fincas.forms import FincaRegistroForm, GeorreferenciacionFormMixin


class TestGeorreferenciacionFormulario(TestCase):
    """Pruebas del diseño del formulario y mixin de georreferenciación."""

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
