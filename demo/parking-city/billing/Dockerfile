FROM sbtscala/scala-sbt:eclipse-temurin-21.0.4_7_1.10.2_3.3.4 AS build
WORKDIR /src
COPY build.sbt ./
COPY project ./project
COPY common ./common
COPY billing ./billing
RUN sbt "billing/stage"

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/billing/target/universal/stage ./
EXPOSE 8080
ENTRYPOINT ["/app/bin/billing"]
