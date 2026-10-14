package city.parking.billing

import sttp.tapir.*
import sttp.tapir.generic.auto.*
import sttp.tapir.json.zio.*
import sttp.tapir.ztapir.*
import zio.json.*

final case class SettleResult(settled: Int) derives JsonCodec

/** Internal route, called once a night by the settlement DAG in the
  * nightly-jobs Airflow project. Not exposed outside the cluster.
  */
object SettleEndpoint:

  val settle =
    endpoint.post
      .in("internal" / "settle")
      .out(jsonBody[SettleResult])
      .errorOut(stringBody)

  def routes(svc: BillingService): List[ZServerEndpoint[Any, Any]] =
    List(
      settle.zServerLogic(_ => svc.settle().mapBoth(_.getMessage, SettleResult(_)))
    )
