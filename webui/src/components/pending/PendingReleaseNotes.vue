<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle, ExternalLink, FileText } from "@lucide/vue";
import { NButton } from "naive-ui";

import type { ReleaseNoteInfo } from "../../api/client";
import { useUpdatesStore } from "../../stores/updates";

const props = withDefaults(defineProps<{
  releaseNote?: ReleaseNoteInfo | null;
  releaseNoteStatus?: string;
  releaseNoteReason?: string;
}>(), {
  releaseNote: null,
  releaseNoteStatus: "",
  releaseNoteReason: "",
});

const updates = useUpdatesStore();
const changelog = computed(() =>
  updates.releaseChangelogStateFor(props.releaseNote),
);
const canReadChangelog = computed(() =>
  updates.releaseChangelogCanLoad(props.releaseNote),
);
const changelogLoading = computed(() => changelog.value.status === "loading");
const changelogReady = computed(() => changelog.value.status === "ready");
const changelogProblem = computed(() =>
  changelog.value.status === "unavailable" || changelog.value.status === "error"
    ? changelog.value.error
    : "",
);
const readChangelogLabel = computed(() =>
  changelogReady.value ? "Changelog loaded" : "Read changelog",
);

function readChangelog(): Promise<void> {
  return updates.loadReleaseChangelog(props.releaseNote);
}
</script>

<template>
  <div v-if="releaseNote?.links.length" class="release-notes-cell">
    <a
      v-for="link in releaseNote.links"
      :key="`${link.kind}-${link.url}`"
      class="release-note-link"
      :href="link.url"
      target="_blank"
      rel="noopener noreferrer"
    >
      {{ link.label }}
      <ExternalLink :size="14" aria-hidden="true" />
    </a>
    <span
      v-if="releaseNote.breaking"
      class="release-breaking-cue wrap-anywhere"
      :title="releaseNote.breaking_reasons.join(' ')"
      aria-label="Possible breaking change"
    >
      <AlertTriangle :size="14" aria-hidden="true" />
      Possible breaking change
    </span>
    <n-button
      v-if="canReadChangelog"
      size="tiny"
      secondary
      class="release-changelog-button"
      :loading="changelogLoading"
      :disabled="changelogLoading"
      @click="readChangelog"
    >
      <template #icon>
        <FileText :size="14" aria-hidden="true" />
      </template>
      {{ readChangelogLabel }}
    </n-button>
    <span
      v-if="changelogProblem"
      class="release-notes-reason release-changelog-problem"
    >
      {{ changelogProblem }}
    </span>
    <details v-if="changelogReady" class="release-changelog-details">
      <summary class="release-changelog-summary">
        Changelog notes
      </summary>
      <pre class="release-changelog-body">{{ changelog.body }}</pre>
      <a
        v-if="changelog.sourceUrl"
        class="text-link release-changelog-source"
        :href="changelog.sourceUrl"
        target="_blank"
        rel="noopener noreferrer"
      >
        Source
        <ExternalLink :size="14" aria-hidden="true" />
      </a>
    </details>
  </div>
  <span
    v-else
    class="release-notes-muted wrap-anywhere"
    :title="releaseNoteReason || undefined"
  >
    <span class="release-notes-status wrap-anywhere">
      {{ releaseNoteStatus }}
    </span>
    <span v-if="releaseNoteReason" class="release-notes-reason">
      {{ releaseNoteReason }}
    </span>
  </span>
</template>
