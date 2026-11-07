# MiniDraconia 1.0.0-rc.2

**Second community preview — experimental, not a stable release. / Segunda versión comunitaria — experimental, no estable.**

A Windows desktop companion built on DyberPet. In this preview she comes alive: crisp at your screen's scaling, she really walks across the screen and looks where she goes, follows the cursor, flies up the screen edges on her broom, sits, reads and sips her tea, and visibly talks while a line is on screen. Three new animations of her own: **mirror** (a smug look in her hand mirror), **quill** (a quick note in her notebook, her wand as a pen) and **yawn** (she now yawns before she dozes off). She also has her own app icon.

She talks in English in one of three modes, and nothing is preset — the download points at no AI provider:

- **Offline lines** (the default): nothing is sent anywhere.
- **Your own AI** (optional): in Settings → AI / Privacy, fill in the base URL and model of any OpenAI-compatible endpoint — a hosted service you choose, with your API key, or a server on your own computer (for example Ollama or LM Studio), which needs no key. Your key is stored encrypted with Windows DPAPI, never sent over plain `http://` to another computer, and a daily request limit protects your money. See `docs/CONNECT-YOUR-AI.md`.
- **Self-hosted relay (advanced)**: if you run your own relay, a `minidraconia_relay.json` beside the executable connects her typed chat to it, with voice. The public download has none. The protocol is in `docs/SELF-HOSTED-RELAY.md`.

Touches, greetings, chatter and other desktop events always use her stored lines and never send anything, in every mode. If a connection fails she answers offline. Anyone can record an optional **voice pack** for her stored lines (`docs/VOICE-PACK.md`); none is included. See the README section “Talking to Draconia” and `docs/PRIVACY.md` for exactly what is sent and to whom.

En español: tres animaciones nuevas (espejo, libreta y bostezo), su propio icono y tres modos de conversación: frases sin conexión (predeterminado), tu propia IA (cualquier servicio compatible con OpenAI o un servidor en tu equipo, sin proveedor preconfigurado) y un relay propio (avanzado). Los toques y demás eventos nunca envían nada. Cualquiera puede grabar un paquete de voz opcional para sus frases.

## Let's improve her together / Mejoremos MiniDraconia juntos

This is my first public software project. Ideas, bug reports, translations, animation/dialogue improvements, tests and focused pull requests are welcome. You do not need to be an expert to contribute. Start with the [README](README.md) and [contribution guide](CONTRIBUTING.md), or [open an issue](https://github.com/adrianrivas44/MiniDraconia/issues).

Es mi primera publicación de software y quiero aprender con la comunidad. Si tienes una idea, una corrección o una mejora, compártela. Puedes probarla, proponer animaciones o diálogos, traducir, mejorar el código o explicar un problema. Empieza por el [README en español](README.es.md), crea un fork o [abre una issue](https://github.com/adrianrivas44/MiniDraconia/issues). Gracias por ayudar a que crezca.

— Zero / adrianrivas44

## Download and verification

- Download the Windows x64 ZIP, extract the entire folder, and run `MiniDraconia/MiniDraconia.exe`. Keep `_internal` beside it. Do not disable your antivirus for an unsigned build.
- 1.0.0-rc.1 passed 204 Windows tests with one platform-specific skip. For 1.0.0-rc.2, the results of the Windows test run, the frozen startup smoke and selftest of the exact ZIP, and the encrypted-key (DPAPI) check on Windows belong in the GitHub Release notes; a check not reported there has not been run. These are automated/offscreen checks, not human visual/audio acceptance or a fresh Windows installation.
- The build-source snapshot is supplied to identify exactly what produced the executable; the repository's community documentation may be newer. Internal execution receipts are retained privately, not shipped as operational logs.
- Compare both public downloads against the `SHA256SUMS.txt` attached to the same GitHub prerelease. Earlier private candidate hashes do not identify this public ZIP.
- The Windows test workflow is supplied as an inactive template, not claimed as green GitHub CI. See [development](docs/DEVELOPMENT.md) for activation instructions and the account-permission limitation.

## Intended correction

The early scripted test package omitted its normal startup module while its selftest passed. This candidate explicitly includes that module and requires real normal-startup evidence in addition to the scripted selftest. Check the build receipt for actual results; the presence of this note does not establish a successful build.

## Not included

No local language model, inference runtime, account, API key, relay configuration or voice pack. Your own AI is optional and off until you fill in an endpoint; a hosted service may charge your account for requests. The character soul is bundled as her prompt for the own-key mode; it does not install a model or enable memory, a microphone, a camera or tools. Unapproved voice playback must remain disabled, and pending audio should not be distributed in the public candidate.

## Known limitations and provenance

Review the privacy/asset notices, remaining human animation/audio checks and rights questions before relying on or redistributing the materials. See `docs/RELEASE-CHECKLIST.md`, `docs/KNOWN-ISSUES.md` and `docs/RIGHTS-REVIEW.md`. The original identity manual describes an earlier private-use context and is preserved unchanged; the maintainer explicitly requested sharing it with this public project. That request does not grant rights belonging to third parties. The engine's GPL license and upstream attribution are preserved; it is not a blanket license for all character, voice, font or reference-derived material.

The raw archive scanner flagged one Qt DLL over 100 MiB. Its size/hash were verified against the installed wheel RECORD. It is included inside a Release ZIP, not as an oversized Git blob. The original finding is not erased; this specific packaging exception does not establish complete Qt/Chromium license compliance.

No compatibility, legal-clearance, clean-machine-install, human visual/audio acceptance or security certification is implied by public availability or the version number.
