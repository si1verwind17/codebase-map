package city.parking.billing

import city.parking.common.Config
import com.stripe.Stripe
import com.stripe.model.{PaymentIntent, Refund}
import com.stripe.param.{PaymentIntentConfirmParams, RefundCreateParams}
import zio.*

/** Confirms or refunds Stripe payment intents (https://api.stripe.com). */
trait StripeCharger:
  def confirm(paymentIntentId: String): Task[Unit]
  def refund(paymentIntentId: String): Task[Unit]

object StripeCharger:

  val live: ZLayer[Any, Throwable, StripeCharger] =
    ZLayer:
      Config.env("STRIPE_API_KEY").map: key =>
        Stripe.apiKey = key
        new StripeCharger:
          def confirm(paymentIntentId: String): Task[Unit] =
            ZIO.attemptBlocking:
              PaymentIntent
                .retrieve(paymentIntentId)
                .confirm(PaymentIntentConfirmParams.builder().build())
              ()

          def refund(paymentIntentId: String): Task[Unit] =
            ZIO.attemptBlocking:
              Refund.create(RefundCreateParams.builder().setPaymentIntent(paymentIntentId).build())
              ()
