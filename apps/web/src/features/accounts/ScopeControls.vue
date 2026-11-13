<script setup lang="ts">
import { ref, watch } from "vue";

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
const dateError = ref("");
watch(
  () => [props.from, props.to],
  () => {
    draftFrom.value = props.from;
    draftTo.value = props.to;
  },
);

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
  dateError.value = "";
  emit("apply-period", { from: draftFrom.value, to: draftTo.value });
}
</script>

<template>
  <form class="global-filters" @submit.prevent="applyPeriod">
    <div class="field">
      <label for="from">From</label
      ><input id="from" v-model="draftFrom" type="date" required />
    </div>
    <div class="field">
      <label for="to">To</label
      ><input
        id="to"
        v-model="draftTo"
        type="date"
        :max="referenceDate"
        required
      />
    </div>
    <button type="submit" class="button secondary">Apply period</button>
    <p v-if="dateError" class="field-error" role="alert">
      {{ dateError }}
    </p>
  </form>
</template>
