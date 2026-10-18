from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalogos", "0003_estadolote_procesobeneficio"),
    ]

    operations = [
        migrations.CreateModel(
            name="BitacoraCatalogoTrazabilidad",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("catalogo", models.CharField(max_length=50)),
                ("registro_id", models.PositiveBigIntegerField()),
                ("registro_codigo", models.CharField(max_length=30)),
                ("registro_nombre", models.CharField(max_length=100)),
                ("accion", models.CharField(max_length=20)),
                ("valores_anteriores", models.JSONField(default=dict)),
                ("valores_nuevos", models.JSONField(default=dict)),
                (
                    "realizado_por_id",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        null=True,
                    ),
                ),
                (
                    "realizado_por_correo",
                    models.EmailField(
                        blank=True,
                        max_length=254,
                        null=True,
                    ),
                ),
                (
                    "ip_address",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Entrada de bitácora de catálogo",
                "verbose_name_plural": "Bitácora de catálogos",
                "db_table": "catalogos_bitacora_trazabilidad",
                "ordering": ["-creado_en"],
            },
        ),
    ]
