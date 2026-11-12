package za.co.customerinsights.insights;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@Component
public class ActivityCursorCodec {
    private final ObjectMapper mapper;
    private final byte[] secret;

    public ActivityCursorCodec(ObjectMapper mapper, @Value("${CURSOR_SECRET:}") String secret) {
        this.mapper = mapper;
        if (!secret.matches("[0-9a-fA-F]{64}")) {
            throw new IllegalArgumentException("CURSOR_SECRET must be 64 hexadecimal characters");
        }
        this.secret = HexFormat.of().parseHex(secret);
        boolean allSame = true;
        for (byte value : this.secret) allSame &= value == this.secret[0];
        if (allSame) throw new IllegalArgumentException("CURSOR_SECRET cannot repeat one byte");
    }

    record Cursor(
            String binding, String datasetId, String epoch, long revision, String at, String id) {}

    String binding(
            ReportingScope.Resolved scope,
            String state,
            String type,
            String category,
            String term,
            int size) {
        return digest(
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
    }

    void validate(Cursor cursor, String binding, FinancialController.Dataset dataset) {
        if (!cursor.binding().equals(binding)) invalid();
        if (!cursor.datasetId().equals(dataset.datasetId())
                || !cursor.epoch().equals(dataset.instanceEpoch())
                || cursor.revision() != dataset.customerRevision()) {
            throw new StaleCursorException();
        }
    }

    private static String value(String input) {
        return input == null ? "" : input;
    }

    private static void invalid() {
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid transaction request");
    }

    String encode(Cursor cursor) {
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

    Cursor decode(String encoded) {
        try {
            if (encoded.length() > 2048 || !encoded.matches("[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+")) {
                invalid();
            }
            String[] parts = encoded.split("\\.");
            byte[] body = Base64.getUrlDecoder().decode(parts[0]);
            byte[] signature = Base64.getUrlDecoder().decode(parts[1]);
            var canonical = Base64.getUrlEncoder().withoutPadding();
            if (!canonical.encodeToString(body).equals(parts[0])
                    || !canonical.encodeToString(signature).equals(parts[1])
                    || signature.length != 32
                    || !MessageDigest.isEqual(mac(parts[0]), signature)) {
                invalid();
            }
            Cursor cursor = mapper.readValue(body, Cursor.class);
            if (cursor.binding() == null
                    || cursor.datasetId() == null
                    || cursor.epoch() == null
                    || cursor.at() == null
                    || cursor.id() == null
                    || !cursor.id().matches("^(au|pe)_[A-Za-z0-9_-]+$")) {
                invalid();
            }
            Instant.parse(cursor.at());
            return cursor;
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (Exception ex) {
            invalid();
            return null;
        }
    }

    private byte[] mac(String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(secret, "HmacSHA256"));
        return mac.doFinal(body.getBytes(StandardCharsets.UTF_8));
    }

    static String digest(String body) {
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
