from fastapi import FastAPI

from common_py.cache import SharedCache

from . import repo

app = FastAPI(title="occupancy")
_cache = SharedCache()


@app.get("/v1/bays/{zone_id}")
def bays(zone_id: str) -> dict:
    """Live bay list for a zone, plus the percent-full figure the cache holds."""
    return {
        "zone_id": zone_id,
        "percent_full": _cache.get_occupancy(zone_id),
        "bays": repo.bays_in_zone(zone_id),
    }
