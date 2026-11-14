package za.co.customerinsights.security;

import java.sql.SQLException;
import java.sql.SQLTransientConnectionException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.transaction.TransactionSystemException;

final class DatabaseUnavailable {
    private DatabaseUnavailable() {}

    static boolean causedBy(Throwable error) {
        for (Throwable cause = error; cause != null; cause = cause.getCause()) {
            if (cause instanceof DataAccessResourceFailureException
                    || cause instanceof QueryTimeoutException
                    || cause instanceof SQLTransientConnectionException) return true;
            if (cause instanceof TransactionSystemException transaction
                    && closedHikariRollback(transaction)) return true;
            if (cause instanceof SQLException sql) {
                String state = sql.getSQLState();
                if (state != null
                        && (state.startsWith("08")
                                || state.equals("57014")
                                || state.equals("57P01")
                                || state.equals("57P02")
                                || state.equals("57P03"))) return true;
            }
        }
        return false;
    }

    private static boolean closedHikariRollback(TransactionSystemException transaction) {
        if (!"JDBC rollback failed".equals(transaction.getMessage())
                || !(transaction.getCause() instanceof SQLException sql)
                || sql.getClass() != SQLException.class
                || sql.getSQLState() != null
                || sql.getErrorCode() != 0
                || !"Connection is closed".equals(sql.getMessage())) return false;

        // Hikari's closed-connection proxy loses SQLState; require its rollback call path.
        StackTraceElement[] trace = sql.getStackTrace();
        if (trace.length == 0
                || !"com.zaxxer.hikari.pool.ProxyConnection$ClosedConnection"
                        .equals(trace[0].getClassName())
                || !"lambda$getClosedConnection$0".equals(trace[0].getMethodName())) return false;
        for (StackTraceElement frame : trace) {
            if ("com.zaxxer.hikari.pool.ProxyConnection".equals(frame.getClassName())
                    && "rollback".equals(frame.getMethodName())) return true;
        }
        return false;
    }
}
