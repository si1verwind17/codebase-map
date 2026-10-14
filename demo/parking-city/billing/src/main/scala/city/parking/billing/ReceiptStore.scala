package city.parking.billing

import city.parking.common.Config
import software.amazon.awssdk.core.sync.RequestBody
import software.amazon.awssdk.services.s3.S3Client
import software.amazon.awssdk.services.s3.model.PutObjectRequest
import zio.*

/** Stores receipt PDFs in the S3 bucket named by RECEIPTS_BUCKET. The nightly
  * export jobs write to the same bucket under the exports/ prefix.
  */
trait ReceiptStore:
  def put(invoice: Invoice, pdf: Array[Byte]): Task[String]

object ReceiptStore:

  val live: ZLayer[Any, Throwable, ReceiptStore] =
    ZLayer.scoped:
      for
        bucket <- Config.env("RECEIPTS_BUCKET")
        s3     <- ZIO.acquireRelease(ZIO.attempt(S3Client.create()))(c => ZIO.succeed(c.close()))
      yield new ReceiptStore:
        def put(invoice: Invoice, pdf: Array[Byte]): Task[String] =
          val key = s"receipts/${invoice.driverId}/${invoice.id}.pdf"
          ZIO
            .attemptBlocking:
              s3.putObject(
                PutObjectRequest.builder().bucket(bucket).key(key).contentType("application/pdf").build(),
                RequestBody.fromBytes(pdf)
              )
            .as(key)
