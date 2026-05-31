<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useBreakpoints } from "@vueuse/core";
import { Plus, Trash2 } from "@lucide/vue";
import {
  NAlert,
  NButton,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSelect,
  NTag,
} from "naive-ui";

import type { SnoozeRecord, SnoozeState } from "../api/client";
import { useUpdateTargetOptions } from "../composables/useUpdateTargetOptions";
import { useAuthStore } from "../stores/auth";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const auth = useAuthStore();
const { serviceKeyOptions } = useUpdateTargetOptions();
const breakpoints = useBreakpoints({ managementDesktop: 1120 });
const useManagementCards = breakpoints.smaller("managementDesktop");
const snoozeState = ref<SnoozeState>("active");
const showCreateConfirm = ref(false);
const showDeleteConfirm = ref(false);
const deleteTarget = ref<SnoozeRecord | null>(null);

const snoozeForm = reactive({
  serviceKey: "",
  snoozedUntil: futureIso(24),
  reason: "",
});

const stateOptions = [
  { label: "Active", value: "active" },
  { label: "Expired", value: "expired" },
  { label: "All", value: "all" },
];

const mutationsEnabled = computed(
  () => auth.session?.mutations_enabled === true,
);
const createDisabled = computed(
  () =>
    !mutationsEnabled.value ||
    !snoozeForm.serviceKey.trim() ||
    !snoozeForm.snoozedUntil.trim() ||
    webui.loading,
);

function futureIso(hours: number): string {
  return new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
}

function setFuture(hours: number): void {
  snoozeForm.snoozedUntil = futureIso(hours);
}

function resetSnoozeForm(): void {
  snoozeForm.serviceKey = "";
  snoozeForm.snoozedUntil = futureIso(24);
  snoozeForm.reason = "";
}

function setSnoozeServiceKey(value: string | number | null): void {
  snoozeForm.serviceKey = value === null ? "" : String(value);
}

function statusLabel(snooze: SnoozeRecord): string {
  return snooze.active ? "active" : "expired";
}

function openCreateConfirm(): void {
  if (createDisabled.value) {
    return;
  }
  showCreateConfirm.value = true;
}

async function confirmCreate(): Promise<void> {
  if (createDisabled.value) {
    return;
  }
  await webui.createSnooze(
    snoozeForm.serviceKey.trim(),
    snoozeForm.snoozedUntil.trim(),
    snoozeForm.reason.trim(),
    snoozeState.value,
  );
  resetSnoozeForm();
}

function openDeleteConfirm(snooze: SnoozeRecord): void {
  if (!mutationsEnabled.value) {
    return;
  }
  deleteTarget.value = snooze;
  showDeleteConfirm.value = true;
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) {
    return;
  }
  await webui.deleteSnooze(deleteTarget.value.id, snoozeState.value);
  deleteTarget.value = null;
}

onMounted(() => {
  void webui.loadUpdateTargets();
  void webui.loadSnoozes(snoozeState.value);
});

watch(snoozeState, (nextState) => {
  void webui.loadSnoozes(nextState);
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>
    <n-alert v-if="!mutationsEnabled" type="info" :show-icon="false">
      Read-only mode is active. Set WUD_WEB_MUTATIONS_ENABLED=true on the server to manage snoozes.
    </n-alert>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">Service snooze</p>
          <h2>New snooze</h2>
        </div>
      </div>
      <n-form class="management-form" @submit.prevent="openCreateConfirm">
        <n-form-item
          label="Service key"
          required
          feedback="Required to create a snooze. Use stack/service."
        >
          <n-select
            :value="snoozeForm.serviceKey"
            filterable
            tag
            clearable
            :options="serviceKeyOptions"
            placeholder="stack/service"
            :disabled="webui.loading"
            @update:value="setSnoozeServiceKey"
          />
        </n-form-item>
        <n-form-item
          label="Snoozed until"
          required
          feedback="Use an ISO timestamp, or choose 1h, 1d, or 7d."
        >
          <n-input
            v-model:value="snoozeForm.snoozedUntil"
            placeholder="YYYY-MM-DDTHH:MM:SSZ"
            :disabled="webui.loading"
          />
        </n-form-item>
        <n-form-item label="Reason">
          <n-input
            v-model:value="snoozeForm.reason"
            placeholder="maintenance"
            :disabled="webui.loading"
          />
        </n-form-item>
        <div class="form-actions">
          <n-button size="small" quaternary :disabled="webui.loading" @click="setFuture(1)">
            1h
          </n-button>
          <n-button size="small" quaternary :disabled="webui.loading" @click="setFuture(24)">
            1d
          </n-button>
          <n-button size="small" quaternary :disabled="webui.loading" @click="setFuture(168)">
            7d
          </n-button>
          <n-button quaternary :disabled="webui.loading" @click="resetSnoozeForm">
            Clear form
          </n-button>
          <n-button
            type="primary"
            attr-type="submit"
            :disabled="createDisabled"
            :loading="webui.loading"
          >
            <template #icon>
              <Plus :size="16" />
            </template>
            Create snooze
          </n-button>
        </div>
      </n-form>
    </section>

    <section class="section-panel">
      <div class="section-heading">
        <div>
          <p class="eyebrow">SQLite state</p>
          <h2>{{ webui.snoozes.length }} snoozes</h2>
        </div>
        <n-select
          v-model:value="snoozeState"
          class="filter-control"
          :options="stateOptions"
          :disabled="webui.loading"
          aria-label="Filter snoozes by state"
        />
      </div>

      <div v-if="!useManagementCards" class="management-table snooze-table">
        <div class="management-table-head">
          <span>Service</span>
          <span>Until</span>
          <span>Reason</span>
          <span>Status</span>
          <span>Actions</span>
        </div>
        <div
          v-for="snooze in webui.snoozes"
          :key="snooze.id"
          class="management-row"
        >
          <strong>{{ snooze.service_key }}</strong>
          <span>{{ snooze.snoozed_until }}</span>
          <span>{{ snooze.reason || "None" }}</span>
          <n-tag size="small" :type="snooze.active ? 'info' : 'default'">
            {{ statusLabel(snooze) }}
          </n-tag>
          <div class="table-actions">
            <n-button
              size="small"
              quaternary
              type="error"
              :disabled="!mutationsEnabled"
              @click="openDeleteConfirm(snooze)"
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
          v-for="snooze in webui.snoozes"
          :key="snooze.id"
          class="mobile-card"
        >
          <div class="mobile-card-title">
            <strong>{{ snooze.service_key }}</strong>
            <n-tag size="small" :type="snooze.active ? 'info' : 'default'">
              {{ statusLabel(snooze) }}
            </n-tag>
          </div>
          <dl>
            <div>
              <dt>Until</dt>
              <dd>{{ snooze.snoozed_until }}</dd>
            </div>
            <div>
              <dt>Reason</dt>
              <dd>{{ snooze.reason || "None" }}</dd>
            </div>
          </dl>
          <div class="table-actions">
            <n-button
              size="small"
              quaternary
              type="error"
              :disabled="!mutationsEnabled"
              @click="openDeleteConfirm(snooze)"
            >
              <template #icon>
                <Trash2 :size="15" />
              </template>
              Delete
            </n-button>
          </div>
        </article>
      </div>
      <div v-if="!webui.snoozes.length" class="empty-state">No snoozes.</div>
    </section>

    <n-modal
      v-model:show="showCreateConfirm"
      preset="dialog"
      title="Create snooze"
      positive-text="Create snooze"
      negative-text="Cancel"
      :positive-button-props="{ type: 'primary', loading: webui.loading }"
      @positive-click="confirmCreate"
    >
      <div class="confirmation-list">
        <div>
          <span>Service</span>
          <strong>{{ snoozeForm.serviceKey.trim() }}</strong>
        </div>
        <div>
          <span>Until</span>
          <strong>{{ snoozeForm.snoozedUntil.trim() }}</strong>
        </div>
        <div>
          <span>Reason</span>
          <strong>{{ snoozeForm.reason.trim() || "None" }}</strong>
        </div>
      </div>
    </n-modal>

    <n-modal
      v-model:show="showDeleteConfirm"
      preset="dialog"
      title="Delete snooze"
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
        <div>
          <span>Until</span>
          <strong>{{ deleteTarget.snoozed_until }}</strong>
        </div>
      </div>
    </n-modal>
  </section>
</template>
