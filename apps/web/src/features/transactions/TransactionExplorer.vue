<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import {
  ApiError,
  getTransactions,
  getTransaction,
  type Activity,
  type CategoryCode,
  type TransactionType,
} from "../../api/client";
import { money } from "../../utils/money";
import categoryPolicy from "../../../../../contracts/finance/categories.json";

const props = defineProps<{
  customerId: string;
  accountIds: string[];
  from: string;
  to: string;
  hidden: boolean;
  active: boolean;
  generation: number;
  datasetEpoch: string;
  dashboardRevision: number;
  reconciling?: boolean;
  referenceDate: string;
  detailId: string | null;
}>();
const emit = defineEmits<{
  open: [id: string];
  close: [];
  unauthorized: [];
  revisionMismatch: [];
  revisionAligned: [];
}>();
const searchInput = ref("");
const search = ref("");
const status = ref<"ALL" | "PENDING" | "POSTED" | "CANCELLED">("ALL");
const type = ref<TransactionType | "">("");
const category = ref<CategoryCode | "">("");
const pageCursors = ref<(string | undefined)[]>([undefined]);
const page = ref(0);
const timer = ref<ReturnType<typeof setTimeout>>();
const types: TransactionType[] = [
  "SALARY_CREDIT",
  "ALLOWANCE_CREDIT",
  "EXTERNAL_RECEIPT",
  "INTEREST_CREDIT",
  "CARD_PURCHASE",
  "DEBIT_ORDER",
  "EXTERNAL_PAYMENT",
  "CASH_WITHDRAWAL",
  "BANK_FEE",
  "SPEND_REFUND",
  "SPEND_REVERSAL",
  "INCOME_REVERSAL",
  "OWN_TRANSFER_OUT",
  "OWN_TRANSFER_IN",
  "OWN_TRANSFER_REVERSAL_OUT",
  "OWN_TRANSFER_REVERSAL_IN",
];
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
const query = useQuery({
  queryKey: computed(() => [
    "transactions",
    props.customerId,
    props.generation,
    props.datasetEpoch,
    props.accountIds.join(","),
    props.from,
    props.to,
    status.value,
    type.value,
    category.value,
    search.value,
    pageCursors.value[page.value],
  ]),
  queryFn: ({ signal }) =>
    getTransactions(
      {
        accountIds: props.accountIds,
        from: props.from,
        to: props.to,
        status: status.value,
        type: type.value || undefined,
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
      !type.value &&
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
const normalizeSearch = (value: string) =>
  value
    .replace(/^\p{White_Space}+|\p{White_Space}+$/gu, "")
    .replace(/\p{White_Space}+/gu, " ");
const normalizedSearch = computed(() => normalizeSearch(searchInput.value));
const searchCodePoints = computed(() => [...normalizedSearch.value].length);
const searchUpdating = computed(() => normalizedSearch.value !== search.value);
const searchError = computed(() =>
  searchCodePoints.value === 1
    ? "Enter at least 2 characters."
    : searchCodePoints.value > 100
      ? "Search is limited to 100 characters."
      : "",
);
watch(searchInput, () => {
  if (timer.value) clearTimeout(timer.value);
  const normalized = normalizedSearch.value;
  if (searchError.value) return;
  timer.value = setTimeout(() => {
    search.value = normalized;
  }, 300);
});
watch(
  [
    () => props.accountIds.join(","),
    () => props.from,
    () => props.to,
    status,
    type,
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
  type.value = "";
  category.value = "";
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
function open(id: string) {
  if (!props.detailId) opener = document.activeElement as HTMLElement;
  emit("open", id);
}
function close() {
  emit("close");
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
});
</script>

<template>
  <section class="transaction-explorer" aria-label="Transaction explorer">
    <div
      class="transaction-tools"
      role="search"
      aria-label="Filter transactions"
    >
      <label class="search-field"
        >Search transactions<input
          v-model="searchInput"
          type="search"
          placeholder="Merchant or description"
          :aria-invalid="!!searchError"
          :aria-describedby="
            searchError ? 'transaction-search-error' : undefined
          "
      /></label>
      <label
        >Status<select v-model="status">
          <option value="ALL">All statuses</option>
          <option value="PENDING">Pending</option>
          <option value="POSTED">Posted</option>
          <option value="CANCELLED">Cancelled</option>
        </select></label
      >
      <label
        >Type<select v-model="type">
          <option value="">All types</option>
          <option v-for="entry in types" :key="entry" :value="entry">
            {{ label(entry) }}
          </option>
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
    <p
      v-if="searchError"
      id="transaction-search-error"
      class="field-error"
      role="alert"
    >
      {{ searchError }}
    </p>
    <p v-if="!searchError && searchUpdating" class="state-panel" role="status">
      Searching transactions…
    </p>
    <p
      v-else-if="!searchError && queryMismatch"
      class="state-panel"
      role="status"
    >
      {{
        reconciling
          ? "Checking for updated activity…"
          : "Updated activity is available. Refresh to align your view."
      }}
    </p>
    <p
      v-else-if="!searchError && query.isPending.value"
      class="state-panel"
      role="status"
    >
      Loading transactions…
    </p>
    <div
      v-else-if="!searchError && query.isError.value"
      class="state-panel error"
      role="alert"
    >
      Transactions could not be loaded.
      <button type="button" @click="query.refetch()">Retry</button>
    </div>
    <template v-else-if="!searchError">
      <p
        v-if="query.isFetching.value"
        class="transaction-refresh"
        role="status"
      >
        Refreshing transactions…
      </p>
      <p v-if="!rows.length" class="state-panel">
        {{
          status !== "ALL" || type || category || search
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
            status === 'ALL' &&
            !type &&
            !category &&
            !search &&
            history.isError.value
          "
          type="button"
          @click="history.refetch()"
        >
          Retry history check
        </button>
      </p>
      <div v-else class="activity-surface">
        <div class="activity-table-wrap">
          <table class="activity-table">
            <thead>
              <tr>
                <th scope="col">Transaction</th>
                <th scope="col">Date</th>
                <th scope="col">Type / category</th>
                <th scope="col">Status</th>
                <th scope="col">Account</th>
                <th scope="col" class="amount">Amount</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in rows" :key="item.id">
                <td>
                  <button
                    type="button"
                    class="activity-link"
                    @click="open(item.id)"
                  >
                    {{ item.merchantName || item.description }}
                  </button>
                </td>
                <td>{{ date(item) }}</td>
                <td>{{ label(item.categoryCode || item.type) }}</td>
                <td>
                  <span
                    class="activity-status"
                    :class="item.status.toLowerCase()"
                    >{{ label(item.status) }}</span
                  >
                </td>
                <td>•••• {{ item.maskedSuffix }}</td>
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
              </tr>
            </tbody>
          </table>
        </div>
        <div class="activity-cards">
          <button
            v-for="item in rows"
            :key="item.id"
            type="button"
            class="activity-card"
            @click="open(item.id)"
          >
            <span class="activity-card-top"
              ><strong>{{ item.merchantName || item.description }}</strong
              ><strong>{{ amount(item) }}</strong></span
            ><span
              >{{ date(item) }} ·
              {{ label(item.categoryCode || item.type) }}</span
            ><span
              ><span
                class="activity-status"
                :class="item.status.toLowerCase()"
                >{{ label(item.status) }}</span
              >
              · •••• {{ item.maskedSuffix }}</span
            ><span v-if="item.recordKind === 'AUTHORIZATION'">{{
              item.status === "PENDING"
                ? "Authorised, not posted"
                : "Cancelled, not posted"
            }}</span>
          </button>
        </div>
      </div>
      <div v-if="rows.length || page" class="activity-pagination">
        <button type="button" :disabled="!page" @click="previous">
          Previous</button
        ><span>Showing {{ rows.length }} results</span
        ><button
          type="button"
          :disabled="!query.data.value?.nextCursor"
          @click="next"
        >
          Next
        </button>
      </div>
    </template>
    <div v-if="detailId" class="detail-backdrop" @click.self="close">
      <aside
        class="detail-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-title"
      >
        <button type="button" class="detail-close" @click="close">Close</button>
        <p v-if="detail.isPending.value" role="status">Loading transaction…</p>
        <p v-else-if="detail.isError.value" role="alert">
          Transaction details unavailable.
          <button type="button" @click="detail.refetch()">Retry</button>
        </p>
        <template v-else-if="detail.data.value">
          <h2 id="detail-title">
            {{
              detail.data.value.merchantName || detail.data.value.description
            }}
          </h2>
          <p class="detail-amount">{{ amount(detail.data.value) }}</p>
          <p v-if="detail.data.value.recordKind === 'AUTHORIZATION'">
            {{
              detail.data.value.status === "PENDING"
                ? "Authorised, not posted. This does not affect posted spending."
                : "Cancelled authorisation. This did not affect posted spending."
            }}
          </p>
          <dl>
            <dt>Status</dt>
            <dd>{{ label(detail.data.value.status) }}</dd>
            <dt>Type</dt>
            <dd>{{ label(detail.data.value.type) }}</dd>
            <dt>Account</dt>
            <dd>•••• {{ detail.data.value.maskedSuffix }}</dd>
            <dt>Description</dt>
            <dd>{{ detail.data.value.description }}</dd>
            <dt>{{ detail.data.value.postedAt ? "Posted" : "Occurred" }}</dt>
            <dd>
              {{
                new Date(
                  (detail.data.value.postedAt || detail.data.value.occurredAt)!,
                ).toLocaleString("en-ZA", { timeZone: "Africa/Johannesburg" })
              }}
            </dd>
            <template
              v-if="
                detail.data.value.recordKind === 'POSTED_ENTRY' &&
                detail.data.value.occurredAt
              "
            >
              <dt>Occurred</dt>
              <dd>
                {{
                  new Date(detail.data.value.occurredAt).toLocaleString(
                    "en-ZA",
                    { timeZone: "Africa/Johannesburg" },
                  )
                }}
              </dd>
            </template>
            <template v-if="detail.data.value.categoryCode">
              <dt>Category</dt>
              <dd>{{ label(detail.data.value.categoryCode) }}</dd> </template
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
  </section>
</template>
