"""Optional SMTP mail. In-app notifications always remain."""

import logging

from app.config import settings

logger = logging.getLogger("taskflow.email")


async def send_email(to: str, subject: str, body: str) -> None:
    if not to:
        logger.info("Skipping email with empty recipient subject=%s", subject)
        return
    if not settings.smtp_configured:
        logger.info("SMTP not configured; skipping email to %s subject=%s", to, subject)
        return
    try:
        from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

        conf = ConnectionConfig(
            MAIL_USERNAME=settings.smtp_user,
            MAIL_PASSWORD=settings.smtp_password,
            MAIL_FROM=settings.smtp_from,
            MAIL_PORT=settings.smtp_port,
            MAIL_SERVER=settings.smtp_host,
            MAIL_STARTTLS=settings.smtp_starttls,
            MAIL_SSL_TLS=settings.smtp_ssl,
            USE_CREDENTIALS=bool(settings.smtp_user),
            VALIDATE_CERTS=True,
            TIMEOUT=10,
        )
        message = MessageSchema(
            subject=subject,
            recipients=[to],
            body=body,
            subtype=MessageType.plain,
        )
        await FastMail(conf).send_message(message)
        logger.info("Email sent to %s subject=%s", to, subject)
    except Exception:
        logger.exception("Email failed to %s subject=%s", to, subject)
