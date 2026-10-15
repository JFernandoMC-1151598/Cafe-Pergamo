"""
Formularios para el módulo de Fincas y Georreferenciación - CAFÉ PÉRGAMO
Subtarea: SCRUM-95 / HU07-ST1: Diseñar el campo opcional de coordenadas para georreferenciación.
Subtarea: SCRUM-98 / HU07-ST5: Actualizar el modelo o esquema de datos para georreferenciación.
Subtarea: SCRUM-97: Validar formato de coordenadas.
Subtarea: SCRUM-91 / HU06-ST3: Crear formulario de registro de finca(s) en la interfaz.
Subtarea: SCRUM-89 / HU06-ST4: Validar campos obligatorios y consistencia de datos del registro.
"""

from django import forms
from .models import Finca, Municipio

from .validators import (
    validar_latitud,
    validar_longitud,
    validar_par_coordenadas,
    LATITUD_MIN,
    LATITUD_MAX,
    LONGITUD_MIN,
    LONGITUD_MAX,
)


class MunicipioChoiceField(forms.ModelChoiceField):
    """
    ModelChoiceField que muestra solo el nombre del municipio en el
    <select> (p. ej. "Chinácota"), sin repetir "(Norte de Santander)" en
    cada opción: todo el catálogo pertenece a ese departamento, así que
    el sufijo es ruido visual en una lista de 40 opciones. El __str__
    completo del modelo ("Chinácota (Norte de Santander)") se conserva
    para otros usos (admin, logs, etc.), aquí solo se cambia el label
    que ve el usuario en el formulario.
    """

    def label_from_instance(self, obj):
        return obj.nombre


def _municipio_field(**overrides):
    """
    Construye el campo `municipio` como una selección real del catálogo
    (RF07 / HU06-ST3 / HU06-ST4): el usuario SOLO puede elegir uno de los
    municipios ya existentes en `Municipio` (activos). Antes era un
    `CharField` de texto libre que creaba un municipio nuevo con
    `get_or_create` por cada error de tipeo -- exactamente lo que
    SCRUM-89 ("Rechazo en backend si ... el municipio seleccionado no es
    válido") pide impedir.
    """
    defaults = dict(
        queryset=Municipio.objects.filter(activo=True).order_by("nombre"),
        required=True,
        label="Municipio",
        empty_label="Seleccione un municipio del catálogo...",
        error_messages={
            "required": "El municipio es obligatorio.",
            "invalid_choice": "El municipio seleccionado no es válido. Debe elegirlo del catálogo.",
        },
        widget=forms.Select(attrs={"class": "form-select", "id": "id_municipio"}),
    )
    defaults.update(overrides)
    return MunicipioChoiceField(**defaults)


class GeorreferenciacionFormMixin(forms.Form):
    """
    Mixin / Formulario base con los campos de georreferenciación (HU-07).

    Criterios de aceptación (DoD de HU07-ST1 y SCRUM-97):
    - Campo de coordenadas opcional (required=False).
    - Inputs con placeholders indicativos de formato decimal (WGS84).
    - Validador que rechaza textos o números fuera de los rangos [-90, 90] y [-180, 180].
    - Validación de consistencia mutua del par de coordenadas.
    """

    latitud = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        min_value=LATITUD_MIN,
        max_value=LATITUD_MAX,
        validators=[validar_latitud],
        error_messages={
            "invalid": "El formato de latitud es inválido. Debe ingresar un valor numérico decimal.",
            "min_value": "La latitud está fuera del rango permitido. Debe estar entre -90.000000 y 90.000000 grados.",
            "max_value": "La latitud está fuera del rango permitido. Debe estar entre -90.000000 y 90.000000 grados.",
            "max_digits": "La latitud no puede tener más de 9 dígitos en total.",
            "max_decimal_places": "La latitud no puede tener más de 6 decimales.",
        },
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
        min_value=LONGITUD_MIN,
        max_value=LONGITUD_MAX,
        validators=[validar_longitud],
        error_messages={
            "invalid": "El formato de longitud es inválido. Debe ingresar un valor numérico decimal.",
            "min_value": "La longitud está fuera del rango permitido. Debe estar entre -180.000000 y 180.000000 grados.",
            "max_value": "La longitud está fuera del rango permitido. Debe estar entre -180.000000 y 180.000000 grados.",
            "max_digits": "La longitud no puede tener más de 9 dígitos en total.",
            "max_decimal_places": "La longitud no puede tener más de 6 decimales.",
        },
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

    def clean(self):
        cleaned_data = super().clean()
        lat = cleaned_data.get("latitud")
        lng = cleaned_data.get("longitud")
        validar_par_coordenadas(lat, lng)
        return cleaned_data


class FincaRegistroForm(GeorreferenciacionFormMixin):
    """
    Formulario estándar para captura de datos de Finca, integrando
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

    municipio = _municipio_field()

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


class FincaModelForm(forms.ModelForm):
    """
    ModelForm enlazado directamente al modelo Finca (HU07-ST5).
    Garantiza compatibilidad ORM y persistencia directa con validación SCRUM-97.
    """

    municipio = _municipio_field()

    class Meta:
        model = Finca
        fields = ["nombre", "municipio", "vereda", "latitud", "longitud"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_nombre",
                "placeholder": "Ej: Finca La Esperanza",
            }),
            "vereda": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_vereda",
                "placeholder": "Ej: Vereda El Silencio",
            }),
            "latitud": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_latitud",
                "step": "any",
                "min": "-90",
                "max": "90",
                "placeholder": "Ej: 7.893910 (Grados decimales)",
            }),
            "longitud": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_longitud",
                "step": "any",
                "min": "-180",
                "max": "180",
                "placeholder": "Ej: -72.507820 (Grados decimales)",
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        lat = cleaned_data.get("latitud")
        lng = cleaned_data.get("longitud")
        validar_par_coordenadas(lat, lng)
        return cleaned_data

    def save(self, commit=True, productor_id=None):
        instance = super().save(commit=False)
        if productor_id is not None:
            instance.productor_id = productor_id
        if not instance.productor_id:
            raise ValueError(
                "No se puede registrar una finca sin un productor identificado "
                "(productor_id). Verifique que el usuario tenga una sesión válida."
            )
        if commit:
            instance.save()
        return instance
