package za.co.customerinsights.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import java.util.UUID;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 1)
public class SecurityEventFilter extends OncePerRequestFilter {
    private long windowMinute = -1;
    private int emitted;

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String requestId = UUID.randomUUID().toString();
        response.setHeader("X-Request-ID", requestId);
        try {
            chain.doFilter(request, response);
        } finally {
            String category = category(request, response.getStatus());
            if (category != null && allow()) {
                System.out.println(
                        eventJson(category, route(request), response.getStatus(), requestId));
            }
        }
    }

    private synchronized boolean allow() {
        long minute = System.currentTimeMillis() / 60_000;
        if (minute != windowMinute) {
            windowMinute = minute;
            emitted = 0;
        }
        return emitted++ < 120;
    }

    static String category(HttpServletRequest request, int status) {
        if ("session_expired".equals(request.getAttribute("csi.securityEvent")))
            return "session_expired";
        String path = request.getRequestURI();
        if (path.equals("/api/v1/auth/login")) {
            if (status == 200) return "login_success";
            if (status == 401) return "login_failure";
        }
        if (path.equals("/api/v1/auth/logout") && status == 204) return "logout";
        if (path.equals("/api/v1/auth/session") && status == 401) return "session_denied";
        if (status == 400) return "validation_rejected";
        if (status == 401) return "authentication_denied";
        if (status == 403) return "authorization_denied";
        if (status == 429) return "throttled";
        return null;
    }

    static String route(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path.equals("/api/v1/auth/login")) return "auth_login";
        if (path.equals("/api/v1/auth/logout")) return "auth_logout";
        if (path.equals("/api/v1/auth/session")) return "auth_session";
        if (path.equals("/api/v1/dashboard")) return "dashboard";
        if (path.equals("/api/v1/accounts")) return "accounts";
        if (path.equals("/api/v1/transactions") || path.startsWith("/api/v1/transactions/"))
            return "transactions";
        return "other";
    }

    static String eventJson(String category, String route, int status, String requestId) {
        return "{\"timestamp\":\""
                + Instant.now()
                + "\",\"event\":\""
                + category
                + "\",\"route\":\""
                + route
                + "\",\"outcome\":\""
                + (status < 400 ? "success" : "denied")
                + "\",\"status\":"
                + status
                + ",\"requestId\":\""
                + requestId
                + "\"}";
    }
}
