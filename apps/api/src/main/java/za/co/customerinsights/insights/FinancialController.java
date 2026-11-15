package za.co.customerinsights.insights;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1")
public class FinancialController {
    private final FinancialQuery financialQuery;

    public FinancialController(FinancialQuery financialQuery) {
        this.financialQuery = financialQuery;
    }

    @GetMapping("/accounts")
    public FinancialQuery.AccountsResponse accounts(Authentication authentication) {
        try {
            return financialQuery.accounts(authentication.getName());
        } catch (FinancialQuery.BalanceUnavailableException error) {
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE, "Account balance unavailable");
        }
    }

    @GetMapping("/dashboard")
    public FinancialQuery.Dashboard dashboard(
            Authentication authentication,
            HttpServletRequest request,
            @RequestParam(required = false) String accountIds,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to) {
        if (request.getParameterMap().entrySet().stream()
                .anyMatch(entry ->
                        !Set.of("accountIds", "from", "to").contains(entry.getKey())
                                || entry.getValue().length != 1)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "Unsupported query parameter");
        }
        return financialQuery.dashboard(authentication.getName(), accountIds, from, to);
    }
}
