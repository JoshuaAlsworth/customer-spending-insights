package za.co.customerinsights.insights;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/api/v1/transactions")
public class ActivityController {
    private static final ZoneId ZONE = ZoneId.of("Africa/Johannesburg");
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
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final byte[] secret;

    public ActivityController(
            JdbcTemplate jdbc, ObjectMapper mapper, @Value("${CURSOR_SECRET:}") String secret) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        if (!secret.matches("[0-9a-fA-F]{64}")) {
            throw new IllegalArgumentException("CURSOR_SECRET must be 64 hexadecimal characters");
        }
        this.secret = HexFormat.of().parseHex(secret);
        boolean allSame = true;
        for (byte value : this.secret) allSame &= value == this.secret[0];
        if (allSame) throw new IllegalArgumentException("CURSOR_SECRET cannot repeat one byte");
    }

    public record Activity(
            String recordKind,
            String id,
            String accountId,
            String maskedSuffix,
            String merchantName,
            String description,
            String status,
            String type,
            String authorizedAmountMinor,
            String occurredAt,
            String postedAt,
            String amountMinor,
            String effectGroup,
            String categoryCode,
            String authorizationActivityId,
            String originalActivityId) {}

    public record ActivityPage(
            List<Map<String, Object>> items,
            String nextCursor,
            FinancialController.Dataset dataset) {}

    private record Cursor(
            String binding, String datasetId, String epoch, long revision, String at, String id) {}

    private record Scope(
            String owner,
            List<String> accounts,
            LocalDate from,
            LocalDate to,
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
        Scope scope = scope(authentication.getName(), accountIds, from, to);
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
        String binding =
                digest(
                        String.join(
                                "\u001f",
                                scope.owner(),
                                String.join(",", scope.accounts()),
                                scope.from().toString(),
                                scope.to().toString(),
                                state,
                                value(type),
                                value(category),
                                value(term),
                                Integer.toString(size),
                                "effective-desc-id-desc"));
        Cursor position = cursor == null ? null : decode(cursor);
        if (position != null) {
            if (!position.binding().equals(binding)) {
                bad();
            }
            if (!position.datasetId().equals(scope.dataset().datasetId())
                    || !position.epoch().equals(scope.dataset().instanceEpoch())
                    || position.revision() != scope.dataset().customerRevision()) {
                throw new StaleCursorException();
            }
        }
        if (scope.accounts().isEmpty()
                || category != null && (state.equals("PENDING") || state.equals("CANCELLED"))
                || type != null
                        && !type.equals("CARD_PURCHASE")
                        && (state.equals("PENDING") || state.equals("CANCELLED"))) {
            return new ActivityPage(List.of(), null, scope.dataset());
        }
        String ids = String.join(",", Collections.nCopies(scope.accounts().size(), "?"));
        String posted =
                """
                SELECT 'POSTED_ENTRY' AS kind, 'pe_' || p.id AS activity_id,
                       p.account_id, a.masked_suffix, m.display_name AS merchant_name,
                       p.raw_description AS description, 'POSTED' AS status,
                       p.transaction_type AS type, au.authorized_amount_minor AS authorized_amount,
                       p.occurred_at, p.posted_at, p.amount_minor, p.effect_group,
                       p.category_code, p.authorization_id, p.original_entry_id,
                       p.posted_at AS effective_at
                FROM posted_entries p
                JOIN accounts a ON a.id = p.account_id
                LEFT JOIN merchants m ON m.id = p.merchant_id
                LEFT JOIN authorizations au ON au.id = p.authorization_id
                WHERE a.customer_id = ? AND a.id IN (%s)
                  AND p.posted_at >= ? AND p.posted_at < ?
                """
                                .formatted(ids)
                        + (type == null ? "" : " AND p.transaction_type = ?")
                        + (category == null
                                ? ""
                                : " AND p.effect_group = 'SPEND' AND p.category_code = ?")
                        + searchClause(term, "p.raw_description");
        String auth =
                """
                SELECT 'AUTHORIZATION' AS kind, 'au_' || u.id AS activity_id,
                       u.account_id, a.masked_suffix, m.display_name AS merchant_name,
                       u.raw_description AS description, u.lifecycle_status AS status,
                       'CARD_PURCHASE' AS type, u.authorized_amount_minor AS authorized_amount,
                       u.occurred_at, NULL::timestamptz AS posted_at,
                       NULL::bigint AS amount_minor, NULL::text AS effect_group,
                       NULL::text AS category_code, NULL::text AS authorization_id,
                       NULL::text AS original_entry_id, u.occurred_at AS effective_at
                FROM authorizations u
                JOIN accounts a ON a.id = u.account_id
                LEFT JOIN merchants m ON m.id = u.merchant_id
                WHERE a.customer_id = ? AND a.id IN (%s)
                  AND u.occurred_at >= ? AND u.occurred_at < ?
                  AND u.lifecycle_status IN ('PENDING', 'CANCELLED')
                """
                                .formatted(ids)
                        + searchClause(term, "u.raw_description");
        List<Object> args = new ArrayList<>();
        boolean includePosted = !state.equals("PENDING") && !state.equals("CANCELLED");
        boolean includeAuth =
                !state.equals("POSTED")
                        && category == null
                        && (type == null || type.equals("CARD_PURCHASE"));
        List<String> parts = new ArrayList<>();
        if (includePosted) {
            parts.add(
                    "("
                            + posted
                            + (position == null ? "" : " AND (p.posted_at,'pe_'||p.id)<(?,?)")
                            + " ORDER BY p.posted_at DESC,('pe_'||p.id) DESC LIMIT ?)");
            addBase(args, scope);
            if (type != null) {
                args.add(type);
            }
            if (category != null) {
                args.add(category);
            }
            addSearch(args, term);
            if (position != null) {
                args.add(Timestamp.from(Instant.parse(position.at())));
                args.add(position.id());
            }
            args.add(size + 1);
        }
        if (includeAuth) {
            parts.add(
                    "("
                            + auth
                            + (state.equals("ALL") ? "" : " AND u.lifecycle_status=?")
                            + (position == null ? "" : " AND (u.occurred_at,'au_'||u.id)<(?,?)")
                            + " ORDER BY u.occurred_at DESC,('au_'||u.id) DESC LIMIT ?)");
            addBase(args, scope);
            addSearch(args, term);
            if (!state.equals("ALL")) {
                args.add(state);
            }
            if (position != null) {
                args.add(Timestamp.from(Instant.parse(position.at())));
                args.add(position.id());
            }
            args.add(size + 1);
        }
        String sql =
                "SELECT * FROM ("
                        + String.join(" UNION ALL ", parts)
                        + ") x ORDER BY effective_at DESC,activity_id DESC LIMIT ?";
        args.add(size + 1);
        List<Activity> rows = jdbc.query(sql, (rs, n) -> map(rs), args.toArray());
        boolean more = rows.size() > size;
        List<Activity> page = more ? rows.subList(0, size) : rows;
        String next = null;
        if (more) {
            Activity last = page.getLast();
            next =
                    encode(
                            new Cursor(
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
        String owner = authentication.getName();
        boolean posted = id.startsWith("pe_");
        String sql =
                posted
                        ? """
                        SELECT 'POSTED_ENTRY' AS kind, 'pe_' || p.id AS activity_id,
                               p.account_id, a.masked_suffix, m.display_name AS merchant_name,
                               p.raw_description AS description, 'POSTED' AS status,
                               p.transaction_type AS type, au.authorized_amount_minor AS authorized_amount,
                               p.occurred_at, p.posted_at, p.amount_minor, p.effect_group,
                               p.category_code, p.authorization_id, p.original_entry_id
                        FROM posted_entries p
                        JOIN accounts a ON a.id = p.account_id
                        LEFT JOIN merchants m ON m.id = p.merchant_id
                        LEFT JOIN authorizations au ON au.id = p.authorization_id
                        WHERE a.customer_id = ? AND p.id = ?
                        """
                        : """
                        SELECT 'AUTHORIZATION' AS kind, 'au_' || u.id AS activity_id,
                               u.account_id, a.masked_suffix, m.display_name AS merchant_name,
                               u.raw_description AS description, u.lifecycle_status AS status,
                               'CARD_PURCHASE' AS type, u.authorized_amount_minor AS authorized_amount,
                               u.occurred_at, NULL::timestamptz AS posted_at,
                               NULL::bigint AS amount_minor, NULL::text AS effect_group,
                               NULL::text AS category_code, NULL::text AS authorization_id,
                               NULL::text AS original_entry_id
                        FROM authorizations u
                        JOIN accounts a ON a.id = u.account_id
                        LEFT JOIN merchants m ON m.id = u.merchant_id
                        WHERE a.customer_id = ? AND u.id = ?
                          AND u.lifecycle_status IN ('PENDING', 'CANCELLED')
                        """;
        List<Activity> rows = jdbc.query(sql, (rs, n) -> map(rs), owner, id.substring(3));
        if (rows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Activity unavailable");
        }
        return wire(rows.getFirst());
    }

    private static Map<String, Object> wire(Activity item) {
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

    private Scope scope(String owner, String accountIds, String from, String to) {
        FinancialController.Dataset dataset =
                jdbc.query(
                        """
                        SELECT d.dataset_id, d.instance_epoch, c.customer_revision,
                               d.reference_date
                        FROM dataset_instance d
                        CROSS JOIN customers c
                        WHERE d.singleton = true AND c.id = ?
                        """,
                        rs ->
                                rs.next()
                                        ? new FinancialController.Dataset(
                                                rs.getString(1),
                                                rs.getString(2),
                                                rs.getLong(3),
                                                rs.getDate(4).toLocalDate())
                                        : null,
                        owner);
        if (dataset == null) {
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE, "Dataset unavailable");
        }
        LocalDate end = date(to, dataset.referenceDate());
        LocalDate start = date(from, end.withDayOfMonth(1));
        if (start.isAfter(end)
                || end.isAfter(dataset.referenceDate())
                || start.isBefore(end.minusMonths(36).plusDays(1))
                || ChronoUnit.DAYS.between(start, end) > 1100) {
            bad();
        }
        List<String> selected;
        if (accountIds == null) {
            selected =
                    jdbc.query(
                            "SELECT id FROM accounts WHERE customer_id = ? ORDER BY id",
                            (rs, n) -> rs.getString(1),
                            owner);
        } else {
            selected = List.of(accountIds.split(",", -1));
            if (selected.size() > 4
                    || selected.stream().anyMatch(id -> !id.matches("[A-Za-z0-9_-]{1,64}"))
                    || selected.stream().distinct().count() != selected.size()) {
                bad();
            }
            String placeholders = String.join(",", Collections.nCopies(selected.size(), "?"));
            List<Object> args = new ArrayList<>();
            args.add(owner);
            args.addAll(selected);
            Integer count =
                    jdbc.queryForObject(
                            "SELECT count(*) FROM accounts WHERE customer_id = ? AND id IN (%s)"
                                    .formatted(placeholders),
                            Integer.class,
                            args.toArray());
            if (count == null || count != selected.size()) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Scope unavailable");
            }
        }
        selected = selected.stream().sorted().toList();
        return new Scope(owner, selected, start, end, dataset);
    }

    private static LocalDate date(String value, LocalDate fallback) {
        if (value == null) {
            return fallback;
        }
        try {
            if (!value.matches("\\d{4}-\\d{2}-\\d{2}")) {
                bad();
            }
            return LocalDate.parse(value);
        } catch (RuntimeException ex) {
            bad();
            return fallback;
        }
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

    private static String value(String input) {
        return input == null ? "" : input;
    }

    private static void addBase(List<Object> args, Scope scope) {
        args.add(scope.owner());
        args.addAll(scope.accounts());
        args.add(Timestamp.from(scope.from().atStartOfDay(ZONE).toInstant()));
        args.add(Timestamp.from(scope.to().plusDays(1).atStartOfDay(ZONE).toInstant()));
    }

    private static void addSearch(List<Object> args, String term) {
        if (term != null) {
            String pattern =
                    "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
            args.add(pattern);
            args.add(pattern);
        }
    }

    private static String searchClause(String term, String descriptionColumn) {
        if (term == null) {
            return "";
        }
        return " AND (m.display_name ILIKE ? ESCAPE '\\' OR "
                + descriptionColumn
                + " ILIKE ? ESCAPE '\\')";
    }

    private static Activity map(ResultSet rs) throws SQLException {
        String kind = rs.getString("kind");
        String authorization = rs.getString("authorization_id");
        String original = rs.getString("original_entry_id");
        Long authorized = rs.getObject("authorized_amount", Long.class);
        Long amount = rs.getObject("amount_minor", Long.class);
        Timestamp posted = rs.getTimestamp("posted_at");
        Timestamp occurred = rs.getTimestamp("occurred_at");
        return new Activity(
                kind,
                rs.getString("activity_id"),
                rs.getString("account_id"),
                rs.getString("masked_suffix").trim(),
                rs.getString("merchant_name"),
                rs.getString("description"),
                rs.getString("status"),
                rs.getString("type"),
                authorized == null ? null : authorized.toString(),
                occurred == null ? null : occurred.toInstant().toString(),
                posted == null ? null : posted.toInstant().toString(),
                amount == null ? null : amount.toString(),
                rs.getString("effect_group"),
                rs.getString("category_code"),
                authorization == null ? null : "au_" + authorization,
                original == null ? null : "pe_" + original);
    }

    private String encode(Cursor cursor) {
        try {
            String body =
                    Base64.getUrlEncoder()
                            .withoutPadding()
                            .encodeToString(mapper.writeValueAsBytes(cursor));
            return body + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(mac(body));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private Cursor decode(String encoded) {
        try {
            if (encoded.length() > 2048 || !encoded.matches("[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+")) {
                bad();
            }
            String[] parts = encoded.split("\\.");
            byte[] body = Base64.getUrlDecoder().decode(parts[0]);
            byte[] signature = Base64.getUrlDecoder().decode(parts[1]);
            var canonical = Base64.getUrlEncoder().withoutPadding();
            if (!canonical.encodeToString(body).equals(parts[0])
                    || !canonical.encodeToString(signature).equals(parts[1])
                    || signature.length != 32
                    || !MessageDigest.isEqual(mac(parts[0]), signature)) {
                bad();
            }
            Cursor cursor = mapper.readValue(body, Cursor.class);
            if (cursor.binding() == null
                    || cursor.datasetId() == null
                    || cursor.epoch() == null
                    || cursor.at() == null
                    || cursor.id() == null
                    || !cursor.id().matches("^(au|pe)_[A-Za-z0-9_-]+$")) {
                bad();
            }
            Instant.parse(cursor.at());
            return cursor;
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (Exception ex) {
            bad();
            return null;
        }
    }

    private byte[] mac(String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(secret, "HmacSHA256"));
        return mac.doFinal(body.getBytes(StandardCharsets.UTF_8));
    }

    private static String digest(String body) {
        try {
            return Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(
                            MessageDigest.getInstance("SHA-256")
                                    .digest(body.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }
}
