"""
Regenera los códigos QR de los lotes existentes con la URL pública vigente.

Los QR creados antes de configurar `QR_BASE_URL` guardaron solo la ruta relativa
('/trazabilidad/lote/<CODIGO>/'), que un celular no puede abrir al escanear.
Este comando es idempotente: solo reescribe los QR cuyo contenido cambió.
Se ejecuta solo en cada despliegue (preDeployCommand de render.yaml).
"""
from django.core.management.base import BaseCommand

from fincas.models import Lote
from fincas.services import sincronizar_o_generar_qr_lote


class Command(BaseCommand):
    help = "Sincroniza el QR de cada lote con QR_BASE_URL (regenera los desactualizados)."

    def handle(self, *args, **options):
        total = 0
        actualizados = 0
        for lote in Lote.objects.all().select_related("codigo_qr").iterator():
            total += 1
            previo = getattr(lote, "codigo_qr", None)
            payload_previo = previo.payload_url if previo else None
            qr = sincronizar_o_generar_qr_lote(lote)
            if payload_previo != qr.payload_url:
                actualizados += 1
        self.stdout.write(self.style.SUCCESS(
            f"QR sincronizados: {actualizados} actualizados de {total} lotes."
        ))
