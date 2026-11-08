# Changelog

## 1.0.0-rc.3 — third community prerelease

What a real test with a local server on Windows exposed in rc.2 (Ollama, no key; see `docs/RECOMMENDED-SETUP.md`), now fixed in the app.

### A server on your own computer is fast
- A base URL whose host is exactly `localhost` now connects to `127.0.0.1`, keeping the scheme, port and path. On Windows `localhost` tried IPv6 `::1` first and a server listening on IPv4 only answered about 2 s late on every reply. If the IPv4 connection is refused, she tries `[::1]` once, so a server that listens on IPv6 only still works. What you typed is what stays saved.
- The Settings hint and the plain-language messages show `http://127.0.0.1:11434/v1`.

### Cold start of a local model
- A server on your own computer (`localhost`, `127.0.0.1`, `::1`) now gets up to 90 s per request, for typed chat and for *Test connection*: the first request after the server starts has to load the model. Hosted endpoints keep 20 s.
- Warm-up: when your own AI is on your own computer, the app sends one tiny request (the same one as *Test connection*) at start and when you save the settings, in the background. It never counts toward the daily limit, is never sent to another computer, is skipped when the daily limit is 0, and a failure is only written to the local log.
- *Test connection* runs in the background, so Settings never freezes while a model loads.
- While a typed message waits on a server on your own computer for more than about 3 s, she keeps her thinking pose until the reply arrives.

### Clean replies from weaker models
- A role prefix before or after the emotion tag (`assistant`, `assistant:`, `assistant>`, `Draconia:`, any case) never reaches the bubble.
- A broken leading tag such as `[]bored]` or `[ bored ]` still sets her pose when the word inside is one of her emotions; otherwise she is neutral. The bracket junk never reaches the bubble.

### Tests and docs
- `tests/test_live_endpoints.py`: an opt-in live test against your own local server (Test connection, the mode, the warm-up, one typed chat, the daily count), skipped unless `MINIDRACONIA_LIVE_LOCAL_URL` and `MINIDRACONIA_LIVE_LOCAL_MODEL` are set; no key is used. See `docs/DEVELOPMENT.md`.
- The version tests follow `VERSION` instead of repeating a literal.
- `docs/KNOWN-ISSUES.md` drops the `localhost` and cold-start items; `docs/CONNECT-YOUR-AI.md` and `docs/RECOMMENDED-SETUP.md` say what changed and keep the rc.2 measurements, labelled as such. No new dependencies.
- Internal module and log names no longer carry an earlier project's character name (`talk.log` replaces the old log file name).

## 1.0.0-rc.2 — second community prerelease (published 2026-11-07)

### She is alive
- Crisp frames at the screen's scaling: each frame is built at the exact physical size for the display (never upscaled), decoded per clip on demand with background prefetch, a few clips kept warm and a memory budget.
- Real walking: the window moves as far as her feet each frame (her walk measured from the sprites with `scripts/measure_sprite_motion.py`: 5.16 sprite px per frame over the loop), scaled with her size, without losing fractions. Walks finish their step, never push into a wall (after 4 blocked frames the walk ends; a walk toward the wall she touches turns around), and follow-the-cursor walks to the real cursor.
- Climbing on her broom along the screen edges is on by default (menu toggle kept): one seamless loop with no other frame while she climbs, a shorter hold at the top, and the descent plays the ride backwards from the frame she holds.
- Variety: her idle pool lives in her role (tea, read, sit, think, stretch, hairflip, spell, slowclap, bored, happy, shy, peek, doze) and never repeats one of the last three; steady frame pacing at her clips' 12 fps; `sit` holds its pose instead of flickering between two frames.
- Talking: she visibly talks for every line in one smooth loop; an emotion clip plays complete (capped by the line), a line never cuts a clip mid-way (2.5 s rule), talk stops when the line or voice ends, and voice, bubble and mouth start together (mouth pauses of at least 0.8 s, with hysteresis).
- English diagnostics in the local log: `screen …` at start and `walk end …` per walk.

### She can talk
- Three conversation modes, chosen in this order: self-hosted relay (advanced) > your own AI > offline lines. Any failure falls back to an offline line.
- Offline (default): `data/draconia_lines_en.json`, one pool per event, never repeating the last lines; no network attempt.
- Settings → AI / Privacy → **Connect your own AI**: OpenAI-compatible base URL, API key (masked, encrypted with Windows DPAPI, *Forget key*), model, *Test connection*, daily request limit (default 200). The active mode is shown in plain words. Text only; approved prerecorded event audio still plays. (D2.4: no endpoint or model is preset; see below.)
- “Talk to Draconia” is back in her menu.

### Events never spend; stored voice; no early naps (D2.1)
- Pet events (greet, pat, pinch, poke, drag, fall, idle, spontaneous chatter, goodbye) always answer from her stored lines in `data/draconia_lines_en.json`, in every mode: they never send a request to a relay or to your own AI, and never spend requests, money or voice quota. Only a typed message goes to the configured brain; if it fails, a stored `chat` line answers. The per-event rate limit, the chatter cadence and the away-sleep rules are unchanged. A stored line never repeats any of the last min(3, n-1) lines of its event.
- Optional voice pack that anyone can record (never in the repository or the public ZIP; format in `docs/VOICE-PACK.md`): `voice_pack/manifest.json` beside the executable (or `full-engine/voice_pack/` from source) gives stored lines her recorded voice when the key, the exact text and the file's sha256 match. It plays through the same playback and sync as relay voice (bubble, mouth and talk timing from the WAV), its emotion picks her pose, and the *Voice* switch and Settings' *Mute* silence it. Without a pack, or for a line it lacks, she is unvoiced as before; the approved v1 clip keeps playing as before (own-key and offline modes).
- No early naps: no random nap in the first 10 minutes or within 3 minutes of a touch, a typed message or a line. Her `sleep` weight is now 0.015 and, whatever the tick range, random naps average at most one per 10 minutes of awake time (her 5–8 s ticks: 6.5 s mean × 1.6 % per roll would be ~6.6 min, capped to 10 min). Away sleep is unchanged.
- The local log gets one timestamped line per behaviour decision (`director act <pose>`, `walk <dir>`, `follow`, `nap <seconds>`, `away sleep`, `wake`), at most 20 per minute, and the log rolls over at 2 MB.
- App icon (provisional) for the executable, her window, the tray and Settings (`res/icons/app.png` / `app.ico`), and Windows version info (MiniDraconia, “MiniDraconia desktop companion”, the version from `VERSION`).

### Three new animations; her icon (D2.2)
- Three new clips of her own, each 73 frames at 12 fps (about 6 s), starting on and fading back to her standing pose: **mirror** (she takes out a hand mirror, tucks her hair, smug smile), **quill** (she writes in a small notebook with her wand as a pen, then taps her chin) and **yawn** (she covers a yawn and rubs an eye). They play through the same frame store and pacing as every clip, decoded on demand (not kept pinned); her worst-case frame cache is unchanged at about 436 MB, under the 450 MB budget.
- Idle variety: mirror and quill join her idle pool (weight 1.5 each; tea stays her favourite at 3) and follow the no-repeat rule. Mirror is likelier when she is happy or excited and rarer when sleepy; quill is likelier when she is content and rarer when excited. A profile made before this version gets these mood entries too; its own entries are kept.
- Falling asleep is now yawn → doze → sleep: for a random nap or away sleep she first yawns once, complete, then dozes off as before (her short random doze opens with the yawn as well). No yawn if she falls asleep while dragged or falling; touching her during the yawn wakes her as before.
- A line arriving during one of these clips never cuts it: the clip finishes if 2.5 s or less remain, otherwise the line takes over at the 2.5 s limit.
- App icon: the owner chose the square portrait; it replaces the provisional medallion in `res/icons/app.png` / `app.ico` (executable, her window, the tray and Settings).

### Random walks look where they go (D2.3)
- A random walk (the director's, and the engine's random animation's) picks its direction from where her window really is on her current screen. She does not walk toward a side with less room than one full walk; one full walk is her walk clip's frames × her measured step × her current size (about 330 px at 100 %). With room on both sides it is still a coin flip. If neither side holds a full walk (at 100 % her window is 515 px wide, so a 1024 px screen leaves 509 px), she walks toward the side with more room, as long as it holds at least half a walk. On a screen too small even for that she does not walk, and that moment becomes one of her idle clips. Before, at a screen edge the coin flip kept choosing the wall, and each of those walks stopped after one frame, so she seemed to start walking and do nothing.
- The local log shows the chosen direction (`director walk left` / `right`), or `director walk none (no room)`.
- Walks requested by name are unchanged: an edge turn, following the cursor and drags keep the wall guard (a walk toward the wall she touches turns around; 4 blocked frames end a walk).

### Open for your own setup (D2.4)
- No preset provider: *Connect your own AI* starts with an empty base URL and model (placeholders `https://your-endpoint.example/v1` and `provider/model-name`). *Test connection* and *Save* refuse an empty base URL or model in plain words, and she stays offline until they are filled in. Values you already saved are kept.
- A server on your own computer (`localhost`, `127.0.0.1`, `::1`), such as Ollama or LM Studio, works without an API key. Any other address needs a key, and a key is never sent over plain `http://` to another computer.
- The relay mode is now documented for anyone as a **self-hosted relay (advanced)**: `docs/SELF-HOSTED-RELAY.md` gives the exact protocol (health, chat, voice), the Bearer token and the `minidraconia_relay.json` file. New guides: `docs/CONNECT-YOUR-AI.md` (English, with a Spanish summary) and `docs/VOICE-PACK.md` (the manifest format).
- `scripts/scan_release.py` knows only generic private paths; a maintainer can add their own markers in an untracked, git-ignored `.release-private-markers` file or with `--private-markers FILE` (a hit blocks; the marker is never printed).

### Packaging
- The public ZIP never contains a relay seed, a key file or a voice pack; the shared asset policy, the builder and the release scanner refuse them, and a build input of another product fails the build.
- The character soul (`docs/identity/SOUL.en.md`) is bundled for the own-key mode. No new dependencies.

## 1.0.0-rc.1 — first community prerelease (published 2026-11-04)

### Preserved baseline
- Windows desktop companion, animated reactions and predefined English offline lines.
- Local per-user preferences/state, Settings and Quit.
- Per-clip approval gate for prerecorded voice playback.

### Scope
- Corrected the missing normal startup module in the frozen package.
- Normal startup checked separately from the scripted selftest.
- Source dependencies, test/build instructions, contribution templates and identity documentation.
- Inventory of third-party licenses, assets and privacy; open rights items stay listed in `docs/RELEASE-CHECKLIST.md`.

This is a scope record, not proof every acceptance gate has passed. See the release checklist for actual gate status. No local language model, AI provider integration or general AI conversation was included in rc.1.
