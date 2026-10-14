package city.parking.pricing

import city.parking.common.Config
import zio.*
import zio.http.*
import zio.json.*
import zio.json.ast.Json

/** Resolves a zone address to coordinates with the Google Maps Geocoding API
  * (https://maps.googleapis.com). Results are stored on the zone row so each
  * address is geocoded once.
  */
trait Geocoder:
  def geocode(address: String): Task[Option[(Double, Double)]]

object Geocoder:

  private val Endpoint = "https://maps.googleapis.com/maps/api/geocode/json"

  val live: ZLayer[Client, Throwable, Geocoder] =
    ZLayer:
      for
        client <- ZIO.service[Client]
        key    <- Config.env("MAPS_API_KEY")
      yield new Geocoder:
        def geocode(address: String): Task[Option[(Double, Double)]] =
          ZIO.scoped:
            for
              url  <- ZIO.fromEither(URL.decode(s"$Endpoint?address=${java.net.URLEncoder.encode(address, "UTF-8")}&key=$key"))
              resp <- client.request(Request.get(url))
              body <- resp.body.asString
              json <- ZIO.fromEither(body.fromJson[Json]).mapError(new RuntimeException(_))
            yield location(json)

  private def location(json: Json): Option[(Double, Double)] =
    for
      obj     <- json.asObject
      results <- obj.get("results").flatMap(_.asArray)
      first   <- results.headOption.flatMap(_.asObject)
      loc     <- first.get("geometry").flatMap(_.asObject).flatMap(_.get("location")).flatMap(_.asObject)
      lat     <- loc.get("lat").flatMap(_.asNumber).map(_.value.doubleValue)
      lng     <- loc.get("lng").flatMap(_.asNumber).map(_.value.doubleValue)
    yield (lat, lng)
