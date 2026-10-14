package city.parking.common

import zio.*

/** Environment-based configuration. Every service reads its endpoints and
  * credentials through these helpers so that docker-compose.yml is the single
  * place where wiring is declared.
  */
object Config:

  def env(key: String): Task[String] =
    ZIO
      .attempt(sys.env.getOrElse(key, throw new IllegalStateException(s"missing env var $key")))

  def envOr(key: String, default: String): String =
    sys.env.getOrElse(key, default)

  def envInt(key: String, default: Int): Int =
    sys.env.get(key).flatMap(_.toIntOption).getOrElse(default)

  /** Postgres connection settings, shared by every Scala service. */
  final case class Db(host: String, port: Int, name: String, user: String, password: String):
    def jdbcUrl: String = s"jdbc:postgresql://$host:$port/$name"

  def db: Task[Db] =
    for
      host <- env("DB_HOST")
      user <- env("DB_USER")
      pass <- env("DB_PASSWORD")
    yield Db(host, envInt("DB_PORT", 5432), envOr("DB_NAME", "parking"), user, pass)

  /** Kafka bootstrap servers. */
  def kafkaBrokers: Task[List[String]] =
    env("KAFKA_BROKERS").map(_.split(',').toList.map(_.trim))
