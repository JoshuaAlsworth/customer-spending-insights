<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { ApiError, getTransactions } from "../../api/client";
import type { Dashboard } from "../../api/client";
import { money } from "../../utils/money";

const props = defineProps<{
  dashboard: Dashboard;
  hidden: boolean;
  customerId: string;
  accountIds: string[];
  generation: number;
  reconciling?: boolean;
}>();
const emit = defineEmits<{
  transactions: [];
  open: [id: string];
  category: [code: string];
  unauthorized: [];
  revisionMismatch: [];
  revisionAligned: [];
}>();
const recent = useQuery({
  queryKey: computed(() => [
    "recent-transactions",
    props.customerId,
    props.generation,
    props.accountIds.join(","),
    props.dashboard.scope.from,
    props.dashboard.scope.to,
    props.dashboard.dataset.instanceEpoch,
  ]),
  queryFn: ({ signal }) =>
    getTransactions(
      {
        accountIds: props.accountIds,
        from: props.dashboard.scope.from,
        to: props.dashboard.scope.to,
        status: "POSTED",
        limit: 4,
      },
      signal,
    ),
  retry: false,
  refetchOnWindowFocus: false,
});
watch(
  [() => recent.data.value?.dataset, () => props.dashboard.dataset],
  ([activity, dashboard]) => {
    if (
      activity &&
      (activity.instanceEpoch !== dashboard.instanceEpoch ||
        activity.customerRevision !== dashboard.customerRevision)
    )
      emit("revisionMismatch");
    else if (activity) emit("revisionAligned");
  },
);
watch(
  () => recent.error.value,
  (error) => {
    if (error instanceof ApiError && error.status === 401) emit("unauthorized");
  },
);
const recentMismatch = computed(
  () =>
    !!recent.data.value &&
    (recent.data.value.dataset.instanceEpoch !==
      props.dashboard.dataset.instanceEpoch ||
      recent.data.value.dataset.customerRevision !==
        props.dashboard.dataset.customerRevision),
);
const shown = (value: string, signed = false) =>
  props.hidden ? "••••" : money(value, signed);
const categoriesExpanded = ref(false);
const orderedCategories = computed(() =>
  [...props.dashboard.categories].sort((left, right) => {
    const a = BigInt(left.netSpendingMinor);
    const b = BigInt(right.netSpendingMinor);
    return a === b
      ? left.displayName.localeCompare(right.displayName)
      : a > b
        ? -1
        : 1;
  }),
);
const shownCategories = orderedCategories;
const recentCategory = (code: string | null, type: string) =>
  props.dashboard.categories.find((item) => item.categoryCode === code)
    ?.displayName ??
  type
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (letter) => letter.toUpperCase());
const recentDate = (value: string) =>
  new Date(value).toLocaleDateString("en-ZA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Johannesburg",
  });
const trendPeak = computed(() =>
  props.dashboard.trend.reduce<(typeof props.dashboard.trend)[number] | null>(
    (peak, bucket) =>
      BigInt(bucket.netSpendingMinor) > BigInt(peak?.netSpendingMinor ?? "0")
        ? bucket
        : peak,
    null,
  ),
);
const trendAxis = computed(() => {
  const max = trendBound.value;
  if (!max) return ["R0"];
  return [4n, 3n, 2n, 1n, 0n].map((part) =>
    money(((max * part) / 4n).toString()).replace(/\.00$/, ""),
  );
});
const trendLabel = (from: string, to: string) =>
  from === to
    ? shortDate(from)
    : from.slice(0, 7) === to.slice(0, 7)
      ? `${Number(from.slice(8))}–${shortDate(to)}`
      : `${shortDate(from)}–${shortDate(to)}`;
const shortDate = (value: string) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
const hasNegativeCategory = computed(() =>
  props.dashboard.categories.some((item) => BigInt(item.netSpendingMinor) < 0n),
);
const hasNegativeTrend = computed(() =>
  props.dashboard.trend.some((item) => BigInt(item.netSpendingMinor) < 0n),
);
const maxCategory = computed(() =>
  props.dashboard.categories.reduce((max, item) => {
    const value = BigInt(item.netSpendingMinor);
    return value < 0n ? max : value > max ? value : max;
  }, 0n),
);
const maxNegativeCategory = computed(() =>
  props.dashboard.categories.reduce((max, item) => {
    const value = -BigInt(item.netSpendingMinor);
    return value > max ? value : max;
  }, 0n),
);
const barStyle = (value: string) => {
  const amount = BigInt(value);
  const scale =
    maxCategory.value * 18n > maxNegativeCategory.value * 80n
      ? maxCategory.value * 18n
      : maxNegativeCategory.value * 80n;
  if (amount === 0n || scale === 0n) return { left: "20%", width: "0%" };
  const width = Number(((amount < 0n ? -amount : amount) * 1440n) / scale);
  return {
    left: `${amount < 0n ? 20 - width : 20}%`,
    width: `${width}%`,
  };
};
const maxTrendMagnitude = computed(() =>
  props.dashboard.trend.reduce((max, bucket) => {
    const signed = BigInt(bucket.netSpendingMinor);
    const value = signed < 0n ? -signed : signed;
    return value > max ? value : max;
  }, 0n),
);
const trendBound = computed(() => {
  const max = maxTrendMagnitude.value;
  if (!max) return 0n;
  const raw = (max + 3n) / 4n;
  let base = 1n;
  while (base * 10n < raw) base *= 10n;
  const step =
    raw <= base
      ? base
      : raw <= base * 2n
        ? base * 2n
        : raw <= base * 5n
          ? base * 5n
          : base * 10n;
  return ((max + step - 1n) / step) * step;
});
const trendHeight = (value: string) => {
  const amount = BigInt(value);
  const maximum = trendBound.value;
  if (amount === 0n || maximum === 0n) return "0%";
  const magnitude = amount < 0n ? -amount : amount;
  const capacity = hasNegativeTrend.value ? 45 : 90;
  return `${Number((magnitude * BigInt(capacity)) / maximum)}%`;
};
</script>

<template>
  <div class="overview-view">
    <section class="summary" aria-label="Financial overview">
      <article class="summary-card primary">
        <p class="metric-name">Money out</p>
        <div class="metric-value">
          {{ shown(dashboard.summary.netSpendingMinor, true) }}
        </div>
        <p
          v-if="!hidden && BigInt(dashboard.summary.netSpendingMinor) < 0n"
          class="metric-note"
        >
          Refunds exceeded posted outgoings in this period.
        </p>
      </article>
      <article class="summary-card">
        <p class="metric-name">Money in</p>
        <div class="metric-value">
          {{ shown(dashboard.summary.incomeMinor, true) }}
        </div>
        <p
          v-if="!hidden && BigInt(dashboard.summary.incomeMinor) < 0n"
          class="metric-note"
        >
          Income reversals exceeded incoming funds.
        </p>
      </article>
      <article class="summary-card">
        <p class="metric-name">Net movement</p>
        <div class="metric-value">
          {{ shown(dashboard.summary.netMovementMinor, true) }}
        </div>
        <details v-if="!hidden" class="net-help">
          <summary>How calculated</summary>
          <p>
            Money in {{ money(dashboard.summary.incomeMinor) }} − money out
            {{ money(dashboard.summary.netSpendingMinor) }} + own-account flow
            {{ money(dashboard.summary.ownAccountFlowMinor, true) }} =
            {{ money(dashboard.summary.netMovementMinor, true) }}.
          </p>
        </details>
      </article>
    </section>
    <section class="analysis" aria-label="Spending analysis">
      <article
        class="panel"
        :class="{ 'categories-collapsed': !categoriesExpanded }"
      >
        <div class="section-head">
          <h2>Where money went</h2>
        </div>
        <p v-if="hidden" class="masked-visual">Amounts hidden</p>
        <p v-else-if="!dashboard.categories.length" class="compact-empty">
          No posted spending or refunds in this period.
        </p>
        <template v-else>
          <div class="category-rows">
            <button
              v-for="item in shownCategories"
              :key="item.categoryCode"
              class="category-row"
              type="button"
              :aria-label="`Filter transactions by ${item.displayName}`"
              @click="emit('category', item.categoryCode)"
            >
              <span class="category-name">{{ item.displayName }}</span>
              <span class="signed-track" aria-hidden="true"
                ><span
                  class="signed-bar"
                  :class="{ negative: BigInt(item.netSpendingMinor) < 0n }"
                  :style="barStyle(item.netSpendingMinor)"
              /></span>
              <span
                class="category-amount"
                :class="{ negative: BigInt(item.netSpendingMinor) < 0n }"
                >{{ money(item.netSpendingMinor) }}</span
              >
            </button>
          </div>
          <div class="chart-key"><span aria-hidden="true">│</span> Zero</div>
          <button
            v-if="dashboard.categories.length > 4"
            type="button"
            class="category-toggle"
            :aria-expanded="categoriesExpanded"
            @click="categoriesExpanded = !categoriesExpanded"
          >
            {{
              categoriesExpanded
                ? "Show fewer categories"
                : "View all categories"
            }}
          </button>
          <p v-if="hasNegativeCategory" class="negative-note">
            Negative amounts mean refunds exceeded spending.
          </p>
        </template>
      </article>
      <article class="panel">
        <div class="section-head">
          <h2>Spending over time</h2>
          <span class="section-meta">{{
            dashboard.trend.length < 3 ? "Monthly totals" : "Weekly totals"
          }}</span>
        </div>
        <p v-if="hidden" class="masked-visual">Amounts hidden</p>
        <p v-else-if="!dashboard.trend.length" class="compact-empty">
          No posted spending or refunds in this period.
        </p>
        <template v-else>
          <div
            class="trend-chart"
            :class="{ signed: hasNegativeTrend }"
            role="group"
            aria-label="Spending by period"
          >
            <div class="trend-axis" aria-hidden="true">
              <span v-for="tick in trendAxis" :key="tick">{{ tick }}</span>
            </div>
            <div
              class="trend-plot"
              :style="{
                gridTemplateColumns: `repeat(${dashboard.trend.length}, minmax(0, 1fr))`,
              }"
            >
              <button
                v-for="bucket in dashboard.trend"
                :key="bucket.from"
                class="trend-column"
                type="button"
                :aria-label="`${trendLabel(bucket.from, bucket.to)}, ${money(bucket.netSpendingMinor)}`"
                :title="`${trendLabel(bucket.from, bucket.to)} · ${money(bucket.netSpendingMinor)}`"
              >
                <span
                  class="trend-bar"
                  :class="{ negative: BigInt(bucket.netSpendingMinor) < 0n }"
                  :style="{ height: trendHeight(bucket.netSpendingMinor) }"
                />
              </button>
            </div>
            <div
              class="trend-labels"
              :style="{
                gridTemplateColumns: `repeat(${dashboard.trend.length}, minmax(0, 1fr))`,
              }"
            >
              <span v-for="bucket in dashboard.trend" :key="bucket.from">{{
                trendLabel(bucket.from, bucket.to)
              }}</span>
            </div>
          </div>
          <div v-if="trendPeak" class="trend-peak">
            <span>Highest spending period</span
            ><strong
              >{{ trendLabel(trendPeak.from, trendPeak.to) }} ·
              {{ money(trendPeak.netSpendingMinor) }}</strong
            >
          </div>
          <details class="exact-values">
            <summary>View exact values</summary>
            <div class="trend-list" role="list">
              <div
                v-for="bucket in dashboard.trend"
                :key="bucket.from"
                class="trend-row"
                role="listitem"
              >
                <span>{{ bucket.from }} – {{ bucket.to }}</span>
                <strong
                  :class="{ negative: BigInt(bucket.netSpendingMinor) < 0n }"
                  >{{ money(bucket.netSpendingMinor) }}</strong
                >
              </div>
            </div>
          </details>
          <p v-if="hasNegativeTrend" class="negative-note">
            A negative period has more spending credits than outgoings.
          </p>
        </template>
      </article>
    </section>
    <section class="transactions" aria-labelledby="recent-title">
      <div class="recent-heading">
        <h2 id="recent-title">Recent posted</h2>
        <button type="button" class="text-link" @click="emit('transactions')">
          View all
        </button>
      </div>
      <p v-if="recentMismatch" class="recent-empty" role="status">
        {{
          reconciling
            ? "Checking for updated activity…"
            : "Updated activity is available. Refresh to align your view."
        }}
      </p>
      <p v-else-if="recent.isPending.value" class="recent-empty" role="status">
        Loading recent transactions…
      </p>
      <p v-else-if="recent.isError.value" class="recent-empty" role="alert">
        Recent transactions could not be loaded.
        <button type="button" @click="recent.refetch()">Retry</button>
      </p>
      <p v-else-if="!recent.data.value?.items?.length" class="recent-empty">
        No posted transactions in this period.
      </p>
      <table v-else class="recent-table">
        <thead>
          <tr>
            <th scope="col">Posting date</th>
            <th scope="col">Description</th>
            <th scope="col">Category / type</th>
            <th scope="col" class="amount">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in recent.data.value.items" :key="item.id">
            <td>{{ recentDate(item.postedAt!) }}</td>
            <td>
              <button type="button" @click="emit('open', item.id)">
                {{ item.merchantName || item.description }}
              </button>
            </td>
            <td>{{ recentCategory(item.categoryCode, item.type) }}</td>
            <td
              class="amount"
              :class="{ credit: BigInt(item.amountMinor!) > 0n }"
            >
              {{ hidden ? "••••" : money(item.amountMinor!, true) }}
            </td>
            <td class="mobile-meta">
              {{ recentDate(item.postedAt!) }} ·
              {{ recentCategory(item.categoryCode, item.type) }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
