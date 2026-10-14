import smtplib
from email.message import EmailMessage

from .config import env


class Mailer:
    """SMTP e-mail sender. Relay host from SMTP_HOST, port from SMTP_PORT."""

    def __init__(self) -> None:
        self._host = env("SMTP_HOST")
        self._port = int(env("SMTP_PORT", "587"))
        self._sender = env("MAIL_FROM", "no-reply@parking.example")

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self._host, self._port) as smtp:
            smtp.starttls()
            smtp.send_message(msg)
