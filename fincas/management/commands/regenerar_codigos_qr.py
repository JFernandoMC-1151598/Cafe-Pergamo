# -*- coding: utf-8 -*-
"""
Comando de gestión Django para regenerar los códigos QR de todos los lotes activos.
Asegura que los QR codifiquen URLs absolutas públicas (ej. de Render) para ser escaneables
desde teléfonos móviles en etiquetas físicas y pantallas.
"""

from django.core.management.base import BaseCommand
from fincas.models import Lote
from fincas.services import sincronizar_o_generar_qr_lote


class Command(BaseCommand):
    help = "Regenera los códigos QR de todos los lotes activos garantizando URLs absolutas navegables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            type=str,
            default=None,
            help="URL base del dominio (ej. https://cafe-pergamo.onrender.com). Si se omite, usa QR_BASE_URL o RENDER_EXTERNAL_URL.",
        )

    def handle(self, *args, **options):
        base_url = options.get("base_url")
        lotes = Lote.objects.filter(activo=True).order_by("codigo")
        total = lotes.count()

        if total == 0:
            self.stdout.write(self.style.WARNING("No hay lotes activos registrados para procesar."))
            return

        actualizados = 0
        for lote in lotes:
            qr = sincronizar_o_generar_qr_lote(
                lote,
                forzar_regeneracion=True,
                base_url=base_url,
            )
            self.stdout.write(
                f"• Lote {lote.codigo}: Identificador={qr.identificador} -> Payload={qr.payload_url}"
            )
            actualizados += 1

        self.stdout.write(
            self.style.SUCCESS(f"\n[OK] Se regeneraron exitosamente {actualizados} de {total} códigos QR.")
        )

