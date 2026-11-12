package za.co.customerinsights.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.CsrfTokenRepository;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder passwords;
    private final CsrfTokenRepository csrfTokens;
    private final HttpSessionSecurityContextRepository contexts;
    private final TransactionTemplate transactions;
    private final String unknownHash;

    public AuthController(JdbcTemplate jdbc, PasswordEncoder passwords,
                          CsrfTokenRepository csrfTokens, HttpSessionSecurityContextRepository contexts,
                          TransactionTemplate transactions) {
        this.jdbc = jdbc;
        this.passwords = passwords;
        this.csrfTokens = csrfTokens;
        this.contexts = contexts;
        this.transactions = transactions;
        this.unknownHash = passwords.encode("unavailable synthetic customer");
    }

    public record LoginRequest(String loginId, String password) {
        @Override public String toString() { return "LoginRequest[redacted]"; }
    }
    public record SessionResponse(String customerId, String displayName, long expiresAtEpochMillis) {}

    @GetMapping("/csrf")
    public CsrfResponse csrf(HttpServletRequest request, HttpServletResponse response) {
        CsrfToken token = csrfTokens.loadToken(request);
        if (token == null) {
            ((CsrfToken) request.getAttribute(CsrfToken.class.getName())).getToken();
            token = (CsrfToken) request.getAttribute("rawCsrfToken");
        } else {
            token = csrfTokens.generateToken(request);
            csrfTokens.saveToken(token, request, response);
        }
        response.setHeader("Cache-Control", "no-store");
        return new CsrfResponse(token.getToken());
    }

    public record CsrfResponse(String token) {
        @Override public String toString() { return "CsrfResponse[redacted]"; }
    }

    @PostMapping(value="/login", consumes=MediaType.APPLICATION_JSON_VALUE)
    public SessionResponse login(@RequestBody LoginRequest input, HttpServletRequest request, HttpServletResponse response) {
        if (input == null || input.loginId() == null || input.password() == null
            || input.loginId().isBlank() || input.loginId().length()>100 || input.password().length()>1024) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid login request");
        }
        String login = input.loginId().trim().toLowerCase(Locale.ROOT);
        LoginResult result = transactions.execute(status -> verify(login, input.password()));
        if (result.customer() == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid credentials");
        }
        Customer customer = result.customer();
        if (request.getSession(false) != null) request.changeSessionId();
        var session = request.getSession(true);
        session.setMaxInactiveInterval(15*60);
        long authenticatedAt = System.currentTimeMillis();
        session.setAttribute(SecurityConfiguration.AUTHENTICATED_AT, authenticatedAt);
        var authentication = UsernamePasswordAuthenticationToken.authenticated(customer.id(), null, List.of());
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(authentication);
        SecurityContextHolder.setContext(context);
        contexts.saveContext(context, request, response);
        renewCsrf(request, response);
        response.setHeader("Cache-Control", "no-store");
        return new SessionResponse(customer.id(), customer.displayName(), expiry(authenticatedAt));
    }

    private LoginResult verify(String login, String password) {
        var customers = jdbc.query("SELECT c.id,c.display_name,cr.password_hash FROM customers c JOIN credentials cr ON cr.customer_id=c.id WHERE c.login_id=? AND c.status='ACTIVE'",
            (rs, row) -> new Customer(rs.getString(1), rs.getString(2), rs.getString(3)), login);
        Customer customer = customers.isEmpty() ? null : customers.getFirst();
        if (customer == null) {
            passwords.matches(password, unknownHash);
            return new LoginResult(null);
        }
        jdbc.update("DELETE FROM login_attempts WHERE window_started_at < now()-interval '1 day' AND (blocked_until IS NULL OR blocked_until<now())");
        jdbc.update("INSERT INTO login_attempts(login_key,attempts,window_started_at) VALUES (?,0,now()) ON CONFLICT DO NOTHING", login);
        var attempt = jdbc.queryForMap("SELECT attempts,blocked_until FROM login_attempts WHERE login_key=? FOR UPDATE", login);
        if (attempt.get("blocked_until") instanceof java.sql.Timestamp blocked && blocked.toInstant().isAfter(Instant.now())) {
            passwords.matches(password, unknownHash);
            return new LoginResult(null);
        }
        boolean correct = passwords.matches(password, customer.passwordHash());
        if (!correct) {
            jdbc.update("""
                UPDATE login_attempts SET
                  attempts=CASE WHEN window_started_at<now()-interval '1 hour' THEN 1 ELSE LEAST(attempts+1,5) END,
                  window_started_at=CASE WHEN window_started_at<now()-interval '1 hour' THEN now() ELSE window_started_at END,
                  blocked_until=CASE WHEN window_started_at<now()-interval '1 hour' THEN NULL
                                     WHEN blocked_until IS NULL AND attempts>=4 THEN now()+interval '15 minutes'
                                     ELSE blocked_until END
                WHERE login_key=?
                """, login);
            return new LoginResult(null);
        }
        jdbc.update("DELETE FROM login_attempts WHERE login_key=?", login);
        return new LoginResult(customer);
    }

    @GetMapping("/session")
    public SessionResponse session(org.springframework.security.core.Authentication authentication, HttpServletRequest request,
                                   HttpServletResponse response) {
        var names = jdbc.query("SELECT display_name FROM customers WHERE id=? AND status='ACTIVE'", (rs, row) -> rs.getString(1), authentication.getName());
        if (names.isEmpty()) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Session expired");
        long started = (long) request.getSession(false).getAttribute(SecurityConfiguration.AUTHENTICATED_AT);
        response.setHeader("Cache-Control", "no-store");
        return new SessionResponse(authentication.getName(), names.getFirst(), expiry(started));
    }

    @PostMapping("/logout")
    public void logout(HttpServletRequest request, HttpServletResponse response) {
        if (request.getSession(false) != null) request.getSession(false).invalidate();
        SecurityContextHolder.clearContext();
        renewCsrf(request, response);
        response.setHeader("Cache-Control", "no-store");
        response.setStatus(204);
    }

    private void renewCsrf(HttpServletRequest request, HttpServletResponse response) {
        csrfTokens.saveToken(null, request, response);
        csrfTokens.saveToken(csrfTokens.generateToken(request), request, response);
    }

    private static long expiry(long authenticatedAt) {
        return Math.min(authenticatedAt + SecurityConfiguration.ABSOLUTE_LIFETIME.toMillis(), System.currentTimeMillis() + 15*60*1000L);
    }

    private record Customer(String id, String displayName, String passwordHash) {}
    private record LoginResult(Customer customer) {}
}
