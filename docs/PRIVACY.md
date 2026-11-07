# Privacy and local data

## Conversation modes

**Pet events never leave your device, in every mode.** Greetings, pats, pinches, pokes, being dragged or dropped, idle and spontaneous chatter, and goodbyes are always answered from her stored English lines on your computer. No event, and no description of one, is sent to a relay or to your own AI, and none of them spends requests or money. Only a message you type in *Talk to Draconia* can go to the configured brain.

**Offline (the default).** Draconia answers from local, predefined English lines. No conversation data is sent anywhere and no network request is made for her lines.

**Your own AI (optional, you turn it on).** In *Settings → AI / Privacy → Connect your own AI* you enter a base URL and a model (nothing is preset: both start empty) and, unless the endpoint is a server on your own computer (`localhost`, `127.0.0.1`, `::1`), your API key. A key is never sent over plain `http://` to another computer. From then on, and only to that base URL:

- your typed messages and the recent typed conversation (up to the last 16 messages, kept in memory only and cleared with *Clear current chat history* or when the app quits),
- her character prompt (the bundled `docs/identity/SOUL.en.md` plus a short desktop addendum)

are sent over HTTPS (or plain `http://` to a server on your own computer) to that endpoint, only when you send a typed message. Nothing else: no files, screenshots, keystrokes, clipboard, other conversations, your Windows user name or your mood/state files. The service you choose may store or process what it receives under its own terms, and a hosted service may charge your account. A server on your own computer keeps it on your computer. The exact request is shown in [connect your own AI](CONNECT-YOUR-AI.md). A local daily request limit (200 by default, editable) protects you from runaway costs; past it she answers offline until the next day and says so once.

**Your key** is encrypted with Windows DPAPI for your Windows user and stored in the profile as `own_key.dpapi`. It is never written in plain text: not in settings, logs, crash reports or diagnostics, and it is never shown again in the app. *Forget key* deletes it and switches back to offline. *Test connection* sends one tiny request and shows only “OK” or the HTTP error.

**Self-hosted relay (advanced).** Someone who runs their own relay service can connect a copy to it by placing a `minidraconia_relay.json` file (`{"base_url", "token"}`) beside the executable, or in the profile; it is copied into the profile on first run. The public download never contains one. In that mode typed messages and the recent typed conversation go to that relay, with the token, and the relay also returns the voice of her typed-chat replies. Pet events never go to the relay. What the relay does with them is up to whoever runs it. See [self-hosted relay](SELF-HOSTED-RELAY.md).

**Voice pack (optional).** Anyone can record a `voice_pack/` folder for her stored lines and place it beside the executable ([format](VOICE-PACK.md)). It is played locally from that folder; nothing is sent. The public download never contains one. The *Voice* switch in her menu, and *Mute* (volume zero) in Settings, silence it.

## Local data

On Windows, the launcher uses `%LOCALAPPDATA%/MiniDraconia-Scripted/`, with product data beneath its `MiniDraconia/` subfolder. This can contain settings, the AI preference file `ai.json` (mode, base URL, model, daily limit; never the key), the encrypted key file, today's request count (`own_key_usage.json`), scripted state and other app data. The inherited desktop code also keeps a local event/mood log, `data/mia_talk.log`: it records which mode and kind of line was used, walks, the screen size and one timestamped line per behaviour decision (for example `director act tea`, `director nap 73`, `director wake`), never your messages, her replies' text, the key or the relay token. Past 2 MB it is moved to `mia_talk.log.1` (one older copy is kept). Do not read “offline” as “nothing is recorded.” A failed startup can leave `startup-diagnostic.txt` in the launcher profile. A migration can preserve an older configuration in `ai.s1-backup.json`. Source/developer test profiles are separate and must be explicitly isolated.

The desktop code observes pointer position/events and can check time since the last input to drive idle behavior. That does not by itself record the contents of keystrokes, capture the screen or activate a microphone/camera. The full inherited source contains legacy modules and external help/upstream links; the precise runtime network boundary is part of release testing, not a blanket claim about every source file. Clicking an external link can open a browser and contact its destination. No telemetry is included.

## Sharing diagnostics

Review a diagnostic before posting it. Tracebacks can reveal your Windows username, installation path or local filenames. Share only a sanitized excerpt needed to reproduce the problem. Never upload the entire AppData folder, auth files, API keys, browser data or private conversations.

## Resetting data

Quit the app first and **back up your data** before moving or resetting its profile. Uninstalling the extracted executable does not necessarily remove per-user data. The project does not silently erase user state as a troubleshooting step.

## Changing what is sent

Any new connector or data must state exactly what is sent, to whom, when it is sent, how keys are stored, whether charges can apply and how to disable it, and must be documented here before it ships. Adding to the character soul alone does not authorize network calls or grant access to an account.
