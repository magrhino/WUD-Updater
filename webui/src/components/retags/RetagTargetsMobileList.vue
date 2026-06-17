<script setup lang="ts">
import { NRadioButton, NRadioGroup, NTag } from "naive-ui";

import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";
import { displayDigest } from "../../utils/digestProvenance";
import {
  candidateLabel,
  composeLocation,
  reasonDetail,
  reasonLabel,
  reasonTagType,
  trackingLabel,
} from "../../views/retags/display";

const props = defineProps<{
  rows: RetagTargetItem[];
  choices: Record<string, RetagTargetChoice>;
  mutationDisabled: boolean;
  mutationNotice: string;
}>();

const emit = defineEmits<{
  "choice-update": [item: RetagTargetItem, choice: RetagTargetChoice];
}>();

function retagChoice(item: RetagTargetItem): RetagTargetChoice {
  return props.choices[item.service_key] ?? "keep-current";
}

function canSwitchToConcrete(item: RetagTargetItem): boolean {
  return item.retag_available && item.choices.includes("switch-to-concrete");
}

function emitRetagChoice(item: RetagTargetItem, choice: string): void {
  if (choice !== "keep-current" && choice !== "switch-to-concrete") {
    return;
  }
  emit("choice-update", item, choice);
}
</script>

<template>
  <div class="mobile-list">
    <article
      v-for="item in rows"
      :key="item.service_key"
      class="mobile-card retag-card"
    >
      <div class="mobile-card-title">
        <div class="retag-card-title">
          <strong>{{ item.service_key }}</strong>
          <span>{{ item.stack }} / {{ item.service }}</span>
        </div>
        <n-tag
          size="small"
          :type="reasonTagType(item)"
          :bordered="false"
        >
          {{ reasonLabel(item.retag_reason) }}
        </n-tag>
      </div>
      <dl>
        <div>
          <dt>Image</dt>
          <dd>
            <code class="wrap-anywhere">{{ item.image }}</code>
          </dd>
        </div>
        <div>
          <dt>Tracking</dt>
          <dd>{{ trackingLabel(item) }} ({{ item.tracking_tag_source || "unknown" }})</dd>
        </div>
        <div>
          <dt>Candidate</dt>
          <dd>{{ candidateLabel(item) }}</dd>
        </div>
        <div>
          <dt>Final image</dt>
          <dd>
            <code class="wrap-anywhere">{{ item.final_image ? displayDigest(item.final_image) : "None" }}</code>
          </dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>
            <code class="wrap-anywhere">{{ composeLocation(item) }}</code>
          </dd>
        </div>
        <div>
          <dt>Choice</dt>
          <dd>
            <n-radio-group
              :value="retagChoice(item)"
              size="small"
              @update:value="emitRetagChoice(item, String($event))"
            >
              <n-radio-button value="keep-current">Keep</n-radio-button>
              <n-radio-button
                value="switch-to-concrete"
                :disabled="!canSwitchToConcrete(item) || mutationDisabled"
                :title="
                  !canSwitchToConcrete(item)
                    ? reasonDetail(item.retag_reason)
                    : mutationNotice
                "
              >
                Switch
              </n-radio-button>
            </n-radio-group>
          </dd>
        </div>
      </dl>
    </article>
  </div>
</template>

<style scoped>
.retag-card-title {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.retag-card-title span {
  color: var(--color-muted-text);
  font-size: 0.84rem;
}

.retag-card code {
  font-family: var(--font-mono);
  font-size: 0.82rem;
}
</style>
