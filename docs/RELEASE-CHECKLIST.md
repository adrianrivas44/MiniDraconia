# Release gate — 1.0.0-rc.1

This is an experimental community prerelease authorized by the maintainer. **Public availability does not complete unchecked items.** Technical checks below refer to frozen candidate F, which completes the Python/OpenSSL notice inventory after D; final community documentation was updated separately. This checklist is a transparent status record, not legal clearance or a stable-release certificate.

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
