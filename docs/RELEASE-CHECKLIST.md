# Release gates — 1.0.0-rc.1 and 1.0.0-rc.2

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

- [ ] Linux test suite green apart from the known environment reds, reviewed independently of the writer's report.
- [ ] Windows test run on a real Windows machine, including the DPAPI key round-trip test (skipped on Linux).
- [ ] Frozen normal startup smoke and scripted selftest of the exact extracted ZIP; release scan of tree and ZIP clean; no relay seed, key file or voice pack in the ZIP.
- [ ] Public tree names nothing of a private setup (private-word check and `scripts/scan_release.py`, with the maintainer's own `.release-private-markers`, both clean on the exact tagged commit).
- [ ] No AI provider preset: a new profile shows empty base URL and model and stays offline; *Test connection* and *Save* refuse empty fields.
- [ ] Your-own-AI mode exercised against a real hosted endpoint with a test key (text only, daily limit, *Forget key*) and against a real local server without a key.
  - Local half done on 2026-11-07: the tagged source's own client (Test connection, mode choice, typed chat, daily count) against a real Ollama on Windows 11 with no key; results in `docs/RECOMMENDED-SETUP.md`. The hosted half and the frozen UI path are still open.
- [ ] Self-hosted relay protocol in `docs/SELF-HOSTED-RELAY.md` exercised against a real relay (health, chat, voice); the public ZIP has no seed.
- [ ] Human review on a real display: walks travel without visible skating and look where they go, broom climb, talking, sit pose, the new mirror/quill/yawn clips, the icon, crisp frames at 150 %.
- [ ] Character, art (including the three new clips and the icon), voice and identity-document provenance/rights resolved. Public availability does not resolve third-party rights.
- [ ] Maintainer reviewed the exact public contents and authorized the push, tag and prerelease; Release assets read back and their SHA256 matched after an unauthenticated download.
