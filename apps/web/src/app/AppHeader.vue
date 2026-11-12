<script setup lang="ts">
defineProps<{
  signedIn: boolean;
  view: "overview" | "transactions";
  hidden: boolean;
  sessionLocked: boolean;
  displayName: string;
}>();
const emit = defineEmits<{
  navigate: [view: "overview" | "transactions"];
  "toggle-hidden": [];
  refresh: [];
  "sign-out": [];
}>();
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <span class="identity">Spending Insights</span>
      <nav v-if="signedIn" class="main-nav" aria-label="Main navigation">
        <button
          type="button"
          class="nav-link"
          :aria-current="view === 'overview' ? 'page' : undefined"
          @click="emit('navigate', 'overview')"
        >
          Overview
        </button>
        <button
          type="button"
          class="nav-link"
          :aria-current="view === 'transactions' ? 'page' : undefined"
          @click="emit('navigate', 'transactions')"
        >
          Transactions
        </button>
      </nav>
    </div>
    <div v-if="signedIn" class="head-right">
      <button
        type="button"
        class="head-btn"
        :aria-label="hidden ? 'Show amounts' : 'Hide amounts'"
        :aria-pressed="hidden"
        :disabled="sessionLocked"
        @click="emit('toggle-hidden')"
      >
        <span class="head-icon" aria-hidden="true">{{
          hidden ? "◉" : "◌"
        }}</span>
        <span class="head-label">{{
          hidden ? "Show amounts" : "Hide amounts"
        }}</span>
      </button>
      <button
        type="button"
        class="head-btn"
        aria-label="Refresh data"
        @click="emit('refresh')"
      >
        <span class="head-icon" aria-hidden="true">↻</span
        ><span class="head-label">Refresh</span>
      </button>
      <details class="profile-menu">
        <summary aria-label="Account menu">
          {{ displayName.slice(0, 1).toUpperCase() }}
        </summary>
        <div class="profile-popover">
          <span>{{ displayName }}</span><button
            type="button"
            @click="emit('sign-out')"
          >
            Sign out
          </button>
        </div>
      </details>
    </div>
  </header>
</template>
