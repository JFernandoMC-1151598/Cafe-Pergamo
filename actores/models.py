"""
Modelos para los actores de la cadena de valor del café (HU08).

Este dominio se mantiene separado de ``usuarios`` y ``fincas`` porque
una asociación, cooperativa o comercializador es una organización
registrada por un administrador, no una cuenta de autenticación ni una
finca productiva.
"""

import re

from django.core.exceptions import ValidationError
from django.db import models


class ActorCadena(models.Model):
    """Organización que participa en la cadena de valor del café."""

    class TipoActor(models.TextChoices):
        ASOCIACION = "ASOCIACION", "Asociación"
        COOPERATIVA = "COOPERATIVA", "Cooperativa"
        COMERCIALIZADOR = "COMERCIALIZADOR", "Comercializador"

    tipo = models.CharField(
        max_length=20,
        choices=TipoActor.choices,
        verbose_name="Tipo de actor",
    )
    razon_social = models.CharField(
        max_length=200,
        verbose_name="Razón social",
    )
    nit = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="NIT",
    )
    contacto = models.CharField(
        max_length=150,
        verbose_name="Persona de contacto",
    )
    correo = models.EmailField(
        verbose_name="Correo electrónico",
    )
    telefono = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono",
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Actor activo",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "actores_cadena"
        ordering = ["razon_social"]
        verbose_name = "Actor de la cadena"
        verbose_name_plural = "Actores de la cadena"

    def clean(self):
        """Valida reglas de negocio antes de persistir el actor."""
        errores = {}

        if not self.razon_social or not self.razon_social.strip():
            errores["razon_social"] = "La razón social es obligatoria."

        if not self.nit or not self.nit.strip():
            errores["nit"] = "El NIT es obligatorio."
        elif not re.fullmatch(r"[0-9 .-]+", self.nit.strip()):
            errores["nit"] = "El NIT solo puede contener números, espacios, puntos y guiones."

        if self.tipo not in self.TipoActor.values:
            errores["tipo"] = "Seleccione un tipo de actor válido."

        if not self.contacto or not self.contacto.strip():
            errores["contacto"] = "El contacto es obligatorio."
        elif not re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü .'-]{2,150}", self.contacto.strip()):
            errores["contacto"] = "El contacto contiene caracteres no válidos."

        if self.telefono and not re.fullmatch(r"[+0-9 ()-]{7,30}", self.telefono.strip()):
            errores["telefono"] = "El teléfono contiene un formato no válido."

        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"{self.razon_social} ({self.get_tipo_display()})"
