"""Pruebas funcionales del listado de variedades de café (HU10-ST2)."""

from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import EstadoLote, ProcesoBeneficio, VariedadCafe
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

    def test_modelo_rechaza_nombre_vacio(self):
        variedad = VariedadCafe(
            nombre="   ",
            especie=VariedadCafe.Especie.ARABICA,
        )

        with self.assertRaises(ValidationError) as contexto:
            variedad.full_clean()

        self.assertIn("nombre", contexto.exception.message_dict)

    def test_modelo_rechaza_especie_invalida(self):
        variedad = VariedadCafe(
            nombre="Variedad inválida",
            especie="NO_EXISTE",
        )

        with self.assertRaises(ValidationError) as contexto:
            variedad.full_clean()

        self.assertIn("especie", contexto.exception.message_dict)


class CatalogosTrazabilidadModelTests(TestCase):
    """Verifica la estructura y las reglas básicas de HU11-ST4."""

    def test_proceso_beneficio_normaliza_codigo_y_campos_de_texto(self):
        proceso = ProcesoBeneficio(
            codigo=" lavado ",
            nombre=" Lavado ",
            descripcion=" Proceso tradicional. ",
            orden=1,
        )

        proceso.full_clean()
        proceso.save()

        self.assertEqual(proceso.codigo, "LAVADO")
        self.assertEqual(proceso.nombre, "Lavado")
        self.assertEqual(proceso.descripcion, "Proceso tradicional.")
        self.assertTrue(proceso.activo)
        self.assertEqual(proceso.orden, 1)

    def test_estado_lote_exige_codigo_y_nombre(self):
        estado = EstadoLote(codigo="", nombre="   ")

        with self.assertRaises(ValidationError) as contexto:
            estado.full_clean()

        self.assertEqual(
            set(contexto.exception.message_dict),
            {"codigo", "nombre"},
        )

    def test_codigos_y_nombres_son_unicos_sin_distinguir_mayusculas(self):
        ProcesoBeneficio.objects.create(
            codigo="HONEY",
            nombre="Honey",
        )

        proceso_codigo_duplicado = ProcesoBeneficio(
            codigo="honey",
            nombre="Honey especial",
        )
        proceso_nombre_duplicado = ProcesoBeneficio(
            codigo="HONEY-2",
            nombre="hONEY",
        )

        with self.assertRaises(ValidationError):
            proceso_codigo_duplicado.full_clean()
        with self.assertRaises(ValidationError):
            proceso_nombre_duplicado.full_clean()

    def test_catalogos_conservan_registros_inactivos(self):
        proceso = ProcesoBeneficio.objects.create(
            codigo="NATURAL",
            nombre="Natural",
            activo=False,
        )
        estado = EstadoLote.objects.create(
            codigo="SECADO",
            nombre="Secado",
            activo=False,
        )

        self.assertFalse(
            ProcesoBeneficio.objects.get(pk=proceso.pk).activo
        )
        self.assertFalse(EstadoLote.objects.get(pk=estado.pk).activo)


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

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_filtro_muestra_solo_inactivas(
        self, _mock_permission, _mock_template_permission
    ):
        response = lista_variedades_view(
            self._request(True, role="ADMINISTRADOR", estado="inactivas")
        )

        self.assertContains(response, "Robusta Tradicional")
        self.assertNotContains(response, "Castillo")


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
            {
                "is_authenticated": True,
            },
        )()
        request.session = {"rol": "ADMINISTRADOR"}
        response = alternar_estado_variedad_view(request, self.variedad.id)

        self.assertEqual(response.status_code, 405)
        self.variedad.refresh_from_db()
        self.assertTrue(self.variedad.activo)


class CicloVidaVariedadTests(TestCase):
    """Comprueba el ciclo completo del catálogo desde la perspectiva funcional."""

    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_crear_editar_inactivar_y_reactivar_conserva_el_registro(
        self, _mock_permission
    ):
        crear_request = RequestFactory().post(
            reverse("crear_variedad"),
            data={
                "nombre": "Bourbon",
                "especie": VariedadCafe.Especie.ARABICA,
                "descripcion": "Variedad inicial.",
            },
        )
        crear_request.user = type(
            "User",
            (),
            {"is_authenticated": True},
        )()
        crear_request.session = {"rol": "ADMINISTRADOR"}
        crear_request._messages = FallbackStorage(crear_request)

        crear_response = crear_variedad_view(crear_request)

        self.assertEqual(crear_response.status_code, 302)
        variedad = VariedadCafe.objects.get(nombre="Bourbon")
        variedad_id = variedad.id

        editar_request = RequestFactory().post(
            reverse("editar_variedad", args=[variedad_id]),
            data={
                "nombre": "Bourbon Mejorado",
                "especie": VariedadCafe.Especie.EXCELSA,
                "descripcion": "Variedad actualizada.",
            },
        )
        editar_request.user = crear_request.user
        editar_request.session = crear_request.session
        editar_request._messages = FallbackStorage(editar_request)

        editar_response = editar_variedad_view(editar_request, variedad_id)

        self.assertEqual(editar_response.status_code, 302)
        variedad.refresh_from_db()
        self.assertEqual(variedad.nombre, "Bourbon Mejorado")
        self.assertEqual(variedad.especie, VariedadCafe.Especie.EXCELSA)
        self.assertTrue(variedad.activo)

        estado_request = RequestFactory().post(
            reverse("alternar_estado_variedad", args=[variedad_id])
        )
        estado_request.user = crear_request.user
        estado_request.session = crear_request.session
        estado_request._messages = FallbackStorage(estado_request)

        alternar_estado_variedad_view(estado_request, variedad_id)
        variedad.refresh_from_db()
        self.assertFalse(variedad.activo)
        self.assertTrue(VariedadCafe.objects.filter(pk=variedad_id).exists())

        alternar_estado_variedad_view(estado_request, variedad_id)
        variedad.refresh_from_db()
        self.assertTrue(variedad.activo)

    @patch("usuarios.templatetags.rbac_tags.usuario_tiene_permiso", return_value=True)
    @patch("usuarios.permissions.usuario_tiene_permiso", return_value=True)
    def test_variedad_creada_aparece_inmediatamente_en_listado(
        self, _mock_permission, _mock_template_permission
    ):
        variedad = VariedadCafe.objects.create(
            nombre="Typica",
            especie=VariedadCafe.Especie.ARABICA,
        )
        request = RequestFactory().get(reverse("lista_variedades"))
        request.user = type(
            "User",
            (),
            {
                "is_authenticated": True,
                "username": "admin@example.com",
                "first_name": "Admin",
            },
        )()
        request.session = {"rol": "ADMINISTRADOR"}
        request._messages = FallbackStorage(request)

        response = lista_variedades_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, variedad.nombre)
