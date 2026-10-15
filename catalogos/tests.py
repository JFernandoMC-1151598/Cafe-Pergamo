"""Pruebas funcionales del listado de variedades de café (HU10-ST2)."""

from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import VariedadCafe
from .views import (
    alternar_estado_variedad_view,
    crear_variedad_view,
    editar_variedad_view,
    lista_variedades_view,
)


class VariedadCafeEspeciesTests(TestCase):
    """Verifica las cuatro especies disponibles en el catálogo."""

    def test_catalogo_incluye_las_cuatro_especies(self):
        self.assertEqual(
            set(VariedadCafe.Especie.values),
            {"ARABICA", "ROBUSTA", "LIBERICA", "EXCELSA"},
        )


class ListaVariedadesTests(TestCase):
    """Comprueba autorización y consulta del catálogo."""

    def _request(self, authenticated, role="", estado=""):
        query = f"?estado={estado}" if estado else ""
        request = RequestFactory().get(
            f"{reverse('lista_variedades')}{query}"
        )
        request.user = type(
            "User",
            (),
            {
                "is_authenticated": authenticated,
                "username": "admin@example.com",
                "first_name": "Admin",
            },
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    def setUp(self):
        VariedadCafe.objects.create(
            nombre="Castillo",
            especie=VariedadCafe.Especie.ARABICA,
        )
        VariedadCafe.objects.create(
            nombre="Robusta Tradicional",
            especie=VariedadCafe.Especie.ROBUSTA,
            activo=False,
        )

    def test_sesion_no_iniciada_redirige_al_login(self):
        response = lista_variedades_view(self._request(False))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_rol_sin_permiso_recibe_403(self, _mock_permission):
        response = lista_variedades_view(
            self._request(True, role="PRODUCTOR")
        )

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_lista_variedades_diferencia_estados(
        self, _mock_permission, _mock_template_permission
    ):
        response = lista_variedades_view(
            self._request(True, role="ADMINISTRADOR")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Castillo")
        self.assertContains(response, "Robusta Tradicional")
        self.assertContains(response, "Activa")
        self.assertContains(response, "Inactiva")

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_filtro_muestra_solo_activas(
        self, _mock_permission, _mock_template_permission
    ):
        response = lista_variedades_view(
            self._request(True, role="ADMINISTRADOR", estado="activas")
        )

        self.assertContains(response, "Castillo")
        self.assertNotContains(response, "Robusta Tradicional")


class CrearVariedadTests(TestCase):
    """Comprueba validación, autorización y persistencia de variedades."""

    def _request(self, authenticated, role="", data=None):
        request = RequestFactory().post(
            reverse("crear_variedad"),
            data=data or {},
        ) if data is not None else RequestFactory().get(
            reverse("crear_variedad")
        )
        request.user = type(
            "User",
            (),
            {
                "is_authenticated": authenticated,
                "username": "admin@example.com",
                "first_name": "Admin",
            },
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_rol_sin_permiso_recibe_403(self, _mock_permission):
        response = crear_variedad_view(
            self._request(True, role="PRODUCTOR")
        )

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_get_muestra_formulario(
        self, _mock_permission, _mock_template_permission
    ):
        response = crear_variedad_view(
            self._request(True, role="ADMINISTRADOR")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registrar variedad de café")

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_post_valido_persiste_y_redirige(self, _mock_permission):
        response = crear_variedad_view(
            self._request(
                True,
                role="ADMINISTRADOR",
                data={
                    "nombre": "Caturra",
                    "especie": VariedadCafe.Especie.ARABICA,
                    "descripcion": "Variedad de prueba.",
                },
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("lista_variedades"))
        variedad = VariedadCafe.objects.get(nombre="Caturra")
        self.assertEqual(variedad.especie, VariedadCafe.Especie.ARABICA)
        self.assertTrue(variedad.activo)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_post_invalido_muestra_errores_y_no_persiste(
        self, _mock_permission, _mock_template_permission
    ):
        response = crear_variedad_view(
            self._request(
                True,
                role="ADMINISTRADOR",
                data={
                    "nombre": "   ",
                    "especie": "",
                    "descripcion": "",
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "obligatorio")
        self.assertEqual(VariedadCafe.objects.count(), 0)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_post_rechaza_nombre_duplicado_sin_importar_mayusculas(
        self, _mock_permission, _mock_template_permission
    ):
        VariedadCafe.objects.create(
            nombre="Castillo",
            especie=VariedadCafe.Especie.ARABICA,
        )

        response = crear_variedad_view(
            self._request(
                True,
                role="ADMINISTRADOR",
                data={
                    "nombre": "castillo",
                    "especie": VariedadCafe.Especie.ARABICA,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ya existe")
        self.assertEqual(VariedadCafe.objects.count(), 1)


class EditarVariedadTests(TestCase):
    """Comprueba la actualización de variedades sin alterar su estado."""

    def _request(self, variedad_id, authenticated, role="", data=None):
        url = reverse("editar_variedad", args=[variedad_id])
        request = RequestFactory().post(url, data=data or {}) if data is not None else RequestFactory().get(url)
        request.user = type(
            "User",
            (),
            {
                "is_authenticated": authenticated,
                "username": "admin@example.com",
                "first_name": "Admin",
            },
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    def setUp(self):
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo",
            especie=VariedadCafe.Especie.ARABICA,
            descripcion="Descripción original.",
            activo=False,
        )

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_rol_sin_permiso_recibe_403(self, _mock_permission):
        response = editar_variedad_view(
            self._request(self.variedad.id, True, role="PRODUCTOR"),
            self.variedad.id,
        )

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_post_actualiza_datos_y_conserva_estado(self, _mock_permission):
        response = editar_variedad_view(
            self._request(
                self.variedad.id,
                True,
                role="ADMINISTRADOR",
                data={
                    "nombre": "Castillo Mejorado",
                    "especie": VariedadCafe.Especie.LIBERICA,
                    "descripcion": "Descripción actualizada.",
                },
            ),
            self.variedad.id,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("lista_variedades"))
        self.variedad.refresh_from_db()
        self.assertEqual(self.variedad.nombre, "Castillo Mejorado")
        self.assertEqual(self.variedad.especie, VariedadCafe.Especie.LIBERICA)
        self.assertEqual(self.variedad.descripcion, "Descripción actualizada.")
        self.assertFalse(self.variedad.activo)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_post_rechaza_nombre_de_otra_variedad(
        self, _mock_permission, _mock_template_permission
    ):
        VariedadCafe.objects.create(
            nombre="Caturra",
            especie=VariedadCafe.Especie.ARABICA,
        )

        response = editar_variedad_view(
            self._request(
                self.variedad.id,
                True,
                role="ADMINISTRADOR",
                data={
                    "nombre": "caturra",
                    "especie": VariedadCafe.Especie.ARABICA,
                    "descripcion": "No debe guardarse.",
                },
            ),
            self.variedad.id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ya existe")
        self.variedad.refresh_from_db()
        self.assertEqual(self.variedad.nombre, "Castillo")


class AlternarEstadoVariedadTests(TestCase):
    """Comprueba la baja lógica y la reactivación del catálogo."""

    def _request(self, variedad_id, authenticated, role=""):
        request = RequestFactory().post(
            reverse("alternar_estado_variedad", args=[variedad_id])
        )
        request.user = type(
            "User",
            (),
            {
                "is_authenticated": authenticated,
                "username": "admin@example.com",
                "first_name": "Admin",
            },
        )()
        request.session = {"rol": role} if role else {}
        request._messages = FallbackStorage(request)
        return request

    def setUp(self):
        self.variedad = VariedadCafe.objects.create(
            nombre="Castillo",
            especie=VariedadCafe.Especie.ARABICA,
        )

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=False)
    def test_rol_sin_permiso_recibe_403(self, _mock_permission):
        response = alternar_estado_variedad_view(
            self._request(self.variedad.id, True, role="PRODUCTOR"),
            self.variedad.id,
        )

        self.assertEqual(response.status_code, 403)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_inactivar_cambia_estado_sin_eliminar_registro(
        self, _mock_permission
    ):
        response = alternar_estado_variedad_view(
            self._request(self.variedad.id, True, role="ADMINISTRADOR"),
            self.variedad.id,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("lista_variedades"))
        self.variedad.refresh_from_db()
        self.assertFalse(self.variedad.activo)
        self.assertTrue(
            VariedadCafe.objects.filter(pk=self.variedad.id).exists()
        )

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_variedad_inactiva_puede_reactivarse(self, _mock_permission):
        self.variedad.activo = False
        self.variedad.save(update_fields=["activo", "actualizado_en"])

        response = alternar_estado_variedad_view(
            self._request(self.variedad.id, True, role="ADMINISTRADOR"),
            self.variedad.id,
        )

        self.assertEqual(response.status_code, 302)
        self.variedad.refresh_from_db()
        self.assertTrue(self.variedad.activo)

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_get_no_cambia_estado_y_responde_metodo_no_permitido(
        self, _mock_permission
    ):
        request = RequestFactory().get(
            reverse("alternar_estado_variedad", args=[self.variedad.id])
        )
        request.user = type(
            "User",
            (),
            {"is_authenticated": True},
        )()
        request.session = {"rol": "ADMINISTRADOR"}
        response = alternar_estado_variedad_view(request, self.variedad.id)

        self.assertEqual(response.status_code, 405)
        self.variedad.refresh_from_db()
        self.assertTrue(self.variedad.activo)
