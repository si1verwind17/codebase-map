from twilio.rest import Client

from .config import env


class SmsClient:
    """Sends text messages through Twilio. Credentials: TWILIO_ACCOUNT_SID and
    TWILIO_AUTH_TOKEN; sender number from TWILIO_FROM."""

    def __init__(self) -> None:
        self._client = Client(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN"))
        self._from = env("TWILIO_FROM")

    def send(self, to: str, body: str) -> str:
        msg = self._client.messages.create(to=to, from_=self._from, body=body)
        return msg.sid
