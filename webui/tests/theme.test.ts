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
import { touchTargetSizePx } from "../src/touchTargets";
import { authSession, settingsResponse } from "./helpers/fixtures";

function relativeLuminance(hex: string): number {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    ?.map((value) => Number.parseInt(value, 16) / 255);
  if (!channels || channels.length !== 3) {
    throw new Error(`Expected a six-digit hex color, received ${hex}`);
  }
  const [red, green, blue] = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(first: string, second: string): number {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  return (
    (Math.max(firstLuminance, secondLuminance) + 0.05) /
    (Math.min(firstLuminance, secondLuminance) + 0.05)
  );
}

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
    expect(root.style.getPropertyValue("--color-warning-bg")).toBe(
      designTokens.color.warningBg,
    );
    expect(root.style.getPropertyValue("--size-touch-target")).toBe(
      `${touchTargetSizePx}px`,
    );
    expect(themeOverrides.common?.primaryColor).toBe(
      designTokens.color.operationalTeal,
    );
    expect(themeOverrides.common?.tableHeaderColor).toBe(
      designTokens.color.tableHead,
    );
    expect(themeOverrides.common?.fontSize).toBe("1rem");
    expect(themeOverrides.Tag?.colorError).toBe(designTokens.color.errorBg);
    expect(themeOverrides.Tag?.textColorError).toBe(
      designTokens.color.errorFg,
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

  it("keeps light muted text at WCAG AA contrast", () => {
    expect(
      contrastRatio(
        themeDesignTokens.light.color.mutedText,
        themeDesignTokens.light.color.tableHead,
      ),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrastRatio(
        themeDesignTokens.light.color.mutedText,
        themeDesignTokens.light.color.bodyBg,
      ),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it("detects the initial effective theme from stored preference or system", () => {
    window.localStorage.setItem(themeStorageKey, "dark");
    expect(detectInitialEffectiveTheme()).toBe("dark");

    globalThis.localStorage.setItem(themeStorageKey, "light");
    expect(detectInitialEffectiveTheme()).toBe("light");

    window.localStorage.setItem(themeStorageKey, "auto");
    mockMatchMedia(true);

    expect(detectInitialEffectiveTheme()).toBe("dark");
  });

  it("reapplies a configured theme preference when authentication changes", async () => {
    setActivePinia(createPinia());
    mockMatchMedia(false);
    globalThis.localStorage.setItem(themeStorageKey, "light");

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
