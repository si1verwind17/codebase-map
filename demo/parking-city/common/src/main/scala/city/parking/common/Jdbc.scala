package city.parking.common

import com.zaxxer.hikari.{HikariConfig, HikariDataSource}
import java.sql.{Connection, PreparedStatement, ResultSet}
import javax.sql.DataSource
import zio.*

/** Thin JDBC helper: a pooled DataSource layer and a few blocking-safe
  * primitives. Repositories in each service write literal SQL and pass it here.
  */
trait Jdbc:
  def query[A](sql: String, params: Any*)(read: ResultSet => A): Task[List[A]]
  def update(sql: String, params: Any*): Task[Int]
  def transaction[A](body: Connection => A): Task[A]

object Jdbc:

  val live: ZLayer[Any, Throwable, Jdbc] =
    ZLayer.scoped:
      for
        cfg <- Config.db
        ds <- ZIO.acquireRelease(ZIO.attempt(pool(cfg)))(p => ZIO.succeed(p.close()))
      yield JdbcLive(ds)

  private def pool(cfg: Config.Db): HikariDataSource =
    val hc = HikariConfig()
    hc.setJdbcUrl(cfg.jdbcUrl)
    hc.setUsername(cfg.user)
    hc.setPassword(cfg.password)
    hc.setMaximumPoolSize(Config.envInt("DB_POOL_SIZE", 8))
    HikariDataSource(hc)

  private final class JdbcLive(ds: DataSource) extends Jdbc:

    def query[A](sql: String, params: Any*)(read: ResultSet => A): Task[List[A]] =
      ZIO.attemptBlocking:
        val c = ds.getConnection
        try
          val ps = bind(c.prepareStatement(sql), params)
          val rs = ps.executeQuery()
          Iterator.continually(rs).takeWhile(_.next()).map(read).toList
        finally c.close()

    def update(sql: String, params: Any*): Task[Int] =
      ZIO.attemptBlocking:
        val c = ds.getConnection
        try bind(c.prepareStatement(sql), params).executeUpdate()
        finally c.close()

    def transaction[A](body: Connection => A): Task[A] =
      ZIO.attemptBlocking:
        val c = ds.getConnection
        try
          c.setAutoCommit(false)
          val a = body(c)
          c.commit()
          a
        catch
          case e: Throwable => c.rollback(); throw e
        finally c.close()

    private def bind(ps: PreparedStatement, params: Seq[Any]): PreparedStatement =
      params.zipWithIndex.foreach((p, i) => ps.setObject(i + 1, p))
      ps
