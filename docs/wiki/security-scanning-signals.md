# Candidate Security Scanning Signals

WUDup can plan pending container image updates, but update candidates should not
be treated as safe or unsafe from tag metadata alone. The recommended first step
is an opt-in advisory prototype that resolves each pending candidate to an exact
platform manifest digest and scans that immutable subject with a local Trivy CLI.

This feature is advisory metadata only. Scan results must not gate updates,
automatically snooze updates, bypass snoozes, or imply that an image is safe.
Automated security policy would require comparing the currently running image
and the candidate with the same scanner, database revision, platform, and
suppression policy.

## Recommended Backend

Use Trivy as the first scanner backend:

- It can scan registry images directly without adding them to the Docker image
  store.
- It supports JSON output, explicit `--platform`, persistent caches, private
  registry credentials, offline database workflows, and telemetry opt-out.
- It can run as a local executable, keeping WUDup free from hosted scanner
  service requirements.

Do not add a broad scanner plugin framework initially. Grype and OSV-Scanner are
reasonable future comparators, but Trivy is enough to prove WUDup's identity,
cache, safety, and UI contracts.

Do not use Docker Scout as the default local backend because local analysis can
transmit package URLs and layer digests to Docker. Do not use OSV or GitHub
Advisory APIs directly as the primary image signal because they are package and
version APIs; they need an SBOM or package inventory first. Registry referrers
and attestations can be useful later, but missing SBOM/VEX artifacts must mean
unknown, not clean.

## Required Candidate Identity

The scanner subject must be immutable and platform-specific:

- canonical registry
- canonical repository
- requested tag or reference for display and audit
- WUD-reported digest
- index digest, when the reported digest is an index
- platform manifest digest
- OS, architecture, and optional variant
- platform source, such as Compose or WUD metadata
- identity status and warnings

Use the canonical repository, platform manifest digest, platform, scanner
version, schema version, and vulnerability database revision as cache identity.
Tags are not cache identity.

Platform priority should be:

1. Compose service `platform:`.
2. WUD image OS, architecture, and variant metadata.
3. Local Docker image inspection as a consistency check.
4. Host platform only as an explicitly marked fallback.

If the platform or child manifest cannot be proven, the result is unknown or
unsupported. WUDup should never silently scan Trivy's default platform.

## Runtime And Safety Contract

Candidate scanning must be disabled by default and separate from Docker update
permission. Refreshing scans from the WebUI should require the same authenticated,
CSRF-protected, mutation-enabled posture as other browser-triggered jobs, while
read-only deployments may display cached results.

The scanner adapter should:

- use a configured executable path, not an arbitrary command string;
- build fixed argv without a shell;
- pass `--scanners vuln`, `--format json`, `--quiet`, `--disable-telemetry`,
  `--image-src registry`, `--platform`, `--cache-dir` when configured, and a
  bounded timeout;
- avoid secret scanning and insecure TLS modes by default;
- redact credentials, tokens, and host-local paths from errors and logs;
- deduplicate identical immutable subjects;
- keep concurrency low for registry rate limits and host resource use.

Offline mode cannot scan a remote candidate unless image content or a
digest-bound SBOM is already local and the vulnerability database is available.
If those inputs are missing, report unavailable or unknown rather than no
findings.

## API And UI Contract

Use cache-first API behavior:

- `GET /api/v1/security-scans` reads cached metadata only.
- `POST /api/v1/security-scans/refresh` validates the current pending subjects
  and queues bounded scan jobs.
- `GET /api/v1/security-scans/jobs/{id}` reports job progress and results.

Do not make pending-update reads start scanner jobs. Join results by immutable
subject identity and the current pending source, not by line number alone.

The UI must say results are candidate-only and scanner/database-specific. For a
clean result, use wording such as "No vulnerabilities reported by Trivy using
database as of ..." rather than "safe." Show scan age, database age, exact
platform, exact digest, severity counts, fixable counts, unfixed count, and
warnings. Treat stale, partial, auth-required, error, unsupported, and offline
states as unknown.

## Validation Plan

Keep default CI fixture-based and offline. Focused tests should cover:

- fixed argv construction, no shell, timeouts, and redacted scanner errors;
- malformed and versioned Trivy JSON;
- multi-architecture images with different child manifests;
- WUD-reported index digest, child digest, stale digest, and platform mismatch;
- Compose and WUD platform conflicts;
- unsupported, auth-required, offline, stale, partial, error, findings, and
  no-findings states;
- cold and warm cache behavior, duplicate subjects, and concurrent refreshes;
- scratch, distroless, EOL, language-only, zero-finding, unfixed, and fixable
  findings fixtures;
- a Docker/network-gated live probe outside default CI.
