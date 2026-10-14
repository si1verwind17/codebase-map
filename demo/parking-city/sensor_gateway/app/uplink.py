import asyncio
import logging

import grpc

import occupancy_pb2
import occupancy_pb2_grpc
from common_py.config import env

log = logging.getLogger("sensor-gateway.uplink")


class OccupancyUplink:
    """Client side of the OccupancyFeed/Stream bidirectional gRPC stream."""

    async def run(self, outbox: asyncio.Queue) -> None:
        async with grpc.aio.insecure_channel(env("OCCUPANCY_GRPC_ADDR")) as channel:
            stub = occupancy_pb2_grpc.OccupancyFeedStub(channel)

            async def updates():
                while True:
                    u = await outbox.get()
                    yield occupancy_pb2.BayUpdate(**u)

            async for ack in stub.Stream(updates()):
                if not ack.accepted:
                    log.warning("occupancy rejected sequence %s", ack.sequence)
