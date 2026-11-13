<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from "vue";

const props = defineProps<{
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
const menuOpen = ref(false);
const menuButton = ref<HTMLButtonElement | null>(null);
const menu = ref<HTMLDialogElement | null>(null);
function closeMenu() {
  menu.value?.close();
}
function onMenuClosed() {
  menuOpen.value = false;
  nextTick(() => menuButton.value?.focus());
}
function onMenuKey(event: KeyboardEvent) {
  if (event.key !== "Tab") return;
  const buttons = menu.value?.querySelectorAll<HTMLButtonElement>("button");
  const first = buttons?.[0];
  const last = buttons?.[buttons.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
function navigate(view: "overview" | "transactions") {
  if (menuOpen.value) closeMenu();
  emit("navigate", view);
}
watch(
  () => [props.signedIn, props.sessionLocked],
  ([signedIn, locked]) => {
    if (!signedIn || locked) menuOpen.value = false;
  },
);
watch(menuOpen, async (open) => {
  document.body.style.overflow = open ? "hidden" : "";
  if (open) {
    await nextTick();
    menu.value?.showModal();
    menu.value?.querySelector<HTMLButtonElement>("nav button")?.focus();
  }
});
onUnmounted(() => {
  document.body.style.overflow = "";
});
</script>

<template>
  <a v-if="signedIn" class="skip-link" href="#dashboard">Skip to content</a>
  <aside v-if="signedIn" class="app-sidebar" aria-label="Application sidebar">
    <div class="sidebar-identity">Spending Insights</div>
    <nav class="sidebar-nav" aria-label="Primary navigation">
      <button
        type="button"
        :aria-current="view === 'overview' ? 'page' : undefined"
        @click="navigate('overview')"
      >
        Overview
      </button>
      <button
        type="button"
        :aria-current="view === 'transactions' ? 'page' : undefined"
        @click="navigate('transactions')"
      >
        Transactions
      </button>
    </nav>
  </aside>
  <header class="app-header" :class="{ 'signed-out-header': !signedIn }">
    <div class="header-left">
      <div class="identity">
        <span class="identity-brand">Spending Insights</span>
        <span v-if="signedIn" class="identity-page">{{
          view === "overview" ? "Your spending" : "Transactions"
        }}</span>
      </div>
      <nav v-if="signedIn" class="main-nav" aria-label="Main navigation">
        <button
          type="button"
          class="nav-link"
          :aria-current="view === 'overview' ? 'page' : undefined"
          @click="navigate('overview')"
        >
          Overview
        </button>
        <button
          type="button"
          class="nav-link"
          :aria-current="view === 'transactions' ? 'page' : undefined"
          @click="navigate('transactions')"
        >
          Transactions
        </button>
      </nav>
    </div>
    <div v-if="signedIn" class="head-right">
      <button
        type="button"
        class="head-btn privacy-button"
        :aria-label="hidden ? 'Show amounts' : 'Hide amounts'"
        :aria-pressed="hidden"
        :disabled="sessionLocked"
        @click="emit('toggle-hidden')"
      >
        <span class="head-icon" aria-hidden="true">{{
          hidden ? "◉" : "◌"
        }}</span><span class="head-label">{{
          hidden ? "Show amounts" : "Hide amounts"
        }}</span>
      </button>
      <button
        type="button"
        class="head-btn refresh-button"
        aria-label="Refresh data"
        :disabled="sessionLocked"
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
  <div v-if="signedIn && !sessionLocked" class="mobile-nav-anchor">
    <dialog
      v-if="menuOpen"
      ref="menu"
      class="mobile-menu"
      aria-label="Navigate"
      @keydown="onMenuKey"
      @close="onMenuClosed"
    >
      <div class="mobile-menu-inner">
        <h2>Navigate</h2>
        <nav class="mobile-menu-grid" aria-label="Mobile navigation">
          <button
            type="button"
            :aria-current="view === 'overview' ? 'page' : undefined"
            @click="navigate('overview')"
          >
            <span class="menu-chart" aria-hidden="true">▂▅█</span
            ><span>Overview</span>
          </button>
          <button
            type="button"
            :aria-current="view === 'transactions' ? 'page' : undefined"
            @click="navigate('transactions')"
          >
            <span class="menu-chart" aria-hidden="true">☷</span
            ><span>Transactions</span>
          </button>
        </nav>
      </div>
      <button
        type="button"
        class="mobile-menu-button mobile-menu-close"
        aria-label="Close navigation"
        @click="closeMenu"
      >
        <span aria-hidden="true">•••</span>
      </button>
    </dialog>
    <button
      ref="menuButton"
      type="button"
      class="mobile-menu-button"
      aria-label="Open navigation"
      :aria-expanded="menuOpen"
      @click="menuOpen = true"
    >
      <span aria-hidden="true">•••</span>
    </button>
  </div>
</template>
