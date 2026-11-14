package za.co.customerinsights.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingResponseWrapper;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class SessionStoreFailureFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        try {
            if (!request.getRequestURI().startsWith("/api/v1/")) {
                chain.doFilter(request, response);
                return;
            }
            var buffered = new ContentCachingResponseWrapper(response);
            chain.doFilter(request, buffered);
            buffered.copyBodyToResponse();
        } catch (ServletException | RuntimeException error) {
            if (!request.getRequestURI().startsWith("/api/v1/")
                    || response.isCommitted()
                    || !DatabaseUnavailable.causedBy(error)) {
                throw error;
            }
            response.reset();
            response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
            response.setContentType("application/problem+json");
            response.setHeader("Cache-Control", "no-store");
            response.getWriter()
                    .write(
                            "{\"type\":\"about:blank\",\"title\":\"Service Unavailable\","
                                    + "\"status\":503,\"detail\":\"The request could not be completed.\","
                                    + "\"code\":\"UNAVAILABLE\",\"requestId\":\""
                                    + UUID.randomUUID()
                                    + "\"}");
        }
    }
}
