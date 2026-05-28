<script setup lang="ts">
import { computed, onMounted } from "vue";
import { breakpointsTailwind, useBreakpoints } from "@vueuse/core";
import type { DataTableColumns } from "naive-ui";

import type { PendingItem } from "../api/client";
import { useWebuiStore } from "../stores/webui";

const webui = useWebuiStore();
const breakpoints = useBreakpoints(breakpointsTailwind);
const isMobile = breakpoints.smaller("md");

const columns = computed<DataTableColumns<PendingItem>>(() => [
  { title: "Line", key: "line_no", width: 80 },
  { title: "Image", key: "image", minWidth: 240 },
  { title: "Repository", key: "repo", minWidth: 200 },
  { title: "Tag", key: "desired_tag", minWidth: 120 },
  { title: "Digest", key: "digest", minWidth: 220 },
]);

onMounted(() => {
  void webui.loadPending();
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="webui.error" type="error" :show-icon="false">
      {{ webui.error }}
    </n-alert>
    <n-alert v-if="webui.pending && !webui.pending.exists" type="warning" :show-icon="false">
      {{ webui.pending.source_file }} is missing.
    </n-alert>

    <div class="section-heading">
      <div>
        <p class="eyebrow">{{ webui.pending?.source_file ?? "Pending file" }}</p>
        <h2>{{ webui.pending?.count ?? 0 }} pending updates</h2>
      </div>
    </div>

    <n-data-table
      v-if="!isMobile"
      :columns="columns"
      :data="webui.pending?.items ?? []"
      :loading="webui.loading"
      :pagination="{ pageSize: 15 }"
      size="small"
      class="data-surface"
    />

    <div v-else class="mobile-list">
      <article v-for="item in webui.pending?.items ?? []" :key="item.line_no" class="mobile-card">
        <div class="mobile-card-title">
          <strong>{{ item.image }}</strong>
          <n-tag size="small">#{{ item.line_no }}</n-tag>
        </div>
        <dl>
          <div>
            <dt>Repository</dt>
            <dd>{{ item.repo }}</dd>
          </div>
          <div>
            <dt>Tag</dt>
            <dd>{{ item.desired_tag || "None" }}</dd>
          </div>
          <div>
            <dt>Digest</dt>
            <dd>{{ item.digest || "None" }}</dd>
          </div>
        </dl>
      </article>
      <div v-if="!webui.pending?.items.length" class="empty-state">No pending updates.</div>
    </div>
  </section>
</template>
