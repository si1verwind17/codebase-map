package city.parking.billing

import city.parking.common.EventProducer
import zio.*

/** Dead-letter parking for events billing could not process. The message is
  * wrapped with the failure reason and published to reservation-events.dlq;
  * an operator replays or discards it by hand.
  */
trait DeadLetters:
  def park(key: String, value: String, reason: String): Task[Unit]

object DeadLetters:

  val Topic = "reservation-events.dlq"

  val live: ZLayer[EventProducer, Nothing, DeadLetters] =
    ZLayer.fromFunction: (producer: EventProducer) =>
      new DeadLetters:
        def park(key: String, value: String, reason: String): Task[Unit] =
          val escaped = reason.replace("\"", "'")
          producer.publish(Topic, key, s"""{"reason":"$escaped","original":$value}""")
