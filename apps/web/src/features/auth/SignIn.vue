<script setup lang="ts">
import { onMounted, ref } from "vue";
import { login, type Session } from "../../api/client";

defineProps<{ status: string }>();
const emit = defineEmits<{ "signed-in": [session: Session] }>();
const loginId = ref("");
const password = ref("");
const busy = ref(false);
const error = ref("");
const loginIdError = ref("");
const passwordError = ref("");
const showPassword = ref(false);
const rememberId = ref(false);

onMounted(() => {
  try {
    const saved = localStorage.getItem("spendingInsightsLoginId");
    if (saved) {
      loginId.value = saved;
      rememberId.value = true;
    }
  } catch {
    // Private browsing may disable local storage.
  }
});

async function submit() {
  loginIdError.value = loginId.value.trim() ? "" : "Enter your Login ID.";
  passwordError.value = password.value ? "" : "Enter your password.";
  if (loginIdError.value || passwordError.value) return;
  busy.value = true;
  error.value = "";
  try {
    const session = await login(loginId.value, password.value);
    try {
      if (rememberId.value)
        localStorage.setItem("spendingInsightsLoginId", loginId.value.trim());
      else localStorage.removeItem("spendingInsightsLoginId");
    } catch {
      // Authentication does not depend on local storage.
    }
    emit("signed-in", session);
  } catch {
    error.value = "Sign in failed. Check your details and try again.";
  } finally {
    password.value = "";
    showPassword.value = false;
    busy.value = false;
  }
}
</script>

<template>
  <main class="signed-out login-view">
    <div class="login-pane">
      <div class="login-brand">Spending Insights</div>
      <div class="login-content">
        <h1>Welcome back</h1>
        <form class="sign-card" novalidate @submit.prevent="submit">
          <p v-if="status" role="status" class="form-status">{{ status }}</p>
          <p v-if="error" role="alert" class="form-error">{{ error }}</p>
          <label for="login-id">Login ID</label>
          <input
            id="login-id"
            v-model="loginId"
            type="text"
            autocomplete="username"
            spellcheck="false"
            :aria-invalid="!!loginIdError"
            :aria-describedby="loginIdError ? 'login-id-error' : undefined"
            @input="loginIdError = ''"
          />
          <p
            v-if="loginIdError"
            id="login-id-error"
            class="field-error"
            role="alert"
          >
            {{ loginIdError }}
          </p>
          <label for="password">Password</label>
          <div class="password-field">
            <input
              id="password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              :aria-invalid="!!passwordError"
              :aria-describedby="passwordError ? 'password-error' : undefined"
              @input="passwordError = ''"
            />
            <button
              type="button"
              :aria-label="showPassword ? 'Hide password' : 'Show password'"
              @click="showPassword = !showPassword"
            >
              {{ showPassword ? "Hide" : "Show" }}
            </button>
          </div>
          <p
            v-if="passwordError"
            id="password-error"
            class="field-error"
            role="alert"
          >
            {{ passwordError }}
          </p>
          <label class="remember-row" for="remember-id">
            <input
              id="remember-id"
              v-model="rememberId"
              type="checkbox"
              aria-label="Remember this ID"
            />
            Remember my Login ID
          </label>
          <button class="login-submit" type="submit" :disabled="busy">
            {{ busy ? "Signing in…" : "Sign in"
            }}<span aria-hidden="true">→</span>
          </button>
        </form>
      </div>
    </div>
    <div class="login-art" aria-hidden="true">
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="login-wave-a" x1="0" y1="0" x2="1" y2="1">
            <stop stop-color="#dcecff" />
            <stop offset=".45" stop-color="#83b4f5" />
            <stop offset="1" stop-color="#184cba" />
          </linearGradient>
          <linearGradient id="login-wave-b" x1="0" y1="0" x2="1" y2="1">
            <stop stop-color="#d8efff" />
            <stop offset=".5" stop-color="#427ad8" />
            <stop offset="1" stop-color="#102d73" />
          </linearGradient>
        </defs>
        <rect width="1000" height="1000" fill="#eaf4ff" />
        <path
          d="M-190 818C29 539 225 635 371 480 521 322 621 89 1111-85V1085H-190Z"
          fill="url(#login-wave-a)"
        />
        <path
          d="M-110 1088C100 751 348 759 484 579 616 403 716 232 1093 113V1088Z"
          fill="url(#login-wave-b)"
        />
        <path
          d="M-81 1092C134 860 368 946 567 726 709 567 842 520 1093 493V1092Z"
          fill="#153a88"
          opacity=".88"
        />
        <path
          d="M-64 1059C187 810 314 865 493 671 612 542 782 346 1062 281"
          fill="none"
          stroke="#fff"
          stroke-opacity=".48"
          stroke-width="15"
        />
      </svg>
    </div>
  </main>
</template>
