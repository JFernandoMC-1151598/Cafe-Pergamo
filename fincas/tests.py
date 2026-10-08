"""
Pruebas unitarias del modelo de datos de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1: Definir modelo de datos para fincas y
relación con productor y municipio.

Criterios de aceptación cubiertos:
- La finca queda asociada a un productor.
- La finca queda asociada a un municipio del catálogo.
- Permite registrar más de una finca por productor.
"""

import uuid

from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from .models import Finca, Municipio


class MunicipioModelTests(TestCase):
    def test_creacion_basica_usa_departamento_por_defecto(self):
        municipio = Municipio.objects.create(codigo="PAMPLONA", nombre="Pamplona")
        self.assertEqual(municipio.departamento, "Norte de Santander")
        self.assertTrue(municipio.activo)

    def test_codigo_unico_en_el_catalogo(self):
        Municipio.objects.create(codigo="CUCUTA", nombre="Cúcuta")
        with self.assertRaises(IntegrityError):
            Municipio.objects.create(codigo="CUCUTA", nombre="Cúcuta (duplicado)")


class FincaModelTests(TestCase):
    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="PAMPLONA", nombre="Pamplona")
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
        with self.assertRaises(IntegrityError):
            Finca.objects.create(nombre="Sin productor", productor_id=None, municipio=self.municipio)

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
