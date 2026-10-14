package city.parking.pricing

import city.parking.common.Config
import io.lettuce.core.RedisClient
import zio.*

/** Read side of the cache shared between several services (SHARED_CACHE_URL).
  * The occupancy service writes `occupancy:<zone>` (percent full, 0-100);
  * pricing reads it to apply a surge factor. Pricing never writes here.
  */
trait SharedCache:
  def occupancyPercent(zoneId: String): Task[Option[Int]]

object SharedCache:

  val live: ZLayer[Any, Throwable, SharedCache] =
    ZLayer.scoped:
      for
        url <- Config.env("SHARED_CACHE_URL")
        cli <- ZIO.acquireRelease(ZIO.attempt(RedisClient.create(url)))(c => ZIO.succeed(c.shutdown()))
        con <- ZIO.attempt(cli.connect().sync())
      yield new SharedCache:
        def occupancyPercent(zoneId: String): Task[Option[Int]] =
          ZIO.attemptBlocking(Option(con.get(s"occupancy:$zoneId")).flatMap(_.toIntOption))
