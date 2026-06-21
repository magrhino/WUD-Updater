import { describe, expect, it } from "vitest";

import { extractChangelogSection } from "../src/utils/releaseChangelogMarkdown";

describe("release changelog markdown sections", () => {
  it("extracts a Mousehole-style tag section", () => {
    const markdown = [
      "# Changelog",
      "",
      "## Unreleased",
      "",
      "- Future work",
      "",
      "## [v0.5.0](https://github.com/t-mart/mousehole/releases/tag/v0.5.0) - 2026-06-20",
      "",
      "- **Breaking**: Live updates use Server-Sent Events instead of WebSockets.",
      "- **Added**: Docker secrets support.",
      "",
      "## [v0.4.0](https://github.com/t-mart/mousehole/releases/tag/v0.4.0) - 2026-06-04",
      "",
      "- Older release",
    ].join("\n");

    const section = extractChangelogSection(markdown, "v0.5.0");

    expect(section).toContain("## [v0.5.0]");
    expect(section).toContain("Server-Sent Events");
    expect(section).toContain("Docker secrets support");
    expect(section).not.toContain("Older release");
  });

  it("matches tags with or without a leading v", () => {
    expect(extractChangelogSection("## [0.5.0]\n\n- Plain tag", "v0.5.0"))
      .toContain("Plain tag");
    expect(extractChangelogSection("## [v0.5.0]\n\n- Prefixed tag", "0.5.0"))
      .toContain("Prefixed tag");
  });

  it("does not strip v from non-version tags", () => {
    for (const [tag, nearMatch] of [
      ["version-1.0", "ersion-1.0"],
      ["vault-1.0", "ault-1.0"],
      ["latest", "vlatest"],
    ]) {
      const markdown = [
        "# Changelog",
        "",
        `## [${nearMatch}]`,
        "",
        "- Wrong section",
        "",
        `## [${tag}]`,
        "",
        "- Exact section",
      ].join("\n");

      const section = extractChangelogSection(markdown, tag);

      expect(section).toContain(`## [${tag}]`);
      expect(section).toContain("Exact section");
      expect(section).not.toContain("Wrong section");
    }
  });

  it("does not prefix-match longer version headings", () => {
    const markdown = [
      "# Changelog",
      "",
      "## [v1.2.1](https://github.com/t-mart/mousehole/releases/tag/v1.2.1)",
      "",
      "- Patch release",
      "",
      "## [v1.2](https://github.com/t-mart/mousehole/releases/tag/v1.2)",
      "",
      "- Minor release",
    ].join("\n");

    const section = extractChangelogSection(markdown, "v1.2");

    expect(section).toContain("## [v1.2]");
    expect(section).toContain("Minor release");
    expect(section).not.toContain("Patch release");
  });

  it("does not match a tag from a markdown link URL in a heading", () => {
    const markdown = [
      "# Changelog",
      "",
      "## [Release notes](https://github.com/t-mart/mousehole/releases/tag/v1.2)",
      "",
      "- Wrong section",
      "",
      "## [v1.2]",
      "",
      "- Exact release",
    ].join("\n");

    const section = extractChangelogSection(markdown, "v1.2");

    expect(section).toContain("## [v1.2]");
    expect(section).toContain("Exact release");
    expect(section).not.toContain("Wrong section");
  });

  it("does not match version headings with delimiter suffixes", () => {
    for (const suffix of [".1", "-rc.1", "+build", "/alpine", "_hotfix"]) {
      const markdown = [
        "# Changelog",
        "",
        `## [v1.2${suffix}]`,
        "",
        "- Suffixed release",
        "",
        "## [v1.2]",
        "",
        "- Exact release",
      ].join("\n");

      const section = extractChangelogSection(markdown, "v1.2");

      expect(section).toContain("## [v1.2]");
      expect(section).toContain("Exact release");
      expect(section).not.toContain("Suffixed release");
    }
  });
});
