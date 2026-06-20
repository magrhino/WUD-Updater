import type {
  SecretSettingStatus,
  SettingsEntry,
  SettingsResponse,
} from "./api/client";

const SANITIZED_SNIPPET_ENTRY_EXCLUSIONS = new Set([
  "HOST_DOCKER_BASE",
  "WUD_WEB_AUTH_REQUIRED",
  "WUD_WEB_SECURE_COOKIES_EFFECTIVE",
  "WUD_WEB_STATIC_SPA_AVAILABLE",
  "WUD_WEB_AUTO_UPDATE_SCHEDULER_ENABLED",
]);

export function sanitizedSettingsEntries(
  settings: SettingsResponse,
): SettingsEntry[] {
  return [...settings.updater, ...settings.webui].filter(
    (entry) =>
      !SANITIZED_SNIPPET_ENTRY_EXCLUSIONS.has(entry.name) &&
      !(
        entry.name === "WUD_COMPOSE_IGNORE_PATHS" &&
        !entry.configured &&
        !entry.value
      ),
  );
}

export function buildSettingsEnvSnippet(settings: SettingsResponse): string {
  const lines = sanitizedSettingsEntries(settings).map(
    (entry) => `${entry.name}=${quoteEnvValue(entry.value)}`,
  );
  appendSecretComments(lines, settings.secrets, "# ");
  return `${lines.join("\n")}\n`;
}

export function buildSettingsComposeSnippet(settings: SettingsResponse): string {
  const lines = ["services:", "  wudup:", "    environment:"];
  lines.push(
    ...sanitizedSettingsEntries(settings).map(
      (entry) => `      ${entry.name}: ${quoteYamlValue(entry.value)}`,
    ),
  );
  appendSecretComments(lines, settings.secrets, "      # ");
  return `${lines.join("\n")}\n`;
}

function appendSecretComments(
  lines: string[],
  secretEntries: SecretSettingStatus[],
  prefix: string,
): void {
  if (secretEntries.length === 0) {
    return;
  }
  lines.push("");
  lines.push(`${prefix}Secret values are intentionally omitted.`);
  lines.push(
    ...secretEntries.map(
      (secret) =>
        `${prefix}${secret.name} omitted: ${
          secret.configured ? "configured" : "not configured"
        }`,
    ),
  );
}

function quoteEnvValue(value: string): string {
  return `"${value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\$/g, "\\$")}"`;
}

function quoteYamlValue(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}
