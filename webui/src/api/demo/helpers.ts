import type { PendingCleanupLine } from "../types";

export function cleanupLineKey(line: PendingCleanupLine): string {
  return `${line.line_no}\u0000${line.raw}`;
}

export function normalizeDemoComposeIgnorePaths(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  const paths: string[] = [];
  const seen = new Set<string>();
  for (const rawItem of trimmed.split(",")) {
    const item = rawItem.trim();
    const parts = item.split("/");
    if (
      !item ||
      item.startsWith("/") ||
      parts.some((part) => part === "" || part === "." || part === "..")
    ) {
      throw new Error(
        "compose_ignore_paths entries must be non-empty relative paths",
      );
    }
    if (!seen.has(item)) {
      seen.add(item);
      paths.push(item);
    }
  }
  return paths.join(", ");
}

export function repoKey(image: string): string {
  const digestless = image.trim().split("@sha256:")[0] ?? image.trim();
  const firstSlash = digestless.indexOf("/");
  const withoutRegistry =
    firstSlash === -1 || !isRegistryPrefix(digestless.slice(0, firstSlash))
      ? digestless
      : digestless.slice(firstSlash + 1);
  const lastSlash = withoutRegistry.lastIndexOf("/");
  const lastSegment = withoutRegistry.slice(lastSlash + 1);
  const tagSeparator = lastSegment.lastIndexOf(":");
  if (tagSeparator === -1) {
    return withoutRegistry;
  }
  return `${withoutRegistry.slice(0, lastSlash + 1)}${lastSegment.slice(0, tagSeparator)}`;
}

function isRegistryPrefix(value: string): boolean {
  return value.includes(".") || value.includes(":") || value === "localhost";
}

export function upsertBy<T>(items: T[], next: T, matches: (item: T) => boolean): T[] {
  const index = items.findIndex(matches);
  if (index === -1) {
    return [next, ...items];
  }
  const updated = [...items];
  updated[index] = next;
  return updated;
}

export function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function clone<T>(value: T): T {
  return structuredClone(value);
}
