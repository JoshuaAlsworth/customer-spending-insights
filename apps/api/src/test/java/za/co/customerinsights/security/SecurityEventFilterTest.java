package za.co.customerinsights.security;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class SecurityEventFilterTest {
    @Test
    void categoriesAndRoutesAreBoundedAndDoNotIncludeInput() {
        var login = new MockHttpServletRequest("POST", "/api/v1/auth/login");
        assertThat(SecurityEventFilter.category(login, 200)).isEqualTo("login_success");
        assertThat(SecurityEventFilter.category(login, 401)).isEqualTo("login_failure");
        var detail = new MockHttpServletRequest("GET", "/api/v1/transactions/private-secret");
        assertThat(SecurityEventFilter.route(detail)).isEqualTo("transactions");
        assertThat(SecurityEventFilter.category(detail, 403)).isEqualTo("authorization_denied");
        assertThat(SecurityEventFilter.category(detail, 400)).isEqualTo("validation_rejected");
        assertThat(
                        SecurityEventFilter.eventJson(
                                "authorization_denied", "transactions", 403, "request"))
                .contains("\"status\":403")
                .doesNotContain("private-secret", "password", "cookie", "csrf");
    }

    @Test
    void sessionExpiryAndLogoutAreRecorded() {
        var session = new MockHttpServletRequest("GET", "/api/v1/auth/session");
        session.setAttribute("csi.securityEvent", "session_expired");
        assertThat(SecurityEventFilter.category(session, 401)).isEqualTo("session_expired");
        var logout = new MockHttpServletRequest("POST", "/api/v1/auth/logout");
        assertThat(SecurityEventFilter.category(logout, 204)).isEqualTo("logout");
    }
}
