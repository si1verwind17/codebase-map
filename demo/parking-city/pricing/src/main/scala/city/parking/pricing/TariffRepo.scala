package city.parking.pricing

import city.parking.common.Jdbc
import zio.*

final case class Tariff(zoneId: String, centsPerHour: Long, currency: String)
final case class Zone(id: String, name: String, address: String, lat: Option[Double], lng: Option[Double])

/** Read-only view of reference data: tariffs, zones, and the demand forecast
  * written nightly by the demand-forecast Airflow DAG.
  */
trait TariffRepo:
  def tariff(zoneId: String): Task[Option[Tariff]]
  def zone(zoneId: String): Task[Option[Zone]]
  def saveCoordinates(zoneId: String, lat: Double, lng: Double): Task[Unit]
  def demandIndex(zoneId: String, hourOfDay: Int): Task[Option[Double]]

object TariffRepo:

  val live: ZLayer[Jdbc, Nothing, TariffRepo] = ZLayer.fromFunction(Live(_))

  private final class Live(db: Jdbc) extends TariffRepo:

    def tariff(zoneId: String): Task[Option[Tariff]] =
      db.query(
        "SELECT zone_id, cents_per_hour, currency FROM tariffs WHERE zone_id = ? AND active",
        zoneId
      )(rs => Tariff(rs.getString(1), rs.getLong(2), rs.getString(3))).map(_.headOption)

    def zone(zoneId: String): Task[Option[Zone]] =
      db.query("SELECT id, name, address, lat, lng FROM zones WHERE id = ?", zoneId): rs =>
        Zone(
          rs.getString(1), rs.getString(2), rs.getString(3),
          Option(rs.getObject(4)).map(_ => rs.getDouble(4)),
          Option(rs.getObject(5)).map(_ => rs.getDouble(5))
        )
      .map(_.headOption)

    def saveCoordinates(zoneId: String, lat: Double, lng: Double): Task[Unit] =
      db.update("UPDATE zones SET lat = ?, lng = ? WHERE id = ?", lat, lng, zoneId).unit

    def demandIndex(zoneId: String, hourOfDay: Int): Task[Option[Double]] =
      db.query(
        "SELECT demand_index FROM demand_forecast WHERE zone_id = ? AND hour_of_day = ?",
        zoneId, hourOfDay
      )(_.getDouble(1)).map(_.headOption)
