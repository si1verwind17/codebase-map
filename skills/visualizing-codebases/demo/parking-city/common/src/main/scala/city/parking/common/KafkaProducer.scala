package city.parking.common

import org.apache.kafka.clients.producer.ProducerRecord
import zio.*
import zio.kafka.producer.{Producer, ProducerSettings}
import zio.kafka.serde.Serde

/** One producer wrapper for every service that publishes events. The topic is
  * always passed explicitly so a reader can follow it to a consumer.
  */
trait EventProducer:
  def publish(topic: String, key: String, json: String): Task[Unit]

object EventProducer:

  val live: ZLayer[Any, Throwable, EventProducer] =
    ZLayer.scoped:
      for
        brokers  <- Config.kafkaBrokers
        producer <- Producer.make(ProducerSettings(brokers))
      yield Live(producer)

  private final class Live(producer: Producer) extends EventProducer:
    def publish(topic: String, key: String, json: String): Task[Unit] =
      producer
        .produce(ProducerRecord(topic, key, json), Serde.string, Serde.string)
        .unit
