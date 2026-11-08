# MiniDraconia 1.0.0-rc.3

**Third community preview — experimental, not a stable release. / Tercera versión comunitaria — experimental, no estable.**

A Windows desktop companion built on DyberPet. She is crisp at your screen's scaling, really walks across the screen and looks where she goes, follows the cursor, flies up the screen edges on her broom, sits, reads and sips her tea, and visibly talks while a line is on screen. Her own animations (**mirror**, **quill** and **yawn**) and her app icon came in rc.2.

She talks in English in one of three modes, and nothing is preset — the download points at no AI provider:

- **Offline lines** (the default): nothing is sent anywhere.
- **Your own AI** (optional): in Settings → AI / Privacy, fill in the base URL and model of any OpenAI-compatible endpoint — a hosted service you choose, with your API key, or a server on your own computer (for example Ollama or LM Studio), which needs no key. Your key is stored encrypted with Windows DPAPI, never sent over plain `http://` to another computer, and a daily request limit protects your money. See `docs/CONNECT-YOUR-AI.md`.
- **Self-hosted relay (advanced)**: if you run your own relay, a `minidraconia_relay.json` beside the executable connects her typed chat to it, with voice. The public download has none. The protocol is in `docs/SELF-HOSTED-RELAY.md`.

Touches, greetings, chatter and other desktop events always use her stored lines and never send anything, in every mode. If a connection fails she answers offline. Anyone can record an optional **voice pack** for her stored lines (`docs/VOICE-PACK.md`); none is included.

## What changed since rc.2

A real test with a local model server on Windows showed three rough edges in rc.2. They are fixed in the app now, not only in the docs:

- **`localhost` is as fast as `127.0.0.1`.** On Windows, `localhost` tried IPv6 first and every reply from a server listening on IPv4 waited about 2 seconds more. The app now connects to `127.0.0.1` for you (and tries `[::1]` once if nothing answers there). Settings keeps what you typed and shows `http://127.0.0.1:11434/v1` as the example.
- **A local model has time to wake up.** A server on your own computer gets up to 90 seconds per request (hosted services keep 20), the app warms the model up with one tiny background request when it starts and when you save your settings (it never counts toward your daily limit), *Test connection* no longer freezes Settings, and she keeps her thinking pose while a slow reply is on its way.
- **Cleaner replies from smaller models.** Stray `assistant>` or `Draconia:` prefixes and broken tags such as `[]bored]` no longer reach her bubble.
- An opt-in live test for your own local server (`tests/test_live_endpoints.py`, see `docs/DEVELOPMENT.md`). No new dependencies.
- Internal module and log names are now neutral: the local log is `data/talk.log` (see `docs/PRIVACY.md`).

En español: `localhost` ya es tan rápido como `127.0.0.1` (la app se conecta a `127.0.0.1` por ti y, si nada responde, prueba `[::1]` una vez); un servidor en tu equipo tiene hasta 90 segundos por petición, la app calienta el modelo con una petición mínima en segundo plano al arrancar y al guardar (nunca cuenta para tu límite diario), *Test connection* ya no congela Settings y ella se queda pensando mientras llega una respuesta lenta. Los prefijos `assistant>` o `Draconia:` y las etiquetas rotas como `[]bored]` ya no aparecen en su globo. Los nombres internos de módulos y del registro ahora son neutros: el registro local es `data/talk.log`.

## Let's improve her together / Mejoremos MiniDraconia juntos

This is my first public software project. Ideas, bug reports, translations, animation/dialogue improvements, tests and focused pull requests are welcome. You do not need to be an expert to contribute. If you try her with your own local model, please share the model and how it went in an issue: it helps everyone. Start with the [README](README.md) and [contribution guide](CONTRIBUTING.md), or [open an issue](https://github.com/adrianrivas44/MiniDraconia/issues).

Es mi primera publicación de software y quiero aprender con la comunidad. Si tienes una idea, una corrección o una mejora, compártela. Puedes probarla, proponer animaciones o diálogos, traducir, mejorar el código o explicar un problema. Si la pruebas con tu propio modelo local, cuéntanos en una issue qué modelo usaste y cómo te fue. Empieza por el [README en español](README.es.md), crea un fork o [abre una issue](https://github.com/adrianrivas44/MiniDraconia/issues). Gracias por ayudar a que crezca.

— Zero / adrianrivas44

## Download and verification

- Download the Windows x64 ZIP, extract the entire folder, and run `MiniDraconia/MiniDraconia.exe`. Keep `_internal` beside it. Do not disable your antivirus for an unsigned build.
- Test results for this build (a check not reported here has not been run):
  - **Windows tests, exact tagged source:** 618 tests on Windows 11 Pro, 0 failures, 3 skips (two git-only checks that do not apply to a source export, and one off-Windows check). The run included the opt-in live test against a real Ollama server with no key.
  - **Frozen ZIP:** the startup smoke test and the scripted self-test passed from the exact extracted ZIP. The release scan of the tree and the ZIP is clean, apart from the reviewed Qt WebEngine DLL size exception.
  - **Encrypted key (DPAPI):** the real round trip passed on Windows.
  - **Real local server (Ollama on Windows, no key), with this build's own client:**
    - `localhost` and `127.0.0.1` were equally fast (median about 0.3 s).
    - The first message right after a server restart got a real reply in 6 to 8 s across three runs, instead of falling back.
    - `llama3.2:3b` replies reached the bubble with no `assistant` prefix or bracket junk.
  - **Real hosted endpoint:** the rc.2 client, whose hosted path is unchanged in rc.3, was checked against an OpenAI-compatible hosted service with a test key. *Test connection* worked, a wrong key showed only the HTTP status, six typed replies stayed in character, and the daily limit switched her to stored lines with its notice.
  - **Not run:** the frozen app's Settings screen driven by a person against a local server; LM Studio.
- These are automated/offscreen checks, not human visual/audio acceptance or a fresh Windows installation. Earlier results are recorded in `docs/RELEASE-CHECKLIST.md` and `docs/RECOMMENDED-SETUP.md`.
- The build-source snapshot is supplied to identify exactly what produced the executable; the repository's community documentation may be newer. Internal execution receipts are retained privately, not shipped as operational logs.
- Compare both public downloads against the `SHA256SUMS.txt` attached to the same GitHub prerelease. Earlier candidate hashes do not identify this public ZIP.
- The Windows test workflow is supplied as an inactive template, not claimed as green GitHub CI. See [development](docs/DEVELOPMENT.md) for activation instructions and the account-permission limitation.

## Not included

No local language model, inference runtime, account, API key, relay configuration or voice pack. Your own AI is optional and off until you fill in an endpoint; a hosted service may charge your account for requests. The character soul is bundled as her prompt for the own-key mode; it does not install a model or enable memory, a microphone, a camera or tools. Unapproved voice playback must remain disabled, and pending audio should not be distributed in the public candidate.

## Known limitations and provenance

Review the privacy/asset notices, remaining human animation/audio checks and rights questions before relying on or redistributing the materials. See `docs/RELEASE-CHECKLIST.md`, `docs/KNOWN-ISSUES.md` and `docs/RIGHTS-REVIEW.md`. The original identity manual describes an earlier private-use context and is preserved unchanged; the maintainer explicitly requested sharing it with this public project. That request does not grant rights belonging to third parties. The engine's GPL license and upstream attribution are preserved; it is not a blanket license for all character, voice, font or reference-derived material.

The raw archive scanner flagged one Qt DLL over 100 MiB. Its size/hash were verified against the installed wheel RECORD. It is included inside a Release ZIP, not as an oversized Git blob. The original finding is not erased; this specific packaging exception does not establish complete Qt/Chromium license compliance.

No compatibility, legal-clearance, clean-machine-install, human visual/audio acceptance or security certification is implied by public availability or the version number.
