import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { getSession, logout, type Session } from "../../api/client";

export function useSessionLifecycle(
  resetFinancialState: () => void,
  onAuthenticated: () => void,
  onSignedOut: () => void,
) {
  const session = ref<Session | null>(null);
  const booting = ref(true);
  const sessionLocked = ref(false);
  const hidden = computed(() => sessionLocked.value);
  const status = ref("");
  let concealTimer: ReturnType<typeof setTimeout> | undefined;

  function clearSensitiveState() {
    session.value = null;
    sessionLocked.value = false;
    resetFinancialState();
  }

  watch(session, (current) => {
    if (concealTimer) clearTimeout(concealTimer);
    if (!current) return;
    const remaining = current.expiresAtEpochMillis - Date.now();
    concealTimer = setTimeout(
      () => {
        clearSensitiveState();
        status.value =
          "Your session ended. Sign in again to view your spending.";
      },
      Math.max(0, remaining),
    );
  });

  let sessionCheck = 0;
  async function validateSession() {
    const check = ++sessionCheck;
    sessionLocked.value = true;
    booting.value = true;
    try {
      const current = await getSession();
      if (check !== sessionCheck) return;
      if (!session.value || session.value.customerId !== current.customerId) {
        clearSensitiveState();
      }
      session.value = current;
      sessionLocked.value = false;
      onAuthenticated();
    } catch {
      if (check !== sessionCheck) return;
      clearSensitiveState();
    } finally {
      if (check === sessionCheck) booting.value = false;
    }
  }

  async function signOut() {
    sessionCheck++;
    sessionLocked.value = true;
    try {
      await logout();
    } catch {
      booting.value = false;
      status.value = "Sign out could not be confirmed. Try again.";
      return;
    }
    clearSensitiveState();
    onSignedOut();
    booting.value = false;
    status.value = "You have signed out.";
    channel?.postMessage("session-changed");
  }
  function signedIn(current: Session) {
    sessionCheck++;
    clearSensitiveState();
    session.value = current;
    sessionLocked.value = false;
    onAuthenticated();
    booting.value = false;
    status.value = "";
    channel?.postMessage("session-changed");
  }
  function onPageShow(event: PageTransitionEvent) {
    if (event.persisted) void validateSession();
  }
  function onVisibility() {
    if (document.visibilityState === "visible" && session.value)
      void validateSession();
  }
  const channel =
    typeof BroadcastChannel === "undefined"
      ? null
      : new BroadcastChannel("spending-insights-session");
  if (channel)
    channel.onmessage = () => {
      clearSensitiveState();
      void validateSession();
    };
  onMounted(() => {
    void validateSession();
    window.addEventListener("pageshow", onPageShow);
    document.addEventListener("visibilitychange", onVisibility);
  });
  onUnmounted(() => {
    sessionCheck++;
    if (concealTimer) clearTimeout(concealTimer);
    channel?.close();
    window.removeEventListener("pageshow", onPageShow);
    document.removeEventListener("visibilitychange", onVisibility);
  });
  return {
    session,
    booting,
    sessionLocked,
    hidden,
    status,
    clearSensitiveState,
    validateSession,
    signOut,
    signedIn,
  };
}
