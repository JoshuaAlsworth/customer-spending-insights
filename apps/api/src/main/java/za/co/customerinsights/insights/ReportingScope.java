package za.co.customerinsights.insights;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
public class ReportingScope {
    private final JdbcTemplate jdbc;

    public ReportingScope(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public record Resolved(
            String owner,
            List<String> accounts,
            LocalDate from,
            LocalDate to,
            FinancialController.Dataset dataset) {
        public Resolved canonical() {
            return new Resolved(owner, accounts.stream().sorted().toList(), from, to, dataset);
        }
    }

    public Resolved resolve(
            String owner, String accountIds, String from, String to, boolean activity) {
        FinancialController.Dataset dataset = dataset(owner);
        LocalDate end = date(to, dataset.referenceDate(), activity);
        LocalDate start = date(from, end.withDayOfMonth(1), activity);
        if (start.isAfter(end)
                || end.isAfter(dataset.referenceDate())
                || start.isBefore(end.minusMonths(36).plusDays(1))
                || ChronoUnit.DAYS.between(start, end) > 1100) {
            invalid(activity, "Invalid reporting period");
        }
        List<String> selected;
        if (accountIds == null) {
            selected =
                    jdbc.query(
                            "SELECT id FROM accounts WHERE customer_id=? AND status='OPEN' AND opened_on<=? ORDER BY id",
                            (rs, n) -> rs.getString(1),
                            owner,
                            dataset.referenceDate());
        } else {
            selected = List.of(accountIds.split(",", -1));
            if (selected.size() > 4
                    || selected.stream().anyMatch(id -> !id.matches("[A-Za-z0-9_-]{1,64}"))
                    || selected.stream().distinct().count() != selected.size()) {
                invalid(activity, "Invalid account selection");
            }
            String placeholders = String.join(",", Collections.nCopies(selected.size(), "?"));
            List<Object> args = new ArrayList<>();
            args.add(owner);
            args.add(dataset.referenceDate());
            args.addAll(selected);
            Integer count =
                    jdbc.queryForObject(
                            "SELECT count(*) FROM accounts WHERE customer_id=? AND status='OPEN' AND opened_on<=? AND id IN ("
                                    + placeholders
                                    + ")",
                            Integer.class,
                            args.toArray());
            if (count == null || count != selected.size()) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Scope unavailable");
            }
        }
        return new Resolved(owner, List.copyOf(selected), start, end, dataset);
    }

    public FinancialController.Dataset dataset(String owner) {
        FinancialController.Dataset dataset =
                jdbc.query(
                        "SELECT d.dataset_id,d.instance_epoch,c.customer_revision,d.reference_date FROM dataset_instance d CROSS JOIN customers c WHERE d.singleton=true AND c.id=?",
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
        return dataset;
    }

    private static LocalDate date(String value, LocalDate fallback, boolean activity) {
        if (value == null) return fallback;
        try {
            if (!value.matches("\\d{4}-\\d{2}-\\d{2}")) throw new IllegalArgumentException();
            return LocalDate.parse(value);
        } catch (RuntimeException ex) {
            invalid(activity, "Invalid date");
            return fallback;
        }
    }

    private static void invalid(boolean activity, String dashboardReason) {
        throw new ResponseStatusException(
                HttpStatus.BAD_REQUEST, activity ? "Invalid transaction request" : dashboardReason);
    }
}
