# MiniDraconia 1.0.0-rc.1

**First public community preview — experimental, not a stable release. / Primera publicación comunitaria — experimental, no estable.**

A Windows desktop companion built on DyberPet, with animated reactions and predefined English offline lines. This first public preview includes source/build documentation, contribution templates, the product soul in English and Spanish, the preserved visual identity manual, and a separate normal-startup packaging check.

## Let's improve her together / Mejoremos MiniDraconia juntos

This is my first public software project. Ideas, bug reports, translations, animation/dialogue improvements, tests and focused pull requests are welcome. You do not need to be an expert to contribute. Start with the [README](README.md) and [contribution guide](CONTRIBUTING.md), or [open an issue](https://github.com/adrianrivas44/MiniDraconia/issues).

Es mi primera publicación de software y quiero aprender con la comunidad. Si tienes una idea, una corrección o una mejora, compártela. Puedes probarla, proponer animaciones o diálogos, traducir, mejorar el código o explicar un problema. Empieza por el [README en español](README.es.md), crea un fork o [abre una issue](https://github.com/adrianrivas44/MiniDraconia/issues). Gracias por ayudar a que crezca.

— Zero / adrianrivas44

## Download and verification

- Download the Windows x64 ZIP, extract the entire folder, and run `MiniDraconia/MiniDraconia.exe`. Keep `_internal` beside it. Do not disable your antivirus for an unsigned build.
- The previous candidate-D baseline passed 200 Windows tests with one platform-specific skip. The public candidate-E build adds three regression tests and version/hash-verified interpreter/OpenSSL notices; its exact fresh suite and executable checks are recorded in the GitHub Release notes. These are automated/offscreen checks, not human visual/audio acceptance or a fresh Windows installation.
- The original build-source snapshot and build receipt are supplied to identify exactly what produced the executable; the repository's community documentation was updated for public publication afterward. Older preparation wording inside those immutable snapshots is historical, not the current repository status.
- Compare both public downloads against the `SHA256SUMS.txt` attached to the same GitHub prerelease. The earlier private candidate-D hashes do not identify the public candidate-E ZIP.
- The Windows test workflow is supplied as an inactive template, not claimed as green GitHub CI. See [development](docs/DEVELOPMENT.md) for activation instructions and the account-permission limitation.

## Intended correction

The early scripted test package omitted its normal startup module while its selftest passed. This candidate explicitly includes that module and requires real normal-startup evidence in addition to the scripted selftest. Check the build receipt for actual results; the presence of this note does not establish a successful build.

## Not included

No local language model, inference runtime, general AI chat or working Claude/xAI connector. The character soul is a reference document, not an installed model. Unapproved voice playback must remain disabled, and pending audio should not be distributed in the public candidate.

## Known limitations and provenance

Review the privacy/asset notices, remaining human animation/audio checks and rights questions before relying on or redistributing the materials. See `docs/RELEASE-CHECKLIST.md`, `docs/KNOWN-ISSUES.md` and `docs/RIGHTS-REVIEW.md`. The original identity manual describes an earlier private-use context and is preserved unchanged; the maintainer explicitly requested sharing it with this public project. That request does not grant rights belonging to third parties. The engine's GPL license and upstream attribution are preserved; it is not a blanket license for all character, voice, font or reference-derived material.

The raw archive scanner flagged one Qt DLL over 100 MiB. Its size/hash were verified against the installed wheel RECORD. It is included inside a Release ZIP, not as an oversized Git blob. The original finding is not erased; this specific packaging exception does not establish complete Qt/Chromium license compliance.

No compatibility, legal-clearance, clean-machine-install, human visual/audio acceptance or security certification is implied by public availability or the version number. General AI chat and Claude/xAI connectors remain future work, not implemented features.
