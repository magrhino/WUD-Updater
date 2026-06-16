<script setup lang="ts">
import { RotateCcw, Save } from "@lucide/vue";
import { NAlert, NButton, NFlex, NInput, NSelect } from "naive-ui";

import { useManagedPreferences } from "./useManagedPreferences";

defineProps<{
  compact: boolean;
}>();

const {
  settings,
  themePreferenceEntry,
  onboardingChecklistEntry,
  composeIgnorePathsEntry,
  digestPinUpdatesEntry,
  themePreferenceValue,
  onboardingChecklistValue,
  composeIgnorePathsValue,
  digestPinUpdatesValue,
  preferencesMessage,
  preferencesError,
  preferencesDisabledReason,
  preferenceControlsDisabled,
  composeIgnorePathsEditable,
  digestPinUpdatesEditable,
  preferencesDirty,
  preferenceSaveDisabled,
  themePreferenceOptions,
  onboardingChecklistOptions,
  digestPinUpdatesOptions,
  coreUpdateTourStatus,
  coreUpdateTourStep,
  managedSourceLabel,
  resetPreferenceForm,
  saveManagedPreferences,
  relaunchOnboardingChecklist,
  replayCoreUpdateTour,
  dismissCoreUpdateTour,
} = useManagedPreferences();
</script>

<template>
  <div id="settings-preferences" class="settings-zone">
    <div class="settings-zone-heading">
      <div>
        <h2>Preferences</h2>
      </div>
    </div>

    <section class="section-panel">
      <div class="section-heading">
        <div class="section-heading-main">
          <p class="eyebrow">Managed preferences</p>
          <h2>WebUI preferences</h2>
          <p class="section-copy">
            Browser-facing preferences persisted in SQLite. Runtime configuration,
            paths, and secrets stay controlled by server config.
          </p>
        </div>
        <Save :size="20" class="section-heading-icon" />
      </div>
      <n-alert
        v-if="preferencesMessage"
        type="success"
        :show-icon="false"
        class="settings-action-alert"
      >
        {{ preferencesMessage }}
      </n-alert>
      <n-alert
        v-if="preferencesError"
        type="error"
        :show-icon="false"
        class="settings-action-alert"
      >
        {{ preferencesError }}
      </n-alert>
      <div class="settings-preference-list">
        <div class="settings-preference-row">
          <div>
            <strong class="wrap-anywhere">Theme preference</strong>
            <span class="wrap-anywhere">
              Source:
              {{ managedSourceLabel(themePreferenceEntry) }}
            </span>
          </div>
          <n-select
            v-model:value="themePreferenceValue"
            :options="themePreferenceOptions"
            :disabled="preferenceControlsDisabled"
            aria-label="Theme preference"
          />
        </div>
        <div class="settings-preference-row">
          <div>
            <strong class="wrap-anywhere">Onboarding checklist</strong>
            <span class="wrap-anywhere">
              Source:
              {{ managedSourceLabel(onboardingChecklistEntry) }}
            </span>
          </div>
          <div class="settings-preference-controls">
            <n-select
              v-model:value="onboardingChecklistValue"
              :options="onboardingChecklistOptions"
              :disabled="preferenceControlsDisabled"
              aria-label="Onboarding checklist"
            />
            <n-button
              size="small"
              :disabled="preferenceControlsDisabled"
              :loading="settings.loading"
              @click="relaunchOnboardingChecklist"
            >
              <template #icon>
                <RotateCcw :size="16" />
              </template>
              Relaunch onboarding
            </n-button>
          </div>
        </div>
        <div class="settings-preference-row">
          <div>
            <strong class="wrap-anywhere">Compose ignore paths</strong>
            <span class="wrap-anywhere">
              Source:
              {{ managedSourceLabel(composeIgnorePathsEntry) }}
            </span>
          </div>
          <div class="settings-preference-controls settings-textarea-controls">
            <n-input
              v-model:value="composeIgnorePathsValue"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              :disabled="preferenceControlsDisabled || !composeIgnorePathsEditable"
              placeholder="old, archive/disabled"
              aria-label="Compose ignore paths"
            />
            <n-alert
              v-if="composeIgnorePathsEntry?.disabled_reason"
              type="info"
              :show-icon="false"
              class="settings-action-alert"
            >
              {{ composeIgnorePathsEntry.disabled_reason }}
            </n-alert>
          </div>
        </div>
        <div class="settings-preference-row">
          <div>
            <strong class="wrap-anywhere">Digest-pin updates</strong>
            <span class="wrap-anywhere">
              Source:
              {{ managedSourceLabel(digestPinUpdatesEntry) }}
            </span>
          </div>
          <div class="settings-preference-controls">
            <n-select
              v-model:value="digestPinUpdatesValue"
              :options="digestPinUpdatesOptions"
              :disabled="preferenceControlsDisabled || !digestPinUpdatesEditable"
              aria-label="Digest-pin updates"
            />
            <n-alert
              v-if="digestPinUpdatesEntry?.disabled_reason"
              type="info"
              :show-icon="false"
              class="settings-action-alert"
            >
              {{ digestPinUpdatesEntry.disabled_reason }}
            </n-alert>
          </div>
        </div>
        <div class="settings-preference-row">
          <div>
            <strong class="wrap-anywhere">Core update tour</strong>
            <span class="wrap-anywhere">
              State: {{ coreUpdateTourStatus }}. Step:
              {{ coreUpdateTourStep }}.
            </span>
          </div>
          <n-flex
            class="settings-button-group"
            :justify="compact ? 'flex-start' : 'flex-end'"
            :size="8"
          >
            <n-button
              size="small"
              :disabled="preferenceControlsDisabled"
              :loading="settings.loading"
              @click="dismissCoreUpdateTour"
            >
              Dismiss tour
            </n-button>
            <n-button
              size="small"
              type="primary"
              :disabled="preferenceControlsDisabled"
              :loading="settings.loading"
              @click="replayCoreUpdateTour"
            >
              <template #icon>
                <RotateCcw :size="16" />
              </template>
              Replay tour
            </n-button>
          </n-flex>
        </div>
      </div>
      <div class="settings-action-row settings-preference-actions">
        <div>
          <strong class="wrap-anywhere">No restart required</strong>
          <span class="wrap-anywhere">Managed values apply to new WebUI requests immediately.</span>
        </div>
        <n-flex
          class="settings-button-group"
          :justify="compact ? 'flex-start' : 'flex-end'"
          :size="8"
        >
          <n-button :disabled="settings.loading || !preferencesDirty" @click="resetPreferenceForm">
            <template #icon>
              <RotateCcw :size="16" />
            </template>
            Reset
          </n-button>
          <n-button
            type="primary"
            :disabled="preferenceSaveDisabled"
            :loading="settings.loading"
            @click="saveManagedPreferences"
          >
            <template #icon>
              <Save :size="16" />
            </template>
            Save preferences
          </n-button>
        </n-flex>
      </div>
      <n-alert
        v-if="preferencesDisabledReason"
        type="info"
        :show-icon="false"
        class="settings-action-alert"
      >
        {{ preferencesDisabledReason }}
      </n-alert>
    </section>
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

.settings-preference-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.settings-preference-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid var(--color-border-subtle);
  background: var(--color-panel-tint);
}

.settings-preference-row>div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.settings-preference-row span {
  color: var(--color-muted-text);
  font-size: 0.86rem;
}

.settings-preference-row>.settings-preference-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.settings-preference-controls :deep(.n-select) {
  flex: 1 1 180px;
  min-width: 180px;
}

.settings-preference-row>.settings-textarea-controls {
  align-items: stretch;
  flex-direction: column;
}

.settings-textarea-controls :deep(.n-input) {
  width: 100%;
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

.settings-action-row span {
  color: var(--color-muted-text);
}

.settings-action-alert {
  margin-top: 12px;
}

.settings-preference-actions {
  align-items: end;
}

@media (max-width: 560px) {
  .settings-preference-row {
    grid-template-columns: 1fr;
  }

  .settings-zone-heading {
    display: grid;
  }

  .settings-action-row {
    display: grid;
    align-items: start;
  }

  .settings-action-row :deep(.n-button) {
    justify-self: start;
  }

  .settings-preference-row>.settings-preference-controls {
    justify-content: flex-start;
  }
}
</style>
