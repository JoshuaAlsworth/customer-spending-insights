import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import AppHeader from "./AppHeader.vue";

it("keeps mobile search accessible and closes the account menu outside", async () => {
  const wrapper = mount(AppHeader, {
    props: {
      signedIn: true,
      view: "transactions",
      sessionLocked: false,
      searchOpen: false,
    },
  });
  expect(wrapper.find(".refresh-button").exists()).toBe(false);
  expect(wrapper.get(".mobile-header-search").attributes("aria-expanded")).toBe(
    "false",
  );
  await wrapper.get(".mobile-header-search").trigger("click");
  expect(wrapper.emitted("search")).toHaveLength(1);
  await wrapper.setProps({ searchOpen: true });
  expect(wrapper.get(".mobile-header-search").attributes("aria-expanded")).toBe(
    "true",
  );
  expect(wrapper.get(".profile-popover").text()).toContain("Sign out");
  expect(wrapper.get(".profile-popover").text()).not.toContain("Refresh");
  const profileMenu = wrapper.get(".profile-menu")
    .element as HTMLDetailsElement;
  profileMenu.open = true;
  document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
  expect(profileMenu.open).toBe(false);
  wrapper.unmount();
});
