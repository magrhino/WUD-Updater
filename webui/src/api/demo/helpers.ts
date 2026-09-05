import type { PendingCleanupLine } from "../types";

export function cleanupLineKey(line: PendingCleanupLine): string {
  return `${line.line_no}\u0000${line.raw}`;
}

export function clone<T>(value: T): T {
  return structuredClone(value);
}
