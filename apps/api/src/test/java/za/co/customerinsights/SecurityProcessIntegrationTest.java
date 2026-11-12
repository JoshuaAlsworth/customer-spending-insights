package za.co.customerinsights;

import static org.assertj.core.api.Assertions.assertThat;

import com.jayway.jsonpath.JsonPath;
import java.io.IOException;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.ServerSocket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.sql.DriverManager;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class SecurityProcessIntegrationTest {
    private static final String STORE_PASSWORD = "local-test-only";
    @TempDir Path temp;

    @Test
    void missingMalformedAndWeakCursorSecretsRejectStartup() throws Exception {
        var database = FinancialIntegrationTest.db;
        for (String supplied : new String[] {null, "too-short", "z".repeat(64), "0".repeat(64)}) {
            var command =
                    new ArrayList<>(
                            Arrays.asList(
                                    Path.of(System.getProperty("java.home"), "bin", "java")
                                            .toString(),
                                    "-jar",
                                    System.getProperty("csi.test.jar"),
                                    "--spring.main.web-application-type=none",
                                    "--DATABASE_URL=" + database.getJdbcUrl(),
                                    "--DATABASE_USER=customer_insights_api",
                                    "--DATABASE_PASSWORD=testapi"));
            var builder = new ProcessBuilder(command).redirectErrorStream(true);
            builder.environment().remove("CURSOR_SECRET");
            if (supplied != null) builder.environment().put("CURSOR_SECRET", supplied);
            Path log =
                    temp.resolve(
                            "invalid-"
                                    + (supplied == null ? "missing" : supplied.length())
                                    + ".log");
            builder.redirectOutput(log.toFile());
            Process process = builder.start();
            try {
                assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
                assertThat(process.exitValue()).isNotZero();
                assertThat(Files.readString(log)).contains("CURSOR_SECRET");
                if (supplied != null) assertThat(Files.readString(log)).doesNotContain(supplied);
            } finally {
                stop(process);
            }
        }
    }

    @Test
    void trustedHttpsCookiesSharedSessionsAndConcurrentLoginLimits() throws Exception {
        // Reuse the disposable, migrated PostgreSQL fixture from the API integration suite.
        var database = FinancialIntegrationTest.db;
        Path store = temp.resolve("localhost.p12");
        String keytool = Path.of(System.getProperty("java.home"), "bin", "keytool").toString();
        var certificate =
                new ProcessBuilder(
                                keytool,
                                "-genkeypair",
                                "-alias",
                                "localhost",
                                "-keyalg",
                                "RSA",
                                "-keysize",
                                "2048",
                                "-validity",
                                "1",
                                "-storetype",
                                "PKCS12",
                                "-keystore",
                                store.toString(),
                                "-storepass",
                                STORE_PASSWORD,
                                "-keypass",
                                STORE_PASSWORD,
                                "-dname",
                                "CN=localhost",
                                "-ext",
                                "SAN=dns:localhost,ip:127.0.0.1")
                        .redirectErrorStream(true)
                        .start();
        assertThat(certificate.waitFor()).isZero();
        KeyStore trusted = KeyStore.getInstance("PKCS12");
        try (var input = Files.newInputStream(store)) {
            trusted.load(input, STORE_PASSWORD.toCharArray());
        }
        var managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        managers.init(trusted);
        SSLContext tls = SSLContext.getInstance("TLS");
        tls.init(null, managers.getTrustManagers(), null);

        int portA = freePort(), portB = freePort();
        Process replicaA = null, replicaB = null;
        try {
            replicaA = start(portA, store, "a");
            replicaB = start(portB, store, "b");
            HttpClient browser = client(tls);
            ready(browser, portA);
            ready(browser, portB);
            var csrf = send(browser, portA, "GET", "/api/v1/auth/csrf", null, null);
            assertThat(csrf.statusCode()).isEqualTo(200);
            String csrfCookie = cookie(csrf, "XSRF-TOKEN");
            assertThat(csrfCookie)
                    .contains("Path=/", "SameSite=Lax", "Secure")
                    .doesNotContain("Domain=");
            assertThat(csrfCookie).doesNotContain("HttpOnly"); // SPA reads this cookie.
            assertThat(
                            send(
                                            browser,
                                            portA,
                                            "POST",
                                            "/api/v1/auth/login",
                                            login("fixture-f04", "fixture-only-password"),
                                            null)
                                    .statusCode())
                    .isEqualTo(403);
            assertThat(
                            send(
                                            browser,
                                            portA,
                                            "POST",
                                            "/api/v1/auth/login",
                                            login("fixture-f04", "fixture-only-password"),
                                            "wrong")
                                    .statusCode())
                    .isEqualTo(403);
            var authenticated =
                    send(
                            browser,
                            portA,
                            "POST",
                            "/api/v1/auth/login",
                            login("fixture-f04", "fixture-only-password"),
                            token(csrf));
            assertThat(authenticated.statusCode()).isEqualTo(200);
            String sessionCookie = cookie(authenticated, "SESSION");
            assertThat(sessionCookie)
                    .contains("Path=/", "SameSite=Lax", "Secure", "HttpOnly")
                    .doesNotContain("Domain=");
            assertThat(cookie(authenticated, "XSRF-TOKEN")).contains("Secure", "SameSite=Lax");
            assertThat(
                            send(
                                            browser,
                                            portA,
                                            "POST",
                                            "/api/v1/auth/login",
                                            login("fixture-f04", "fixture-only-password"),
                                            token(csrf))
                                    .statusCode())
                    .isEqualTo(403);
            var rotateCsrf = send(browser, portA, "GET", "/api/v1/auth/csrf", null, null);
            var rotated =
                    send(
                            browser,
                            portA,
                            "POST",
                            "/api/v1/auth/login",
                            login("fixture-f04", "fixture-only-password"),
                            token(rotateCsrf));
            assertThat(rotated.statusCode()).isEqualTo(200);
            assertThat(cookie(rotated, "SESSION")).isNotEqualTo(sessionCookie);
            var oldSessionRequest =
                    HttpRequest.newBuilder(
                                    URI.create("https://localhost:" + portB + "/api/v1/accounts"))
                            .header("Cookie", sessionCookie.split(";", 2)[0])
                            .GET()
                            .build();
            assertThat(
                            client(tls)
                                    .send(oldSessionRequest, HttpResponse.BodyHandlers.ofString())
                                    .statusCode())
                    .isEqualTo(401);
            assertThat(send(browser, portB, "GET", "/api/v1/accounts", null, null).statusCode())
                    .isEqualTo(200);
            var crossCsrf = send(browser, portB, "GET", "/api/v1/auth/csrf", null, null);
            assertThat(
                            send(
                                            browser,
                                            portB,
                                            "POST",
                                            "/api/v1/auth/logout",
                                            null,
                                            token(crossCsrf))
                                    .statusCode())
                    .isEqualTo(204);
            assertThat(send(browser, portA, "GET", "/api/v1/accounts", null, null).statusCode())
                    .isEqualTo(401);
            assertThat(send(browser, portB, "GET", "/api/v1/accounts", null, null).statusCode())
                    .isEqualTo(401);

            var nextCsrf = send(browser, portB, "GET", "/api/v1/auth/csrf", null, null);
            var relogin =
                    send(
                            browser,
                            portB,
                            "POST",
                            "/api/v1/auth/login",
                            login("fixture-f04", "fixture-only-password"),
                            token(nextCsrf));
            assertThat(relogin.statusCode()).isEqualTo(200);
            String historyPath = "/api/v1/transactions?from=2025-10-30&to=2025-11-02&limit=1";
            var firstPage = send(browser, portB, "GET", historyPath, null, null);
            assertThat(firstPage.statusCode()).isEqualTo(200);
            String cursor = JsonPath.read(firstPage.body(), "$.nextCursor");
            assertThat(cursor).isNotBlank();
            String nextPagePath = historyPath + "&cursor=" + cursor;
            assertThat(send(browser, portA, "GET", nextPagePath, null, null).statusCode())
                    .isEqualTo(200);
            stop(replicaA);
            replicaA = start(portA, store, "a-rotated", FinancialIntegrationTest.newCursorSecret());
            ready(browser, portA);
            var rotatedCursorResponse = send(browser, portA, "GET", nextPagePath, null, null);
            assertThat(rotatedCursorResponse.statusCode()).isEqualTo(400);
            assertThat(rotatedCursorResponse.body())
                    .contains("INVALID_REQUEST")
                    .doesNotContain("CURSOR_SECRET");
            stop(replicaA);
            replicaA = start(portA, store, "a-restarted");
            ready(browser, portA);
            assertThat(send(browser, portA, "GET", nextPagePath, null, null).statusCode())
                    .isEqualTo(200);
            assertThat(send(browser, portA, "GET", "/api/v1/accounts", null, null).statusCode())
                    .isEqualTo(200);
            var finalCsrf = send(browser, portA, "GET", "/api/v1/auth/csrf", null, null);
            assertThat(
                            send(
                                            browser,
                                            portA,
                                            "POST",
                                            "/api/v1/auth/logout",
                                            null,
                                            token(finalCsrf))
                                    .statusCode())
                    .isEqualTo(204);
            assertThat(send(browser, portB, "GET", "/api/v1/accounts", null, null).statusCode())
                    .isEqualTo(401);

            try (var admin =
                            DriverManager.getConnection(
                                    database.getJdbcUrl(),
                                    database.getUsername(),
                                    database.getPassword());
                    var statement = admin.createStatement()) {
                statement.executeUpdate("DELETE FROM login_attempts WHERE login_key='fixture-f04'");
            }
            var jobs = new ArrayList<Callable<Integer>>();
            for (int n = 0; n < 6; n++) {
                final int port = n % 2 == 0 ? portA : portB;
                jobs.add(() -> {
                    HttpClient attacker = client(tls);
                    var challenge = send(attacker, port, "GET", "/api/v1/auth/csrf", null, null);
                    return send(
                                    attacker,
                                    port,
                                    "POST",
                                    "/api/v1/auth/login",
                                    login("fixture-f04", "wrong"),
                                    token(challenge))
                            .statusCode();
                });
            }
            try (var pool = Executors.newFixedThreadPool(6)) {
                for (var outcome : pool.invokeAll(jobs)) assertThat(outcome.get()).isEqualTo(401);
            }
            try (var admin =
                            DriverManager.getConnection(
                                    database.getJdbcUrl(),
                                    database.getUsername(),
                                    database.getPassword());
                    var statement = admin.createStatement()) {
                try (var rows =
                        statement.executeQuery(
                                "SELECT attempts,blocked_until>now() FROM login_attempts WHERE login_key='fixture-f04'")) {
                    assertThat(rows.next()).isTrue();
                    assertThat(rows.getInt(1)).isEqualTo(5);
                    assertThat(rows.getBoolean(2)).isTrue();
                }
            }
            HttpClient locked = client(tls);
            var lockedCsrf = send(locked, portA, "GET", "/api/v1/auth/csrf", null, null);
            assertThat(
                            send(
                                            locked,
                                            portA,
                                            "POST",
                                            "/api/v1/auth/login",
                                            login("fixture-f04", "fixture-only-password"),
                                            token(lockedCsrf))
                                    .statusCode())
                    .isEqualTo(401);
            long[] knownTime = new long[4], unknownTime = new long[4];
            for (int n = 0; n < 4; n++) {
                long start = System.nanoTime();
                var knownDenied =
                        send(
                                locked,
                                portA,
                                "POST",
                                "/api/v1/auth/login",
                                login("fixture-f04", "wrong"),
                                token(lockedCsrf));
                knownTime[n] = System.nanoTime() - start;
                start = System.nanoTime();
                var unknownDenied =
                        send(
                                locked,
                                portA,
                                "POST",
                                "/api/v1/auth/login",
                                login("missing-process-timing-" + n, "wrong"),
                                token(lockedCsrf));
                unknownTime[n] = System.nanoTime() - start;
                assertThat(knownDenied.statusCode())
                        .isEqualTo(unknownDenied.statusCode())
                        .isEqualTo(401);
                assertThat(JsonPath.<String>read(knownDenied.body(), "$.code"))
                        .isEqualTo(JsonPath.<String>read(unknownDenied.body(), "$.code"));
            }
            Arrays.sort(knownTime);
            Arrays.sort(unknownTime);
            System.out.printf(
                    "Known/unknown denied-login median: %.1f/%.1f ms%n",
                    knownTime[2] / 1_000_000.0, unknownTime[2] / 1_000_000.0);
            assertThat(knownTime[2]).isLessThan(unknownTime[2] * 3);
            assertThat(unknownTime[2]).isLessThan(knownTime[2] * 3);
            try (var admin =
                            DriverManager.getConnection(
                                    database.getJdbcUrl(),
                                    database.getUsername(),
                                    database.getPassword());
                    var statement = admin.createStatement()) {
                statement.executeUpdate(
                        "UPDATE login_attempts SET blocked_until=now()-interval '1 second' WHERE login_key='fixture-f04'");
            }
            assertThat(
                            send(
                                            locked,
                                            portA,
                                            "POST",
                                            "/api/v1/auth/login",
                                            login("fixture-f04", "fixture-only-password"),
                                            token(lockedCsrf))
                                    .statusCode())
                    .isEqualTo(200);
            for (int n = 0; n < 8; n++) {
                HttpClient unknown = client(tls);
                var challenge = send(unknown, portB, "GET", "/api/v1/auth/csrf", null, null);
                var denied =
                        send(
                                unknown,
                                portB,
                                "POST",
                                "/api/v1/auth/login",
                                login("missing-process-" + n, "wrong"),
                                token(challenge));
                assertThat(denied.statusCode()).isEqualTo(401);
                assertThat(denied.body())
                        .contains("INVALID_CREDENTIALS")
                        .doesNotContain("missing-process-");
            }
            try (var admin =
                            DriverManager.getConnection(
                                    database.getJdbcUrl(),
                                    database.getUsername(),
                                    database.getPassword());
                    var statement = admin.createStatement();
                    var rows =
                            statement.executeQuery(
                                    "SELECT count(*) FROM login_attempts WHERE login_key LIKE 'missing-process-%'")) {
                assertThat(rows.next()).isTrue();
                assertThat(rows.getInt(1)).isZero();
            }
        } finally {
            stop(replicaA);
            stop(replicaB);
        }
    }

    private Process start(int port, Path store, String name) throws IOException {
        return start(port, store, name, FinancialIntegrationTest.TEST_CURSOR_SECRET);
    }

    private Process start(int port, Path store, String name, String cursorSecret)
            throws IOException {
        var builder =
                new ProcessBuilder(
                                Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                                "-Xmx512m",
                                "-jar",
                                System.getProperty("csi.test.jar"),
                                "--server.port=" + port,
                                "--server.ssl.enabled=true",
                                "--server.ssl.key-store=" + store,
                                "--server.ssl.key-store-password=" + STORE_PASSWORD,
                                "--server.ssl.key-store-type=PKCS12",
                                "--server.ssl.key-alias=localhost",
                                "--COOKIE_SECURE=true",
                                "--DATABASE_URL=" + FinancialIntegrationTest.db.getJdbcUrl(),
                                "--DATABASE_USER=customer_insights_api",
                                "--DATABASE_PASSWORD=testapi")
                        .redirectErrorStream(true)
                        .redirectOutput(temp.resolve(name + ".log").toFile());
        builder.environment().put("CURSOR_SECRET", cursorSecret);
        return builder.start();
    }

    private static HttpClient client(SSLContext tls) {
        return HttpClient.newBuilder()
                .sslContext(tls)
                .cookieHandler(new CookieManager(null, CookiePolicy.ACCEPT_ALL))
                .connectTimeout(Duration.ofSeconds(3))
                .build();
    }

    private static HttpResponse<String> send(
            HttpClient client, int port, String method, String path, String body, String token)
            throws Exception {
        var builder =
                HttpRequest.newBuilder(URI.create("https://localhost:" + port + path))
                        .timeout(Duration.ofSeconds(20));
        if (token != null) builder.header("X-XSRF-TOKEN", token);
        if (body != null) builder.header("Content-Type", "application/json");
        builder.method(
                method,
                body == null
                        ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body));
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static String login(String id, String password) {
        return "{\"loginId\":\"" + id + "\",\"password\":\"" + password + "\"}";
    }

    private static String token(HttpResponse<String> response) {
        return JsonPath.read(response.body(), "$.token");
    }

    private static String cookie(HttpResponse<String> response, String name) {
        return response.headers().allValues("Set-Cookie").stream()
                .filter(value -> value.startsWith(name + "="))
                .findFirst()
                .orElseThrow();
    }

    private static int freePort() throws IOException {
        try (var socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        }
    }

    private static void ready(HttpClient client, int port) throws Exception {
        for (int n = 0; n < 100; n++) {
            try {
                if (send(client, port, "GET", "/actuator/health", null, null).statusCode() == 200)
                    return;
            } catch (IOException ignored) {
            }
            Thread.sleep(200);
        }
        throw new AssertionError("HTTPS replica did not become healthy on port " + port);
    }

    private static void stop(Process process) throws InterruptedException {
        if (process == null) return;
        process.destroy();
        if (!process.waitFor(5, java.util.concurrent.TimeUnit.SECONDS)) process.destroyForcibly();
    }
}
