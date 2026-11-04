# Privacy and local data

## Current scripted mode

The character uses local, predefined lines; no cloud model integration or local language-model inference is implemented. The normal launch initializes a per-user folder rather than writing preferences into the installation.

On Windows, the current launcher uses `%LOCALAPPDATA%/MiniDraconia-Scripted/`, with product data beneath its `MiniDraconia/` subfolder. This can contain settings, scripted state and other app data. The inherited desktop code also keeps a local event/mood log, `data/mia_talk.log`; do not read “offline” as “nothing is recorded.” A failed startup can leave `startup-diagnostic.txt` in the launcher profile. A migration can preserve an older configuration in `ai.s1-backup.json`, including fields this release does not use. Source/developer test profiles are separate and must be explicitly isolated.

The desktop code observes pointer position/events and can check time since the last input to drive idle behavior. That does not by itself record the contents of keystrokes, capture the screen or activate a microphone/camera. The full inherited source contains legacy modules and external help/upstream links; the precise runtime network boundary is part of release testing, not a blanket claim about every source file. Clicking an external link can open a browser and contact its destination. No telemetry or external-provider behavior should be added without a documented review.

## Sharing diagnostics

Review a diagnostic before posting it. Tracebacks can reveal your Windows username, installation path or local filenames. Share only a sanitized excerpt needed to reproduce the problem. Never upload the entire AppData folder, auth files, API keys, browser data or private conversations.

## Resetting data

Quit the app first and **back up your data** before moving or resetting its profile. Uninstalling the extracted executable does not necessarily remove per-user data. The project does not silently erase user state as a troubleshooting step.

## Future model connectors

Any future connector must state exactly what is sent, to whom, when it is sent, how credentials are stored, whether charges can apply and how to disable it. Adding a character soul alone does not authorize network calls or grant access to an account.
