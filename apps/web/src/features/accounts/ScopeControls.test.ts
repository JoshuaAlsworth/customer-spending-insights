import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import ScopeControls from "./ScopeControls.vue";

it("rejects a period after the dataset reference date and accepts its last day", async () => {
  const wrapper = mount(ScopeControls, {
    props: {
      from: "2026-10-01",
      to: "2026-10-31",
      referenceDate: "2026-10-31",
    },
  });
  await wrapper.get(".period-popover > button:last-of-type").trigger("click");
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

it("shows the reference month and crosses the year boundary for the previous month", async () => {
  const wrapper = mount(ScopeControls, {
    props: {
      from: "2027-01-01",
      to: "2027-01-15",
      referenceDate: "2027-01-15",
    },
  });
  const choices = wrapper.findAll(".period-popover > button");
  expect(choices[0]?.text()).toBe("January 2027");
  expect(choices[1]?.text()).toBe("December 2026");
  expect(choices[0]?.attributes("aria-pressed")).toBe("true");
  expect(choices[1]?.attributes("aria-pressed")).toBe("false");
  await choices[1]?.trigger("click");
  expect(wrapper.emitted("apply-period")?.[0]).toEqual([
    { from: "2026-12-01", to: "2026-12-31" },
  ]);
  await wrapper.setProps({ from: "2026-12-01", to: "2026-12-31" });
  expect(choices[1]?.attributes("aria-pressed")).toBe("true");
  wrapper.unmount();
});

it("keeps custom dates in the period dropdown with keyboard focus", async () => {
  const wrapper = mount(ScopeControls, {
    attachTo: document.body,
    props: {
      from: "2026-10-01",
      to: "2026-10-31",
      referenceDate: "2026-10-31",
    },
  });
  const picker = wrapper.get(".period-picker").element as HTMLDetailsElement;
  picker.open = true;
  await wrapper.get(".period-popover > button:last-of-type").trigger("click");
  expect(document.activeElement).toBe(wrapper.get("#from").element);
  expect(wrapper.find(".picker-backdrop").exists()).toBe(false);
  await wrapper.get("#from").trigger("keydown", { key: "Escape" });
  expect(picker.open).toBe(false);
  expect(document.activeElement).toBe(wrapper.get("summary").element);
  wrapper.unmount();
});
