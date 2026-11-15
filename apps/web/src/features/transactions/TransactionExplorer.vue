<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useQuery } from "@tanstack/vue-query";
import {
  ApiError,
  getTransactions,
  getTransaction,
  type Activity,
  type Account,
  type CategoryCode,
} from "../../api/client";
import { money } from "../../utils/money";
import categoryPolicy from "../../../../../contracts/finance/categories.json";

const props = defineProps<{
  customerId: string;
  accountIds: string[];
  from: string;
  to: string;
  hidden: boolean;
  mobileSearchOpen?: boolean;
  active: boolean;
  generation: number;
  datasetEpoch: string;
  dashboardRevision: number;
  reconciling?: boolean;
  referenceDate: string;
  detailId: string | null;
  accounts?: Account[];
}>();
const emit = defineEmits<{
  open: [id: string];
  close: [];
  unauthorized: [];
  revisionMismatch: [];
  revisionAligned: [];
}>();
const searchInput = ref("");
const searchField = ref<HTMLInputElement | null>(null);
const filterMenu = ref<HTMLDetailsElement | null>(null);
function closeFilterOutside(event: PointerEvent) {
  if (
    filterMenu.value?.open &&
    !filterMenu.value.contains(event.target as Node)
  )
    filterMenu.value.open = false;
}
function closeFilterOnEscape(event: KeyboardEvent) {
  if (event.key === "Escape" && filterMenu.value?.open) {
    filterMenu.value.open = false;
    filterMenu.value.querySelector("summary")?.focus();
  }
}
onMounted(() => {
  document.addEventListener("pointerdown", closeFilterOutside);
  document.addEventListener("keydown", closeFilterOnEscape);
});
const search = ref("");
const status = ref<"ALL" | "PENDING" | "POSTED" | "CANCELLED">("ALL");
const category = ref<CategoryCode | "">("");
const pageCursors = ref<(string | undefined)[]>([undefined]);
const page = ref(0);
const timer = ref<ReturnType<typeof setTimeout>>();
const categories: CategoryCode[] = [
  "HOUSING_UTILITIES",
  "GROCERIES",
  "TRANSPORT_FUEL",
  "FOOD_DINING",
  "SHOPPING",
  "HEALTH",
  "SUBSCRIPTIONS_COMMS",
  "INSURANCE_FIN_SERVICES",
  "EDUCATION",
  "ENTERTAINMENT_LEISURE",
  "CASH_WITHDRAWALS",
  "MONEY_SENT",
  "BANK_FEES",
  "UNCATEGORIZED",
];
function applyCategory(code: string) {
  if (!categories.includes(code as CategoryCode)) return;
  category.value = code as CategoryCode;
  pageCursors.value = [undefined];
  page.value = 0;
}
function resetPagination() {
  pageCursors.value = [undefined];
  page.value = 0;
}
defineExpose({ applyCategory, resetPagination });
const label = (value: string) =>
  value in categoryPolicy.categories
    ? categoryPolicy.categories[value as CategoryCode]
    : value
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/^./, (char) => char.toUpperCase());
const amount = (item: Activity) =>
  props.hidden
    ? "••••"
    : money(
        item.recordKind === "AUTHORIZATION"
          ? `-${item.authorizedAmountMinor}`
          : item.amountMinor,
        true,
      );
const date = (item: Activity) =>
  new Date(item.postedAt ?? item.occurredAt).toLocaleDateString("en-ZA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Johannesburg",
  });
const detailDate = (value: string) =>
  new Date(value).toLocaleDateString("en-ZA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Johannesburg",
  });
const accountName = (item: Activity) => {
  const account = props.accounts?.find((entry) => entry.id === item.accountId);
  return `${account?.alias ?? "Account"} · •• ${item.maskedSuffix}`;
};
const transactionQueryKey = computed(() => [
  "transactions",
  props.customerId,
  props.generation,
  props.datasetEpoch,
  props.accountIds.join(","),
  props.from,
  props.to,
  status.value,
  category.value,
  search.value,
  pageCursors.value[page.value],
]);
const query = useQuery({
  queryKey: transactionQueryKey,
  queryFn: ({ signal }) =>
    getTransactions(
      {
        accountIds: props.accountIds,
        from: props.from,
        to: props.to,
        status: status.value,
        category: category.value || undefined,
        search: search.value || undefined,
        cursor: pageCursors.value[page.value],
      },
      signal,
    ),
  enabled: computed(
    () => props.active && !!props.customerId && !!props.from && !!props.to,
  ),
  retry: false,
  staleTime: 0,
  refetchOnWindowFocus: false,
  // Reuse rows only when the customer, scope, filters, and cursor still match.
  placeholderData: (previousData, previousQuery) =>
    previousQuery?.queryKey.every(
      (part, index) => index === 9 || part === transactionQueryKey.value[index],
    )
      ? previousData
      : undefined,
});
function availableHistoryStart(referenceDate: string) {
  const [year, month, day] = referenceDate.split("-").map(Number);
  const priorYear = year - 3;
  const lastDay = new Date(Date.UTC(priorYear, month, 0)).getUTCDate();
  return new Date(Date.UTC(priorYear, month - 1, Math.min(day, lastDay) + 1))
    .toISOString()
    .slice(0, 10);
}
const history = useQuery({
  queryKey: computed(() => [
    "transaction-history-presence",
    props.customerId,
    props.generation,
    props.datasetEpoch,
    props.accountIds.join(","),
    props.referenceDate,
  ]),
  queryFn: ({ signal }) =>
    getTransactions(
      {
        accountIds: props.accountIds,
        from: availableHistoryStart(props.referenceDate),
        to: props.referenceDate,
        limit: 1,
      },
      signal,
    ),
  enabled: computed(
    () =>
      props.active &&
      query.isSuccess.value &&
      query.data.value?.items.length === 0 &&
      page.value === 0 &&
      status.value === "ALL" &&
      !category.value &&
      !search.value,
  ),
  retry: false,
  refetchOnWindowFocus: false,
});
const detail = useQuery({
  queryKey: computed(() => [
    "transaction-detail",
    props.customerId,
    props.generation,
    props.datasetEpoch,
    props.detailId,
  ]),
  queryFn: ({ signal }) => getTransaction(props.detailId!, signal),
  enabled: computed(() => props.active && !!props.detailId),
  retry: false,
  refetchOnWindowFocus: false,
});
const queryMismatch = computed(
  () =>
    !!query.data.value &&
    (query.data.value.dataset.instanceEpoch !== props.datasetEpoch ||
      query.data.value.dataset.customerRevision !== props.dashboardRevision),
);
const rows = computed(() => query.data.value?.items ?? []);
const groupedRows = computed(() =>
  (["PENDING", "POSTED", "CANCELLED"] as const)
    .map((entry) => ({
      status: entry,
      title: `${label(entry)} transactions`,
      items: rows.value.filter((item) => item.status === entry),
    }))
    .filter((group) => group.items.length),
);
const normalizeSearch = (value: string) =>
  value
    .replace(/^\p{White_Space}+|\p{White_Space}+$/gu, "")
    .replace(/\p{White_Space}+/gu, " ");
const normalizedSearch = computed(() => normalizeSearch(searchInput.value));
const searchCodePoints = computed(() => [...normalizedSearch.value].length);
const validSearch = computed(() =>
  searchCodePoints.value === 1 ? "" : normalizedSearch.value,
);
const searchUpdating = computed(() => validSearch.value !== search.value);
const searchError = computed(() =>
  searchCodePoints.value > 100 ? "Search is limited to 100 characters." : "",
);
watch(
  () => props.mobileSearchOpen,
  async (open) => {
    if (open) {
      await nextTick();
      searchField.value?.focus();
    } else {
      searchInput.value = "";
      search.value = "";
    }
  },
);
watch(searchInput, () => {
  if (timer.value) clearTimeout(timer.value);
  if (searchError.value) return;
  timer.value = setTimeout(() => {
    search.value = validSearch.value;
  }, 300);
});
watch(
  [
    () => props.accountIds.join(","),
    () => props.from,
    () => props.to,
    status,
    category,
    search,
  ],
  () => {
    pageCursors.value = [undefined];
    page.value = 0;
  },
);
watch(
  [
    () => query.data.value?.dataset,
    () => props.datasetEpoch,
    () => props.dashboardRevision,
  ],
  ([dataset, epoch, revision]) => {
    if (!dataset || !props.active) return;
    if (
      dataset.instanceEpoch !== epoch ||
      dataset.customerRevision !== revision
    )
      emit("revisionMismatch");
    else emit("revisionAligned");
  },
);
watch(
  () => query.error.value,
  (error) => {
    if (error instanceof ApiError && error.status === 401) emit("unauthorized");
    if (error instanceof ApiError && error.status === 409) {
      pageCursors.value = [undefined];
      page.value = 0;
    }
  },
);
watch(
  [
    () => history.data.value?.dataset,
    () => props.datasetEpoch,
    () => props.dashboardRevision,
  ],
  ([dataset, epoch, revision]) => {
    if (
      dataset &&
      props.active &&
      (dataset.instanceEpoch !== epoch || dataset.customerRevision !== revision)
    )
      emit("revisionMismatch");
  },
);
watch(
  () => history.error.value,
  (error) => {
    if (error instanceof ApiError && error.status === 401) emit("unauthorized");
  },
);
watch(
  () => detail.error.value,
  (error) => {
    if (error instanceof ApiError && error.status === 401) emit("unauthorized");
  },
);
function reset() {
  searchInput.value = "";
  search.value = "";
  status.value = "ALL";
  category.value = "";
  if (filterMenu.value) filterMenu.value.open = false;
}
function next() {
  if (!query.data.value?.nextCursor) return;
  pageCursors.value = [
    ...pageCursors.value.slice(0, page.value + 1),
    query.data.value.nextCursor,
  ];
  page.value++;
}
function previous() {
  if (page.value) page.value--;
}
let opener: HTMLElement | null = null;
function open(id: string, focusTarget = document.activeElement as HTMLElement) {
  if (!props.detailId) opener = focusTarget;
  emit("open", id);
}
function openRow(id: string, event: MouseEvent) {
  const button = (
    event.currentTarget as HTMLTableRowElement
  ).querySelector<HTMLElement>(".activity-link");
  open(id, button ?? undefined);
}
function close() {
  emit("close");
}
function restoreDetailFocus() {
  requestAnimationFrame(() =>
    (opener?.isConnected
      ? opener
      : document.querySelector<HTMLElement>(".page-heading h1")
    )?.focus(),
  );
}
function onKey(event: KeyboardEvent) {
  if (!props.detailId) return;
  if (event.key === "Escape") {
    close();
    return;
  }
  if (event.key !== "Tab") return;
  const panel = document.querySelector<HTMLElement>(".detail-panel");
  const focusable = Array.from(
    panel?.querySelectorAll<HTMLElement>(
      "button, a[href], [tabindex]:not([tabindex='-1'])",
    ) ?? [],
  );
  if (!focusable.length) return;
  const first = focusable[0],
    last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
watch(
  () => props.detailId,
  (id) => {
    if (id)
      requestAnimationFrame(() =>
        document.querySelector<HTMLElement>(".detail-close")?.focus(),
      );
  },
);
if (typeof window !== "undefined") window.addEventListener("keydown", onKey);
onBeforeUnmount(() => {
  if (timer.value) clearTimeout(timer.value);
  window.removeEventListener("keydown", onKey);
  document.removeEventListener("pointerdown", closeFilterOutside);
  document.removeEventListener("keydown", closeFilterOnEscape);
});
</script>

<template>
  <section
    class="transaction-explorer"
    :class="{
      'search-active': mobileSearchOpen || status !== 'ALL' || category,
    }"
    aria-label="Transaction explorer"
  >
    <div
      id="transaction-tools"
      class="transaction-tools"
      role="search"
      aria-label="Filter transactions"
    >
      <label class="search-field"
        ><span class="sr-only">Search transactions</span
        ><svg
          class="search-field-icon"
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
        >
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m16 16 5 5" /></svg
        ><input
          ref="searchField"
          v-model="searchInput"
          type="search"
          placeholder="Search transactions"
          :aria-invalid="!!searchError"
          :aria-describedby="
            searchError
              ? 'transaction-search-error'
              : searchCodePoints === 1
                ? 'transaction-search-hint'
                : undefined
          "
        /><span
          v-if="
            !searchError &&
            (searchUpdating || (query.isFetching.value && query.data.value))
          "
          class="search-progress"
          role="status"
          ><span class="sr-only">Updating results…</span></span
        ></label
      >
      <details ref="filterMenu" class="transaction-filter-menu">
        <summary
          class="select-button"
          :aria-label="
            status !== 'ALL' || category ? 'Filters, active' : 'Filters'
          "
        >
          Filters<span
            v-if="status !== 'ALL' || category"
            class="filter-indicator"
            aria-hidden="true"
          />
        </summary>
        <div class="transaction-filter-popover">
          <label
            >Status<select v-model="status">
              <option value="ALL">All statuses</option>
              <option value="PENDING">Pending</option>
              <option value="POSTED">Posted</option>
              <option value="CANCELLED">Cancelled</option>
            </select></label
          >
          <label
            >Category<select v-model="category">
              <option value="">All categories</option>
              <option v-for="entry in categories" :key="entry" :value="entry">
                {{ label(entry) }}
              </option>
            </select></label
          >
          <button type="button" class="text-link" @click="reset">
            Reset filters
          </button>
        </div>
      </details>
    </div>
    <p
      v-if="searchError"
      id="transaction-search-error"
      class="field-error"
      role="alert"
    >
      {{ searchError }}
    </p>
    <p
      v-else-if="searchCodePoints === 1"
      id="transaction-search-hint"
      class="sr-only"
    >
      Enter one more character to search.
    </p>
    <p v-if="queryMismatch" class="state-panel" role="status">
      {{
        reconciling
          ? "Checking for updated activity…"
          : "Updated activity is available. Reload the page to align your view."
      }}
    </p>
    <p v-else-if="query.isPending.value" class="state-panel" role="status">
      Loading transactions…
    </p>
    <div v-else-if="query.isError.value" class="state-panel error" role="alert">
      Transactions could not be loaded.
      <button type="button" @click="query.refetch()">Retry</button>
    </div>
    <template v-else>
      <p v-if="!rows.length" class="state-panel" role="status">
        {{
          status !== "ALL" || category || search
            ? "No transactions match these filters."
            : history.isPending.value
              ? "Checking available history…"
              : history.isError.value
                ? "No activity in this period. Earlier history could not be checked."
                : history.isSuccess.value && !history.data.value?.items.length
                  ? "No activity in available history."
                  : "No activity in this period."
        }}
        <button
          v-if="
            status === 'ALL' && !category && !search && history.isError.value
          "
          type="button"
          @click="history.refetch()"
        >
          Retry history check
        </button>
      </p>
      <div v-else class="activity-surface">
        <section
          v-for="group in groupedRows"
          :key="group.status"
          class="activity-section"
          :class="group.status.toLowerCase()"
          :aria-label="group.title"
        >
          <h2 class="subsection-title">{{ group.title }}</h2>
          <table class="activity-table">
            <thead>
              <tr>
                <th scope="col">
                  {{
                    group.status === "POSTED" ? "Posting date" : "Authorised"
                  }}
                </th>
                <th scope="col">Description</th>
                <th scope="col">
                  {{ group.status === "POSTED" ? "Category / type" : "Type" }}
                </th>
                <th v-if="!accountIds.length" scope="col">Account</th>
                <th scope="col" class="amount">Amount</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in group.items"
                :key="item.id"
                class="transaction-row"
                @click="openRow(item.id, $event)"
              >
                <td>{{ date(item) }}</td>
                <td>
                  <button
                    type="button"
                    class="activity-link"
                    @click.stop="open(item.id)"
                  >
                    {{ item.merchantName || item.description }}
                  </button>
                </td>
                <td>{{ label(item.categoryCode || item.type) }}</td>
                <td v-if="!accountIds.length" class="account-cell">
                  •••• {{ item.maskedSuffix }}
                </td>
                <td
                  class="amount"
                  :class="{
                    credit:
                      item.recordKind === 'POSTED_ENTRY' &&
                      BigInt(item.amountMinor) > 0n,
                  }"
                >
                  {{ amount(item) }}
                  <small
                    v-if="item.recordKind === 'AUTHORIZATION'"
                    class="provisional-note"
                    >{{
                      item.status === "PENDING"
                        ? "Authorised, not posted"
                        : "Cancelled, not posted"
                    }}</small
                  >
                </td>
                <td class="mobile-meta">
                  {{ date(item) }} · {{ label(item.categoryCode || item.type)
                  }}<span v-if="!accountIds.length">
                    · •••• {{ item.maskedSuffix }}</span
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
      <div
        v-if="page || query.data.value?.nextCursor"
        class="activity-pagination"
      >
        <button type="button" :disabled="!page" @click="previous">
          Previous</button
        ><span class="page-count"
          ><strong>Page {{ page + 1 }}</strong
          ><span class="page-size">{{ rows.length }} on this page</span></span
        ><button
          type="button"
          :disabled="!query.data.value?.nextCursor"
          @click="next"
        >
          Next
        </button>
      </div>
    </template>
    <Transition name="detail" @after-leave="restoreDetailFocus">
      <div v-if="detailId" class="detail-backdrop" @click.self="close">
        <aside
          class="detail-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="detail-title"
        >
          <div class="detail-heading">
            <h2 id="detail-title">Transaction details</h2>
            <button
              type="button"
              class="detail-close"
              aria-label="Close transaction details"
              @click="close"
            >
              ×
            </button>
          </div>
          <p v-if="detail.isPending.value" role="status">
            Loading transaction…
          </p>
          <p v-else-if="detail.isError.value" role="alert">
            Transaction details unavailable.
            <button type="button" @click="detail.refetch()">Retry</button>
          </p>
          <template v-else-if="detail.data.value">
            <p class="detail-amount">{{ amount(detail.data.value) }}</p>
            <p class="detail-merchant">
              {{
                detail.data.value.merchantName || detail.data.value.description
              }}
            </p>
            <div class="detail-badges">
              <span
                class="status-badge"
                :class="detail.data.value.status.toLowerCase()"
                >{{ label(detail.data.value.status) }}</span
              >
              <span class="detail-type">{{
                label(detail.data.value.type)
              }}</span>
            </div>
            <p v-if="detail.data.value.recordKind === 'AUTHORIZATION'">
              {{
                detail.data.value.status === "PENDING"
                  ? "Authorised, not posted. This does not affect posted spending."
                  : "Cancelled authorisation. This did not affect posted spending."
              }}
            </p>
            <dl>
              <dt>Account</dt>
              <dd>{{ accountName(detail.data.value) }}</dd>
              <template v-if="detail.data.value.occurredAt">
                <dt>Transaction date</dt>
                <dd>{{ detailDate(detail.data.value.occurredAt) }}</dd>
              </template>
              <template v-if="detail.data.value.postedAt">
                <dt>Posting date</dt>
                <dd>{{ detailDate(detail.data.value.postedAt) }}</dd>
              </template>
              <template v-if="detail.data.value.categoryCode">
                <dt>Category</dt>
                <dd>{{ label(detail.data.value.categoryCode) }}</dd> </template
              ><template v-if="detail.data.value.description">
                <dt>Original description</dt>
                <dd>{{ detail.data.value.description }}</dd> </template
              ><template
                v-if="
                  detail.data.value.recordKind === 'POSTED_ENTRY' &&
                  detail.data.value.authorizedAmountMinor
                "
              >
                <dt>Originally authorised</dt>
                <dd>
                  {{
                    hidden
                      ? "••••"
                      : money(detail.data.value.authorizedAmountMinor)
                  }}
                </dd> </template
              ><template
                v-if="
                  detail.data.value.recordKind === 'POSTED_ENTRY' &&
                  detail.data.value.originalActivityId
                "
              >
                <dt>Original activity</dt>
                <dd>
                  <button
                    type="button"
                    class="text-link"
                    @click="open(detail.data.value.originalActivityId!)"
                  >
                    {{ detail.data.value.originalActivityId }}
                  </button>
                </dd>
              </template>
            </dl>
          </template>
        </aside>
      </div>
    </Transition>
  </section>
</template>
