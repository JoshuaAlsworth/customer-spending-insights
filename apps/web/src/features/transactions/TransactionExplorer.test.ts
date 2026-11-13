import { mount, flushPromises } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { afterEach, expect, it, vi } from "vitest";
import TransactionExplorer from "./TransactionExplorer.vue";
import type { ActivityPage } from "../../api/client";

const { getTransactions, getTransaction } = vi.hoisted(() => ({
  getTransactions: vi.fn(),
  getTransaction: vi.fn(),
}));
vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, getTransactions, getTransaction };
});

const posted = {
  recordKind: "POSTED_ENTRY",
  id: "pe_one",
  accountId: "owned",
  maskedSuffix: "1234",
  merchantName: "Cedar Market",
  description: "Cedar Market groceries",
  status: "POSTED",
  type: "CARD_PURCHASE",
  amountMinor: "-24000",
  authorizedAmountMinor: "25000",
  effectGroup: "SPEND",
  categoryCode: "GROCERIES",
  occurredAt: "2026-10-01T09:00:00Z",
  postedAt: "2026-10-01T10:00:00Z",
  authorizationActivityId: "au_one",
  originalActivityId: null,
} as const;
const dataset = {
  datasetId: "demo",
  instanceEpoch: "00000000-0000-0000-0000-000000000001",
  customerRevision: 0,
  referenceDate: "2026-10-31",
};
const page = (cursor: string | null): ActivityPage =>
  ({ items: [posted], nextCursor: cursor, dataset }) as ActivityPage;
function mountExplorer() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return mount(TransactionExplorer, {
    props: {
      customerId: "customer",
      accountIds: ["owned"],
      from: "2026-10-01",
      to: "2026-10-31",
      hidden: false,
      active: true,
      generation: 1,
      datasetEpoch: dataset.instanceEpoch,
      dashboardRevision: 0,
      referenceDate: dataset.referenceDate,
      detailId: null,
    },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  });
}
afterEach(() => {
  vi.clearAllMocks();
});

it("uses one responsive row source for keyset pages, resets filters, and hides amounts", async () => {
  getTransactions.mockImplementation(async (filters: { cursor?: string }) =>
    page(filters.cursor ? null : "next"),
  );
  const wrapper = mountExplorer();
  await flushPromises();
  expect(wrapper.findAll(".activity-table tbody tr")).toHaveLength(1);
  expect(wrapper.findAll(".activity-section")).toHaveLength(1);
  expect(wrapper.get(".activity-section .subsection-title").text()).toBe(
    "Posted transactions",
  );
  expect(wrapper.findAll(".activity-card")).toHaveLength(0);
  expect(wrapper.text()).toContain("−R240.00");
  await wrapper.get(".activity-pagination button:last-child").trigger("click");
  await flushPromises();
  expect(getTransactions.mock.calls.at(-1)?.[0].cursor).toBe("next");
  await wrapper.get("select").setValue("PENDING");
  await flushPromises();
  expect(getTransactions.mock.calls.at(-1)?.[0].cursor).toBeUndefined();
  expect(getTransactions.mock.calls.at(-1)?.[0].status).toBe("PENDING");
  await wrapper.setProps({ hidden: true });
  expect(wrapper.text()).not.toContain("R240.00");
  wrapper.unmount();
});

it("returns to the first cursor when the same chart category is activated again", async () => {
  getTransactions.mockImplementation(async (filters: { cursor?: string }) =>
    page(filters.cursor ? null : "next"),
  );
  const wrapper = mountExplorer();
  await flushPromises();
  wrapper.vm.applyCategory("GROCERIES");
  await flushPromises();
  expect(getTransactions.mock.calls.at(-1)?.[0]).toMatchObject({
    category: "GROCERIES",
    cursor: undefined,
  });
  await wrapper.get(".activity-pagination button:last-child").trigger("click");
  await flushPromises();
  expect(getTransactions.mock.calls.at(-1)?.[0].cursor).toBe("next");
  wrapper.vm.applyCategory("GROCERIES");
  await flushPromises();
  expect(getTransactions.mock.calls.at(-1)?.[0]).toMatchObject({
    category: "GROCERIES",
    cursor: undefined,
  });
  wrapper.unmount();
});

it("debounces normalized search and shows typed posted detail", async () => {
  getTransactions.mockResolvedValue(page(null));
  getTransaction.mockResolvedValue(posted);
  const wrapper = mountExplorer();
  await flushPromises();
  const firstCount = getTransactions.mock.calls.length;
  await wrapper.get('input[type="search"]').setValue("  CEDAR   MARKET ");
  await new Promise((resolve) => setTimeout(resolve, 350));
  await flushPromises();
  expect(getTransactions.mock.calls.length).toBe(firstCount + 1);
  expect(getTransactions.mock.calls.at(-1)?.[0].search).toBe("CEDAR MARKET");
  await wrapper.get(".activity-link").trigger("click");
  expect(wrapper.emitted("open")?.[0]).toEqual(["pe_one"]);
  await wrapper.setProps({ detailId: "pe_one" });
  await flushPromises();
  expect(wrapper.get('[role="dialog"]').text()).toContain(
    "Originally authorised",
  );
  expect(wrapper.get('[role="dialog"]').text()).toContain("R250.00");
  wrapper.unmount();
});

it("validates Unicode code points locally before sending search", async () => {
  getTransactions.mockResolvedValue(page(null));
  const wrapper = mountExplorer();
  await flushPromises();
  const field = wrapper.get('input[type="search"]');
  const initialCalls = getTransactions.mock.calls.length;
  await field.setValue("😀");
  expect(field.attributes("aria-invalid")).toBe("true");
  expect(field.attributes("aria-describedby")).toBe("transaction-search-error");
  expect(wrapper.get("#transaction-search-error").text()).toContain(
    "at least 2",
  );
  await new Promise((resolve) => setTimeout(resolve, 330));
  expect(getTransactions).toHaveBeenCalledTimes(initialCalls);
  expect(wrapper.text()).not.toContain("Transactions could not be loaded.");

  for (const [input, expected] of [
    ["😀😀", "😀😀"],
    ["𐐷𐐷", "𐐷𐐷"],
    ["e\u0301", "e\u0301"],
    ["ab", "ab"],
    ["x".repeat(100), "x".repeat(100)],
    ["  A   B  ", "A B"],
    ["\u00a0 A\u00a0\u00a0B \u00a0", "A B"],
    ["%_\\", "%_\\"],
    ["", ""],
  ] as const) {
    await field.setValue(input);
    expect(field.attributes("aria-invalid")).toBe("false");
    await new Promise((resolve) => setTimeout(resolve, 330));
    await flushPromises();
    expect(getTransactions.mock.calls.at(-1)?.[0].search).toBe(
      expected || undefined,
    );
  }
  const validCalls = getTransactions.mock.calls.length;
  await field.setValue("x".repeat(101));
  expect(wrapper.get("#transaction-search-error").text()).toContain(
    "100 characters",
  );
  await new Promise((resolve) => setTimeout(resolve, 330));
  expect(getTransactions).toHaveBeenCalledTimes(validCalls);
  await wrapper.get(".transaction-tools button").trigger("click");
  expect(wrapper.find("#transaction-search-error").exists()).toBe(false);
  wrapper.unmount();
});

it("does not show an older search response under newer filters", async () => {
  let resolveOld!: (value: ActivityPage) => void;
  let resolveNew!: (value: ActivityPage) => void;
  getTransactions.mockImplementation(({ search }: { search?: string }) => {
    if (search === "Cedar")
      return new Promise<ActivityPage>((resolve) => (resolveOld = resolve));
    if (search === "Harbor")
      return new Promise<ActivityPage>((resolve) => (resolveNew = resolve));
    return Promise.resolve(page(null));
  });
  const wrapper = mountExplorer();
  await flushPromises();
  const field = wrapper.get('input[type="search"]');
  await field.setValue("Cedar");
  await new Promise((resolve) => setTimeout(resolve, 330));
  await flushPromises();
  await field.setValue("Harbor");
  await new Promise((resolve) => setTimeout(resolve, 330));
  await flushPromises();
  resolveNew({
    ...page(null),
    items: [{ ...posted, id: "pe_harbor", merchantName: "Harbor" }],
  } as ActivityPage);
  await flushPromises();
  expect(wrapper.text()).toContain("Harbor");
  resolveOld(page(null));
  await flushPromises();
  expect(wrapper.text()).toContain("Harbor");
  expect(wrapper.text()).not.toContain("Cedar Market");
  wrapper.unmount();
});

it("distinguishes empty available history from an empty selected period", async () => {
  getTransactions.mockResolvedValue({ items: [], nextCursor: null, dataset });
  const wrapper = mountExplorer();
  await flushPromises();
  expect(getTransactions).toHaveBeenCalledTimes(2);
  expect(wrapper.text()).toContain("No activity in available history.");
  wrapper.unmount();
});

it("reports no activity in the selected period when older activity exists", async () => {
  getTransactions.mockImplementation(async (filters: { from: string }) =>
    filters.from === "2026-10-01"
      ? { items: [], nextCursor: null, dataset }
      : page(null),
  );
  const wrapper = mountExplorer();
  await flushPromises();
  expect(wrapper.text()).toContain("No activity in this period.");
  wrapper.unmount();
});

it("conceals a page until its revision matches the dashboard", async () => {
  getTransactions.mockResolvedValue({
    ...page(null),
    dataset: { ...dataset, customerRevision: 1 },
  });
  const wrapper = mountExplorer();
  await flushPromises();
  expect(wrapper.emitted("revisionMismatch")).toBeTruthy();
  expect(wrapper.findAll(".activity-table tbody tr")).toHaveLength(0);
  await wrapper.setProps({ dashboardRevision: 1 });
  await flushPromises();
  expect(wrapper.emitted("revisionAligned")).toBeTruthy();
  expect(wrapper.findAll(".activity-table tbody tr")).toHaveLength(1);
  wrapper.unmount();
});
