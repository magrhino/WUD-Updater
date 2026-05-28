# Changelog

All notable changes to WUD-Updater are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com) and versions follow
[Semantic Versioning](https://semver.org).

## [0.16.0](https://github.com/magrhino/WUD-Updater/compare/v0.15.1...v0.16.0) (2026-05-28)


### Features

* **web:** [codex] add read-only WebUI API foundation ([#56](https://github.com/magrhino/WUD-Updater/issues/56)) ([285dabe](https://github.com/magrhino/WUD-Updater/commit/285dabe414db8ff1cb022abd33ab2c6839dc52d6))

## [0.15.1](https://github.com/magrhino/WUD-Updater/compare/v0.15.0...v0.15.1) (2026-05-25)


### Bug Fixes

* **updater:** preflight invalid compose ports ([#55](https://github.com/magrhino/WUD-Updater/issues/55)) ([4b0c1dc](https://github.com/magrhino/WUD-Updater/commit/4b0c1dcc3d50fc445d16239a587edbe29d708f9f))
* **updates:** allow selectable tag exclusions ([#53](https://github.com/magrhino/WUD-Updater/issues/53)) ([49864ec](https://github.com/magrhino/WUD-Updater/commit/49864eca3602f73698202755c3e458b446f9189f))

## [0.15.0](https://github.com/magrhino/WUD-Updater/compare/v0.14.1...v0.15.0) (2026-05-25)


### Features

* **doctor:** Add container doctor mode for WUD-Updater ([#51](https://github.com/magrhino/WUD-Updater/issues/51)) ([4446086](https://github.com/magrhino/WUD-Updater/commit/44460864c1699f2701d134072bd30e6ef5775f30))

## [0.14.1](https://github.com/magrhino/WUD-Updater/compare/v0.14.0...v0.14.1) (2026-05-24)


### Bug Fixes

* **updates:** handle pinned release self-updates ([d0f7b4e](https://github.com/magrhino/WUD-Updater/commit/d0f7b4e12038edf07b0672c99a1074b1cfe59f70))
* **updates:** pull release self-update image directly ([d473715](https://github.com/magrhino/WUD-Updater/commit/d4737157cd9bb1407553b1795a351442e5c5f756))

## [0.14.0](https://github.com/magrhino/WUD-Updater/compare/v0.13.0...v0.14.0) (2026-05-24)


### Features

* **updater:** Add prompted tag exclusions to the updater flow ([#48](https://github.com/magrhino/WUD-Updater/issues/48)) ([6ce34ce](https://github.com/magrhino/WUD-Updater/commit/6ce34cec024a96a88b0cc65832fdcd5de195992f))

## [0.13.0](https://github.com/magrhino/WUD-Updater/compare/v0.12.3...v0.13.0) (2026-05-23)


### Features

* **updates:** default host wrapper to python ([#45](https://github.com/magrhino/WUD-Updater/issues/45)) ([04ab55d](https://github.com/magrhino/WUD-Updater/commit/04ab55dcb673051326e51d5a70e86261a576f9f0))


### Bug Fixes

* **updates:** Fix WUD-Updater self-update fallback target ([#47](https://github.com/magrhino/WUD-Updater/issues/47)) ([3e2d268](https://github.com/magrhino/WUD-Updater/commit/3e2d26865304ef7dea97b463f29eac94c663db21))

## [0.12.3](https://github.com/magrhino/WUD-Updater/compare/v0.12.2...v0.12.3) (2026-05-21)


### Bug Fixes

* **updater:** record preflight-skipped audit rows ([ba9026f](https://github.com/magrhino/WUD-Updater/commit/ba9026f718cb2948ae31c720156b9b26cb8eec97))
* **updater:** report bind-mount preflight failures ([a23635e](https://github.com/magrhino/WUD-Updater/commit/a23635e76f09d47ca613f383d6c96d04160ca92c))

## [0.12.2](https://github.com/magrhino/WUD-Updater/compare/v0.12.1...v0.12.2) (2026-05-21)


### Bug Fixes

* **compose:** validate mapped host project directories ([#41](https://github.com/magrhino/WUD-Updater/issues/41)) ([6f1c3bb](https://github.com/magrhino/WUD-Updater/commit/6f1c3bbb738e4c1d11db31ac8d5366789f29c92f))

## [0.12.1](https://github.com/magrhino/WUD-Updater/compare/v0.12.0...v0.12.1) (2026-05-21)


### Bug Fixes

* **updater:** Warn on Compose bind mounts that resolve only inside the helper container ([#39](https://github.com/magrhino/WUD-Updater/issues/39)) ([7ac9399](https://github.com/magrhino/WUD-Updater/commit/7ac93994200cf3699b20d6d98213128ed0ecf550))

## [0.12.0](https://github.com/magrhino/WUD-Updater/compare/v0.11.1...v0.12.0) (2026-05-20)


### Features

* **db:** Use the existing SQLite3 DB for updater state ([#38](https://github.com/magrhino/WUD-Updater/issues/38)) ([ecc0829](https://github.com/magrhino/WUD-Updater/commit/ecc0829a29a1ed485bfb5b17eb2ea7436348c0dc))


### Bug Fixes

* **updater:** scope network consumer updates to matched service ([8ec7720](https://github.com/magrhino/WUD-Updater/commit/8ec77203540eec04d62dfec2d71b40779166205a))

## [0.11.1](https://github.com/magrhino/WUD-Updater/compare/v0.11.0...v0.11.1) (2026-05-20)


### Bug Fixes

* **updater:** expand network-mode lifecycle scope ([1ec9150](https://github.com/magrhino/WUD-Updater/commit/1ec9150bc1339494837b7a867c0e055ff6d185af))
* **updater:** include network-mode consumers in lifecycle scope ([19d0a33](https://github.com/magrhino/WUD-Updater/commit/19d0a33482dbb92f43a974f1948c974575daba11))

## [0.11.0](https://github.com/magrhino/WUD-Updater/compare/v0.10.1...v0.11.0) (2026-05-20)


### Features

* add startup banner release check ([4b3d99e](https://github.com/magrhino/WUD-Updater/commit/4b3d99efa481700e038aa389f713be6190fe98cd))


### Bug Fixes

* **updater:** avoid compose down for stack recreate ([a4ec1d8](https://github.com/magrhino/WUD-Updater/commit/a4ec1d897c14ac19fc77a886ba22d87344d5faad))

## [0.10.1](https://github.com/magrhino/WUD-Updater/compare/v0.10.0...v0.10.1) (2026-05-20)


### Bug Fixes

* **updater:** avoid pulling unrelated services during stack recreate ([b9b6da1](https://github.com/magrhino/WUD-Updater/commit/b9b6da15961f94346fec0efa7bf6750c995b22a3))

## [0.10.0](https://github.com/magrhino/WUD-Updater/compare/v0.9.2...v0.10.0) (2026-05-19)


### Features

* **updater:** allow service label to force stack recreation ([601f4bc](https://github.com/magrhino/WUD-Updater/commit/601f4bcaf3acc1a76bbf41cdc57c19ae0cf59514))


### Bug Fixes

* **updater:** map compose services from structured config ([1b74d5a](https://github.com/magrhino/WUD-Updater/commit/1b74d5a76630e74842a37f9fee0fd58e2dd2bb82))

## [0.9.2](https://github.com/magrhino/WUD-Updater/compare/v0.9.1...v0.9.2) (2026-05-19)


### Bug Fixes

* **ui:** omit empty rich panel style ([27a8fb2](https://github.com/magrhino/WUD-Updater/commit/27a8fb2be73389c5b4f8ab7adec907de88cd8bd3))

## [0.9.1](https://github.com/magrhino/WUD-Updater/compare/v0.9.0...v0.9.1) (2026-05-19)


### Bug Fixes

* **updates:** Fix tag update confirmation flow and harden compose tag rewrites ([#30](https://github.com/magrhino/WUD-Updater/issues/30)) ([e083d49](https://github.com/magrhino/WUD-Updater/commit/e083d4976ce53e6b4e31ba9ff4e2e9594c2433ba))

## [0.9.0](https://github.com/magrhino/WUD-Updater/compare/v0.8.0...v0.9.0) (2026-05-19)


### Features

* **updater:** Add tag override validation for WUD updates ([#28](https://github.com/magrhino/WUD-Updater/issues/28)) ([feb84c5](https://github.com/magrhino/WUD-Updater/commit/feb84c54ee39d55853ca9dc2c881ec737f241680))

## [0.8.0](https://github.com/magrhino/WUD-Updater/compare/v0.7.0...v0.8.0) (2026-05-19)


### Features

* **cli:** add rich terminal improvements ([#26](https://github.com/magrhino/WUD-Updater/issues/26)) ([d46170f](https://github.com/magrhino/WUD-Updater/commit/d46170ff7892337b63b9f34f8d338de219ec26f8))

## [0.7.0](https://github.com/magrhino/WUD-Updater/compare/v0.6.0...v0.7.0) (2026-05-19)


### Features

* **ci:** Add CodeQL analysis workflow configuration ([093ae59](https://github.com/magrhino/WUD-Updater/commit/093ae5991a8991134d057922e427a58b1d96429b))


### Bug Fixes

* **updater:** write default error reports for failed updates ([58c2696](https://github.com/magrhino/WUD-Updater/commit/58c2696b167c1ed547d677bd5ed703e34db7f19d))


### Documentation

* **truenas:** clarify status helper behavior ([3ad3c6f](https://github.com/magrhino/WUD-Updater/commit/3ad3c6f12abdcb9d664a33cef564b0427b72885a))

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
