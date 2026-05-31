import { describe, expect, it } from "vitest";

import {
  buildSettingsComposeSnippet,
  buildSettingsEnvSnippet,
  sanitizedSettingsEntries,
} from "../src/settingsSnippets";
import { settingsResponse } from "./helpers/fixtures";

describe("settings snippet helpers", () => {
  it("builds sanitized env and Compose snippets without secret values", () => {
    const settings = settingsResponse({
      secrets: [
        { name: "WUD_WEB_TOKEN", configured: false },
        { name: "GITHUB_TOKEN", configured: true },
        { name: "DISCORD_WEBHOOK", configured: false },
      ],
    });

    expect(sanitizedSettingsEntries(settings).map((entry) => entry.name)).not.toContain(
      "HOST_DOCKER_BASE",
    );

    const envSnippet = buildSettingsEnvSnippet(settings);
    const composeSnippet = buildSettingsComposeSnippet(settings);

    expect(envSnippet).toContain('DOCKER_BASE="/srv/docker"');
    expect(envSnippet).toContain("# GITHUB_TOKEN omitted: configured");
    expect(composeSnippet).toContain("services:");
    expect(composeSnippet).toContain('      DOCKER_BASE: "/srv/docker"');
    expect(composeSnippet).toContain("      # DISCORD_WEBHOOK omitted: not configured");
    expect(`${envSnippet}\n${composeSnippet}`).not.toContain("github-token-secret");
  });
});
