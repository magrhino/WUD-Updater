import { describe, expect, it, vi } from "vitest";

import {
  extractChangelogSection,
  fetchReleaseChangelog,
  findChangelogRawUrl,
  parseGitHubReleaseUrl,
} from "../src/utils/releaseChangelog";

function textResponse(body: string, init: ResponseInit = {}): Response {
  return new Response(body, init);
}

describe("release changelog extraction", () => {
  it("parses GitHub release URLs", () => {
    expect(
      parseGitHubReleaseUrl(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
      ),
    ).toMatchObject({
      owner: "t-mart",
      repo: "mousehole",
      tag: "v0.5.0",
      canonicalUrl:
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
    });
    expect(parseGitHubReleaseUrl("https://example.com/acme/app")).toBeNull();
  });

  it("finds changelog links and converts GitHub markdown URLs to raw URLs", () => {
    expect(
      findChangelogRawUrl("[changelog](https://github.com/t-mart/mousehole/blob/master/CHANGELOG.md)", {
        owner: "t-mart",
        repo: "mousehole",
      }),
    ).toBe(
      "https://raw.githubusercontent.com/t-mart/mousehole/master/CHANGELOG.md",
    );
    expect(
      findChangelogRawUrl("[release notes](CHANGELOG.md)", {
        owner: "t-mart",
        repo: "mousehole",
      }),
    ).toBe(
      "https://raw.githubusercontent.com/t-mart/mousehole/HEAD/CHANGELOG.md",
    );
  });

  it("finds titled changelog links after malformed markdown noise", () => {
    const noisyBody = `${"[not a changelog](README.md \"".repeat(1500)} [release notes](docs/CHANGELOG.md "notes")`;

    expect(
      findChangelogRawUrl(noisyBody, {
        owner: "t-mart",
        repo: "mousehole",
      }),
    ).toBe(
      "https://raw.githubusercontent.com/t-mart/mousehole/HEAD/docs/CHANGELOG.md",
    );
  });

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

  it("returns unavailable when the release body has no changelog link", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      textResponse(JSON.stringify({ body: "No changelog here." })),
    );

    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: fetchMock },
      ),
    ).resolves.toMatchObject({
      status: "unavailable",
      error: "No changelog link found in the GitHub release body.",
    });
  });

  it("returns unavailable when the changelog has no matching tag section", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        textResponse(
          JSON.stringify({
            body: "[changelog](https://github.com/t-mart/mousehole/blob/master/CHANGELOG.md)",
          }),
        ),
      )
      .mockResolvedValueOnce(textResponse("# Changelog\n\n## [v0.4.0]\n\n- Old"));

    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: fetchMock },
      ),
    ).resolves.toMatchObject({
      status: "unavailable",
      error: "No changelog section found for v0.5.0.",
    });
  });

  it("rejects oversized and failed fetches", async () => {
    const oversizedFetch = vi.fn().mockResolvedValueOnce(
      textResponse("{}", { headers: { "content-length": "20" } }),
    );
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: oversizedFetch, maxBytes: 10 },
      ),
    ).rejects.toThrow("GitHub release response is too large.");

    const oversizedBodyFetch = vi.fn().mockResolvedValueOnce(textResponse("{}"));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: oversizedBodyFetch, maxBytes: 1 },
      ),
    ).rejects.toThrow("GitHub release response is too large.");

    const failedStatusFetch = vi
      .fn()
      .mockResolvedValueOnce(textResponse("Not found", { status: 404 }));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: failedStatusFetch },
      ),
    ).rejects.toThrow("Could not fetch GitHub release (404).");

    const failedFetch = vi.fn().mockRejectedValueOnce(new Error("network failed"));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: failedFetch },
      ),
    ).rejects.toThrow("network failed");
  });
});
