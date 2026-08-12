<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle, RotateCcw, Send, ShieldAlert } from "@lucide/vue";
import { NAlert, NButton, NFlex, NModal, NTag } from "naive-ui";

import type {
  ReleaseNotificationItem,
  ReleaseNotificationResponse,
} from "../../api/client";
import { pluralize } from "../../views/pending/utils";
import {
  notificationStatusLabel,
  notificationStatusType,
} from "./releaseNotificationStatus";

const props = defineProps<{
  error: string;
  loading: boolean;
  response: ReleaseNotificationResponse | null;
  sendDisabled: boolean;
  sendDisabledMessage: string;
  show: boolean;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "resendPreview"): void;
  (event: "send"): void;
}>();

const resendPreviewAvailable = computed(
  () =>
    Boolean(props.response) &&
    props.response?.sent === false &&
    (props.response?.skipped_count ?? 0) > 0,
);
const notificationModeLabel = computed(() => {
  if (!props.response) {
    return "";
  }
  if (props.response?.mode === "per_container") {
    return "Per container";
  }
  return "Digest";
});
const resendPolicyLabel = computed(() => {
  if (!props.response) {
    return "";
  }
  if (props.response?.resend_policy === "cooldown") {
    return "Cooldown";
  }
  return "Remote changes";
});
const notificationItems = computed(() =>
  [...(props.response?.items ?? [])].sort((left, right) =>
    Number(right.security?.outcome === "verified_critical_high") -
    Number(left.security?.outcome === "verified_critical_high"),
  ),
);

function handleModalShowUpdate(value: boolean): void {
  if (!value) {
    emit("close");
  }
}

function notificationDetail(item: ReleaseNotificationItem): string {
  if (item.skipped_reason) {
    return item.skipped_reason;
  }
  return item.notification_last_sent_at
    ? `Last sent ${item.notification_last_sent_at}`
    : "";
}

function securityLabel(item: ReleaseNotificationItem): string {
  if (item.security?.outcome === "verified_critical_high") {
    const severity = item.security.severity === "critical" ? "Critical" : "High";
    return `${severity} security`;
  }
  return item.security?.outcome === "needs_review" ? "Security review" : "";
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
            <em>{{ response?.batch_count ?? 0 }} Discord message batch(es)</em>
          </div>
          <div class="list-row">
            <span>Mode</span>
            <strong>{{ notificationModeLabel }}</strong>
            <em>{{ resendPolicyLabel ? `${resendPolicyLabel} resend policy` : "" }}</em>
          </div>
        </div>
      </section>

      <section
        v-if="response?.messages.length"
        class="preflight-impact preflight-block"
        aria-labelledby="release-digest-title"
      >
        <div class="preflight-impact-heading">
          <strong id="release-digest-title">Discord digest preview</strong>
          <n-tag size="small">{{ pluralize(response.messages.length, "message") }}</n-tag>
        </div>
        <div class="release-digest-messages">
          <article
            v-for="(message, index) in response.messages"
            :key="index"
            class="release-digest-message"
          >
            <span v-if="response.messages.length > 1">
              Message {{ index + 1 }} of {{ response.messages.length }}
            </span>
            <pre>{{ message }}</pre>
          </article>
        </div>
      </section>

      <section
        v-if="notificationItems.length"
        class="preflight-impact preflight-block"
        aria-labelledby="release-items-title"
      >
        <div class="preflight-impact-heading">
          <strong id="release-items-title">Notifications</strong>
          <n-tag size="small">{{ pluralize(notificationItems.length, "update") }}</n-tag>
        </div>
        <div class="compact-list">
          <div
            v-for="item in notificationItems"
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
              <template v-if="notificationDetail(item)">
                <span aria-hidden="true"> - </span>
                {{ notificationDetail(item) }}
              </template>
            </em>
            <span class="release-notification-tags">
              <n-tag
                v-if="securityLabel(item)"
                size="small"
                :type="item.security.outcome === 'verified_critical_high' ? 'error' : 'warning'"
                :aria-label="securityLabel(item)"
              >
                <template #icon>
                  <ShieldAlert
                    v-if="item.security.outcome === 'verified_critical_high'"
                    :size="14"
                    aria-hidden="true"
                  />
                  <AlertTriangle v-else :size="14" aria-hidden="true" />
                </template>
                {{ securityLabel(item) }}
              </n-tag>
              <n-tag size="small" :type="notificationStatusType(item.notification_status)">
                {{ notificationStatusLabel(item.notification_status) }}
              </n-tag>
            </span>
          </div>
        </div>
      </section>

      <n-flex class="preflight-footer" justify="flex-end" :size="8">
        <n-button size="small" quaternary @click="emit('close')">
          Cancel
        </n-button>
        <n-button
          size="small"
          secondary
          :disabled="loading || !resendPreviewAvailable"
          :loading="loading"
          @click="emit('resendPreview')"
        >
          <template #icon>
            <RotateCcw :size="16" />
          </template>
          Preview resend
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

<style scoped>
.release-digest-messages {
  display: grid;
  gap: 8px;
  max-height: min(44vh, 420px);
  overflow: auto;
}

.release-digest-message {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.release-digest-message > span {
  color: var(--color-muted-text);
  font-size: 0.78rem;
  font-weight: 700;
}

.release-digest-message pre {
  margin: 0;
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 0.82rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.release-notification-tags {
  display: flex;
  grid-column: 2 / -1;
  flex-wrap: wrap;
  gap: 6px;
}

@media (--wud-compact) {
  .release-notification-tags {
    grid-column: 1;
  }
}
</style>
