"""
Pruebas unitarias del modelo de datos de Fincas - CAFÉ PÉRGAMO
Subtarea: SCRUM-87 / HU06-ST1: Definir modelo de datos para fincas y
relación con productor y municipio.

Criterios de aceptación cubiertos:
- La finca queda asociada a un productor.
- La finca queda asociada a un municipio del catálogo.
- Permite registrar más de una finca por productor.

Subtarea: SCRUM-88 / HU06-ST2: Permitir la asociacion de multiples
fincas a un mismo productor. Criterios cubiertos (ver descripcion de
SCRUM-88):
- Agregar una 2a/3a/enesima finca no choca con ninguna unicidad mal
  aplicada (p. ej. nombre validado como unico global en vez de por
  productor).
- No existe limite artificial de cantidad de fincas por productor.
- El listado de fincas de un productor (via el related_name "fincas"
  de Usuario) devuelve correctamente las suyas, sin mezclarse con las
  de otro productor.
- Cada finca nueva pasa las mismas validaciones de HU06-ST1 de forma
  independiente, sin afectar ni sobrescribir las ya registradas.
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
class AsociacionMultiplesFincasPorProductorTests(TestCase):
    """HU06-ST2 (SCRUM-88): un productor puede tener N fincas, y el
    listado por productor no se mezcla entre productores distintos."""

    def setUp(self):
        self.municipio = Municipio.objects.create(codigo="PAMPLONA", nombre="Pamplona")
        self.productor_a = uuid.uuid4()
        self.productor_b = uuid.uuid4()

    def test_nombre_repetido_entre_fincas_del_mismo_productor_no_choca(self):
        """El nombre de la finca no esta validado como unico global."""
        Finca.objects.create(nombre="Mi Finca", productor_id=self.productor_a, municipio=self.municipio)
        # No debe lanzar IntegrityError por nombre duplicado.
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
        """Cada finca nueva pasa, de forma independiente, las mismas
        validaciones de HU06-ST1 (municipio obligatorio del catalogo)."""
        Finca.objects.create(nombre="Finca 1", productor_id=self.productor_a, municipio=self.municipio)
        with self.assertRaises(IntegrityError):
            Finca.objects.create(nombre="Finca 2 sin municipio", productor_id=self.productor_a, municipio=None)
