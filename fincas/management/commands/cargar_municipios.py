"""
Comando de gestión Django para cargar los municipios de Norte de Santander.
Subtarea: SCRUM-117 / HU09-ST7: Preparar datos iniciales del catálogo de municipios.
DoD: Fixture o comando de carga inicial con los municipios cafeteros de Norte de Santander.

Uso:
    python manage.py cargar_municipios
    python manage.py cargar_municipios --reactivar
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from fincas.models import Municipio

# Catálogo oficial de los 40 municipios de Norte de Santander con códigos DANE
MUNICIPIOS_NORTE_DE_SANTANDER = [
    ("54001", "Cúcuta"),
    ("54003", "Ábrego"),
    ("54051", "Arboledas"),
    ("54099", "Bochalema"),
    ("54109", "Bucarasica"),
    ("54125", "Cácota"),
    ("54128", "Cáchira"),
    ("54172", "Chinácota"),
    ("54174", "Chitagá"),
    ("54206", "Convención"),
    ("54223", "Cucutilla"),
    ("54239", "Durania"),
    ("54245", "El Carmen"),
    ("54250", "El Tarra"),
    ("54261", "El Zulia"),
    ("54313", "Gramalote"),
    ("54344", "Hacarí"),
    ("54347", "Herrán"),
    ("54377", "Labateca"),
    ("54385", "La Esperanza"),
    ("54398", "La Playa de Belén"),
    ("54405", "Los Patios"),
    ("54418", "Lourdes"),
    ("54480", "Mutiscua"),
    ("54498", "Ocaña"),
    ("54518", "Pamplona"),
    ("54520", "Pamplonita"),
    ("54553", "Puerto Santander"),
    ("54599", "Ragonvalia"),
    ("54660", "Salazar de Las Palmas"),
    ("54670", "San Calixto"),
    ("54673", "San Cayetano"),
    ("54680", "Santiago"),
    ("54720", "Sardinata"),
    ("54743", "Silos"),
    ("54800", "Teorama"),
    ("54810", "Tibú"),
    ("54820", "Toledo"),
    ("54871", "Villa Caro"),
    ("54874", "Villa del Rosario"),
]


class Command(BaseCommand):
    help = (
        "Carga o sincroniza el catálogo inicial de los 40 municipios de Norte de Santander (HU-09 / SCRUM-117)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--departamento",
            type=str,
            default="Norte de Santander",
            help="Nombre del departamento al que pertenecen los municipios (por defecto: Norte de Santander).",
        )
        parser.add_argument(
            "--reactivar",
            action="store_true",
            help="Si se especifica, reactiva (activo=True) los municipios que hayan sido previamente inactivados.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        departamento = options["departamento"]
        reactivar = options["reactivar"]

        creados = 0
        actualizados = 0
        mantenidos = 0

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Iniciando carga del catálogo de municipios para '{departamento}'..."
            )
        )

        for codigo, nombre in MUNICIPIOS_NORTE_DE_SANTANDER:
            # Buscar por código DANE o por nombre para evitar duplicados en BD
            municipio = Municipio.objects.filter(codigo=codigo).first()
            if not municipio:
                municipio = Municipio.objects.filter(nombre__iexact=nombre).first()

            if municipio:
                cambios = False
                if municipio.codigo != codigo:
                    municipio.codigo = codigo
                    cambios = True
                if municipio.nombre != nombre:
                    municipio.nombre = nombre
                    cambios = True
                if municipio.departamento != departamento:
                    municipio.departamento = departamento
                    cambios = True
                if reactivar and not municipio.activo:
                    municipio.activo = True
                    cambios = True

                if cambios:
                    municipio.save()
                    actualizados += 1
                else:
                    mantenidos += 1
            else:
                Municipio.objects.create(
                    codigo=codigo,
                    nombre=nombre,
                    departamento=departamento,
                    activo=True,
                )
                creados += 1

        total = creados + actualizados + mantenidos
        self.stdout.write(
            self.style.SUCCESS(
                f"\nProceso completado con éxito:"
                f"\n - Total evaluados: {total}"
                f"\n - Creados nuevos: {creados}"
                f"\n - Actualizados: {actualizados}"
                f"\n - Sin cambios (ya existentes): {mantenidos}"
                f"\n - Total municipios en BD: {Municipio.objects.count()}"
            )
        )
