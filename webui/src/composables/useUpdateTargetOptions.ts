import { computed } from "vue";
import type { SelectOption } from "naive-ui";

import type { UpdateTargetItem } from "../api/client";
import { useUpdatesStore } from "../stores/updates";

export function useUpdateTargetOptions() {
  const updates = useUpdatesStore();
  const targets = computed(() => updates.updateTargets?.items ?? []);
  const serviceKeyOptions = computed(() =>
    uniqueOptions(
      targets.value
        .filter((target) => target.service_key)
        .map((target) => ({
          label: target.service_key,
          value: target.service_key,
        })),
    ),
  );
  const imageRepoOptions = computed(() =>
    uniqueOptions(
      targets.value
        .filter((target) => target.image_repo)
        .map((target) => ({
          label: target.image_repo,
          value: target.image_repo,
        })),
    ),
  );

  function targetForServiceKey(serviceKey: string): UpdateTargetItem | undefined {
    return targets.value.find((target) => target.service_key === serviceKey);
  }

  function targetForImageRepo(imageRepo: string): UpdateTargetItem | undefined {
    return targets.value.find((target) => target.image_repo === imageRepo);
  }

  function tagOptionsForImageRepo(imageRepo: string): SelectOption[] {
    return uniqueOptions(
      targets.value
        .filter(
          (target) =>
            target.image_repo === imageRepo && target.current_tag.trim() !== "",
        )
        .map((target) => ({
          label: target.current_tag,
          value: target.current_tag,
        })),
    );
  }

  return {
    targets,
    serviceKeyOptions,
    imageRepoOptions,
    targetForServiceKey,
    targetForImageRepo,
    tagOptionsForImageRepo,
  };
}

function uniqueOptions(options: SelectOption[]): SelectOption[] {
  const seen = new Set<string>();
  const unique: SelectOption[] = [];
  for (const option of options) {
    const value = String(option.value ?? "");
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    unique.push(option);
  }
  return unique.sort((left, right) =>
    String(left.value ?? "").localeCompare(String(right.value ?? "")),
  );
}
