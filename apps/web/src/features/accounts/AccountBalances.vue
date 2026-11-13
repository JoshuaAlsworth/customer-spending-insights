<script setup lang="ts">
import { computed } from "vue";
import type { AccountsResponse } from "../../api/client";
import { money } from "../../utils/money";

const props = defineProps<{
  response: AccountsResponse;
  accountId: string;
  hidden: boolean;
  compact?: boolean;
}>();
const emit = defineEmits<{ "update:accountId": [value: string] }>();

const asOf = computed(() =>
  new Intl.DateTimeFormat("en-ZA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Johannesburg",
  }).format(new Date(`${props.response.balanceAsOfDate}T12:00:00Z`)),
);
const selected = computed(() =>
  props.response.accounts.find((account) => account.id === props.accountId),
);
const selectedBalance = computed(() =>
  props.accountId
    ? (selected.value?.postedBalanceMinor ?? null)
    : props.response.combinedPostedBalanceMinor,
);
const visibleAmount = (value: string | null) =>
  props.hidden ? "••••" : value === null ? "Unavailable" : money(value);
const accountKind = (value: string) =>
  value === "SECONDARY_TRANSACTIONAL"
    ? "Secondary account"
    : value === "SAVINGS"
      ? "Savings account"
      : "Everyday account";
</script>

<template>
  <section
    :class="compact ? 'selected-balance' : 'accounts-overview'"
    :aria-labelledby="
      compact ? 'selected-balance-title' : 'your-accounts-title'
    "
  >
    <template v-if="compact">
      <div class="accounts-heading">
        <h2 id="selected-balance-title">Account balance</h2>
        <span class="section-meta">Posted balance as at {{ asOf }}</span>
      </div>
      <div v-if="response.accounts.length" class="selected-balance-row">
        <label class="field" for="transaction-account">
          <span>Account</span>
          <select
            id="transaction-account"
            :value="accountId"
            @change="
              emit(
                'update:accountId',
                ($event.target as HTMLSelectElement).value,
              )
            "
          >
            <option value="">All accounts</option>
            <option
              v-for="account in response.accounts"
              :key="account.id"
              :value="account.id"
            >
              {{ account.alias }} · •• {{ account.maskedSuffix }}
            </option>
          </select>
        </label>
        <div class="selected-balance-amount">
          <span>{{ accountId ? selected?.alias : "All accounts" }}</span>
          <strong
            :class="{
              'balance-negative':
                !hidden &&
                selectedBalance !== null &&
                BigInt(selectedBalance) < 0n,
            }"
          >
            {{ visibleAmount(selectedBalance) }}
          </strong>
        </div>
      </div>
      <p v-else class="accounts-empty">
        No open accounts are available. A posted balance cannot be shown.
      </p>
    </template>
    <template v-else>
      <div class="accounts-heading">
        <div>
          <h2 id="your-accounts-title">Your accounts</h2>
          <p>Choose an account to explore its spending.</p>
        </div>
        <span class="section-meta">Posted balances as at {{ asOf }}</span>
      </div>
      <fieldset v-if="response.accounts.length" class="account-options">
        <legend class="sr-only">Choose account for spending analysis</legend>
        <label class="account-option" :class="{ selected: !accountId }">
          <input
            type="radio"
            name="overview-account"
            value=""
            :checked="!accountId"
            @change="emit('update:accountId', '')"
          />
          <span class="account-option-name">
            <strong>All accounts</strong>
            <small>Combined posted balance</small>
          </span>
          <strong
            class="account-option-amount"
            :class="{
              'balance-negative':
                !hidden &&
                response.combinedPostedBalanceMinor !== null &&
                BigInt(response.combinedPostedBalanceMinor) < 0n,
            }"
          >
            {{ visibleAmount(response.combinedPostedBalanceMinor) }}
          </strong>
        </label>
        <label
          v-for="account in response.accounts"
          :key="account.id"
          class="account-option"
          :class="{ selected: accountId === account.id }"
        >
          <input
            type="radio"
            name="overview-account"
            :value="account.id"
            :checked="accountId === account.id"
            @change="emit('update:accountId', account.id)"
          />
          <span class="account-option-name">
            <strong>{{ account.alias }}</strong>
            <small
              >{{ accountKind(account.accountKind) }} · ••
              {{ account.maskedSuffix }}</small
            >
          </span>
          <strong
            class="account-option-amount"
            :class="{
              'balance-negative':
                !hidden && BigInt(account.postedBalanceMinor) < 0n,
            }"
          >
            {{ visibleAmount(account.postedBalanceMinor) }}
          </strong>
        </label>
      </fieldset>
      <p v-else class="accounts-empty">
        No open accounts are available. A posted balance cannot be shown.
      </p>
    </template>
  </section>
</template>
