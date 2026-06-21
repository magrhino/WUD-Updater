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
  const linkPattern = /\[([^\]]+)]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
  let match: RegExpExecArray | null;
  while ((match = linkPattern.exec(releaseBody)) !== null) {
    const label = match[1] ?? "";
    const href = match[2] ?? "";
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
  const match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line.trim());
  if (!match) {
    return null;
  }
  return {
    level: match[1].length,
    text: match[2],
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
  return value
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/[`*_~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
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
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
