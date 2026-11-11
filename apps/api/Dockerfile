FROM eclipse-temurin:25.0.5_8-jdk-alpine@sha256:c7c3d0bdf7f2bbc5a05a6712ed334d198360105634ea9adf76fca94f381b1e3f AS build
WORKDIR /app
COPY gradlew settings.gradle.kts build.gradle.kts ./
COPY gradle ./gradle
RUN chmod +x gradlew && ./gradlew dependencies --configuration runtimeClasspath --no-daemon --quiet > /dev/null
COPY src ./src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:25.0.5_8-jre-alpine@sha256:e1898fd6a11fc965a994d8ace186fd3585aeb636cf8f05f47a723fcfee0b0918
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
