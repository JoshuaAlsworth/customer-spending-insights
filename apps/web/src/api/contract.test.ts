import { expect, expectTypeOf, it, vi } from "vitest";
import { login } from "./client";
import type { components } from "./generated/schema";

type Activity = components["schemas"]["Activity"];
type Authorization = Extract<Activity, { recordKind: "AUTHORIZATION" }>;
type Posted = Extract<Activity, { recordKind: "POSTED_ENTRY" }>;

expectTypeOf<components["schemas"]["MoneyMinor"]>().toEqualTypeOf<string>();
expectTypeOf<Authorization["amountMinor"]>().toEqualTypeOf<null>();
expectTypeOf<Authorization["authorizedAmountMinor"]>().toEqualTypeOf<string>();
expectTypeOf<Posted["amountMinor"]>().toEqualTypeOf<string>();
expectTypeOf<Posted["authorizedAmountMinor"]>().toEqualTypeOf<string | null>();
expectTypeOf<Authorization["status"]>().toEqualTypeOf<
  "PENDING" | "CANCELLED"
>();
expectTypeOf<
  components["schemas"]["Problem"]["code"]
>().toEqualTypeOf<string>();

it("sends same-origin credentials and the CSRF header on login", async () => {
  const fetch = vi.fn(async (request: Request) => {
    const pathname = new URL(request.url).pathname;
    return new Response(
      JSON.stringify(
        pathname.endsWith("/csrf")
          ? { token: "test-csrf" }
          : {
              customerId: "test",
              displayName: "Test",
              expiresAtEpochMillis: 1,
            },
      ),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });
  vi.stubGlobal("fetch", fetch);
  try {
    await login("synthetic", "test-only");
    const calls = fetch.mock.calls.map(([request]) => request);
    expect(calls).toHaveLength(3);
    expect(calls[0].url).toContain("/api/v1/auth/csrf");
    expect(calls[1].credentials).toBe("same-origin");
    expect(calls[1].headers.get("X-XSRF-TOKEN")).toBe("test-csrf");
    expect(await calls[1].json()).toEqual({
      loginId: "synthetic",
      password: "test-only",
    });
  } finally {
    vi.unstubAllGlobals();
  }
});
