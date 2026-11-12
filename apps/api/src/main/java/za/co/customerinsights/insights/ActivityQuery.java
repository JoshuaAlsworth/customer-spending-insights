package za.co.customerinsights.insights;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class ActivityQuery {
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

    private static final ZoneId ZONE = ZoneId.of("Africa/Johannesburg");
    private final JdbcTemplate jdbc;

    public ActivityQuery(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    record Filters(
            String state,
            String type,
            String category,
            String term,
            int size,
            ActivityCursorCodec.Cursor position) {}

    List<Activity> list(ReportingScope.Resolved scope, Filters filters) {
        String state = filters.state();
        String type = filters.type();
        String category = filters.category();
        String term = filters.term();
        int size = filters.size();
        ActivityCursorCodec.Cursor position = filters.position();
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
        return rows;
    }

    List<Activity> detail(String owner, String id) {
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
        return rows;
    }

    private static void addBase(List<Object> args, ReportingScope.Resolved scope) {
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
}
