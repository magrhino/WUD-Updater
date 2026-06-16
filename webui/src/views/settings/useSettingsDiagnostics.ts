import { ref } from "vue";
import { useClipboard } from "@vueuse/core";

import { useConnectionStore } from "../../stores/connection";

export function useSettingsDiagnostics() {
  const connection = useConnectionStore();
  const { copy, isSupported: isClipboardSupported } = useClipboard();
  const diagnosticsDownloading = ref(false);
  const diagnosticsMessage = ref("");
  const diagnosticsError = ref("");

  async function loadSupportBundleText(): Promise<string | null> {
    diagnosticsMessage.value = "";
    diagnosticsError.value = "";
    diagnosticsDownloading.value = true;
    try {
      const bundle = await connection.diagnosticsSupportBundle();
      return JSON.stringify(bundle, null, 2);
    } catch (exc) {
      diagnosticsError.value =
        exc instanceof Error ? exc.message : "Failed to load support bundle";
      return null;
    } finally {
      diagnosticsDownloading.value = false;
    }
  }

  async function copySupportBundle(): Promise<void> {
    const text = await loadSupportBundleText();
    if (text !== null) {
      await copy(text);
      // Since copied is a ref updated by useClipboard asynchronously,
      // we just assume success if it didn't throw and set a generic message.
      diagnosticsMessage.value = "Diagnostics copied to clipboard.";
    }
  }

  async function downloadSupportBundle(): Promise<void> {
    const text = await loadSupportBundleText();
    if (text !== null) {
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "wud-updater-diagnostics.json";
      a.click();
      URL.revokeObjectURL(url);
      diagnosticsMessage.value = "Diagnostics downloaded successfully.";
    }
  }

  return {
    diagnosticsDownloading,
    diagnosticsMessage,
    diagnosticsError,
    isClipboardSupported,
    copySupportBundle,
    downloadSupportBundle,
  };
}
