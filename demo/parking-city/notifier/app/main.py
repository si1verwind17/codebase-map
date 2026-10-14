"""Notifier: turns reservation events into SMS and e-mail.

Consumes the reservation-events topic as consumer group "notifier". Compose runs
two replicas; Kafka splits the partitions between them, so each event is handled
once per group (the billing service reads the same topic in its own group).
"""
import json
import logging

from confluent_kafka import Consumer, KafkaError

from common_py.config import env
from common_py.mailer import Mailer
from common_py.sms import SmsClient

from .directory import contact_for
from .templates import render

log = logging.getLogger("notifier")


def main() -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": env("KAFKA_BROKERS"),
            "group.id": "notifier",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe(["reservation-events"])
    sms = SmsClient()
    mailer = Mailer()

    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                log.error("kafka error: %s", msg.error())
            continue
        handle(json.loads(msg.value()), sms, mailer)
        consumer.commit(msg)


def handle(event: dict, sms: SmsClient, mailer: Mailer) -> None:
    text = render(event)
    if text is None:
        return
    contact = contact_for(event["driverId"])
    if contact.phone:
        sms.send(contact.phone, text.short)
    if contact.email:
        mailer.send(contact.email, text.subject, text.long)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
