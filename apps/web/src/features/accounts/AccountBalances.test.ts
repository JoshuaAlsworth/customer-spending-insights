import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import type { AccountsResponse } from "../../api/client";
import AccountBalances from "./AccountBalances.vue";

const response: AccountsResponse = {
  accounts: [
    {
      id: "everyday",
      alias: "Everyday",
      accountKind: "EVERYDAY",
      maskedSuffix: "0042",
      postedBalanceMinor: "2215000",
    },
    {
      id: "savings",
      alias: "Savings",
      accountKind: "SAVINGS",
      maskedSuffix: "0019",
      postedBalanceMinor: "350000",
    },
  ],
  combinedPostedBalanceMinor: "2565000",
  balanceAsOfDate: "2026-10-31",
  currency: "ZAR",
  dataset: {
    datasetId: "fixture",
    instanceEpoch: "epoch",
    customerRevision: 0,
    referenceDate: "2026-10-31",
  },
};

it("shows exact F-13 balances and uses native account selection", async () => {
  const wrapper = mount(AccountBalances, {
    props: { response, accountId: "", hidden: false },
  });
  expect(wrapper.get("h2").text()).toBe("Your accounts");
  expect(wrapper.text()).toContain("R25,650.00");
  expect(wrapper.text()).toContain("R22,150.00");
  expect(wrapper.text()).toContain("R3,500.00");
  expect(wrapper.text()).toContain("31 Oct 2026");
  expect(wrapper.findAll('input[type="radio"]')).toHaveLength(3);
  await wrapper.get('input[value="savings"]').setValue();
  expect(wrapper.emitted("update:accountId")?.[0]).toEqual(["savings"]);
  await wrapper.get('input[value=""]').setValue();
  expect(wrapper.emitted("update:accountId")?.[1]).toEqual([""]);
});

it("shows the selected fixed-date balance on Transactions with one shared selector", async () => {
  const wrapper = mount(AccountBalances, {
    props: { response, accountId: "everyday", hidden: false, compact: true },
  });
  expect(wrapper.text()).toContain("R22,150.00");
  expect(wrapper.get(".account-button").text()).not.toContain("R25,650.00");
  expect(wrapper.findAll('input[type="radio"]')).toHaveLength(3);
  await wrapper.get('input[value="savings"]').setValue();
  expect(wrapper.emitted("update:accountId")?.[0]).toEqual(["savings"]);
});

it("preserves signed negatives and genuine zero while masking every amount", async () => {
  const edge: AccountsResponse = {
    ...response,
    accounts: [
      { ...response.accounts[0], postedBalanceMinor: "-5000" },
      { ...response.accounts[1], postedBalanceMinor: "0" },
    ],
    combinedPostedBalanceMinor: "-5000",
  };
  const wrapper = mount(AccountBalances, {
    props: { response: edge, accountId: "", hidden: false },
  });
  expect(wrapper.text()).toContain("−R50.00");
  expect(wrapper.text()).toContain("R0.00");
  await wrapper.setProps({ hidden: true });
  expect(wrapper.text()).not.toContain("R50.00");
  expect(wrapper.text()).not.toContain("R0.00");
  expect(
    wrapper.findAll(".account-option-amount").map((item) => item.text()),
  ).toEqual(["••••", "••••", "••••"]);
  wrapper.unmount();
});

it("distinguishes no eligible accounts from a zero balance and supports four accounts", () => {
  const empty = mount(AccountBalances, {
    props: {
      response: { ...response, accounts: [], combinedPostedBalanceMinor: null },
      accountId: "",
      hidden: false,
    },
  });
  expect(empty.text()).toContain("A posted balance cannot be shown");
  expect(empty.text()).not.toContain("R0.00");
  expect(empty.findAll('input[type="radio"]')).toHaveLength(0);
  empty.unmount();

  const four = mount(AccountBalances, {
    props: {
      response: {
        ...response,
        accounts: [
          ...response.accounts,
          { ...response.accounts[0], id: "secondary", alias: "Secondary" },
          { ...response.accounts[1], id: "additional", alias: "Additional" },
        ],
      },
      accountId: "",
      hidden: false,
    },
  });
  expect(four.findAll('input[type="radio"]')).toHaveLength(5);
  four.unmount();
});
