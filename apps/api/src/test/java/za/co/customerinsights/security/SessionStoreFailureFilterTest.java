package za.co.customerinsights.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.sql.SQLException;
import java.sql.SQLTransientConnectionException;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.CannotGetJdbcConnectionException;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.transaction.UnexpectedRollbackException;

class SessionStoreFailureFilterTest {
    private final SessionStoreFailureFilter filter = new SessionStoreFailureFilter();

    @Test
    void databaseFailureBeforeFinancialResponseReturnsGenericUnavailable() throws Exception {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();

        filter.doFilter(
                request,
                response,
                (ignoredRequest, ignoredResponse) -> {
                    throw new CannotGetJdbcConnectionException("private connection details");
                });

        assertThat(response.getStatus()).isEqualTo(503);
        assertThat(response.getHeader("Cache-Control")).isEqualTo("no-store");
        assertThat(response.getContentType()).startsWith("application/problem+json");
        assertThat(response.getContentAsString())
                .contains("\"code\":\"UNAVAILABLE\"")
                .doesNotContain("private connection details");
    }

    @Test
    void unrelatedFailureIsNotHidden() {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();

        assertThatThrownBy(() ->
                        filter.doFilter(
                                request,
                                response,
                                (ignoredRequest, ignoredResponse) -> {
                                    throw new IllegalStateException("application bug");
                                }))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void sessionTransactionFailureReturnsGenericUnavailable() throws Exception {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();

        filter.doFilter(
                request,
                response,
                (ignoredRequest, ignoredResponse) -> {
                    throw new TransactionSystemException(
                            "private connection details", new SQLException("closed", "08006"));
                });

        assertThat(response.getStatus()).isEqualTo(503);
        assertThat(response.getContentAsString()).doesNotContain("private connection details");
    }

    @Test
    void closedHikariRollbackWithoutSqlStateReturnsGenericUnavailable() throws Exception {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();

        filter.doFilter(
                request,
                response,
                (ignoredRequest, bufferedResponse) -> {
                    bufferedResponse.getWriter().write("private financial response");
                    throw closedHikariRollback();
                });

        assertThat(response.getStatus()).isEqualTo(503);
        assertThat(response.getContentType()).startsWith("application/problem+json");
        assertThat(response.getHeader("Cache-Control")).isEqualTo("no-store");
        assertThat(response.getContentAsString())
                .contains("\"code\":\"UNAVAILABLE\"")
                .doesNotContain(
                        "private financial response", "Connection is closed", "JDBC rollback");
        assertThat(
                        new ApiErrors()
                                .database(closedHikariRollback(), new MockHttpServletResponse())
                                .getStatus())
                .isEqualTo(503);
    }

    @Test
    void arbitraryMissingSqlStateAndOtherRollbackFailuresAreNotOutages() {
        var response = new MockHttpServletResponse();
        var generic =
                new TransactionSystemException(
                        "JDBC rollback failed", new SQLException("Connection is closed"));
        var wrongOperation =
                new TransactionSystemException(
                        "application rollback failed", closedHikariSQLException());

        assertThatThrownBy(() -> new ApiErrors().database(generic, response)).isSameAs(generic);
        assertThatThrownBy(() -> new ApiErrors().database(wrongOperation, response))
                .isSameAs(wrongOperation);
    }

    @Test
    void unrelatedTransactionFailureIsNotMislabelledUnavailable() {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();
        var failure = new UnexpectedRollbackException("logic error");

        assertThatThrownBy(() ->
                        filter.doFilter(
                                request,
                                response,
                                (ignoredRequest, ignoredResponse) -> {
                                    throw failure;
                                }))
                .isSameAs(failure);
        assertThatThrownBy(() -> new ApiErrors().database(failure, response)).isSameAs(failure);
        assertThat(response.isCommitted()).isFalse();
        assertThat(response.getContentAsByteArray()).isEmpty();
    }

    @Test
    void responseBodyIsWithheldUntilSessionCommitCompletes() throws Exception {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();

        filter.doFilter(
                request,
                response,
                (ignoredRequest, bufferedResponse) -> {
                    bufferedResponse.getWriter().write("private financial response");
                    throw new TransactionSystemException(
                            "session save failed", new SQLException("closed", "08006"));
                });

        assertThat(response.getStatus()).isEqualTo(503);
        assertThat(response.getContentAsString()).doesNotContain("private financial response");
    }

    @Test
    void exhaustedPoolConnectionFailureReturnsUnavailable() throws Exception {
        var request = new MockHttpServletRequest("GET", "/api/v1/dashboard");
        var response = new MockHttpServletResponse();
        filter.doFilter(
                request,
                response,
                (ignoredRequest, ignoredResponse) -> {
                    throw new org.springframework.transaction.CannotCreateTransactionException(
                            "pool exhausted", new SQLTransientConnectionException("timed out"));
                });
        assertThat(response.getStatus()).isEqualTo(503);
    }

    private static TransactionSystemException closedHikariRollback() {
        return new TransactionSystemException("JDBC rollback failed", closedHikariSQLException());
    }

    private static SQLException closedHikariSQLException() {
        var failure = new SQLException("Connection is closed");
        failure.setStackTrace(
                new StackTraceElement[] {
                    new StackTraceElement(
                            "com.zaxxer.hikari.pool.ProxyConnection$ClosedConnection",
                            "lambda$getClosedConnection$0",
                            "ProxyConnection.java",
                            559),
                    new StackTraceElement(
                            "com.zaxxer.hikari.pool.ProxyConnection",
                            "rollback",
                            "ProxyConnection.java",
                            386)
                });
        return failure;
    }
}
