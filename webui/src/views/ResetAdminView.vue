<script setup lang="ts">
import { useRoute } from "vue-router";
import { KeyRound } from "@lucide/vue";
import { NAlert, NButton, NForm, NFormItem, NInput } from "naive-ui";

import AppBrandMark from "../components/app/AppBrandMark.vue";
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
          <AppBrandMark :size="36" />
        </div>
        <div>
          <p class="eyebrow">WUDup</p>
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
        <n-form-item
          label="Username"
          required
          feedback="Required for recovery."
          :label-props="{ for: 'reset-admin-username' }"
        >
          <n-input
            v-model:value="username"
            autofocus
            :input-props="{
              id: 'reset-admin-username',
              name: 'username',
              autocomplete: 'username',
              required: true,
            }"
          />
        </n-form-item>
        <n-form-item
          :label="`New password (${passwordMinLength}+ characters)`"
          required
          :validation-status="passwordValidationStatus"
          :feedback="passwordFeedback"
          :label-props="{ for: 'reset-admin-password' }"
        >
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            :input-props="{
              id: 'reset-admin-password',
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
          :label-props="{ for: 'reset-admin-confirm-password' }"
        >
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            :status="confirmPasswordValidationStatus"
            :input-props="{
              id: 'reset-admin-confirm-password',
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
            <KeyRound :size="18" />
          </template>
          Reset admin
        </n-button>
      </n-form>
    </div>
  </section>
</template>
