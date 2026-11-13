import { mount } from "@vue/test-utils";
import { flushPromises } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { expect, it, vi } from "vitest";
import App from "./App.vue";

const accountResponse = (referenceDate: string, balance = "500000") => ({
  accounts: [
    {
      id: "a1",
      alias: "Everyday",
      maskedSuffix: "0042",
      accountKind: "EVERYDAY",
      postedBalanceMinor: balance,
    },
  ],
  combinedPostedBalanceMinor: balance,
  balanceAsOfDate: referenceDate,
  currency: "ZAR",
  dataset: {
    datasetId: "test",
    instanceEpoch: "epoch",
    customerRevision: 0,
    referenceDate,
  },
});

it("shows sign in after a rejected session bootstrap", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("", { status: 401 }));
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
  await flushPromises();
  expect(wrapper.get("h1").text()).toBe("Welcome back");
  expect((fetch.mock.calls[0] as unknown as [Request])[0].url).toContain(
    "/api/v1/auth/session",
  );
  expect((fetch.mock.calls[0] as unknown as [Request])[0].credentials).toBe(
    "same-origin",
  );
  expect(
    fetch.mock.calls.every(
      (call) => !(call[0] as Request).url.includes("actuator"),
    ),
  ).toBe(true);
  wrapper.unmount();
  vi.unstubAllGlobals();
});

it("renders the server dashboard after session and account lookup", async () => {
  const dataset = {
    scope: { from: "2026-11-01", to: "2026-11-11", accountIds: ["a1"] },
    summary: {
      incomeMinor: "2000000",
      grossSpendingMinor: "105000",
      spendingCreditsMinor: "20000",
      netSpendingMinor: "85000",
      ownAccountFlowMinor: "-200000",
      netMovementMinor: "1715000",
    },
    categories: [],
    trend: [],
    dataset: {
      datasetId: "test",
      instanceEpoch: "epoch",
      customerRevision: 0,
      referenceDate: "2026-11-11",
    },
  };
  const fetch = vi.fn(async (request: Request) => {
    const path = request.url;
    const value = path.endsWith("/auth/session")
      ? {
          customerId: "c1",
          displayName: "Sample Customer",
          expiresAtEpochMillis: Date.now() + 900000,
        }
      : path.endsWith("/accounts")
        ? accountResponse("2026-11-11")
        : dataset;
    return new Response(JSON.stringify(value), {
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
  await flushPromises();
  await flushPromises();
  expect(wrapper.text()).toContain("R850.00");
  expect(wrapper.text()).toContain("Sample Customer");
  expect(
    fetch.mock.calls.some((call) =>
      (call[0] as Request).url.includes("/api/v1/dashboard"),
    ),
  ).toBe(true);
  expect(
    fetch.mock.calls.some((call) =>
      (call[0] as Request).url.includes("/api/v1/dashboard?accountIds=a1"),
    ),
  ).toBe(true);
  wrapper.unmount();
  vi.unstubAllGlobals();
});

it("applies a chart category again after reset without changing the spending scope", async () => {
  location.hash = "#overview";
  const dashboard = {
    scope: { from: "2026-10-01", to: "2026-10-31", accountIds: ["a1"] },
    summary: {
      incomeMinor: "0",
      grossSpendingMinor: "85000",
      spendingCreditsMinor: "0",
      netSpendingMinor: "85000",
      ownAccountFlowMinor: "0",
      netMovementMinor: "-85000",
    },
    categories: [
      {
        categoryCode: "GROCERIES",
        displayName: "Groceries",
        netSpendingMinor: "60000",
      },
      {
        categoryCode: "HEALTH",
        displayName: "Health",
        netSpendingMinor: "25000",
      },
    ],
    trend: [],
    dataset: {
      datasetId: "test",
      instanceEpoch: "epoch",
      customerRevision: 0,
      referenceDate: "2026-10-31",
    },
  };
  const activityRequests: URL[] = [];
  const fetch = vi.fn(async (request: Request) => {
    const url = new URL(request.url);
    const body = url.pathname.endsWith("/auth/session")
      ? {
          customerId: "c1",
          displayName: "Customer",
          expiresAtEpochMillis: Date.now() + 900000,
        }
      : url.pathname.endsWith("/accounts")
        ? accountResponse("2026-10-31")
        : url.pathname.endsWith("/dashboard")
          ? dashboard
          : (() => {
              activityRequests.push(url);
              return {
                items: [],
                nextCursor: null,
                dataset: dashboard.dataset,
              };
            })();
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
    const groceries = 'button[aria-label="Filter transactions by Groceries"]';
    await wrapper.get(groceries).trigger("click");
    await flushPromises();
    expect(
      (
        wrapper.get("label:has(select):last-of-type select")
          .element as HTMLSelectElement
      ).value,
    ).toBe("GROCERIES");
    expect(activityRequests.at(-1)?.searchParams.get("category")).toBe(
      "GROCERIES",
    );
    await wrapper.get(".transaction-filter-menu summary").trigger("click");
    await wrapper.get(".transaction-filter-popover button").trigger("click");
    await flushPromises();
    expect(
      (
        wrapper.get("label:has(select):last-of-type select")
          .element as HTMLSelectElement
      ).value,
    ).toBe("");
    await wrapper.get(".sidebar-nav button:first-child").trigger("click");
    await wrapper.get(groceries).trigger("click");
    await flushPromises();
    expect(
      (
        wrapper.get("label:has(select):last-of-type select")
          .element as HTMLSelectElement
      ).value,
    ).toBe("GROCERIES");
    expect(activityRequests.at(-1)?.searchParams.get("category")).toBe(
      "GROCERIES",
    );
    expect(activityRequests.at(-1)?.searchParams.has("cursor")).toBe(false);
    await wrapper.get(".sidebar-nav button:first-child").trigger("click");
    expect(wrapper.get(".summary-card.primary .metric-value").text()).toBe(
      "+R850.00",
    );
    await wrapper
      .get('button[aria-label="Filter transactions by Health"]')
      .trigger("click");
    await flushPromises();
    expect(activityRequests.at(-1)?.searchParams.get("category")).toBe(
      "HEALTH",
    );
    expect(wrapper.get(".account-button").text()).toContain("Everyday");
    expect(wrapper.get(".period-control").text()).toContain("Oct 2026");
  } finally {
    wrapper.unmount();
    vi.unstubAllGlobals();
    location.hash = "";
  }
});

it("keeps cached spending concealed after failed logout until a server session check succeeds", async () => {
  let failLogout = true;
  const dashboard = {
    scope: { from: "2026-10-01", to: "2026-10-31", accountIds: ["a1"] },
    summary: {
      incomeMinor: "2000000",
      grossSpendingMinor: "105000",
      spendingCreditsMinor: "20000",
      netSpendingMinor: "85000",
      ownAccountFlowMinor: "0",
      netMovementMinor: "1915000",
    },
    categories: [],
    trend: [],
    dataset: {
      datasetId: "test",
      instanceEpoch: "epoch",
      customerRevision: 0,
      referenceDate: "2026-10-31",
    },
  };
  const fetch = vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/auth/logout") && failLogout)
      return new Response("", { status: 503 });
    const body = path.endsWith("/auth/csrf")
      ? { token: "test-csrf" }
      : path.endsWith("/auth/session")
        ? {
            customerId: "c1",
            displayName: "Sample Customer",
            expiresAtEpochMillis: Date.now() + 900000,
          }
        : path.endsWith("/accounts")
          ? accountResponse("2026-10-31")
          : dashboard;
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
    expect(wrapper.text()).toContain("R850.00");
    await wrapper.get(".profile-popover button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Sign out could not be confirmed");
    expect(wrapper.text()).not.toContain("R850.00");
    expect(
      wrapper.get('[aria-label="Show amounts"]').attributes("disabled"),
    ).toBeDefined();
    await wrapper.get('[aria-label="Show amounts"]').trigger("click");
    expect(wrapper.text()).not.toContain("R850.00");
    await wrapper.get("button.button.secondary").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("R850.00");
    failLogout = false;
    await wrapper.get(".profile-popover button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).not.toContain("R850.00");
    expect(wrapper.get("h1").text()).toBe("Welcome back");
  } finally {
    wrapper.unmount();
    vi.unstubAllGlobals();
  }
});

it("rejects a late previous-customer dashboard after logout and new login", async () => {
  let customer = "c1";
  let releaseOld: ((response: Response) => void) | undefined;
  const oldDashboard = new Promise<Response>((resolve) => {
    releaseOld = resolve;
  });
  const response = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  const dashboard = (amount: string) => ({
    scope: { from: "2026-10-01", to: "2026-10-31", accountIds: ["a1"] },
    summary: {
      incomeMinor: "0",
      grossSpendingMinor: amount,
      spendingCreditsMinor: "0",
      netSpendingMinor: amount,
      ownAccountFlowMinor: "0",
      netMovementMinor: `-${amount}`,
    },
    categories: [],
    trend: [],
    dataset: {
      datasetId: "test",
      instanceEpoch: "epoch",
      customerRevision: 0,
      referenceDate: "2026-10-31",
    },
  });
  const fetch = vi.fn((request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/auth/csrf"))
      return Promise.resolve(response({ token: "test-csrf" }));
    if (path.endsWith("/auth/login")) {
      customer = "c2";
      return Promise.resolve(
        response({
          customerId: customer,
          displayName: "Second Customer",
          expiresAtEpochMillis: Date.now() + 900000,
        }),
      );
    }
    if (path.endsWith("/auth/logout"))
      return Promise.resolve(new Response(null, { status: 204 }));
    if (path.endsWith("/auth/session"))
      return Promise.resolve(
        response({
          customerId: customer,
          displayName: "First Customer",
          expiresAtEpochMillis: Date.now() + 900000,
        }),
      );
    if (path.endsWith("/accounts"))
      return Promise.resolve(response(accountResponse("2026-10-31")));
    if (path.endsWith("/dashboard"))
      return customer === "c1"
        ? oldDashboard
        : Promise.resolve(response(dashboard("20000")));
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
    expect(
      fetch.mock.calls.some(([request]) =>
        new URL((request as Request).url).pathname.endsWith("/dashboard"),
      ),
    ).toBe(true);
    await wrapper.get(".profile-popover button").trigger("click");
    await flushPromises();
    releaseOld?.(response(dashboard("999900")));
    await flushPromises();
    expect(wrapper.text()).not.toContain("R9,999.00");
    await wrapper.get("#login-id").setValue("fixture-second");
    await wrapper.get("#password").setValue("fixture-only-password");
    await wrapper.get(".sign-card").trigger("submit");
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("R200.00");
    expect(wrapper.text()).not.toContain("R9,999.00");
  } finally {
    wrapper.unmount();
    vi.unstubAllGlobals();
  }
});
