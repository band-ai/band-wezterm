# Changelog

## [0.4.1](https://github.com/band-ai/band-wezterm/compare/v0.4.0...v0.4.1) (2026-09-20)


### Bug Fixes

* **release:** add no-clone installers ([#10](https://github.com/band-ai/band-wezterm/issues/10)) ([250f9ce](https://github.com/band-ai/band-wezterm/commit/250f9ce0e97ed9ec4e4f210781fc8546e8a35082))

## [0.4.0](https://github.com/band-ai/band-wezterm/compare/v0.3.0...v0.4.0) (2026-09-20)


### Features

* add band command ([3603943](https://github.com/band-ai/band-wezterm/commit/36039435f316726dd8865f527c0a5411e1cfeba5))
* discover harness model catalogs live ([19337bd](https://github.com/band-ai/band-wezterm/commit/19337bd4a69d32740d2a5a0755c7cfbcf0f4ba1b))
* **install:** support remote script installation ([0aed038](https://github.com/band-ai/band-wezterm/commit/0aed0383941650a8917a080246d92f7bed5782ad))
* **rooms:** manage agents from roster ([608165a](https://github.com/band-ai/band-wezterm/commit/608165a28c0a5179293be7b1e550ac3e63d6a2e4))
* show agents and rooms in split workspace ([654d6b8](https://github.com/band-ai/band-wezterm/commit/654d6b87c0d9670a34a398532139ac3ce39318f6))


### Bug Fixes

* **agents:** reconcile stale catalog entries ([8e3e999](https://github.com/band-ai/band-wezterm/commit/8e3e9995e2553cc0dd4cb9957281d30c71b744d0))
* **agents:** validate harnesses before registration ([67ab5d1](https://github.com/band-ai/band-wezterm/commit/67ab5d11c7b9c7c907c602fe624cf32283a5b421))
* **auth:** target production endpoints by default ([fc1f937](https://github.com/band-ai/band-wezterm/commit/fc1f93724a89ab83bc2a1bed2c23850e401da4e9))
* **claude:** prevent unsupported effort bridge crash ([5eb2dec](https://github.com/band-ai/band-wezterm/commit/5eb2dec116b6e9e0389e61d7454f8c3ae525917f))
* **control:** refresh harness model catalogs ([1a29b7f](https://github.com/band-ai/band-wezterm/commit/1a29b7f76f3ab62023dbef5aa021fa98719d6a76))
* **control:** refresh platform catalogs automatically ([6b1a70c](https://github.com/band-ai/band-wezterm/commit/6b1a70c6636ad2359701b967b3ab91a8076b72c8))
* **control:** serialize realtime and window lifecycle ([0189328](https://github.com/band-ai/band-wezterm/commit/01893284a85353a158d236f0c408f444df8f97c0))
* ignore stale authentication failures ([252acbe](https://github.com/band-ai/band-wezterm/commit/252acbe6610d2964e061977cad0335834c950d46))
* install stable releases by default ([fc04d87](https://github.com/band-ai/band-wezterm/commit/fc04d87299203a881a8ac0c99692b90038182ffe))
* **opencode:** manage shared bridge server ([439c4f1](https://github.com/band-ai/band-wezterm/commit/439c4f1b5650c5416686c2c9120e507498ebd796))
* **runtime:** reconcile closed agent tabs globally ([a7b30f4](https://github.com/band-ai/band-wezterm/commit/a7b30f46a0af993da27e473c67f73fd494890137))


### Documentation

* clarify OAuth deployment settings ([a7167a7](https://github.com/band-ai/band-wezterm/commit/a7167a76b78a7dedf22f99de0a2f65a768d32bef))
* refresh workspace guide and screenshots ([e98def0](https://github.com/band-ai/band-wezterm/commit/e98def0a45a0449e7d9255ecf49b91653d2deca2))

## [0.3.0](https://github.com/band-ai/band-wezterm/compare/v0.2.0...v0.3.0) (2026-09-20)


### Features

* **agents:** add private harness consoles ([#7](https://github.com/band-ai/band-wezterm/issues/7)) ([fbebb27](https://github.com/band-ai/band-wezterm/commit/fbebb272bdc795a4531896d2643d27ffa91339ee))
* **auth:** bundle the shared VS Code/Jam public OAuth client ([7fd99b1](https://github.com/band-ai/band-wezterm/commit/7fd99b1b2434c4f958fc439cf17de2a4a23ec5f7))
* **control:** delete rooms with two-press confirm ([1a1fbc0](https://github.com/band-ai/band-wezterm/commit/1a1fbc0d5521a18b7969533919647aaa8817b6b1))
* **control:** roles, model tuning, and host settings (VSC parity) ([2605689](https://github.com/band-ai/band-wezterm/commit/260568956024bddbec10964555d97bed2ea80978))
* **control:** show room agent state ([808912f](https://github.com/band-ai/band-wezterm/commit/808912f04dc921acea7b1f8ac50ea9630ec780b7))
* **control:** sign out, reconfigure/delete agent, role library ([765bc7d](https://github.com/band-ai/band-wezterm/commit/765bc7d34cff36ea5ea179b9f3d20ef4e454931d))
* install via git+uv with WezTerm plugin and setup ([#6](https://github.com/band-ai/band-wezterm/issues/6)) ([e7dd245](https://github.com/band-ai/band-wezterm/commit/e7dd2458d828fd5bf9534b258dee7c7a24c1942c))
* **install:** add Windows installer ([523cd30](https://github.com/band-ai/band-wezterm/commit/523cd30ea389090da85e4934ec66bceff63ed555))
* **mentions:** complete handles with tab ([0c92ee3](https://github.com/band-ai/band-wezterm/commit/0c92ee3a6cf33c0e445dab6241f73951d6d3822e))


### Bug Fixes

* **agents:** bind role identity at launch ([9df0b1b](https://github.com/band-ai/band-wezterm/commit/9df0b1be3870bae204eb84db5136430666329d1b))
* **agents:** make reconfigure keyboard-safe ([4463af6](https://github.com/band-ai/band-wezterm/commit/4463af643a6fc66257f274de8c87082f811fb47d))
* **agents:** register with valid names and selected tuning ([bcb8372](https://github.com/band-ai/band-wezterm/commit/bcb8372d23ff5431f6eaea08422b517ac17565de))
* **agents:** show live agent runtime ([73dfb7d](https://github.com/band-ai/band-wezterm/commit/73dfb7d0cd46ba88b6cd36c20a561c0cf9a3f471))
* **agents:** surface catalog operations ([22257cf](https://github.com/band-ai/band-wezterm/commit/22257cfd29a57a5b6bfd30261cd343eb224723d8))
* **auth:** complete browser sign-in callback ([ea0a4fe](https://github.com/band-ai/band-wezterm/commit/ea0a4fe5b7c6fe80bd9a7f6fb6fcc64b673e189f))
* **auth:** return to sign-in after rejected sessions ([e87b824](https://github.com/band-ai/band-wezterm/commit/e87b824acc3a5f3491b98b841234a5ce95f8a1d7))
* clear ruff violations from harness merge onto main ([2fd37dc](https://github.com/band-ai/band-wezterm/commit/2fd37dc1e712b7559f29987aa70e00b4fed71f98))
* **codex:** migrate rejected model alias ([876ce17](https://github.com/band-ai/band-wezterm/commit/876ce178ad843788f983624ed1df4c6af83ad541))
* **codex:** replace unsupported model option ([7f1ef07](https://github.com/band-ai/band-wezterm/commit/7f1ef0722bd23e19407b7af871633d4be0c9b36c))
* **control:** require managed profile on start; wire Copilot effort ([#5](https://github.com/band-ai/band-wezterm/issues/5)) ([6e469be](https://github.com/band-ai/band-wezterm/commit/6e469be6d15236bc6ea7f594c3f27163d60ac3c1))
* **host:** attach/restart Control and add just recipes ([a22df3c](https://github.com/band-ai/band-wezterm/commit/a22df3c2e82389866d6fb318196ce61e1287c40f))
* **install:** provision harness extras ([#8](https://github.com/band-ai/band-wezterm/issues/8)) ([b9ba146](https://github.com/band-ai/band-wezterm/commit/b9ba146b40cd948db340611bcfea343d3a35f251))
* **launcher:** detach gui bootstrap ([90f3638](https://github.com/band-ai/band-wezterm/commit/90f36389e49824369f165fe115727b377ca59dbf))
* **launcher:** recover restart window race ([53f90c1](https://github.com/band-ai/band-wezterm/commit/53f90c1953fd94cde8c2ccd2f277284465452817))
* **launcher:** recover when wezterm gui is unavailable ([3dd0d9f](https://github.com/band-ai/band-wezterm/commit/3dd0d9fd71f13a361df3ed80f6ddca2a104bc70b))
* **mentions:** complete handles with spaces ([7c0b9c5](https://github.com/band-ai/band-wezterm/commit/7c0b9c5bba6b44dcc29c534fd2728d9cad772250))
* **rooms:** accept roster-name mentions ([6da88ef](https://github.com/band-ai/band-wezterm/commit/6da88ef1840adb19e79eea883e43b548f4e5fe28))
* **setup:** repair comment-only WezTerm configs ([d0e5204](https://github.com/band-ai/band-wezterm/commit/d0e5204b698797d6f3cd81f5c615696ccff876c3))


### Documentation

* **agents:** document justfile recipes for local workflows ([a7a90aa](https://github.com/band-ai/band-wezterm/commit/a7a90aa7929fe2360309c9351c480383809c8f73))
* polish README for open-source landing ([9b0418a](https://github.com/band-ai/band-wezterm/commit/9b0418a83667c59a057d60c9c9f9eeafbac12a00))

## [0.2.0](https://github.com/band-ai/band-wezterm/compare/v0.1.0...v0.2.0) (2026-09-19)


### Features

* scaffold Band WezTerm host discovery PoC for INT-1496 ([d117f6c](https://github.com/band-ai/band-wezterm/commit/d117f6cfe1f80513533a1d8a5c478055f601aa10))
* **wezterm:** Band-client discovery PoC (INT-1496) ([b69d836](https://github.com/band-ai/band-wezterm/commit/b69d83603074f357c8703cb82ae08605f90295a7))


### Bug Fixes

* add All room filter so Starred is clearly a filter chip ([2795f32](https://github.com/band-ai/band-wezterm/commit/2795f32d02fcc2b5a9f2495bce7c7ed8687056ef))
* harden auth, realtime, OSC announce, and live-test harness ([def90e9](https://github.com/band-ai/band-wezterm/commit/def90e9e28bded6bad40c570b6e66ecdb16816ab))
* load room message history on enter ([52585de](https://github.com/band-ai/band-wezterm/commit/52585dec496a160123b3e3d0606740b4a69efef5))
* make agent filter chips exclusive with an All option ([78749d1](https://github.com/band-ai/band-wezterm/commit/78749d1963b53957419e1e78c4ef56f1aa885172))
* name Control and agent tabs instead of process/initials ([80859a4](https://github.com/band-ai/band-wezterm/commit/80859a489122dc06c4d75497416344387aab936e))
