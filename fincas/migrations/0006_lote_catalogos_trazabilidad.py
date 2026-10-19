from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("catalogos", "0004_bitacoracatalogotrazabilidad"),
        ("fincas", "0005_cosecha_lote"),
    ]

    operations = [
        migrations.AddField(
            model_name="lote",
            name="proceso_beneficio",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lotes",
                to="catalogos.procesobeneficio",
                verbose_name="Proceso de beneficio",
            ),
        ),
        migrations.AddField(
            model_name="lote",
            name="estado_lote",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lotes",
                to="catalogos.estadolote",
                verbose_name="Estado del lote",
            ),
        ),
    ]
