package za.co.customerinsights.insights;

import jakarta.servlet.http.HttpServletRequest;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.sql.Timestamp;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1")
public class FinancialController {
    private static final ZoneId REPORTING_ZONE = ZoneId.of("Africa/Johannesburg");
    private final JdbcTemplate jdbc;
    private final ReportingScope reportingScope;

    public FinancialController(JdbcTemplate jdbc, ReportingScope reportingScope) {
        this.jdbc = jdbc;
        this.reportingScope = reportingScope;
    }

    public record Account(
            String id,
            String alias,
            String maskedSuffix,
            String accountKind,
            String postedBalanceMinor) {}

    public record AccountsResponse(
            List<Account> accounts,
            String combinedPostedBalanceMinor,
            LocalDate balanceAsOfDate,
            String currency,
            Dataset dataset) {}

    public record Scope(LocalDate from, LocalDate to, List<String> accountIds) {}

    public record Summary(
            String incomeMinor,
            String grossSpendingMinor,
            String spendingCreditsMinor,
            String netSpendingMinor,
            String ownAccountFlowMinor,
            String netMovementMinor) {}

    public record Category(String categoryCode, String displayName, String netSpendingMinor) {}

    public record Trend(LocalDate from, LocalDate to, String netSpendingMinor) {}

    public record Dataset(
            String datasetId,
            String instanceEpoch,
            long customerRevision,
            LocalDate referenceDate) {}

    public record Dashboard(
            Scope scope,
            Summary summary,
            List<Category> categories,
            List<Trend> trend,
            Dataset dataset) {}

    @GetMapping("/accounts")
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AccountsResponse accounts(Authentication authentication) {
        Dataset dataset = reportingScope.dataset(authentication.getName());
        var cutoff =
                Timestamp.from(
                        dataset.referenceDate()
                                .plusDays(1)
                                .atStartOfDay(REPORTING_ZONE)
                                .toInstant());
        List<Account> accounts =
                jdbc.query(
                        "SELECT a.id,a.alias,a.masked_suffix,a.account_kind,a.balance_anchor_at,"
                                + "a.opening_balance_minor::numeric + COALESCE(p.total,0) "
                                + "FROM accounts a LEFT JOIN LATERAL ("
                                + "SELECT sum(e.amount_minor::numeric) AS total FROM posted_entries e "
                                + "WHERE e.account_id=a.id AND e.posted_at>=a.balance_anchor_at AND e.posted_at<?"
                                + ") p ON true WHERE a.customer_id=? AND a.status='OPEN' AND a.opened_on<=? ORDER BY a.id",
                        (rs, n) -> {
                            if (rs.getTimestamp(5) == null
                                    || !rs.getTimestamp(5).toInstant().isBefore(cutoff.toInstant())
                                    || rs.getBigDecimal(6) == null) {
                                throw new ResponseStatusException(
                                        HttpStatus.SERVICE_UNAVAILABLE,
                                        "Account balance unavailable");
                            }
                            return new Account(
                                    rs.getString(1),
                                    rs.getString(2),
                                    rs.getString(3).trim(),
                                    rs.getString(4),
                                    exact(rs.getBigDecimal(6)).toString());
                        },
                        cutoff,
                        authentication.getName(),
                        dataset.referenceDate());
        BigInteger combined = BigInteger.ZERO;
        for (Account account : accounts) {
            combined = combined.add(new BigInteger(account.postedBalanceMinor()));
        }
        return new AccountsResponse(
                accounts,
                accounts.isEmpty() ? null : combined.toString(),
                dataset.referenceDate(),
                "ZAR",
                dataset);
    }

    @GetMapping("/dashboard")
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Dashboard dashboard(
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
        ReportingScope.Resolved resolved =
                reportingScope.resolve(authentication.getName(), accountIds, from, to, false);
        String owner = resolved.owner();
        Dataset dataset = resolved.dataset();
        LocalDate start = resolved.from();
        LocalDate end = resolved.to();
        List<String> selected = resolved.accounts();
        if (selected.isEmpty()) return emptyDashboard(start, end, selected, dataset);
        String placeholders = String.join(",", java.util.Collections.nCopies(selected.size(), "?"));
        String predicate =
                " FROM posted_entries p JOIN accounts a ON a.id=p.account_id WHERE a.customer_id=? AND a.id IN ("
                        + placeholders
                        + ") AND p.posted_at>=? AND p.posted_at<?";
        var args = new ArrayList<Object>();
        args.add(owner);
        args.addAll(selected);
        args.add(Timestamp.from(start.atStartOfDay(REPORTING_ZONE).toInstant()));
        args.add(Timestamp.from(end.plusDays(1).atStartOfDay(REPORTING_ZONE).toInstant()));
        BigInteger[] totals =
                jdbc.query(
                        "SELECT "
                                + "COALESCE(sum(CASE WHEN p.effect_group='INCOME' THEN p.amount_minor::numeric ELSE 0 END),0),"
                                + "COALESCE(sum(CASE WHEN p.effect_group='SPEND' AND p.amount_minor<0 THEN -p.amount_minor::numeric ELSE 0 END),0),"
                                + "COALESCE(sum(CASE WHEN p.effect_group='SPEND' AND p.amount_minor>0 THEN p.amount_minor::numeric ELSE 0 END),0),"
                                + "COALESCE(sum(CASE WHEN p.effect_group='INTERNAL' THEN p.amount_minor::numeric ELSE 0 END),0)"
                                + predicate,
                        rs -> {
                            rs.next();
                            return new BigInteger[] {
                                exact(rs.getBigDecimal(1)),
                                exact(rs.getBigDecimal(2)),
                                exact(rs.getBigDecimal(3)),
                                exact(rs.getBigDecimal(4))
                            };
                        },
                        args.toArray());
        BigInteger spending = totals[1].subtract(totals[2]);
        Summary summary =
                new Summary(
                        totals[0].toString(),
                        totals[1].toString(),
                        totals[2].toString(),
                        spending.toString(),
                        totals[3].toString(),
                        totals[0].subtract(spending).add(totals[3]).toString());
        List<Category> categories =
                jdbc.query(
                        "SELECT p.category_code,c.display_name,-sum(p.amount_minor::numeric)"
                                + predicate.replace(
                                        " JOIN accounts a ON a.id=p.account_id",
                                        " JOIN accounts a ON a.id=p.account_id JOIN categories c ON c.code=p.category_code")
                                + " AND p.effect_group='SPEND' GROUP BY p.category_code,c.display_name,c.display_order ORDER BY c.display_order",
                        (rs, n) ->
                                new Category(
                                        rs.getString(1),
                                        rs.getString(2),
                                        exact(rs.getBigDecimal(3)).toString()),
                        args.toArray());
        List<Daily> days =
                jdbc.query(
                        "SELECT (p.posted_at AT TIME ZONE 'Africa/Johannesburg')::date,-sum(p.amount_minor::numeric)"
                                + predicate
                                + " AND p.effect_group='SPEND' GROUP BY 1 ORDER BY 1",
                        (rs, n) ->
                                new Daily(rs.getDate(1).toLocalDate(), exact(rs.getBigDecimal(2))),
                        args.toArray());
        return new Dashboard(
                new Scope(start, end, List.copyOf(selected)),
                summary,
                categories,
                buckets(start, end, days),
                dataset);
    }

    private Dashboard emptyDashboard(
            LocalDate start, LocalDate end, List<String> selected, Dataset dataset) {
        return new Dashboard(
                new Scope(start, end, selected),
                new Summary("0", "0", "0", "0", "0", "0"),
                List.of(),
                buckets(start, end, List.of()),
                dataset);
    }

    private static BigInteger exact(BigDecimal value) {
        return value.toBigIntegerExact();
    }

    private record Daily(LocalDate date, BigInteger cents) {}

    private static List<Trend> buckets(LocalDate from, LocalDate to, List<Daily> days) {
        long length = ChronoUnit.DAYS.between(from, to) + 1;
        Map<LocalDate, BigInteger> totals = new LinkedHashMap<>();
        for (LocalDate date = from; !date.isAfter(to); ) {
            totals.put(date, BigInteger.ZERO);
            date = next(date, length);
        }
        for (Daily day : days) {
            LocalDate key =
                    length <= 14
                            ? day.date()
                            : length <= 62
                                    ? day.date()
                                            .with(
                                                    TemporalAdjusters.previousOrSame(
                                                            DayOfWeek.MONDAY))
                                    : day.date().withDayOfMonth(1);
            if (key.isBefore(from)) key = from;
            totals.merge(key, day.cents(), BigInteger::add);
        }
        List<Trend> result = new ArrayList<>();
        for (LocalDate key : totals.keySet()) {
            LocalDate next = next(key, length);
            result.add(
                    new Trend(
                            key,
                            next.minusDays(1).isAfter(to) ? to : next.minusDays(1),
                            totals.get(key).toString()));
        }
        return result;
    }

    private static LocalDate next(LocalDate date, long length) {
        if (length <= 14) return date.plusDays(1);
        if (length <= 62) return date.with(TemporalAdjusters.next(DayOfWeek.MONDAY));
        return date.withDayOfMonth(1).plusMonths(1);
    }
}
