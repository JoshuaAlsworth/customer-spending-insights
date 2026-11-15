import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import SignIn from "./SignIn.vue";

it("focuses the first invalid sign-in field and gives both fields form names", async () => {
  const wrapper = mount(SignIn, {
    attachTo: document.body,
    props: { status: "" },
  });

  await wrapper.get("form").trigger("submit");
  expect(document.activeElement).toBe(wrapper.get("#login-id").element);
  expect(wrapper.get("#login-id").attributes("name")).toBe("username");

  await wrapper.get("#login-id").setValue("synthetic-00007");
  await wrapper.get("form").trigger("submit");
  expect(document.activeElement).toBe(wrapper.get("#password").element);
  expect(wrapper.get("#password").attributes("name")).toBe("password");
  expect(wrapper.emitted("signed-in")).toBeUndefined();

  wrapper.unmount();
});
