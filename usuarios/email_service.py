from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


DEFAULT_EXPIRATION_MINUTES = 30


def send_password_recovery_email(
    recipient_email,
    reset_url,
    user_name="",
    expiration_minutes=DEFAULT_EXPIRATION_MINUTES,
):
    context = {
        "user_name": user_name,
        "reset_url": reset_url,
        "expiration_minutes": expiration_minutes,
    }
    html_message = render_to_string("emails/recuperar_contrasena.html", context)
    text_message = (
        "Solicitaste restablecer tu contrasena en Cafe Pergamo. "
        f"Usa este enlace dentro de {expiration_minutes} minutos: {reset_url}"
    )

    message = EmailMultiAlternatives(
        subject="Restablecimiento de contrasena - Cafe Pergamo",
        body=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )
    message.attach_alternative(html_message, "text/html")
    return message.send(fail_silently=False)
