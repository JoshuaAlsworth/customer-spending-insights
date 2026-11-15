import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import AccountBalances from "./AccountBalances.vue";
import type { AccountsResponse } from "../../api/client";

const response = {
  accounts: [
    {
      id: "everyday",
      alias: "Everyday",
      maskedSuffix: "0042",
      accountKind: "EVERYDAY",
      postedBalanceMinor: "1459950",
    },
    {
      id: "savings",
      alias: "Savings",
      maskedSuffix: "0043",
      accountKind: "SAVINGS",
      postedBalanceMinor: "50000",
    },
  ],
  combinedPostedBalanceMinor: "1509950",
  balanceAsOfDate: "2026-10-31",
  currency: "ZAR",
  dataset: {
    datasetId: "fixture",
    instanceEpoch: "epoch",
    customerRevision: 0,
    referenceDate: "2026-10-31",
  },
} as AccountsResponse;

it("uses an anchored account list with focus and outside-click dismissal", async () => {
  const wrapper = mount(AccountBalances, {
    attachTo: document.body,
    props: { response, accountId: "everyday", hidden: false },
  });
  const picker = wrapper.get(".account-picker").element as HTMLDetailsElement;
  picker.open = true;
  expect(wrapper.find(".picker-backdrop").exists()).toBe(false);
  expect(wrapper.find(".picker-sheet-heading").exists()).toBe(false);
  expect(wrapper.get(".account-options").text()).toContain("R14,599.50");
  await wrapper.get('input[value="savings"]').setValue();
  expect(wrapper.emitted("update:accountId")?.[0]).toEqual(["savings"]);
  expect(picker.open).toBe(false);
  expect(document.activeElement).toBe(wrapper.get("summary").element);
  picker.open = true;
  document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
  expect(picker.open).toBe(false);
  wrapper.unmount();
});
