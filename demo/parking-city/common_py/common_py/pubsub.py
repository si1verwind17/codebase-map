import json

from google.cloud import pubsub_v1

from .config import env


class Publisher:
    """Publishes JSON messages to a GCP Pub/Sub topic in GCP_PROJECT."""

    def __init__(self) -> None:
        self._client = pubsub_v1.PublisherClient()
        self._project = env("GCP_PROJECT")

    def publish(self, topic: str, payload: dict) -> str:
        path = self._client.topic_path(self._project, topic)
        future = self._client.publish(path, json.dumps(payload).encode("utf-8"))
        return future.result(timeout=10)


class Puller:
    """Pull-side helper around SubscriberClient.pull for one subscription."""

    def __init__(self, subscription: str) -> None:
        self._client = pubsub_v1.SubscriberClient()
        self._path = self._client.subscription_path(env("GCP_PROJECT"), subscription)

    def pull(self, max_messages: int = 100):
        resp = self._client.pull(request={"subscription": self._path, "max_messages": max_messages})
        return resp.received_messages

    def ack(self, ack_ids: list[str]) -> None:
        if ack_ids:
            self._client.acknowledge(request={"subscription": self._path, "ack_ids": ack_ids})
