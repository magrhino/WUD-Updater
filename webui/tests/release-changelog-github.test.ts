import { describe, expect, it } from "vitest";

import {
  findChangelogRawUrl,
  parseGitHubReleaseUrl,
} from "../src/utils/releaseChangelogGithub";

describe("GitHub release changelog links", () => {
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
});
