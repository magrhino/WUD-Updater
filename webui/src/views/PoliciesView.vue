<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useBreakpoints } from "@vueuse/core";
import { Edit3, Save, Trash2 } from "@lucide/vue";
import {
  NAlert,
  NButton,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSwitch,
  NTag,
} from "naive-ui";

import type {
  AutoUpdateDay,
  ServicePolicyRecord,
  ServicePolicyUpdateMode,
} from "../api/client";
import { useAuthStore } from "../stores/auth";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const auth = useAuthStore();
const breakpoints = useBreakpoints({ managementDesktop: 1200 });
const useManagementCards = breakpoints.smaller("managementDesktop");
const showSaveConfirm = ref(false);
const showDeleteConfirm = ref(false);
const deleteTarget = ref<ServicePolicyRecord | null>(null);

const policyForm = reactive({
  serviceKey: "",
  updateMode: "" as ServicePolicyUpdateMode,
  autoUpdate: false,
  autoUpdateTime: "",
  autoUpdateDays: [] as AutoUpdateDay[],
  snoozeDefaultSeconds: null as number | null,
});

const AUTO_UPDATE_TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;
const dayLabels: Record<AutoUpdateDay, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

const updateModeOptions = [
  { label: "Default", value: "" },
  { label: "Pause", value: "pause" },
  { label: "Stop", value: "stop" },
  { label: "Live", value: "live" },
];
const weekdayOptions = Object.entries(dayLabels).map(([value, label]) => ({
  label,
  value,
}));

const mutationsEnabled = computed(
  () => auth.session?.mutations_enabled === true,
);
const timezoneKnown = computed(() => webui.status !== null);
const timezoneLabel = computed(() => webui.status?.timezone ?? "loading");
const scheduleFeedback = computed(() =>
  timezoneKnown.value
    ? `Server timezone: ${timezoneLabel.value}`
    : "Server timezone is loading.",
);
const autoUpdateScheduleValid = computed(
  () =>
    !policyForm.autoUpdate ||
    (AUTO_UPDATE_TIME_PATTERN.test(policyForm.autoUpdateTime) &&
      policyForm.autoUpdateDays.length > 0),
);
const formScheduleLabel = computed(() => {
  if (!policyForm.autoUpdate) {
    return "Disabled";
  }
  const time = normalizedAutoUpdateTime();
  if (time === null || policyForm.autoUpdateDays.length === 0) {
    return "Not scheduled";
  }
  const days = policyForm.autoUpdateDays.map((day) => dayLabels[day]).join(", ");
  return `${days} at ${time}`;
});
const saveDisabled = computed(
  () =>
    !mutationsEnabled.value ||
    !policyForm.serviceKey.trim() ||
    !autoUpdateScheduleValid.value ||
    (policyForm.autoUpdate && !timezoneKnown.value) ||
    webui.loading,
);

function editPolicy(policy: ServicePolicyRecord): void {
  policyForm.serviceKey = policy.service_key;
  policyForm.updateMode = policy.update_mode as ServicePolicyUpdateMode;
  policyForm.autoUpdate = policy.auto_update;
  policyForm.autoUpdateTime = policy.auto_update_time ?? "";
  policyForm.autoUpdateDays = [...policy.auto_update_days];
  policyForm.snoozeDefaultSeconds = policy.snooze_default_seconds;
}

function resetPolicyForm(): void {
  policyForm.serviceKey = "";
  policyForm.updateMode = "";
  policyForm.autoUpdate = false;
  policyForm.autoUpdateTime = "";
  policyForm.autoUpdateDays = [];
  policyForm.snoozeDefaultSeconds = null;
}

function modeLabel(mode: string): string {
  return mode || "default";
}

function snoozeLabel(seconds: number | null): string {
  return seconds === null ? "None" : `${seconds}s`;
}

function scheduleLabel(policy: ServicePolicyRecord): string {
  if (!policy.auto_update) {
    return "Disabled";
  }
  if (policy.auto_update_time === null || policy.auto_update_days.length === 0) {
    return "Not scheduled";
  }
  const days = policy.auto_update_days.map((day) => dayLabels[day]).join(", ");
  return `${days} at ${policy.auto_update_time}`;
}

function normalizedSnoozeSeconds(): number | null {
  if (policyForm.snoozeDefaultSeconds === null) {
    return null;
  }
  return Math.max(0, Math.trunc(policyForm.snoozeDefaultSeconds));
}

function normalizedAutoUpdateTime(): string | null {
  const value = policyForm.autoUpdateTime.trim();
  return AUTO_UPDATE_TIME_PATTERN.test(value) ? value : null;
}

function openSaveConfirm(): void {
  if (saveDisabled.value) {
    return;
  }
  showSaveConfirm.value = true;
}

async function confirmSave(): Promise<void> {
  if (saveDisabled.value) {
    return;
  }
  await webui.upsertServicePolicy(
    policyForm.serviceKey.trim(),
    policyForm.updateMode,
    policyForm.autoUpdate,
    normalizedSnoozeSeconds(),
    normalizedAutoUpdateTime(),
    [...policyForm.autoUpdateDays],
  );
}

function openDeleteConfirm(policy: ServicePolicyRecord): void {
  if (!mutationsEnabled.value) {
    return;
  }
  deleteTarget.value = policy;
  showDeleteConfirm.value = true;
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) {
    return;
  }
  await webui.deleteServicePolicy(deleteTarget.value.service_key);
  if (deleteTarget.value.service_key === policyForm.serviceKey) {
    resetPolicyForm();
  }
  deleteTarget.value = null;
}

onMounted(() => {
  if (webui.status === null) {
    void webui.loadStatus();
  }
  void webui.loadServicePolicies();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>
    <n-alert v-if="!mutationsEnabled" type="info" :show-icon="false">
      Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to edit policies.
    </n-alert>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Service policy</p>
          <h2>{{ policyForm.serviceKey ? "Edit policy" : "New policy" }}</h2>
        </div>
      </div>
      <n-form class="management-form" @submit.prevent="openSaveConfirm">
        <n-form-item
          label="Service key"
          required
          feedback="Required to save a policy. Use stack/service."
        >
          <n-input
            v-model:value="policyForm.serviceKey"
            placeholder="stack/service"
            :disabled="webui.loading"
          />
        </n-form-item>
        <n-form-item label="Update mode">
          <n-select
            v-model:value="policyForm.updateMode"
            :options="updateModeOptions"
            :disabled="webui.loading"
          />
        </n-form-item>
        <n-form-item label="Auto update">
          <n-switch v-model:value="policyForm.autoUpdate" :disabled="webui.loading" />
        </n-form-item>
        <n-form-item
          :label="`Update time (${timezoneLabel})`"
          :feedback="scheduleFeedback"
        >
          <n-input
            v-model:value="policyForm.autoUpdateTime"
            placeholder="09:30"
            :maxlength="5"
            :disabled="webui.loading"
          />
        </n-form-item>
        <n-form-item label="Update days">
          <n-select
            v-model:value="policyForm.autoUpdateDays"
            multiple
            :options="weekdayOptions"
            :disabled="webui.loading"
          />
        </n-form-item>
        <n-form-item
          label="Default snooze seconds"
          feedback="Optional. Leave empty for no default snooze."
        >
          <n-input-number
            v-model:value="policyForm.snoozeDefaultSeconds"
            clearable
            :min="0"
            :show-button="false"
            :disabled="webui.loading"
          />
        </n-form-item>
        <div class="form-actions">
          <n-button quaternary :disabled="webui.loading" @click="resetPolicyForm">
            Clear form
          </n-button>
          <n-button
            type="primary"
            attr-type="submit"
            :disabled="saveDisabled"
            :loading="webui.loading"
          >
            <template #icon>
              <Save :size="16" />
            </template>
            Save policy
          </n-button>
        </div>
      </n-form>
    </section>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">SQLite state</p>
          <h2>{{ webui.servicePolicies.length }} service policies</h2>
        </div>
      </div>

      <div v-if="!useManagementCards" class="management-table policy-table">
        <div class="management-table-head">
          <span>Service</span>
          <span>Mode</span>
          <span>Auto</span>
          <span>Schedule</span>
          <span>Snooze</span>
          <span>Actions</span>
        </div>
        <div
          v-for="policy in webui.servicePolicies"
          :key="policy.service_key"
          class="management-row"
        >
          <strong>{{ policy.service_key }}</strong>
          <n-tag size="small">{{ modeLabel(policy.update_mode) }}</n-tag>
          <span>{{ policy.auto_update ? "Yes" : "No" }}</span>
          <span>{{ scheduleLabel(policy) }}</span>
          <span>{{ snoozeLabel(policy.snooze_default_seconds) }}</span>
          <div class="table-actions">
            <n-button size="small" quaternary @click="editPolicy(policy)">
              <template #icon>
                <Edit3 :size="15" />
              </template>
              Edit
            </n-button>
            <n-button
              size="small"
              quaternary
              type="error"
              :disabled="!mutationsEnabled"
              @click="openDeleteConfirm(policy)"
            >
              <template #icon>
                <Trash2 :size="15" />
              </template>
              Delete
            </n-button>
          </div>
        </div>
      </div>

      <div v-else class="mobile-list">
        <article
          v-for="policy in webui.servicePolicies"
          :key="policy.service_key"
          class="mobile-card"
        >
          <div class="mobile-card-title">
            <strong>{{ policy.service_key }}</strong>
            <n-tag size="small">{{ modeLabel(policy.update_mode) }}</n-tag>
          </div>
          <dl>
            <div>
              <dt>Auto update</dt>
              <dd>{{ policy.auto_update ? "Yes" : "No" }}</dd>
            </div>
            <div>
              <dt>Schedule</dt>
              <dd>{{ scheduleLabel(policy) }}</dd>
            </div>
            <div>
              <dt>Snooze</dt>
              <dd>{{ snoozeLabel(policy.snooze_default_seconds) }}</dd>
            </div>
          </dl>
          <div class="table-actions">
            <n-button size="small" quaternary @click="editPolicy(policy)">
              <template #icon>
                <Edit3 :size="15" />
              </template>
              Edit
            </n-button>
            <n-button
              size="small"
              quaternary
              type="error"
              :disabled="!mutationsEnabled"
              @click="openDeleteConfirm(policy)"
            >
              <template #icon>
                <Trash2 :size="15" />
              </template>
              Delete
            </n-button>
          </div>
        </article>
      </div>
      <div v-if="!webui.servicePolicies.length" class="empty-state">No service policies.</div>
    </section>

    <n-modal
      v-model:show="showSaveConfirm"
      preset="dialog"
      title="Save service policy"
      positive-text="Save policy"
      negative-text="Cancel"
      :positive-button-props="{ type: 'primary', loading: webui.loading }"
      @positive-click="confirmSave"
    >
      <div class="confirmation-list">
        <div>
          <span>Service</span>
          <strong>{{ policyForm.serviceKey.trim() }}</strong>
        </div>
        <div>
          <span>Mode</span>
          <strong>{{ modeLabel(policyForm.updateMode) }}</strong>
        </div>
        <div>
          <span>Auto update</span>
          <strong>{{ policyForm.autoUpdate ? "Yes" : "No" }}</strong>
        </div>
        <div>
          <span>Schedule</span>
          <strong>{{ formScheduleLabel }}</strong>
        </div>
        <div>
          <span>Snooze</span>
          <strong>{{ snoozeLabel(normalizedSnoozeSeconds()) }}</strong>
        </div>
      </div>
    </n-modal>

    <n-modal
      v-model:show="showDeleteConfirm"
      preset="dialog"
      title="Delete service policy"
      positive-text="Delete"
      negative-text="Cancel"
      :positive-button-props="{ type: 'error', loading: webui.loading }"
      @positive-click="confirmDelete"
    >
      <div v-if="deleteTarget" class="confirmation-list">
        <div>
          <span>Service</span>
          <strong>{{ deleteTarget.service_key }}</strong>
        </div>
      </div>
    </n-modal>
  </section>
</template>
