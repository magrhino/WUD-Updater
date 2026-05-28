<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ShieldCheck, UserPlus } from "@lucide/vue";

import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const username = ref("admin");
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
    await auth.claimSetup(claim.value, username.value, password.value);
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
          <h1>Create admin</h1>
        </div>
      </div>

      <n-alert v-if="!claim" type="warning" :show-icon="false" class="block-alert">
        Open the setup link printed by the WebUI server.
      </n-alert>
      <n-alert v-if="auth.error" type="error" :show-icon="false" class="block-alert">
        {{ auth.error }}
      </n-alert>

      <n-form @submit.prevent="submit">
        <n-form-item label="Username">
          <n-input v-model:value="username" autocomplete="username" autofocus />
        </n-form-item>
        <n-form-item :label="`Password (${passwordMinLength}+ characters)`">
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            autocomplete="new-password"
          />
        </n-form-item>
        <n-form-item label="Confirm password">
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            autocomplete="new-password"
            :status="confirmPassword && !passwordsMatch ? 'error' : undefined"
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
            <UserPlus :size="18" />
          </template>
          Create admin
        </n-button>
      </n-form>
    </div>
  </section>
</template>
