# Changelog

All notable changes to WUD-Updater are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com) and versions follow
[Semantic Versioning](https://semver.org).

## [Unreleased]

### Added

- Added Ruff to the development validation path and documented the virtual-environment setup for local checks.
- Added actionlint CI for pull requests targeting `main`.
- Added an opt-in Python-backed `updates` wrapper path with parity coverage for update status, alerts, dry runs, and updater dispatch.
- Added no-sudo support for configured updater commands in the Python wrapper path.

### Fixed

- Fixed macOS CI dependency installation by installing Python development dependencies inside a local virtual environment.
- Preserved the default shell-backed `updates` behavior unless the Python wrapper path is explicitly enabled.

Release entries are authored when a release is cut. Ordinary feature and docs
work should update the relevant user-facing docs in the same change, but leave
this file alone until release prep.

Release sections use this shape:

```markdown
## [vX.Y.Z] — YYYY-MM-DD

### Added

### Changed

### Fixed
```

No release sections have been published yet.
