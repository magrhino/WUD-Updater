<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { LogIn } from "@lucide/vue";
import { NAlert, NButton, NForm, NFormItem, NInput } from "naive-ui";

import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const username = ref("");
const password = ref("");
const submitting = ref(false);

async function submit(): Promise<void> {
  submitting.value = true;
  try {
    await auth.login(username.value, password.value);
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.replace(redirect);
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
          <LogIn :size="24" />
        </div>
        <div>
          <p class="eyebrow">WUD-Updater</p>
          <h1>Sign in</h1>
        </div>
      </div>

      <n-alert v-if="auth.error" type="error" :show-icon="false" class="block-alert">
        {{ auth.error }}
      </n-alert>

      <n-form @submit.prevent="submit">
        <n-form-item label="Username">
          <n-input
            v-model:value="username"
            autocomplete="username"
            autofocus
          />
        </n-form-item>
        <n-form-item label="Password">
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            autocomplete="current-password"
          />
        </n-form-item>
        <n-button
          attr-type="submit"
          type="primary"
          block
          :disabled="!username || !password"
          :loading="submitting || auth.loading"
        >
          <template #icon>
            <LogIn :size="18" />
          </template>
          Sign in
        </n-button>
      </n-form>
    </div>
  </section>
</template>
