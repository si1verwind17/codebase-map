package city.parking.reservations

import city.parking.common.Config
import io.lettuce.core.RedisClient
import zio.*
import zio.json.*

/** The reservations service's own Redis (REDIS_URL): a short-lived quote cache
  * so a driver who re-submits a form does not trigger a second pricing call.
  * Nothing else reads this instance.
  */
trait QuoteCache:
  def get(key: String): Task[Option[Quote]]
  def put(key: String, q: Quote): Task[Unit]

object QuoteCache:

  val live: ZLayer[Any, Throwable, QuoteCache] =
    ZLayer.scoped:
      for
        url <- Config.env("REDIS_URL")
        cli <- ZIO.acquireRelease(ZIO.attempt(RedisClient.create(url)))(c => ZIO.succeed(c.shutdown()))
        con <- ZIO.attempt(cli.connect().sync())
      yield new QuoteCache:
        def get(key: String): Task[Option[Quote]] =
          ZIO.attemptBlocking(Option(con.get(s"quote:$key")).flatMap(_.fromJson[Quote].toOption))
        def put(key: String, q: Quote): Task[Unit] =
          ZIO.attemptBlocking(con.setex(s"quote:$key", 120, q.toJson)).unit
