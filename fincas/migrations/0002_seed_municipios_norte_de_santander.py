"""
Datos semilla del catálogo de municipios de Norte de Santander - CAFÉ PÉRGAMO
Subtarea: SCRUM-91 / HU06-ST3: Crear formulario de registro de finca(s) en la interfaz.
Subtarea: SCRUM-89 / HU06-ST4: Validar campos obligatorios y consistencia de datos del registro.

El criterio de aceptación de HU06-ST3/ST4 exige "seleccionar el municipio
desde el catálogo" y "rechazo en backend si ... el municipio seleccionado
no es válido". Eso solo tiene sentido si el catálogo YA viene poblado: de
lo contrario el <select> del formulario de registro estaría vacío y nadie
podría registrar una finca.

Esta migración siembra los 40 municipios oficiales de Norte de Santander
(división político-administrativa del departamento), identificados por
`codigo`, así que es segura de reaplicar y no duplica la fila "PAMPLONA"
insertada manualmente en Supabase durante la verificación de
HU06-ST1/ST2 (se funde con ella en vez de chocar).

Nota: ya se sembraron estos 40 municipios directamente en Supabase
(producción) el 2026-10-13 para no bloquear el trabajo mientras se
investigaba por qué la primera corrida de esta migración se quedaba
colgada contra la base de datos remota. La función de abajo sigue
siendo la fuente de verdad -- es idempotente (no usa `select_for_update`
ni savepoints anidados, solo una comprobación simple + UPDATE/INSERT)
para que un checkout nuevo (o la base de datos de pruebas) quede igual
de poblado sin volver a pelear con eso.
"""

from django.db import migrations


MUNICIPIOS_NORTE_DE_SANTANDER = [
    ("ABREGO", "Ábrego"),
    ("ARBOLEDAS", "Arboledas"),
    ("BOCHALEMA", "Bochalema"),
    ("BUCARASICA", "Bucarasica"),
    ("CACOTA", "Cácota"),
    ("CACHIRA", "Cáchira"),
    ("CHINACOTA", "Chinácota"),
    ("CHITAGA", "Chitagá"),
    ("CONVENCION", "Convención"),
    ("CUCUTILLA", "Cucutilla"),
    ("CUCUTA", "Cúcuta"),
    ("DURANIA", "Durania"),
    ("EL_CARMEN", "El Carmen"),
    ("EL_TARRA", "El Tarra"),
    ("EL_ZULIA", "El Zulia"),
    ("GRAMALOTE", "Gramalote"),
    ("HACARI", "Hacarí"),
    ("HERRAN", "Herrán"),
    ("LA_ESPERANZA", "La Esperanza"),
    ("LA_PLAYA", "La Playa"),
    ("LABATECA", "Labateca"),
    ("LOS_PATIOS", "Los Patios"),
    ("LOURDES", "Lourdes"),
    ("MUTISCUA", "Mutiscua"),
    ("OCANA", "Ocaña"),
    ("PAMPLONA", "Pamplona"),
    ("PAMPLONITA", "Pamplonita"),
    ("PUERTO_SANTANDER", "Puerto Santander"),
    ("RAGONVALIA", "Ragonvalia"),
    ("SALAZAR_PALMAS", "Salazar de las Palmas"),
    ("SAN_CALIXTO", "San Calixto"),
    ("SAN_CAYETANO", "San Cayetano"),
    ("SANTIAGO", "Santiago"),
    ("SARDINATA", "Sardinata"),
    ("SILOS", "Silos"),
    ("TEORAMA", "Teorama"),
    ("TIBU", "Tibú"),
    ("TOLEDO", "Toledo"),
    ("VILLA_CARO", "Villa Caro"),
    ("VILLA_DEL_ROSARIO", "Villa del Rosario"),
]


def sembrar_municipios(apps, schema_editor):
    """
    Deliberadamente NO usa `update_or_create` (que internamente hace
    `select_for_update()` + un SAVEPOINT por fila): es innecesario para
    una siembra de datos de una sola vez sin escrituras concurrentes, y
    esos SAVEPOINT anidados dentro de la transacción de la propia
    migración fueron, aparentemente, lo que hizo que la primera corrida
    se quedara colgada contra Supabase. Esta versión es un simple
    "existe -> actualiza, si no -> crea" por cada fila.
    """
    Municipio = apps.get_model("fincas", "Municipio")
    for codigo, nombre in MUNICIPIOS_NORTE_DE_SANTANDER:
        existente = Municipio.objects.filter(codigo=codigo).first()
        if existente is not None:
            existente.nombre = nombre
            existente.departamento = "Norte de Santander"
            existente.activo = True
            existente.save(update_fields=["nombre", "departamento", "activo"])
        else:
            Municipio.objects.create(
                codigo=codigo,
                nombre=nombre,
                departamento="Norte de Santander",
                activo=True,
            )


def eliminar_municipios(apps, schema_editor):
    Municipio = apps.get_model("fincas", "Municipio")
    codigos = [codigo for codigo, _ in MUNICIPIOS_NORTE_DE_SANTANDER]
    Municipio.objects.filter(codigo__in=codigos).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("fincas", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(sembrar_municipios, eliminar_municipios),
    ]
