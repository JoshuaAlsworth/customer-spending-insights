import { defineComponent } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import { getSession } from "../../api/client";
import type { Session } from "../../api/client";
import { useSessionLifecycle } from "./useSessionLifecycle";

vi.mock("../../api/client", () => ({ getSession: vi.fn(), logout: vi.fn() }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

function harness() {
  const reset = vi.fn();
  const authenticated = vi.fn();
  let lifecycle!: ReturnType<typeof useSessionLifecycle>;
  const wrapper = mount(
    defineComponent({
      setup() {
        lifecycle = useSessionLifecycle(reset, authenticated, vi.fn());
        return () => null;
      },
    }),
  );
  return { wrapper, lifecycle, reset, authenticated };
}
const customer = (id: string): Session => ({
  customerId: id,
  displayName: id,
  expiresAtEpochMillis: Date.now() + 900000,
});

it("locks on a cross-tab change and ignores the older session response", async () => {
  const channel = { onmessage: null as (() => void) | null, close: vi.fn() };
  vi.stubGlobal(
    "BroadcastChannel",
    vi.fn(function () {
      return channel;
    }),
  );
  let resolveOld!: (session: Session) => void;
  let resolveNew!: (session: Session) => void;
  vi.mocked(getSession)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveNew = resolve;
        }),
    );
  const { wrapper, lifecycle, reset, authenticated } = harness();
  channel.onmessage!();
  expect(reset).toHaveBeenCalledOnce();
  expect(lifecycle.sessionLocked.value).toBe(true);
  resolveNew(customer("new"));
  await flushPromises();
  resolveOld(customer("old"));
  await flushPromises();
  expect(lifecycle.session.value?.customerId).toBe("new");
  expect(authenticated).toHaveBeenCalledOnce();
  wrapper.unmount();
  expect(channel.close).toHaveBeenCalledOnce();
});

it("clears financial state at session expiry and releases its timer", async () => {
  vi.useFakeTimers();
  vi.mocked(getSession).mockResolvedValue(customer("current"));
  const { wrapper, lifecycle, reset } = harness();
  await flushPromises();
  reset.mockClear();
  await vi.advanceTimersByTimeAsync(900000);
  expect(lifecycle.session.value).toBeNull();
  expect(reset).toHaveBeenCalledOnce();
  expect(lifecycle.status.value).toContain("Your session ended");
  wrapper.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("ignores a session response after unmount", async () => {
  let resolveSession!: (session: Session) => void;
  vi.mocked(getSession).mockImplementation(
    () =>
      new Promise((resolve) => {
        resolveSession = resolve;
      }),
  );
  const { wrapper, lifecycle, authenticated } = harness();
  wrapper.unmount();
  resolveSession(customer("late"));
  await flushPromises();
  expect(lifecycle.session.value).toBeNull();
  expect(authenticated).not.toHaveBeenCalled();
});
