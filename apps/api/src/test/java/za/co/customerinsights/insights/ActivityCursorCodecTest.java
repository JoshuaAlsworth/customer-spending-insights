package za.co.customerinsights.insights;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class ActivityCursorCodecTest {
    private static final String SECRET =
            "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
    private static final String ACCEPTED_CURSOR =
            "eyJiaW5kaW5nIjoiYmluZGluZyIsImRhdGFzZXRJZCI6ImRhdGFzZXQiLCJlcG9jaCI6IjEyM2U0NTY3LWU4OWItMTJkMy1hNDU2LTQyNjYxNDE3NDAwMCIsInJldmlzaW9uIjo3LCJhdCI6IjIwMjYtMTAtMDFUMTA6MDA6MDBaIiwiaWQiOiJwZV90ZXN0In0.Sugdb1OAKroTHVYx1icH3E9x8dw7xriecfvxinOtGWw";

    @Test
    void preservesAcceptedCursorBytesAndDecoding() {
        ActivityCursorCodec codec = new ActivityCursorCodec(new ObjectMapper(), SECRET);
        var cursor =
                new ActivityCursorCodec.Cursor(
                        "binding",
                        "dataset",
                        "123e4567-e89b-12d3-a456-426614174000",
                        7,
                        "2026-10-01T10:00:00Z",
                        "pe_test");
        assertThat(codec.encode(cursor)).isEqualTo(ACCEPTED_CURSOR);
        assertThat(codec.decode(ACCEPTED_CURSOR)).isEqualTo(cursor);
    }
}
