package za.co.customerinsights.insights;

import jakarta.servlet.http.HttpServletRequest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1/transactions")
public class ActivityController {
    private static final Set<String> TYPES =
            Set.of(
                    "SALARY_CREDIT",
                    "ALLOWANCE_CREDIT",
                    "EXTERNAL_RECEIPT",
                    "INTEREST_CREDIT",
                    "CARD_PURCHASE",
                    "DEBIT_ORDER",
                    "EXTERNAL_PAYMENT",
                    "CASH_WITHDRAWAL",
                    "BANK_FEE",
                    "SPEND_REFUND",
                    "SPEND_REVERSAL",
                    "INCOME_REVERSAL",
                    "OWN_TRANSFER_OUT",
                    "OWN_TRANSFER_IN",
                    "OWN_TRANSFER_REVERSAL_OUT",
                    "OWN_TRANSFER_REVERSAL_IN");
    private static final Set<String> CATEGORIES =
            Set.of(
                    "HOUSING_UTILITIES",
                    "GROCERIES",
                    "TRANSPORT_FUEL",
                    "FOOD_DINING",
                    "SHOPPING",
                    "HEALTH",
                    "SUBSCRIPTIONS_COMMS",
                    "INSURANCE_FIN_SERVICES",
                    "EDUCATION",
                    "ENTERTAINMENT_LEISURE",
                    "CASH_WITHDRAWALS",
                    "MONEY_SENT",
                    "BANK_FEES",
                    "UNCATEGORIZED");
    private final ReportingScope reportingScope;
    private final ActivityQuery activityQuery;
    private final ActivityCursorCodec cursorCodec;

    public ActivityController(
            ReportingScope reportingScope,
            ActivityQuery activityQuery,
            ActivityCursorCodec cursorCodec) {
        this.reportingScope = reportingScope;
        this.activityQuery = activityQuery;
        this.cursorCodec = cursorCodec;
    }

    public record ActivityPage(
            List<Map<String, Object>> items,
            String nextCursor,
            FinancialController.Dataset dataset) {}

    @GetMapping
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ActivityPage list(
            Authentication authentication,
            HttpServletRequest request,
            @RequestParam(required = false) String accountIds,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String search,
            @RequestParam(required = false) String limit,
            @RequestParam(required = false) String cursor) {
        rejectUnexpected(
                request,
                Set.of(
                        "accountIds",
                        "from",
                        "to",
                        "status",
                        "type",
                        "category",
                        "search",
                        "limit",
                        "cursor"));
        ReportingScope.Resolved scope =
                reportingScope
                        .resolve(authentication.getName(), accountIds, from, to, true)
                        .canonical();
        String state = status == null ? "ALL" : status;
        if (!Set.of("ALL", "PENDING", "POSTED", "CANCELLED").contains(state)
                || type != null && !TYPES.contains(type)
                || category != null && !CATEGORIES.contains(category)) {
            bad();
        }
        String term =
                search == null
                        ? null
                        : search.replaceAll("(?U)^\\s+|\\s+$", "").replaceAll("(?U)\\s+", " ");
        if (term != null
                && (term.codePointCount(0, term.length()) < 2
                        || term.codePointCount(0, term.length()) > 100)) {
            bad();
        }
        int size = 25;
        if (limit != null) {
            try {
                size = Integer.parseInt(limit);
            } catch (NumberFormatException ex) {
                bad();
            }
            if (size < 1 || size > 100) {
                bad();
            }
        }
        String binding = cursorCodec.binding(scope, state, type, category, term, size);
        ActivityCursorCodec.Cursor position = cursor == null ? null : cursorCodec.decode(cursor);
        if (position != null) cursorCodec.validate(position, binding, scope.dataset());
        if (scope.accounts().isEmpty()
                || category != null && (state.equals("PENDING") || state.equals("CANCELLED"))
                || type != null
                        && !type.equals("CARD_PURCHASE")
                        && (state.equals("PENDING") || state.equals("CANCELLED"))) {
            return new ActivityPage(List.of(), null, scope.dataset());
        }
        List<ActivityQuery.Activity> rows =
                activityQuery.list(
                        scope,
                        new ActivityQuery.Filters(state, type, category, term, size, position));
        boolean more = rows.size() > size;
        List<ActivityQuery.Activity> page = more ? rows.subList(0, size) : rows;
        String next = null;
        if (more) {
            ActivityQuery.Activity last = page.getLast();
            next =
                    cursorCodec.encode(
                            new ActivityCursorCodec.Cursor(
                                    binding,
                                    scope.dataset().datasetId(),
                                    scope.dataset().instanceEpoch(),
                                    scope.dataset().customerRevision(),
                                    last.postedAt() != null ? last.postedAt() : last.occurredAt(),
                                    last.id()));
        }
        return new ActivityPage(
                page.stream().map(ActivityController::wire).toList(), next, scope.dataset());
    }

    @GetMapping("/{id}")
    @Transactional(readOnly = true)
    public Map<String, Object> detail(Authentication authentication, @PathVariable String id) {
        if (!id.matches("^(au|pe)_[A-Za-z0-9_-]+$")) {
            bad();
        }
        List<ActivityQuery.Activity> rows = activityQuery.detail(authentication.getName(), id);
        if (rows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Activity unavailable");
        }
        return wire(rows.getFirst());
    }

    private static Map<String, Object> wire(ActivityQuery.Activity item) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("recordKind", item.recordKind());
        result.put("id", item.id());
        result.put("accountId", item.accountId());
        result.put("maskedSuffix", item.maskedSuffix());
        result.put("merchantName", item.merchantName());
        result.put("description", item.description());
        result.put("status", item.status());
        result.put("type", item.type());
        result.put("authorizedAmountMinor", item.authorizedAmountMinor());
        result.put("occurredAt", item.occurredAt());
        result.put("postedAt", item.postedAt());
        result.put("amountMinor", item.amountMinor());
        result.put("effectGroup", item.effectGroup());
        result.put("categoryCode", item.categoryCode());
        if (item.recordKind().equals("POSTED_ENTRY")) {
            result.put("authorizationActivityId", item.authorizationActivityId());
            result.put("originalActivityId", item.originalActivityId());
        }
        return result;
    }

    private static void rejectUnexpected(HttpServletRequest request, Set<String> allowed) {
        if (request.getParameterMap().entrySet().stream()
                .anyMatch(e -> !allowed.contains(e.getKey()) || e.getValue().length != 1)) {
            bad();
        }
    }

    private static void bad() {
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid transaction request");
    }
}
