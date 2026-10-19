from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("fincas", "0006_lote_catalogos_trazabilidad"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="cosecha",
            options={
                "managed": True,
                "ordering": ["-fecha_cosecha", "-creado_en"],
                "verbose_name": "Cosecha",
                "verbose_name_plural": "Cosechas",
            },
        ),
        migrations.AlterModelOptions(
            name="lote",
            options={
                "managed": True,
                "ordering": ["-creado_en"],
                "verbose_name": "Lote",
                "verbose_name_plural": "Lotes",
            },
        ),
    ]
