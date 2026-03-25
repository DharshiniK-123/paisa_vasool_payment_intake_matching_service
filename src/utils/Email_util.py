from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from src.config.settings import settings

mail_config = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_STARTTLS=getattr(settings, "MAIL_STARTTLS", True),
    MAIL_SSL_TLS=getattr(settings, "MAIL_SSL_TLS", False),
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)


fastmail = FastMail(mail_config)


async def send_email(to: str, subject: str, body: str) -> None:
    message = MessageSchema(
        subject=subject,
        recipients=[to],
        body=body,
        subtype=MessageType.plain,
    )
    await fastmail.send_message(message)
