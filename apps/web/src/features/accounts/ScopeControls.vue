<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";

const props = defineProps<{
  from: string;
  to: string;
  referenceDate: string;
  label?: string;
}>();
const emit = defineEmits<{
  "apply-period": [period: { from: string; to: string }];
}>();
const draftFrom = ref(props.from);
const draftTo = ref(props.to);
const customOpen = ref(false);
const dateError = ref("");
const picker = ref<HTMLDetailsElement | null>(null);
const popoverMaxHeight = ref(440);
function closePicker(restoreFocus = true) {
  if (picker.value) picker.value.open = false;
  if (restoreFocus)
    void nextTick(() => picker.value?.querySelector("summary")?.focus());
}
function onToggle() {
  if (picker.value?.open) updatePopoverHeight();
}
function updatePopoverHeight() {
  if (!picker.value?.open) return;
  const bottom =
    picker.value.querySelector("summary")?.getBoundingClientRect().bottom ?? 0;
  const viewport = window.visualViewport;
  popoverMaxHeight.value = Math.max(
    48,
    (viewport ? viewport.offsetTop + viewport.height : window.innerHeight) -
      bottom -
      20,
  );
}
function toggleCustom() {
  customOpen.value = !customOpen.value;
  if (customOpen.value)
    void nextTick(() =>
      picker.value?.querySelector<HTMLInputElement>("#from")?.focus(),
    );
}
const shortDate = (date: string) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
const monthYear = (date: string) =>
  new Intl.DateTimeFormat("en-GB", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
const fullMonthYear = (date: string) =>
  new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
const currentMonthLabel = computed(() => fullMonthYear(props.referenceDate));
const previousMonthLabel = computed(() => {
  const date = new Date(`${props.referenceDate}T12:00:00Z`);
  return fullMonthYear(
    calendarDate(date.getUTCFullYear(), date.getUTCMonth() - 1, 1),
  );
});
const periodLabel = computed(() => {
  if (!props.from || !props.to) return "Choose dates";
  return props.from.slice(0, 7) === props.to.slice(0, 7)
    ? `${Number(props.from.slice(8))}–${Number(props.to.slice(8))} ${monthYear(props.to)}`
    : `${shortDate(props.from)} – ${shortDate(props.to)}`;
});
const compactLabel = computed(() =>
  props.from && props.to && props.from.slice(0, 7) === props.to.slice(0, 7)
    ? fullMonthYear(props.to)
    : "Custom dates",
);
watch(
  () => [props.from, props.to],
  () => {
    draftFrom.value = props.from;
    draftTo.value = props.to;
  },
);
function choose(from: string, to: string) {
  dateError.value = "";
  emit("apply-period", { from, to });
  closePicker();
}
function closeOutside(event: PointerEvent) {
  if (picker.value?.open && !picker.value.contains(event.target as Node))
    closePicker(false);
}
onMounted(() => {
  document.addEventListener("pointerdown", closeOutside);
  window.addEventListener("resize", updatePopoverHeight);
  window.addEventListener("scroll", updatePopoverHeight, true);
  window.visualViewport?.addEventListener("resize", updatePopoverHeight);
  window.visualViewport?.addEventListener("scroll", updatePopoverHeight);
});
onUnmounted(() => {
  document.removeEventListener("pointerdown", closeOutside);
  window.removeEventListener("resize", updatePopoverHeight);
  window.removeEventListener("scroll", updatePopoverHeight, true);
  window.visualViewport?.removeEventListener("resize", updatePopoverHeight);
  window.visualViewport?.removeEventListener("scroll", updatePopoverHeight);
});
function calendarDate(year: number, month: number, day: number) {
  return new Date(Date.UTC(year, month, day)).toISOString().slice(0, 10);
}
function monthRange(offset: number) {
  const date = new Date(`${props.referenceDate}T12:00:00Z`);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth() + offset;
  return {
    from: calendarDate(year, month, 1),
    to: offset === 0 ? props.referenceDate : calendarDate(year, month + 1, 0),
  };
}
function last90Range() {
  const date = new Date(`${props.referenceDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 89);
  return { from: date.toISOString().slice(0, 10), to: props.referenceDate };
}
const selectedPeriod = computed(() => {
  if (!props.from || !props.to) return "";
  const matches = (period: { from: string; to: string }) =>
    props.from === period.from && props.to === period.to;
  return matches(monthRange(0))
    ? "current"
    : matches(monthRange(-1))
      ? "previous"
      : matches(last90Range())
        ? "last90"
        : "custom";
});
function chooseMonth(offset: number) {
  const period = monthRange(offset);
  choose(period.from, period.to);
}
function chooseLast90() {
  const period = last90Range();
  choose(period.from, period.to);
}
function applyPeriod() {
  const start = new Date(`${draftFrom.value}T12:00:00Z`);
  const end = new Date(`${draftTo.value}T12:00:00Z`);
  const maxEnd = new Date(start);
  maxEnd.setUTCMonth(maxEnd.getUTCMonth() + 36);
  if (
    !draftFrom.value ||
    !draftTo.value ||
    Number.isNaN(+start) ||
    Number.isNaN(+end) ||
    start.toISOString().slice(0, 10) !== draftFrom.value ||
    end.toISOString().slice(0, 10) !== draftTo.value ||
    start > end ||
    draftTo.value > props.referenceDate ||
    end >= maxEnd
  ) {
    dateError.value = `Choose a valid period of up to 36 months ending ${props.referenceDate} or earlier.`;
    return;
  }
  choose(draftFrom.value, draftTo.value);
}
</script>

<template>
  <section class="period-control">
    <span class="mobile-field-label" aria-hidden="true">Period</span>
    <span class="field-label">{{ label ?? "Spending period" }}</span>
    <details
      ref="picker"
      class="period-picker"
      @keydown.esc.prevent="closePicker()"
      @toggle="onToggle"
    >
      <summary
        class="select-button"
        :aria-label="`${label ?? 'Spending period'}: ${periodLabel}`"
      >
        <span class="period-long">{{ periodLabel }}</span><span
          class="period-short"
          >{{ compactLabel }}</span
        >
      </summary>
      <div
        class="period-popover"
        :style="{ '--period-max-height': `${popoverMaxHeight}px` }"
      >
        <button
          type="button"
          :aria-pressed="selectedPeriod === 'current'"
          @click="chooseMonth(0)"
        >
          {{ currentMonthLabel }}
        </button>
        <button
          type="button"
          :aria-pressed="selectedPeriod === 'previous'"
          @click="chooseMonth(-1)"
        >
          {{ previousMonthLabel }}
        </button>
        <button
          type="button"
          :aria-pressed="selectedPeriod === 'last90'"
          @click="chooseLast90"
        >
          Last 90 days
        </button>
        <button
          type="button"
          :aria-expanded="customOpen"
          :aria-pressed="selectedPeriod === 'custom'"
          @click="toggleCustom"
        >
          Custom dates
        </button>
        <form
          v-if="customOpen"
          class="custom-range"
          @submit.prevent="applyPeriod"
        >
          <label
            >From<input id="from" v-model="draftFrom" type="date" required
          /></label>
          <label
            >To<input
              id="to"
              v-model="draftTo"
              type="date"
              :max="referenceDate"
              required
          /></label>
          <p v-if="dateError" class="field-error" role="alert">
            {{ dateError }}
          </p>
          <div class="custom-actions">
            <button
              type="button"
              class="button secondary"
              @click="customOpen = false"
            >
              Cancel</button
            ><button type="submit" class="button primary">Apply period</button>
          </div>
        </form>
      </div>
    </details>
  </section>
</template>
