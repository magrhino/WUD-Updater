export type ReleaseChangelogStatus =
  | "idle"
  | "loading"
  | "ready"
  | "unavailable"
  | "error";

export type ReleaseChangelogState = {
  status: ReleaseChangelogStatus;
  body: string;
  sourceUrl: string;
  error: string;
};

export type GitHubReleaseRef = {
  owner: string;
  repo: string;
  tag: string;
  canonicalUrl: string;
};

export type ReleaseChangelogResult =
  | {
      status: "ready";
      body: string;
      sourceUrl: string;
    }
  | {
      status: "unavailable";
      error: string;
    };

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

type FetchReleaseChangelogOptions = {
  fetch?: FetchLike;
  maxBytes?: number;
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 6000;
const DEFAULT_MAX_BYTES = 512 * 1024;
const VERSION_TAG_PATTERN =
  /^\d+(?:[._-]\d+)*(?:[-+][0-9A-Za-z][0-9A-Za-z._+-]*)?$/;

export const IDLE_RELEASE_CHANGELOG: ReleaseChangelogState = {
  status: "idle",
  body: "",
  sourceUrl: "",
  error: "",
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

export async function fetchReleaseChangelog(
  releaseUrl: string,
  releaseTag: string,
  options: FetchReleaseChangelogOptions = {},
): Promise<ReleaseChangelogResult> {
  const release = parseGitHubReleaseUrl(releaseUrl);
  if (release === null) {
    return {
      status: "unavailable",
      error: "Only public GitHub release links support changelog extraction.",
    };
  }

  const fetchImpl = options.fetch ?? fetch;
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const apiTag = encodeURIComponent(release.tag);
  const releaseJson = await fetchTextWithLimit(
    `https://api.github.com/repos/${release.owner}/${release.repo}/releases/tags/${apiTag}`,
    {
      accept: "application/vnd.github+json",
      fetchImpl,
      maxBytes,
      resource: "GitHub release",
      timeoutMs,
    },
  );
  const releaseBody = releaseBodyFromJson(releaseJson);
  const changelogUrl = findChangelogRawUrl(releaseBody, release);
  if (!changelogUrl) {
    return {
      status: "unavailable",
      error: "No changelog link found in the GitHub release body.",
    };
  }

  const changelogMarkdown = await fetchTextWithLimit(changelogUrl, {
    accept: "text/plain",
    fetchImpl,
    maxBytes,
    resource: "changelog",
    timeoutMs,
  });
  const tag = releaseTag.trim() || release.tag;
  const section = extractChangelogSection(changelogMarkdown, tag);
  if (!section) {
    return {
      status: "unavailable",
      error: `No changelog section found for ${tag}.`,
    };
  }
  return {
    status: "ready",
    body: section,
    sourceUrl: changelogUrl,
  };
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

export function extractChangelogSection(
  markdown: string,
  releaseTag: string,
): string {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  let startIndex = -1;
  let startLevel = 0;
  for (const [index, line] of lines.entries()) {
    const heading = parseAtxHeading(line);
    if (heading && headingMatchesTag(heading.text, releaseTag)) {
      startIndex = index;
      startLevel = heading.level;
      break;
    }
  }
  if (startIndex === -1) {
    return "";
  }

  let endIndex = lines.length;
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    const heading = parseAtxHeading(lines[index]);
    if (heading && heading.level <= startLevel) {
      endIndex = index;
      break;
    }
  }
  return lines.slice(startIndex, endIndex).join("\n").trim();
}

function releaseBodyFromJson(raw: string): string {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error("GitHub release response was not valid JSON.");
  }
  if (typeof value !== "object" || value === null || !("body" in value)) {
    return "";
  }
  const body = (value as { body?: unknown }).body;
  return typeof body === "string" ? body : "";
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

function parseAtxHeading(
  line: string,
): { level: number; text: string } | null {
  const trimmed = line.trim();
  let level = 0;
  while (trimmed[level] === "#") {
    level += 1;
  }
  if (
    level === 0 ||
    level > 6 ||
    trimmed[level] === "#" ||
    !isMarkdownWhitespace(trimmed[level])
  ) {
    return null;
  }
  let textStart = level + 1;
  while (textStart < trimmed.length && isMarkdownWhitespace(trimmed[textStart])) {
    textStart += 1;
  }
  if (textStart >= trimmed.length) {
    return null;
  }

  let textEnd = trimmed.length;
  while (textEnd > textStart + 1 && trimmed[textEnd - 1] === "#") {
    textEnd -= 1;
  }
  while (textEnd > textStart + 1 && isMarkdownWhitespace(trimmed[textEnd - 1])) {
    textEnd -= 1;
  }
  return {
    level,
    text: trimmed.slice(textStart, textEnd),
  };
}

function headingMatchesTag(heading: string, releaseTag: string): boolean {
  const text = plainMarkdownText(heading);
  return tagVariants(releaseTag).some((tag) =>
    new RegExp(
      `(^|[^0-9A-Za-z._+/-])${escapeRegExp(tag)}([^0-9A-Za-z._+/-]|$)`,
      "i",
    ).test(text),
  );
}

function plainMarkdownText(value: string): string {
  return replaceMarkdownLinksWithLabels(value)
    .replace(/[`*_~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function replaceMarkdownLinksWithLabels(value: string): string {
  let result = "";
  let searchIndex = 0;
  while (searchIndex < value.length) {
    const labelStart = value.indexOf("[", searchIndex);
    if (labelStart === -1) {
      return result + value.slice(searchIndex);
    }
    const labelEnd = value.indexOf("]", labelStart + 1);
    if (labelEnd === -1) {
      return result + value.slice(searchIndex);
    }
    const hrefStart = labelEnd + 2;
    if (
      labelEnd === labelStart + 1 ||
      value[labelEnd + 1] !== "(" ||
      value[hrefStart] === ")"
    ) {
      result += value.slice(searchIndex, labelStart + 1);
      searchIndex = labelStart + 1;
      continue;
    }
    const hrefEnd = value.indexOf(")", hrefStart);
    if (hrefEnd === -1) {
      return result + value.slice(searchIndex);
    }
    result += value.slice(searchIndex, labelStart);
    result += value.slice(labelStart + 1, labelEnd);
    searchIndex = hrefEnd + 1;
  }
  return result;
}

function tagVariants(releaseTag: string): string[] {
  const trimmed = releaseTag.trim();
  if (!trimmed) {
    return [];
  }
  const withoutLeadingV = trimmed.replace(/^v/i, "");
  if (!VERSION_TAG_PATTERN.test(withoutLeadingV)) {
    return [trimmed];
  }
  return [...new Set([trimmed, withoutLeadingV, `v${withoutLeadingV}`])];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);
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

async function fetchTextWithLimit(
  url: string,
  options: {
    accept: string;
    fetchImpl: FetchLike;
    maxBytes: number;
    resource: string;
    timeoutMs: number;
  },
): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs);
  try {
    const response = await options.fetchImpl(url, {
      headers: { Accept: options.accept },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Could not fetch ${options.resource} (${response.status}).`);
    }
    const contentLength = Number(response.headers.get("content-length") || "0");
    if (contentLength > options.maxBytes) {
      throw new Error(`${options.resource} response is too large.`);
    }
    const text = await response.text();
    if (text.length > options.maxBytes) {
      throw new Error(`${options.resource} response is too large.`);
    }
    return text;
  } finally {
    clearTimeout(timeout);
  }
}
