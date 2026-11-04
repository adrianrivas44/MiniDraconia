# MiniDraconia

A small Windows desktop companion with an expressive character, touch reactions and scripted offline lines. Built on [DyberPet](https://github.com/ChaozhongLiu/DyberPet).

**First community release candidate: 1.0.0-rc.1. Not a stable release.**

[Español](README.es.md) · [Contribute](CONTRIBUTING.md) · [Character & visual guide](docs/identity/README.md) · [Privacy](docs/PRIVACY.md) · [Roadmap](docs/ROADMAP.md)

## Why share it?

MiniDraconia started as a personal project. This is my first public software project, and I am opening it to learn and build with other people. If you have an idea, find a bug, or know how to improve her animations, dialogue, accessibility or code, you are welcome here. You do not need to be an expert: testing, translations, thoughtful suggestions and clear explanations all help.

**Help shape what comes next:** [share an idea or report a bug](https://github.com/adrianrivas44/MiniDraconia/issues), fork the project and send a focused pull request, or start with the [contribution guide](CONTRIBUTING.md). English and Spanish contributions are welcome.

— Zero / [adrianrivas44](https://github.com/adrianrivas44)

## What this version does

- Displays an animated desktop companion.
- Reacts to touch zones and dragging, with predefined English lines.
- Provides settings and a way to quit from the companion's menu.
- Keeps its preferences and scripted state in a per-user local folder, outside the installation.
- Gates prerecorded voice playback on individual clip approval and the user's audio settings.

**This is not an AI chat application yet.** No local language model or inference server is included. Connecting your own Claude or xAI model is a future contribution area, not a working integration. A ChatGPT/Claude/xAI subscription does not automatically provide API access. The included character “soul” describes a conversational persona; it does not enable a model, memory, microphone, camera or external tools.

## Run the Windows build

Use the Windows ZIP attached to the [1.0.0-rc.1 prerelease](https://github.com/adrianrivas44/MiniDraconia/releases/tag/v1.0.0-rc.1)—not the automatically generated source-code ZIP. This is an experimental community candidate, not a stable or security-certified release.

1. Extract the **entire** ZIP into an ordinary folder.
2. Open `MiniDraconia/MiniDraconia.exe`. Keep `_internal` beside the executable; it is required.
3. Use the companion's context menu for Settings or Quit.

Initial support target: **Windows 11 x64**. Other Windows versions, macOS and Linux are not validated targets for this candidate. No administrator access should be required to run the app. An unsigned build may trigger a Windows reputation warning; do not disable your antivirus to run it. Check the release checksum and provenance before deciding whether to trust a download.

Read the release notes and compare the download's SHA256 before opening it. The public Windows build comes from the frozen candidate-E source, which adds verified Python/OpenSSL notices to the earlier candidate D; community-facing documentation in this repository may be newer. See [the release checklist](docs/RELEASE-CHECKLIST.md) for verified checks and remaining limitations. Public availability does not mean all rights questions or human acceptance checks have been resolved.

## Develop and build

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for the tested Python version, setup, test runner and Windows build commands. Runtime code is under `full-engine/`; tests and packaging tools are in the repository root. Install/build evidence must come from a real Windows environment, not from merely reading a dependency file.

The build checks both the normal startup path and the separate scripted selftest. This matters: an early test ZIP passed its selftest but omitted its normal startup module. That packaging defect must not recur in community releases.

## Help improve it

Good first areas: Windows startup and scaling, native falling/drag behavior, animation transitions, accessibility, English dialogue polish, tests and dependency/build reproducibility. See the [roadmap](docs/ROADMAP.md) and [contribution guide](CONTRIBUTING.md). Please discuss large changes before implementing them.

## Character, credits and rights

Draconia is an **adult, fan-created reinterpretation inspired by Draco Malfoy**, not an official character or an affiliated product. The project does not claim ownership of the underlying franchise or its trademarks. A fan-project disclaimer is not a substitute for checking redistribution rights.

The inherited engine code retains its GPL-3.0 license and attribution to Chaozhong Liu/DyberPet. See [LICENSE](LICENSE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Code, character documents, images, fonts and generated audio require separate provenance checks; the code license does not license third-party characters, brands or provider services. See [rights review](docs/RIGHTS-REVIEW.md).
