<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { KeyRound, ShieldCheck } from "@lucide/vue";
import { NAlert, NButton, NForm, NFormItem, NInput } from "naive-ui";

import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const username = ref(typeof route.query.user === "string" ? route.query.user : "");
const password = ref("");
const confirmPassword = ref("");
const submitting = ref(false);

const claim = computed(() =>
  typeof route.query.claim === "string" ? route.query.claim : "",
);
const passwordMinLength = computed(
  () => auth.setupStatus?.password_min_length ?? 12,
);
const passwordsMatch = computed(
  () => password.value.length > 0 && password.value === confirmPassword.value,
);
const passwordValidationStatus = computed<"error" | undefined>(() =>
  password.value.length > 0 && password.value.length < passwordMinLength.value
    ? "error"
    : undefined,
);
const passwordFeedback = computed(() =>
  passwordValidationStatus.value === "error"
    ? `Use at least ${passwordMinLength.value} characters.`
    : `Minimum ${passwordMinLength.value} characters.`,
);
const confirmPasswordValidationStatus = computed<"error" | undefined>(() =>
  confirmPassword.value && !passwordsMatch.value ? "error" : undefined,
);
const confirmPasswordFeedback = computed(() =>
  confirmPasswordValidationStatus.value === "error"
    ? "Passwords do not match."
    : "Repeat the new password.",
);
const canSubmit = computed(
  () =>
    Boolean(claim.value) &&
    Boolean(username.value.trim()) &&
    password.value.length >= passwordMinLength.value &&
    passwordsMatch.value,
);

onMounted(async () => {
  await auth.loadSetupStatus();
});

async function submit(): Promise<void> {
  submitting.value = true;
  try {
    await auth.resetAdmin(claim.value, username.value, password.value);
    await router.replace({ name: "dashboard" });
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="login-page">
    <div class="login-panel">
      <div class="login-heading">
        <div class="login-mark">
          <ShieldCheck :size="24" />
        </div>
        <div>
          <p class="eyebrow">WUD-Updater</p>
          <h1>Reset admin</h1>
        </div>
      </div>

      <n-alert v-if="!claim" type="warning" :show-icon="false" class="block-alert">
        Open the recovery link printed by the WebUI reset command.
      </n-alert>
      <n-alert v-if="auth.error" type="error" :show-icon="false" class="block-alert">
        {{ auth.error }}
      </n-alert>

      <n-form @submit.prevent="submit">
        <n-form-item label="Username" required feedback="Required for recovery.">
          <n-input v-model:value="username" autocomplete="username" autofocus />
        </n-form-item>
        <n-form-item
          :label="`New password (${passwordMinLength}+ characters)`"
          required
          :validation-status="passwordValidationStatus"
          :feedback="passwordFeedback"
        >
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            autocomplete="new-password"
          />
        </n-form-item>
        <n-form-item
          label="Confirm password"
          required
          :validation-status="confirmPasswordValidationStatus"
          :feedback="confirmPasswordFeedback"
        >
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            autocomplete="new-password"
            :status="confirmPasswordValidationStatus"
          />
        </n-form-item>
        <n-button
          attr-type="submit"
          type="primary"
          block
          :disabled="!canSubmit"
          :loading="submitting || auth.loading"
        >
          <template #icon>
            <KeyRound :size="18" />
          </template>
          Reset admin
        </n-button>
      </n-form>
    </div>
  </section>
</template>
