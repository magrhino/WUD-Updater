# Security Policy

## Supported Versions

Security fixes target the current `main` branch and the next stable release.
Please reproduce issues on the latest tagged release, GHCR image tag, or commit
available to you before reporting when practical.

Older release tags are immutable deployment references. Upgrade to a current
release before reporting unless the older version is needed to explain impact
or regression history.

## Reporting A Vulnerability

Report security vulnerabilities privately through GitHub Security Advisories:

<https://github.com/magrhino/WUD-Updater/security/advisories/new>

Do not open public issues, discussions, or pull requests for suspected
vulnerabilities until a fix or disclosure plan is agreed.

Include enough detail to reproduce and triage the issue:

- The WUD-Updater version, image tag, or commit.
- The deployment method: host install, Docker Compose image, local build, or
  source checkout.
- Relevant configuration, Compose snippets, command output, logs, and minimal
  reproduction steps.
- Whether the issue requires Docker socket access, WebUI exposure, WUD callback
  inputs, release-note webhooks, or TrueNAS status checks.

Redact secrets and machine-specific details. Do not include real Discord
webhook URLs, GitHub tokens, browser session cookies, setup or reset claims,
private service URLs, private hostnames, absolute home-directory paths, or
other credentials. Use placeholders when a value shape matters.

## Security Scope

Reports are in scope when they show that WUD-Updater does something outside
the documented trust boundaries, including:

- WebUI authentication, session, CSRF, Origin, Host, trusted proxy, or secure
  cookie bypasses.
- Browser-triggered Docker mutations when `WUD_WEB_MUTATIONS_ENABLED` is not
  enabled, or mutation requests that bypass authentication, CSRF checks, or the
  plan-first apply flow.
- Mutating Docker operations that occur during `--dry-run`, without
  interactive confirmation, or without `--yes`.
- Secret exposure in logs, generated files, API responses, release-note helper
  output, issue templates, workflow logs, or public documentation.
- Command injection, path traversal, unsafe deserialization, unsafe log access,
  or unsafe file writes from WUD callback fields, image names, Compose metadata,
  environment variables, or WebUI inputs.
- Unsafe managed WUD script sync behavior, Compose tag rewrites, tag exclusion
  writes, or update-file locking that can write outside the intended mounted
  directories.
- GitHub Actions, release, dependency, or container-publishing weaknesses that
  could let untrusted code publish artifacts or exfiltrate repository secrets.

## Documented Trust Boundaries

The following behaviors are documented operational risks, not vulnerabilities
by themselves:

- Mounting `/var/run/docker.sock` gives WUD-Updater root-equivalent control of
  the host Docker daemon. Only run trusted images with that socket.
- The hardened socket-proxy example reduces direct socket exposure, but Docker
  Compose pull, stop, and recreate operations still require proxy `POST=1`.
- The TrueNAS status helper does not use a TrueNAS API key, but enabling
  `TRUENAS_STATUS_CHECK=true` gives a short-lived helper trusted-host access to
  the local TrueNAS middleware socket for read status methods.
- `updates --yes`, `docker-update-from-wud --yes`, and
  `WUD_WEB_MUTATIONS_ENABLED=true` intentionally allow update mutations within
  the documented controls.
- Optional GitHub and Discord release-note integrations use tokens and webhooks
  supplied through environment variables or host-local secret stores.

## Security Defaults And Expectations

WUD-Updater defaults to non-mutating operation where practical:

- The container image runs `updates --dry-run` by default.
- `--dry-run` must not pull images, recreate containers, remove WUD lines, or
  otherwise mutate host state.
- Mutating Docker operations require interactive confirmation or `--yes`.
- The WebUI starts read-only by default, with browser mutations disabled unless
  `WUD_WEB_MUTATIONS_ENABLED=true` is set.
- Browser sessions use HttpOnly cookies and CSRF protection. `WUD_WEB_TOKEN` is
  only an optional API bearer token; it is not accepted by the browser login form
  and does not bypass first-run setup.
- `WUD_WEB_DEV_NO_AUTH=true` is for local development and tests only.

Deployments should keep Docker socket, stack, script, output, log, and database
mounts scoped to the directories WUD-Updater needs. When exposing the WebUI
outside loopback, set the browser-visible public origin, allowed hosts, trusted
proxy addresses, and secure-cookie behavior intentionally.

Secrets such as Discord webhooks and GitHub tokens must come from environment
variables, Compose secrets, or host-local configuration. Do not commit secrets
to this repository. The callback scripts redact webhook values in helper logs
where those commands are printed.

## Automated Checks

The repository keeps security checks high-signal and cost-conscious:

- Dependabot checks Python, npm, Docker, and GitHub Actions dependencies on a
  weekly schedule.
- CodeQL scans Actions, Python, and WebUI JavaScript/TypeScript.
- The security workflow runs workflow auditing with zizmor.
- Dependency Review blocks public pull requests with high-severity dependency
  changes when the repository is public.
- OSSF Scorecard runs as an advisory signal on non-PR events when the
  repository is public.

These checks do not replace private vulnerability reporting.

## Disclosure And Fixes

Security reports are handled privately on a maintainer best-effort basis. Fixes
normally land on `main`, are covered by focused validation when practical, and
ship in the next stable release. Public disclosure should wait until a fix,
upgrade guidance, or advisory text is ready.
