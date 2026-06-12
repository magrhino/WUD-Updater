import type { DigestTagProvenance } from "../api/client";

export type DigestProvenanceDisplay = {
  primary: string;
  digest: string;
  title: string;
};

export function digestProvenanceDisplay(
  provenance: DigestTagProvenance | null | undefined,
): DigestProvenanceDisplay | null {
  if (!provenance) {
    return null;
  }
  const repo = imageRepositoryLabel(
    provenance.source_image || provenance.final_image,
  );
  const fromTag =
    provenance.watch_tag || provenance.resolved_tag || "unknown";
  const toTag = provenance.resolved_tag || provenance.watch_tag || "unknown";
  const digest = provenance.target_digest
    ? `Digest: ${displayDigest(provenance.target_digest)}`
    : "";
  const title = [
    provenance.source_image ? `Source: ${provenance.source_image}` : "",
    provenance.final_image ? `Deploying: ${provenance.final_image}` : "",
    provenance.target_digest ? `Digest: ${provenance.target_digest}` : "",
    provenance.provenance_source
      ? `Source: ${provenance.provenance_source}`
      : "",
    provenance.provenance_confidence
      ? `Confidence: ${provenance.provenance_confidence}`
      : "",
  ]
    .filter(Boolean)
    .join("\n");

  return {
    primary: `${repo}: ${fromTag} -> ${toTag}`,
    digest,
    title,
  };
}

export function displayDigest(value: string): string {
  if (!value || value.length <= 36) {
    return value;
  }
  return `${value.slice(0, 20)}...${value.slice(-12)}`;
}

function imageRepositoryLabel(value: string): string {
  const digestless = value.split("@sha256:", 1)[0] ?? value;
  const slash = digestless.lastIndexOf("/");
  const colon = digestless.lastIndexOf(":");
  if (colon > slash) {
    return digestless.slice(0, colon);
  }
  return digestless;
}
