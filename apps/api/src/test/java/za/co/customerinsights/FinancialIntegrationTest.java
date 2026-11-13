package za.co.customerinsights;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

import com.jayway.jsonpath.JsonPath;
import jakarta.servlet.http.Cookie;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.session.Session;
import org.springframework.session.SessionRepository;
import org.springframework.session.jdbc.JdbcIndexedSessionRepository;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.MountableFile;

@SpringBootTest(properties = {"server.servlet.session.cookie.secure=false", "COOKIE_SECURE=false"})
@AutoConfigureMockMvc
class FinancialIntegrationTest {
    static final String TEST_CURSOR_SECRET = newCursorSecret();

    static String newCursorSecret() {
        byte[] key = new byte[32];
        new SecureRandom().nextBytes(key);
        return HexFormat.of().formatHex(key);
    }

    static final PostgreSQLContainer<?> db =
            new PostgreSQLContainer<>("postgres:17.7-alpine")
                    .withDatabaseName("customer_insights")
                    .withUsername("customer_insights")
                    .withPassword("test")
                    .withCopyFileToContainer(
                            MountableFile.forHostPath(
                                    Path.of("../../tools/db/provision.sh").toAbsolutePath()),
                            "/tmp/provision.sh")
                    .withCopyFileToContainer(
                            MountableFile.forHostPath(
                                    Path.of("../../tools/db/test-fixture.sql").toAbsolutePath()),
                            "/tmp/test-fixture.sql");

    static {
        db.start();
        Flyway.configure()
                .dataSource(db.getJdbcUrl(), db.getUsername(), db.getPassword())
                .locations("classpath:db/migration")
                .load()
                .migrate();
        try {
            check(
                    db.execInContainer(
                            "sh",
                            "-c",
                            "DB_HOST=localhost API_DB_PASSWORD=testapi PGPASSWORD=test sh /tmp/provision.sh"));
            check(
                    db.execInContainer(
                            "sh",
                            "-c",
                            "PGPASSWORD=test psql -U customer_insights -d customer_insights -v ON_ERROR_STOP=1 -f /tmp/test-fixture.sql"));
        } catch (Exception exception) {
            throw new ExceptionInInitializerError(exception);
        }
    }

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", db::getJdbcUrl);
        registry.add("spring.datasource.username", () -> "customer_insights_api");
        registry.add("spring.datasource.password", () -> "testapi");
        registry.add("CURSOR_SECRET", () -> TEST_CURSOR_SECRET);
    }

    static void check(org.testcontainers.containers.Container.ExecResult result) {
        assertThat(result.getExitCode())
                .describedAs(result.getStderr() + result.getStdout())
                .isZero();
    }

    @Autowired MockMvc mvc;
    @Autowired JdbcIndexedSessionRepository sessions;

    @Test
    void unauthenticatedFinancialDataIsDenied() throws Exception {
        assertThat(mvc.perform(get("/actuator/health")).andReturn().getResponse().getStatus())
                .isEqualTo(200);
        assertThat(
                        mvc.perform(get("/actuator/health/liveness"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(200);
        assertThat(mvc.perform(get("/api/v1/accounts")).andReturn().getResponse().getStatus())
                .isEqualTo(401);
        assertThat(mvc.perform(get("/api/v1/dashboard")).andReturn().getResponse().getStatus())
                .isEqualTo(401);
        assertThat(mvc.perform(get("/private")).andReturn().getResponse().getStatus())
                .isEqualTo(401);
        Cookie deniedCookie =
                mvc.perform(get("/api/v1/accounts"))
                        .andReturn()
                        .getResponse()
                        .getCookie("XSRF-TOKEN");
        assertThat(
                        mvc.perform(get("/api/v1/auth/csrf").cookie(deniedCookie))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(200);
    }

    @Test
    void csrfIsRequiredAndBadCredentialsAreGeneric() throws Exception {
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/login")
                                                .contentType("application/json")
                                                .content(
                                                        "{\"loginId\":\"fixture-f09\",\"password\":\"wrong\"}"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(403);
        var csrf = mvc.perform(get("/api/v1/auth/csrf")).andReturn().getResponse();
        String token = token(csrf.getContentAsString());
        Cookie cookie = csrf.getCookie("XSRF-TOKEN");
        assertThat(cookie).isNotNull();
        var bad =
                mvc.perform(
                                post("/api/v1/auth/login")
                                        .contentType("application/json")
                                        .cookie(cookie)
                                        .header("X-XSRF-TOKEN", token)
                                        .content(
                                                "{\"loginId\":\"fixture-f09\",\"password\":\"wrong\"}"))
                        .andReturn()
                        .getResponse();
        assertThat(bad.getStatus()).isEqualTo(401);
        assertThat(bad.getContentAsString()).doesNotContain("fixture-f09");
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/login")
                                                .contentType("application/json")
                                                .cookie(cookie)
                                                .header("X-XSRF-TOKEN", token)
                                                .content(
                                                        "{\"loginId\":\"fixture-f09\",\"password\":\"wrong\",\"customerId\":\"fixture-f01\"}"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
    }

    @Test
    void unknownLoginsDoNotGrowAttemptStateAndValidPasswordRecoversAfterCooldown()
            throws Exception {
        var csrf = mvc.perform(get("/api/v1/auth/csrf")).andReturn().getResponse();
        Cookie cookie = csrf.getCookie("XSRF-TOKEN");
        String header = token(csrf.getContentAsString());
        for (int index = 0; index < 8; index++) {
            String login = index < 6 ? "fixture-f09" : "missing-" + index;
            var denied =
                    mvc.perform(
                                    post("/api/v1/auth/login")
                                            .contentType("application/json")
                                            .cookie(cookie)
                                            .header("X-XSRF-TOKEN", header)
                                            .content(
                                                    "{\"loginId\":\""
                                                            + login
                                                            + "\",\"password\":\"wrong\"}"))
                            .andReturn()
                            .getResponse();
            assertThat(denied.getStatus()).isEqualTo(401);
            assertThat(denied.getContentAsString()).doesNotContain(login);
        }
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            try (var rows =
                    statement.executeQuery(
                            "SELECT count(*) FROM login_attempts WHERE login_key LIKE 'missing-%'")) {
                rows.next();
                assertThat(rows.getInt(1)).isZero();
            }
            try (var rows =
                    statement.executeQuery(
                            "SELECT attempts,blocked_until IS NOT NULL FROM login_attempts WHERE login_key='fixture-f09'")) {
                rows.next();
                assertThat(rows.getInt(1)).isEqualTo(5);
                assertThat(rows.getBoolean(2)).isTrue();
            }
            statement.executeUpdate(
                    "INSERT INTO login_attempts(login_key,attempts,window_started_at) VALUES('stale-test',1,now()-interval '2 days')");
        }
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/login")
                                                .contentType("application/json")
                                                .cookie(cookie)
                                                .header("X-XSRF-TOKEN", header)
                                                .content(
                                                        "{\"loginId\":\"fixture-f09\",\"password\":\"fixture-only-password\"}"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(401);
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            statement.executeUpdate(
                    "UPDATE login_attempts SET blocked_until=now()-interval '1 second' WHERE login_key='fixture-f09'");
        }
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/login")
                                                .contentType("application/json")
                                                .cookie(cookie)
                                                .header("X-XSRF-TOKEN", header)
                                                .content(
                                                        "{\"loginId\":\"fixture-f09\",\"password\":\"fixture-only-password\"}"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(200);
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement();
                var rows =
                        statement.executeQuery(
                                "SELECT count(*) FROM login_attempts WHERE login_key='stale-test'")) {
            rows.next();
            assertThat(rows.getInt(1)).isZero();
        }
    }

    @Test
    void exactOwnedDashboardAndCrossCustomerDenial() throws Exception {
        Cookie session = login("fixture-f09");
        var accounts =
                mvc.perform(get("/api/v1/accounts").cookie(session)).andReturn().getResponse();
        assertThat(accounts.getStatus()).isEqualTo(200);
        assertThat(accounts.getContentAsString())
                .contains("f09-everyday")
                .doesNotContain("f01-everyday");
        var dashboard =
                mvc.perform(get("/api/v1/dashboard").cookie(session)).andReturn().getResponse();
        assertThat(dashboard.getStatus()).isEqualTo(200);
        assertThat(dashboard.getContentAsString())
                .contains("\"incomeMinor\":\"1875000\"")
                .contains("\"grossSpendingMinor\":\"1260050\"")
                .contains("\"spendingCreditsMinor\":\"12000\"")
                .contains("\"netSpendingMinor\":\"1248050\"")
                .contains("\"netMovementMinor\":\"626950\"");
        List<String> weekly =
                JsonPath.read(dashboard.getContentAsString(), "$.trend[*].netSpendingMinor");
        assertThat(weekly).containsExactly("0", "67500", "257550", "305000", "618000");
        List<Map<String, String>> weeks = JsonPath.read(dashboard.getContentAsString(), "$.trend");
        assertThat(weeks.stream().map(item -> item.get("from") + "/" + item.get("to")))
                .containsExactly(
                        "2026-10-01/2026-10-04",
                        "2026-10-05/2026-10-11",
                        "2026-10-12/2026-10-18",
                        "2026-10-19/2026-10-25",
                        "2026-10-26/2026-10-31");
        assertThat(weekly.stream().map(BigInteger::new).reduce(BigInteger.ZERO, BigInteger::add))
                .isEqualTo(new BigInteger("1248050"));
        List<Map<String, String>> categories =
                JsonPath.read(dashboard.getContentAsString(), "$.categories");
        Map<String, String> byCategory =
                categories.stream()
                        .collect(
                                Collectors.toMap(
                                        item -> item.get("categoryCode"),
                                        item -> item.get("netSpendingMinor")));
        assertThat(byCategory)
                .containsExactlyInAnyOrderEntriesOf(
                        Map.of(
                                "HOUSING_UTILITIES",
                                "420000",
                                "GROCERIES",
                                "325000",
                                "TRANSPORT_FUEL",
                                "190000",
                                "MONEY_SENT",
                                "157550",
                                "CASH_WITHDRAWALS",
                                "100000",
                                "UNCATEGORIZED",
                                "60000",
                                "BANK_FEES",
                                "7500",
                                "HEALTH",
                                "-12000"));
        assertThat(
                        byCategory.values().stream()
                                .map(BigInteger::new)
                                .reduce(BigInteger.ZERO, BigInteger::add))
                .isEqualTo(new BigInteger("1248050"));
        var foreign =
                mvc.perform(
                                get("/api/v1/dashboard?accountIds=f09-everyday,f01-everyday")
                                        .cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(foreign.getStatus()).isEqualTo(404);
        assertThat(foreign.getContentType()).startsWith("application/problem+json");
        assertThat(foreign.getContentAsString())
                .contains("\"code\":\"NOT_FOUND\"")
                .contains("\"requestId\"")
                .doesNotContain("f01-everyday");
    }

    @Test
    void exactPostedBalancesUseAnchorsAndFixedReferenceDate() throws Exception {
        String f13 =
                mvc.perform(get("/api/v1/accounts").cookie(login("fixture-f01")))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<String>read(f13, "$.accounts[0].postedBalanceMinor"))
                .isEqualTo("2215000");
        assertThat(JsonPath.<String>read(f13, "$.accounts[1].postedBalanceMinor"))
                .isEqualTo("350000");
        assertThat(JsonPath.<String>read(f13, "$.combinedPostedBalanceMinor")).isEqualTo("2565000");
        assertThat(JsonPath.<String>read(f13, "$.balanceAsOfDate")).isEqualTo("2026-10-31");
        assertThat(JsonPath.<String>read(f13, "$.currency")).isEqualTo("ZAR");
        assertThat(JsonPath.<String>read(f13, "$.dataset.datasetId"))
                .isEqualTo("spending-overview-isolated-fixture-v2");

        Cookie f14Session = login("fixture-f14");
        String f14 =
                mvc.perform(get("/api/v1/accounts").cookie(f14Session))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<String>read(f14, "$.combinedPostedBalanceMinor")).isEqualTo("1000000");
        String september =
                mvc.perform(
                                get("/api/v1/dashboard?from=2026-09-01&to=2026-09-30")
                                        .cookie(f14Session))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        String october =
                mvc.perform(
                                get("/api/v1/dashboard?from=2026-10-01&to=2026-10-31")
                                        .cookie(f14Session))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<String>read(september, "$.summary.netMovementMinor"))
                .isEqualTo("700000");
        assertThat(JsonPath.<String>read(october, "$.summary.netMovementMinor"))
                .isEqualTo("-200000");
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(f14Session))
                                .andReturn()
                                .getResponse()
                                .getContentAsString())
                .isEqualTo(f14);

        String f16 =
                mvc.perform(get("/api/v1/accounts").cookie(login("fixture-f16")))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<String>read(f16, "$.combinedPostedBalanceMinor")).isEqualTo("460000");
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var sql = admin.createStatement();
                var septemberBalance =
                        sql.executeQuery(
                                "SELECT sum(a.opening_balance_minor::numeric + COALESCE((SELECT sum(p.amount_minor::numeric) FROM posted_entries p WHERE p.account_id=a.id AND p.posted_at>=a.balance_anchor_at AND p.posted_at<'2026-10-01 00:00+02'),0)) FROM accounts a WHERE a.customer_id='fixture-f16'")) {
            assertThat(septemberBalance.next()).isTrue();
            assertThat(septemberBalance.getBigDecimal(1).toBigIntegerExact())
                    .isEqualTo(new BigInteger("380000"));
        }
        String f17 =
                mvc.perform(get("/api/v1/accounts").cookie(login("fixture-f17")))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<String>read(f17, "$.accounts[0].postedBalanceMinor"))
                .isEqualTo("-5000");
        assertThat(JsonPath.<String>read(f17, "$.accounts[1].postedBalanceMinor")).isEqualTo("0");
        String closed =
                mvc.perform(get("/api/v1/accounts").cookie(login("fixture-closed")))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<List<?>>read(closed, "$.accounts")).isEmpty();
        assertThat(closed).contains("\"combinedPostedBalanceMinor\":null");
        assertThat(
                        mvc.perform(
                                        get("/api/v1/dashboard?accountIds=closed-only")
                                                .cookie(login("fixture-closed")))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(404);
    }

    @Test
    void legacyAccountWithoutAnchorIsUnavailableRatherThanZero() throws Exception {
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var sql = admin.createStatement()) {
            sql.executeUpdate(
                    "INSERT INTO customers(id,display_name,login_id,status,primary_persona) VALUES('legacy-anchor-customer','Legacy','legacy-anchor-customer','ACTIVE','SALARIED')");
            sql.executeUpdate(
                    "INSERT INTO credentials(customer_id,password_hash) SELECT 'legacy-anchor-customer',password_hash FROM credentials WHERE customer_id='fixture-f09'");
            sql.executeUpdate(
                    "INSERT INTO accounts(id,customer_id,account_kind,alias,masked_suffix,opened_on,status) VALUES('legacy-anchor-account','legacy-anchor-customer','EVERYDAY','Everyday','1234','2026-01-01','OPEN')");
            try {
                var response =
                        mvc.perform(get("/api/v1/accounts").cookie(login("legacy-anchor-customer")))
                                .andReturn()
                                .getResponse();
                assertThat(response.getStatus()).isEqualTo(503);
                assertThat(response.getContentAsString())
                        .doesNotContain("postedBalanceMinor")
                        .doesNotContain("1234");
            } finally {
                sql.executeUpdate("DELETE FROM accounts WHERE id='legacy-anchor-account'");
                sql.executeUpdate(
                        "DELETE FROM credentials WHERE customer_id='legacy-anchor-customer'");
                sql.executeUpdate("DELETE FROM customers WHERE id='legacy-anchor-customer'");
            }
        }
    }

    @Test
    void activityListAndDetailsAreOwnedFilteredAndCursorBound() throws Exception {
        Cookie session = login("fixture-f09");
        var page =
                mvc.perform(
                                get("/api/v1/transactions?from=2026-10-01&to=2026-10-31&limit=2")
                                        .cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(page.getStatus()).isEqualTo(200);
        List<String> firstIds = JsonPath.read(page.getContentAsString(), "$.items[*].id");
        assertThat(firstIds).hasSize(2);
        String cursor = JsonPath.read(page.getContentAsString(), "$.nextCursor");
        assertThat(cursor).isNotBlank();
        var next =
                mvc.perform(
                                get("/api/v1/transactions?from=2026-10-01&to=2026-10-31&limit=2&cursor="
                                                + cursor)
                                        .cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(next.getStatus()).isEqualTo(200);
        List<String> nextIds = JsonPath.read(next.getContentAsString(), "$.items[*].id");
        assertThat(nextIds).doesNotContainAnyElementsOf(firstIds);
        var seen = new java.util.LinkedHashSet<String>(firstIds);
        String traversalCursor = cursor;
        while (traversalCursor != null) {
            var response =
                    mvc.perform(
                                    get("/api/v1/transactions?from=2026-10-01&to=2026-10-31&limit=2&cursor="
                                                    + traversalCursor)
                                            .cookie(session))
                            .andReturn()
                            .getResponse();
            assertThat(response.getStatus()).isEqualTo(200);
            List<String> ids = JsonPath.read(response.getContentAsString(), "$.items[*].id");
            for (String id : ids) assertThat(seen.add(id)).isTrue();
            traversalCursor = JsonPath.read(response.getContentAsString(), "$.nextCursor");
        }
        assertThat(seen).hasSize(13);
        assertThat(
                        mvc.perform(
                                        get("/api/v1/transactions?status=PENDING&category=HEALTH")
                                                .cookie(session))
                                .andReturn()
                                .getResponse()
                                .getContentAsString())
                .contains("\"items\":[]");
        assertThat(
                        mvc.perform(
                                        get("/api/v1/transactions?accountIds=f09-everyday,f01-everyday")
                                                .cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(404);
        assertThat(
                        mvc.perform(get("/api/v1/transactions/pe_f01-original").cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(404);
        assertThat(
                        mvc.perform(get("/api/v1/transactions/au_f01-auth").cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(404);
        assertThat(
                        mvc.perform(get("/api/v1/transactions/invalid").cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        assertThat(
                        mvc.perform(
                                        get("/api/v1/transactions?limit=2&status=POSTED&cursor="
                                                        + cursor)
                                                .cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        assertThat(
                        mvc.perform(
                                        get("/api/v1/transactions")
                                                .param("search", "%")
                                                .cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
    }

    @Test
    void dashboardAndActivityShareReportingScopeRules() throws Exception {
        Cookie owner = login("fixture-f04");
        for (String path : List.of("/api/v1/dashboard", "/api/v1/transactions")) {
            var defaultResponse = mvc.perform(get(path).cookie(owner)).andReturn().getResponse();
            assertThat(defaultResponse.getStatus()).isEqualTo(200);
            if (path.endsWith("dashboard")) {
                assertThat(
                                JsonPath.<String>read(
                                        defaultResponse.getContentAsString(), "$.scope.from"))
                        .isEqualTo("2026-10-01");
                assertThat(
                                JsonPath.<String>read(
                                        defaultResponse.getContentAsString(), "$.scope.to"))
                        .isEqualTo("2026-10-31");
            }
            var explicit =
                    mvc.perform(
                                    get(path)
                                            .param("from", "2025-10-01")
                                            .param("to", "2025-11-30")
                                            .param("accountIds", "f04-savings,f04-everyday")
                                            .cookie(owner))
                            .andReturn()
                            .getResponse();
            assertThat(explicit.getStatus()).isEqualTo(200);
            for (String invalid : List.of("2026-02-30", "2020-01-01", "2026-11-01")) {
                assertThat(
                                mvc.perform(get(path).param("from", invalid).cookie(owner))
                                        .andReturn()
                                        .getResponse()
                                        .getStatus())
                        .isEqualTo(400);
            }
            for (String invalid : List.of("", "f04-everyday,f04-everyday")) {
                assertThat(
                                mvc.perform(get(path).param("accountIds", invalid).cookie(owner))
                                        .andReturn()
                                        .getResponse()
                                        .getStatus())
                        .isEqualTo(400);
            }
            for (String foreign : List.of("f01-everyday", "f04-everyday,f01-everyday")) {
                assertThat(
                                mvc.perform(get(path).param("accountIds", foreign).cookie(owner))
                                        .andReturn()
                                        .getResponse()
                                        .getStatus())
                        .isEqualTo(404);
            }
            assertThat(
                            mvc.perform(get(path).cookie(login("fixture-empty")))
                                    .andReturn()
                                    .getResponse()
                                    .getStatus())
                    .isEqualTo(200);
        }
        var dashboard =
                mvc.perform(
                                get("/api/v1/dashboard")
                                        .param("accountIds", "f04-savings,f04-everyday")
                                        .cookie(owner))
                        .andReturn()
                        .getResponse();
        assertThat(
                        JsonPath.<List<String>>read(
                                dashboard.getContentAsString(), "$.scope.accountIds"))
                .containsExactly("f04-savings", "f04-everyday");
        String firstOrder =
                mvc.perform(
                                get("/api/v1/transactions")
                                        .param("accountIds", "f04-savings,f04-everyday")
                                        .param("from", "2025-10-01")
                                        .param("to", "2025-11-30")
                                        .param("limit", "1")
                                        .cookie(owner))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        String secondOrder =
                mvc.perform(
                                get("/api/v1/transactions")
                                        .param("accountIds", "f04-everyday,f04-savings")
                                        .param("from", "2025-10-01")
                                        .param("to", "2025-11-30")
                                        .param("limit", "1")
                                        .cookie(owner))
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        assertThat(JsonPath.<String>read(firstOrder, "$.nextCursor"))
                .isNotBlank()
                .isEqualTo(JsonPath.<String>read(secondOrder, "$.nextCursor"));
    }

    @Test
    void bothReportingRoutesReturnUnavailableWithoutDataset() throws Exception {
        Cookie owner = login("fixture-f04");
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            statement.execute("CREATE TEMP TABLE saved_dataset AS TABLE dataset_instance");
            statement.executeUpdate("DELETE FROM dataset_instance");
            try {
                for (String path : List.of("/api/v1/dashboard", "/api/v1/transactions")) {
                    assertThat(
                                    mvc.perform(get(path).cookie(owner))
                                            .andReturn()
                                            .getResponse()
                                            .getStatus())
                            .isEqualTo(503);
                }
            } finally {
                statement.executeUpdate("INSERT INTO dataset_instance SELECT * FROM saved_dataset");
            }
        }
    }

    @Test
    void activityKindsSearchAndStaleCursor() throws Exception {
        Cookie session = login("fixture-f09");
        var pending =
                mvc.perform(get("/api/v1/transactions?status=PENDING").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(pending.getStatus()).isEqualTo(200);
        List<Map<String, Object>> items = JsonPath.read(pending.getContentAsString(), "$.items");
        assertThat(items).hasSize(2);
        assertThat(items)
                .allSatisfy(item -> {
                    assertThat(item.get("recordKind")).isEqualTo("AUTHORIZATION");
                    assertThat(item.get("amountMinor")).isNull();
                    assertThat(item).doesNotContainKey("originalActivityId");
                });
        var detail =
                mvc.perform(get("/api/v1/transactions/au_f09-pending1").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(detail.getStatus()).isEqualTo(200);
        assertThat(detail.getContentAsString())
                .contains("\"authorizedAmountMinor\":\"72000\"")
                .contains("\"postedAt\":null");
        var posted =
                mvc.perform(get("/api/v1/transactions/pe_f09-refund").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(posted.getStatus()).isEqualTo(200);
        assertThat(posted.getContentAsString())
                .contains("\"amountMinor\":\"12000\"")
                .contains("\"originalActivityId\":\"pe_f09-original\"");
        var searched =
                mvc.perform(
                                get("/api/v1/transactions")
                                        .param("search", "  HARBOR   HEALTH ")
                                        .cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(searched.getStatus()).isEqualTo(200);
        assertThat(searched.getContentAsString()).contains("pe_f09-refund");
        var wildcard =
                mvc.perform(get("/api/v1/transactions").param("search", "%_").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(wildcard.getStatus()).isEqualTo(200);
        assertThat(wildcard.getContentAsString()).contains("\"items\":[]");
        for (String valid :
                List.of(
                        "😀😀",
                        "𐐷𐐷",
                        "e\u0301",
                        "x".repeat(100),
                        "  A   B  ",
                        "\u00a0 A\u00a0\u00a0B \u00a0",
                        "%_\\")) {
            assertThat(
                            mvc.perform(
                                            get("/api/v1/transactions")
                                                    .param("search", valid)
                                                    .cookie(session))
                                    .andReturn()
                                    .getResponse()
                                    .getStatus())
                    .describedAs(valid)
                    .isEqualTo(200);
        }
        for (String invalid : List.of("😀", "x".repeat(101))) {
            assertThat(
                            mvc.perform(
                                            get("/api/v1/transactions")
                                                    .param("search", invalid)
                                                    .cookie(session))
                                    .andReturn()
                                    .getResponse()
                                    .getStatus())
                    .describedAs(invalid)
                    .isEqualTo(400);
        }
        assertThat(
                        mvc.perform(get("/api/v1/transactions?type=BAD").cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        var first =
                mvc.perform(get("/api/v1/transactions?limit=1").cookie(session))
                        .andReturn()
                        .getResponse();
        String cursor = JsonPath.read(first.getContentAsString(), "$.nextCursor");
        assertThat(
                        mvc.perform(
                                        get("/api/v1/transactions?limit=1&cursor=" + cursor)
                                                .cookie(login("fixture-f01")))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            statement.executeUpdate(
                    "UPDATE customers SET customer_revision=customer_revision+1 WHERE id='fixture-f09'");
        }
        try {
            var stale =
                    mvc.perform(
                                    get("/api/v1/transactions?limit=1&cursor=" + cursor)
                                            .cookie(session))
                            .andReturn()
                            .getResponse();
            assertThat(stale.getStatus()).isEqualTo(409);
            assertThat(stale.getContentAsString()).contains("\"code\":\"STALE_CURSOR\"");
            assertThat(
                            mvc.perform(get("/api/v1/transactions?limit=1").cookie(session))
                                    .andReturn()
                                    .getResponse()
                                    .getStatus())
                    .isEqualTo(200);
        } finally {
            try (var admin =
                            DriverManager.getConnection(
                                    db.getJdbcUrl(), db.getUsername(), db.getPassword());
                    var statement = admin.createStatement()) {
                statement.executeUpdate(
                        "UPDATE customers SET customer_revision=customer_revision-1 WHERE id='fixture-f09'");
            }
        }
        String originalEpoch = JsonPath.read(first.getContentAsString(), "$.dataset.instanceEpoch");
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement =
                        admin.prepareStatement(
                                "UPDATE dataset_instance SET instance_epoch=? WHERE singleton=true")) {
            statement.setObject(1, UUID.randomUUID());
            statement.executeUpdate();
        }
        try {
            var stale =
                    mvc.perform(
                                    get("/api/v1/transactions?limit=1&cursor=" + cursor)
                                            .cookie(session))
                            .andReturn()
                            .getResponse();
            assertThat(stale.getStatus()).isEqualTo(409);
            assertThat(stale.getContentAsString()).contains("\"code\":\"STALE_CURSOR\"");
        } finally {
            try (var admin =
                            DriverManager.getConnection(
                                    db.getJdbcUrl(), db.getUsername(), db.getPassword());
                    var statement =
                            admin.prepareStatement(
                                    "UPDATE dataset_instance SET instance_epoch=? WHERE singleton=true")) {
                statement.setObject(1, UUID.fromString(originalEpoch));
                statement.executeUpdate();
            }
        }
    }

    @Test
    void cursorRejectsNoncanonicalAndModifiedSignatures() throws Exception {
        Cookie session = login("fixture-f09");
        String path = "/api/v1/transactions?limit=1";
        var first = mvc.perform(get(path).cookie(session)).andReturn().getResponse();
        String cursor = JsonPath.read(first.getContentAsString(), "$.nextCursor");
        assertThat(cursor).isNotBlank();
        assertThat(
                        mvc.perform(get(path + "&cursor=" + cursor).cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(200);
        String[] parts = cursor.split("\\.");
        String alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
        String signature = parts[1];
        int last = alphabet.indexOf(signature.charAt(signature.length() - 1));
        assertThat(last % 4).isZero(); // SHA-256 leaves two unused bits in 43 Base64URL characters.
        String prefix = signature.substring(0, signature.length() - 1);
        String noncanonical = parts[0] + "." + prefix + alphabet.charAt(last + 1);
        assertThat(Base64.getUrlDecoder().decode(noncanonical.split("\\.")[1]))
                .isEqualTo(Base64.getUrlDecoder().decode(signature));
        String significantBit = parts[0] + "." + prefix + alphabet.charAt(last ^ 4);
        byte[] differentKey = HexFormat.of().parseHex(TEST_CURSOR_SECRET);
        differentKey[0] ^= 1;
        Mac otherMac = Mac.getInstance("HmacSHA256");
        otherMac.init(new SecretKeySpec(differentKey, "HmacSHA256"));
        String otherSignature =
                Base64.getUrlEncoder()
                        .withoutPadding()
                        .encodeToString(
                                otherMac.doFinal(parts[0].getBytes(StandardCharsets.UTF_8)));
        String paddedBody =
                new String(Base64.getUrlDecoder().decode(parts[0]), StandardCharsets.UTF_8) + " ";
        while (paddedBody.getBytes(StandardCharsets.UTF_8).length % 3 == 0) paddedBody += " ";
        String canonicalBody =
                Base64.getUrlEncoder()
                        .withoutPadding()
                        .encodeToString(paddedBody.getBytes(StandardCharsets.UTF_8));
        int bodyLast = alphabet.indexOf(canonicalBody.charAt(canonicalBody.length() - 1));
        String noncanonicalBody =
                canonicalBody.substring(0, canonicalBody.length() - 1)
                        + alphabet.charAt(bodyLast + 1);
        Mac originalMac = Mac.getInstance("HmacSHA256");
        originalMac.init(
                new SecretKeySpec(HexFormat.of().parseHex(TEST_CURSOR_SECRET), "HmacSHA256"));
        String bodySignature =
                Base64.getUrlEncoder()
                        .withoutPadding()
                        .encodeToString(
                                originalMac.doFinal(
                                        noncanonicalBody.getBytes(StandardCharsets.UTF_8)));
        for (String changed :
                List.of(
                        noncanonical,
                        significantBit,
                        parts[0] + ".!",
                        parts[0] + "." + otherSignature,
                        noncanonicalBody + "." + bodySignature)) {
            var rejected =
                    mvc.perform(get(path).param("cursor", changed).cookie(session))
                            .andReturn()
                            .getResponse();
            assertThat(rejected.getStatus()).describedAs(changed).isEqualTo(400);
            assertThat(rejected.getContentAsString()).contains("\"code\":\"INVALID_REQUEST\"");
        }
    }

    @Test
    void postingReplacesProvisionalActivityAndKeepsOriginalAmount() throws Exception {
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var sql = admin.createStatement()) {
            sql.executeUpdate(
                    "INSERT INTO customers(id,display_name,login_id,status,primary_persona) VALUES('history-customer','History Customer','history-customer','ACTIVE','SALARIED')");
            sql.executeUpdate(
                    "INSERT INTO credentials(customer_id,password_hash) SELECT 'history-customer',password_hash FROM credentials WHERE customer_id='fixture-f09'");
            sql.executeUpdate(
                    "INSERT INTO accounts(id,customer_id,account_kind,alias,masked_suffix,opened_on,status) VALUES('history-account','history-customer','EVERYDAY','Everyday','9876','2025-01-01','OPEN')");
            sql.executeUpdate(
                    "INSERT INTO authorizations(id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,raw_description,source_event_id) VALUES ('history-auth','history-account',25000,'2026-10-30 09:00+02','PENDING','Sample shop','history:history-auth'),('history-pending','history-account',10000,'2026-10-28 09:00+02','PENDING','Other shop','history:history-pending'),('history-cancelled','history-account',5000,'2026-10-28 09:00+02','CANCELLED','Cancelled shop','history:history-cancelled')");
        }
        Cookie session = login("history-customer");
        var before =
                mvc.perform(get("/api/v1/transactions?limit=1").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(before.getStatus()).isEqualTo(200);
        assertThat(before.getContentAsString()).contains("au_history-auth");
        String cursor = JsonPath.read(before.getContentAsString(), "$.nextCursor");
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var sql = admin.createStatement()) {
            admin.setAutoCommit(false);
            sql.executeUpdate(
                    "UPDATE authorizations SET lifecycle_status='POSTED' WHERE id='history-auth'");
            sql.executeUpdate(
                    "INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,category_code,classification_provenance,authorization_id) VALUES('history-post','history-account','history:history-post',-24000,'ZAR','CARD_PURCHASE','SPEND','2026-10-31 09:00+02','2026-10-30 09:00+02','Sample shop','UNCATEGORIZED','UNCATEGORIZED','history-auth')");
            sql.executeUpdate(
                    "UPDATE customers SET customer_revision=customer_revision+1 WHERE id='history-customer'");
            admin.commit();
        }
        var stale =
                mvc.perform(get("/api/v1/transactions?limit=1&cursor=" + cursor).cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(stale.getStatus()).isEqualTo(409);
        var after =
                mvc.perform(get("/api/v1/transactions").cookie(session)).andReturn().getResponse();
        assertThat(after.getStatus()).isEqualTo(200);
        List<String> ids = JsonPath.read(after.getContentAsString(), "$.items[*].id");
        assertThat(ids)
                .containsExactly("pe_history-post", "au_history-pending", "au_history-cancelled");
        var traversed = new java.util.ArrayList<String>();
        String next = null;
        do {
            String path = "/api/v1/transactions?limit=1" + (next == null ? "" : "&cursor=" + next);
            var response = mvc.perform(get(path).cookie(session)).andReturn().getResponse();
            assertThat(response.getStatus()).isEqualTo(200);
            traversed.addAll(JsonPath.read(response.getContentAsString(), "$.items[*].id"));
            next = JsonPath.read(response.getContentAsString(), "$.nextCursor");
        } while (next != null);
        assertThat(traversed).containsExactlyElementsOf(ids);
        assertThat(after.getContentAsString())
                .contains("\"authorizedAmountMinor\":\"25000\"")
                .contains("\"amountMinor\":\"-24000\"");
        var posted =
                mvc.perform(get("/api/v1/transactions/pe_history-post").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(posted.getContentAsString())
                .contains("\"authorizationActivityId\":\"au_history-auth\"");
        assertThat(
                        mvc.perform(get("/api/v1/transactions/au_history-auth").cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(404);
        var cancelled =
                mvc.perform(get("/api/v1/transactions/au_history-cancelled").cookie(session))
                        .andReturn()
                        .getResponse();
        assertThat(cancelled.getContentAsString())
                .contains("\"status\":\"CANCELLED\"")
                .contains("\"amountMinor\":null");
    }

    @Test
    void logoutRevokesDatabaseSessionAndStaleCsrfIsDenied() throws Exception {
        Cookie session = login("fixture-f09");
        var csrf = mvc.perform(get("/api/v1/auth/csrf").cookie(session)).andReturn().getResponse();
        Cookie csrfCookie = csrf.getCookie("XSRF-TOKEN");
        String valid = token(csrf.getContentAsString());
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/logout")
                                                .cookie(session, csrfCookie)
                                                .header("X-XSRF-TOKEN", "forged"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(403);
        var logout =
                mvc.perform(
                                post("/api/v1/auth/logout")
                                        .cookie(session, csrfCookie)
                                        .header("X-XSRF-TOKEN", valid))
                        .andReturn()
                        .getResponse();
        assertThat(logout.getStatus()).isEqualTo(204);
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(session))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(401);
        var repeatCsrf = mvc.perform(get("/api/v1/auth/csrf")).andReturn().getResponse();
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/logout")
                                                .cookie(repeatCsrf.getCookie("XSRF-TOKEN"))
                                                .header(
                                                        "X-XSRF-TOKEN",
                                                        token(repeatCsrf.getContentAsString())))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(204);
        Cookie renewed = logout.getCookie("XSRF-TOKEN");
        assertThat(renewed).isNotNull();
        assertThat(
                        mvc.perform(
                                        post("/api/v1/auth/login")
                                                .contentType("application/json")
                                                .cookie(renewed)
                                                .header("X-XSRF-TOKEN", valid)
                                                .content(
                                                        "{\"loginId\":\"fixture-f09\",\"password\":\"fixture-only-password\"}"))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(403);
    }

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void databaseSessionEnforcesIdleAndAbsoluteExpiry() throws Exception {
        Cookie activeCookie = login("fixture-f09");
        String activeId = new String(Base64.getDecoder().decode(activeCookie.getValue()));
        Session active = sessions.findById(activeId);
        active.setLastAccessedTime(Instant.now().minus(Duration.ofMinutes(5)));
        ((SessionRepository) sessions).save(active);
        assertThat(
                        mvc.perform(get("/api/v1/auth/session").cookie(activeCookie))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(200);
        Session refreshed = sessions.findById(activeId);
        assertThat(refreshed.getLastAccessedTime())
                .isAfter(Instant.now().minus(Duration.ofMinutes(1)));

        Cookie idleCookie = login("fixture-f01");
        String idleId = new String(Base64.getDecoder().decode(idleCookie.getValue()));
        Session idle = sessions.findById(idleId);
        assertThat(idle).isNotNull();
        idle.setLastAccessedTime(Instant.now().minus(Duration.ofMinutes(16)));
        ((SessionRepository) sessions).save(idle);
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(idleCookie))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(401);

        Cookie absoluteCookie = login("fixture-f03");
        String absoluteId = new String(Base64.getDecoder().decode(absoluteCookie.getValue()));
        Session absolute = sessions.findById(absoluteId);
        assertThat(absolute).isNotNull();
        absolute.setAttribute(
                "authenticatedAt", System.currentTimeMillis() - Duration.ofHours(9).toMillis());
        ((SessionRepository) sessions).save(absolute);
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(absoluteCookie))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(401);
        assertThat(sessions.findById(absoluteId)).isNull();
    }

    @Test
    void authenticationRotatesExistingSessionIdentity() throws Exception {
        Cookie first = login("fixture-f04");
        var csrf = mvc.perform(get("/api/v1/auth/csrf").cookie(first)).andReturn().getResponse();
        var second =
                mvc.perform(
                                post("/api/v1/auth/login")
                                        .contentType("application/json")
                                        .cookie(first, csrf.getCookie("XSRF-TOKEN"))
                                        .header("X-XSRF-TOKEN", token(csrf.getContentAsString()))
                                        .content(
                                                "{\"loginId\":\"fixture-f04\",\"password\":\"fixture-only-password\"}"))
                        .andReturn()
                        .getResponse();
        assertThat(second.getStatus()).isEqualTo(200);
        Cookie rotated =
                Arrays.stream(second.getCookies())
                        .filter(c -> c.getName().equals("SESSION"))
                        .findFirst()
                        .orElseThrow();
        assertThat(rotated.getValue()).isNotEqualTo(first.getValue());
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(first))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(401);
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(rotated))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(200);
    }

    @Test
    void restrictedRoleCannotWriteFinancialTablesAndFixtureReplayIsNoop() throws Exception {
        try (var connection =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), "customer_insights_api", "testapi");
                var statement = connection.createStatement()) {
            assertThatThrownBy(() ->
                            statement.executeUpdate(
                                    "UPDATE posted_entries SET amount_minor=1 WHERE id='f09-fee'"))
                    .isInstanceOf(SQLException.class);
            assertThatThrownBy(() ->
                            statement.executeUpdate(
                                    "INSERT INTO customers(id,display_name,login_id,status,primary_persona) VALUES('bad','bad','bad','ACTIVE','STUDENT')"))
                    .isInstanceOf(SQLException.class);
            assertThatThrownBy(() ->
                            statement.executeUpdate("CREATE TABLE forbidden_api_ddl(id integer)"))
                    .isInstanceOf(SQLException.class);
        }
        check(
                db.execInContainer(
                        "sh",
                        "-c",
                        "PGPASSWORD=test psql -U customer_insights -d customer_insights -v ON_ERROR_STOP=1 -f /tmp/test-fixture.sql"));
        try (var connection =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), "customer_insights_api", "testapi");
                var statement = connection.createStatement();
                var rows =
                        statement.executeQuery(
                                "SELECT count(*) FROM posted_entries WHERE account_id='f09-everyday'")) {
            rows.next();
            assertThat(rows.getInt(1)).isEqualTo(12);
        }
    }

    @Test
    void provisioningRemovesPriorFinancialWriteGrants() throws Exception {
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            statement.execute(
                    "GRANT INSERT, UPDATE, DELETE ON posted_entries, accounts TO customer_insights_api");
        }
        check(
                db.execInContainer(
                        "sh",
                        "-c",
                        "DB_HOST=localhost API_DB_PASSWORD=testapi PGPASSWORD=test sh /tmp/provision.sh"));
        try (var api =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), "customer_insights_api", "testapi");
                var statement = api.createStatement()) {
            assertThatThrownBy(() ->
                            statement.executeUpdate(
                                    "UPDATE posted_entries SET amount_minor=1 WHERE id='f09-fee'"))
                    .isInstanceOf(SQLException.class);
            assertThatThrownBy(() ->
                            statement.executeUpdate(
                                    "INSERT INTO accounts(id,customer_id,account_kind,alias,masked_suffix,opened_on,status) VALUES('bad','fixture-f09','EVERYDAY','bad','0000','2026-01-01','OPEN')"))
                    .isInstanceOf(SQLException.class);
            try (var rows = statement.executeQuery("SELECT count(*) FROM posted_entries")) {
                assertThat(rows.next()).isTrue();
            }
            try (var rows =
                    statement.executeQuery(
                            "SELECT has_table_privilege(current_user,'spring_session','INSERT')")) {
                assertThat(rows.next()).isTrue();
                assertThat(rows.getBoolean(1)).isTrue();
            }
        }
    }

    @Test
    void provisioningStaysInDedicatedDatabaseAndIsIdempotent() throws Exception {
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            statement.execute("CREATE ROLE unrelated_provision_test LOGIN PASSWORD 'test-only'");
            statement.execute(
                    "CREATE DATABASE unrelated_provision_test OWNER unrelated_provision_test");
            statement.execute("CREATE SEQUENCE provision_test_sequence");
            statement.execute(
                    "GRANT USAGE, UPDATE ON SEQUENCE provision_test_sequence TO customer_insights_api");
            statement.execute("GRANT INSERT ON posted_entries TO customer_insights_api");
            try (var rows =
                    statement.executeQuery(
                            "SELECT has_sequence_privilege('customer_insights_api','provision_test_sequence','USAGE'), has_table_privilege('customer_insights_api','posted_entries','INSERT')")) {
                assertThat(rows.next()).isTrue();
                assertThat(rows.getBoolean(1)).isTrue();
                assertThat(rows.getBoolean(2)).isTrue();
            }
        }
        String unrelatedUrl =
                "jdbc:postgresql://"
                        + db.getHost()
                        + ":"
                        + db.getMappedPort(5432)
                        + "/unrelated_provision_test";
        try (var unrelated =
                        DriverManager.getConnection(
                                unrelatedUrl, "unrelated_provision_test", "test-only");
                var statement = unrelated.createStatement()) {
            statement.execute("CREATE TABLE unrelated_data(id integer PRIMARY KEY)");
            statement.execute("INSERT INTO unrelated_data VALUES(7)");
        }
        try {
            check(
                    db.execInContainer(
                            "sh",
                            "-c",
                            "DB_HOST=localhost API_DB_PASSWORD=testapi PGPASSWORD=test sh /tmp/provision.sh"));
            check(
                    db.execInContainer(
                            "sh",
                            "-c",
                            "DB_HOST=localhost API_DB_PASSWORD=testapi PGPASSWORD=test sh /tmp/provision.sh"));
            try (var admin =
                            DriverManager.getConnection(
                                    db.getJdbcUrl(), db.getUsername(), db.getPassword());
                    var statement = admin.createStatement()) {
                try (var rows =
                        statement.executeQuery(
                                "SELECT has_database_privilege('unrelated_provision_test','unrelated_provision_test','TEMP')")) {
                    assertThat(rows.next()).isTrue();
                    assertThat(rows.getBoolean(1)).isTrue();
                }
                try (var rows =
                        statement.executeQuery(
                                "SELECT has_sequence_privilege('customer_insights_api','provision_test_sequence','USAGE'), has_table_privilege('customer_insights_api','posted_entries','INSERT')")) {
                    assertThat(rows.next()).isTrue();
                    assertThat(rows.getBoolean(1)).isFalse();
                    assertThat(rows.getBoolean(2)).isFalse();
                }
                try (var rows =
                        statement.executeQuery(
                                "SELECT has_database_privilege('customer_insights_api','customer_insights','TEMP'), has_schema_privilege('customer_insights_api','public','CREATE')")) {
                    assertThat(rows.next()).isTrue();
                    assertThat(rows.getBoolean(1)).isFalse();
                    assertThat(rows.getBoolean(2)).isFalse();
                }
                statement.execute(
                        "ALTER DATABASE customer_insights OWNER TO unrelated_provision_test");
                var rejected =
                        db.execInContainer(
                                "sh",
                                "-c",
                                "DB_HOST=localhost API_DB_PASSWORD=testapi PGPASSWORD=test sh /tmp/provision.sh");
                assertThat(rejected.getExitCode()).isNotZero();
                assertThat(rejected.getStderr() + rejected.getStdout())
                        .contains("Provisioning requires the dedicated customer_insights database");
                statement.execute("ALTER DATABASE customer_insights OWNER TO customer_insights");
            }
            try (var api =
                            DriverManager.getConnection(
                                    db.getJdbcUrl(), "customer_insights_api", "testapi");
                    var statement = api.createStatement()) {
                assertThatThrownBy(() ->
                                statement.execute(
                                        "CREATE TABLE forbidden_provision_test(id integer)"))
                        .isInstanceOf(SQLException.class);
                assertThatThrownBy(() ->
                                statement.execute(
                                        "CREATE TEMP TABLE forbidden_provision_temp(id integer)"))
                        .isInstanceOf(SQLException.class);
                statement.execute(
                        "INSERT INTO login_attempts(login_key,attempts,window_started_at) VALUES('provision-test',0,now()) ON CONFLICT DO NOTHING");
                statement.execute("DELETE FROM login_attempts WHERE login_key='provision-test'");
            }
            try (var admin =
                            DriverManager.getConnection(
                                    db.getJdbcUrl(), db.getUsername(), db.getPassword());
                    var statement = admin.createStatement()) {
                statement.execute("CREATE TABLE provision_migration_test(id integer)");
                statement.execute("DROP TABLE provision_migration_test");
            }
            try (var unrelated =
                            DriverManager.getConnection(
                                    unrelatedUrl, "unrelated_provision_test", "test-only");
                    var statement = unrelated.createStatement();
                    var rows = statement.executeQuery("SELECT id FROM unrelated_data")) {
                assertThat(rows.next()).isTrue();
                assertThat(rows.getInt(1)).isEqualTo(7);
            }
        } finally {
            try (var admin =
                            DriverManager.getConnection(
                                    db.getJdbcUrl(), db.getUsername(), db.getPassword());
                    var statement = admin.createStatement()) {
                statement.execute("ALTER DATABASE customer_insights OWNER TO customer_insights");
                statement.execute("DROP SEQUENCE IF EXISTS provision_test_sequence");
                statement.execute("DROP DATABASE IF EXISTS unrelated_provision_test");
                statement.execute("DROP ROLE IF EXISTS unrelated_provision_test");
            }
        }
    }

    @Test
    void transferCorrectionsRequireTheOriginalPairAndCannotBeRepeated() throws Exception {
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            admin.setAutoCommit(false);
            statement.executeUpdate(
                    "INSERT INTO transfer_groups(id,customer_id,kind) VALUES('test-reversal','fixture-f01','REVERSAL')");
            statement.executeUpdate(
                    """
                    INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,classification_provenance,original_entry_id,transfer_group_id) VALUES
                    ('test-reverse-in','f01-everyday','test:reverse:in',200000,'ZAR','OWN_TRANSFER_REVERSAL_IN','INTERNAL','2026-10-06 09:00+02','2026-10-06 09:00+02','Reversal','NOT_APPLICABLE','f01-out','test-reversal'),
                    ('test-reverse-out','f01-savings','test:reverse:out',-200000,'ZAR','OWN_TRANSFER_REVERSAL_OUT','INTERNAL','2026-10-06 09:00+02','2026-10-06 09:00+02','Reversal','NOT_APPLICABLE','f01-in','test-reversal')
                    """);
            statement.execute("SET CONSTRAINTS ALL IMMEDIATE");
            assertThatThrownBy(() ->
                            statement.executeUpdate(
                                    """
                                    INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,classification_provenance,original_entry_id,transfer_group_id) VALUES
                                    ('test-duplicate','f01-everyday','test:duplicate',200000,'ZAR','OWN_TRANSFER_REVERSAL_IN','INTERNAL','2026-10-07 09:00+02','2026-10-07 09:00+02','Duplicate','NOT_APPLICABLE','f01-out','test-reversal')
                                    """))
                    .isInstanceOf(SQLException.class);
            admin.rollback();
        }
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            admin.setAutoCommit(false);
            statement.executeUpdate(
                    "INSERT INTO transfer_groups(id,customer_id,kind) VALUES('test-other','fixture-f01','ORIGINAL'),('test-unrelated','fixture-f01','REVERSAL')");
            statement.executeUpdate(
                    """
                    INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,classification_provenance,transfer_group_id) VALUES
                    ('test-other-out','f01-everyday','test:other:out',-200000,'ZAR','OWN_TRANSFER_OUT','INTERNAL','2026-10-06 09:00+02','2026-10-06 09:00+02','Other transfer','NOT_APPLICABLE','test-other'),
                    ('test-other-in','f01-savings','test:other:in',200000,'ZAR','OWN_TRANSFER_IN','INTERNAL','2026-10-06 09:00+02','2026-10-06 09:00+02','Other transfer','NOT_APPLICABLE','test-other')
                    """);
            statement.execute("SET CONSTRAINTS ALL IMMEDIATE");
            statement.execute("SET CONSTRAINTS ALL DEFERRED");
            statement.executeUpdate(
                    """
                    INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,classification_provenance,original_entry_id,transfer_group_id) VALUES
                    ('test-mixed-in','f01-everyday','test:mixed:in',200000,'ZAR','OWN_TRANSFER_REVERSAL_IN','INTERNAL','2026-10-07 09:00+02','2026-10-07 09:00+02','Mixed reversal','NOT_APPLICABLE','f01-out','test-unrelated'),
                    ('test-mixed-out','f01-savings','test:mixed:out',-200000,'ZAR','OWN_TRANSFER_REVERSAL_OUT','INTERNAL','2026-10-07 09:00+02','2026-10-07 09:00+02','Mixed reversal','NOT_APPLICABLE','test-other-in','test-unrelated')
                    """);
            assertThatThrownBy(() -> statement.execute("SET CONSTRAINTS ALL IMMEDIATE"))
                    .isInstanceOf(SQLException.class);
            admin.rollback();
        }
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement()) {
            admin.setAutoCommit(false);
            statement.executeUpdate(
                    """
                    INSERT INTO posted_entries(id,account_id,source_event_id,amount_minor,currency,transaction_type,effect_group,posted_at,occurred_at,raw_description,category_code,classification_provenance,original_entry_id) VALUES
                    ('test-cross-account-refund','f01-savings','test:cross-account-refund',1000,'ZAR','SPEND_REFUND','SPEND','2026-10-07 09:00+02','2026-10-07 09:00+02','Refund','GROCERIES','OBLIGATION','f01-grocery')
                    """);
            statement.execute("SET CONSTRAINTS ALL IMMEDIATE");
            admin.rollback();
        }
        try (var admin =
                        DriverManager.getConnection(
                                db.getJdbcUrl(), db.getUsername(), db.getPassword());
                var statement = admin.createStatement();
                var rows =
                        statement.executeQuery(
                                "SELECT count(*) FROM posted_entries WHERE source_event_id LIKE 'test:%'")) {
            rows.next();
            assertThat(rows.getInt(1)).isZero();
        }
    }

    @Test
    void oneAndBothAccountTransfersAndRefundOnlyPeriod() throws Exception {
        Cookie f01 = login("fixture-f01");
        var one =
                mvc.perform(get("/api/v1/dashboard?accountIds=f01-everyday").cookie(f01))
                        .andReturn()
                        .getResponse();
        assertThat(one.getStatus()).isEqualTo(200);
        assertThat(one.getContentAsString())
                .contains("\"netSpendingMinor\":\"85000\"")
                .contains("\"ownAccountFlowMinor\":\"-200000\"")
                .contains("\"netMovementMinor\":\"1715000\"");
        var both = mvc.perform(get("/api/v1/dashboard").cookie(f01)).andReturn().getResponse();
        assertThat(both.getContentAsString())
                .contains("\"ownAccountFlowMinor\":\"0\"")
                .contains("\"netMovementMinor\":\"1915000\"");
        Cookie f03 = login("fixture-f03");
        var refund = mvc.perform(get("/api/v1/dashboard").cookie(f03)).andReturn().getResponse();
        assertThat(refund.getContentAsString())
                .contains("\"netSpendingMinor\":\"-15000\"")
                .contains("\"netMovementMinor\":\"15000\"");
        List<Map<String, String>> refundCategories =
                JsonPath.read(refund.getContentAsString(), "$.categories");
        assertThat(
                        refundCategories.stream()
                                .collect(
                                        Collectors.toMap(
                                                item -> item.get("categoryCode"),
                                                item -> item.get("netSpendingMinor"))))
                .containsExactlyInAnyOrderEntriesOf(
                        Map.of("HEALTH", "-20000", "BANK_FEES", "5000"));
        assertThat(
                        refundCategories.stream()
                                .map(item -> new BigInteger(item.get("netSpendingMinor")))
                                .reduce(BigInteger.ZERO, BigInteger::add))
                .isEqualTo(new BigInteger("-15000"));
    }

    @Test
    void reportingBoundsEmptyCustomerCrossMonthTransferAndLargeCents() throws Exception {
        Cookie empty = login("fixture-empty");
        assertThat(
                        mvc.perform(get("/api/v1/accounts").cookie(empty))
                                .andReturn()
                                .getResponse()
                                .getContentAsString())
                .contains("\"accounts\":[]");
        assertThat(
                        mvc.perform(get("/api/v1/dashboard").cookie(empty))
                                .andReturn()
                                .getResponse()
                                .getContentAsString())
                .contains("\"netSpendingMinor\":\"0\"");
        Cookie f04 = login("fixture-f04");
        var october =
                mvc.perform(get("/api/v1/dashboard?from=2025-10-01&to=2025-10-31").cookie(f04))
                        .andReturn()
                        .getResponse();
        var november =
                mvc.perform(get("/api/v1/dashboard?from=2025-11-01&to=2025-11-30").cookie(f04))
                        .andReturn()
                        .getResponse();
        var combined =
                mvc.perform(get("/api/v1/dashboard?from=2025-10-31&to=2025-11-01").cookie(f04))
                        .andReturn()
                        .getResponse();
        assertThat(october.getContentAsString()).contains("\"ownAccountFlowMinor\":\"-200000\"");
        assertThat(november.getContentAsString()).contains("\"ownAccountFlowMinor\":\"200000\"");
        assertThat(combined.getContentAsString()).contains("\"ownAccountFlowMinor\":\"0\"");
        assertThat(
                        mvc.perform(
                                        get("/api/v1/dashboard?from=2026-02-30&to=2026-10-31")
                                                .cookie(f04))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        assertThat(
                        mvc.perform(
                                        get("/api/v1/dashboard?from=2026-10-01&to=2026-11-01")
                                                .cookie(f04))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        assertThat(
                        mvc.perform(
                                        get("/api/v1/dashboard?from=2020-01-01&to=2026-10-31")
                                                .cookie(f04))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        assertThat(
                        mvc.perform(get("/api/v1/dashboard?sort=amount").cookie(f04))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        assertThat(
                        mvc.perform(get("/api/v1/dashboard?accountIds=").cookie(f04))
                                .andReturn()
                                .getResponse()
                                .getStatus())
                .isEqualTo(400);
        Cookie large = login("fixture-large");
        assertThat(
                        mvc.perform(get("/api/v1/dashboard").cookie(large))
                                .andReturn()
                                .getResponse()
                                .getContentAsString())
                .contains("\"incomeMinor\":\"9007199254740993\"");
    }

    private Cookie login(String login) throws Exception {
        var csrf = mvc.perform(get("/api/v1/auth/csrf")).andReturn().getResponse();
        var response =
                mvc.perform(
                                post("/api/v1/auth/login")
                                        .contentType("application/json")
                                        .cookie(csrf.getCookie("XSRF-TOKEN"))
                                        .header("X-XSRF-TOKEN", token(csrf.getContentAsString()))
                                        .content(
                                                "{\"loginId\":\""
                                                        + login
                                                        + "\",\"password\":\"fixture-only-password\"}"))
                        .andReturn()
                        .getResponse();
        assertThat(response.getStatus()).describedAs(response.getContentAsString()).isEqualTo(200);
        return Arrays.stream(response.getCookies())
                .filter(c -> c.getName().equals("SESSION"))
                .findFirst()
                .orElseThrow();
    }

    private static String token(String json) {
        return json.replaceAll(".*\"token\":\"([^\"]+)\".*", "$1");
    }
}
