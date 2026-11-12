<script setup lang="ts">
import { computed } from "vue";
import type { Dashboard } from "../../api/client";
import { money } from "../../utils/money";

const props = defineProps<{ dashboard: Dashboard; hidden: boolean }>();
const emit = defineEmits<{ transactions: [] }>();
const shown = (value: string, signed = false) =>
  props.hidden ? "••••" : money(value, signed);
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
const trendHeight = (value: string) => {
  const amount = BigInt(value);
  const maximum = maxTrendMagnitude.value;
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
        <p class="metric-name">Net spending</p>
        <div class="metric-value">
          {{ shown(dashboard.summary.netSpendingMinor) }}
        </div>
        <p class="metric-note">
          Posted outgoings less spending credits. Own-account transfers
          excluded.
        </p>
        <p
          v-if="!hidden && BigInt(dashboard.summary.netSpendingMinor) < 0n"
          class="metric-note"
        >
          Refunds exceeded posted outgoings in this period.
        </p>
      </article>
      <article class="summary-card">
        <p class="metric-name">Net incoming funds</p>
        <div class="metric-value">
          {{ shown(dashboard.summary.incomeMinor) }}
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
            Net incoming funds {{ money(dashboard.summary.incomeMinor) }} − net
            spending {{ money(dashboard.summary.netSpendingMinor) }} +
            own-account flow
            {{ money(dashboard.summary.ownAccountFlowMinor, true) }} =
            {{ money(dashboard.summary.netMovementMinor, true) }}.
          </p>
        </details>
      </article>
    </section>
    <section class="analysis" aria-label="Spending analysis">
      <article class="panel">
        <div class="section-head">
          <h2>Where money went</h2>
        </div>
        <p v-if="hidden" class="masked-visual">Amounts hidden</p>
        <p v-else-if="!dashboard.categories.length" class="compact-empty">
          No posted spending or refunds in this period.
        </p>
        <template v-else>
          <div class="category-rows" role="list">
            <div
              v-for="item in dashboard.categories"
              :key="item.categoryCode"
              class="category-row"
              role="listitem"
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
            </div>
          </div>
          <p v-if="hasNegativeCategory" class="negative-note">
            Negative amounts mean refunds exceeded spending.
          </p>
        </template>
      </article>
      <article class="panel">
        <div class="section-head">
          <h2>Spending over time</h2>
          <span class="section-meta"
            >{{ dashboard.scope.from }} – {{ dashboard.scope.to }}</span
          >
        </div>
        <p v-if="hidden" class="masked-visual">Amounts hidden</p>
        <p v-else-if="!dashboard.trend.length" class="compact-empty">
          No posted spending or refunds in this period.
        </p>
        <template v-else>
          <div
            class="trend-chart"
            :class="{ signed: hasNegativeTrend }"
            aria-hidden="true"
          >
            <div
              class="trend-plot"
              :style="{
                gridTemplateColumns: `repeat(${dashboard.trend.length}, minmax(0, 1fr))`,
              }"
            >
              <div
                v-for="bucket in dashboard.trend"
                :key="bucket.from"
                class="trend-column"
              >
                <span
                  class="trend-bar"
                  :class="{ negative: BigInt(bucket.netSpendingMinor) < 0n }"
                  :style="{ height: trendHeight(bucket.netSpendingMinor) }"
                />
              </div>
            </div>
            <div
              class="trend-labels"
              :style="{
                gridTemplateColumns: `repeat(${dashboard.trend.length}, minmax(0, 1fr))`,
              }"
            >
              <span v-for="bucket in dashboard.trend" :key="bucket.from"
                >{{ bucket.from.slice(5) }}–{{ bucket.to.slice(5) }}</span
              >
            </div>
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
        <h2 id="recent-title">Recent posted transactions</h2>
        <button type="button" class="text-link" @click="emit('transactions')">
          View all transactions
        </button>
      </div>
      <p class="recent-empty">
        Recent transaction details will be available with the transaction
        explorer.
      </p>
    </section>
  </div>
</template>
