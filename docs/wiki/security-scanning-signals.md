# Candidate Security Scanning And Update Delta Signals

WUDup exposes advisory security scan metadata for pending container updates.
When enabled, the WebUI resolves each candidate to a platform-specific
immutable image subject, runs a local Trivy registry scan, and stores cached
advisory results for display. When WUD metadata includes the installed
`local_digest`, refresh jobs also scan that digest and show whether the
candidate fixes, keeps, or introduces reported findings.

Scan results are advisory metadata only. They must not gate updates,
automatically snooze updates, bypass snoozes, or imply that an image is safe.
Delta comparisons are only shown when the current image and candidate were
scanned with the same scanner version, database revision, schema, and platform.
Missing scanner or vulnerability-database provenance makes the comparison
unknown.

## Subject Identity

Each scan subject must identify the exact image being evaluated:

- canonical registry and repository;
- requested tag or reference for display and audit;
- WUD-reported digest;
- index digest, when the reported digest is an index;
- platform manifest digest;
- OS, architecture, and optional variant;
- platform source, such as Compose or WUD metadata;
- identity status and warnings.

Cache identity is the canonical repository, platform manifest digest, platform,
scanner version, schema version, and vulnerability database revision and updated
timestamp. Tags are display metadata, not cache identity.

Platform priority is:

1. Compose service `platform:`.
2. WUD image OS, architecture, and variant metadata.
3. Local Docker image inspection as a consistency check.
4. Host platform only as an explicitly marked fallback.

If the platform or child manifest cannot be proven, the result is unknown or
unsupported. WUDup must not silently scan Trivy's default platform.

## Runtime Contract

Security scanning is disabled by default and separate from Docker update
permission. Read-only deployments may display cached results, but refreshing
scans from the WebUI requires authentication, CSRF protection,
`WUD_SECURITY_SCANNING_ENABLED=true`, and `WUD_WEB_MUTATIONS_ENABLED=true`.

Pending-update reads do not start scanner jobs. Refresh jobs scan the candidate
as usual, scan the installed digest when WUD provides `local_digest`, reuse the
candidate scan when both subjects are identical, deduplicate immutable subjects,
run with low concurrency, and avoid treating registry, auth, offline, stale,
partial, or unsupported states as clean results. File-only legacy mode without
WUD metadata keeps the candidate scan and reports an explicit unknown
comparison.

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

- `GET /api/v1/security-scans` reads cached scan results for current pending
  candidates and cached installed-digest comparisons when available. When
  scanning is enabled, it may use WUD metadata and resolve missing reported
  digests so current candidates can join existing cache entries, but it must
  not run Trivy or create refresh jobs.
- `POST /api/v1/security-scans/refresh` validates current pending subjects and
  queues bounded candidate scan jobs plus installed-digest scan jobs when WUD
  metadata provides the installed digest.
- `GET /api/v1/security-scans/jobs/{id}` reports job progress and results.

Results are joined by immutable subject identity and current pending source, not
line number alone. `SecurityScanInfo.subject` describes the candidate subject.
`SecurityScanInfo.comparison` describes the installed subject, delta status, and
fixed, remaining, and introduced findings. Every finding preserves Trivy's
`Target`, `Class`, and `Type`; comparison keys include that target identity so
the same package/advisory in separate image targets remains separate. The UI
groups rows by target, package, and advisory and labels raw occurrences
separately from unique advisory counts. The UI must label results as
scanner/database-specific advisory metadata. Clean wording should say "No
vulnerabilities reported by Trivy using database as of ..." rather than "safe."

Show scan age, scanner/database provenance, configured reference, candidate
index and platform digests, exact immutable Trivy subject, installed identity,
exact platform, raw severity counts, unique advisory counts, fixable counts,
unfixed count, and warnings. Treat stale, partial,
auth-required, error, unsupported, and offline states as unknown.

## Validation Expectations

Default validation stays fixture-based and offline. Focused coverage should keep
guarding fixed argv construction, no shell execution, bounded timeouts, redacted
errors, malformed Trivy JSON, platform conflicts, digest mismatch handling,
cache identity, duplicate subjects, concurrent refreshes, and unknown states.

Docker or network-gated probes belong outside default CI.
