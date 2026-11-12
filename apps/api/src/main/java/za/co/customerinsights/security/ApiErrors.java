package za.co.customerinsights.security;

import jakarta.servlet.http.HttpServletResponse;
import java.util.UUID;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;
import za.co.customerinsights.insights.StaleCursorException;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(ResponseStatusException.class)
    ProblemDetail expected(ResponseStatusException error, HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        int status = error.getStatusCode().value();
        String code =
                switch (status) {
                    case 400 -> "INVALID_REQUEST";
                    case 401 -> "INVALID_CREDENTIALS";
                    case 404 -> "NOT_FOUND";
                    case 429 -> "TOO_MANY_REQUESTS";
                    case 503 -> "UNAVAILABLE";
                    default -> "REQUEST_FAILED";
                };
        return problem(status, code);
    }

    @ExceptionHandler(StaleCursorException.class)
    ProblemDetail stale(HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        return problem(409, "STALE_CURSOR");
    }

    @ExceptionHandler(DataAccessException.class)
    ProblemDetail database(HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        return problem(503, "UNAVAILABLE");
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ProblemDetail malformed(HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        return problem(400, "INVALID_REQUEST");
    }

    private static ProblemDetail problem(int status, String code) {
        ProblemDetail detail =
                ProblemDetail.forStatusAndDetail(
                        HttpStatus.valueOf(status), "The request could not be completed.");
        detail.setProperty("code", code);
        detail.setProperty("requestId", UUID.randomUUID().toString());
        return detail;
    }
}
