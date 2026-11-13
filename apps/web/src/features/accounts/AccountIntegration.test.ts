import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { expect, it, vi } from "vitest";
import App from "../../App.vue";

it("keeps fixed-date balances while account and period selection scope both routes", async () => {
  location.hash = "";
  const dataset = {
    datasetId: "fixture",
    instanceEpoch: "epoch",
    customerRevision: 0,
    referenceDate: "2026-10-31",
  };
  const requests: string[] = [];
  const fetch = vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    requests.push(url.pathname + url.search);
    let body: unknown;
    if (url.pathname.endsWith("/auth/session")) {
      body = {
        customerId: "fixture-f01",
        displayName: "Fixture One",
        expiresAtEpochMillis: Date.now() + 900000,
      };
    } else if (url.pathname.endsWith("/accounts")) {
      body = {
        accounts: [
          {
            id: "everyday",
            alias: "Everyday",
            maskedSuffix: "0042",
            accountKind: "EVERYDAY",
            postedBalanceMinor: "2215000",
          },
          {
            id: "savings",
            alias: "Savings",
            maskedSuffix: "0019",
            accountKind: "SAVINGS",
            postedBalanceMinor: "350000",
          },
        ],
        combinedPostedBalanceMinor: "2565000",
        balanceAsOfDate: "2026-10-31",
        currency: "ZAR",
        dataset,
      };
    } else if (url.pathname.endsWith("/dashboard")) {
      body = {
        scope: {
          from: url.searchParams.get("from") ?? "2026-10-01",
          to: url.searchParams.get("to") ?? "2026-10-31",
          accountIds: url.searchParams.get("accountIds")
            ? [url.searchParams.get("accountIds")]
            : ["everyday", "savings"],
        },
        summary: {
          incomeMinor: "0",
          grossSpendingMinor:
            url.searchParams.get("accountIds") === "savings"
              ? "20000"
              : "85000",
          spendingCreditsMinor: "0",
          netSpendingMinor:
            url.searchParams.get("accountIds") === "savings"
              ? "20000"
              : "85000",
          ownAccountFlowMinor: "0",
          netMovementMinor:
            url.searchParams.get("accountIds") === "savings"
              ? "-20000"
              : "-85000",
        },
        categories: [],
        trend: [],
        dataset,
      };
    } else if (url.pathname.includes("/transactions")) {
      body = { items: [], nextCursor: null, dataset };
    } else {
      throw new Error(`Unexpected URL ${url}`);
    }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  const wrapper = mount(App, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          {
            queryClient: new QueryClient({
              defaultOptions: { queries: { retry: false } },
            }),
          },
        ],
      ],
    },
  });
  try {
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("R25,650.00");
    expect(wrapper.text()).toContain("R850.00");
    expect(wrapper.findAll("#account")).toHaveLength(0);

    await wrapper.get('input[value="savings"]').setValue();
    await flushPromises();
    expect(
      requests.some((path) => path.includes("/dashboard?accountIds=savings")),
    ).toBe(true);
    expect(wrapper.text()).toContain("R200.00");
    expect(wrapper.text()).toContain("R3,500.00");

    const accountRequests = requests.filter((path) =>
      path.endsWith("/accounts"),
    ).length;
    await wrapper.get(".period-popover button:last-of-type").trigger("click");
    await wrapper.get("#from").setValue("2026-09-01");
    await wrapper.get("#to").setValue("2026-09-30");
    await wrapper.get(".custom-range").trigger("submit");
    await flushPromises();
    expect(requests.filter((path) => path.endsWith("/accounts"))).toHaveLength(
      accountRequests,
    );
    expect(
      requests.some(
        (path) =>
          path.includes("from=2026-09-01") &&
          path.includes("accountIds=savings"),
      ),
    ).toBe(true);
    expect(wrapper.text()).toContain("Posted balance · 31 Oct 2026");
    expect(wrapper.text()).toContain("R3,500.00");

    await wrapper.get(".main-nav button:last-child").trigger("click");
    await flushPromises();
    expect(wrapper.get(".account-button").text()).toContain("Savings");
    expect(wrapper.get(".period-picker").text()).toContain("1–30 Sept 2026");
    expect(wrapper.text()).toContain("Posted balance · 31 Oct 2026");
    expect(wrapper.text()).toContain("R3,500.00");
  } finally {
    wrapper.unmount();
    vi.unstubAllGlobals();
    location.hash = "";
  }
});

it("hides mixed account and dashboard revisions until one reconciliation aligns them", async () => {
  location.hash = "";
  let accountCalls = 0;
  let dashboardCalls = 0;
  let releaseFinal: ((value: Response) => void) | undefined;
  const finalDashboard = new Promise<Response>((resolve) => {
    releaseFinal = resolve;
  });
  const dataset = (revision: number) => ({
    datasetId: "fixture",
    instanceEpoch: "epoch",
    customerRevision: revision,
    referenceDate: "2026-10-31",
  });
  const response = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  const dashboard = (revision: number) => ({
    scope: { from: "2026-10-01", to: "2026-10-31", accountIds: ["everyday"] },
    summary: {
      incomeMinor: "0",
      grossSpendingMinor: revision ? "24000" : "0",
      spendingCreditsMinor: "0",
      netSpendingMinor: revision ? "24000" : "0",
      ownAccountFlowMinor: "0",
      netMovementMinor: revision ? "-24000" : "0",
    },
    categories: [],
    trend: [],
    dataset: dataset(revision),
  });
  const fetch = vi.fn((request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/auth/session"))
      return Promise.resolve(
        response({
          customerId: "fixture-f15",
          displayName: "Fixture Fifteen",
          expiresAtEpochMillis: Date.now() + 900000,
        }),
      );
    if (path.endsWith("/accounts")) {
      accountCalls++;
      const revision = accountCalls > 1 ? 1 : 0;
      return Promise.resolve(
        response({
          accounts: [
            {
              id: "everyday",
              alias: "Everyday",
              maskedSuffix: "0015",
              accountKind: "EVERYDAY",
              postedBalanceMinor: revision ? "76000" : "100000",
            },
          ],
          combinedPostedBalanceMinor: revision ? "76000" : "100000",
          balanceAsOfDate: "2026-10-31",
          currency: "ZAR",
          dataset: dataset(revision),
        }),
      );
    }
    if (path.endsWith("/dashboard")) {
      dashboardCalls++;
      return dashboardCalls === 3
        ? finalDashboard
        : Promise.resolve(response(dashboard(0)));
    }
    if (path.includes("/transactions"))
      return Promise.resolve(
        response({
          items: [],
          nextCursor: null,
          dataset: dataset(accountCalls > 1 ? 1 : 0),
        }),
      );
    throw new Error(`Unexpected URL ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  const wrapper = mount(App, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          {
            queryClient: new QueryClient({
              defaultOptions: { queries: { retry: false } },
            }),
          },
        ],
      ],
    },
  });
  try {
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("R1,000.00");
    await wrapper.get('[aria-label="Refresh data"]').trigger("click");
    await vi.waitFor(() => expect(dashboardCalls).toBe(3));
    expect(wrapper.text()).toContain(
      "Account balances and spending are updating",
    );
    expect(wrapper.text()).not.toContain("R760.00");
    expect(wrapper.text()).not.toContain("R240.00");
    releaseFinal?.(response(dashboard(1)));
    await vi.waitFor(() => expect(wrapper.text()).toContain("R760.00"));
    expect(wrapper.text()).toContain("R240.00");
    expect(accountCalls).toBe(3);
    expect(dashboardCalls).toBe(3);
  } finally {
    wrapper.unmount();
    vi.unstubAllGlobals();
    location.hash = "";
  }
});

it("treats a missing posted balance as unavailable instead of zero", async () => {
  location.hash = "";
  const fetch = vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    const body = path.endsWith("/auth/session")
      ? {
          customerId: "c1",
          displayName: "Sample",
          expiresAtEpochMillis: Date.now() + 900000,
        }
      : {
          accounts: [
            {
              id: "a1",
              alias: "Everyday",
              maskedSuffix: "0042",
              accountKind: "EVERYDAY",
            },
          ],
          combinedPostedBalanceMinor: "0",
          balanceAsOfDate: "2026-10-31",
          currency: "ZAR",
          dataset: {
            datasetId: "fixture",
            instanceEpoch: "epoch",
            customerRevision: 0,
            referenceDate: "2026-10-31",
          },
        };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  const wrapper = mount(App, {
    global: {
      plugins: [
        [
          VueQueryPlugin,
          {
            queryClient: new QueryClient({
              defaultOptions: { queries: { retry: false } },
            }),
          },
        ],
      ],
    },
  });
  try {
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("Accounts could not be loaded");
    expect(wrapper.text()).not.toContain("R0.00");
  } finally {
    wrapper.unmount();
    vi.unstubAllGlobals();
    location.hash = "";
  }
});
