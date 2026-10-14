import logging

import occupancy_pb2
import occupancy_pb2_grpc
from common_py.cache import SharedCache

from . import repo
from .overstay import OverstayWatcher

log = logging.getLogger("occupancy.feed")


class OccupancyFeedService(occupancy_pb2_grpc.OccupancyFeedServicer):
    """Server side of the bidirectional stream: persist each bay change, refresh
    the shared cache that pricing and the dashboard read, and ack the sequence."""

    def __init__(self) -> None:
        self._cache = SharedCache()
        self._overstay = OverstayWatcher()

    def Stream(self, request_iterator, context):
        for update in request_iterator:
            try:
                repo.upsert_bay(update.zone_id, update.bay_id, update.occupied, update.plate or None)
                self._cache.set_bay(update.zone_id, update.bay_id, update.occupied)
                self._cache.set_occupancy(update.zone_id, repo.percent_full(update.zone_id))
                self._overstay.check(update.zone_id, update.bay_id, update.plate)
                yield occupancy_pb2.Ack(sequence=update.sequence, accepted=True)
            except Exception:  # noqa: BLE001 - one bad update must not kill the stream
                log.exception("failed to apply update %s", update.sequence)
                yield occupancy_pb2.Ack(sequence=update.sequence, accepted=False)
