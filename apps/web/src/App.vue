<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import AppHeader from "./app/AppHeader.vue";
import SignIn from "./features/auth/SignIn.vue";
import ScopeControls from "./features/accounts/ScopeControls.vue";
import AccountBalances from "./features/accounts/AccountBalances.vue";
import OverviewView from "./features/overview/OverviewView.vue";
import TransactionExplorer from "./features/transactions/TransactionExplorer.vue";
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
const reconciliationAttempted = ref(false);
const reconciling = ref(false);
const generation = ref(0);
const sessionLocked = ref(false);
const hidden = computed(() => sessionLocked.value);
const view = ref<"overview" | "transactions">(
  location.hash.startsWith("#transactions") ? "transactions" : "overview",
);
const selectedAccount = ref("");
const accountSelectionInitialized = ref(false);
const transactionExplorer = ref<InstanceType<
  typeof TransactionExplorer
> | null>(null);
const detailId = ref<string | null>(parseDetail());
function parseDetail() {
  const match = location.hash.match(/^#transactions\/(au|pe)_[A-Za-z0-9_-]+$/);
  return match ? location.hash.slice("#transactions/".length) : null;
}
function openDetail(id: string) {
  detailId.value = id;
  location.hash = `transactions/${id}`;
}
function closeDetail() {
  detailId.value = null;
  location.hash = "transactions";
}
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
  accountSelectionInitialized.value = false;
  detailId.value = null;
  from.value = "";
  to.value = "";
  periodSet.value = false;
  sessionLocked.value = false;
  reconciliationAttempted.value = false;
  reconciling.value = false;
  refreshing.value = false;
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
const snapshotMismatch = computed(() => {
  const accountDataset = accounts.data.value?.dataset;
  const analysisDataset = dashboard.data.value?.dataset;
  return (
    !!accountDataset &&
    !!analysisDataset &&
    (accountDataset.datasetId !== analysisDataset.datasetId ||
      accountDataset.instanceEpoch !== analysisDataset.instanceEpoch ||
      accountDataset.customerRevision !== analysisDataset.customerRevision ||
      accountDataset.referenceDate !== analysisDataset.referenceDate)
  );
});

watch(
  () => accounts.data.value?.accounts,
  (owned) => {
    if (owned && !accountSelectionInitialized.value) {
      selectedAccount.value = owned[0]?.id ?? "";
      accountSelectionInitialized.value = true;
      return;
    }
    if (
      owned &&
      selectedAccount.value &&
      !owned.some((item) => item.id === selectedAccount.value)
    )
      selectedAccount.value = "";
  },
  { flush: "sync" },
);
watch(
  [
    snapshotMismatch,
    () => accounts.isFetching.value,
    () => dashboard.isFetching.value,
    reconciling,
    refreshing,
  ],
  ([
    mismatch,
    accountsFetching,
    dashboardFetching,
    isReconciling,
    isRefreshing,
  ]) => {
    if (
      mismatch &&
      !accountsFetching &&
      !dashboardFetching &&
      !isReconciling &&
      !isRefreshing
    )
      void reconcileActivity();
  },
);

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
async function refresh() {
  if (!session.value || sessionLocked.value || refreshing.value) return;
  const customerId = session.value.customerId;
  const currentGeneration = generation.value;
  const scope = () =>
    `${selectedAccount.value}|${periodSet.value}|${from.value}|${to.value}`;
  const currentScope = scope();
  const stillCurrent = () =>
    session.value?.customerId === customerId &&
    generation.value === currentGeneration &&
    !sessionLocked.value;
  const failed = (error: unknown, message: string) => {
    if (error instanceof ApiError && error.status === 401) {
      clearSensitiveState();
      status.value = "Your session ended. Sign in again to view your spending.";
    } else status.value = message;
  };
  refreshing.value = true;
  status.value = "";
  transactionExplorer.value?.resetPagination();
  try {
    await Promise.all([
      client.cancelQueries({
        queryKey: ["transactions", customerId, currentGeneration],
      }),
      client.cancelQueries({
        queryKey: ["recent-transactions", customerId, currentGeneration],
      }),
      client.cancelQueries({
        queryKey: [
          "transaction-history-presence",
          customerId,
          currentGeneration,
        ],
      }),
      client.cancelQueries({
        queryKey: ["transaction-detail", customerId, currentGeneration],
      }),
    ]);
    const accountResult = await accounts.refetch();
    if (!stillCurrent()) return;
    if (accountResult.isError) {
      failed(
        accountResult.error,
        "Account balances could not be refreshed. Try again.",
      );
      return;
    }
    if (scope() !== currentScope) return;
    if (accountResult.data?.accounts.length) {
      const dashboardResult = await dashboard.refetch();
      if (!stillCurrent()) return;
      if (dashboardResult.isError) {
        failed(
          dashboardResult.error,
          "Spending data could not be refreshed. Try again.",
        );
        return;
      }
      if (scope() !== currentScope) return;
      if (snapshotMismatch.value) {
        status.value =
          "Account balances and spending did not align. Try Refresh again.";
        return;
      }
    }
    await Promise.all([
      client.invalidateQueries({
        queryKey: ["transactions", customerId, currentGeneration],
      }),
      client.invalidateQueries({
        queryKey: ["recent-transactions", customerId, currentGeneration],
      }),
      client.invalidateQueries({
        queryKey: [
          "transaction-history-presence",
          customerId,
          currentGeneration,
        ],
      }),
      client.invalidateQueries({
        queryKey: ["transaction-detail", customerId, currentGeneration],
      }),
    ]);
  } catch (error) {
    if (stillCurrent())
      failed(error, "Activity could not be refreshed. Try again.");
  } finally {
    if (
      session.value?.customerId === customerId &&
      generation.value === currentGeneration
    )
      refreshing.value = false;
  }
}
watch([selectedAccount, from, to], () => {
  reconciliationAttempted.value = false;
});
async function reconcileActivity() {
  if (
    !session.value ||
    sessionLocked.value ||
    reconciling.value ||
    refreshing.value
  )
    return;
  if (reconciliationAttempted.value) {
    status.value =
      "Updated activity is available. Use Refresh to align your view.";
    return;
  }
  reconciliationAttempted.value = true;
  reconciling.value = true;
  try {
    const accountResult = await accounts.refetch();
    if (accountResult.isError) {
      status.value =
        "Updated account balances are unavailable. Use Refresh to retry.";
      return;
    }
    if (accountResult.data?.accounts.length) await dashboard.refetch();
    await Promise.all([
      client.invalidateQueries({ queryKey: ["transactions"] }),
      client.invalidateQueries({ queryKey: ["recent-transactions"] }),
      client.invalidateQueries({ queryKey: ["transaction-history-presence"] }),
    ]);
  } finally {
    reconciling.value = false;
  }
}
function activityAligned() {
  if (
    !snapshotMismatch.value &&
    status.value ===
      "Updated activity is available. Use Refresh to align your view."
  )
    status.value = "";
}
function setPeriod(period: { from: string; to: string }) {
  from.value = period.from;
  to.value = period.to;
  periodSet.value = true;
}
function setView(next: "overview" | "transactions") {
  view.value = next;
  detailId.value = null;
  location.hash = next;
}
function openCategory(code: string) {
  transactionExplorer.value?.applyCategory(code);
  setView("transactions");
}
function onHashChange() {
  view.value = location.hash.startsWith("#transactions")
    ? "transactions"
    : "overview";
  detailId.value = parseDetail();
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
    v-if="session || booting"
    :signed-in="!!session"
    :view="view"
    :session-locked="sessionLocked"
    :refreshing="refreshing"
    @navigate="setView"
    @refresh="refresh"
    @sign-out="signOut"
  />
  <main v-if="booting" class="signed-out">
    <p role="status">Checking your session…</p>
  </main>
  <SignIn v-else-if="!session" :status="status" @signed-in="signedIn" />
  <main v-else id="dashboard" class="shell">
    <p v-if="refreshing" class="sr-only" role="status">
      Refreshing account balances and spending…
    </p>
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
    <div class="page-top">
      <div class="page-heading">
        <h1 tabindex="-1">
          {{ view === "overview" ? "Your spending" : "Transactions" }}
        </h1>
        <span
          v-if="
            !sessionLocked &&
            !snapshotMismatch &&
            dashboard.data.value?.dataset.referenceDate
          "
          class="data-through"
          >Data through {{ dashboard.data.value.dataset.referenceDate }}</span
        >
      </div>
      <p v-if="sessionLocked" class="state-panel" role="status">
        Spending is locked until your session is checked.
      </p>
      <p v-else-if="accounts.isPending.value" class="state-panel" role="status">
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
      <template v-else-if="accounts.data.value">
        <div class="global-filters">
          <p v-if="snapshotMismatch" class="state-panel" role="status">
            Account balances and spending are updating. Use Refresh if this
            continues.
          </p>
          <AccountBalances
            v-else
            v-model:account-id="selectedAccount"
            :response="accounts.data.value"
            :hidden="hidden"
            :compact="view === 'transactions'"
          />
          <ScopeControls
            v-if="accounts.data.value.accounts.length && !snapshotMismatch"
            :from="from"
            :to="to"
            :reference-date="accounts.data.value.dataset.referenceDate"
            :label="
              view === 'transactions' ? 'Transaction dates' : 'Spending period'
            "
            @apply-period="setPeriod"
          />
        </div>
      </template>
    </div>
    <div class="content-stack">
      <template
        v-if="
          !sessionLocked &&
          accounts.isSuccess.value &&
          accounts.data.value?.accounts.length &&
          view === 'overview' &&
          !snapshotMismatch
        "
      >
        <p v-if="dashboard.isPending.value" class="state-panel" role="status">
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
          :customer-id="session.customerId"
          :account-ids="accountIds"
          :generation="generation"
          :reconciling="reconciling"
          @revision-aligned="activityAligned"
          @revision-mismatch="reconcileActivity"
          @unauthorized="clearSensitiveState"
          @transactions="setView('transactions')"
          @open="openDetail"
          @category="openCategory"
        />
      </template>
      <p
        v-if="
          view === 'transactions' && dashboard.isPending.value && !sessionLocked
        "
        class="state-panel"
        role="status"
      >
        Loading your spending scope…
      </p>
      <div
        v-if="
          view === 'transactions' && dashboard.isError.value && !sessionLocked
        "
        class="state-panel error"
        role="alert"
      >
        Spending scope could not be loaded.
        <button type="button" @click="dashboard.refetch()">Retry</button>
      </div>
      <TransactionExplorer
        v-if="
          dashboard.data.value &&
          !sessionLocked &&
          accounts.data.value?.accounts.length
        "
        v-show="
          view === 'transactions' &&
          !snapshotMismatch &&
          !accounts.isError.value &&
          !dashboard.isError.value
        "
        ref="transactionExplorer"
        :customer-id="session.customerId"
        :account-ids="accountIds"
        :from="from"
        :to="to"
        :hidden="hidden"
        :active="
          view === 'transactions' &&
          !sessionLocked &&
          !refreshing &&
          !snapshotMismatch &&
          !accounts.isError.value &&
          !dashboard.isError.value
        "
        :generation="generation"
        :dataset-epoch="dashboard.data.value.dataset.instanceEpoch"
        :dashboard-revision="dashboard.data.value.dataset.customerRevision"
        :reconciling="reconciling"
        :reference-date="dashboard.data.value.dataset.referenceDate"
        :detail-id="detailId"
        :accounts="accounts.data.value?.accounts"
        @open="openDetail"
        @close="closeDetail"
        @unauthorized="clearSensitiveState"
        @revision-mismatch="reconcileActivity"
        @revision-aligned="activityAligned"
      />
    </div>
  </main>
</template>
