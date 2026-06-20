<script setup lang="ts">
import { RefreshCw } from "@lucide/vue";
import { NAlert, NButton, NGi, NGrid, NModal } from "naive-ui";

import OnboardingChecklist from "../../components/OnboardingChecklist.vue";
import { useSettingsRestart } from "./useSettingsRestart";

defineProps<{
  compact: boolean;
}>();

const {
  connection,
  mutationsEnabled,
  restartButtonDisabled,
  restartContainerTarget,
  restartDisabledReason,
  restartDialogVisible,
  restartError,
  restartMessage,
  openRestartDialog,
  confirmRestartContainer,
} = useSettingsRestart();
</script>

<template>
  <div id="settings-actions" class="settings-zone">
    <div class="settings-zone-heading">
      <div>
        <h2>Actions</h2>
      </div>
    </div>

    <n-grid
      class="settings-zone-grid settings-actions-grid"
      item-responsive
      responsive="self"
      cols="1 760:12"
      :x-gap="16"
      :y-gap="16"
    >
      <n-gi span="1 760:5">
        <section class="section-panel">
          <div class="section-heading">
            <div class="section-heading-main">
              <p class="eyebrow">Maintenance</p>
              <h2>Container</h2>
              <p class="section-copy">
                Restart the running WebUI container after a helper image update or
                runtime configuration change.
              </p>
            </div>
            <RefreshCw :size="20" class="section-heading-icon" />
          </div>
          <n-alert
            v-if="restartMessage"
            type="success"
            :show-icon="false"
            class="settings-action-alert"
          >
            {{ restartMessage }}
          </n-alert>
          <n-alert
            v-if="restartError"
            type="error"
            :show-icon="false"
            class="settings-action-alert"
          >
            {{ restartError }}
          </n-alert>
          <n-grid
            class="settings-risk-facts"
            aria-label="Container restart facts"
            responsive="self"
            :cols="compact ? 1 : '1 220:2 340:3'"
            :x-gap="8"
            :y-gap="8"
          >
            <n-gi>
              <div class="settings-risk-fact">
                <span class="wrap-anywhere">Target</span>
                <strong class="wrap-anywhere">{{ restartContainerTarget || "Unavailable" }}</strong>
              </div>
            </n-gi>
            <n-gi>
              <div class="settings-risk-fact">
                <span class="wrap-anywhere">Permission</span>
                <strong class="wrap-anywhere">{{ mutationsEnabled ? "Allowed" : "Read-only" }}</strong>
              </div>
            </n-gi>
            <n-gi>
              <div class="settings-risk-fact">
                <span class="wrap-anywhere">Impact</span>
                <strong class="wrap-anywhere">Temporary disconnect</strong>
              </div>
            </n-gi>
          </n-grid>
          <div class="settings-action-row">
            <div>
              <strong class="wrap-anywhere">Restart WebUI container</strong>
              <span class="wrap-anywhere">The current browser session will temporarily lose connection.</span>
              <code v-if="restartContainerTarget" class="wrap-anywhere">{{ restartContainerTarget }}</code>
            </div>
            <n-button
              type="warning"
              :disabled="restartButtonDisabled"
              :loading="connection.loading"
              @click="openRestartDialog"
            >
              <template #icon>
                <RefreshCw :size="16" />
              </template>
              Restart container
            </n-button>
          </div>
          <n-alert
            v-if="restartDisabledReason"
            type="info"
            :show-icon="false"
            class="settings-action-alert"
          >
            {{ restartDisabledReason }}
          </n-alert>
        </section>
      </n-gi>

      <n-gi span="1 760:7">
        <OnboardingChecklist />
      </n-gi>
    </n-grid>

    <n-modal
      v-model:show="restartDialogVisible"
      preset="dialog"
      title="Restart WebUI container"
      positive-text="Restart container"
      negative-text="Cancel"
      :positive-button-props="{
        type: 'warning',
        loading: connection.loading,
        disabled: restartButtonDisabled,
      }"
      @positive-click="confirmRestartContainer"
    >
      <n-alert type="warning" :show-icon="false" class="block-alert">
        This restarts the container serving the WebUI. The page may disconnect until
        Docker brings it back.
      </n-alert>
      <p class="settings-dialog-copy">
        Target container:
        <code class="wrap-anywhere">{{ restartContainerTarget || "unavailable" }}</code>
      </p>
    </n-modal>
  </div>
</template>

<style scoped>
.settings-zone {
  display: grid;
  gap: 12px;
  scroll-margin-top: 18px;
}

.settings-zone-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
}

.settings-zone-heading>div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-zone-heading h2,
.settings-zone-heading p {
  margin: 0;
}

.settings-zone-heading h2 {
  color: var(--color-ink);
  font-size: 1.08rem;
  line-height: 1.25;
}

.settings-zone-heading p {
  max-width: 72ch;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.45;
}

.settings-zone-grid {
  align-items: start;
}

.settings-risk-facts {
  margin-top: 14px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.settings-risk-fact {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.settings-risk-fact span {
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
}

.settings-risk-fact strong {
  color: var(--color-ink);
  font-size: 0.9rem;
}

.settings-action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-subtle);
}

.settings-action-row>div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.settings-action-row span,
.settings-dialog-copy {
  color: var(--color-muted-text);
}

.settings-action-row code,
.settings-dialog-copy code {
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.84rem;
}

.settings-action-alert {
  margin-top: 12px;
}

.settings-actions-grid .settings-action-row {
  flex-wrap: wrap;
  align-items: flex-start;
}

.settings-actions-grid .settings-action-row>div {
  flex: 1 1 180px;
}

.settings-dialog-copy {
  margin: 0;
  line-height: 1.45;
}

@media (--wud-narrow-actions) {
  .settings-actions-grid {
    grid-template-columns: 1fr;
  }
}

@media (--wud-compact) {
  .settings-zone-heading {
    display: grid;
  }

  .settings-action-row {
    display: grid;
    align-items: start;
  }

  .settings-action-row :deep(.n-button) {
    justify-self: start;
    min-width: 44px;
    min-height: 44px;
  }
}
</style>
