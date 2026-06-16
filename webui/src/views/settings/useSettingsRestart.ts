import { computed, ref } from "vue";

import { useConnectionStore } from "../../stores/connection";
import { useSettingsSafety } from "./useSettingsSafety";

export function useSettingsRestart() {
  const connection = useConnectionStore();
  const safety = useSettingsSafety();
  const restartDialogVisible = ref(false);
  const restartMessage = ref("");
  const restartError = ref("");
  const restartButtonDisabled = computed(
    () => connection.loading || safety.restartDisabledReason.value !== "",
  );

  function openRestartDialog(): void {
    if (restartButtonDisabled.value) {
      return;
    }
    restartMessage.value = "";
    restartError.value = "";
    restartDialogVisible.value = true;
  }

  async function confirmRestartContainer(): Promise<void> {
    if (restartButtonDisabled.value) {
      return;
    }
    restartMessage.value = "";
    restartError.value = "";
    try {
      const response = await connection.restartContainer();
      restartDialogVisible.value = false;
      restartMessage.value = `Restart requested for ${response.container}. The WebUI may disconnect while the container comes back.`;
    } catch (exc) {
      restartError.value =
        exc instanceof Error ? exc.message : "Container restart failed";
    }
  }

  return {
    ...safety,
    connection,
    restartButtonDisabled,
    restartDialogVisible,
    restartMessage,
    restartError,
    openRestartDialog,
    confirmRestartContainer,
  };
}
