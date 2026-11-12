package za.co.customerinsights.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.CsrfTokenRepository;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.context.SecurityContextHolderFilter;
import org.springframework.web.filter.OncePerRequestFilter;

@Configuration
public class SecurityConfiguration {
    public static final String AUTHENTICATED_AT = "authenticatedAt";
    public static final Duration ABSOLUTE_LIFETIME = Duration.ofHours(8);

    @Bean
    PasswordEncoder passwordEncoder() {
        return new Argon2PasswordEncoder(16, 32, 1, 1 << 16, 3);
    }

    @Bean
    CsrfTokenRepository csrfTokenRepository(@Value("${COOKIE_SECURE:true}") boolean secure) {
        CookieCsrfTokenRepository cookies = CookieCsrfTokenRepository.withHttpOnlyFalse();
        cookies.setCookieCustomizer(builder -> builder.sameSite("Lax").secure(secure));
        return new CsrfTokenRepository() {
            public CsrfToken generateToken(HttpServletRequest request) { return cookies.generateToken(request); }
            public void saveToken(CsrfToken token, HttpServletRequest request, HttpServletResponse response) {
                request.setAttribute("rawCsrfToken", token);
                cookies.saveToken(token, request, response);
            }
            public CsrfToken loadToken(HttpServletRequest request) { return cookies.loadToken(request); }
        };
    }

    @Bean
    HttpSessionSecurityContextRepository securityContextRepository() {
        return new HttpSessionSecurityContextRepository();
    }

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http, CsrfTokenRepository csrfTokens,
                                            HttpSessionSecurityContextRepository contextRepository) throws Exception {
        return http
            .requestCache(cache -> cache.disable())
            .securityContext(context -> context.securityContextRepository(contextRepository))
            .csrf(csrf -> csrf.spa().csrfTokenRepository(csrfTokens))
            .sessionManagement(session -> session.sessionFixation(fixation -> fixation.changeSessionId()))
            .authorizeHttpRequests(requests -> requests
                .requestMatchers("/actuator/health", "/actuator/health/**", "/api/v1/auth/csrf", "/api/v1/auth/login", "/api/v1/auth/logout").permitAll()
                .requestMatchers("/api/v1/auth/session", "/api/v1/accounts", "/api/v1/dashboard").authenticated()
                .anyRequest().denyAll())
            .exceptionHandling(errors -> errors.authenticationEntryPoint((request, response, exception) ->
                writeProblem(response, 401, "UNAUTHENTICATED"))
                .accessDeniedHandler((request, response, exception) -> writeProblem(response, 403, "FORBIDDEN")))
            .addFilterAfter(absoluteLifetimeFilter(), SecurityContextHolderFilter.class)
            .headers(headers -> headers.contentSecurityPolicy(csp -> csp.policyDirectives("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'")))
            .build();
    }

    private OncePerRequestFilter absoluteLifetimeFilter() {
        return new OncePerRequestFilter() {
            @Override
            protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                            jakarta.servlet.FilterChain chain) throws IOException, jakarta.servlet.ServletException {
                Authentication auth = SecurityContextHolder.getContext().getAuthentication();
                if (auth != null && auth.isAuthenticated() && !(auth instanceof AnonymousAuthenticationToken)) {
                    var session = request.getSession(false);
                    Object started = session == null ? null : session.getAttribute(AUTHENTICATED_AT);
                    if (!(started instanceof Long timestamp) || Instant.now().isAfter(Instant.ofEpochMilli(timestamp).plus(ABSOLUTE_LIFETIME))) {
                        if (session != null) session.invalidate();
                        SecurityContextHolder.clearContext();
                        writeProblem(response, 401, "SESSION_EXPIRED");
                        return;
                    }
                }
                chain.doFilter(request, response);
            }
        };
    }

    private static void writeProblem(HttpServletResponse response, int status, String code) throws IOException {
        response.setStatus(status);
        response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
        response.setHeader("Cache-Control", "no-store");
        response.getWriter().write("{\"type\":\"about:blank\",\"title\":\"Request denied\",\"status\":" + status + ",\"code\":\"" + code + "\",\"requestId\":\"" + UUID.randomUUID() + "\"}");
    }
}
