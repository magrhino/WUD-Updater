import {
  computed,
  watch,
  watchEffect,
  type ComputedRef,
  type WritableComputedRef,
} from "vue";
import { useColorMode } from "@vueuse/core";
import { darkTheme, type GlobalTheme, type GlobalThemeOverrides } from "naive-ui";

import { useAuthStore } from "./stores/auth";
import { useSettingsStore } from "./stores/settings";
import { touchTargetSizePx } from "./touchTargets";
import { runInBackground } from "./utils/promises";

export type EffectiveTheme = "light" | "dark";
export type ThemePreference = "system" | EffectiveTheme;

type StoredThemePreference = "auto" | EffectiveTheme;

export const themeStorageKey = "theme-preference";
export const themePreferenceOrder: readonly ThemePreference[] = [
  "system",
  "light",
  "dark",
] as const;

const fontTokens = {
  sans: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  mono: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
} as const;

type ThemeTokens = {
  font: typeof fontTokens;
  color: {
    ink: string;
    textSecondary: string;
    bodyBg: string;
    surface: string;
    sidebar: string;
    sidebarHover: string;
    sidebarText: string;
    sidebarMuted: string;
    mutedText: string;
    border: string;
    borderSubtle: string;
    borderDashed: string;
    borderHover: string;
    panelTint: string;
    tableHead: string;
    actionBlue: string;
    actionBlueHover: string;
    actionBluePressed: string;
    operationalTeal: string;
    operationalTealHover: string;
    operationalTealPressed: string;
    warningFg: string;
    warningBg: string;
    warningHover: string;
    warningPressed: string;
    errorFg: string;
    errorBg: string;
    errorHover: string;
    errorPressed: string;
    loginBg: string;
    logBg: string;
    logText: string;
    codeText: string;
  };
  shadow: {
    panelLift: string;
  };
};

const lightDesignTokens: ThemeTokens = {
  font: {
    ...fontTokens,
  },
  color: {
    ink: "#172026",
    textSecondary: "#43525a",
    bodyBg: "#f5f7f8",
    surface: "#ffffff",
    sidebar: "#132126",
    sidebarHover: "#21383f",
    sidebarText: "#f7fbfc",
    sidebarMuted: "#c9d6d9",
    mutedText: "#627177",
    border: "#dbe3e6",
    borderSubtle: "#e6ecef",
    borderDashed: "#cbd8dd",
    borderHover: "#86b7dd",
    panelTint: "#f9fbfc",
    tableHead: "#f0f5f6",
    actionBlue: "#0f6fbd",
    actionBlueHover: "#0d5f9f",
    actionBluePressed: "#0b4e84",
    operationalTeal: "#137a63",
    operationalTealHover: "#106a58",
    operationalTealPressed: "#0c5748",
    warningFg: "#663c00",
    warningBg: "#fff1d6",
    warningHover: "#824d00",
    warningPressed: "#4d2d00",
    errorFg: "#b42318",
    errorBg: "#fde8e6",
    errorHover: "#961b12",
    errorPressed: "#7a160f",
    loginBg: "#eef3f5",
    logBg: "#0f171a",
    logText: "#d8e8df",
    codeText: "#263239",
  },
  shadow: {
    panelLift: "0 1px 2px rgb(23 32 38 / 0.04)",
  },
} as const;

const darkDesignTokens: ThemeTokens = {
  font: {
    ...fontTokens,
  },
  color: {
    ink: "#eef7f8",
    textSecondary: "#c2d0d4",
    bodyBg: "#0f171a",
    surface: "#162126",
    sidebar: "#0a1215",
    sidebarHover: "#1b3036",
    sidebarText: "#f4fbfc",
    sidebarMuted: "#a8bdc3",
    mutedText: "#9badb3",
    border: "#31444b",
    borderSubtle: "#26383f",
    borderDashed: "#3a5159",
    borderHover: "#5d9dc9",
    panelTint: "#111c20",
    tableHead: "#1c2b31",
    actionBlue: "#72bdf0",
    actionBlueHover: "#8fcdf6",
    actionBluePressed: "#4fa6df",
    operationalTeal: "#58c5a6",
    operationalTealHover: "#73d7bb",
    operationalTealPressed: "#39ab8d",
    warningFg: "#ffe0a3",
    warningBg: "#38280e",
    warningHover: "#fff0c7",
    warningPressed: "#ffc766",
    errorFg: "#ff9286",
    errorBg: "#3a1d1b",
    errorHover: "#ffafa8",
    errorPressed: "#e77569",
    loginBg: "#0d1518",
    logBg: "#081013",
    logText: "#d8e8df",
    codeText: "#d8e7eb",
  },
  shadow: {
    panelLift: "0 1px 2px rgb(0 0 0 / 0.24)",
  },
};

export const themeDesignTokens = {
  light: lightDesignTokens,
  dark: darkDesignTokens,
} as const;

export const designTokens = themeDesignTokens.light;

function cssVariablesFor(tokens: ThemeTokens): Record<string, string> {
  return {
    "--font-sans": tokens.font.sans,
    "--font-mono": tokens.font.mono,
    "--color-ink": tokens.color.ink,
    "--color-text-secondary": tokens.color.textSecondary,
    "--color-body-bg": tokens.color.bodyBg,
    "--color-surface": tokens.color.surface,
    "--color-sidebar": tokens.color.sidebar,
    "--color-sidebar-hover": tokens.color.sidebarHover,
    "--color-sidebar-text": tokens.color.sidebarText,
    "--color-sidebar-muted": tokens.color.sidebarMuted,
    "--color-muted-text": tokens.color.mutedText,
    "--color-border": tokens.color.border,
    "--color-border-subtle": tokens.color.borderSubtle,
    "--color-border-dashed": tokens.color.borderDashed,
    "--color-border-hover": tokens.color.borderHover,
    "--color-panel-tint": tokens.color.panelTint,
    "--color-table-head": tokens.color.tableHead,
    "--color-action-blue": tokens.color.actionBlue,
    "--color-action-blue-hover": tokens.color.actionBlueHover,
    "--color-action-blue-pressed": tokens.color.actionBluePressed,
    "--color-operational-teal": tokens.color.operationalTeal,
    "--color-operational-teal-hover": tokens.color.operationalTealHover,
    "--color-operational-teal-pressed": tokens.color.operationalTealPressed,
    "--color-warning-fg": tokens.color.warningFg,
    "--color-warning-bg": tokens.color.warningBg,
    "--color-warning-hover": tokens.color.warningHover,
    "--color-warning-pressed": tokens.color.warningPressed,
    "--color-error-fg": tokens.color.errorFg,
    "--color-error-bg": tokens.color.errorBg,
    "--color-error-hover": tokens.color.errorHover,
    "--color-error-pressed": tokens.color.errorPressed,
    "--color-login-bg": tokens.color.loginBg,
    "--color-log-bg": tokens.color.logBg,
    "--color-log-text": tokens.color.logText,
    "--color-code-text": tokens.color.codeText,
    "--shadow-panel-lift": tokens.shadow.panelLift,
    "--size-touch-target": `${touchTargetSizePx}px`,
  };
}

function themeOverridesFor(tokens: ThemeTokens): GlobalThemeOverrides {
  return {
    common: {
      baseColor: tokens.color.surface,
      bodyColor: tokens.color.bodyBg,
      cardColor: tokens.color.surface,
      modalColor: tokens.color.surface,
      tableColor: tokens.color.surface,
      tableHeaderColor: tokens.color.tableHead,
      hoverColor: tokens.color.panelTint,
      inputColor: tokens.color.surface,
      inputColorDisabled: tokens.color.panelTint,
      borderColor: tokens.color.border,
      dividerColor: tokens.color.borderSubtle,
      primaryColor: tokens.color.operationalTeal,
      primaryColorHover: tokens.color.operationalTealHover,
      primaryColorPressed: tokens.color.operationalTealPressed,
      primaryColorSuppl: tokens.color.operationalTeal,
      infoColor: tokens.color.actionBlue,
      infoColorHover: tokens.color.actionBlueHover,
      infoColorPressed: tokens.color.actionBluePressed,
      infoColorSuppl: tokens.color.actionBlue,
      successColor: tokens.color.operationalTeal,
      successColorHover: tokens.color.operationalTealHover,
      successColorPressed: tokens.color.operationalTealPressed,
      successColorSuppl: tokens.color.operationalTeal,
      warningColor: tokens.color.warningFg,
      warningColorHover: tokens.color.warningHover,
      warningColorPressed: tokens.color.warningPressed,
      warningColorSuppl: tokens.color.warningFg,
      errorColor: tokens.color.errorFg,
      errorColorHover: tokens.color.errorHover,
      errorColorPressed: tokens.color.errorPressed,
      errorColorSuppl: tokens.color.errorFg,
      textColorBase: tokens.color.ink,
      textColor1: tokens.color.ink,
      textColor2: tokens.color.textSecondary,
      textColor3: tokens.color.mutedText,
      textColorDisabled: tokens.color.mutedText,
      placeholderColor: tokens.color.mutedText,
      placeholderColorDisabled: tokens.color.mutedText,
      iconColor: tokens.color.mutedText,
      fontFamily: tokens.font.sans,
      fontFamilyMono: tokens.font.mono,
      fontSize: "1rem",
      borderRadius: "7px",
      borderRadiusSmall: "7px",
    },
    Tag: {
      // Naive Tag color* slots are backgrounds; text/border slots use foreground tokens.
      borderWarning: `1px solid ${tokens.color.warningFg}`,
      colorBorderedWarning: tokens.color.warningBg,
      colorWarning: tokens.color.warningBg,
      closeIconColorWarning: tokens.color.warningFg,
      closeIconColorHoverWarning: tokens.color.warningHover,
      closeIconColorPressedWarning: tokens.color.warningPressed,
      textColorWarning: tokens.color.warningFg,
      borderError: `1px solid ${tokens.color.errorFg}`,
      colorBorderedError: tokens.color.errorBg,
      colorError: tokens.color.errorBg,
      closeIconColorError: tokens.color.errorFg,
      closeIconColorHoverError: tokens.color.errorHover,
      closeIconColorPressedError: tokens.color.errorPressed,
      textColorError: tokens.color.errorFg,
    },
  };
}

export const themeOverridesByMode: Record<EffectiveTheme, GlobalThemeOverrides> = {
  light: themeOverridesFor(themeDesignTokens.light),
  dark: themeOverridesFor(themeDesignTokens.dark),
};

export const themeOverrides = themeOverridesByMode.light;

export const themePreferenceLabels: Record<ThemePreference, string> = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
};

function normalizeStoredPreference(value: StoredThemePreference): ThemePreference {
  return value === "auto" ? "system" : value;
}

function storedThemePreference(value: ThemePreference): StoredThemePreference {
  return value === "system" ? "auto" : value;
}

export function nextThemePreference(current: ThemePreference): ThemePreference {
  const index = themePreferenceOrder.indexOf(current);
  return themePreferenceOrder[(index + 1) % themePreferenceOrder.length];
}

export function detectInitialEffectiveTheme(): EffectiveTheme {
  if (typeof window === "undefined") {
    return "light";
  }

  try {
    const stored = window.localStorage.getItem(themeStorageKey);
    if (stored === "dark" || stored === "light") {
      return stored;
    }
  } catch {
    // Storage can be unavailable in locked-down browsers; system preference still applies.
  }

  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyThemeCssVars(root?: HTMLElement): void;
export function applyThemeCssVars(
  theme: EffectiveTheme,
  root?: HTMLElement,
): void;
export function applyThemeCssVars(
  themeOrRoot: EffectiveTheme | HTMLElement = "light",
  root = document.documentElement,
): void {
  const theme = typeof themeOrRoot === "string" ? themeOrRoot : "light";
  const target = typeof themeOrRoot === "string" ? root : themeOrRoot;
  const tokens = themeDesignTokens[theme];

  for (const [name, value] of Object.entries(cssVariablesFor(tokens))) {
    target.style.setProperty(name, value);
  }

  target.dataset.theme = theme;
  target.style.setProperty("color-scheme", theme);
}

export function useWebuiTheme(): {
  preference: WritableComputedRef<ThemePreference>;
  effectiveTheme: ComputedRef<EffectiveTheme>;
  nextPreference: ComputedRef<ThemePreference>;
  naiveTheme: ComputedRef<GlobalTheme | undefined>;
  themeOverrides: ComputedRef<GlobalThemeOverrides>;
  cycleThemePreference: () => void;
} {
  const colorMode = useColorMode({
    attribute: "data-theme",
    disableTransition: true,
    initialValue: "auto",
    storageKey: themeStorageKey,
  });

  const preference = computed<ThemePreference>({
    get: () => normalizeStoredPreference(colorMode.store.value),
    set: (value) => {
      colorMode.store.value = storedThemePreference(value);
    },
  });
  const effectiveTheme = computed<EffectiveTheme>(() =>
    colorMode.state.value === "dark" ? "dark" : "light",
  );
  const nextPreference = computed(() => nextThemePreference(preference.value));
  const naiveTheme = computed(() =>
    effectiveTheme.value === "dark" ? darkTheme : undefined,
  );
  const activeThemeOverrides = computed(
    () => themeOverridesByMode[effectiveTheme.value],
  );
  const auth = useAuthStore();
  const settings = useSettingsStore();
  const managedThemePreference = computed(() =>
    settings.settings?.managed.find((entry) => entry.key === "theme_preference"),
  );

  watchEffect(() => {
    applyThemeCssVars(effectiveTheme.value);
  });

  watch(
    () => auth.authenticated,
    (authenticated) => {
      if (authenticated && settings.settings === null) {
        runInBackground(settings.loadSettings());
      }
    },
    { immediate: true },
  );

  watch(
    [managedThemePreference, () => auth.authenticated],
    ([entry, authenticated]) => {
      if (
        authenticated &&
        entry?.source === "configured" &&
        (entry.value === "system" ||
          entry.value === "light" ||
          entry.value === "dark") &&
        preference.value !== entry.value
      ) {
        preference.value = entry.value;
      }
    },
    { immediate: true },
  );

  return {
    preference,
    effectiveTheme,
    nextPreference,
    naiveTheme,
    themeOverrides: activeThemeOverrides,
    cycleThemePreference: () => {
      preference.value = nextPreference.value;
    },
  };
}
