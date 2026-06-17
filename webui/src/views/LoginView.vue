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

function submittedForm(event: Event): HTMLFormElement | null {
  if (event.currentTarget instanceof HTMLFormElement) {
    return event.currentTarget;
  }
  if (event.target instanceof HTMLFormElement) {
    return event.target;
  }
  return null;
}

async function submit(event: Event): Promise<void> {
  const form = submittedForm(event);
  const formData = form ? new FormData(form) : null;
  const submittedUsername = String(formData?.get("username") ?? username.value);
  const submittedPassword = String(formData?.get("password") ?? password.value);

  username.value = submittedUsername;
  password.value = submittedPassword;
  submitting.value = true;
  try {
    await auth.login(submittedUsername, submittedPassword);
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.replace(redirect);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="auth-page">
    <div class="auth-panel">
      <div class="auth-heading">
        <div class="auth-mark">
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
        <n-form-item label="Username" :label-props="{ for: 'login-username' }">
          <n-input
            v-model:value="username"
            autofocus
            :input-props="{
              id: 'login-username',
              name: 'username',
              autocomplete: 'username',
              required: true,
            }"
          />
        </n-form-item>
        <n-form-item label="Password" :label-props="{ for: 'login-password' }">
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            :input-props="{
              id: 'login-password',
              name: 'password',
              autocomplete: 'current-password',
              required: true,
            }"
          />
        </n-form-item>
        <n-button
          attr-type="submit"
          type="primary"
          block
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
