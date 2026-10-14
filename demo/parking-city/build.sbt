ThisBuild / scalaVersion := "3.3.4"
ThisBuild / organization := "city.parking"
ThisBuild / version      := "0.4.0"

val zioV     = "2.1.9"
val tapirV   = "1.11.7"
val zioHttpV = "3.0.1"

lazy val common = project
  .in(file("common"))
  .settings(
    libraryDependencies ++= Seq(
      "dev.zio"          %% "zio"        % zioV,
      "dev.zio"          %% "zio-kafka"  % "2.8.3",
      "org.postgresql"    % "postgresql" % "42.7.4",
      "com.zaxxer"        % "HikariCP"   % "5.1.0"
    )
  )

lazy val reservations = project
  .in(file("reservations"))
  .dependsOn(common)
  .enablePlugins(JavaAppPackaging)
  .settings(
    libraryDependencies ++= Seq(
      "com.softwaremill.sttp.tapir" %% "tapir-zio-http-server" % tapirV,
      "com.softwaremill.sttp.tapir" %% "tapir-json-zio"        % tapirV,
      "dev.zio"                     %% "zio-http"              % zioHttpV,
      "io.lettuce"                   % "lettuce-core"          % "6.4.0.RELEASE",
      "com.stripe"                   % "stripe-java"           % "27.1.0"
    )
  )

lazy val pricing = project
  .in(file("pricing"))
  .dependsOn(common)
  .enablePlugins(JavaAppPackaging)
  .settings(
    libraryDependencies ++= Seq(
      "com.softwaremill.sttp.tapir" %% "tapir-zio-http-server" % tapirV,
      "com.softwaremill.sttp.tapir" %% "tapir-json-zio"        % tapirV,
      "dev.zio"                     %% "zio-http"              % zioHttpV,
      "io.lettuce"                   % "lettuce-core"          % "6.4.0.RELEASE"
    )
  )

lazy val billing = project
  .in(file("billing"))
  .dependsOn(common)
  .enablePlugins(JavaAppPackaging)
  .settings(
    libraryDependencies ++= Seq(
      "com.softwaremill.sttp.tapir" %% "tapir-zio-http-server" % tapirV,
      "com.softwaremill.sttp.tapir" %% "tapir-json-zio"        % tapirV,
      "dev.zio"                     %% "zio-http"              % zioHttpV,
      "software.amazon.awssdk"       % "s3"                    % "2.28.11",
      "com.stripe"                   % "stripe-java"           % "27.1.0"
    )
  )

lazy val root = project.in(file(".")).aggregate(common, reservations, pricing, billing)
