<script setup lang="ts">
import { ShieldCheck, UserPlus } from "@lucide/vue";
import { NAlert, NButton, NForm, NFormItem, NInput } from "naive-ui";

import { useAdminClaimForm } from "./useAdminClaimForm";

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
  initialUsername: "admin",
  operation: "setup",
  successRoute: { name: "settings", query: { onboarding: "1" } },
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
        <n-form-item
          label="Username"
          required
          feedback="Required for setup."
          :label-props="{ for: 'setup-username' }"
        >
          <n-input
            v-model:value="username"
            autofocus
            :input-props="{
              id: 'setup-username',
              name: 'username',
              autocomplete: 'username',
              required: true,
            }"
          />
        </n-form-item>
        <n-form-item
          :label="`Password (${passwordMinLength}+ characters)`"
          required
          :validation-status="passwordValidationStatus"
          :feedback="passwordFeedback"
          :label-props="{ for: 'setup-password' }"
        >
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            :input-props="{
              id: 'setup-password',
              name: 'password',
              autocomplete: 'new-password',
              required: true,
            }"
          />
        </n-form-item>
        <n-form-item
          label="Confirm password"
          required
          :validation-status="confirmPasswordValidationStatus"
          :feedback="confirmPasswordFeedback"
          :label-props="{ for: 'setup-confirm-password' }"
        >
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            :status="confirmPasswordValidationStatus"
            :input-props="{
              id: 'setup-confirm-password',
              name: 'confirm-password',
              autocomplete: 'new-password',
              required: true,
            }"
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
