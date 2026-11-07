# MiniDraconia

A small Windows desktop companion with an expressive character who walks, climbs on her broom, reacts to touch and talks: offline lines by default, or your own AI if you connect one. Built on [DyberPet](https://github.com/ChaozhongLiu/DyberPet).

**Release candidate 1.0.0-rc.2, the latest prerelease. Experimental, not a stable release.**

[Español](README.es.md) · [Contribute](CONTRIBUTING.md) · [Character & visual guide](docs/identity/README.md) · [Connect your own AI](docs/CONNECT-YOUR-AI.md) · [Recommended setup & tests](docs/RECOMMENDED-SETUP.md) · [Privacy](docs/PRIVACY.md) · [Roadmap](docs/ROADMAP.md)

## Why share it?

MiniDraconia started as a personal project. This is my first public software project, and I am opening it to learn and build with other people. If you have an idea, find a bug, or know how to improve her animations, dialogue, accessibility or code, you are welcome here. You do not need to be an expert: testing, translations, thoughtful suggestions and clear explanations all help.

**Help shape what comes next:** [share an idea or report a bug](https://github.com/adrianrivas44/MiniDraconia/issues), fork the project and send a focused pull request, or start with the [contribution guide](CONTRIBUTING.md). English and Spanish contributions are welcome.

— Zero / [adrianrivas44](https://github.com/adrianrivas44)

## What this version does

- Displays an animated desktop companion, crisp at the screen's scaling, who walks across the screen (and looks where she goes), follows the cursor, climbs the screen edges on her broom, sits, reads and sips her tea.
- New in 1.0.0-rc.2: three animations of her own (**mirror**, **quill** and **yawn**: she yawns before she dozes off), and her own app icon for the executable, her window, the tray and Settings.
- Reacts to touch zones and dragging. She visibly talks while a line is on screen.
- Talks in English: offline lines by default, your own AI if you connect one, or a self-hosted relay (see below). Type to her from her menu (“Talk to Draconia”).
- Supports an optional voice pack that anyone can record for her stored lines ([voice pack](docs/VOICE-PACK.md)); none is included.
- Provides settings and a way to quit from the companion's menu.
- Keeps its preferences and state in a per-user local folder, outside the installation.
- Gates prerecorded voice playback on individual clip approval and the user's audio settings.

No local language model or inference server is included. The included character “soul” describes her persona; it does not enable memory, a microphone, a camera or external tools.

## Talking to Draconia

She has three modes, and nothing is preset: the download points at no AI provider.

- **Offline (default).** She answers from her built-in English lines. Nothing is sent anywhere, and no account is needed.
- **Your own AI (optional).** In *Settings → AI / Privacy → Connect your own AI*, fill in the base URL and the model name of any OpenAI-compatible endpoint: a hosted service you choose (with your API key) or a server on your own computer, such as Ollama (`http://localhost:11434/v1`) or LM Studio (`http://localhost:1234/v1`), which needs no key. The fields start empty; *Test connection* sends one tiny request. A key is never sent over plain `http://` to another computer. A chat subscription is not an API key. A hosted service may charge your account, so a daily request limit (200 by default, editable) stops her from sending more; past it she answers offline until the next day. See [connect your own AI](docs/CONNECT-YOUR-AI.md).
- **Self-hosted relay (advanced).** If you run your own relay service, a `minidraconia_relay.json` file beside the executable connects her typed chat to it, voice included. The download contains none. See [self-hosted relay](docs/SELF-HOSTED-RELAY.md) for the exact protocol.
- **What spends what.** Pats, pinches, pokes, drags, falls, greetings, goodbyes, idle remarks and her spontaneous chatter always use her stored lines on your computer, in every mode: they never send anything and never spend a request. Only a message you type in *Talk to Draconia* goes to your AI, and only that counts toward the daily limit.
- **What is sent, and to whom.** Only with your own AI or a self-hosted relay, only when you send a typed message, and only to the address you configured: that message and the recent typed conversation (kept in memory only), with her character prompt for your own AI. Nothing else: no desktop events, files, screenshots or keystrokes. The service may keep what it receives under its own terms.
- **Your key** is stored encrypted on your device with Windows (DPAPI, for your Windows user only). It is never written in plain text, shown again or logged. *Forget key* deletes it.
- If anything fails (no connection, a rejected key, the limit), she answers from her offline lines; the bubble always works.

See [privacy](docs/PRIVACY.md) for the details.

## Run the Windows build

Use the Windows ZIP attached to the [latest prerelease](https://github.com/adrianrivas44/MiniDraconia/releases) (1.0.0-rc.2)—not the automatically generated source-code ZIP. This is an experimental community candidate, not a stable or security-certified release.

1. Extract the **entire** ZIP into an ordinary folder.
2. Open `MiniDraconia/MiniDraconia.exe`. Keep `_internal` beside the executable; it is required.
3. Use the companion's context menu for Settings or Quit.

Initial support target: **Windows 11 x64**. Other Windows versions, macOS and Linux are not validated targets for this candidate. No administrator access should be required to run the app. An unsigned build may trigger a Windows reputation warning; do not disable your antivirus to run it. Check the release checksum and provenance before deciding whether to trust a download.

Read the release notes and compare the download's SHA256 before opening it. The public Windows build comes from the source snapshot attached to the same prerelease, including verified Python/OpenSSL notices; community-facing documentation in this repository may be newer. See [the release checklist](docs/RELEASE-CHECKLIST.md) for verified checks and remaining limitations. Public availability does not mean all rights questions or human acceptance checks have been resolved.

## Develop and build

See [DEVELOPMENT.md](docs/DEVELOPMENT.md) for the tested Python version, setup, test runner and Windows build commands. Runtime code is under `full-engine/`; tests and packaging tools are in the repository root. Install/build evidence must come from a real Windows environment, not from merely reading a dependency file.

The build checks both the normal startup path and the separate scripted selftest. This matters: an early test ZIP passed its selftest but omitted its normal startup module. That packaging defect must not recur in community releases.

## Help improve it

Good first areas: Windows startup and scaling, native falling/drag behavior, animation transitions, accessibility, English dialogue polish (offline lines live in `full-engine/data/draconia_lines_en.json`), tests and dependency/build reproducibility. See the [roadmap](docs/ROADMAP.md) and [contribution guide](CONTRIBUTING.md). Please discuss large changes before implementing them.

## Character, credits and rights

Draconia is an **adult, fan-created reinterpretation inspired by Draco Malfoy**, not an official character or an affiliated product. The project does not claim ownership of the underlying franchise or its trademarks. A fan-project disclaimer is not a substitute for checking redistribution rights.

The inherited engine code retains its GPL-3.0 license and attribution to Chaozhong Liu/DyberPet. See [LICENSE](LICENSE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Code, character documents, images, fonts and generated audio require separate provenance checks; the code license does not license third-party characters, brands or provider services. See [rights review](docs/RIGHTS-REVIEW.md).
