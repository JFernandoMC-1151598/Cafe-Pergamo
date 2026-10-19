"""Formularios del catálogo de variedades de café (HU10)."""

from django import forms

from .models import EstadoLote, ProcesoBeneficio, VariedadCafe


class VariedadCafeForm(forms.ModelForm):
    """Valida y normaliza los datos de una variedad antes de guardarla."""

    class Meta:
        model = VariedadCafe
        fields = ("nombre", "especie", "descripcion")
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": 100,
                    "placeholder": "Ej. Castillo",
                    "autocomplete": "off",
                }
            ),
            "especie": forms.Select(attrs={"class": "form-select"}),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descripción opcional de la variedad.",
                }
            ),
        }

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        if not nombre:
            raise forms.ValidationError(
                "El nombre de la variedad es obligatorio."
            )
        queryset = VariedadCafe.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(
                "Ya existe una variedad con ese nombre."
            )
        return nombre

    def clean_descripcion(self):
        return self.cleaned_data.get("descripcion", "").strip()


class CatalogoTrazabilidadForm(forms.ModelForm):
    """Formulario común para administrar los catálogos de trazabilidad."""

    class Meta:
        fields = ("codigo", "nombre", "descripcion", "orden")
        widgets = {
            "codigo": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 30}
            ),
            "nombre": forms.TextInput(
                attrs={"class": "form-control", "maxlength": 100}
            ),
            "descripcion": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
            "orden": forms.NumberInput(
                attrs={"class": "form-control", "min": 0}
            ),
        }

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()

    def clean_nombre(self):
        return self.cleaned_data["nombre"].strip()

    def clean_descripcion(self):
        return self.cleaned_data.get("descripcion", "").strip()


class ProcesoBeneficioForm(CatalogoTrazabilidadForm):
    class Meta(CatalogoTrazabilidadForm.Meta):
        model = ProcesoBeneficio


class EstadoLoteForm(CatalogoTrazabilidadForm):
    class Meta(CatalogoTrazabilidadForm.Meta):
        model = EstadoLote
