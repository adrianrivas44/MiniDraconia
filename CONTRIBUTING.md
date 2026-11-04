# Contributing to MiniDraconia

Thank you for helping with a first community project. Small, reproducible contributions are easier to review than complete rewrites. English and Spanish reports are welcome; the current app dialogue is English.

**También puedes participar sin programar.** Cuéntanos qué no entiendes, prueba una versión, sugiere una animación o mejora una traducción. Abre una [issue](https://github.com/adrianrivas44/MiniDraconia/issues) en español o inglés. Para cambios de código, crea un fork y envía un pull request; explica qué cambia y cómo lo comprobaste. No necesitas una invitación para empezar.

## Before starting

Read the README and roadmap. For a large behavior change, new provider, dependency, character redesign or licensing change, open a discussion/issue first. Do not assume an item on the roadmap is already assigned or approved.

## Report a bug

Include the version, Windows version/architecture, whether you used the release ZIP or source, expected vs actual behavior, and short reproduction steps. A cropped screenshot or sanitized startup diagnostic can help. **Remove your name, local paths, messages, tokens and account information before sharing logs.** Never attach your complete AppData folder or credential files.

## Work on the code

Follow [DEVELOPMENT.md](docs/DEVELOPMENT.md). Use a separate branch, keep changes focused and add a test for a bug before fixing it. Run the test runner. For startup/packaging changes, run the extracted Windows executable's normal startup smoke **and** its selftest; one does not replace the other. Include exact commands and results in your pull request, and say what you could not test.

Do not add model weights, inference runtimes, generated build directories, user profiles or secrets to Git. Do not add automatic installers, telemetry, external model calls or auto-updates without explicit design review. Offline mode must remain usable without an account.

## Character and assets

Read [the identity guide](docs/identity/README.md) before changing her dialogue or art. The original source documents and the desktop's limited scripted implementation are different layers. Do not claim a dialogue safety case has passed merely because a prompt describes it. Changes to prerecorded clips need individual listening review; do not flip approval flags to pass tests.

Keep provenance and existing license notices. Do not submit material you cannot lawfully share, official franchise artwork/logos, copied commercial voices, private conversations or personal photos without appropriate permission. Generated assets still need source/provider/provenance review. Avoid blanket “all assets are open source” claims.

## Pull-request checklist

- What user-visible problem does this solve?
- What changed, and what deliberately did not change?
- Which test failed before the fix, and what passes now?
- Were privacy, offline behavior and upstream attribution preserved?
- Are new assets/dependencies documented with provenance and license information?
- What remains untested or needs human review?

Use respectful, specific feedback. Critique code and behavior, not people. Do not share secrets in an issue, a screenshot or a pull request. For a security problem, follow [SECURITY.md](SECURITY.md).
