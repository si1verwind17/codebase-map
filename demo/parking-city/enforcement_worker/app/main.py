"""Enforcement worker: long-polls the SQS work queue of violations.

Compose runs three replicas. They share one queue and take turns: SQS hides a
message from the others while one worker holds it, and the message is deleted
only after the fine was accepted by the city fines API.
"""
import json
import logging

import boto3

from common_py.config import env

from .fines import FinesClient

log = logging.getLogger("enforcement-worker")


def main() -> None:
    sqs = boto3.client("sqs")
    queue_url = env("VIOLATIONS_QUEUE_URL")
    fines = FinesClient()

    while True:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
        )
        for message in resp.get("Messages", []):
            violation = json.loads(message["Body"])
            try:
                fines.issue(violation)
            except Exception:  # noqa: BLE001 - leave it on the queue; it reappears after the timeout
                log.exception("fine rejected for %s", violation.get("plate"))
                continue
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
