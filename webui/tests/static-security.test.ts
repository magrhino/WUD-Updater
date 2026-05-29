import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const webuiRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const sourceRoot = join(webuiRoot, "src");

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(ts|vue)$/.test(entry.name) ? [path] : [];
  });
}

function contents(paths: string[]): Array<{ path: string; content: string }> {
  return paths.map((path) => ({
    path: relative(webuiRoot, path),
    content: readFileSync(path, "utf8"),
  }));
}

describe("static frontend security guards", () => {
  it("keeps auth and API code away from browser storage", () => {
    const guardedFiles = contents([
      join(sourceRoot, "api", "client.ts"),
      join(sourceRoot, "stores", "auth.ts"),
    ]);
    const disallowed = /\b(localStorage|sessionStorage|useLocalStorage)\b/;

    const offenders = guardedFiles
      .filter(({ content }) => disallowed.test(content))
      .map(({ path }) => path);

    expect(offenders).toEqual([]);
  });

  it("does not add raw html rendering in frontend source", () => {
    const disallowed = /\b(v-html|innerHTML)\b/;
    const offenders = contents(sourceFiles(sourceRoot))
      .filter(({ content }) => disallowed.test(content))
      .map(({ path }) => path);

    expect(offenders).toEqual([]);
  });
});
