import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
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

it("shows exact authoritative amounts and hides every accessible amount", () => {
  const wrapper = mount(OverviewView, { props: { dashboard, hidden: false } });
  expect(wrapper.text()).toContain("R850.00");
  expect(wrapper.text()).toContain("+R17,150.00");
  expect(wrapper.text()).toContain("−R200.00");
  wrapper.setProps({ hidden: true });
  return wrapper.vm.$nextTick().then(() => {
    expect(wrapper.text()).not.toMatch(/R[\d,]+\.\d\d/);
    expect(wrapper.attributes("aria-label") ?? "").not.toMatch(/R[\d,]+\.\d\d/);
    expect(wrapper.text()).toContain("Amounts hidden");
  });
});

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
    props: { dashboard: signed, hidden: false },
  });
  expect(
    wrapper.findAll(".trend-bar").map((bar) => bar.attributes("style")),
  ).toEqual(["height: 45%;", "height: 45%;", "height: 0%;"]);
  expect(wrapper.text()).toContain("−R100.00");
  wrapper.unmount();
});
