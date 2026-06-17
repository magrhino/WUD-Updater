# Changelog

All notable changes to WUD-Updater are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com) and versions follow
[Semantic Versioning](https://semver.org).

## [0.40.0](https://github.com/magrhino/WUD-Updater/compare/v0.39.0...v0.40.0) (2026-06-17)


### Features

* **snoozes:** Add dependency snooze support to the WebUI and backend ([#298](https://github.com/magrhino/WUD-Updater/issues/298)) ([f995092](https://github.com/magrhino/WUD-Updater/commit/f9950929858417916cfa789b0a7a992e96210d41))


### Bug Fixes

* **sonar:** SonarQube issues across updater and WebUI ([#326](https://github.com/magrhino/WUD-Updater/issues/326)) ([23b7788](https://github.com/magrhino/WUD-Updater/commit/23b77882391f481ff97b4b90df5c06e2ad553446))


### Documentation

* **webui:** prefer playwright plugin validation ([e80bd64](https://github.com/magrhino/WUD-Updater/commit/e80bd6440d25723e2bcc095a18fdb30e309463d3))

## [0.39.0](https://github.com/magrhino/WUD-Updater/compare/v0.38.4...v0.39.0) (2026-06-15)


### Features

* **retags:** Add Retags management support to the WebUI and backend ([#289](https://github.com/magrhino/WUD-Updater/issues/289)) ([60bea75](https://github.com/magrhino/WUD-Updater/commit/60bea75295822abc863cdfd077018423a0d304b8))
* **webui:** add post-update verification ([#287](https://github.com/magrhino/WUD-Updater/issues/287)) ([58abcce](https://github.com/magrhino/WUD-Updater/commit/58abccece8126cd551f9a6526726381463fb9a0f))

## [0.38.4](https://github.com/magrhino/WUD-Updater/compare/v0.38.3...v0.38.4) (2026-06-13)


### Bug Fixes

* **shell:** Fix shell portability and update path-aware Python tests ([#285](https://github.com/magrhino/WUD-Updater/issues/285)) ([f997b56](https://github.com/magrhino/WUD-Updater/commit/f997b5630945357ad69d74c7cfe5572797b0afb2))
* **updater:** Handle stale pending digest entries during WUD retries ([#284](https://github.com/magrhino/WUD-Updater/issues/284)) ([f525afb](https://github.com/magrhino/WUD-Updater/commit/f525afbfc7792e636f2620c2709d6b02897ede8f))
* **webui:** serialize run history digest provenance ([#282](https://github.com/magrhino/WUD-Updater/issues/282)) ([66a3add](https://github.com/magrhino/WUD-Updater/commit/66a3add7d2ff37280d04513be077014587e95bdd))

## [0.38.3](https://github.com/magrhino/WUD-Updater/compare/v0.38.2...v0.38.3) (2026-06-13)


### Bug Fixes

* **compose:** support digest unpin for multiline images ([#278](https://github.com/magrhino/WUD-Updater/issues/278)) ([f0979d2](https://github.com/magrhino/WUD-Updater/commit/f0979d28897f522adf8aef923e64fe44ff75c5be))

## [0.38.2](https://github.com/magrhino/WUD-Updater/compare/v0.38.1...v0.38.2) (2026-06-13)


### Bug Fixes

* **demo:** Refactor demo WebUI API into focused modules ([#273](https://github.com/magrhino/WUD-Updater/issues/273)) ([cbdfb4d](https://github.com/magrhino/WUD-Updater/commit/cbdfb4d462ec7677d62e55f47212f45275bbc856))
* **digest:** Persist digest tag provenance in SQLite and expose it through the WebUI ([#274](https://github.com/magrhino/WUD-Updater/issues/274)) ([ab4bf84](https://github.com/magrhino/WUD-Updater/commit/ab4bf84577b69c290bfb1e724e8a35e1a3e2673f))
* pending plan review and digest update flows ([#275](https://github.com/magrhino/WUD-Updater/issues/275)) ([795f972](https://github.com/magrhino/WUD-Updater/commit/795f9723bf8b87c83a5354c85fdc576e82a0730f))


### Documentation

* add vscode gitignore ([a8c17a7](https://github.com/magrhino/WUD-Updater/commit/a8c17a7ec8eec47217aac7e478bdd3f18e3e9642))

## [0.38.1](https://github.com/magrhino/WUD-Updater/compare/v0.38.0...v0.38.1) (2026-06-09)


### Bug Fixes

* **web:** remove facade monkeypatch seams ([#257](https://github.com/magrhino/WUD-Updater/issues/257)) ([c326990](https://github.com/magrhino/WUD-Updater/commit/c32699078507f1c0aa6114d18c205cea5d358862))


### Documentation

* Add demo link to Web Deployment section ([91b97ca](https://github.com/magrhino/WUD-Updater/commit/91b97caf126aadf274708e3d545b40f40f61776a))
* Add donation section to README ([59672f4](https://github.com/magrhino/WUD-Updater/commit/59672f4364b58e58b87ad90cda99dfe85a8e83e7))
* Fix header formatting in README.md ([fbdeab4](https://github.com/magrhino/WUD-Updater/commit/fbdeab4078f39844e27f6c04ffe526dc66b16bd8))
* guide agents toward composable backend modules ([#234](https://github.com/magrhino/WUD-Updater/issues/234)) ([c7c791e](https://github.com/magrhino/WUD-Updater/commit/c7c791e755b620f6b13e75d4e865d9d7cad3fcff))

## [0.38.0](https://github.com/magrhino/WUD-Updater/compare/v0.37.0...v0.38.0) (2026-06-07)


### Features

* Harden the updates wrapper and TrueNAS checks and Remove bash ([#217](https://github.com/magrhino/WUD-Updater/issues/217)) ([9550872](https://github.com/magrhino/WUD-Updater/commit/955087206482da482c13497b35fb5b0236e45d15))


### Bug Fixes

* [codex] harden digest-pin updates and CI maintenance ([#215](https://github.com/magrhino/WUD-Updater/issues/215)) ([bf47041](https://github.com/magrhino/WUD-Updater/commit/bf47041deb4ea0f6ae11c0206e1198e9e6c78db0))
* [codex] maintainability quick wins ([#216](https://github.com/magrhino/WUD-Updater/issues/216)) ([4a1bbee](https://github.com/magrhino/WUD-Updater/commit/4a1bbeeb4e0a01a7b007403e23335fd69e3aab93))
* **digest:** allow updater to read human tags and rewrite to regex ([#213](https://github.com/magrhino/WUD-Updater/issues/213)) ([c821414](https://github.com/magrhino/WUD-Updater/commit/c82141431301adc91cbd8aea227aec51335a6fb8))
* fix regression findings ([#229](https://github.com/magrhino/WUD-Updater/issues/229)) ([2c39377](https://github.com/magrhino/WUD-Updater/commit/2c39377002afcbd2543c90baa2de542f2f84f5eb))
* **tests:** run local full suite sections in parallel ([#211](https://github.com/magrhino/WUD-Updater/issues/211)) ([d48aae4](https://github.com/magrhino/WUD-Updater/commit/d48aae438f8f466300268d714e4093fa34d86490))

## [0.37.0](https://github.com/magrhino/WUD-Updater/compare/v0.36.1...v0.37.0) (2026-06-05)


### Features

* Support digest-pin rematching for tagged WUD entries ([#209](https://github.com/magrhino/WUD-Updater/issues/209)) ([d6fa1ad](https://github.com/magrhino/WUD-Updater/commit/d6fa1ad01c52f3248f8bea5d460d227473faba64))

## [0.36.1](https://github.com/magrhino/WUD-Updater/compare/v0.36.0...v0.36.1) (2026-06-05)


### Bug Fixes

* apply CodeRabbit auto-fixes ([87f84ba](https://github.com/magrhino/WUD-Updater/commit/87f84bad5cf91fc9a47784a4c8faf3e085f52932))
* Merge pull request [#205](https://github.com/magrhino/WUD-Updater/issues/205) from magrhino/codex/fix-webui-compose-ignore-default ([76922af](https://github.com/magrhino/WUD-Updater/commit/76922af3d07fdb738bffd7c0a303fd8729ef7c80))
* **webui:** clarify onboarding check diagnostics ([3068e85](https://github.com/magrhino/WUD-Updater/commit/3068e85d4660a3b2ae3757cc30ab1ea85e30b3ec))
* **webui:** preserve default compose ignores in doctor ([ea026bb](https://github.com/magrhino/WUD-Updater/commit/ea026bbd6f8695220753e7fa1d001e6ee6e03647))

## [0.36.0](https://github.com/magrhino/WUD-Updater/compare/v0.35.1...v0.36.0) (2026-06-05)


### Features

* **tests:** parallelize Python test suite with pytest-xdist ([dc16409](https://github.com/magrhino/WUD-Updater/commit/dc164096d24a4792da610fdf1bfd8794003158a8))
* **updater:** add digest-pin compose updates ([c0cc0dc](https://github.com/magrhino/WUD-Updater/commit/c0cc0dc27fb8e0096eb191203d38208ef3a23205))


### Bug Fixes

* apply CodeRabbit auto-fixes ([3a92885](https://github.com/magrhino/WUD-Updater/commit/3a928853f88ae44eb0cbb731618c966b14a0f674))
* apply CodeRabbit auto-fixes ([afc15a5](https://github.com/magrhino/WUD-Updater/commit/afc15a5f14721006681926781da65a7600c685a0))
* **digest:** reuse primary http resolver for index digest ([4348c5f](https://github.com/magrhino/WUD-Updater/commit/4348c5f6db14c714c0e6ab548a3cc402b3be0cb9))
* **updater:** reduce digest-pin verification false negatives ([e7b1005](https://github.com/magrhino/WUD-Updater/commit/e7b1005ee89bb94f34d688b1c4700caee7c189bf))
* **updater:** verify digest-pin self-update targets ([f203d68](https://github.com/magrhino/WUD-Updater/commit/f203d680a9b2a7e6a4b7497c8488732dc9711bc1))

## [0.35.1](https://github.com/magrhino/WUD-Updater/compare/v0.35.0...v0.35.1) (2026-06-05)


### Bug Fixes

* **webui:** pending update safety cues ([#197](https://github.com/magrhino/WUD-Updater/issues/197)) ([bb62b12](https://github.com/magrhino/WUD-Updater/commit/bb62b123128662197e76b8d6f415e5d177cefd0c))

## [0.35.0](https://github.com/magrhino/WUD-Updater/compare/v0.34.2...v0.35.0) (2026-06-04)


### Features

* **ui:** improve run history and audit log ([#195](https://github.com/magrhino/WUD-Updater/issues/195)) ([f6ad5e1](https://github.com/magrhino/WUD-Updater/commit/f6ad5e11536e9b6be360661bd7d8b43f225b106a))

## [0.34.2](https://github.com/magrhino/WUD-Updater/compare/v0.34.1...v0.34.2) (2026-06-04)


### Bug Fixes

* **webui:** Refine stale pending diagnostics in the WebUI ([#192](https://github.com/magrhino/WUD-Updater/issues/192)) ([8474f56](https://github.com/magrhino/WUD-Updater/commit/8474f5631aee1e59cd3171f49f8f4011b9bbef9f))

## [0.34.1](https://github.com/magrhino/WUD-Updater/compare/v0.34.0...v0.34.1) (2026-06-04)


### Bug Fixes

* **webui:** change default port to 7417 ([f099195](https://github.com/magrhino/WUD-Updater/commit/f09919568d4db6a48ddee674f1f836c528d88bec))


### Documentation

* Update and clarify docs to suggest webui is preferred deployment ([cc34c08](https://github.com/magrhino/WUD-Updater/commit/cc34c08db0d9f4ed70ff52330e8009ede23358a3))
* **webui:** clarify env examples for deployments ([7892792](https://github.com/magrhino/WUD-Updater/commit/7892792f8a8a8e50278daa0321ecf5d9113b594e))

## [0.34.0](https://github.com/magrhino/WUD-Updater/compare/v0.33.0...v0.34.0) (2026-06-04)


### Features

* **webui:** [codex] add apply preflight readiness summary ([#189](https://github.com/magrhino/WUD-Updater/issues/189)) ([1b180cc](https://github.com/magrhino/WUD-Updater/commit/1b180cc6d23b7429a9269dcebf1f7c2e13ec0fed))

## [0.33.0](https://github.com/magrhino/WUD-Updater/compare/v0.32.0...v0.33.0) (2026-06-03)


### Features

* **webui:** [codex] add WebUI self-update banner ([#184](https://github.com/magrhino/WUD-Updater/issues/184)) ([5e6b135](https://github.com/magrhino/WUD-Updater/commit/5e6b1354ae2294d757e4cd7b73c86ac223dcbc11))


### Documentation

* Add GNU General Public License v3 ([303fc72](https://github.com/magrhino/WUD-Updater/commit/303fc728e69c5df67c1fff209563d5203793005b))

## [0.32.0](https://github.com/magrhino/WUD-Updater/compare/v0.31.5...v0.32.0) (2026-06-03)


### Features

* **ui:** add diagnostics support bundle ([#182](https://github.com/magrhino/WUD-Updater/issues/182)) ([88408d5](https://github.com/magrhino/WUD-Updater/commit/88408d582886f5726f53ab823a0f6c84d74d0010))

## [0.31.5](https://github.com/magrhino/WUD-Updater/compare/v0.31.4...v0.31.5) (2026-06-02)


### Bug Fixes

* **ui:** harden static demo artifact tests ([28183c6](https://github.com/magrhino/WUD-Updater/commit/28183c67ef658d601a713a2c95809c81303adc5d))

## [0.31.4](https://github.com/magrhino/WUD-Updater/compare/v0.31.3...v0.31.4) (2026-06-02)


### Bug Fixes

* **verification:** Verify GHCR digests before applying WUD updates ([#174](https://github.com/magrhino/WUD-Updater/issues/174)) ([bab9707](https://github.com/magrhino/WUD-Updater/commit/bab97078512f5b45cc77e1a944e151566c0b2592))

## [0.31.3](https://github.com/magrhino/WUD-Updater/compare/v0.31.2...v0.31.3) (2026-06-01)


### Bug Fixes

* **webui:** clarify stack names on pending page ([4fa5fa8](https://github.com/magrhino/WUD-Updater/commit/4fa5fa83f16a6a3a76f57522e5170371ffa84737))
* **webui:** Collapse completed live logs behind a toggle ([#172](https://github.com/magrhino/WUD-Updater/issues/172)) ([98fe6ae](https://github.com/magrhino/WUD-Updater/commit/98fe6ae831045ea118b7b88fc42b258f1b940403))

## [0.31.2](https://github.com/magrhino/WUD-Updater/compare/v0.31.1...v0.31.2) (2026-06-01)


### Bug Fixes

* **ui:** improve login autofill handling ([9f37755](https://github.com/magrhino/WUD-Updater/commit/9f37755f4a947ad47277bd16408ac2f55d1a39a1))
* **webui:** Recover GitHub release links from running GHCR containers ([#159](https://github.com/magrhino/WUD-Updater/issues/159)) ([4de5ea7](https://github.com/magrhino/WUD-Updater/commit/4de5ea77b138fd4039ca62a9bb12bc8e388758be))

## [0.31.1](https://github.com/magrhino/WUD-Updater/compare/v0.31.0...v0.31.1) (2026-06-01)


### Bug Fixes

* **config:** honor updater and WebUI env defaults ([#154](https://github.com/magrhino/WUD-Updater/issues/154)) ([930380c](https://github.com/magrhino/WUD-Updater/commit/930380cc16b4c60788036a37ea646967b0af1d36))

## [0.31.0](https://github.com/magrhino/WUD-Updater/compare/v0.30.0...v0.31.0) (2026-06-01)


### Features

* **ui:** Add onboarding tour and relaunch controls to the WebUI ([#153](https://github.com/magrhino/WUD-Updater/issues/153)) ([b145167](https://github.com/magrhino/WUD-Updater/commit/b145167ff463b48e72f5a6718843941a404f497e))
* **ui:** Polish WebUI with clearer empty and completion states ([#150](https://github.com/magrhino/WUD-Updater/issues/150)) ([a49e1f2](https://github.com/magrhino/WUD-Updater/commit/a49e1f2883fc63a83a2a67384472308593ac7089))


### Bug Fixes

* **webui:** Add shared update-target helpers for management forms ([#152](https://github.com/magrhino/WUD-Updater/issues/152)) ([8461eea](https://github.com/magrhino/WUD-Updater/commit/8461eea806585fe9311372aabc9bbc67770c90b5))

## [0.30.0](https://github.com/magrhino/WUD-Updater/compare/v0.29.0...v0.30.0) (2026-05-31)


### Features

* **cli:** add init configuration wizard ([#147](https://github.com/magrhino/WUD-Updater/issues/147)) ([9e31e17](https://github.com/magrhino/WUD-Updater/commit/9e31e177fb56fa8c852f0762ea5fc930e52d2b3e))
* **webui:** add first-run onboarding checklist ([#145](https://github.com/magrhino/WUD-Updater/issues/145)) ([8743e21](https://github.com/magrhino/WUD-Updater/commit/8743e21dc13f10c4e2faee20f786ffcb6b5d2b58))
* **webui:** Add managed WebUI preferences to Settings ([#149](https://github.com/magrhino/WUD-Updater/issues/149)) ([8845c6e](https://github.com/magrhino/WUD-Updater/commit/8845c6eeb04b11f1900ecc1663106ea5db8776b8))
* **webui:** Add restart path setting to the WebUI ([#148](https://github.com/magrhino/WUD-Updater/issues/148)) ([2f1ec82](https://github.com/magrhino/WUD-Updater/commit/2f1ec823840a4c348861974657ec0bfdd0c49de7))

## [0.29.0](https://github.com/magrhino/WUD-Updater/compare/v0.28.0...v0.29.0) (2026-05-31)


### Features

* **webui:** add structured doctor results panel ([#142](https://github.com/magrhino/WUD-Updater/issues/142)) ([5404c35](https://github.com/magrhino/WUD-Updater/commit/5404c350693c88d162c334dc8c4336d1394a9f87))

## [0.28.0](https://github.com/magrhino/WUD-Updater/compare/v0.27.1...v0.28.0) (2026-05-31)


### Features

* **webui:** Polish the settings page for clearer runtime configuration ([#140](https://github.com/magrhino/WUD-Updater/issues/140)) ([550851c](https://github.com/magrhino/WUD-Updater/commit/550851c7c147a57ba8c266e6b323eca23110275a))


### Documentation

* **webui:** streamline compose env defaults ([285036b](https://github.com/magrhino/WUD-Updater/commit/285036bbd1d3eba5ea1b435cb5fe112221949c7a))

## [0.27.1](https://github.com/magrhino/WUD-Updater/compare/v0.27.0...v0.27.1) (2026-05-31)


### Bug Fixes

* **auth:** throttle failed webui logins ([#138](https://github.com/magrhino/WUD-Updater/issues/138)) ([405fee4](https://github.com/magrhino/WUD-Updater/commit/405fee47236b42fea501acf1d586ce8ae28a2229))

## [0.27.0](https://github.com/magrhino/WUD-Updater/compare/v0.26.0...v0.27.0) (2026-05-31)


### Features

* **webui:** Add selected pending-entry removal to the WebUI demo ([#135](https://github.com/magrhino/WUD-Updater/issues/135)) ([6bf9e11](https://github.com/magrhino/WUD-Updater/commit/6bf9e11ec1d19523abd934139d996c4e5f8bf709))

## [0.26.0](https://github.com/magrhino/WUD-Updater/compare/v0.25.0...v0.26.0) (2026-05-30)


### Features

* **ui:** add unmatched pending cleanup ([#133](https://github.com/magrhino/WUD-Updater/issues/133)) ([3747aea](https://github.com/magrhino/WUD-Updater/commit/3747aeab9c785fe9bc8fb164fbd37cee3518304d))

## [0.25.0](https://github.com/magrhino/WUD-Updater/compare/v0.24.2...v0.25.0) (2026-05-30)


### Features

* **webui:** Replace the sidebar mutation badge with a release link ([#130](https://github.com/magrhino/WUD-Updater/issues/130)) ([b43464a](https://github.com/magrhino/WUD-Updater/commit/b43464a0bc516358f5157c48ff318bca0727d06e))

## [0.24.2](https://github.com/magrhino/WUD-Updater/compare/v0.24.1...v0.24.2) (2026-05-30)


### Bug Fixes

* **ui:** Polish WebUI demo state and pending page interactions ([#127](https://github.com/magrhino/WUD-Updater/issues/127)) ([6c9a1a2](https://github.com/magrhino/WUD-Updater/commit/6c9a1a25010a2f069055c625f3642a9a1a5cf22e))

## [0.24.1](https://github.com/magrhino/WUD-Updater/compare/v0.24.0...v0.24.1) (2026-05-30)


### Bug Fixes

* **web:** Avoid resolving pending stack groups in status ([#123](https://github.com/magrhino/WUD-Updater/issues/123)) ([c963a55](https://github.com/magrhino/WUD-Updater/commit/c963a558d89a97644a40d0212de8a81ca3bbcea2))

## [0.24.0](https://github.com/magrhino/WUD-Updater/compare/v0.23.3...v0.24.0) (2026-05-30)


### Features

* **ui:** Add a system-aware theme toggle to the WebUI ([#121](https://github.com/magrhino/WUD-Updater/issues/121)) ([160af1f](https://github.com/magrhino/WUD-Updater/commit/160af1fcaad74bdc9f23203264331617d5449615))

## [0.23.3](https://github.com/magrhino/WUD-Updater/compare/v0.23.2...v0.23.3) (2026-05-29)


### Bug Fixes

* **release:** scope release lookup to repository ([d74e8f7](https://github.com/magrhino/WUD-Updater/commit/d74e8f7af29e44bf623fe5ed2ff956e8d9a37ca4))

## [0.23.2](https://github.com/magrhino/WUD-Updater/compare/v0.23.1...v0.23.2) (2026-05-29)


### Bug Fixes

* **release:** handle manifest release output fallback ([556c5f2](https://github.com/magrhino/WUD-Updater/commit/556c5f2f657fa2a5a933a7cd7afc7148f41aa63b))

## [0.23.1](https://github.com/magrhino/WUD-Updater/compare/v0.23.0...v0.23.1) (2026-05-29)


### Continuous Integration

* **release:** force 0.23.1 release check ([9f5ebc4](https://github.com/magrhino/WUD-Updater/commit/9f5ebc4b1216ee8552052a371502441277039f64))

## [0.23.0](https://github.com/magrhino/WUD-Updater/compare/v0.22.2...v0.23.0) (2026-05-29)


### Features

* **auth:** add WebUI admin recovery flow ([#109](https://github.com/magrhino/WUD-Updater/issues/109)) ([730e032](https://github.com/magrhino/WUD-Updater/commit/730e032ea73968cda23395c3d314de632e1949b6))
* **web:** add minimal unauthenticated health endpoint ([#108](https://github.com/magrhino/WUD-Updater/issues/108)) ([5be4e3a](https://github.com/magrhino/WUD-Updater/commit/5be4e3ab3094d5f3327fad46f8b8fe6106d2a4ac))

## [0.22.2](https://github.com/magrhino/WUD-Updater/compare/v0.22.1...v0.22.2) (2026-05-29)


### Bug Fixes

* **webui:** show recovery message for lost apply jobs ([#104](https://github.com/magrhino/WUD-Updater/issues/104)) ([584d111](https://github.com/magrhino/WUD-Updater/commit/584d1116261c7270fa72bcc862fc0b847cca4299))

## [0.22.1](https://github.com/magrhino/WUD-Updater/compare/v0.22.0...v0.22.1) (2026-05-29)


### Bug Fixes

* **webui:** explain unavailable release notes ([91dbb26](https://github.com/magrhino/WUD-Updater/commit/91dbb2641ea7583c271f6c1c989f9d96a51650f3))
* **webui:** resolve release notes from docker source labels ([6990546](https://github.com/magrhino/WUD-Updater/commit/6990546ca9a3770b232ff3798ea6d171c768c968))

## [0.22.0](https://github.com/magrhino/WUD-Updater/compare/v0.21.2...v0.22.0) (2026-05-29)


### Features

* **webui:** Preserve legacy Discord release-note payloads while adding a shared webui release-note helper ([#77](https://github.com/magrhino/WUD-Updater/issues/77)) ([5f2741c](https://github.com/magrhino/WUD-Updater/commit/5f2741c9d9d0300c9f60b3902490a4910a03e78d))

## [0.21.2](https://github.com/magrhino/WUD-Updater/compare/v0.21.1...v0.21.2) (2026-05-29)


### Bug Fixes

* **webui:** stabilize mobile shell accessibility ([#75](https://github.com/magrhino/WUD-Updater/issues/75)) ([d28638f](https://github.com/magrhino/WUD-Updater/commit/d28638f6ec05a02b9c993176f945043bef7f1f63))

## [0.21.1](https://github.com/magrhino/WUD-Updater/compare/v0.21.0...v0.21.1) (2026-05-29)


### Bug Fixes

* **webui:** Refine WebUI styling around shared Naive theme tokens ([#73](https://github.com/magrhino/WUD-Updater/issues/73)) ([6ba6122](https://github.com/magrhino/WUD-Updater/commit/6ba6122e3b81d7125f4ec3d80e350619d6ee8af6))

## [0.21.0](https://github.com/magrhino/WUD-Updater/compare/v0.20.1...v0.21.0) (2026-05-29)


### Features

* **ui:** improve pending update controls ([09f9ff1](https://github.com/magrhino/WUD-Updater/commit/09f9ff10f27c4747086a94f989d679625e28ca33))

## [0.20.1](https://github.com/magrhino/WUD-Updater/compare/v0.20.0...v0.20.1) (2026-05-29)


### Bug Fixes

* **ui:** Add parity pages for WebUI state management ([#69](https://github.com/magrhino/WUD-Updater/issues/69)) ([04373aa](https://github.com/magrhino/WUD-Updater/commit/04373aacc62b4d1c25f05afefed237ffafd68e73))

## [0.20.0](https://github.com/magrhino/WUD-Updater/compare/v0.19.0...v0.20.0) (2026-05-28)


### Features

* **webui:** Expose typed WebUI state operations ([#67](https://github.com/magrhino/WUD-Updater/issues/67)) ([3441090](https://github.com/magrhino/WUD-Updater/commit/34410908c4c15069e4c066317c12ff8ec9bb1346))

## [0.19.0](https://github.com/magrhino/WUD-Updater/compare/v0.18.0...v0.19.0) (2026-05-28)


### Features

* **webui:** Add safe WebUI plan application and container docs ([#64](https://github.com/magrhino/WUD-Updater/issues/64)) ([9b0fdff](https://github.com/magrhino/WUD-Updater/commit/9b0fdff3c2005c17279639d4008ed64a76ecaa81))

## [0.18.0](https://github.com/magrhino/WUD-Updater/compare/v0.17.0...v0.18.0) (2026-05-28)


### Features

* **ui:** Add local Vue dev server and seeded demo state ([#61](https://github.com/magrhino/WUD-Updater/issues/61)) ([d5b349d](https://github.com/magrhino/WUD-Updater/commit/d5b349d66f38d6a4ec0e867a575cb64cec380988))


### Bug Fixes

* **auth:** Add first-run setup and session-based login for the WebUI ([#63](https://github.com/magrhino/WUD-Updater/issues/63)) ([f40d0e9](https://github.com/magrhino/WUD-Updater/commit/f40d0e96d8b6fe820eaec1c0d01f88270205e12d))

## [0.17.0](https://github.com/magrhino/WUD-Updater/compare/v0.16.0...v0.17.0) (2026-05-28)


### Features

* **ui:** add read-only vue webui ([#58](https://github.com/magrhino/WUD-Updater/issues/58)) ([5d343c0](https://github.com/magrhino/WUD-Updater/commit/5d343c09d713787df5bf418e6965cadd5192edeb))

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
