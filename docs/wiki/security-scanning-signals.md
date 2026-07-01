# Candidate Security Scanning Signals

WUDup exposes candidate-only security scan metadata for pending container
updates. When enabled, the WebUI resolves each candidate to a platform-specific
immutable image subject, runs a local Trivy registry scan, and stores cached
advisory results for display.

Scan results are advisory metadata only. They must not gate updates,
automatically snooze updates, bypass snoozes, or imply that an image is safe.
Policy decisions require comparing the current image and candidate with the
same scanner, database revision, platform, and suppression policy.

## Subject Identity

Each scan subject must identify the exact candidate being evaluated:

- canonical registry and repository;
- requested tag or reference for display and audit;
- WUD-reported digest;
- index digest, when the reported digest is an index;
- platform manifest digest;
- OS, architecture, and optional variant;
- platform source, such as Compose or WUD metadata;
- identity status and warnings.

Cache identity is the canonical repository, platform manifest digest, platform,
scanner version, schema version, and vulnerability database revision. Tags are
display metadata, not cache identity.

Platform priority is:

1. Compose service `platform:`.
2. WUD image OS, architecture, and variant metadata.
3. Local Docker image inspection as a consistency check.
4. Host platform only as an explicitly marked fallback.

If the platform or child manifest cannot be proven, the result is unknown or
unsupported. WUDup must not silently scan Trivy's default platform.

## Runtime Contract

Candidate scanning is disabled by default and separate from Docker update
permission. Read-only deployments may display cached results, but refreshing
scans from the WebUI requires authentication, CSRF protection,
`WUD_SECURITY_SCANNING_ENABLED=true`, and `WUD_WEB_MUTATIONS_ENABLED=true`.

Pending-update reads do not start scanner jobs. Refresh jobs deduplicate
identical immutable subjects, run with low concurrency, and avoid treating
registry, auth, offline, stale, partial, or unsupported states as clean results.

Offline mode cannot scan a remote candidate unless image content or a
digest-bound SBOM is already local and the vulnerability database is available.
If those inputs are missing, report unavailable or unknown rather than no
findings.

## Scanner Execution

The scanner adapter uses a configured executable path, not an arbitrary command
string. It builds fixed argv without a shell and runs Trivy with vulnerability
scanning, JSON output, quiet mode, telemetry disabled, registry image source,
explicit platform, optional cache directory, and a bounded timeout.

Scanner errors and logs must redact credentials, tokens, and host-local paths.
Secret scanning and insecure TLS modes stay disabled by default.

## API And UI Contract

The API is cache-first:

- `GET /api/v1/security-scans` reads cached metadata only.
- `POST /api/v1/security-scans/refresh` validates current pending subjects and
  queues bounded scan jobs.
- `GET /api/v1/security-scans/jobs/{id}` reports job progress and results.

Results are joined by immutable subject identity and current pending source, not
line number alone. The UI must label results as candidate-only and
scanner/database-specific. Clean wording should say "No vulnerabilities reported
by Trivy using database as of ..." rather than "safe."

Show scan age, database age, exact platform, exact digest, severity counts,
fixable counts, unfixed count, and warnings. Treat stale, partial,
auth-required, error, unsupported, and offline states as unknown.

## Validation Expectations

Default validation stays fixture-based and offline. Focused coverage should keep
guarding fixed argv construction, no shell execution, bounded timeouts, redacted
errors, malformed Trivy JSON, platform conflicts, digest mismatch handling,
cache identity, duplicate subjects, concurrent refreshes, and unknown states.

Docker or network-gated probes belong outside default CI.
