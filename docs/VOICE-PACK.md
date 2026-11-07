# Voice pack (optional)

Draconia's stored lines (`full-engine/data/draconia_lines_en.json`: greetings, pats, pinches, drags, falls, idle remarks, chatter, offline chat replies and goodbyes) are shown as text. A **voice pack** lets anyone give some of those lines a recorded voice: your own recordings, a friend's, or a voice you have the right to use. It is optional, and the project does not ship one.

## Where it goes

- Windows build: a folder `voice_pack/` beside `MiniDraconia.exe`.
- Source run: `full-engine/voice_pack/` (git-ignored).

The folder holds `manifest.json` and the WAV files it lists, side by side (no subfolders).

## manifest.json

```json
{
  "voice_id": "my-recordings-2026",
  "lines": [
    {
      "key": "greet",
      "text": "There you are. The day can begin properly now.",
      "emotion": "proud",
      "file": "greet-01.wav",
      "seconds": 2.4,
      "sha256": "<sha256 of greet-01.wav, 64 hex characters>"
    },
    {
      "key": "pat",
      "text": "One pat. I counted.",
      "emotion": "happy",
      "file": "pat-01.wav",
      "seconds": 1.6,
      "sha256": "<sha256 of pat-01.wav, 64 hex characters>"
    }
  ]
}
```

- `voice_id`: any name for your pack (informational).
- `key`: the event key of the line in `draconia_lines_en.json` (`greet`, `pat`, `pinch`, `touch_body`, `drag`, `fall`, `idle`, `chatter`, `chat`, `bye`).
- `text`: the line exactly as it is in `draconia_lines_en.json`. If the line is later edited, its recording is no longer used.
- `emotion`: her pose while she says it, one of `neutral`, `happy`, `angry`, `bored`, `flustered`, `shy`, `thinking`, `proud`, `sarcastic`, `greet`, `bye`.
- `file`: a plain `.wav` file name inside the pack folder (no folders, no `..`).
- `seconds`: the recording's length (informational; playback timing is read from the WAV itself).
- `sha256`: the SHA-256 of the WAV file. Compute it with `certutil -hashfile greet-01.wav SHA256` on Windows or `sha256sum greet-01.wav` elsewhere.

A line is voiced only when the manifest has its key and exact text, the file exists in the pack folder and its sha256 matches. Anything else (no pack, a broken manifest, a missing or altered file, a line not in the pack) leaves the line as text, and never stops the app. Use 16-bit PCM WAV files.

## How it plays

A voiced line plays through the same path as any voice: bubble, mouth and talking time follow the WAV's length, and its `emotion` picks her pose. The *Voice* switch in her menu turns pack audio off and on, and *Mute* (volume zero) in Settings silences it. A pack plays locally and sends nothing anywhere. It works in every conversation mode, because stored lines are used in every mode.

The single prerecorded clip that ships with the app (`res/role/Draconia/note/voice/head-01.wav`, approved individually with `approved: true` in its own manifest) is separate from voice packs and keeps working as before.

## Never in the public build

A voice pack never ships in the public ZIP or in the repository: `voice_pack/` is git-ignored, and the shared asset policy, the builder (`package_scripted.py`) and `scripts/scan_release.py` refuse any `voice_pack` folder. Put yours beside your own copy of the executable. Check that you have the right to use and share any voice you record or generate.
