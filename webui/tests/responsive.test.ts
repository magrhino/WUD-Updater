import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  responsiveCustomMedia,
  responsiveMediaQueries,
} from "../src/responsive";

const webuiRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const sourceRoot = join(webuiRoot, "src");
const responsiveCssPath = join(
  sourceRoot,
  "assets",
  "styles",
  "responsive.css",
);
const responsiveTsPath = join(sourceRoot, "responsive.ts");

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(css|ts|vue)$/.test(entry.name) ? [path] : [];
  });
}

function sourceContents(): Array<{ path: string; content: string }> {
  return sourceFiles(sourceRoot)
    .filter((path) => path !== responsiveCssPath && path !== responsiveTsPath)
    .map((path) => ({
      path: relative(webuiRoot, path),
      content: readFileSync(path, "utf8"),
    }));
}

function cssCustomMediaDefinitions(): Map<string, string> {
  const css = readFileSync(responsiveCssPath, "utf8");
  const definitions = new Map<string, string>();
  const pattern = /@custom-media\s+(--[\w-]+)\s+([^;]+);/g;
  for (const match of css.matchAll(pattern)) {
    definitions.set(match[1], match[2].trim());
  }
  return definitions;
}

describe("responsive media tokens", () => {
  it("keeps CSS custom media definitions aligned with TypeScript queries", () => {
    const definitions = cssCustomMediaDefinitions();
    const keys = Object.keys(
      responsiveCustomMedia,
    ) as Array<keyof typeof responsiveCustomMedia>;

    expect(definitions.size).toBe(keys.length);
    for (const key of keys) {
      expect(definitions.get(responsiveCustomMedia[key])).toBe(
        responsiveMediaQueries[key],
      );
    }
  });

  it("keeps responsive breakpoints behind shared tokens", () => {
    const disallowed = [
      /@media\s*\(\s*(?:max-width:\s*\d+px|prefers-reduced-motion:\s*reduce)\s*\)/,
      /useMediaQuery\(\s*["'`]\(max-width:/,
      /useBreakpoints\(\s*\{/,
      /\bbreakpointsTailwind\b/,
      /matchMedia\(\s*["'`]\(prefers-reduced-motion:/,
    ];

    const offenders = sourceContents()
      .filter(({ content }) => disallowed.some((pattern) => pattern.test(content)))
      .map(({ path }) => path);

    expect(offenders).toEqual([]);
  });
});
