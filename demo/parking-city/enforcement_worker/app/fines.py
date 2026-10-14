import httpx

from common_py.config import env

AMOUNTS = {"overstay": 4500, "no_reservation": 6000}


class FinesClient:
    """Posts fines to the city's fines API (base URL FINES_API_URL), which is
    run by the municipality, not by this system."""

    def __init__(self) -> None:
        self._base = env("FINES_API_URL")
        self._client = httpx.Client(timeout=10.0, headers={"X-Api-Key": env("FINES_API_KEY")})

    def issue(self, violation: dict) -> str:
        resp = self._client.post(
            f"{self._base}/v2/fines",
            json={
                "plate": violation["plate"],
                "zone": violation["zone_id"],
                "bay": violation["bay_id"],
                "reason": violation["kind"],
                "amount_cents": AMOUNTS.get(violation["kind"], 4500),
            },
        )
        resp.raise_for_status()
        return resp.json()["fine_id"]
