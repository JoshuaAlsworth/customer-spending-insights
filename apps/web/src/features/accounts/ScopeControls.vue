<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";

const props = defineProps<{
  from: string;
  to: string;
  referenceDate: string;
}>();
const emit = defineEmits<{
  "apply-period": [period: { from: string; to: string }];
}>();
const draftFrom = ref(props.from);
const draftTo = ref(props.to);
const customOpen = ref(false);
const dateError = ref("");
const picker = ref<HTMLDetailsElement | null>(null);
function closePicker() {
  if (picker.value) picker.value.open = false;
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
const periodLabel = computed(() => {
  if (!props.from || !props.to) return "Choose dates";
  return props.from.slice(0, 7) === props.to.slice(0, 7)
    ? `${Number(props.from.slice(8))}–${Number(props.to.slice(8))} ${monthYear(props.to)}`
    : `${shortDate(props.from)} – ${shortDate(props.to)}`;
});
const compactLabel = computed(() =>
  props.from && props.to && props.from.slice(0, 7) === props.to.slice(0, 7)
    ? monthYear(props.to)
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
  void nextTick(() => picker.value?.querySelector("summary")?.focus());
}
function closeOutside(event: PointerEvent) {
  if (picker.value?.open && !picker.value.contains(event.target as Node))
    closePicker();
}
onMounted(() => document.addEventListener("pointerdown", closeOutside));
onUnmounted(() => document.removeEventListener("pointerdown", closeOutside));
function calendarDate(year: number, month: number, day: number) {
  return new Date(Date.UTC(year, month, day)).toISOString().slice(0, 10);
}
function chooseMonth(offset: number) {
  const date = new Date(`${props.referenceDate}T12:00:00Z`);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth() + offset;
  choose(
    calendarDate(year, month, 1),
    offset === 0 ? props.referenceDate : calendarDate(year, month + 1, 0),
  );
}
function chooseLast90() {
  const date = new Date(`${props.referenceDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 89);
  choose(date.toISOString().slice(0, 10), props.referenceDate);
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
    <span class="field-label">Spending period</span>
    <details
      ref="picker"
      class="period-picker"
      @keydown.esc.prevent="closePicker"
    >
      <summary
        class="select-button"
        :aria-label="`Spending period: ${periodLabel}`"
      >
        <span class="period-long">{{ periodLabel }}</span><span
          class="period-short"
          >{{ compactLabel }}</span
        >
      </summary>
      <div class="period-popover">
        <button type="button" @click="chooseMonth(0)">Current month</button>
        <button type="button" @click="chooseMonth(-1)">Previous month</button>
        <button type="button" @click="chooseLast90">Last 90 days</button>
        <button
          type="button"
          :aria-expanded="customOpen"
          @click="customOpen = !customOpen"
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
