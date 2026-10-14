import asyncio
import json
import logging
from typing import AsyncIterator

import websockets

from common_py.config import env

log = logging.getLogger("sensor-gateway.vendor")


async def vendor_messages() -> AsyncIterator[dict]:
    """Yields decoded messages from the sensor vendor's WebSocket feed and
    reconnects with a short back-off whenever the connection drops."""
    url = env("SENSORCLOUD_WS_URL")
    token = env("SENSORCLOUD_TOKEN")
    while True:
        try:
            async with websockets.connect(url, extra_headers={"Authorization": f"Bearer {token}"}) as ws:
                log.info("connected to sensor vendor")
                async for frame in ws:
                    yield json.loads(frame)
        except (websockets.ConnectionClosed, OSError) as exc:
            log.warning("vendor feed dropped: %s", exc)
            await asyncio.sleep(2)
