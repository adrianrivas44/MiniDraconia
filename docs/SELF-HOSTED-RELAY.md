# Self-hosted relay (advanced)

A self-hosted relay is a small web service **you run yourself** that answers Draconia's typed chat and can give those replies a voice. It is an advanced option for people who want to put their own model, prompt or voice behind one address, for example on a home server. The app does not include a relay, does not know any relay address, and the public download never contains a relay configuration.

When a relay is configured it takes priority: self-hosted relay > your own AI ([connect your own AI](CONNECT-YOUR-AI.md)) > offline lines. Pet events (touches, greetings, chatter, drags, falls, goodbyes) never go to the relay in any mode; they always use her stored lines. If the relay fails, she answers from her stored lines.

## Configure the client

Create a file named `minidraconia_relay.json`:

```json
{"base_url": "http://192.168.1.50:8080", "token": "replace-with-a-long-random-token"}
```

- `base_url`: the relay's address, starting with `http://` or `https://`, without a trailing path (a trailing `/` is ignored). For example `http://192.168.1.50:8080` on your home network or `https://relay.example`.
- `token`: a secret shared between the app and your relay. No spaces, no `<` or `>`.

Place it in either location:

- **Beside the executable**, next to `MiniDraconia.exe` (for a source run: the repository root). On its next start the app copies it into your profile once; an existing profile copy is never overwritten.
- **Directly in your profile**: `%LOCALAPPDATA%\MiniDraconia-Scripted\MiniDraconia\data\minidraconia_relay.json` on Windows.

An invalid file (missing fields, a placeholder like `<token>`, spaces, another scheme) is ignored. To turn the relay off, delete the profile copy and the copy beside the executable. *Settings → AI / Privacy* shows "self-hosted relay (advanced)" while it is active. The token is never logged, printed or shown.

The token travels in the `Authorization` header. Over `https://` it is encrypted; over plain `http://` anyone on the network path can read it, so use plain `http://` only inside a network you trust.

## Protocol

Every request carries `Authorization: Bearer <token>`; requests with a body also send `Content-Type: application/json`. Any 2xx status is success. 401/403 is a rejected token, 429 a rate limit; a timeout, a network error or a 5xx answer is tried once more after half a second. Any failure means her stored line answers instead.

### GET /v1/health

Checked once when the pet starts, only to note the result in her local log; chat does not wait for it. Any 2xx answer is healthy; the body is ignored (keep it under 4 KB). Timeout: 5 seconds.

### POST /v1/chat

Sent only for a message the user typed in *Talk to Draconia*. Request:

```json
{
  "text": "How was your day?",
  "history": [
    {"role": "user", "content": "Hello."},
    {"role": "assistant", "content": "There you are."}
  ]
}
```

- `text`: the typed message, at most 500 characters.
- `history`: the recent typed conversation, at most the last 16 messages, oldest first; `role` is `user` or `assistant`, each `content` at most 500 characters. It may be empty.

Response (2xx, JSON, at most 64 KB):

```json
{"emotion": "proud", "text": "Productive. I judged three things and approved one."}
```

- `text`: her reply, required and not empty. A leading tag such as `[happy]` and voice cues such as `[sigh]` or `<soft>…</soft>` are removed from the bubble; it is cut at 300 characters. Short replies (one or two sentences) fit her bubble best.
- `emotion`: one of `neutral`, `happy`, `angry`, `bored`, `flustered`, `shy`, `thinking`, `proud`, `sarcastic`, `greet`, `bye`. It chooses her pose; anything else counts as `neutral`.

Timeout: 20 seconds.

### POST /v1/tts

Asked for the voice of a typed-chat reply, only while her *Voice* switch is on and the app is not muted. Request:

```json
{"text": "Productive. I judged three things and approved one."}
```

Response (2xx): the audio as a WAV file in the body (it must start with `RIFF` … `WAVE`), at most 16 MB. 16-bit PCM mono at 24 kHz is what the client is tested with. Her mouth and bubble follow the WAV's length. Timeout: 30 seconds. If it fails, the reply is shown without voice.

## What your relay receives

Only what is listed above: the typed message, the recent typed conversation and the text to speak. Nothing about desktop events, files, screenshots or keystrokes. What the relay does with it, and which model or voice it uses, is up to whoever runs it; document that for the people who use your relay.

## Never in the public build

The public ZIP never contains a `minidraconia_relay.json`. `.gitignore`, the shared asset policy (`full-engine/packaging/asset_policy.py`), the builder (`package_scripted.py`) and `scripts/scan_release.py` all refuse one. Add yours beside your own copy of the executable after the build.
