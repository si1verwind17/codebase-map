from dataclasses import dataclass

import httpx

from common_py.config import env


@dataclass
class Contact:
    phone: str | None
    email: str | None


def contact_for(driver_id: str) -> Contact:
    """Looks up a driver's contact details in the accounts system, an external
    service whose base URL is ACCOUNTS_API_URL."""
    resp = httpx.get(f"{env('ACCOUNTS_API_URL')}/drivers/{driver_id}/contact", timeout=5.0)
    resp.raise_for_status()
    body = resp.json()
    return Contact(phone=body.get("phone"), email=body.get("email"))
