package city.parking.reservations

import city.parking.common.Config
import com.stripe.Stripe
import com.stripe.model.PaymentIntent
import com.stripe.param.PaymentIntentCreateParams
import zio.*

/** Creates payment intents at Stripe (https://api.stripe.com). The charge is
  * confirmed later by billing; the payment result arrives through the
  * payments-webhook service.
  */
trait StripeGateway:
  def createIntent(reservationId: String, cents: Long, currency: String): Task[String]

object StripeGateway:

  val live: ZLayer[Any, Throwable, StripeGateway] =
    ZLayer:
      Config.env("STRIPE_API_KEY").map: key =>
        Stripe.apiKey = key
        new StripeGateway:
          def createIntent(reservationId: String, cents: Long, currency: String): Task[String] =
            ZIO.attemptBlocking:
              val params = PaymentIntentCreateParams
                .builder()
                .setAmount(cents)
                .setCurrency(currency)
                .putMetadata("reservation_id", reservationId)
                .build()
              PaymentIntent.create(params).getId
