export type GitHubReleaseRef = {
  owner: string;
  repo: string;
  tag: string;
  canonicalUrl: string;
};

export function parseGitHubReleaseUrl(value: string): GitHubReleaseRef | null {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (parsed.hostname.toLowerCase() !== "github.com") {
    return null;
  }
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (
    parts.length < 5 ||
    parts[2] !== "releases" ||
    parts[3] !== "tag" ||
    !parts[0] ||
    !parts[1]
  ) {
    return null;
  }
  const tag = decodeURIComponent(parts.slice(4).join("/"));
  if (!tag) {
    return null;
  }
  return {
    owner: parts[0],
    repo: parts[1],
    tag,
    canonicalUrl: `https://github.com/${parts[0]}/${parts[1]}/releases/tag/${encodeURIComponent(tag)}`,
  };
}

export function releaseChangelogKey(releaseUrl: string): string {
  return parseGitHubReleaseUrl(releaseUrl)?.canonicalUrl ?? "";
}

export function findChangelogRawUrl(
  releaseBody: string,
  release: Pick<GitHubReleaseRef, "owner" | "repo">,
): string {
  for (const { label, href } of markdownLinks(releaseBody)) {
    if (!changelogLabelMatches(label)) {
      continue;
    }
    const rawUrl = githubMarkdownUrlToRaw(resolveGitHubMarkdownHref(href, release));
    if (rawUrl) {
      return rawUrl;
    }
  }
  return "";
}

function changelogLabelMatches(label: string): boolean {
  const normalized = label
    .replace(/[`*_~]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return (
    normalized.includes("changelog") ||
    normalized.includes("change log") ||
    normalized.includes("release notes")
  );
}

function* markdownLinks(
  markdown: string,
): Generator<{ label: string; href: string }> {
  let searchIndex = 0;
  while (searchIndex < markdown.length) {
    const labelStart = markdown.indexOf("[", searchIndex);
    if (labelStart === -1) {
      return;
    }
    const labelEnd = markdown.indexOf("]", labelStart + 1);
    if (labelEnd === -1) {
      return;
    }
    if (labelEnd === labelStart + 1 || markdown[labelEnd + 1] !== "(") {
      searchIndex = labelStart + 1;
      continue;
    }

    const link = readMarkdownLink(markdown, labelEnd + 2);
    if (link === null) {
      searchIndex = labelEnd + 1;
      continue;
    }
    yield {
      label: markdown.slice(labelStart + 1, labelEnd),
      href: link.href,
    };
    searchIndex = link.endIndex;
  }
}

function readMarkdownLink(
  markdown: string,
  hrefStart: number,
): { href: string; endIndex: number } | null {
  let cursor = hrefStart;
  while (
    cursor < markdown.length &&
    markdown[cursor] !== ")" &&
    !isMarkdownWhitespace(markdown[cursor])
  ) {
    cursor += 1;
  }
  if (cursor === hrefStart) {
    return null;
  }

  const href = markdown.slice(hrefStart, cursor);
  if (markdown[cursor] === ")") {
    return { href, endIndex: cursor + 1 };
  }
  if (!isMarkdownWhitespace(markdown[cursor])) {
    return null;
  }
  const endIndex = readMarkdownLinkTitleEnd(markdown, cursor);
  return endIndex === -1 ? null : { href, endIndex };
}

function readMarkdownLinkTitleEnd(markdown: string, titleStart: number): number {
  let cursor = titleStart;
  while (cursor < markdown.length && isMarkdownWhitespace(markdown[cursor])) {
    cursor += 1;
  }
  if (markdown[cursor] !== '"') {
    return -1;
  }
  cursor += 1;
  while (cursor < markdown.length) {
    if (markdown[cursor] === '"') {
      return markdown[cursor + 1] === ")" ? cursor + 2 : -1;
    }
    if (isMarkdownLinkTitleTerminator(markdown[cursor])) {
      return -1;
    }
    cursor += 1;
  }
  return -1;
}

function isMarkdownLinkTitleTerminator(value: string | undefined): boolean {
  return value === "[" || value === ")" || value === "\n" || value === "\r";
}

function resolveGitHubMarkdownHref(
  href: string,
  release: Pick<GitHubReleaseRef, "owner" | "repo">,
): string {
  if (!href || href.startsWith("#")) {
    return "";
  }
  if (/^https?:\/\//i.test(href)) {
    return href;
  }
  const base = `https://github.com/${release.owner}/${release.repo}/blob/HEAD/`;
  if (href.startsWith("/")) {
    const parts = href.split("/").filter(Boolean);
    if (parts[0] !== release.owner || parts[1] !== release.repo) {
      return new URL(href.replace(/^\/+/, ""), base).toString();
    }
    return new URL(href, `https://github.com`).toString();
  }
  return new URL(href, base).toString();
}

function githubMarkdownUrlToRaw(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return "";
  }
  parsed.hash = "";
  const parts = parsed.pathname.split("/").filter(Boolean);
  const markdownPath = parts.join("/");
  if (!/\.(md|markdown)$/i.test(markdownPath)) {
    return "";
  }
  if (parsed.hostname.toLowerCase() === "raw.githubusercontent.com") {
    return parsed.toString();
  }
  if (
    parsed.hostname.toLowerCase() !== "github.com" ||
    parts.length < 5 ||
    parts[2] !== "blob"
  ) {
    return "";
  }
  return `https://raw.githubusercontent.com/${parts[0]}/${parts[1]}/${parts[3]}/${parts.slice(4).join("/")}`;
}

function isMarkdownWhitespace(value: string | undefined): boolean {
  return (
    value === " " ||
    value === "\t" ||
    value === "\n" ||
    value === "\r" ||
    value === "\f" ||
    value === "\v"
  );
}
