import { mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import App from "./App.vue";

it("renders the bootstrap page without requesting operational diagnostics", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const wrapper = mount(App);
  expect(wrapper.get("h1").text()).toBe("Customer Spending Insights");
  expect(wrapper.text()).toContain("Application setup is in progress.");
  expect(fetch).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});
