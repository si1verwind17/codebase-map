"""Occupancy service: gRPC server for OccupancyFeed/Stream plus a small HTTP API."""
import logging
from concurrent import futures

import grpc
import uvicorn

import occupancy_pb2_grpc

from .api import app as http_app
from .grpc_server import OccupancyFeedService


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    occupancy_pb2_grpc.add_OccupancyFeedServicer_to_server(OccupancyFeedService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    logging.getLogger("occupancy").info("gRPC feed listening on :50051")
    uvicorn.run(http_app, host="0.0.0.0", port=8080)
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
