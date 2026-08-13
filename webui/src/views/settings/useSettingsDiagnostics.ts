import { ref } from "vue";
import { useClipboard } from "@vueuse/core";

import type { DiagnosticsSupportBundleResponse } from "../../api/client";
import { useConnectionStore } from "../../stores/connection";

function diagnosticsOperationError(error_: unknown, fallback: string): string {
  return error_ instanceof Error ? error_.message : fallback;
}

export function useSettingsDiagnostics(
  options: {
    reuseLoadedText?: boolean;
    artifactLabel?: string;
    downloadFilename?: string;
    selectBundle?: (bundle: DiagnosticsSupportBundleResponse) => unknown;
  } = {},
) {
  const connection = useConnectionStore();
  const { copy, isSupported: isClipboardSupported } = useClipboard();
  const artifactLabel = options.artifactLabel ?? "Diagnostics";
  const diagnosticsDownloading = ref(false);
  const diagnosticsText = ref("");
  const diagnosticsMessage = ref("");
  const diagnosticsError = ref("");

  async function loadSupportBundleText(): Promise<string | null> {
    diagnosticsMessage.value = "";
    diagnosticsError.value = "";
    diagnosticsDownloading.value = true;
    try {
      const bundle = await connection.diagnosticsSupportBundle();
      const text = JSON.stringify(
        options.selectBundle?.(bundle) ?? bundle,
        null,
        2,
      );
      diagnosticsText.value = text;
      return text;
    } catch (error_) {
      diagnosticsError.value = diagnosticsOperationError(
        error_,
        `Failed to load ${artifactLabel.toLowerCase()}`,
      );
      return null;
    } finally {
      diagnosticsDownloading.value = false;
    }
  }

  async function refreshSupportBundle(): Promise<void> {
    const text = await loadSupportBundleText();
    if (text !== null) {
      diagnosticsMessage.value = `${artifactLabel} loaded.`;
    }
  }

  async function copySupportBundle(): Promise<void> {
    try {
      diagnosticsMessage.value = "";
      diagnosticsError.value = "";
      const text =
        (options.reuseLoadedText && diagnosticsText.value) ||
        (await loadSupportBundleText());
      if (text === null) {
        return;
      }
      await copy(text);
      // Since copied is a ref updated by useClipboard asynchronously,
      // we just assume success if it didn't throw and set a generic message.
      diagnosticsMessage.value = `${artifactLabel} copied to clipboard.`;
    } catch (error_) {
      diagnosticsMessage.value = "";
      diagnosticsError.value = diagnosticsOperationError(
        error_,
        `Failed to copy ${artifactLabel.toLowerCase()}`,
      );
    }
  }

  async function downloadSupportBundle(): Promise<void> {
    let url: string | null = null;
    try {
      diagnosticsMessage.value = "";
      diagnosticsError.value = "";
      const text =
        (options.reuseLoadedText && diagnosticsText.value) ||
        (await loadSupportBundleText());
      if (text === null) {
        return;
      }
      const blob = new Blob([text], { type: "application/json" });
      url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = options.downloadFilename ?? "wudup-diagnostics.json";
      a.click();
      URL.revokeObjectURL(url);
      url = null;
      diagnosticsMessage.value = `${artifactLabel} downloaded successfully.`;
    } catch (error_) {
      if (url !== null) {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // Keep the original download error visible to the user.
        }
      }
      diagnosticsMessage.value = "";
      diagnosticsError.value = diagnosticsOperationError(
        error_,
        `Failed to download ${artifactLabel.toLowerCase()}`,
      );
    }
  }

  return {
    diagnosticsDownloading,
    diagnosticsText,
    diagnosticsMessage,
    diagnosticsError,
    isClipboardSupported,
    refreshSupportBundle,
    copySupportBundle,
    downloadSupportBundle,
  };
}
