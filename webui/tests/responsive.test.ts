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

function isCustomMediaName(value: string): boolean {
  if (!value.startsWith("--") || value.length === 2) {
    return false;
  }

  for (const char of value.slice(2)) {
    if (
      (char >= "a" && char <= "z") ||
      (char >= "A" && char <= "Z") ||
      (char >= "0" && char <= "9") ||
      char === "_" ||
      char === "-"
    ) {
      continue;
    }

    return false;
  }

  return true;
}

function isCssWhitespace(char: string): boolean {
  return (
    char === " " ||
    char === "\t" ||
    char === "\n" ||
    char === "\r" ||
    char === "\f"
  );
}

function firstWhitespaceIndex(value: string): number {
  for (let index = 0; index < value.length; index += 1) {
    if (isCssWhitespace(value[index])) {
      return index;
    }
  }

  return -1;
}

function cssCustomMediaDefinitions(): Map<string, string> {
  const css = readFileSync(responsiveCssPath, "utf8");
  const definitions = new Map<string, string>();
  const customMediaPrefix = "@custom-media";
  for (const line of css.split("\n")) {
    const statement = line.trim();
    if (
      !statement.startsWith(customMediaPrefix) ||
      !statement.endsWith(";")
    ) {
      continue;
    }

    const declaration = statement.slice(customMediaPrefix.length, -1);
    if (!isCssWhitespace(declaration[0])) {
      continue;
    }

    const body = declaration.trim();
    const nameEnd = firstWhitespaceIndex(body);
    if (nameEnd === -1) {
      continue;
    }

    const name = body.slice(0, nameEnd);
    if (!isCustomMediaName(name)) {
      continue;
    }

    definitions.set(name, body.slice(nameEnd).trim());
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

  it("uses inclusive helpers for max-width breakpoint composables", () => {
    const source = readFileSync(responsiveTsPath, "utf8");

    expect(source).toContain(
      'useBreakpoints(responsiveBreakpoints).smallerOrEqual("dataCards")',
    );
    expect(source).toContain(
      'useBreakpoints(responsiveBreakpoints).smallerOrEqual("managementCards")',
    );
    expect(source).toContain(
      'useBreakpoints(responsiveBreakpoints).smallerOrEqual("policyManagementCards")',
    );
    expect(source).not.toMatch(
      /useBreakpoints\(responsiveBreakpoints\)\.smaller\("(dataCards|managementCards|policyManagementCards)"\)/,
    );
  });
});
