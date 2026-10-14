import json

import boto3

from common_py.config import env

from . import repo


class OverstayWatcher:
    """When a car stays past its reservation, queue a violation. The queue is a
    work queue (VIOLATIONS_QUEUE_URL): each message is handled by exactly one
    enforcement-worker replica."""

    def __init__(self) -> None:
        self._sqs = boto3.client("sqs")
        self._queue_url = env("VIOLATIONS_QUEUE_URL")

    def check(self, zone_id: str, bay_id: str, plate: str) -> None:
        if not plate or not repo.overstayed(zone_id, bay_id):
            return
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"zone_id": zone_id, "bay_id": bay_id, "plate": plate, "kind": "overstay"}),
            MessageGroupId=zone_id,
        )
