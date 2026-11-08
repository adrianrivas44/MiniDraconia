# Development and Windows packaging

Initial build target: Windows 11 x64 and Python 3.11. The inherited working toolchain used Python 3.11.15, PySide6 6.5.3 and PyInstaller 6.16.0. The dependency files and resulting build manifest are the authority for the candidate; a fresh install must be tested separately from reuse of a developer environment.

The public build's runtime notice references cover **Python 3.11.15 and OpenSSL 3.5.7**. The builder verifies the actual interpreter/OpenSSL versions and all reference hashes before copying those notices. A different runtime requires updating the references and their provenance; do not bypass that check or silently reuse another version's notices.

## Continuous-integration template

The Windows test workflow is preserved at `.github/workflow-templates/windows-tests.yml`, but is **not active CI**. The credential available for this first publication could push source but could not install GitHub Actions workflows. No broader account permission was requested. A maintainer can activate it by copying the template to `.github/workflows/tests.yml` using an appropriately authorized GitHub session. Until that is done and a real run passes, local Windows verification is not a GitHub CI result.

## Install in a project-local environment (PowerShell)

From the extracted/cloned repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\run_tests.py
```

These commands are for a separate MiniDraconia environment, not for an existing agent/runtime environment. No model weights, Ollama, Kokoro or ONNX inference stack is required for scripted mode. The present manifests are pinned/bounded from a known toolchain, not a claim that every new machine has reproduced the installation.

## Run from source

```powershell
.\.venv\Scripts\python.exe full-engine\packaging\portable_entry.py
```

Run through `portable_entry.py`, which initializes the per-user profile. Do not start the engine module directly and then work around missing profile setup by writing state into the source folder.

## Tests and source hygiene

```powershell
.\.venv\Scripts\python.exe scripts\run_tests.py
.\.venv\Scripts\python.exe scripts\scan_release.py
```

The test runner creates a fresh isolated profile and sets offscreen/mute before Qt imports. A skipped Qt test is not a successful Windows/UI test; read the final counts and exceptions. The scanner reports paths/types/counts, not secret values. Its legal-review list does not certify rights.

## Live test against your own local server (opt-in)

The normal tests never contact the network: every request goes to a fake transport. `tests/test_live_endpoints.py` is the one exception, and it is skipped unless you set both variables to an OpenAI-compatible server **on your own computer** (Ollama, LM Studio or similar, with the model already pulled):

```powershell
$env:MINIDRACONIA_LIVE_LOCAL_URL = "http://127.0.0.1:11434/v1"   # or http://localhost:11434/v1
$env:MINIDRACONIA_LIVE_LOCAL_MODEL = "qwen2.5:7b-instruct"        # the name your server lists
.\.venv\Scripts\python.exe scripts\run_tests.py --pattern test_live_endpoints.py
```

With them set, it runs the real client and the real Settings view (offscreen Qt) in the runner's isolated profile, with **no API key**: *Test connection* must show `Connection OK.`, saving must make the mode "your own AI", the warm-up must reach the server without changing the daily count, and one typed chat through the conversation brain must come back from your server (`own_key`) with a known emotion, a bubble text with no `assistant` prefix or bracket junk, and a daily count increased by exactly 1. The test refuses any address that is not on your own computer, and it never reads a key from the environment: do not put one there. The first request may take a while if the server still has to load the model. A skip means it did not run; it is not a pass.

## Build the Windows ZIP

```powershell
.\.venv\Scripts\python.exe package_scripted.py --preflight-only
.\.venv\Scripts\python.exe package_scripted.py --build-id my-unique-build
```

Choose a new build id for each attempt. The builder refuses to overwrite an existing build. It needs the repository's README, LICENSE and RELEASE-NOTES. Do not use `--allow-missing-docs` for a complete public release: that flag deliberately marks a package incomplete.

A coordinator with an existing, separately reviewed PyInstaller folder can supply `--buildtools <absolute-folder>`. That is optional; no private machine path is required by the public build. Never add your private environment or buildtools directory to Git.

The builder writes the candidate ZIP, checksum and build receipt under `dist/`, plus detailed evidence under `work/<build-id>/`. It checks QtQml resource provenance against installed wheel RECORD data, package paths/symlinks, CRC and complete extracted-file hashes. It executes **both** modes of the exact extracted executable:

- `--startup-smoke --report <absolute-new-file>`: the normal app construction and real event loop, with an isolated profile and automated exit.
- `--selftest-scripted --report <absolute-new-file>`: separate scripted interaction audit.

Reports and profiles must be fresh, absolute and outside the installation; the smoke report is also outside its profile. The builder supplies these paths automatically. Runtime checks use a path with spaces and do not inherit the developer's PYTHONPATH.

## Sprites, walking and talking modes

- `scripts/measure_sprite_motion.py` measures how far her planted foot travels per frame (`frame_move` in `full-engine/res/role/Draconia/act_conf.json`, the loop mean) and where each step ends (`step_ends`). Re-run it after changing the walk sprites: `QT_QPA_PLATFORM=offscreen python scripts/measure_sprite_motion.py`.
- Her idle pool and weights are `idle_poses` in `full-engine/res/role/Draconia/pet_conf.json`.
- Conversation modes live in `full-engine/DyberPet/brain_client.py` (offline / own AI / self-hosted relay) and `pet_conversation.py`; tests use fake transports and never contact the network (except the opt-in live test above). No endpoint or model is preset ([connect your own AI](CONNECT-YOUR-AI.md)).
- A self-hosted relay (advanced) is connected by placing `minidraconia_relay.json` (`{"base_url", "token"}`) beside your own built executable **after** `package_scripted.py` has produced and verified the public ZIP; the protocol is in [SELF-HOSTED-RELAY.md](SELF-HOSTED-RELAY.md). The same goes for an optional `voice_pack/` ([VOICE-PACK.md](VOICE-PACK.md)). Never put either in the repository, in `full-engine/` or in a public ZIP: `.gitignore`, the asset policy, the builder and `scripts/scan_release.py` reject them.
- `scripts/scan_release.py` flags only generic private paths. To also block your own machine names, folders or account names, list them (one literal per line) in an untracked `.release-private-markers` file at the repository root (git-ignored) or pass `--private-markers FILE`; a hit is a blocking finding and the marker itself is never printed.

## Layout

- `full-engine/run_DyberPet.py`: inherited application and real normal startup.
- `full-engine/packaging/`: portable entry and PyInstaller specification.
- `full-engine/DyberPet/`: behavior, UI, profile paths and startup evidence probe.
- `full-engine/data/` and `full-engine/res/`: required default data/resources, not user state.
- `tests/`: behavior and packaging regression tests.
- `docs/identity/`: product soul and visual reference, not an active assistant profile.

Preserve upstream attribution and the corresponding source of every binary release. Do not claim byte-for-byte reproducible EXEs without a reproducibility experiment; versioned inputs and hashes establish provenance, not deterministic compiler output. Final licensing, human visual/audio and publication checks remain in the release checklist.
