<script setup lang="ts">
import { Send } from "@lucide/vue";
import { NAlert, NButton, NFlex, NModal, NTag } from "naive-ui";

import type { ReleaseNotificationResponse } from "../../api/client";
import { pluralize } from "../../views/pending/utils";

defineProps<{
  error: string;
  loading: boolean;
  response: ReleaseNotificationResponse | null;
  sendDisabled: boolean;
  sendDisabledMessage: string;
  show: boolean;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "send"): void;
}>();

function handleModalShowUpdate(value: boolean): void {
  if (!value) {
    emit("close");
  }
}
</script>

<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    @update:show="handleModalShowUpdate"
  >
    <dialog
      open
      class="preflight-modal"
      aria-labelledby="release-notification-modal-title"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">Release notes</p>
          <h2 id="release-notification-modal-title">Send Discord notifications</h2>
          <p class="preflight-summary-text">
            Preview the payload WUDup will send before posting to the configured Discord webhook.
          </p>
        </div>
        <n-tag :type="response?.sendable_count ? 'success' : 'warning'">
          {{ pluralize(response?.sendable_count ?? 0, "notification") }}
        </n-tag>
      </div>

      <n-alert
        v-if="response?.sent"
        class="preflight-block"
        type="success"
      >
        Release-note notifications sent. Audit run #{{ response.audit_run_id }}.
      </n-alert>
      <n-alert
        v-if="error"
        class="preflight-block"
        type="warning"
      >
        Release-note notification is unavailable: {{ error }}
      </n-alert>
      <n-alert
        v-if="!response && loading"
        class="preflight-block"
        type="info"
      >
        Preparing release-note notification preview.
      </n-alert>
      <n-alert
        v-if="response && !response.enabled"
        class="preflight-block"
        type="warning"
      >
        Release-note notifications are disabled.
      </n-alert>
      <n-alert
        v-else-if="response && !response.destination.configured"
        class="preflight-block"
        type="warning"
      >
        Discord release-note webhook is not configured.
      </n-alert>
      <n-alert
        v-if="sendDisabledMessage"
        class="preflight-block"
        type="info"
      >
        {{ sendDisabledMessage }}
      </n-alert>
      <n-alert
        v-for="warning in response?.warnings ?? []"
        :key="warning"
        class="preflight-block"
        type="warning"
      >
        {{ warning }}
      </n-alert>

      <section class="preflight-impact preflight-block" aria-labelledby="release-destination-title">
        <div class="preflight-impact-heading">
          <strong id="release-destination-title">Destination</strong>
          <n-tag
            size="small"
            :type="
              response
                ? (response.destination.configured ? 'success' : 'warning')
                : 'default'
            "
          >
            {{
              response
                ? (response.destination.configured ? "Configured" : "Missing")
                : "Preview pending"
            }}
          </n-tag>
        </div>
        <div class="compact-list">
          <div class="list-row">
            <span>Discord</span>
            <strong>
              {{
                response
                  ? (response.destination.source || "Webhook not configured")
                  : "Preview not loaded"
              }}
            </strong>
            <em>{{ response ? response.batches.length : 0 }} Discord message batch(es)</em>
          </div>
        </div>
      </section>

      <section
        v-if="response?.items.length"
        class="preflight-impact preflight-block"
        aria-labelledby="release-items-title"
      >
        <div class="preflight-impact-heading">
          <strong id="release-items-title">Notifications</strong>
          <n-tag size="small">{{ pluralize(response.items.length, "update") }}</n-tag>
        </div>
        <div class="compact-list">
          <div
            v-for="item in response.items"
            :key="`${item.line_no}-${item.image}`"
            class="list-row plan-line-row"
          >
            <span>#{{ item.line_no }}</span>
            <strong>{{ item.title }}</strong>
            <em>
              <code>{{ item.image }}</code>
              <template v-if="item.triggers.length">
                <span aria-hidden="true"> - </span>
                {{ item.triggers.map((trigger) => trigger.name || trigger.type || trigger.id).join(", ") }}
              </template>
            </em>
          </div>
        </div>
      </section>

      <n-flex class="preflight-footer" justify="flex-end" :size="8">
        <n-button size="small" quaternary @click="emit('close')">
          Cancel
        </n-button>
        <n-button
          type="primary"
          size="small"
          :disabled="sendDisabled"
          :loading="loading"
          @click="emit('send')"
        >
          <template #icon>
            <Send :size="16" />
          </template>
          Send to Discord
        </n-button>
      </n-flex>
    </dialog>
  </n-modal>
</template>
