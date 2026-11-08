# Release gates — 1.0.0-rc.1, 1.0.0-rc.2 and 1.0.0-rc.3

This is an experimental community prerelease authorized by the maintainer. **Public availability does not complete unchecked items.** The first list is 1.0.0-rc.1's: its technical checks refer to frozen candidate F, which completes the Python/OpenSSL notice inventory after D; final community documentation was updated separately. This checklist is a transparent status record, not legal clearance or a stable-release certificate.

- [ ] Source snapshot and first-publication scope frozen; maintainer reviewed exact public contents.
- [x] Dependencies documented and installed in a new isolated Windows virtual environment; pip check passed. Not a fresh-machine Windows installation.
- [x] Offline/unit/UI tests on real Windows with isolated profiles: 204 passed, 1 platform-specific skip, 0 failures/errors (205 registered).
- [x] Frozen normal startup smoke and separate scripted selftest pass from the exact extracted ZIP, including a path with spaces and no development PYTHONPATH.
- [x] New user settings stay outside the installation; tested installation manifest remained unchanged. Existing laptop installation was not overwritten.
- [x] Source/binary manifests, ZIP CRC and all file hashes verified.
- [x] Secret/private-data scan reviewed; archive traversal/symlinks/large files checked. The sole raw archive finding is the exact verified Qt DLL over the Git-blob threshold, reviewed as a Release ZIP exception, not silently suppressed.
- [ ] Upstream copyright, code license and full dependency redistribution notices preserved.
  - Existing code notices are preserved. Python 3.11.15 LICENSE and OpenSSL 3.5.7 LICENSE/AUTHORS were added, with runtime DLL matching and version/hash validation. Complete component-specific Qt/Chromium coverage is not certified.
- [ ] Character, art, voice and identity-document provenance/rights resolved. Maintainer has explicitly requested public exposure, which does not resolve third-party rights.
- [ ] Human visual/animation/fall/audio acceptance recorded; no unapproved clip enabled.
- [x] Independent technical review of D completed; two final P2 gate issues corrected and reviewed. Publication review identified missing interpreter/OpenSSL notices; F corrects those and rechecks the final build, integrity, normal startup and all tests. No independent whole-tree F re-audit is claimed. Separate rights/notice questions are not marked resolved.
- [x] Maintainer requested an open public community publication on the authenticated adrianrivas44 account; label 1.0.0-rc.1, not stable.
- [x] Public push/release explicitly authorized; repository, tag and prerelease read back. All three Release assets were then fully downloaded without authentication and their byte counts/SHA256 matched. Publication/download verification does not complete the unchecked human or rights items above.

The Windows ZIP belongs in Release assets, not in Git history. Source, tests and build instructions belong in the repository. Do not upload private intake archives, internal operation reports or a developer's environment.

## 1.0.0-rc.2 — publication gate

An item is checked only with evidence attached to the publication record. Technical results from the writer's Linux run are inputs to review, not acceptance.

- [x] Linux test suite green apart from the known environment reds, reviewed independently of the writer's report.
  - Linux 558 tests, only the 7 known environment reds; Evidence: the maintainer's acceptance record of 2026-11-07.
- [x] Windows test run on a real Windows machine, including the DPAPI key round-trip test (skipped on Linux).
  - Windows 11 Pro, 559 tests, 0 failures, 3 skips; real DPAPI round trip passed.
- [x] Frozen normal startup smoke and scripted selftest of the exact extracted ZIP; release scan of tree and ZIP clean; no relay seed, key file or voice pack in the ZIP.
  - Startup smoke and selftest passed from the exact ZIP; ZIP scan clean apart from the reviewed Qt DLL size exception; no seed, key file or voice pack in the ZIP.
- [x] Public tree names nothing of a private setup (private-word check and `scripts/scan_release.py`, with the maintainer's own `.release-private-markers`, both clean on the exact tagged commit).
  - Private-word test and `scripts/scan_release.py` with the maintainer's markers clean on `ea4261b`.
- [x] No AI provider preset: a new profile shows empty base URL and model and stays offline; *Test connection* and *Save* refuse empty fields.
  - Covered by the Settings tests on Linux and Windows (empty fields, offline, refusals).
- [x] Your-own-AI mode exercised against a real hosted endpoint with a test key (text only, daily limit, *Forget key*) and against a real local server without a key.
  - Checked after publication with the tagged client: a hosted endpoint (Test connection, wrong key, six typed replies, daily limit) and a real Ollama server on Windows with no key; results in `docs/RECOMMENDED-SETUP.md`. *Forget key* is covered by the Windows key-store tests, not by a hosted run.
  - Local half done on 2026-11-07: the tagged source's own client (Test connection, mode choice, typed chat, daily count) against a real Ollama on Windows 11 with no key; results in `docs/RECOMMENDED-SETUP.md`. The hosted half and the frozen UI path are still open.
- [ ] Self-hosted relay protocol in `docs/SELF-HOSTED-RELAY.md` exercised against a real relay (health, chat, voice); the public ZIP has no seed.
- [ ] Human review on a real display: walks travel without visible skating and look where they go, broom climb, talking, sit pose, the new mirror/quill/yawn clips, the icon, crisp frames at 150 %.
- [ ] Character, art (including the three new clips and the icon), voice and identity-document provenance/rights resolved. Public availability does not resolve third-party rights.
- [x] Maintainer reviewed the exact public contents and authorized the push, tag and prerelease; Release assets read back and their SHA256 matched after an unauthenticated download.
  - Push, tag and prerelease authorized by the maintainer; all three assets downloaded without authentication, byte counts and SHA256 matched.

## 1.0.0-rc.3 — publication gate

Same rule: an item is checked only with evidence attached to the publication record. The writer's Linux run and its stand-in servers are inputs to review, not acceptance. The unchecked rc.2 items above stay open unless their own evidence is recorded.

- [x] Linux test suite green apart from the known environment reds, reviewed independently of the writer's report.
  - Linux run on the release commit: only the 7 known environment reds.
- [x] Windows test run on a real Windows machine from a source export of the exact tagged commit, including the DPAPI key round-trip test; skips read and explained.
  - Windows 11 Pro from a source export of the release commit: 618 tests, 0 failures, 3 skips (two git-only checks, one off-Windows check); real DPAPI round trip passed.
- [x] Frozen normal startup smoke and scripted selftest of the exact extracted ZIP; release scan of tree and ZIP clean; no relay seed, key file or voice pack in the ZIP; `VERSION` and the executable's version info say `1.0.0-rc.3`.
  - Startup smoke and selftest passed from the exact ZIP; scan of tree and ZIP clean apart from the reviewed Qt DLL size exception; no seed, key file or voice pack; version 1.0.0-rc.3.
- [x] Public tree names nothing of a private setup (private-word check and `scripts/scan_release.py`, with the maintainer's own `.release-private-markers`, both clean on the exact tagged commit).
  - Private-word test and `scripts/scan_release.py` with the maintainer's markers clean on the release commit.
- [x] `localhost` against a real local server on Windows: Settings keeps `http://localhost:11434/v1` as typed, requests go to `127.0.0.1`, and replies are as fast as with `127.0.0.1` (median compared with the rc.2 measurement).
  - Real Ollama on Windows with this build's client: median about 0.3 s through `localhost` and through `127.0.0.1` (rc.2: 2.3 s vs 0.36 s). The saved value keeping `localhost` is covered by the Settings tests.
- [x] Cold start against a real local server on Windows: the warm-up runs at start and on save, never changes the daily count, and the first typed message after a server restart gets a real reply (or, past 90 s, a stored line), with her thinking pose while it waits; Settings stays responsive during *Test connection*.
  - After a server restart (model not loaded) the first typed message got a real reply in 6.4–7.8 s over three builds; the warm-up never counts (live test and unit tests).
- [x] A weaker local model (for example `llama3.2:3b`): no `assistant` / `assistant>` / `Draconia:` prefix or bracket junk reaches the bubble.
  - `llama3.2:3b` on Windows: no role prefix or bracket junk in the bubble; its real strings are in the reply-cleaning tests.
- [x] Opt-in live test `tests/test_live_endpoints.py` run on Windows against a real local server with `MINIDRACONIA_LIVE_LOCAL_URL` and `MINIDRACONIA_LIVE_LOCAL_MODEL` set and no key.
  - Ran in the Windows test run against Ollama (`http://localhost:11434/v1`, `qwen2.5:7b-instruct`, no key): passed.
- [ ] The frozen app's Settings screen exercised against a real local server (Test connection, Save, a typed chat) by a person on a real display.
- [x] Your-own-AI mode against a real hosted endpoint with a test key (text only, daily limit, *Forget key*); hosted timeouts unchanged at 20 s.
  - Hosted run on 2026-11-07 with the rc.2 client, unchanged for hosted endpoints in rc.3 (20 s timeout covered by tests): Test connection, wrong key, six typed replies, daily limit. *Forget key* is covered by the Windows key-store tests.
- [x] `RELEASE-NOTES.md` test-result placeholders replaced with the real results, or the unrun checks named as not run.
  - Filled in with the results above; unrun checks are named as not run.
- [ ] Human review on a real display of the items still open from rc.2 (walks, broom climb, talking, sit pose, mirror/quill/yawn, the icon, crisp frames at 150 %).
- [ ] Character, art, voice and identity-document provenance/rights resolved. Public availability does not resolve third-party rights.
- [ ] Maintainer reviewed the exact public contents and authorized the push, tag and prerelease; Release assets read back and their SHA256 matched after an unauthenticated download.
