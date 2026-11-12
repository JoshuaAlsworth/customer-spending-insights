<script setup lang="ts">
import { ref } from "vue";
import { login, type Session } from "../../api/client";

defineProps<{ status: string }>();
const emit = defineEmits<{ "signed-in": [session: Session] }>();
const loginId = ref("");
const password = ref("");
const busy = ref(false);
const error = ref("");

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    emit("signed-in", await login(loginId.value, password.value));
  } catch {
    error.value = "Sign in failed. Check your details and try again.";
  } finally {
    password.value = "";
    busy.value = false;
  }
}
</script>

<template>
  <main class="signed-out">
    <form class="sign-card" @submit.prevent="submit">
      <p class="eyebrow">YOUR FINANCIAL VIEW</p>
      <h1>Welcome back</h1>
      <p class="sign-intro">
        Sign in to see your spending across your accounts.
      </p>
      <p v-if="status" role="status" class="form-status">
        {{ status }}
      </p>
      <p v-if="error" role="alert" class="form-error">
        {{ error }}
      </p>
      <label for="login-id">Login ID</label>
      <input id="login-id" v-model="loginId" autocomplete="username" required />
      <label for="password">Password</label>
      <input
        id="password"
        v-model="password"
        type="password"
        autocomplete="current-password"
        required
      />
      <button class="button primary" type="submit" :disabled="busy">
        {{ busy ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </main>
</template>
