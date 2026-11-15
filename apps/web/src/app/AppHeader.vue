<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";

const props = defineProps<{
  signedIn: boolean;
  view: "overview" | "transactions";
  sessionLocked: boolean;
  searchOpen: boolean;
}>();
const emit = defineEmits<{
  navigate: [view: "overview" | "transactions"];
  search: [];
  "sign-out": [];
}>();
const menuOpen = ref(false);
const menuClosing = ref(false);
const profileMenu = ref<HTMLDetailsElement | null>(null);
const menuButton = ref<HTMLButtonElement | null>(null);
const menu = ref<HTMLDialogElement | null>(null);
function closeMenu() {
  const dialog = menu.value;
  if (!dialog?.open || menuClosing.value) return;
  if (
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ||
    !dialog.animate
  ) {
    dialog.close();
    return;
  }
  menuClosing.value = true;
  const style = getComputedStyle(dialog);
  const animation = dialog.animate(
    [
      { opacity: style.opacity, transform: style.transform },
      { opacity: 0, transform: "translateY(100%)" },
    ],
    { duration: 300, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
  );
  void animation.finished.then(
    () => dialog.close(),
    () => dialog.close(),
  );
}
function closeProfileOutside(event: PointerEvent) {
  if (
    profileMenu.value?.open &&
    !profileMenu.value.contains(event.target as Node)
  )
    profileMenu.value.open = false;
}
function closeProfileOnEscape(event: KeyboardEvent) {
  if (event.key === "Escape" && profileMenu.value?.open) {
    profileMenu.value.open = false;
    profileMenu.value.querySelector("summary")?.focus();
  }
}
onMounted(() => {
  document.addEventListener("pointerdown", closeProfileOutside);
  document.addEventListener("keydown", closeProfileOnEscape);
});
function onMenuClosed() {
  menuOpen.value = false;
  menuClosing.value = false;
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
  document.removeEventListener("pointerdown", closeProfileOutside);
  document.removeEventListener("keydown", closeProfileOnEscape);
});
</script>

<template>
  <a v-if="signedIn" class="skip-link" href="#dashboard">Skip to content</a>
  <aside v-if="signedIn" class="app-sidebar" aria-label="Application sidebar">
    <div class="sidebar-identity">
      <img class="brand-logo" src="/spending-insights-logo.svg" alt="" />
      Spending Insights
    </div>
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
        <span class="identity-brand">
          <img class="brand-logo" src="/spending-insights-logo.svg" alt="" />
          Spending Insights
        </span>
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
        v-if="view === 'transactions'"
        type="button"
        class="mobile-header-search"
        aria-label="Search transactions"
        aria-controls="transaction-tools"
        :aria-expanded="searchOpen"
        :disabled="sessionLocked"
        @click="emit('search')"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
        >
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m16 16 5 5" />
        </svg>
      </button>
      <details ref="profileMenu" class="profile-menu">
        <summary aria-label="Account menu">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
          >
            <circle cx="12" cy="7" r="3.3" />
            <path d="M4.5 20v-2a7.5 7.5 0 0 1 15 0v2" />
          </svg>
        </summary>
        <div class="profile-popover">
          <button
            class="sign-out-button"
            type="button"
            @click="emit('sign-out')"
          >
            <span aria-hidden="true">↪</span> Sign out
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
      @click.self="closeMenu"
      @cancel.prevent="closeMenu"
      @close="onMenuClosed"
    >
      <div class="mobile-menu-inner">
        <div class="mobile-menu-brand">
          <img class="brand-logo" src="/spending-insights-logo.svg" alt="" />
          <span>Spending Insights</span>
        </div>
        <h2>Navigate</h2>
        <nav class="mobile-menu-grid" aria-label="Mobile navigation">
          <button
            type="button"
            :aria-current="view === 'overview' ? 'page' : undefined"
            @click="navigate('overview')"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 40 40"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
            >
              <rect x="4" y="4" width="13" height="13" rx="2" />
              <rect x="23" y="4" width="13" height="13" rx="2" />
              <rect x="4" y="23" width="13" height="13" rx="2" />
              <rect x="23" y="23" width="13" height="13" rx="2" /></svg
            ><span>Overview</span>
          </button>
          <button
            type="button"
            :aria-current="view === 'transactions' ? 'page' : undefined"
            @click="navigate('transactions')"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 40 40"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="5" y="3" width="30" height="34" rx="3" />
              <path d="M16 13h13M16 20h13M16 27h13" />
              <circle cx="11" cy="13" r="1" fill="currentColor" stroke="none" />
              <circle cx="11" cy="20" r="1" fill="currentColor" stroke="none" />
              <circle
                cx="11"
                cy="27"
                r="1"
                fill="currentColor"
                stroke="none"
              /></svg
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
