<script setup lang="ts">
import { ExternalLink, Info } from "@lucide/vue";
import {
  NAlert,
  NModal,
  NTabPane,
  NTabs,
  NTag,
  NTooltip,
} from "naive-ui";

import type {
  SelfUpdatePlanResponse,
  SelfUpdateResponse,
  SelfUpdateStrategy,
} from "../../api/client";

type SelfUpdatePlanStack = SelfUpdatePlanResponse["plan"]["stacks"][number];
type SelfUpdateTagUpdate = SelfUpdatePlanStack["tag_updates"][number];

defineProps<{
  show: boolean;
  strategy: SelfUpdateStrategy;
  actionLabel: string;
  loading: boolean;
  confirmDisabled: boolean;
  selfUpdate: SelfUpdateResponse | null;
  planStack?: SelfUpdatePlanStack;
  tagUpdates: SelfUpdateTagUpdate[];
  releaseCapTitle: string;
  releasesUrl: string;
}>();

defineEmits<{
  "update:show": [value: boolean];
  confirm: [];
}>();
</script>

<template>
  <n-modal
    :show="show"
    preset="dialog"
    title="Update WUDup"
    :positive-text="actionLabel"
    negative-text="Cancel"
    :positive-button-props="{
      type: 'warning',
      loading,
      disabled: confirmDisabled,
    }"
    @update:show="$emit('update:show', $event)"
    @positive-click="$emit('confirm')"
  >
    <div class="self-update-modal">
      <n-alert
        v-if="strategy === 'prepare_tag_update'"
        type="warning"
      >
        This updates the Compose image tag and pulls the image. Recreate
        the WUDup container from outside the WebUI to run it.
      </n-alert>
      <n-alert v-else type="warning">
        This pulls the WUDup image only. Recreate the container
        outside the WebUI to run the new version.
      </n-alert>

      <n-tabs type="line" animated>
        <n-tab-pane name="overview" tab="Update Plan">
          <div class="self-update-pane">
            <div class="self-update-facts">
              <div>
                <span>Image</span>
                <code>{{ selfUpdate?.target_image || "unavailable" }}</code>
              </div>
              <div>
                <span>Container</span>
                <code>{{ selfUpdate?.restart_container || "unavailable" }}</code>
              </div>
            </div>

            <div
              v-if="strategy === 'prepare_tag_update'"
              class="self-update-plan"
            >
              <div class="self-update-notes-heading">
                <strong>Compose tag update</strong>
                <span v-if="loading" class="self-update-disabled">
                  Loading preview
                </span>
              </div>
              <template v-if="planStack">
                <div class="self-update-facts">
                  <div>
                    <span>Stack</span>
                    <code>{{ planStack.name }}</code>
                  </div>
                  <div>
                    <span>Services</span>
                    <code>{{ planStack.services.join(", ") }}</code>
                  </div>
                </div>
                <div class="self-update-tag-updates">
                  <div
                    v-for="item in tagUpdates"
                    :key="`${item.old_image}:${item.desired_tag}`"
                  >
                    <span>{{ item.old_image }} &rarr;</span>
                    <code>{{ item.new_image }}</code>
                  </div>
                </div>
              </template>
              <n-alert v-else type="info">
                Generating Compose tag-update preview.
              </n-alert>
            </div>
          </div>
        </n-tab-pane>

        <n-tab-pane name="notes" tab="Release Notes">
          <div class="self-update-pane">
            <div class="self-update-notes-heading">
              <strong>Release notes</strong>
              <n-tooltip trigger="hover">
                <template #trigger>
                  <button
                    type="button"
                    class="self-update-cap"
                    :title="releaseCapTitle"
                  >
                    <Info :size="14" aria-hidden="true" />
                    Cap {{ selfUpdate?.release_notes_cap ?? 10 }}
                  </button>
                </template>
                {{ releaseCapTitle }}
              </n-tooltip>
            </div>

            <div
              v-if="selfUpdate?.release_notes.length"
              class="self-update-notes"
            >
              <article
                v-for="note in selfUpdate.release_notes"
                :key="note.tag"
                class="self-update-note"
              >
                <div class="self-update-note-title">
                  <a
                    :href="note.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {{ note.title || note.tag }}
                    <ExternalLink :size="14" aria-hidden="true" />
                  </a>
                  <span>{{ note.published_at || note.tag }}</span>
                </div>
                <n-tag v-if="note.breaking" type="warning" size="small">
                  Review required
                </n-tag>
                <p>{{ note.body || "No release-note body was published." }}</p>
                <small v-if="note.body_truncated">
                  Release note body truncated in the WebUI. Open GitHub for the full text.
                </small>
              </article>
            </div>
            <p v-else class="self-update-empty-notes">
              Release notes are unavailable from the WebUI. Open GitHub releases before updating.
            </p>

            <a
              class="text-link self-update-github-link"
              :href="releasesUrl"
              target="_blank"
              rel="noopener noreferrer"
            >
              Open GitHub releases
              <ExternalLink :size="14" aria-hidden="true" />
            </a>
          </div>
        </n-tab-pane>
      </n-tabs>
    </div>
  </n-modal>
</template>

<style scoped>
.self-update-modal,
.self-update-pane,
.self-update-plan {
  display: grid;
  gap: 14px;
}

.self-update-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.self-update-facts div {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.self-update-facts span,
.self-update-note-title span,
.self-update-empty-notes,
.self-update-note small,
.self-update-disabled {
  color: var(--color-muted-text);
  font-size: 0.84rem;
}

.self-update-facts code,
.self-update-note p {
  overflow-wrap: anywhere;
}

.self-update-tag-updates {
  display: grid;
  gap: 8px;
}

.self-update-tag-updates div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.self-update-tag-updates span {
  color: var(--color-muted-text);
  font-size: 0.84rem;
  overflow-wrap: anywhere;
}

.self-update-tag-updates code {
  overflow-wrap: anywhere;
}

.self-update-notes-heading,
.self-update-note-title,
.self-update-github-link,
.self-update-cap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.self-update-notes-heading {
  justify-content: space-between;
}

.self-update-cap {
  border: 0;
  padding: 0;
  color: var(--color-muted-text);
  background: transparent;
  font: inherit;
  font-size: 0.84rem;
  cursor: help;
}

.self-update-notes {
  display: grid;
  gap: 10px;
  max-height: min(44vh, 420px);
  overflow: auto;
}

.self-update-note {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.self-update-note-title {
  justify-content: space-between;
  gap: 10px;
}

.self-update-note-title a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--color-action-blue);
  font-weight: 700;
}

.self-update-note p,
.self-update-empty-notes {
  margin: 0;
  white-space: pre-wrap;
}

@media (--wud-compact) {
  .self-update-facts,
  .self-update-note-title {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
