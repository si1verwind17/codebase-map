import redis

from .config import env


class SharedCache:
    """Client for the cache shared by occupancy (writer) and pricing and
    city-dashboard (readers). Address comes from SHARED_CACHE_URL."""

    def __init__(self) -> None:
        self._r = redis.Redis.from_url(env("SHARED_CACHE_URL"), decode_responses=True)

    def set_occupancy(self, zone_id: str, percent: int) -> None:
        self._r.set(f"occupancy:{zone_id}", percent, ex=300)

    def get_occupancy(self, zone_id: str) -> int | None:
        value = self._r.get(f"occupancy:{zone_id}")
        return int(value) if value is not None else None

    def set_bay(self, zone_id: str, bay_id: str, occupied: bool) -> None:
        self._r.hset(f"bays:{zone_id}", bay_id, "1" if occupied else "0")

    def bays(self, zone_id: str) -> dict[str, bool]:
        return {k: v == "1" for k, v in self._r.hgetall(f"bays:{zone_id}").items()}
