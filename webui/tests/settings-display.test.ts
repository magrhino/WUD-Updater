import { describe, expect, it } from "vitest";

import {
  coreUpdateTourStatusLabel,
  coreUpdateTourStepLabel,
  displayValue,
  entryCountLabel,
  managedOptions,
  secretRows,
  SETTINGS_NAV_GROUPS,
  settingRows,
  sourceLabel,
  sourceTagType,
  THEME_PREFERENCE_LABELS,
} from "../src/views/settings/settingsDisplay";
import { settingsResponse } from "./helpers/fixtures";

describe("settings display helpers", () => {
  it("maps settings entries to disclosure rows", () => {
    const configured = settingsResponse().updater[0];
    const requestScoped = settingsResponse().webui.find(
      (entry) => entry.source === "request",
    )!;

    expect(displayValue("")).toBe("unset");
    expect(entryCountLabel([configured])).toBe("1 value");
    expect(entryCountLabel([configured, requestScoped])).toBe("2 values");
    expect(sourceLabel(configured)).toBe("Configured");
    expect(sourceTagType(configured)).toBe("success");
    expect(sourceLabel(requestScoped)).toBe("Request scoped");
    expect(sourceTagType(requestScoped)).toBe("info");

    expect(settingRows([configured])[0]).toMatchObject({
      key: "DOCKER_BASE",
      detail: "Default: /srv/docker",
      valueKind: "code",
      tagLabel: "Configured",
      tagType: "success",
    });
  });

  it("redacts secret row values", () => {
    expect(secretRows(settingsResponse().secrets)).toContainEqual(
      expect.objectContaining({
        key: "GITHUB_TOKEN",
        value: "Raw value hidden",
        valueClass: "settings-redacted-value",
        tagLabel: "Configured",
        tagType: "success",
      }),
    );
  });

  it("labels managed options and core tour state", () => {
    const themeEntry = settingsResponse().managed.find(
      (entry) => entry.key === "theme_preference",
    );

    expect(managedOptions(themeEntry, THEME_PREFERENCE_LABELS)).toEqual([
      { label: "System theme", value: "system" },
      { label: "Light theme", value: "light" },
      { label: "Dark theme", value: "dark" },
    ]);
    expect(coreUpdateTourStatusLabel("completed")).toBe("Completed");
    expect(coreUpdateTourStepLabel("runs_history")).toBe("History");
  });

  it("keeps the settings nav grouped by workflow", () => {
    expect(SETTINGS_NAV_GROUPS).toEqual([
      {
        id: "operate",
        label: "Operate",
        links: [
          { id: "settings-actions", label: "Actions" },
          { id: "settings-preferences", label: "Preferences" },
        ],
      },
      {
        id: "configuration",
        label: "Configuration",
        links: [
          { id: "settings-runtime", label: "Overview" },
          { id: "settings-paths", label: "Paths" },
          { id: "settings-behavior", label: "Behavior" },
          { id: "settings-webui", label: "WebUI safety" },
          { id: "settings-secrets", label: "Secrets" },
        ],
      },
      {
        id: "support",
        label: "Support",
        links: [
          { id: "settings-diagnostics", label: "Diagnostics" },
          { id: "settings-docs", label: "Docs" },
        ],
      },
    ]);
  });
});
