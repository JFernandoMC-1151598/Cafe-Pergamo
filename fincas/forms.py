"""
Formularios para el módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
"""

from django import forms


class GeorreferenciacionFormMixin(forms.Form):
    """
    Mixin / Formulario base con los campos de georreferenciación (HU-07).
    
    Criterios de aceptación (DoD de HU07-ST1 / SCRUM-95):
    - Campo de coordenadas opcional (required=False).
    - Inputs con placeholders indicativos de formato decimal (WGS84).
    - Ayudas de entrada y textos contextuales (límites de latitud y longitud).
    - Comportamiento permisivo cuando el campo no es informado (admite nulos / cadenas vacías).
    """

    latitud = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        min_value=-90.0,
        max_value=90.0,
        label="Latitud",
        help_text="Coordenada en grados decimales entre -90.000000 y 90.000000 (Sistema WGS84).",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "id": "id_latitud",
                "name": "latitud",
                "placeholder": "Ej: 7.893910 (Grados decimales)",
                "step": "any",
                "min": "-90",
                "max": "90",
                "autocomplete": "off",
            }
        ),
    )

    longitud = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        min_value=-180.0,
        max_value=180.0,
        label="Longitud",
        help_text="Coordenada en grados decimales entre -180.000000 y 180.000000 (Sistema WGS84).",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "id": "id_longitud",
                "name": "longitud",
                "placeholder": "Ej: -72.507820 (Grados decimales)",
                "step": "any",
                "min": "-180",
                "max": "180",
                "autocomplete": "off",
            }
        ),
    )


class FincaRegistroForm(GeorreferenciacionFormMixin):
    """
    Formulario completo para captura de datos de Finca, integrando
    los campos básicos prediales junto con la sección de georreferenciación opcional.
    """

    nombre = forms.CharField(
        max_length=150,
        required=True,
        label="Nombre de la Finca",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "id_nombre",
                "placeholder": "Ej: Finca La Esperanza",
            }
        ),
    )

    municipio = forms.CharField(
        max_length=100,
        required=True,
        label="Municipio",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "id_municipio",
                "placeholder": "Ej: Arboledas, Toledo, Salazar...",
            }
        ),
    )

    vereda = forms.CharField(
        max_length=150,
        required=False,
        label="Vereda / Sector (Opcional)",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "id_vereda",
                "placeholder": "Ej: Vereda El Silencio",
            }
        ),
    )
