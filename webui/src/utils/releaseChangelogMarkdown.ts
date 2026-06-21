const VERSION_TAG_PATTERN =
  /^\d+(?:[._-]\d+)*(?:[-+][0-9A-Za-z][0-9A-Za-z._+-]*)?$/;

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
  const text = plainMarkdownText(heading).toLowerCase();
  return tagVariants(releaseTag).some((tag) =>
    textContainsDelimitedTag(text, tag.toLowerCase()),
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

function textContainsDelimitedTag(text: string, tag: string): boolean {
  let startIndex = 0;
  while (startIndex < text.length) {
    const tagIndex = text.indexOf(tag, startIndex);
    if (tagIndex === -1) {
      return false;
    }
    if (
      isTagBoundary(text[tagIndex - 1]) &&
      isTagBoundary(text[tagIndex + tag.length])
    ) {
      return true;
    }
    startIndex = tagIndex + 1;
  }
  return false;
}

function isTagBoundary(value: string | undefined): boolean {
  if (value === undefined) {
    return true;
  }
  const code = value.charCodeAt(0);
  return !(
    (code >= 48 && code <= 57) ||
    (code >= 65 && code <= 90) ||
    (code >= 97 && code <= 122) ||
    value === "." ||
    value === "_" ||
    value === "+" ||
    value === "/" ||
    value === "-"
  );
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
