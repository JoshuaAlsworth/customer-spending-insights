<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import AppHeader from "./app/AppHeader.vue";
import SignIn from "./features/auth/SignIn.vue";
import ScopeControls from "./features/accounts/ScopeControls.vue";
import OverviewView from "./features/overview/OverviewView.vue";
import {
  ApiError,
  getAccounts,
  getDashboard,
  getSession,
  logout,
  type Session,
} from "./api/client";

const client = useQueryClient();
const session = ref<Session | null>(null);
const booting = ref(true);
const refreshing = ref(false);
const generation = ref(0);
const privacyHidden = ref(false);
const sessionLocked = ref(false);
const hidden = computed(() => privacyHidden.value || sessionLocked.value);
const view = ref<"overview" | "transactions">(
  location.hash === "#transactions" ? "transactions" : "overview",
);
const selectedAccount = ref("");
const from = ref("");
const to = ref("");
const periodSet = ref(false);
const status = ref("");
const accountIds = computed(() =>
  selectedAccount.value ? [selectedAccount.value] : [],
);
let concealTimer: ReturnType<typeof setTimeout> | undefined;

function clearSensitiveState() {
  generation.value++;
  session.value = null;
  selectedAccount.value = "";
  from.value = "";
  to.value = "";
  periodSet.value = false;
  privacyHidden.value = false;
  sessionLocked.value = false;
  client.clear();
}

const accounts = useQuery({
  queryKey: computed(() => [
    "accounts",
    session.value?.customerId,
    generation.value,
  ]),
  queryFn: ({ signal }: { signal: AbortSignal }) => getAccounts(signal),
  enabled: computed(() => !!session.value),
  staleTime: 60_000,
  retry: false,
  refetchOnWindowFocus: false,
});

const dashboard = useQuery({
  queryKey: computed(() => [
    "dashboard",
    session.value?.customerId,
    generation.value,
    selectedAccount.value,
    periodSet.value ? from.value : "default",
    periodSet.value ? to.value : "default",
  ]),
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    getDashboard(
      accountIds.value,
      periodSet.value ? from.value : undefined,
      periodSet.value ? to.value : undefined,
      signal,
    ),
  enabled: computed(
    () =>
      !!session.value &&
      accounts.isSuccess.value &&
      (accounts.data.value?.accounts.length ?? 0) > 0,
  ),
  staleTime: 60_000,
  retry: false,
  refetchOnWindowFocus: false,
});

watch(
  () => [accounts.error.value, dashboard.error.value],
  (errors) => {
    if (
      errors.some((error) => error instanceof ApiError && error.status === 401)
    ) {
      clearSensitiveState();
      status.value = "Your session ended. Sign in again to view your spending.";
    }
  },
);
watch(
  () => session.value?.customerId,
  () => {
    selectedAccount.value = "";
  },
);
watch(
  () => dashboard.data.value?.scope,
  (scope) => {
    if (scope && !periodSet.value) {
      from.value = scope.from;
      to.value = scope.to;
    }
  },
);
watch(session, (current) => {
  if (concealTimer) clearTimeout(concealTimer);
  if (!current) return;
  const remaining = current.expiresAtEpochMillis - Date.now();
  concealTimer = setTimeout(
    () => {
      clearSensitiveState();
      status.value = "Your session ended. Sign in again to view your spending.";
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
  booting.value = false;
  status.value = "You have signed out.";
  channel?.postMessage("session-changed");
}
function signedIn(current: Session) {
  sessionCheck++;
  clearSensitiveState();
  session.value = current;
  sessionLocked.value = false;
  booting.value = false;
  status.value = "";
  channel?.postMessage("session-changed");
}
function toggleAmounts() {
  if (!sessionLocked.value) privacyHidden.value = !privacyHidden.value;
}
async function refresh() {
  if (refreshing.value) return;
  status.value = "";
  refreshing.value = true;
  try {
    await Promise.all([accounts.refetch(), dashboard.refetch()]);
  } finally {
    refreshing.value = false;
  }
}
function setPeriod(period: { from: string; to: string }) {
  from.value = period.from;
  to.value = period.to;
  periodSet.value = true;
}
function setView(next: "overview" | "transactions") {
  view.value = next;
  location.hash = next;
}
function onHashChange() {
  view.value = location.hash === "#transactions" ? "transactions" : "overview";
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
  window.addEventListener("hashchange", onHashChange);
  window.addEventListener("pageshow", onPageShow);
  document.addEventListener("visibilitychange", onVisibility);
});
onUnmounted(() => {
  if (concealTimer) clearTimeout(concealTimer);
  channel?.close();
  window.removeEventListener("hashchange", onHashChange);
  window.removeEventListener("pageshow", onPageShow);
  document.removeEventListener("visibilitychange", onVisibility);
});
</script>

<template>
  <AppHeader
    :signed-in="!!session"
    :view="view"
    :hidden="hidden"
    :session-locked="sessionLocked"
    :display-name="session?.displayName ?? ''"
    @navigate="setView"
    @toggle-hidden="toggleAmounts"
    @refresh="refresh"
    @sign-out="signOut"
  />
  <main v-if="booting" class="signed-out">
    <p role="status">Checking your session…</p>
  </main>
  <SignIn v-else-if="!session" :status="status" @signed-in="signedIn" />
  <main v-else class="shell">
    <p v-if="status" class="state-panel error" role="alert">
      {{ status }}
    </p>
    <button
      v-if="sessionLocked"
      type="button"
      class="button secondary"
      @click="validateSession"
    >
      Check session
    </button>
    <div class="page-heading">
      <h1>{{ view === "overview" ? "Your spending" : "Transactions" }}</h1>
      <span
        v-if="!sessionLocked && dashboard.data.value?.dataset.referenceDate"
        class="data-through"
        >Data through {{ dashboard.data.value.dataset.referenceDate }}</span
      >
    </div>
    <ScopeControls
      v-if="accounts.data.value && dashboard.data.value && !sessionLocked"
      v-model:account-id="selectedAccount"
      :from="from"
      :to="to"
      :accounts="accounts.data.value.accounts"
      :reference-date="dashboard.data.value.dataset.referenceDate"
      @apply-period="setPeriod"
    />
    <p v-if="accounts.isPending.value" class="state-panel" role="status">
      Loading your accounts…
    </p>
    <div
      v-else-if="accounts.isError.value"
      class="state-panel error"
      role="alert"
    >
      Accounts could not be loaded.
      <button type="button" @click="accounts.refetch()">Retry</button>
    </div>
    <p
      v-else-if="accounts.data.value?.accounts.length === 0"
      class="state-panel"
    >
      No accounts are available for this customer.
    </p>
    <template v-else-if="sessionLocked">
      <p class="state-panel" role="status">
        Spending is locked until your session is checked.
      </p>
    </template>
    <template v-else-if="view === 'overview'">
      <p v-if="refreshing" class="state-panel" role="status">
        Refreshing your spending…
      </p>
      <p
        v-else-if="dashboard.isPending.value"
        class="state-panel"
        role="status"
      >
        Loading your spending…
      </p>
      <div
        v-else-if="dashboard.isError.value"
        class="state-panel error"
        role="alert"
      >
        Spending data could not be loaded.
        <button type="button" @click="dashboard.refetch()">Retry</button>
      </div>
      <OverviewView
        v-else-if="dashboard.data.value"
        :dashboard="dashboard.data.value"
        :hidden="hidden"
        @transactions="setView('transactions')"
      />
    </template>
    <section v-else class="state-panel" aria-labelledby="transactions-title">
      <h2 id="transactions-title">Transaction history</h2>
      <p>
        Transaction exploration is being built. Your account and reporting
        period will carry through when it is available.
      </p>
    </section>
  </main>
  <nav
    v-if="session && !sessionLocked"
    class="bottom-nav"
    aria-label="Mobile navigation"
  >
    <button
      type="button"
      :aria-current="view === 'overview' ? 'page' : undefined"
      @click="setView('overview')"
    >
      Overview
    </button>
    <button
      type="button"
      :aria-current="view === 'transactions' ? 'page' : undefined"
      @click="setView('transactions')"
    >
      Transactions
    </button>
  </nav>
</template>
