<script setup lang="ts">
import { NButton, NInput, NRadioButton, NRadioGroup, NTag } from "naive-ui";

import type { RetagTargetChoice, RetagTargetItem } from "../../api/client";
import { displayDigest } from "../../utils/digestProvenance";
import {
  canEnableRetagTargetChoice,
  canShowRetagAction,
  canSwitchToConcrete,
  emitRetagChoice,
  emitRetagAction,
  retagChoice,
  retagActionDisabled,
  retagActionTitle,
  retagChoiceDescriptionId,
  retagChoiceDisabledReason,
  retagTargetChoiceTitle,
  retagTargetIdentity,
  retagTargetTagValidationError,
  retagTargetTagErrorId,
  retagTargetTagValue,
} from "./retagChoices";
import {
  candidateLabel,
  composeLocation,
  reasonLabel,
  reasonTagType,
  runtimeStateDetail,
  runtimeStateLabel,
  runtimeStateTagType,
  trackingLabel,
} from "../../views/retags/display";

defineProps<{
  rows: RetagTargetItem[];
  choices: Record<string, RetagTargetChoice>;
  targetTags: Record<string, string>;
  mutationDisabled: boolean;
  mutationNotice: string;
}>();

const emit = defineEmits<{
  "choice-update": [item: RetagTargetItem, choice: RetagTargetChoice];
  "target-tag-update": [item: RetagTargetItem, tag: string];
}>();
</script>

<template>
  <div class="mobile-list">
    <article
      v-for="item in rows"
      :key="retagTargetIdentity(item)"
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
      <div
        v-if="canShowRetagAction(item, targetTags)"
        class="retag-card-primary-action"
      >
        <n-button
          class="retag-one-service-button"
          size="small"
          secondary
          type="primary"
          :disabled="retagActionDisabled(item, targetTags, mutationDisabled)"
          :title="retagActionTitle(item, targetTags, mutationDisabled, mutationNotice)"
          :aria-label="`Retag ${item.service_key}`"
          :aria-describedby="
            retagChoiceDisabledReason(item, targetTags, mutationDisabled, mutationNotice)
              ? retagChoiceDescriptionId(item)
              : undefined
          "
          @click="emitRetagAction(emit, item, targetTags, mutationDisabled)"
        >
          Retag this service
        </n-button>
      </div>
      <dl>
        <div>
          <dt>Image</dt>
          <dd>
            <code class="wrap-anywhere">{{ item.image }}</code>
          </dd>
        </div>
        <div>
          <dt>Runtime</dt>
          <dd class="retag-runtime-review">
            <n-tag
              size="small"
              :type="runtimeStateTagType(item)"
              :bordered="false"
            >
              {{ runtimeStateLabel(item) }}
            </n-tag>
            <span>{{ runtimeStateDetail(item) }}</span>
          </dd>
        </div>
        <div>
          <dt>Tracking</dt>
          <dd>{{ trackingLabel(item) }} ({{ item.tracking_tag_source || "unknown" }})</dd>
        </div>
        <div>
          <dt>Candidate</dt>
          <dd>
            <span>{{ candidateLabel(item) }}</span>
            <a
              v-if="item.candidate_link_url"
              class="text-link retag-source-link"
              :href="item.candidate_link_url"
              target="_blank"
              rel="noreferrer"
            >
              {{ item.candidate_link_label || "Open source" }}
            </a>
            <span
              v-if="item.candidate_warning"
              class="release-notes-reason"
            >
              {{ item.candidate_warning }}
            </span>
          </dd>
        </div>
        <div>
          <dt>Final image</dt>
          <dd>
            <code class="wrap-anywhere">{{ item.final_image ? displayDigest(item.final_image) : "None" }}</code>
          </dd>
        </div>
        <div>
          <dt>Target tag</dt>
          <dd class="retag-target-field">
            <n-input
              :value="retagTargetTagValue(item, targetTags)"
              size="small"
              class="tag-override-input retag-target-input"
              :placeholder="item.proposed_tag || 'Enter tag'"
              :disabled="mutationDisabled"
              :status="
                retagChoice(item, choices, targetTags) === 'switch-to-concrete' &&
                retagTargetTagValidationError(item, targetTags)
                  ? 'error'
                  : undefined
              "
              :title="
                retagChoice(item, choices, targetTags) === 'switch-to-concrete'
                  ? retagTargetTagValidationError(item, targetTags) || undefined
                  : undefined
              "
              :input-props="{
                'aria-label': `Target tag for ${item.service_key}`,
                'aria-invalid':
                  retagChoice(item, choices, targetTags) === 'switch-to-concrete' &&
                  retagTargetTagValidationError(item, targetTags)
                    ? 'true'
                    : 'false',
                'aria-describedby':
                  retagChoice(item, choices, targetTags) === 'switch-to-concrete' &&
                  retagTargetTagValidationError(item, targetTags)
                    ? retagTargetTagErrorId(item)
                    : undefined,
              }"
              @update:value="emit('target-tag-update', item, String($event))"
            />
            <span
              v-if="
                retagChoice(item, choices, targetTags) === 'switch-to-concrete' &&
                retagTargetTagValidationError(item, targetTags)
              "
              class="retag-input-error"
              :id="retagTargetTagErrorId(item)"
            >
              {{ retagTargetTagValidationError(item, targetTags) }}
            </span>
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
              :value="retagChoice(item, choices, targetTags)"
              size="small"
              role="radiogroup"
              :aria-label="`Retag choice for ${item.service_key}`"
              :aria-describedby="
                retagChoiceDisabledReason(item, targetTags, mutationDisabled, mutationNotice)
                  ? retagChoiceDescriptionId(item)
                  : undefined
              "
              @update:value="emitRetagChoice(emit, item, String($event), targetTags)"
            >
              <n-radio-button value="keep-current">Keep</n-radio-button>
              <n-radio-button
                value="switch-to-concrete"
                :disabled="!canEnableRetagTargetChoice(item, targetTags) || mutationDisabled"
                :title="retagTargetChoiceTitle(item, targetTags, mutationNotice)"
              >
                Retag
              </n-radio-button>
            </n-radio-group>
            <span
              v-if="retagChoiceDisabledReason(item, targetTags, mutationDisabled, mutationNotice)"
              :id="retagChoiceDescriptionId(item)"
              class="retag-choice-help"
            >
              {{ retagChoiceDisabledReason(item, targetTags, mutationDisabled, mutationNotice) }}
            </span>
            <n-tag
              v-if="canSwitchToConcrete(item)"
              size="small"
              type="info"
              :bordered="false"
            >
              Automatch ready
            </n-tag>
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

.retag-card-primary-action {
  display: flex;
}

.retag-one-service-button {
  width: 100%;
}

.retag-source-link {
  width: fit-content;
  font-size: 0.84rem;
}

.retag-runtime-review {
  align-items: flex-start;
  display: grid;
  gap: 4px;
}

.retag-target-field {
  align-items: stretch;
  display: grid;
  gap: 4px;
}

.retag-input-error {
  color: var(--color-warning-fg);
  font-size: 0.78rem;
  line-height: 1.35;
}

.retag-choice-help {
  color: var(--color-muted-text);
  font-size: 0.78rem;
  line-height: 1.35;
}

@media (--wud-data-cards) {
  .retag-card dl > div {
    grid-template-columns: minmax(0, 1fr);
  }

  .retag-card :deep(.n-radio-group) {
    display: flex;
    width: 100%;
  }

  .retag-card :deep(.n-radio-button) {
    flex: 1 1 0;
    min-height: var(--size-touch-target);
  }
}
</style>
