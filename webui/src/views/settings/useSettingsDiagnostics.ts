import { ref } from "vue";
import { useClipboard } from "@vueuse/core";

import { useConnectionStore } from "../../stores/connection";

function diagnosticsOperationError(exc: unknown, fallback: string): string {
  return exc instanceof Error ? exc.message : fallback;
}

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
      diagnosticsError.value = diagnosticsOperationError(
        exc,
        "Failed to load support bundle",
      );
      return null;
    } finally {
      diagnosticsDownloading.value = false;
    }
  }

  async function copySupportBundle(): Promise<void> {
    try {
      const text = await loadSupportBundleText();
      if (text === null) {
        return;
      }
      await copy(text);
      // Since copied is a ref updated by useClipboard asynchronously,
      // we just assume success if it didn't throw and set a generic message.
      diagnosticsMessage.value = "Diagnostics copied to clipboard.";
    } catch (exc) {
      diagnosticsMessage.value = "";
      diagnosticsError.value = diagnosticsOperationError(
        exc,
        "Failed to copy support bundle",
      );
    }
  }

  async function downloadSupportBundle(): Promise<void> {
    let url: string | null = null;
    try {
      const text = await loadSupportBundleText();
      if (text === null) {
        return;
      }
      const blob = new Blob([text], { type: "application/json" });
      url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "wud-updater-diagnostics.json";
      a.click();
      URL.revokeObjectURL(url);
      url = null;
      diagnosticsMessage.value = "Diagnostics downloaded successfully.";
    } catch (exc) {
      if (url !== null) {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // Keep the original download error visible to the user.
        }
      }
      diagnosticsMessage.value = "";
      diagnosticsError.value = diagnosticsOperationError(
        exc,
        "Failed to download support bundle",
      );
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
