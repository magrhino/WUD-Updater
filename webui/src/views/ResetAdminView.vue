<script setup lang="ts">
import { useRoute } from "vue-router";
import { KeyRound, ShieldCheck } from "@lucide/vue";
import { NAlert, NButton, NForm, NFormItem, NInput } from "naive-ui";

import { useAdminClaimForm } from "./useAdminClaimForm";

const route = useRoute();
const initialUsername = typeof route.query.user === "string" ? route.query.user : "";
const {
  auth,
  username,
  password,
  confirmPassword,
  submitting,
  claim,
  passwordMinLength,
  passwordValidationStatus,
  passwordFeedback,
  confirmPasswordValidationStatus,
  confirmPasswordFeedback,
  canSubmit,
  submit,
} = useAdminClaimForm({
  initialUsername,
  operation: "reset-admin",
  successRoute: { name: "dashboard" },
});
</script>

<template>
  <section class="auth-page">
    <div class="auth-panel">
      <div class="auth-heading">
        <div class="auth-mark">
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
