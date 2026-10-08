"""Formularios y validaciones de actores de la cadena (HU08-ST1)."""

import re

from django import forms

from .models import ActorCadena


class ActorCadenaForm(forms.ModelForm):
    """Valida los datos del actor antes de que ST5 los persista."""

    class Meta:
        model = ActorCadena
        fields = (
            "tipo",
            "razon_social",
            "nit",
            "contacto",
            "correo",
            "telefono",
        )

    def clean_razon_social(self):
        razon_social = self.cleaned_data["razon_social"].strip()
        if not razon_social:
            raise forms.ValidationError("La razón social es obligatoria.")
        return razon_social

    def clean_nit(self):
        nit = self.cleaned_data["nit"].strip()
        if not nit:
            raise forms.ValidationError("El NIT es obligatorio.")
        if not re.fullmatch(r"[0-9 .-]+", nit):
            raise forms.ValidationError(
                "El NIT solo puede contener números, espacios, puntos y guiones."
            )
        return nit

    def clean_contacto(self):
        contacto = self.cleaned_data["contacto"].strip()
        if not contacto:
            raise forms.ValidationError("El contacto es obligatorio.")
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü .'-]{2,150}", contacto):
            raise forms.ValidationError("El contacto contiene caracteres no válidos.")
        return contacto

    def clean_telefono(self):
        telefono = self.cleaned_data["telefono"].strip()
        if telefono and not re.fullmatch(r"[+0-9 ()-]{7,30}", telefono):
            raise forms.ValidationError("El teléfono contiene un formato no válido.")
        return telefono
