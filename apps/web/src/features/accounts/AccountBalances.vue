<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import type { AccountsResponse } from "../../api/client";
import { money } from "../../utils/money";

const props = defineProps<{
  response: AccountsResponse;
  accountId: string;
  hidden: boolean;
  compact?: boolean;
}>();
const emit = defineEmits<{ "update:accountId": [value: string] }>();
const picker = ref<HTMLDetailsElement | null>(null);
function closePicker() {
  if (picker.value) picker.value.open = false;
}
function choose(id: string) {
  emit("update:accountId", id);
  closePicker();
  void nextTick(() => picker.value?.querySelector("summary")?.focus());
}
function closeOutside(event: PointerEvent) {
  if (picker.value?.open && !picker.value.contains(event.target as Node))
    closePicker();
}
onMounted(() => document.addEventListener("pointerdown", closeOutside));
onUnmounted(() => document.removeEventListener("pointerdown", closeOutside));

const asOf = computed(() =>
  new Intl.DateTimeFormat("en-ZA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Johannesburg",
  }).format(new Date(`${props.response.balanceAsOfDate}T12:00:00Z`)),
);
const asOfCompact = computed(() =>
  new Intl.DateTimeFormat("en-ZA", {
    day: "numeric",
    month: "short",
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
const accountName = (account: AccountsResponse["accounts"][number]) => {
  const kind =
    account.accountKind === "SAVINGS"
      ? "Savings account"
      : account.accountKind === "SECONDARY_TRANSACTIONAL"
        ? "Secondary account"
        : "Everyday account";
  return account.alias.toLowerCase() ===
    kind.replace(" account", "").toLowerCase()
    ? kind
    : account.alias;
};
</script>

<template>
  <section
    class="account-control"
    :class="compact ? 'selected-balance' : 'accounts-overview'"
  >
    <span class="field-label">Posted balance · {{ asOf }}</span>
    <details
      v-if="response.accounts.length"
      ref="picker"
      class="account-picker"
      @keydown.esc.prevent="closePicker"
    >
      <summary
        class="select-button account-button"
        :aria-label="`Account: ${selected ? accountName(selected) : 'All accounts'}`"
      >
        <span class="account-button-name">{{
          selected
            ? `${accountName(selected)} · •• ${selected.maskedSuffix}`
            : "All accounts"
        }}</span>
        <span class="account-button-name account-button-short">{{
          selected
            ? `${selected.alias} ••${selected.maskedSuffix}`
            : "All accounts"
        }}</span>
        <span class="selected-balance-amount"
          ><strong
            :class="{
              'balance-negative':
                !hidden &&
                selectedBalance !== null &&
                BigInt(selectedBalance) < 0n,
            }"
            >{{ visibleAmount(selectedBalance) }}</strong
          ><small>Posted · {{ asOfCompact }}</small></span
        >
      </summary>
      <fieldset class="account-options">
        <legend class="sr-only">Choose account for spending analysis</legend>
        <h2 class="sr-only">Your accounts</h2>
        <label
          v-for="account in response.accounts"
          :key="account.id"
          class="account-option"
          :class="{ selected: accountId === account.id }"
        >
          <input
            type="radio"
            name="account-selection"
            :value="account.id"
            :checked="accountId === account.id"
            @change="choose(account.id)"
          />
          <span class="account-option-name"
            >{{ accountName(account) }} · •• {{ account.maskedSuffix }}</span
          >
          <strong
            class="account-option-amount"
            :class="{
              'balance-negative':
                !hidden && BigInt(account.postedBalanceMinor) < 0n,
            }"
            >{{ visibleAmount(account.postedBalanceMinor) }}</strong
          >
        </label>
        <label class="account-option" :class="{ selected: !accountId }">
          <input
            type="radio"
            name="account-selection"
            value=""
            :checked="!accountId"
            @change="choose('')"
          />
          <span class="account-option-name">All accounts</span>
          <strong
            class="account-option-amount"
            :class="{
              'balance-negative':
                !hidden &&
                response.combinedPostedBalanceMinor !== null &&
                BigInt(response.combinedPostedBalanceMinor) < 0n,
            }"
            >{{ visibleAmount(response.combinedPostedBalanceMinor) }}</strong
          >
        </label>
      </fieldset>
    </details>
    <p v-else class="accounts-empty">
      No open accounts are available. A posted balance cannot be shown.
    </p>
  </section>
</template>
