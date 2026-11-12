import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import ScopeControls from "./ScopeControls.vue";

it("rejects a period after the dataset reference date and accepts its last day", async () => {
  const wrapper = mount(ScopeControls, {
    props: {
      accounts: [],
      accountId: "",
      from: "2026-10-01",
      to: "2026-10-31",
      referenceDate: "2026-10-31",
    },
  });
  await wrapper.get("#to").setValue("2026-11-01");
  await wrapper.get("form").trigger("submit");
  expect(wrapper.emitted("apply-period")).toBeUndefined();
  expect(wrapper.get(".field-error").text()).toContain("2026-10-31");
  await wrapper.get("#to").setValue("2026-10-31");
  await wrapper.get("form").trigger("submit");
  expect(wrapper.emitted("apply-period")?.[0]).toEqual([
    { from: "2026-10-01", to: "2026-10-31" },
  ]);
  wrapper.unmount();
});
