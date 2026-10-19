"""Mail for the expiry reminders: smtplib to the relay of SMTP_*, always with STARTTLS.

The relay is the one the MSP configures (SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM). A message is sent only after the connection has been
upgraded with STARTTLS and the certificate of the relay has been checked: a relay
that does not offer STARTTLS gets no message and no password. The text of a
failure never holds the password or the message.
"""

import smtplib
import ssl
from email.message import EmailMessage

from app.settings import Settings

TIMEOUT_SECONDS = 20.0
# The name this client gives itself in EHLO. It avoids a lookup of the host name.
LOCAL_HOSTNAME = "revrook.invalid"


class MailError(Exception):
    """The message could not be sent. The text is safe to log and to show."""


def mail_configured(settings: Settings) -> bool:
    """Whether a relay and a sender are set, so that a message can be sent."""
    return bool(settings.smtp_host) and bool(settings.smtp_from or settings.smtp_user)


def build_message(sender: str, to: str, subject: str, body: str) -> EmailMessage:
    """A plain text message. A line break in a header makes EmailMessage refuse it."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def send_mail(
    settings: Settings,
    to: str,
    subject: str,
    body: str,
    *,
    tls_context: ssl.SSLContext | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> None:
    """Send one message through the configured relay. Raises MailError.

    `tls_context` is for tests that trust a throwaway certificate; the default is
    the system store with the host name checked.
    """
    sender = settings.smtp_from or settings.smtp_user
    if not settings.smtp_host or not sender:
        raise MailError("SMTP_HOST and SMTP_FROM must be set to send mail")
    try:
        message = build_message(sender, to, subject, body)
    except ValueError:
        raise MailError("the message has a line break in a header") from None
    context = tls_context or ssl.create_default_context()
    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            local_hostname=LOCAL_HOSTNAME,
            timeout=timeout,
        ) as smtp:
            smtp.ehlo()
            if not smtp.has_extn("starttls"):
                raise MailError(
                    "the mail server does not offer STARTTLS; nothing was sent"
                )
            smtp.starttls(context=context)
            smtp.ehlo()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(message)
    except MailError:
        raise
    except (smtplib.SMTPException, OSError) as error:
        # The class names the problem (refused, timed out, bad certificate, bad
        # login); the text of the error could echo an address, so it is left out.
        reason = type(error).__name__
        raise MailError(f"the mail could not be sent: {reason}") from None
