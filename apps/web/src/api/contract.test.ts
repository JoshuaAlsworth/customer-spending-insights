import { expect, expectTypeOf, it, vi } from "vitest";
import { getTransaction, getTransactions, login } from "./client";
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

const authorization = {
  recordKind: "AUTHORIZATION",
  id: "au_test",
  accountId: "account",
  maskedSuffix: "1234",
  merchantName: null,
  description: "Card hold",
  status: "PENDING",
  type: "CARD_PURCHASE",
  authorizedAmountMinor: "123",
  occurredAt: "2026-10-01T10:00:00Z",
  postedAt: null,
  amountMinor: null,
  effectGroup: null,
  categoryCode: null,
};

const posted = {
  ...authorization,
  recordKind: "POSTED_ENTRY",
  id: "pe_test",
  status: "POSTED",
  postedAt: "2026-10-02T10:00:00Z",
  amountMinor: "-123",
  effectGroup: "SPEND",
  categoryCode: "GROCERIES",
  authorizationActivityId: "au_test",
  originalActivityId: null,
};

async function withResponse<T>(body: unknown, run: () => Promise<T>) {
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetch);
  try {
    return await run();
  } finally {
    vi.unstubAllGlobals();
  }
}

it.each([authorization, posted])(
  "preserves list and detail variant $recordKind",
  async (item) => {
    const page = {
      items: [item],
      nextCursor: null,
      dataset: {
        datasetId: "d",
        instanceEpoch: "e",
        customerRevision: 1,
        referenceDate: "2026-10-31",
      },
    };
    expect(await withResponse(page, () => getTransactions({}))).toEqual(page);
    expect(await withResponse(item, () => getTransaction(item.id))).toEqual(
      item,
    );
  },
);

it.each(["postedAt", "amountMinor", "effectGroup", "categoryCode"] as const)(
  "rejects missing or non-null authorization field %s",
  async (field) => {
    const missing = { ...authorization };
    delete (missing as Partial<typeof authorization>)[field];
    await expect(
      withResponse(missing, () => getTransaction(missing.id)),
    ).rejects.toThrow(field);
    await expect(
      withResponse({ items: [missing], nextCursor: null, dataset: {} }, () =>
        getTransactions({}),
      ),
    ).rejects.toThrow(field);
    const wrong = { ...authorization, [field]: "invalid" };
    await expect(
      withResponse(wrong, () => getTransaction(wrong.id)),
    ).rejects.toThrow(field);
  },
);

it("rejects an unknown activity variant", async () => {
  await expect(
    withResponse({ ...authorization, recordKind: "UNKNOWN" }, () =>
      getTransaction("au_test"),
    ),
  ).rejects.toThrow("Invalid activity response");
});
