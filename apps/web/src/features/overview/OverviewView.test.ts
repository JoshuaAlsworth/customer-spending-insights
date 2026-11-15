import { flushPromises, mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import OverviewView from "./OverviewView.vue";
import type { Dashboard } from "../../api/client";

const dashboard: Dashboard = {
  scope: { from: "2026-10-01", to: "2026-10-31", accountIds: ["a1"] },
  summary: {
    incomeMinor: "2000000",
    grossSpendingMinor: "105000",
    spendingCreditsMinor: "20000",
    netSpendingMinor: "85000",
    ownAccountFlowMinor: "-200000",
    netMovementMinor: "1715000",
  },
  categories: [
    {
      categoryCode: "HEALTH",
      displayName: "Health",
      netSpendingMinor: "-20000",
    },
  ],
  trend: [{ from: "2026-10-01", to: "2026-10-07", netSpendingMinor: "85000" }],
  dataset: {
    datasetId: "fixture",
    instanceEpoch: "epoch",
    customerRevision: 0,
    referenceDate: "2026-10-31",
  },
};

const offlineFetch = vi.fn().mockRejectedValue(new Error("offline"));
vi.stubGlobal("fetch", offlineFetch);
const global = {
  plugins: [
    [
      VueQueryPlugin,
      {
        queryClient: new QueryClient({
          defaultOptions: { queries: { retry: false } },
        }),
      },
    ] as [typeof VueQueryPlugin, { queryClient: QueryClient }],
  ],
};
const previewProps = { customerId: "c1", accountIds: ["a1"], generation: 0 };

it("opens recent transaction details from the full row without duplicate clicks", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              id: "pe_recent",
              recordKind: "POSTED_ENTRY",
              merchantName: "Cedar Market",
              description: "Cedar Market groceries",
              type: "CARD_PURCHASE",
              categoryCode: "GROCERIES",
              amountMinor: "-24000",
              postedAt: "2026-10-01T10:00:00Z",
            },
          ],
          nextCursor: null,
          dataset: dashboard.dataset,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  const wrapper = mount(OverviewView, {
    props: {
      dashboard,
      hidden: false,
      ...previewProps,
      customerId: "recent-row-test",
    },
    global,
  });
  try {
    await flushPromises();
    const row = wrapper.get(".recent-table .transaction-row");
    await row.get(".amount").trigger("click");
    expect(wrapper.emitted("open")?.[0]).toEqual(["pe_recent"]);
    await row.get("button").trigger("click");
    expect(wrapper.emitted("open")).toHaveLength(2);
  } finally {
    wrapper.unmount();
    vi.stubGlobal("fetch", offlineFetch);
  }
});

it("uses one compact state for an account without posted spending", async () => {
  const empty = {
    ...dashboard,
    summary: {
      ...dashboard.summary,
      incomeMinor: "2000000",
      grossSpendingMinor: "0",
      spendingCreditsMinor: "0",
      netSpendingMinor: "0",
      netMovementMinor: "1800000",
    },
    categories: [],
    trend: [{ from: "2026-10-01", to: "2026-10-07", netSpendingMinor: "0" }],
  };
  const wrapper = mount(OverviewView, {
    props: {
      dashboard: empty,
      balanceMinor: "500000",
      balanceAsOf: "2026-10-31",
      hidden: false,
      ...previewProps,
    },
    global,
  });
  expect(wrapper.get(".summary-card.primary .metric-value").text()).toBe(
    "R0.00",
  );
  expect(wrapper.get(".mobile-balance-context").text()).toContain("R5,000.00");
  expect(wrapper.get(".analysis-empty").text()).toContain(
    "Try another account or period.",
  );
  expect(wrapper.findAll(".analysis .panel")).toHaveLength(1);
  expect(wrapper.find(".trend-chart").exists()).toBe(false);
  expect(wrapper.find(".transactions").exists()).toBe(true);
  await wrapper.setProps({
    dashboard: {
      ...empty,
      summary: {
        ...empty.summary,
        grossSpendingMinor: "10000",
        spendingCreditsMinor: "10000",
      },
    },
  });
  expect(wrapper.find(".analysis-empty").exists()).toBe(false);
  expect(wrapper.find(".trend-chart").exists()).toBe(true);
  wrapper.unmount();
});

it("keeps ten signed categories available through the desktop disclosure", async () => {
  const names = [
    "Housing & utilities",
    "Groceries",
    "Transport & fuel",
    "Money sent",
    "Cash withdrawals",
    "Other",
    "Bank fees",
    "Health",
    "Shopping",
    "Education",
  ];
  const expanded = {
    ...dashboard,
    categories: names.map((displayName, index) => ({
      categoryCode:
        `CATEGORY_${index}` as Dashboard["categories"][number]["categoryCode"],
      displayName,
      netSpendingMinor: index === 7 ? "-12000" : String((9 - index) * 10000),
    })),
  };
  const wrapper = mount(OverviewView, {
    props: { dashboard: expanded, hidden: false, ...previewProps },
    global,
  });
  expect(wrapper.findAll(".category-row")).toHaveLength(10);
  const toggle = wrapper.get(".category-toggle.desktop-needed");
  expect(toggle.classes()).toContain("desktop-needed");
  expect(toggle.attributes("aria-expanded")).toBe("false");
  expect(toggle.attributes("aria-controls")).toBe("overview-categories");
  await toggle.trigger("click");
  expect(toggle.attributes("aria-expanded")).toBe("true");
  expect(wrapper.text()).toContain("−R120.00");
  await wrapper.setProps({
    dashboard: {
      ...expanded,
      scope: { ...expanded.scope, from: "2026-09-01" },
    },
  });
  expect(toggle.attributes("aria-expanded")).toBe("false");
  wrapper.unmount();
});

it("shows exact authoritative amounts and hides every accessible amount", () => {
  const wrapper = mount(OverviewView, {
    props: { dashboard, hidden: false, ...previewProps },
    global,
  });
  expect(wrapper.get(".summary-card.primary .metric-value").text()).toBe(
    "−R850.00",
  );
  expect(wrapper.text()).toContain("+R17,150.00");
  expect(wrapper.text()).toContain("−R200.00");
  wrapper.setProps({ hidden: true });
  return wrapper.vm.$nextTick().then(() => {
    expect(wrapper.text()).not.toMatch(/R[\d,]+\.\d\d/);
    expect(wrapper.attributes("aria-label") ?? "").not.toMatch(/R[\d,]+\.\d\d/);
    expect(wrapper.text()).toContain("Amounts hidden");
  });
});

it("shows the selected posted balance on mobile and masks it with other amounts", async () => {
  const wrapper = mount(OverviewView, {
    props: {
      dashboard,
      balanceMinor: "-12000",
      balanceAsOf: "2026-10-31",
      hidden: false,
      ...previewProps,
    },
    global,
  });
  expect(wrapper.get(".mobile-balance-context").text()).toBe(
    "Balance −R120.00 · posted 31 Oct 2026",
  );
  await wrapper.setProps({ hidden: true });
  expect(wrapper.get(".mobile-balance-context").text()).toContain("••••");
  expect(wrapper.text()).not.toContain("R120.00");
  await wrapper.setProps({ hidden: false, balanceMinor: null });
  expect(wrapper.get(".mobile-balance-context").text()).toContain(
    "Unavailable",
  );
  wrapper.unmount();
});

it("uses the same mobile category scale for spending and refunds", () => {
  const wrapper = mount(OverviewView, {
    props: {
      dashboard: {
        ...dashboard,
        categories: [
          {
            categoryCode: "GROCERIES",
            displayName: "Groceries",
            netSpendingMinor: "420000",
          },
          {
            categoryCode: "HEALTH",
            displayName: "Health",
            netSpendingMinor: "-210000",
          },
        ],
      },
      hidden: false,
      ...previewProps,
    },
    global,
  });
  expect(
    wrapper.findAll(".signed-bar").map((bar) => bar.attributes("style")),
  ).toEqual([
    expect.stringContaining("--mobile-width: 100%"),
    expect.stringContaining("--mobile-width: 50%"),
  ]);
  wrapper.unmount();
});

it.each([
  ["85000", "−R850.00", false],
  ["-15000", "+R150.00", true],
  ["0", "R0.00", false],
] as const)(
  "renders the signed Money out value %s",
  (minor, expected, negative) => {
    const wrapper = mount(OverviewView, {
      props: {
        dashboard: {
          ...dashboard,
          summary: { ...dashboard.summary, netSpendingMinor: minor },
        },
        hidden: false,
        ...previewProps,
      },
      global,
    });
    expect(wrapper.get(".summary-card.primary .metric-value").text()).toBe(
      expected,
    );
    expect(wrapper.get(".summary-card.primary").text()).toContain(expected);
    expect(wrapper.find(".summary-card.primary .metric-note").exists()).toBe(
      negative,
    );
    wrapper.unmount();
  },
);

it("uses one visual scale for equal positive and negative trend buckets", () => {
  const signed = {
    ...dashboard,
    trend: [
      { from: "2026-10-01", to: "2026-10-07", netSpendingMinor: "10000" },
      { from: "2026-10-08", to: "2026-10-14", netSpendingMinor: "-10000" },
      { from: "2026-10-15", to: "2026-10-21", netSpendingMinor: "0" },
    ],
  };
  const wrapper = mount(OverviewView, {
    props: { dashboard: signed, hidden: false, ...previewProps },
    global,
  });
  expect(
    wrapper.findAll(".trend-bar").map((bar) => bar.attributes("style")),
  ).toEqual(["height: 45%;", "height: 45%;", "height: 0%;"]);
  expect(
    wrapper.findAll(".trend-column")[1].attributes("aria-label"),
  ).toContain("−R100.00");
  wrapper.unmount();
});

it("shows the selected trend bucket and clears it when the period changes", async () => {
  const wrapper = mount(OverviewView, {
    props: { dashboard, hidden: false, ...previewProps },
    global,
  });
  await wrapper.get(".trend-column").trigger("click");
  expect(wrapper.get(".trend-column").attributes("aria-pressed")).toBe("true");
  expect(wrapper.get(".trend-reading").text()).toContain("R850.00");
  await wrapper.setProps({
    dashboard: {
      ...dashboard,
      scope: { ...dashboard.scope, from: "2026-09-01" },
    },
  });
  expect(wrapper.find(".trend-reading").exists()).toBe(false);
  wrapper.unmount();
});

it("opens transactions with the selected category code", async () => {
  const wrapper = mount(OverviewView, {
    props: { dashboard, hidden: false, ...previewProps },
    global,
  });
  await wrapper
    .get('button[aria-label="Filter transactions by Health"]')
    .trigger("click");
  expect(wrapper.emitted("category")?.[0]).toEqual(["HEALTH"]);
  wrapper.unmount();
});
