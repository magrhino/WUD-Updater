import { describe, expect, it, vi } from "vitest";

import {
  applyThemeCssVars,
  designTokens,
  detectInitialEffectiveTheme,
  themeDesignTokens,
  themeOverrides,
  themeOverridesByMode,
  themeStorageKey,
} from "../src/theme";

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
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-color-scheme: dark)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    expect(detectInitialEffectiveTheme()).toBe("dark");
  });
});
