# Generado a mano (sin acceso a `manage.py makemigrations` desde este
# entorno) para SCRUM-141 / HU13-ST1: Definir modelo de datos y relación
# Cosecha-Lote. Los campos reflejan exactamente fincas/models.py; si al
# correr `python manage.py makemigrations` localmente Django no detecta
# cambios pendientes, es la confirmación de que este archivo quedó
# sincronizado con el modelo.

from decimal import Decimal
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalogos', '0002_alter_variedadcafe_especie'),
        ('fincas', '0004_merge_20261015_2229'),
    ]

    operations = [
        migrations.CreateModel(
            name='Cosecha',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_cosecha', models.DateField(help_text='Fecha en que se realizó la cosecha.', verbose_name='Fecha de la cosecha')),
                ('cantidad_total', models.DecimalField(decimal_places=2, help_text='Cantidad total cosechada, en kilogramos.', max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], verbose_name='Cantidad total cosechada (kg)')),
                ('cantidad_disponible', models.DecimalField(decimal_places=2, help_text='Saldo sin asignar a ningún lote todavía. Se descuenta automáticamente al crear lotes (HU13-ST2).', max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Cantidad disponible (kg)')),
                ('activo', models.BooleanField(default=True, verbose_name='Cosecha activa')),
                ('creado_en', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')),
                ('actualizado_en', models.DateTimeField(auto_now=True, verbose_name='Última actualización')),
                ('finca', models.ForeignKey(help_text='Finca de la que proviene la cosecha.', on_delete=django.db.models.deletion.PROTECT, related_name='cosechas', to='fincas.finca', verbose_name='Finca')),
                ('variedad', models.ForeignKey(blank=True, help_text='Variedad cosechada, del catálogo de HU10 (opcional).', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cosechas', to='catalogos.variedadcafe', verbose_name='Variedad de café')),
            ],
            options={
                'verbose_name': 'Cosecha',
                'verbose_name_plural': 'Cosechas',
                'db_table': 'cosechas',
                'ordering': ['-fecha_cosecha', '-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='Lote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(help_text='Código único alfanumérico del lote (criterio de aceptación HU13).', max_length=30, unique=True, verbose_name='Código del lote')),
                ('cantidad', models.DecimalField(decimal_places=2, help_text='Cantidad asignada a este lote; no puede superar el saldo disponible de la cosecha.', max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], verbose_name='Cantidad del lote (kg)')),
                ('activo', models.BooleanField(default=True, verbose_name='Lote activo')),
                ('creado_en', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')),
                ('cosecha', models.ForeignKey(help_text='Cosecha existente a partir de la cual se crea el lote.', on_delete=django.db.models.deletion.PROTECT, related_name='lotes', to='fincas.cosecha', verbose_name='Cosecha de origen')),
            ],
            options={
                'verbose_name': 'Lote',
                'verbose_name_plural': 'Lotes',
                'db_table': 'lotes',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.AddConstraint(
            model_name='cosecha',
            constraint=models.CheckConstraint(condition=models.Q(('cantidad_disponible__lte', models.F('cantidad_total'))), name='cosecha_disponible_no_supera_total'),
        ),
    ]
