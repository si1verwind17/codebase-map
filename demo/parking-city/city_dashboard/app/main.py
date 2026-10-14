"""City dashboard backend.

Receives bay-status messages by Pub/Sub *push* (the subscription in
deploy/pubsub.yaml delivers each message as an HTTP POST) and serves live zone
views from the shared cache.
"""
import base64
import json
from collections import deque

from fastapi import FastAPI, HTTPException

from common_py.cache import SharedCache

app = FastAPI(title="city-dashboard")
_cache = SharedCache()
_recent: deque[dict] = deque(maxlen=200)


@app.post("/pubsub/bay-status", status_code=204)
async def bay_status_push(envelope: dict) -> None:
    """Pub/Sub push endpoint. A non-2xx response makes Pub/Sub redeliver."""
    message = envelope.get("message")
    if not message or "data" not in message:
        raise HTTPException(status_code=400, detail="not a pubsub push envelope")
    update = json.loads(base64.b64decode(message["data"]))
    _recent.append(update)


@app.get("/api/zones/{zone_id}/live")
def zone_live(zone_id: str) -> dict:
    return {
        "zone_id": zone_id,
        "percent_full": _cache.get_occupancy(zone_id),
        "bays": _cache.bays(zone_id),
        "recent_changes": [u for u in _recent if u["zone_id"] == zone_id][-20:],
    }
