# Changelog

All notable changes to WUD-Updater are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com) and versions follow
[Semantic Versioning](https://semver.org).

## [0.6.0](https://github.com/magrhino/WUD-Updater/compare/v0.5.0...v0.6.0) (2026-05-19)


### Features

* **truenas:** Switch TrueNAS status checks to a local helper container ([#23](https://github.com/magrhino/WUD-Updater/issues/23)) ([b780b18](https://github.com/magrhino/WUD-Updater/commit/b780b1866386bbd36c812c471c5e6ca7fb70b780))

## [0.5.0](https://github.com/magrhino/WUD-Updater/compare/v0.4.3...v0.5.0) (2026-05-18)


### Features

* **db:** Add SQLite persistence validation for the updater ([#20](https://github.com/magrhino/WUD-Updater/issues/20)) ([0400154](https://github.com/magrhino/WUD-Updater/commit/04001546d32316e2a69c3f7a45c1aa3af0e31f94))


### Bug Fixes

* **updates:** handle unreachable TrueNAS and interrupted prompts ([d0d2946](https://github.com/magrhino/WUD-Updater/commit/d0d294671f89bbf87f9b63320edfa6dce28f3918))


### Documentation

* **truenas:** align api client example with secret-file auth ([2ed9c56](https://github.com/magrhino/WUD-Updater/commit/2ed9c5698fe8c20ab20fdc690999db21d30c1eec))

## [0.4.3](https://github.com/magrhino/WUD-Updater/compare/v0.4.2...v0.4.3) (2026-05-18)


### Bug Fixes

* **logs:** create generated logs exclusively ([ac405fc](https://github.com/magrhino/WUD-Updater/commit/ac405fc8b19d4014c3809a01c1e966ba63d88269))
* **wud:** standardize release-note curl handling ([77c098c](https://github.com/magrhino/WUD-Updater/commit/77c098c3b93042f9cecd94c64bf2caf2f3b535e5))

## [0.4.2](https://github.com/magrhino/WUD-Updater/compare/v0.4.1...v0.4.2) (2026-05-18)


### Bug Fixes

* **wud:** harden discord webhook payloads ([58029cc](https://github.com/magrhino/WUD-Updater/commit/58029cc454eb21739bb636db14cfa4a3c8cf3ddd))


### Documentation

* **github:** add contributor templates ([#15](https://github.com/magrhino/WUD-Updater/issues/15)) ([3349713](https://github.com/magrhino/WUD-Updater/commit/3349713e818450d6ab9e93b35600a5a02a6ff60c))

## [0.4.1](https://github.com/magrhino/WUD-Updater/compare/v0.4.0...v0.4.1) (2026-05-18)


### Bug Fixes

* **logs:** move default updater logs out of docker root ([3d42e94](https://github.com/magrhino/WUD-Updater/commit/3d42e941830fdefa833c090413372cc8de1570bd))
* **logs:** move default updater logs out of docker root ([9aeff64](https://github.com/magrhino/WUD-Updater/commit/9aeff64cd43f01eec92e44d91ae0d2b7d0818bec))


### Documentation

* **changelog:** note updater log directory change ([1d7de0f](https://github.com/magrhino/WUD-Updater/commit/1d7de0ffec29c6c38f277415d9f6c6df9e9794cd))
* **docker:** add hardened socket proxy compose example ([147c75a](https://github.com/magrhino/WUD-Updater/commit/147c75afd48fb72daddbc6113db20186bd4c4575))
* **docker:** use published image in compose example ([cdc66ff](https://github.com/magrhino/WUD-Updater/commit/cdc66ff281623a9061b0fd08c29a5dec7282df54))
* Move temlpate.env and document ([1ac0bf3](https://github.com/magrhino/WUD-Updater/commit/1ac0bf311938e8c72d66b1e4e4dacbf4eaac3740))

## [0.4.0](https://github.com/magrhino/WUD-Updater/compare/v0.3.0...v0.4.0) (2026-05-18)


### Features

* **python:** Archive Bash updater and sync WUD scripts ([#11](https://github.com/magrhino/WUD-Updater/issues/11)) ([240d096](https://github.com/magrhino/WUD-Updater/commit/240d09603310b79a3471f3432fd0a7f3e8fe5cfc))

## [0.3.0](https://github.com/magrhino/WUD-Updater/compare/v0.2.0...v0.3.0) (2026-05-18)


### Features

* **container:** add WUD script startup sync ([95a9a96](https://github.com/magrhino/WUD-Updater/commit/95a9a96259786fddfe8ecad8d7c59d0e7b51f70b))

## [0.2.0](https://github.com/magrhino/WUD-Updater/compare/v0.1.0...v0.2.0) (2026-05-18)


### Features

* **updater:** make Python updater default ([2ef6d95](https://github.com/magrhino/WUD-Updater/commit/2ef6d95e29f269429421bc270eb914ade0b98c1a))


### Documentation

* **changelog:** add Python updater default entry ([eeb85ba](https://github.com/magrhino/WUD-Updater/commit/eeb85ba9eb7c594f5efba56ea45fa4c0a7b4658a))

## 0.1.0 (2026-05-18)


### Features

* **docker:** add deployable updater image ([be76783](https://github.com/magrhino/WUD-Updater/commit/be76783647b299c1b93cfd1ac3b6aef362e900ac))
* **python:** add docker compose subprocess layer ([c5b1195](https://github.com/magrhino/WUD-Updater/commit/c5b1195ca5b9e4e261e0b8413fa6f4af137becef))
* **python:** add updater package skeleton ([557c360](https://github.com/magrhino/WUD-Updater/commit/557c36069a28c5d759e489a67ec5939b1ad5e720))
* scaffold wud updater ([1700332](https://github.com/magrhino/WUD-Updater/commit/17003321d23fb8775da4db0a6782b372f626d0ec))
* **updater:** add opt-in compose tag updates ([4a2bfca](https://github.com/magrhino/WUD-Updater/commit/4a2bfcacbdbb1b3b3e96691666690178ff8f89d3))
* **updater:** add opt-in Python update-from-wud ([65199e5](https://github.com/magrhino/WUD-Updater/commit/65199e556f0caddbae704888feca0e924be4a635))
* **updates:** add interactive image selector ([79cdae0](https://github.com/magrhino/WUD-Updater/commit/79cdae078a7cba5392aca20e2734ca137b6a1e49))
* **updates:** add no-sudo Python wrapper mode ([908a35a](https://github.com/magrhino/WUD-Updater/commit/908a35a114c39f102f7e4ef1570829d9830c4033))
* **updates:** add opt-in python wrapper parity ([4051375](https://github.com/magrhino/WUD-Updater/commit/4051375dc95d7f455476888a304f50c266192b0b))
* **updates:** add python updates wrapper ([01d5258](https://github.com/magrhino/WUD-Updater/commit/01d525855268aa042291fd61e5abcf529e2d5872))
* **wud-file:** add Python WUD lock cleanup helpers ([1591deb](https://github.com/magrhino/WUD-Updater/commit/1591deb2571d84c3ac6e3664c89d48ba1d7d4418))
* **wud:** add Python WUD parsing parity helpers ([fb8bae6](https://github.com/magrhino/WUD-Updater/commit/fb8bae61f331ac69607ab0b7b64144a558648bc0))


### Bug Fixes

* **ci:** install dev dependencies in workflow venv ([49b1c21](https://github.com/magrhino/WUD-Updater/commit/49b1c21d5543b92193c13e85d66496ac36bd1da7))
* **command:** handle subprocess launch failures ([a37312e](https://github.com/magrhino/WUD-Updater/commit/a37312e47d432e409ac110f2e16cc02cc5936311))
* **compose:** align python docker layer with shell behavior ([0918c9c](https://github.com/magrhino/WUD-Updater/commit/0918c9c6daf062258e8396fd3108a680a12eb44f))
* **compose:** preserve recovery behavior in python layer ([bdf3edd](https://github.com/magrhino/WUD-Updater/commit/bdf3edd9759e3259f6c2b153756274d7e9c857b4))
* **python:** align config defaults and version floor ([26d99dc](https://github.com/magrhino/WUD-Updater/commit/26d99dcca8e2701d13ef34bef3c3a7cf8bff5540))
* **updater:** preserve wud output ownership under sudo ([ac879a7](https://github.com/magrhino/WUD-Updater/commit/ac879a7002712c302f6350e6d64739f781e0c88f))
* **updater:** restore WUD lines on tag backup failure ([5086aa0](https://github.com/magrhino/WUD-Updater/commit/5086aa095f369be4fbcb995c2c42079fa63fed6e))
* **updates:** preserve python wrapper opt-in dispatch ([58acfce](https://github.com/magrhino/WUD-Updater/commit/58acfce879c5d504ab6ce0098a408f78661fc0eb))
* **updates:** validate WUD selections before updater handoff ([97946bd](https://github.com/magrhino/WUD-Updater/commit/97946bd71b9ac67f132caea2c8b8c58c0a465f7a))
* use home docker defaults and valid release payload ([c512d1e](https://github.com/magrhino/WUD-Updater/commit/c512d1e87a8d4a29e6e8531e2d3504f1537547c9))
* **wud:** preserve todo file shared access ([1f5e9a9](https://github.com/magrhino/WUD-Updater/commit/1f5e9a915fde6e1471a27f147c904fae17253707))
* **wud:** stop generated digests from blocking updates ([d12be85](https://github.com/magrhino/WUD-Updater/commit/d12be856bc0acf01d2da3bb98026443dc093fa84))
* **wud:** suppress trap-only cleanup shellcheck warning ([a28e144](https://github.com/magrhino/WUD-Updater/commit/a28e1449bb9b24159e498a6899594b39b3aceae0))
* **wud:** surface rewrite and semver failures ([1be85df](https://github.com/magrhino/WUD-Updater/commit/1be85dff1b5988679b8216108eac63a5188f4abe))
* **wud:** synchronize todo file rewrites ([bd98adc](https://github.com/magrhino/WUD-Updater/commit/bd98adce192613b730a4553084f963bb74efbc6f))


### Documentation

* **agents:** tune context guidance ([196f8b1](https://github.com/magrhino/WUD-Updater/commit/196f8b12f32e4b957f7fe2db9950b58bdec0a57d))
* **changelog:** add updates wrapper entries ([c80bf99](https://github.com/magrhino/WUD-Updater/commit/c80bf99d338c6e25bd58feab61060c3c7cf70edf))
* document python refactor and changelog policy ([35be690](https://github.com/magrhino/WUD-Updater/commit/35be6907fa7922c293843fdc21ef5890992e6b51))
* initialize repo guidance and README ([930fade](https://github.com/magrhino/WUD-Updater/commit/930fadeaa765a1d7ed4e9ab3147ea5f29f4c2639))

## [Unreleased]

### Added

- Added deployment, development, container script sync, release-note notification, and WUD update flow docs under `docs/`.

### Changed

- Moved detailed deployment, development, and workflow guidance from the root README into `docs/`.
- Archived the legacy Bash updater path and moved the Docker Compose example under `docs/examples/`.
- Moved updater logs to a configurable `WUD_LOG_DIR`, defaulting to `./logs` on hosts and `/logs` in the container.

### Fixed

- Hardened entrypoint WUD script sync so mounted script destinations must be safe directories before image scripts are copied.

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
