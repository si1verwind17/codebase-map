"""Sensor gateway.

Stream in:  WebSocket client to the sensor vendor (SENSORCLOUD_WS_URL).
Stream out: gRPC bidirectional stream OccupancyFeed/Stream to the occupancy service.
Fan-out:    every normalised update is also published to the Pub/Sub topic bay-status.
"""
import asyncio
import logging

from common_py.pubsub import Publisher

from .normalise import to_update
from .uplink import OccupancyUplink
from .vendor import vendor_messages

log = logging.getLogger("sensor-gateway")


async def main() -> None:
    publisher = Publisher()
    uplink = OccupancyUplink()
    outbox: asyncio.Queue = asyncio.Queue(maxsize=10_000)

    async def pump_vendor() -> None:
        async for raw in vendor_messages():
            update = to_update(raw)
            if update is None:
                continue
            await outbox.put(update)
            # Other consumers (dashboard push, analytics pull) hang off Pub/Sub.
            await asyncio.to_thread(publisher.publish, "bay-status", update)

    await asyncio.gather(pump_vendor(), uplink.run(outbox))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
