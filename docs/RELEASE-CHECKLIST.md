# Release gate — 1.0.0-rc.1

This is an experimental community prerelease authorized by the maintainer. **Public availability does not complete unchecked items.** Technical checks below refer to frozen candidate D; final community documentation was updated separately. This checklist is a transparent status record, not legal clearance or a stable-release certificate.

- [ ] Source snapshot and first-publication scope frozen; maintainer reviewed exact public contents.
- [x] Dependencies documented and installed in a new isolated Windows virtual environment; pip check passed. Not a fresh-machine Windows installation.
- [x] Offline/unit/UI tests on real Windows with isolated profiles: 200 passed, 1 platform-specific skip, 0 failures/errors.
- [x] Frozen normal startup smoke and separate scripted selftest pass from the exact extracted ZIP, including a path with spaces and no development PYTHONPATH.
- [x] New user settings stay outside the installation; tested installation manifest remained unchanged. Existing laptop installation was not overwritten.
- [x] Source/binary manifests, ZIP CRC and all file hashes verified.
- [ ] Secret/private-data scan reviewed; archive traversal/symlinks/large files checked.
- [ ] Upstream copyright, code license and full dependency redistribution notices preserved.
- [ ] Character, art, voice and identity-document provenance/rights resolved. Maintainer has explicitly requested public exposure, which does not resolve third-party rights.
- [ ] Human visual/animation/fall/audio acceptance recorded; no unapproved clip enabled.
- [x] Independent technical review of frozen candidate completed; two final P2 gate issues corrected and reviewed. Separate rights/notice questions are not marked resolved.
- [x] Maintainer requested an open public community publication on the authenticated adrianrivas44 account; label 1.0.0-rc.1, not stable.
- [ ] Public push/release explicitly authorized, then destination read back and download tested.

The Windows ZIP belongs in Release assets, not in Git history. Source, tests and build instructions belong in the repository. Do not upload private intake archives, internal operation reports or a developer's environment.
