# novasim Java 21 simulator — multi-stage: maven build -> slim JRE run.
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -o dependency:go-offline || mvn -q dependency:go-offline
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/target/novasim.jar /app/novasim.jar
ENTRYPOINT ["java", "-jar", "/app/novasim.jar"]
CMD ["--headless", "--rate", "5", "--duration", "86400"]
