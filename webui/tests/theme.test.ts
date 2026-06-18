import { createPinia, setActivePinia } from "pinia";
import { effectScope, nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../src/stores/auth";
import { useSettingsStore } from "../src/stores/settings";
import {
  applyThemeCssVars,
  designTokens,
  detectInitialEffectiveTheme,
  themeDesignTokens,
  themeOverrides,
  themeOverridesByMode,
  themeStorageKey,
  useWebuiTheme,
} from "../src/theme";
import { authSession, settingsResponse } from "./helpers/fixtures";

function mockMatchMedia(prefersDark: boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" && prefersDark,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("webui theme tokens", () => {
  it("maps light design tokens to CSS variables and Naive UI overrides", () => {
    const root = document.createElement("div");

    applyThemeCssVars(root);

    expect(root.style.getPropertyValue("--color-operational-teal")).toBe(
      designTokens.color.operationalTeal,
    );
    expect(root.style.getPropertyValue("--color-table-head")).toBe(
      designTokens.color.tableHead,
    );
    expect(themeOverrides.common?.primaryColor).toBe(
      designTokens.color.operationalTeal,
    );
    expect(themeOverrides.common?.tableHeaderColor).toBe(
      designTokens.color.tableHead,
    );
  });

  it("maps dark design tokens to CSS variables and Naive UI overrides", () => {
    const root = document.createElement("div");

    applyThemeCssVars("dark", root);

    expect(root.dataset.theme).toBe("dark");
    expect(root.style.getPropertyValue("color-scheme")).toBe("dark");
    expect(root.style.getPropertyValue("--color-body-bg")).toBe(
      themeDesignTokens.dark.color.bodyBg,
    );
    expect(root.style.getPropertyValue("--color-table-head")).toBe(
      themeDesignTokens.dark.color.tableHead,
    );
    expect(themeOverridesByMode.dark.common?.primaryColor).toBe(
      themeDesignTokens.dark.color.operationalTeal,
    );
    expect(themeOverridesByMode.dark.common?.tableHeaderColor).toBe(
      themeDesignTokens.dark.color.tableHead,
    );
  });

  it("detects the initial effective theme from stored preference or system", () => {
    window.localStorage.setItem(themeStorageKey, "dark");
    expect(detectInitialEffectiveTheme()).toBe("dark");

    window.localStorage.setItem(themeStorageKey, "light");
    expect(detectInitialEffectiveTheme()).toBe("light");

    window.localStorage.setItem(themeStorageKey, "auto");
    mockMatchMedia(true);

    expect(detectInitialEffectiveTheme()).toBe("dark");
  });

  it("reapplies a configured theme preference when authentication changes", async () => {
    setActivePinia(createPinia());
    mockMatchMedia(false);
    window.localStorage.setItem(themeStorageKey, "light");

    const scope = effectScope();
    try {
      const theme = scope.run(() => useWebuiTheme());
      if (!theme) {
        throw new Error("Theme composable did not initialize");
      }
      const auth = useAuthStore();
      const settings = useSettingsStore();
      const configuredSettings = settingsResponse();
      settings.settings = {
        ...configuredSettings,
        managed: configuredSettings.managed.map((entry) =>
          entry.key === "theme_preference"
            ? { ...entry, value: "dark", source: "configured" }
            : entry,
        ),
      };
      await nextTick();

      expect(theme.preference.value).toBe("light");

      auth.session = authSession({ authenticated: true });
      await nextTick();

      expect(theme.preference.value).toBe("dark");
    } finally {
      scope.stop();
    }
  });
});
